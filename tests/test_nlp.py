"""Tests for the real spaCy NLP pipeline: segmentation, tokens, offsets,
lemmas, stopwords, POS. All values asserted against actual library output
properties, never hardcoded full outputs.
"""

from services import nlp_service

SAMPLE = (
    "This essay will discuss climate change and agriculture. "
    "Climate change have serious effects on farmers. "
    "Farmers experience lower crop production because extreme temperatures affect crops. "
    "Farmers also experience problems because rainfall patterns continue to change."
)


def test_sentence_segmentation_counts_and_offsets():
    out = nlp_service.analyze_text(SAMPLE)
    sents = out["sentences"]
    assert len(sents) == 4
    # Offsets must slice back the exact sentence text from the raw input.
    raw = SAMPLE.replace("\r\n", "\n")
    for s in sents:
        assert raw[s["start"] : s["end"]] == s["text"]
    # Sentences must be contiguous and ordered.
    for a, b in zip(sents, sents[1:]):
        assert a["end"] <= b["start"]
    assert sents[0]["start"] == 0


def test_tokenization_exposes_everything_with_offsets():
    out = nlp_service.analyze_text(SAMPLE)
    raw = SAMPLE.replace("\r\n", "\n")
    toks = out["tokens"]
    assert len(toks) > 20
    required = {"index", "text", "lemma", "pos", "tag", "is_stopword",
                "is_punctuation", "is_alpha", "sentence", "start", "end"}
    for t in toks:
        assert required.issubset(t.keys())
        assert raw[t["start"] : t["end"]] == t["text"]
        assert isinstance(t["is_stopword"], bool)


def test_lemmatization_preserves_surface_form():
    out = nlp_service.analyze_text("Temperatures affect crops.")
    by_text = {t["text"]: t for t in out["tokens"]}
    assert by_text["affect"]["lemma"] == "affect"
    assert by_text["Temperatures"]["lemma"].lower() == "temperature"
    # Surface form preserved, lemma stored separately.
    assert by_text["affect"]["text"] == "affect"


def test_stopword_flags_visible():
    out = nlp_service.analyze_text("This is a test of stopwords.")
    flags = {t["text"].lower(): t["is_stopword"] for t in out["tokens"]}
    assert flags["this"] is True
    assert flags["is"] is True
    # Content words are not stopwords; nothing is deleted from the trace.
    assert flags["test"] is False
    # Exact token stream for the fixed input: nothing added, nothing dropped.
    assert [t["text"] for t in out["tokens"]] == [
        "This", "is", "a", "test", "of", "stopwords", ".",
    ]


def test_pos_tags_are_real_spacy_output():
    out = nlp_service.analyze_text("Farmers experience problems.")
    by_text = {t["text"]: t for t in out["tokens"]}
    assert by_text["Farmers"]["pos"] == "NOUN"
    assert by_text["experience"]["pos"] == "VERB"
    assert by_text["."  ]["pos"] == "PUNCT"
    assert all(t["tag"] for t in out["tokens"] if t["is_alpha"])


def test_normalization_is_conservative():
    raw = "Hello  world.\r\nSecond line."
    out = nlp_service.analyze_text(raw)
    assert out["chars_before"] == len(raw)
    assert "\r" not in out["normalized_input"]
    # Offsets still valid against the newline-unified text.
    unified = raw.replace("\r\n", "\n")
    for s in out["sentences"]:
        assert unified[s["start"] : s["end"]] == s["text"]
