"""Phase 7A: adapters call production detectors; no logic duplicated."""

from pathlib import Path

from services.validation import adapters


def test_thesis002_adapter_calls_production(monkeypatch):
    calls = {}

    def fake_analyze(text):
        calls["nlp_text"] = text
        return {"sentences": [{"number": 1, "text": text, "start": 0}]}

    def fake_detect(sentences):
        calls["rule_input"] = sentences
        return ([{"rule_id": "THESIS_002", "status": "ISSUE",
                  "sentence_number": 1,
                  "details": {"pattern": "p", "matched_text": "m"},
                  "reason": "r"}], {1: True})

    monkeypatch.setattr(adapters.nlp_service, "analyze_text", fake_analyze)
    monkeypatch.setattr(adapters.meta_rules, "detect_meta_statements", fake_detect)
    out = adapters.predict_thesis002("This essay will discuss crops.")
    assert out["detector_id"] == "THESIS_002"
    assert out["predicted_label"] == "META_STATEMENT"
    assert out["system_positive"] is True
    assert out["ruleset_version"] == "VR-2"
    assert calls["nlp_text"] == "This essay will discuss crops."
    assert calls["rule_input"][0]["number"] == 1


def test_topic_adapter_calls_production(monkeypatch):
    calls = {}

    def fake_analyze(topic, kws, text):
        calls["args"] = (topic, kws, text)
        return {
            "corpus": {}, "tfidf": {"dimensions": 5, "processing_ms": 0.1},
            "cosine": {"raw_similarity": 0.7, "manual_result": 0.7,
                       "difference": 0.0, "match": True,
                       "zero_vector_note": None, "processing_ms": 0.1},
            "classification": {"classification": "STRONG",
                               "comparison": "0.7000 >= 0.60",
                               "threshold_warning": "w",
                               "weak_moderate_boundary": 0.3,
                               "strong_boundary": 0.6,
                               "processing_ms": 0.1},
        }

    monkeypatch.setattr(adapters.similarity, "analyze_topic", fake_analyze)
    out = adapters.predict_topic("student text", "Topic", ["climate"])
    assert out["predicted_label"] == "STRONG"
    assert out["evidence"]["similarity"] == 0.7
    # Production signature is (topic, keywords, text): adapter reorders.
    assert calls["args"] == ("Topic", ["climate"], "student text")


def test_topic_adapter_requires_topic_and_keywords():
    import pytest
    with pytest.raises(ValueError):
        adapters.predict_topic("text", None, ["climate"])
    with pytest.raises(ValueError):
        adapters.predict_topic("text", "Topic", [])


def test_no_duplicated_detector_logic():
    """Adapters must contain no patterns, thresholds, or vectorizer config."""
    src = Path(adapters.__file__).read_text(encoding="utf-8")
    for forbidden in (r"this\s+", "TfidfVectorizer", "re.compile",
                      "0.30", "0.60", "cosine_similarity([", "WordNet(",
                      "synsets", "META_PATTERNS"):
        assert forbidden not in src, forbidden
    # Only production modules are used.
    assert "meta_rules.detect_meta_statements" in src
    assert "analyze_topic" in src
