"""Phase 7B result labeling, manuscript summary, research export package.

Every value is sourced from persisted run artifacts. No interpretation
beyond the data; significance is never claimed. Demo runs carry the
DEMO banner; formal runs carry the FORMAL label with full provenance.
"""

from __future__ import annotations

from datetime import datetime, timezone

from services.validation import annotations as annotations_mod
from services.validation import datasets as datasets_mod
from services.validation import errornotes as errornotes_mod
from services.validation import io as io_mod
from services.validation import protocols
from services.validation import quality as quality_mod
from services.validation import runs as runs_mod


def result_label(run_id: str) -> str:
    """FORMAL vs DEMO result labeling. Never mixed."""
    run = runs_mod.get_run(run_id)
    if run is None:
        raise datasets_mod.ValidationError(f"Run '{run_id}' not found.")
    ds = datasets_mod.get_dataset(run["dataset_id"])
    if ds is not None and ds["is_demo"]:
        return protocols.DEMO_BANNER
    return "FORMAL VR-2 VALIDATION RESULT"


def _metric_map(detail: dict) -> dict:
    return {m["metric_name"]: m for m in detail["metrics"]}


def _fmt(m: dict | None) -> str:
    if m is None or m.get("status") != "OK" or m.get("metric_value") is None:
        reason = (m or {}).get("reason") or "undefined"
        return f"undefined ({reason})"
    v = m["metric_value"]
    return f"{v:.4f} ({v * 100:.2f}%)"


METRIC_GLOSSARY = {
    "accuracy": "overall proportion classified correctly",
    "precision": "of predicted positives, proportion actually positive",
    "recall": "of real positives, proportion detected",
    "specificity": "of real negatives, proportion correctly rejected",
    "f1": "harmonic balance of precision and recall",
}


def manuscript_summary(run_id: str) -> dict:
    """Plain factual summary sourced ONLY from the persisted run."""
    detail = runs_mod.get_run_detail(run_id)
    run = detail["run"]
    ds = datasets_mod.get_dataset(run["dataset_id"])
    mm = _metric_map(detail)
    lines = []
    if ds["is_demo"]:
        lines.append(protocols.DEMO_BANNER + " Framework demonstration only.")
    else:
        lines.append("FORMAL VR-2 VALIDATION RESULT.")
    lines.append(
        f"Detector {run['detector_id']} was evaluated using N={run['sample_count']} "
        f"human-labeled samples (excluded: {run['excluded_count']}) under "
        f"{ds['protocol_version']}.")
    if run["detector_id"] == "THESIS_002":
        lines.append(
            f"The frozen VR-2 detector produced TP={int(mm['TP']['metric_value'])}, "
            f"TN={int(mm['TN']['metric_value'])}, FP={int(mm['FP']['metric_value'])}, "
            f"and FN={int(mm['FN']['metric_value'])}.")
        lines.append(
            f"Accuracy: {_fmt(mm['accuracy'])}. Precision: {_fmt(mm['precision'])}. "
            f"Recall: {_fmt(mm['recall'])}. Specificity: {_fmt(mm['specificity'])}. "
            f"F1: {_fmt(mm['f1'])}.")
    else:
        per = []
        for cls in ("WEAK", "MODERATE", "STRONG"):
            per.append(
                f"{cls} (support {int(mm[f'support_{cls}']['metric_value'])}): "
                f"precision {_fmt(mm[f'precision_{cls}'])}, "
                f"recall {_fmt(mm[f'recall_{cls}'])}, F1 {_fmt(mm[f'f1_{cls}'])}.")
        lines.append(" ".join(per))
        lines.append(
            f"Overall accuracy: {_fmt(mm['accuracy'])}. "
            f"Macro F1: {_fmt(mm['macro_f1'])}. Weighted F1: {_fmt(mm['weighted_f1'])}.")
    lines.append(
        f"Dataset {run['dataset_id']} (hash {run['dataset_hash'][:12]}...), "
        f"run {run['id']}, ruleset {run['ruleset_version']}, "
        f"annotators {', '.join(annotations_mod.annotator_ids(run['dataset_id'])) or 'none'}.")
    for w in detail["warnings"]:
        lines.append("Warning: " + w)
    return {
        "result_label": result_label(run_id),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "text": "\n".join(lines),
        "glossary": METRIC_GLOSSARY,
    }


def research_package(run_id: str) -> dict:
    """Complete machine-readable research package for one formal run."""
    detail = runs_mod.get_run_detail(run_id)
    run = detail["run"]
    ds = datasets_mod.get_dataset(run["dataset_id"])
    samples = datasets_mod.list_samples(ds["id"])
    annotations = []
    unclear, adjudicated = 0, 0
    for s in samples:
        ann = annotations_mod.latest_annotation(s["id"])
        if ann is None:
            continue
        annotations.append(ann)
        label, how = annotations_mod.effective_label(ann)
        if label is None:
            unclear += 1
        if how == "adjudicated":
            adjudicated += 1
    excluded = [s for s in samples if not s["included"]]
    markers = runs_mod.result_markers(run["dataset_id"])
    return {
        "envelope": "essayscaff-validation-research-package",
        "result_label": result_label(run_id),
        "is_demo": markers["is_demo"],
        "result_type": markers["result_type"],
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "dataset_metadata": ds,
        "sample_counts": {
            "total": len(samples),
            "included": sum(1 for s in samples if s["included"]),
            "excluded": len(excluded),
        },
        "provenance_summary": quality_mod.quality_summary(ds["id"])["provenance_breakdown"],
        "annotation_protocol": {
            "protocol_version": ds["protocol_version"],
            "protocol_text": datasets_mod._detector(ds["detector_id"])["protocol_text"],
        },
        "annotator_summary": {
            "annotators": annotations_mod.annotator_ids(ds["id"]),
            "inter_rater": detail["inter_rater"],
        },
        "dataset_hash": run["dataset_hash"],
        "dataset_hash_verified": run["dataset_hash_verified"],
        "ruleset_snapshot": run["snapshot"],
        "config_hash": run["config_hash"],
        "validation_run_id": run["id"],
        "confusion_matrix": detail["cells"],
        "metrics": detail["metrics"],
        "excluded_sample_report": [
            {"sample_id": s["id"], "reason": s["exclusion_reason"]} for s in excluded],
        "unclear_adjudication_report": {
            "unclear_unadjudicated": unclear,
            "adjudicated": adjudicated,
        },
        "error_case_table": runs_mod.error_cells(run_id),
        "error_notes": errornotes_mod.list_error_notes(run_id),
        "environment_snapshot": run["environment"],
        "manuscript_summary": manuscript_summary(run_id)["text"],
        "artifacts": {
            "dataset_csv": io_mod.export_dataset_csv(ds["id"]),
            "run_csv": io_mod.export_run_csv(run_id),
            "run_json": io_mod.export_run_json(run_id),
        },
    }
