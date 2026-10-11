"""Phase 7A human annotation model.

Independence rule: the human label is NEVER derived from system output.
The annotation (blinded) view exposes no prediction fields; predictions
are produced only at run time, after dataset freeze.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timezone

from services.validation import datasets as datasets_mod
from services.validation import protocols, store

UNCLEAR = "UNCLEAR"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _allowed_labels(detector_id: str) -> list[str]:
    return datasets_mod._detector(detector_id)["labels"] + [UNCLEAR]


def annotate(sample_id: str, detector_id: str, annotator_id: str,
             human_label: str, confidence: str | None = None,
             notes: str = "") -> dict:
    """Record one primary human annotation (blinded; no system output seen)."""
    sample = store.get_one("validation_samples", sample_id)
    if sample is None:
        raise datasets_mod.ValidationError(f"Sample '{sample_id}' not found.")
    parent = store.get_one("validation_datasets", sample["dataset_id"])
    if parent is None:
        raise datasets_mod.ValidationError("Parent dataset not found.")
    if parent["status"] not in ("DRAFT", "ANNOTATING"):
        raise datasets_mod.ValidationError(
            f"Dataset is {parent['status']}: labels are frozen. "
            "Use adjudication for corrections, never silent edits."
        )
    if detector_id != parent["detector_id"]:
        raise datasets_mod.ValidationError(
            f"Detector mismatch: dataset targets {parent['detector_id']}."
        )
    if not isinstance(annotator_id, str) or not annotator_id.strip():
        raise datasets_mod.ValidationError("'annotator_id' is required.")
    if human_label not in _allowed_labels(detector_id):
        raise datasets_mod.ValidationError(
            f"Invalid label '{human_label}'. Allowed: {_allowed_labels(detector_id)}. "
            "Unknown labels are rejected, never coerced."
        )
    existing = store.list_where(
        "validation_annotations",
        "sample_id = ? AND annotator_id = ? AND adjudicated_label IS NULL",
        (sample_id, annotator_id.strip()),
    )
    if existing:
        raise datasets_mod.ValidationError(
            "This annotator already labeled this sample. "
            "Post-freeze corrections require adjudication."
        )
    spec = datasets_mod._detector(detector_id)
    record = {
        "id": f"VANN-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{secrets.token_hex(3).upper()}",
        "sample_id": sample_id,
        "dataset_id": sample["dataset_id"],
        "detector_id": detector_id,
        "annotator_id": annotator_id.strip(),
        "human_label": human_label,
        "confidence": confidence,
        "notes": notes or "",
        "annotated_at": _now(),
        "adjudicated_label": None,
        "adjudication_notes": None,
        "adjudicated_at": None,
        "protocol_version": spec["protocol_version"],
    }
    store.insert("validation_annotations", record)
    return dict(record)


def latest_annotation(sample_id: str) -> dict | None:
    rows = store.list_where(
        "validation_annotations", "sample_id = ?", (sample_id,))
    if not rows:
        return None
    return sorted(rows, key=lambda r: r["annotated_at"])[-1]


def effective_label(annotation: dict | None) -> tuple[str | None, str | None]:
    """Return (label, how). UNCLEAR (unadjudicated) -> (None, 'excluded-unclear')."""
    if annotation is None:
        return None, "missing-annotation"
    label = annotation.get("adjudicated_label") or annotation.get("human_label")
    if label == UNCLEAR:
        return None, "excluded-unclear"
    return label, "adjudicated" if annotation.get("adjudicated_label") else "primary"


def adjudicate(sample_id: str, adjudicated_label: str,
               adjudication_notes: str) -> dict:
    """Adjudication during DRAFT/ANNOTATING. Never overwrites the human label.

    FROZEN/EVALUATED datasets refuse adjudication: mutating ground truth
    after freeze would invalidate the dataset hash and split live state
    from stored metrics. To correct a frozen dataset, create a NEW dataset
    (e.g. via dataset CSV export followed by CSV import with corrected
    labels) and freeze/run that instead; the frozen original stays intact
    for audit.
    """
    ann = latest_annotation(sample_id)
    if ann is None:
        raise datasets_mod.ValidationError(
            f"No annotation exists for sample '{sample_id}'.")
    parent = store.get_one("validation_datasets", ann["dataset_id"])
    if parent is not None and parent["status"] in ("FROZEN", "EVALUATED"):
        raise datasets_mod.ValidationError(
            f"Dataset is {parent['status']}: post-freeze adjudication is "
            "forbidden because it would invalidate the frozen dataset hash. "
            "Create a new dataset with the corrected labels and freeze that "
            "instead; the frozen original is preserved for audit.")
    spec_labels = datasets_mod._detector(ann["detector_id"])["labels"]
    if adjudicated_label not in spec_labels:
        raise datasets_mod.ValidationError(
            f"Adjudicated label must be one of {spec_labels} (UNCLEAR not allowed)."
        )
    if not isinstance(adjudication_notes, str) or not adjudication_notes.strip():
        raise datasets_mod.ValidationError("Adjudication requires documented notes.")
    store.update("validation_annotations", ann["id"], {
        "adjudicated_label": adjudicated_label,
        "adjudication_notes": adjudication_notes.strip(),
        "adjudicated_at": _now(),
    })
    return store.get_one("validation_annotations", ann["id"])


def blinded_sample_view(sample_id: str) -> dict:
    """ANNOTATION MODE payload: human-label fields only. No predictions.

    Contract: keys here must never include prediction, similarity,
    confidence-from-system, fired rule, matrix category, or correctness.
    """
    sample = datasets_mod.get_sample(sample_id)
    if sample is None:
        raise datasets_mod.ValidationError(f"Sample '{sample_id}' not found.")
    parent = store.get_one("validation_datasets", sample["dataset_id"])
    spec = datasets_mod._detector(parent["detector_id"])
    return {
        "sample_id": sample["id"],
        "dataset_id": sample["dataset_id"],
        "detector_id": parent["detector_id"],
        "raw_text": sample["raw_text"],
        "topic": sample["topic"],
        "teacher_keywords": sample["teacher_keywords"],
        "source": sample["source"],
        "allowed_labels": spec["labels"] + [UNCLEAR],
        "annotation_instructions": spec["protocol_text"],
        "protocol_version": spec["protocol_version"],
        "existing_annotation": latest_annotation(sample_id),
    }


def annotator_ids(dataset_id: str) -> list[str]:
    rows = store.list_where(
        "validation_annotations", "dataset_id = ?", (dataset_id,))
    return sorted({r["annotator_id"] for r in rows})


def inter_rater_status(dataset_id: str) -> dict:
    """Single rater -> N/A display. Two+ independent raters -> kappa-ready."""
    from services.validation import metrics as metrics_mod

    rows = store.list_where(
        "validation_annotations", "dataset_id = ?", (dataset_id,))
    by_sample: dict[str, dict[str, str]] = {}
    for r in rows:
        label, _ = effective_label(r)
        if label is None:
            continue
        by_sample.setdefault(r["sample_id"], {})[r["annotator_id"]] = label
    raters = sorted({r["annotator_id"] for r in rows})
    if len(raters) == 0:
        return {"status": "N/A", "display": protocols.NO_ANNOTATIONS_DISPLAY,
                "annotators": raters}
    if len(raters) < 2:
        return {"status": "N/A", "display": protocols.SINGLE_RATER_DISPLAY,
                "annotators": raters}
    shared = sorted(s for s, m in by_sample.items() if len(m) >= 2)
    if not shared:
        return {"status": "N/A",
                "display": protocols.SINGLE_RATER_DISPLAY + " (no shared samples)",
                "annotators": raters}
    a, b = raters[0], raters[1]
    shared2 = [s for s in shared if a in by_sample[s] and b in by_sample[s]]
    result = metrics_mod.cohens_kappa(
        [by_sample[s][a] for s in shared2], [by_sample[s][b] for s in shared2])
    result["annotators"] = [a, b]
    result["shared_samples"] = len(shared2)
    return result
