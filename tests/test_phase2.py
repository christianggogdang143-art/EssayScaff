"""Phase 2 tests: keywords, WordNet, TF-IDF, cosine, classification,
topic feedback, persistence, replay, and input validation."""

import math

import pytest

import config
from app import create_app
from services import db, keywords, similarity, wordnet_service
from services.keywords import keyword_score

TOPIC = "Effects of climate change on agriculture"
TEACHER_KW = ["climate", "agriculture", "farmers", "crop", "temperature", "rainfall"]
TEXT_A = (
    "This essay will discuss climate change and agriculture. "
    "Climate change has serious effects on farmers. "
    "Extreme temperatures can reduce crop production, "
    "and irregular rainfall can affect planting schedules."
)
TEXT_B = (
    "Online video games allow players to communicate with friends across different countries. "
    "Competitive games also require teamwork and quick decision making."
)
TEXT_C = (
    "Farming communities increasingly face changing weather conditions. "
    "Growers may experience lower harvests when heat and unpredictable precipitation affect cultivation."
)


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "db_path", lambda: tmp_path / "test.db")
    application = create_app(prewarm=False)
    application.config.update(TESTING=True)
    return application.test_client()


def _analyze(client, text, topic=TOPIC, kws=TEACHER_KW):
    payload = {"text": text}
    if topic is not None:
        payload["topic"] = topic
    if kws is not None:
        payload["teacher_keywords"] = kws
    return client.post("/api/analyze", json=payload)


def _tokens_of(text):
    from services import nlp_service

    out = nlp_service.analyze_text(text)
    return out["tokens"], len(out["sentences"])


# ------------------------------------------------ keywords
def test_keyword_candidates_from_real_tokens():
    tokens, n_sent = _tokens_of(TEXT_A)
    out = keywords.extract_candidates(tokens, n_sent)
    by_lemma = {t["lemma"]: t for t in out["terms"]}
    assert by_lemma["climate"]["candidate"] is True
    assert by_lemma["climate"]["pos"] in ("NOUN", "PROPN")
    # Punctuation never becomes a row; stopword determiners rejected.
    assert "." not in by_lemma
    assert all(t["candidate_reason"] for t in out["terms"] if not t["candidate"])
    assert all(t["score"] > 0 for t in out["terms"] if t["candidate"])
    assert "score = " in out["formula"]


def test_keyword_ranking_deterministic():
    tokens, n_sent = _tokens_of(TEXT_A)
    first = keywords.extract_candidates(tokens, n_sent)
    second = keywords.extract_candidates(tokens, n_sent)
    assert first["terms"] == second["terms"]
    assert first["selected"] == second["selected"]
    # Ranks are 1..k without gaps; selection is top-N.
    ranks = sorted(t["rank"] for t in first["terms"] if t["candidate"])
    assert len(ranks) > 0
    assert ranks == list(range(1, len(ranks) + 1))
    assert len(first["selected"]) <= 15
    assert set(first["selected"]) <= {t["lemma"] for t in first["terms"] if t["candidate"]}


def test_keyword_score_formula_exact():
    assert keyword_score(2, "NOUN", 1, 4) == pytest.approx(math.log(3) + 2.0 + 0.25)
    assert keyword_score(0, "VERB", 0, 4) == pytest.approx(0.0 + 1.0 + 0.0)


def test_query_terms_keep_provenance():
    terms = keywords.build_query_terms(TOPIC, TEACHER_KW)
    kinds = {t["kind"] for t in terms}
    assert {"TEACHER_KEYWORD", "TOPIC_TERM"} <= kinds
    teacher = [t for t in terms if t["kind"] == "TEACHER_KEYWORD"]
    assert {t["original"] for t in teacher} == set(TEACHER_KW)
    assert all(t["lemmas"] for t in teacher)


# ------------------------------------------------ wordnet + matching
def test_direct_and_lemma_matches():
    tokens, _ = _tokens_of(TEXT_A)
    student_lemmas = {(t.get("lemma") or t["text"]).lower() for t in tokens if t.get("is_alpha")}
    student_surfaces = {t["text"].lower() for t in tokens if t.get("is_alpha")}
    out = wordnet_service.analyze_terms(keywords.build_query_terms(TOPIC, TEACHER_KW), student_lemmas, student_surfaces)
    by_orig = {}
    for t in out["terms"]:
        by_orig.setdefault((t["kind"], t["original_term"]), t)
    assert by_orig[("TEACHER_KEYWORD", "rainfall")]["match_type"] == "DIRECT"
    assert by_orig[("TEACHER_KEYWORD", "temperature")]["match_type"] == "LEMMA"  # temperatures -> temperature
    assert out["direct_count"] + out["lemma_count"] + out["wordnet_count"] + out["no_match_count"] == len(out["terms"])


def test_wordnet_lookup_real_and_filtered():
    exp = wordnet_service.expand_term("agriculture", "agriculture", "NOUN", {"agriculture"})
    assert exp["status"] == "ok"
    assert exp["synset_count"] > 0
    assert all("definition" in s and s["definition"] for s in exp["synsets"])
    assert len(exp["retained"]) == len(set(exp["retained"]))  # deduplicated
    assert all(" " not in t and t == t.lower() for t in exp["retained"])
    assert all(c["rejection_reason"] for c in exp["candidates"] if not c["retained"])
    assert "nltk_version" not in exp  # version lives on analyze_terms level


def test_wordnet_analyze_reports_library_version():
    out = wordnet_service.analyze_terms([], set(), set())
    assert out["library"] == "NLTK WordNet"
    import nltk

    assert out["nltk_version"] == nltk.__version__


def test_wordnet_unavailable_handled_honestly(monkeypatch):
    from nltk.corpus import wordnet as wn

    def _boom(*a, **k):
        raise LookupError("missing-data")

    monkeypatch.setattr(wn, "synsets", _boom)
    exp = wordnet_service.expand_term("crop", "crop", "NOUN", set())
    assert exp["status"] == "unavailable"
    assert "LookupError" in exp["error"]


# ------------------------------------------------ tf-idf + cosine
def test_tfidf_vocabulary_and_dimensions():
    vec = similarity.vectorize("climate change agriculture", "climate farmers crop")
    assert vec["dimensions"] == vec["vocabulary_size"] > 0
    assert len(vec["topic_vector"]) == vec["dimensions"] == len(vec["student_vector"])
    assert set(vec["vocabulary"]) == set(vec["idf"].keys())
    assert vec["library"] == "scikit-learn"


def test_zero_overlap_similarity():
    vec = similarity.vectorize("alpha beta gamma", "delta epsilon zeta")
    cos = similarity.cosine_similarity(vec["topic_vector"], vec["student_vector"])
    assert cos["raw_similarity"] == 0.0
    assert cos["match"] is True
    # Genuine orthogonality (both vectors non-zero, no shared terms): the
    # independent manual computation agrees, and no defined-zero policy was
    # invoked to reach 0.0.
    assert cos["manual_result"] == 0.0
    assert cos["zero_vector_note"] is None


def test_identical_text_similarity():
    vec = similarity.vectorize("climate change farmers", "climate change farmers")
    cos = similarity.cosine_similarity(vec["topic_vector"], vec["student_vector"])
    assert cos["raw_similarity"] == pytest.approx(1.0)
    assert cos["match"] is True


def test_manual_cosine_reproduces_library():
    import math

    # Hand-computed expectations, independent of both implementations.
    assert similarity.cosine_similarity([1, 0], [0, 1])["raw_similarity"] == pytest.approx(0.0)
    assert similarity.cosine_similarity([3, 4], [3, 4])["raw_similarity"] == pytest.approx(1.0)
    assert similarity.cosine_similarity([1, 0], [1, 1])["raw_similarity"] == pytest.approx(1 / math.sqrt(2))
    vecs = [
        ([0.5, 0.0, 0.25], [0.5, 0.5, 0.0]),
        ([0.0, 0.0], [0.3, 0.4]),
        ([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]),
    ]
    for a, b in vecs:
        cos = similarity.cosine_similarity(a, b)
        assert cos["difference"] <= 1e-9
        assert cos["match"] is True


# ------------------------------------------------ classification
@pytest.mark.parametrize(
    "sim,expected",
    [(0.0, "WEAK"), (0.29, "WEAK"), (0.30, "MODERATE"), (0.45, "MODERATE"), (0.599, "MODERATE"), (0.60, "STRONG"), (1.0, "STRONG")],
)
def test_classification_thresholds_and_boundaries(sim, expected):
    cls = similarity.classify(sim)
    assert cls["classification"] == expected
    assert f"{sim:.4f}" in cls["comparison"]
    assert cls["weak_moderate_boundary"] == config.TOPIC_MODERATE_THRESHOLD
    assert cls["strong_boundary"] == config.TOPIC_STRONG_THRESHOLD
    assert "PENDING EMPIRICAL" in cls["threshold_warning"]
    assert similarity.predict_relevance(sim) == expected


# ------------------------------------------------ api + feedback
def test_topic_pipeline_end_to_end(client):
    data = _analyze(client, TEXT_A).get_json()
    assert data["technical"]["phase2"]["ran"] is True
    cos = data["technical"]["phase2"]["topic_analysis"]["cosine"]
    assert cos["match"] is True
    fb = [f for f in data["feedback"] if f["source"] == "TOPIC_CLASSIFIER"]
    assert len(fb) == 1
    assert fb[0]["details"]["direct_matches"]
    assert fb[0]["category"] == "Topic"
    assert "Write this instead" not in fb[0]["suggestion"]
    chains = {c["feedback_id"]: c for c in data["transparency"]["backtraces"]}
    assert chains[fb[0]["feedback_id"]]["topic_chain"]["classification"] == data["summary"]["topic_classification"]


def test_weak_topic_feedback_names_missing(client):
    data = _analyze(client, TEXT_B).get_json()
    fb = [f for f in data["feedback"] if f["source"] == "TOPIC_CLASSIFIER"][0]
    assert fb["severity"] == "warning"
    assert fb["title"] == "Topic connection: WEAK"
    assert "mechanically" in fb["suggestion"] and "own words" in fb["suggestion"]


def test_missing_topic_skips_pipeline(client):
    data = _analyze(client, TEXT_A, topic=None, kws=None).get_json()
    assert data["technical"]["phase2"]["ran"] is False
    assert not [f for f in data["feedback"] if f["source"] == "TOPIC_CLASSIFIER"]
    assert data["summary"]["topic_classification"] is None
    by_id = {s["id"]: s for s in data["transparency"]["pipeline"]}
    assert by_id["keyword_extraction"]["status"] == "COMPLETE"
    assert by_id["topic_classification"]["status"] == "NOT_RUN"


def test_topic_without_teacher_keywords_runs(client):
    data = _analyze(client, TEXT_A, kws=None).get_json()
    assert data["technical"]["phase2"]["ran"] is True


def test_invalid_topic_inputs_rejected(client):
    assert client.post("/api/analyze", json={"text": "hello world today", "topic": 123}).status_code == 400
    assert client.post("/api/analyze", json={"text": "hello world today", "teacher_keywords": "climate"}).status_code == 400
    assert client.post("/api/analyze", json={"text": "hello world today", "teacher_keywords": ["ok", 5]}).status_code == 400
    assert client.post("/api/analyze", json={"text": "hello world today", "topic": "x" * 501}).status_code == 413
    assert client.post("/api/analyze", json={"text": "hello world today", "teacher_keywords": ["k"] * 51}).status_code == 413


# ------------------------------------------------ persistence + replay
def test_phase2_persistence_and_replay(client):
    created = _analyze(client, TEXT_A).get_json()
    again = client.get(f"/api/analysis/{created['analysis_id']}").get_json()
    assert again["technical"]["phase2"] == created["technical"]["phase2"]
    assert again["transparency"]["pipeline"] == created["transparency"]["pipeline"]
    assert again["summary"]["topic_similarity"] == created["summary"]["topic_similarity"]


def test_phase1b_record_replays_without_phase2(client):
    created = _analyze(client, TEXT_A, topic=None, kws=None).get_json()
    again = client.get(f"/api/analysis/{created['analysis_id']}").get_json()
    assert again["technical"]["phase2"]["ran"] is False
    assert [s["id"] for s in again["transparency"]["pipeline"]] == [
        "raw_input", "normalization", "sentence_segmentation", "tokenization",
        "lemmatization", "stopword_identification", "pos_tagging", "rule_engine",
        "languagetool", "keyword_extraction", "wordnet_expansion", "tfidf",
        "cosine_similarity", "topic_classification", "feedback", "persistence",
    ]


def test_new_source_files_whitelisted(client):
    for file, func in [
        ("services/keywords.py", "extract_candidates"),
        ("services/wordnet_service.py", "analyze_terms"),
        ("services/similarity.py", "cosine_similarity"),
    ]:
        res = client.get("/api/source", query_string={"file": file, "function": func})
        assert res.status_code == 200, file
        assert f"def {func}" in res.get_json()["source"]
