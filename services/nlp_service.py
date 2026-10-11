"""Core spaCy NLP pipeline for EssayScaff Phase 1.

Pipeline stages (all real, measured, traceable):
  raw text -> normalization (conservative copy) -> spaCy parse on the
  ORIGINAL text (so character offsets stay exact) -> sentences -> tokens
  (text/lemma/POS/tag/stopword/punct/alpha + offsets + sentence number).

Never fabricate: every value comes from the actual spaCy Doc.
Never mutate the student's original text.
"""

from __future__ import annotations

import time
import unicodedata

import spacy

import config

_nlp = None
_nlp_model_name = None


def get_nlp():
    """Load (once) and return the spaCy pipeline + resolved model name."""
    global _nlp, _nlp_model_name
    if _nlp is None:
        _nlp = spacy.load(config.SPACY_MODEL)
        _nlp_model_name = config.SPACY_MODEL
    return _nlp


def get_model_name() -> str:
    get_nlp()
    return _nlp_model_name or config.SPACY_MODEL


def normalize_text(raw: str) -> dict:
    """Conservative normalization.

    The student's original text is preserved untouched. We return a
    separate analysis copy with only: unicode NFC + CRLF/CR -> LF.
    We do NOT strip/insert/delete characters beyond that, so offsets
    computed on the raw text remain valid.
    """
    t0 = time.perf_counter()
    normalized = unicodedata.normalize("NFC", raw.replace("\r\n", "\n").replace("\r", "\n"))
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    return {
        "normalized": normalized,
        "chars_before": len(raw),
        "chars_after": len(normalized),
        "processing_ms": elapsed_ms,
    }


def analyze_text(raw_text: str) -> dict:
    """Run the full spaCy pipeline on the ORIGINAL text.

    Returns dict with: normalized_input, sentences, tokens, timings, spacy_model.
    Sentence/token offsets are character offsets into the original text.
    """
    timings: dict[str, float] = {}

    t0 = time.perf_counter()
    norm = normalize_text(raw_text)
    timings["normalization_ms"] = (time.perf_counter() - t0) * 1000.0

    nlp = get_nlp()

    t0 = time.perf_counter()
    # Parse the ORIGINAL text so offsets match what the student typed.
    doc = nlp(raw_text.replace("\r\n", "\n").replace("\r", "\n"))
    timings["spacy_parse_ms"] = (time.perf_counter() - t0) * 1000.0

    t0 = time.perf_counter()
    sentences = []
    for i, sent in enumerate(doc.sents, start=1):
        sentences.append(
            {
                "number": i,
                "text": sent.text,
                "start": sent.start_char,
                "end": sent.end_char,
            }
        )
    timings["segmentation_ms"] = (time.perf_counter() - t0) * 1000.0

    t0 = time.perf_counter()
    # Map each token to its sentence number via token.sent.start.
    sent_number_by_token_start: dict[int, int] = {}
    for s in doc.sents:
        num = next(n["number"] for n in sentences if n["start"] == s.start_char)
        for tok in s:
            sent_number_by_token_start[tok.i] = num

    tokens = []
    for tok in doc:
        tokens.append(
            {
                "index": tok.i,
                "text": tok.text,
                "lemma": tok.lemma_,
                "pos": tok.pos_,
                "tag": tok.tag_,
                "dep": tok.dep_,
                "is_stopword": bool(tok.is_stop),
                "is_punctuation": bool(tok.is_punct),
                "is_alpha": bool(tok.is_alpha),
                "sentence": sent_number_by_token_start.get(tok.i),
                "start": tok.idx,
                "end": tok.idx + len(tok.text),
            }
        )
    timings["tokenization_ms"] = (time.perf_counter() - t0) * 1000.0
    # Lemmatization / stopword / POS tagging all come from the same spaCy
    # parse above; record ~0 extra ms honestly rather than inventing numbers.
    timings["lemmatization_ms"] = 0.0
    timings["stopword_ms"] = 0.0
    timings["pos_tagging_ms"] = 0.0

    try:
        from importlib import metadata as _metadata

        _model_version = _metadata.version("en-core-web-sm")
    except Exception:  # noqa: BLE001 - version reporting must never break NLP
        _model_version = "unknown"

    return {
        "normalized_input": norm["normalized"],
        "chars_before": norm["chars_before"],
        "chars_after": norm["chars_after"],
        "sentences": sentences,
        "tokens": tokens,
        "spacy_doc": doc,
        "spacy_model": get_model_name(),
        "spacy_version": __import__("spacy").__version__,
        "spacy_model_version": _model_version,
        "timings": timings,
    }
