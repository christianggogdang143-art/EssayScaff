"""Phase 7B data-quality tooling: progress, duplicates, quality summary.

All views here use HUMAN labels only. System predictions never appear
before freeze; progress shows annotation coverage, never detector output.
"""

from __future__ import annotations

import re

from services.validation import annotations as annotations_mod
from services.validation import datasets as datasets_mod
from services.validation import store


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").casefold()).strip()


def progress(dataset_id: str) -> dict:
    """Annotation progress with live human class counts (no predictions)."""
    ds = datasets_mod.get_dataset(dataset_id)
    if ds is None:
        raise datasets_mod.ValidationError(f"Dataset '{dataset_id}' not found.")
    samples = datasets_mod.list_samples(dataset_id)
    included = [s for s in samples if s["included"]]
    excluded = [s for s in samples if not s["included"]]
    class_counts: dict[str, int] = {}
    annotated = unclear = 0
    for s in included:
        label, _how = annotations_mod.effective_label(
            annotations_mod.latest_annotation(s["id"]))
        if label is None:
            unclear += 1
        else:
            annotated += 1
            class_counts[label] = class_counts.get(label, 0) + 1
    return {
        "dataset_id": dataset_id,
        "detector_id": ds["detector_id"],
        "status": ds["status"],
        "total_samples": len(samples),
        "included": len(included),
        "excluded": len(excluded),
        "annotated": annotated,
        "remaining": len(included) - annotated - unclear,
        "unclear": unclear,
        "class_counts": class_counts,
        "annotators": annotations_mod.annotator_ids(dataset_id),
    }


def duplicates(dataset_id: str) -> list[dict]:
    """Exact-duplicate candidates (normalized text; +topic/kws for topics).

    Flagged, never silently removed. The researcher retains, excludes,
    or documents intentional duplication.
    """
    ds = datasets_mod.get_dataset(dataset_id)
    if ds is None:
        raise datasets_mod.ValidationError(f"Dataset '{dataset_id}' not found.")
    groups: dict[str, list[str]] = {}
    for s in datasets_mod.list_samples(dataset_id):
        key = _norm(s["raw_text"])
        if ds["detector_id"] == "TOPIC_CLASSIFIER":
            key += "\u0001" + _norm(s["topic"]) + "\u0001" + "|".join(
                sorted(_norm(k) for k in s["teacher_keywords"]))
        groups.setdefault(key, []).append(s["id"])
    return [{"flag": "DUPLICATE CANDIDATE", "sample_ids": sorted(ids)}
            for ids in groups.values() if len(ids) > 1]


def quality_summary(dataset_id: str) -> dict:
    """DATA QUALITY SUMMARY required before freeze approval."""
    ds = datasets_mod.get_dataset(dataset_id)
    if ds is None:
        raise datasets_mod.ValidationError(f"Dataset '{dataset_id}' not found.")
    prog = progress(dataset_id)
    samples = datasets_mod.list_samples(dataset_id)
    provenance: dict[str, int] = {}
    for s in samples:
        provenance[s["provenance"]] = provenance.get(s["provenance"], 0) + 1
    missing_fields = []
    for s in samples:
        if ds["detector_id"] == "TOPIC_CLASSIFIER":
            if not (s["topic"] or "").strip():
                missing_fields.append({"sample_id": s["id"], "field": "topic"})
            if not s["teacher_keywords"]:
                missing_fields.append({"sample_id": s["id"], "field": "teacher_keywords"})
    ann_rows = store.list_where(
        "validation_annotations", "dataset_id = ?", (dataset_id,))
    by_sample: dict[str, set[str]] = {}
    for r in ann_rows:
        by_sample.setdefault(r["sample_id"], set()).add(r["annotator_id"])
    double_coded = sum(1 for v in by_sample.values() if len(v) >= 2)
    dupes = duplicates(dataset_id)
    reasons = []
    if ds["status"] != "ANNOTATING":
        reasons.append(f"Dataset status is {ds['status']}; must be ANNOTATING.")
    if prog["included"] == 0:
        reasons.append("Zero included samples.")
    if prog["remaining"] > 0:
        reasons.append(f"{prog['remaining']} included sample(s) lack annotations.")
    if prog["unclear"] > 0:
        reasons.append(f"{prog['unclear']} UNCLEAR sample(s) need adjudication or exclusion-with-reason.")
    if missing_fields:
        reasons.append(f"{len(missing_fields)} missing required field(s).")
    return {
        "dataset_id": dataset_id,
        "dataset_name": ds["name"],
        "detector_id": ds["detector_id"],
        "protocol_version": ds["protocol_version"],
        "ruleset_version": ds["ruleset_version"],
        "is_demo": ds["is_demo"],
        "total_samples": prog["total_samples"],
        "included_samples": prog["included"],
        "excluded_samples": prog["excluded"],
        "annotated_samples": prog["annotated"],
        "unannotated_samples": prog["remaining"],
        "unclear_samples": prog["unclear"],
        "class_distribution": prog["class_counts"],
        "annotator_count": len(prog["annotators"]),
        "annotators": prog["annotators"],
        "double_coded_samples": double_coded,
        "provenance_breakdown": provenance,
        "missing_fields": missing_fields,
        "duplicate_candidates": dupes,
        "freeze_eligible": not reasons,
        "freeze_blockers": reasons,
    }


FREEZE_APPROVAL_STATEMENT = (
    "This action locks the current sample set and human labels "
    "for evaluation against VR-2."
)


def freeze_preview(dataset_id: str) -> dict:
    """Explicit approval payload shown BEFORE the researcher freezes."""
    summary = quality_summary(dataset_id)
    current_hash = datasets_mod.compute_dataset_hash(dataset_id)
    return {
        "approval_statement": FREEZE_APPROVAL_STATEMENT,
        "freeze_eligible": summary["freeze_eligible"],
        "freeze_blockers": summary["freeze_blockers"],
        "quality_summary": summary,
        "current_hash_if_frozen_now": current_hash,
        "ruleset_version": summary["ruleset_version"],
    }
