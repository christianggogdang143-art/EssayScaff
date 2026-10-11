"""Phase 7A production detector adapters.

WHAT WE VALIDATE = WHAT STUDENTS ACTUALLY USE.

Each adapter calls the SAME production functions as the student
pipeline. No detector logic (patterns, thresholds, TF-IDF settings)
is duplicated here: this module contains no patterns, no thresholds,
no vectorizer configuration.

- THESIS_002: services.nlp_service.analyze_text -> rules.meta_rules
  .detect_meta_statements (identical call sequence to services/stage2.py).
- TOPIC_CLASSIFIER: services.similarity.analyze_topic (the full
  production topic pipeline: corpus -> TF-IDF -> cosine -> classify).
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

import config
from services import nlp_service, similarity
from services.validation import protocols
from services.validation import snapshot as snapshot_mod
from rules import meta_rules


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _base_record(detector_id: str, processing_ms: float) -> dict:
    return {
        "detector_id": detector_id,
        "ruleset_version": config.VALIDATION_RULESET_VERSION,
        "config_hash": snapshot_mod.config_hash(),
        "predicted_at": _now(),
        "processing_ms": processing_ms,
    }


def predict_thesis002(raw_text: str) -> dict:
    """Run the frozen production THESIS_002 detector on one sample.

    Positive = the production rule fired (status ISSUE) on any sentence.
    """
    t0 = time.perf_counter()
    sentences = nlp_service.analyze_text(raw_text)["sentences"]
    rule_results, _by_sentence = meta_rules.detect_meta_statements(sentences)
    fired = [r for r in rule_results if r.get("status") == "ISSUE"]
    spec = protocols.DETECTORS["THESIS_002"]
    record = _base_record("THESIS_002", (time.perf_counter() - t0) * 1000.0)
    record.update({
        "system_positive": bool(fired),
        "predicted_label": spec["system_positive"] if fired else spec["system_negative"],
        "raw_detector_output": {
            "fired_count": len(fired),
            "sentence_count": len(sentences),
        },
        "evidence": [
            {
                "sentence_number": r.get("sentence_number"),
                "pattern": (r.get("details") or {}).get("pattern"),
                "matched_text": (r.get("details") or {}).get("matched_text"),
                "reason": r.get("reason"),
            }
            for r in fired
        ],
    })
    return record


def predict_topic(raw_text: str, topic: str | None,
                  teacher_keywords: list[str] | None) -> dict:
    """Run the frozen production topic pipeline on one sample."""
    if not topic or not (teacher_keywords or []):
        raise ValueError(
            "TOPIC_CLASSIFIER samples require an assignment topic and "
            "teacher keywords.")
    t0 = time.perf_counter()
    bundle = similarity.analyze_topic(topic, teacher_keywords, raw_text)
    record = _base_record("TOPIC_CLASSIFIER", (time.perf_counter() - t0) * 1000.0)
    cls = bundle["classification"]
    cos = bundle["cosine"]
    record.update({
        "system_positive": None,
        "predicted_label": cls["classification"],
        "raw_detector_output": {
            "similarity": cos["raw_similarity"],
            "comparison": cls["comparison"],
            "threshold_warning": cls["threshold_warning"],
            "manual_result": cos["manual_result"],
            "manual_library_difference": cos["difference"],
            "manual_library_match": cos["match"],
            "zero_vector_note": cos["zero_vector_note"],
            "tfidf_dimensions": bundle["tfidf"]["dimensions"],
        },
        "evidence": {
            "similarity": cos["raw_similarity"],
            "comparison": cls["comparison"],
            "weak_moderate_boundary": cls["weak_moderate_boundary"],
            "strong_boundary": cls["strong_boundary"],
            "direct_matches": (bundle["corpus"].get("direct_matches")
                               if isinstance(bundle.get("corpus"), dict) else None),
        },
    })
    return record


def predict(detector_id: str, sample: dict) -> dict:
    """Dispatch to the production adapter for one validation sample."""
    if detector_id == "THESIS_002":
        return predict_thesis002(sample["raw_text"])
    if detector_id == "TOPIC_CLASSIFIER":
        return predict_topic(
            sample["raw_text"], sample.get("topic"),
            sample.get("teacher_keywords") or [])
    raise ValueError(f"Pilot scope covers THESIS_002 and TOPIC_CLASSIFIER only.")
