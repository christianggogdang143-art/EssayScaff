"""Tests for the six EssayScaff heuristic rules. Each rule is called as an
isolated function (confusion-matrix-ready design)."""

from rules import mechanics_rules, style_rules, thesis_rules
from rules.meta_rules import detect_meta_statements
from rules.rule_engine import run_all_rules
from services import nlp_service


def _parse(text):
    out = nlp_service.analyze_text(text)
    return out["spacy_doc"], out["sentences"]


def test_meta_statement_rule_detects_required_patterns():
    doc, sents = _parse("This essay will discuss climate change. Farmers adapt.")
    results, by_sent = detect_meta_statements(sents)
    assert by_sent[1] is True
    assert by_sent[2] is False
    hit = [r for r in results if r["rule_id"] == "THESIS_002"]
    assert len(hit) == 1
    assert hit[0]["evidence"].lower() == "this essay will"
    raw = "This essay will discuss climate change. Farmers adapt."
    assert raw[hit[0]["start"] : hit[0]["end"]].lower() == "this essay will"
    assert hit[0]["sentence_number"] == 1


def test_meta_statement_case_insensitive_and_variants():
    doc, sents = _parse("In this PAPER we study soils. Results follow.")
    results, by_sent = detect_meta_statements(sents)
    assert by_sent[1] is True
    assert any(r["details"]["pattern"] == r"in\s+this\s+paper" for r in results)


def test_thesis_candidate_heuristic():
    doc, sents = _parse(
        "This essay will discuss climate change. "
        "Climate change threatens smallholder farmers most severely."
    )
    _, by_sent = detect_meta_statements(sents)
    out = thesis_rules.detect_thesis_candidates(doc, sents, by_sent)
    first = [r for r in out if r["sentence_number"] == 1][0]
    second = [r for r in out if r["sentence_number"] == 2][0]
    assert first["status"] == "NOT_CANDIDATE"  # meta-statement rejected
    assert second["status"] == "CANDIDATE"
    assert second["details"]["main_verb_detected"]
    assert second["details"]["subject_available"] is True
    assert second["details"]["is_declarative"] is True


def test_passive_voice_uses_dependency_evidence():
    doc, sents = _parse("The experiment was conducted by the team. The team analyzed data.")
    results = style_rules.detect_passive_voice(doc, sents)
    flagged = {r["sentence_number"] for r in results}
    assert 1 in flagged
    assert 2 not in flagged  # guards against naive 'was' matching
    assert results[0]["rule_id"] == "STYLE_001"


def test_passive_voice_avoids_was_false_positive():
    doc, sents = _parse("The weather was pleasant yesterday.")
    results = style_rules.detect_passive_voice(doc, sents)
    assert results == []


def test_repeated_sentence_opening():
    doc, sents = _parse("The student reads. The student writes. The student revises. Others observe.")
    results = style_rules.detect_repeated_openings(sents)
    assert len(results) == 1
    assert results[0]["rule_id"] == "STYLE_002"
    assert results[0]["details"]["count"] == 3
    assert results[0]["details"]["affected_sentences"] == [1, 2, 3]


def test_fragment_heuristic_conservative():
    doc, sents = _parse("Because he ran. He ran quickly to the farm today.")
    results = mechanics_rules.detect_fragments(doc, sents)
    flagged = {r["sentence_number"] for r in results}
    assert 1 in flagged
    assert 2 not in flagged
    assert "POSSIBLE" in results[0]["reason"].upper()


def test_runon_heuristic():
    long_sentence = (
        "Farmers plant crops in the spring and they harvest them in the autumn and they sell "
        "them at the market and they save the profits for the winter and they prepare the soil again"
    )
    doc, sents = _parse(long_sentence + ". Short sentence here.")
    results = mechanics_rules.detect_runons(doc, sents)
    flagged = {r["sentence_number"] for r in results}
    assert 1 in flagged
    assert 2 not in flagged


def test_rule_engine_runs_all_six():
    doc, sents = _parse(
        "This essay will discuss climate change and agriculture. "
        "Climate change have serious effects on farmers."
    )
    out = run_all_rules(doc, sents)
    assert set(out["timings"].keys()) == {
        "THESIS_001_ms", "THESIS_002_ms", "STYLE_001_ms",
        "STYLE_002_ms", "MECHANICS_001_ms", "MECHANICS_002_ms",
    }
    ids = {r["rule_id"] for r in out["results"]}
    assert "THESIS_001" in ids and "THESIS_002" in ids
