"""Phase 1B tests: transparency pipeline, backtraces, source-viewer security,
execution events, timing fields, LanguageTool lifecycle, stored replay."""

import importlib

import pytest

from app import create_app
from services import db, grammar_service, source_view, transparency
from services.transparency import RULE_SOURCES, STEP_DEFS

SAMPLE = (
    "This essay will discuss climate change and agriculture. "
    "Climate change have serious effects on farmers. "
    "Farmers experience lower crop production because extreme temperatures affect crops. "
    "Farmers also experience problems because rainfall patterns continue to change."
)


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "db_path", lambda: tmp_path / "test.db")
    application = create_app(prewarm=False)
    application.config.update(TESTING=True)
    return application.test_client()


@pytest.fixture()
def analysis(client):
    return client.post("/api/analyze", json={"text": SAMPLE}).get_json()


# ------------------------------------------------ transparency structure
def test_pipeline_structure_and_required_keys(analysis):
    steps = analysis["transparency"]["pipeline"]
    assert len(steps) == 16
    assert [s["number"] for s in steps] == list(range(1, 17))
    required = {"number", "name", "purpose", "file", "function", "input",
                "process", "output", "timing_ms", "next", "status"}
    for s in steps:
        assert required.issubset(s.keys()), s["id"]
        assert isinstance(s["timing_ms"], (int, float)) and s["timing_ms"] >= 0
    ids = [s["id"] for s in steps]
    for expected in ("raw_input", "normalization", "sentence_segmentation",
                     "tokenization", "lemmatization", "stopword_identification",
                     "pos_tagging", "rule_engine", "languagetool",
                     "keyword_extraction", "wordnet_expansion", "tfidf",
                     "cosine_similarity", "topic_classification",
                     "feedback", "persistence"):
        assert expected in ids
    # Without topic input: keywords still extracted, topic gears NOT_RUN.
    phase2_ids = {"keyword_extraction", "wordnet_expansion", "tfidf",
                  "cosine_similarity", "topic_classification"}
    by_id = {s["id"]: s for s in steps}
    assert by_id["keyword_extraction"]["status"] == "COMPLETE"
    for sid in phase2_ids - {"keyword_extraction"}:
        assert by_id[sid]["status"] == "NOT_RUN"


def test_run_info_versions_are_real(analysis):
    import platform

    import spacy

    ri = analysis["transparency"]["run_info"]
    assert ri["spacy_version"] == spacy.__version__
    assert ri["spacy_model"] == "en_core_web_sm"
    assert ri["python_version"] == platform.python_version()
    assert ri["app_version"] == "1.1.0"
    assert ri["languagetool_status"] in ("available", "unavailable")
    assert ri["total_ms"] > 0


def test_step_source_mapping_points_to_real_code():
    for step in STEP_DEFS:
        assert step["file"] in source_view.WHITELIST, step["id"]
        module = importlib.import_module(source_view.WHITELIST[step["file"]])
        assert hasattr(module, step["function"]), (step["id"], step["function"])
    for rule_id, ref in RULE_SOURCES.items():
        assert ref["file"] in source_view.WHITELIST
        module = importlib.import_module(source_view.WHITELIST[ref["file"]])
        assert hasattr(module, ref["function"]), rule_id


# ------------------------------------------------ source viewer security
def test_source_valid_request_allowed(client):
    res = client.get("/api/source", query_string={"file": "services/nlp_service.py", "function": "analyze_text"})
    assert res.status_code == 200
    body = res.get_json()
    assert body["allowed"] is True
    assert "def analyze_text" in body["source"]
    assert body["start_line"] >= 1 and body["end_line"] >= body["start_line"]


@pytest.mark.parametrize("evil", [
    "../app.py",
    "../../etc/passwd",
    "/etc/passwd",
    "C:\\Windows\\win.ini",
    "..\\..\\secret",
    ".env",
    "essayscaff.db",
    "requirements.txt",
    "totally_unknown.py",
    "",
])
def test_source_non_whitelisted_denied(client, evil):
    res = client.get("/api/source", query_string={"file": evil})
    assert res.status_code in (403, 404)
    assert res.get_json()["allowed"] is False


def test_source_unknown_function_rejected(client):
    res = client.get("/api/source", query_string={"file": "rules/meta_rules.py", "function": "no_such_function"})
    assert res.status_code == 404
    assert res.get_json()["allowed"] is False


# ------------------------------------------------ backtraces
def test_feedback_backtrace_meta_statement(analysis):
    chains = {c["feedback_id"]: c for c in analysis["transparency"]["backtraces"]}
    fb1 = next(c for c in chains.values() if c["source"] == "THESIS_002")
    assert fb1["generated_by"] == "THESIS_002"
    assert fb1["rule_file"] == "rules/meta_rules.py"
    assert fb1["evidence"].lower() == "this essay will"
    assert fb1["char_start"] == 0 and fb1["char_end"] == 15
    assert fb1["sentence"]["number"] == 1
    # Evidence span must slice out of the original text.
    raw = analysis["technical"]["raw_input"]
    assert raw[fb1["char_start"]:fb1["char_end"]].lower() == "this essay will"
    # Related tokens T0..T2 cover the evidence span.
    assert fb1["token_indices"] == [0, 1, 2]
    assert "this essay will" in fb1["original_text"].lower()


def test_every_feedback_has_backtrace(analysis):
    fb_ids = {f["feedback_id"] for f in analysis["feedback"]}
    chain_ids = {c["feedback_id"] for c in analysis["transparency"]["backtraces"]}
    assert fb_ids == chain_ids


def test_token_sentence_trace(analysis):
    tech = analysis["technical"]
    for tok in tech["tokens"]:
        sent = next(s for s in tech["sentences"] if s["number"] == tok["sentence"])
        assert sent["start"] <= tok["start"] < sent["end"]
        assert tech["raw_input"][tok["start"]:tok["end"]] == tok["text"]
    detail = transparency.token_detail(tech["tokens"], 4, tech["sentences"], tech["raw_input"], "en_core_web_sm")
    assert detail["surface"] == "climate"  # T4 of the manual sample text
    assert tech["raw_input"][detail["char_start"]:detail["char_end"]] == "climate"
    assert detail["sentence"]["number"] == 1
    assert detail["processed_in"] == "services/nlp_service.py :: analyze_text"
    assert "spaCy" in detail["produced_by"]
    assert transparency.token_detail(tech["tokens"], 99999, tech["sentences"], tech["raw_input"], "m") is None


# ------------------------------------------------ events + timings
def test_execution_log_ordered_and_complete(analysis):
    log = analysis["transparency"]["execution_log"]
    assert log[0]["event"] == "analysis started" and log[0]["t_ms"] == 0.0
    assert log[-1]["event"] == "response completed"
    times = [e["t_ms"] for e in log]
    assert all(b >= a for a, b in zip(times, times[1:])), "events must be chronological"
    names = " | ".join(e["event"] for e in log)
    for required in ("rule engine started", "THESIS_002 completed",
                     "LanguageTool completed", "feedback constructed",
                     "database persistence completed"):
        assert required in names


def test_tokenization_event_present_and_ordered(analysis):
    log = analysis["transparency"]["execution_log"]
    names = [e["event"] for e in log]
    tok_idx = next(i for i, n in enumerate(names) if n.startswith("tokenization completed"))
    assert f"({len(analysis['technical']['tokens'])} tokens)" in names[tok_idx]
    assert names.index("sentence segmentation captured") < tok_idx
    assert tok_idx < names.index("rule engine started")
    times = [e["t_ms"] for e in log]
    assert all(b >= a for a, b in zip(times, times[1:])), "events must be chronological"


def test_timing_fields_present_and_measured(analysis):
    timings = analysis["technical"]["timings"]
    for key in ("validation_ms", "normalization_ms", "spacy_total_ms",
                "sentence_capture_ms", "token_property_capture_ms", "rules_ms",
                "language_tool_ms", "feedback_ms", "database_ms", "total_ms"):
        assert key in timings, key
        assert isinstance(timings[key], (int, float)), (key, timings[key])
        assert timings[key] >= 0, (key, timings[key])
    assert timings["total_ms"] > 0
    assert timings["database_ms"] > 0  # honestly measured, patched post-save


def test_languagetool_cold_warm_split_fields(analysis):
    lt = analysis["technical"]["language_tool_results"]
    assert "init_ms" in lt and "check_ms" in lt and "cold_init_in_this_call" in lt
    assert lt["status"] in ("available", "unavailable")
    if lt["status"] == "available":
        assert lt["check_ms"] is not None and lt["check_ms"] >= 0


# ------------------------------------------------ lifecycle + replay
def test_languagetool_instance_reused():
    grammar_service._get_tool()
    first = grammar_service._tool
    assert first is not None
    grammar_service.check_grammar("Farmers adapt.", [])
    grammar_service.check_grammar("Farmers adapt quickly.", [])
    assert grammar_service._tool is first
    stats = grammar_service.get_stats()
    assert stats["initialized"] is True
    assert stats["check_count"] >= 2


def test_languagetool_unavailable_fallback_is_honest(monkeypatch):
    import language_tool_python

    monkeypatch.setattr(grammar_service, "_tool", None)
    monkeypatch.setattr(
        language_tool_python, "LanguageTool",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom-no-java")),
    )
    out = grammar_service.check_grammar("Some text here.", [])
    assert out["status"] == "unavailable"
    assert "boom-no-java" in out["error"]
    assert out["issues"] == []
    # Restore real singleton for the rest of the suite.
    monkeypatch.undo()
    grammar_service._tool = None
    grammar_service._tool_error = None
    assert grammar_service._get_tool() is not None


def test_stored_analysis_replay(client, analysis):
    again = client.get(f"/api/analysis/{analysis['analysis_id']}").get_json()
    assert again["id"] == analysis["analysis_id"]
    assert again["transparency"]["pipeline"] == analysis["transparency"]["pipeline"]
    assert again["transparency"]["execution_log"] == analysis["transparency"]["execution_log"]
    assert again["transparency"]["backtraces"] == analysis["transparency"]["backtraces"]
    assert again["transparency"]["historical_code_warning"] is True


def test_legacy_run_without_transparency_reports_not_recorded(client, tmp_path):
    import json
    import sqlite3

    db.init_db()
    conn = sqlite3.connect(db.db_path())
    conn.execute(
        "INSERT OR REPLACE INTO analysis_runs (id, raw_text, normalized_text, stage,"
        " created_at, processing_ms, summary_json, feedback_json, technical_json,"
        " transparency_json) VALUES (?,?,?,?,?,?,?,?,?,?)",
        ("RUN-20000101-000001", "Old text.", "Old text.", None, "2000-01-01",
         1.0, json.dumps({}), json.dumps([]), json.dumps({}), None),
    )
    conn.commit()
    conn.close()
    rec = client.get("/api/analysis/RUN-20000101-000001").get_json()
    assert rec["transparency"]["pipeline"] == []
    assert "not recorded" in str(rec["transparency"]["run_info"])
