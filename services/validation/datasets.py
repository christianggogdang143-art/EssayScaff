"""Phase 7A dataset + sample model.

Formal datasets start EMPTY: the researcher imports legitimate labeled
data or annotates manually. No sample may disappear silently — exclusion
retains the record with a reason.
"""

from __future__ import annotations

import hashlib
import json
import secrets
from datetime import datetime, timezone

import config
from services.validation import protocols, store


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id(prefix: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    return f"{prefix}-{stamp}-{secrets.token_hex(3).upper()}"


class ValidationError(ValueError):
    """Domain error surfaced to the API as 4xx with a plain message."""


def _detector(detector_id: str) -> dict:
    try:
        return protocols.DETECTORS[detector_id]
    except KeyError:
        raise ValidationError(
            f"Unknown detector_id '{detector_id}'. Pilot scope: {sorted(protocols.DETECTORS)}."
        )


def create_dataset(name: str, detector_id: str, description: str = "",
                   source: str | None = None, notes: str = "",
                   is_demo: bool = False) -> dict:
    """Create an EMPTY dataset in DRAFT status."""
    spec = _detector(detector_id)
    if not isinstance(name, str) or not name.strip():
        raise ValidationError("Dataset 'name' must be a non-empty string.")
    record = {
        "id": _new_id("VDS"),
        "name": name.strip(),
        "description": description or "",
        "detector_id": detector_id,
        "validation_type": spec["validation_type"],
        "label_schema_json": store.jdump(spec["labels"]),
        "ruleset_version": config.VALIDATION_RULESET_VERSION,
        "status": "DRAFT",
        "created_at": _now(),
        "frozen_at": None,
        "sample_count": 0,
        "source": source,
        "dataset_hash": None,
        "notes": notes or "",
        "protocol_version": spec["protocol_version"],
        "is_demo": 1 if is_demo else 0,
    }
    store.insert("validation_datasets", record)
    return get_dataset(record["id"])


def get_dataset(dataset_id: str) -> dict | None:
    row = store.get_one("validation_datasets", dataset_id)
    if row is None:
        return None
    return _decorate(row)


def _decorate(row: dict) -> dict:
    row = dict(row)
    row["label_schema"] = store.jload(row.pop("label_schema_json"), [])
    row["is_demo"] = bool(row.get("is_demo"))
    return row


def list_datasets(include_demo: bool = True) -> list[dict]:
    rows = store.list_where("validation_datasets", "1=1")
    out = [_decorate(r) for r in rows]
    if not include_demo:
        out = [d for d in out if not d["is_demo"]]
    return sorted(out, key=lambda d: d["created_at"])


def set_status(dataset_id: str, new_status: str) -> dict:
    row = store.get_one("validation_datasets", dataset_id)
    if row is None:
        raise ValidationError(f"Dataset '{dataset_id}' not found.")
    if new_status not in protocols.DATASET_STATUSES:
        raise ValidationError(f"Unknown status '{new_status}'.")
    allowed = protocols.STATUS_TRANSITIONS.get(row["status"], ())
    if new_status not in allowed:
        raise ValidationError(
            f"Illegal transition {row['status']} -> {new_status}. "
            f"Allowed: {list(allowed) or 'none'}."
        )
    fields = {"status": new_status}
    store.update("validation_datasets", dataset_id, fields)
    return get_dataset(dataset_id)


def add_sample(dataset_id: str, raw_text: str, topic: str | None = None,
               teacher_keywords: list[str] | None = None,
               source: str | None = None,
               provenance: str = "HUMAN_CREATED_RESEARCH_SAMPLE") -> dict:
    """Add one sample. Datasets accept samples only before FREEZE."""
    row = store.get_one("validation_datasets", dataset_id)
    if row is None:
        raise ValidationError(f"Dataset '{dataset_id}' not found.")
    if row["status"] not in ("DRAFT", "ANNOTATING"):
        raise ValidationError(
            f"Dataset is {row['status']}: samples cannot be added after freeze. "
            "Create a new dataset for corrections."
        )
    if not isinstance(raw_text, str) or not raw_text.strip():
        raise ValidationError("Sample 'raw_text' must be a non-empty string.")
    if provenance not in protocols.PROVENANCE_VALUES:
        raise ValidationError(
            f"Unknown provenance '{provenance}'. Allowed: {list(protocols.PROVENANCE_VALUES)}."
        )
    if teacher_keywords is not None and (
        not isinstance(teacher_keywords, list)
        or not all(isinstance(k, str) for k in teacher_keywords)
    ):
        raise ValidationError("Field 'teacher_keywords' must be a list of strings.")
    if topic is not None and not isinstance(topic, str):
        raise ValidationError("Field 'topic' must be a string.")
    record = {
        "id": _new_id("VSMP"),
        "dataset_id": dataset_id,
        "raw_text": raw_text,
        "topic": topic,
        "teacher_keywords_json": store.jdump(teacher_keywords or []),
        "source": source,
        "provenance": provenance,
        "created_at": _now(),
        "included": 1,
        "exclusion_reason": None,
    }
    store.insert("validation_samples", record)
    _refresh_sample_count(dataset_id)
    return get_sample(record["id"])


def get_sample(sample_id: str) -> dict | None:
    row = store.get_one("validation_samples", sample_id)
    if row is None:
        return None
    return _decorate_sample(row)


def _decorate_sample(row: dict) -> dict:
    row = dict(row)
    row["teacher_keywords"] = store.jload(row.pop("teacher_keywords_json"), [])
    row["included"] = bool(row.get("included"))
    return row


def list_samples(dataset_id: str, included_only: bool = False) -> list[dict]:
    where = "dataset_id = ?"
    params: tuple = (dataset_id,)
    if included_only:
        where += " AND included = 1"
    rows = store.list_where("validation_samples", where, params)
    return [_decorate_sample(r) for r in rows]


def exclude_sample(sample_id: str, reason: str) -> dict:
    """Retain the record, mark excluded with a documented reason."""
    row = store.get_one("validation_samples", sample_id)
    if row is None:
        raise ValidationError(f"Sample '{sample_id}' not found.")
    if not isinstance(reason, str) or not reason.strip():
        raise ValidationError("Exclusion requires a documented reason.")
    parent = store.get_one("validation_datasets", row["dataset_id"])
    if parent is not None and parent["status"] not in ("DRAFT", "ANNOTATING"):
        raise ValidationError(
            "Exclusion after freeze requires an adjudication record, "
            "not silent removal. Record the reason via adjudication."
        )
    store.update("validation_samples", sample_id,
                 {"included": 0, "exclusion_reason": reason.strip()})
    _refresh_sample_count(row["dataset_id"])
    return get_sample(sample_id)


def _refresh_sample_count(dataset_id: str) -> None:
    rows = store.list_where(
        "validation_samples", "dataset_id = ? AND included = 1", (dataset_id,))
    store.update("validation_datasets", dataset_id, {"sample_count": len(rows)})


def dataset_hash_payload(dataset_id: str) -> dict:
    """Canonical freeze payload: exact sample IDs + effective human labels."""
    from services.validation import annotations as annotations_mod

    row = store.get_one("validation_datasets", dataset_id)
    if row is None:
        raise ValidationError(f"Dataset '{dataset_id}' not found.")
    samples = sorted(list_samples(dataset_id), key=lambda s: s["id"])
    entries = []
    for s in samples:
        ann = annotations_mod.latest_annotation(s["id"])
        entries.append({
            "sample_id": s["id"],
            "raw_text": s["raw_text"],
            "topic": s["topic"],
            "teacher_keywords": s["teacher_keywords"],
            "included": s["included"],
            "exclusion_reason": s["exclusion_reason"],
            "human_label": ann["human_label"] if ann else None,
            "annotator_id": ann["annotator_id"] if ann else None,
            "adjudicated_label": ann["adjudicated_label"] if ann else None,
        })
    return {
        "dataset_id": dataset_id,
        "ruleset_version": row["ruleset_version"],
        "protocol_version": row["protocol_version"],
        "samples": entries,
    }


def compute_dataset_hash(dataset_id: str) -> str:
    payload = dataset_hash_payload(dataset_id)
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def freeze_dataset(dataset_id: str) -> dict:
    """Freeze: dataset must be ANNOTATING with >=1 annotated included sample."""
    from services.validation import annotations as annotations_mod

    row = store.get_one("validation_datasets", dataset_id)
    if row is None:
        raise ValidationError(f"Dataset '{dataset_id}' not found.")
    if row["status"] != "ANNOTATING":
        raise ValidationError(
            f"Only ANNOTATING datasets can be frozen (current: {row['status']})."
        )
    samples = list_samples(dataset_id, included_only=True)
    if not samples:
        raise ValidationError("Cannot freeze a dataset with zero included samples.")
    unannotated = [
        s["id"] for s in samples
        if annotations_mod.latest_annotation(s["id"]) is None
    ]
    if unannotated:
        raise ValidationError(
            f"Cannot freeze: {len(unannotated)} included sample(s) lack annotations "
            f"(e.g. {unannotated[0]}). Annotate or exclude-with-reason first."
        )
    unresolved = [
        s["id"] for s in samples
        if annotations_mod.effective_label(
            annotations_mod.latest_annotation(s["id"]))[0] is None
    ]
    if unresolved:
        raise ValidationError(
            f"Cannot freeze: {len(unresolved)} UNCLEAR sample(s) (e.g. "
            f"{unresolved[0]}) must be adjudicated or excluded with a "
            "documented reason first. UNCLEAR is never forced into a class."
        )
    digest = compute_dataset_hash(dataset_id)
    store.update("validation_datasets", dataset_id, {
        "status": "FROZEN",
        "frozen_at": _now(),
        "dataset_hash": digest,
    })
    _refresh_sample_count(dataset_id)
    return get_dataset(dataset_id)


def verify_dataset_hash(dataset_id: str) -> dict:
    row = store.get_one("validation_datasets", dataset_id)
    if row is None:
        raise ValidationError(f"Dataset '{dataset_id}' not found.")
    if not row["dataset_hash"]:
        return {"verified": False, "reason": "Dataset is not frozen (no stored hash)."}
    current = compute_dataset_hash(dataset_id)
    return {"verified": current == row["dataset_hash"],
            "stored": row["dataset_hash"], "current": current}
