"""Phase 7A reproducible, append-only validation runs.

A run: FROZEN dataset -> VR-2 production predictions -> persisted
confusion cells + metrics. Completed runs are never overwritten:
dataset/ruleset/label changes require a NEW run.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timezone

import config
from services.validation import adapters, annotations as annotations_mod
from services.validation import datasets as datasets_mod
from services.validation import metrics as metrics_mod
from services.validation import protocols, store
from services.validation import snapshot as snapshot_mod


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_run_id() -> str:
    return f"VRUN-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{secrets.token_hex(3).upper()}"


def _environment() -> dict:
    snap = snapshot_mod.build_snapshot()
    return {
        "python": snap.get("python_version"),
        "ruleset_version": snap.get("ruleset_version"),
        "app_version": snap.get("app_version"),
        "spacy_version": snap.get("spacy_version"),
        "spacy_model": snap.get("spacy_model"),
        "spacy_model_version": snap.get("spacy_model_version"),
        "nltk_version": snap.get("nltk_version"),
        "sklearn_version": snap.get("sklearn_version"),
    }


def create_run(dataset_id: str) -> dict:
    """Create + execute a validation run. Raises ValidationError on misuse."""
    ds = datasets_mod.get_dataset(dataset_id)
    if ds is None:
        raise datasets_mod.ValidationError(f"Dataset '{dataset_id}' not found.")
    if ds["status"] not in protocols.RUN_ELIGIBLE_STATUSES:
        raise datasets_mod.ValidationError(
            f"Dataset is {ds['status']}: runs require a FROZEN dataset. "
            "Freeze the dataset (ground truth fixed) before evaluation."
        )
    # VR-2 freeze enforcement: never evaluate a stale/newer ruleset silently.
    current_ruleset = config.VALIDATION_RULESET_VERSION
    if ds["ruleset_version"] != current_ruleset:
        raise datasets_mod.ValidationError(
            f"Ruleset drift: dataset frozen under {ds['ruleset_version']} but "
            f"active ruleset is {current_ruleset}. Create a new dataset "
            "revision under the active ruleset; never overwrite VR-2 results."
        )
    verification = datasets_mod.verify_dataset_hash(dataset_id)
    if not verification.get("verified"):
        raise datasets_mod.ValidationError(
            "Dataset hash mismatch: ground truth changed after freeze. "
            "Create a new dataset revision instead."
        )
    # Pre-run VR-2 enforcement: the live implementation must reproduce the
    # pinned freeze hashes, not merely carry the "VR-2" version string.
    freeze_check = snapshot_mod.verify_vr2_freeze()
    if freeze_check["problems"]:
        raise datasets_mod.ValidationError(
            "VR2_FREEZE_DRIFT_DETECTED: " + "; ".join(freeze_check["problems"]) +
            ". Refusing validation run: the implementation no longer matches "
            "the frozen VR-2 detector. Restore VR-2 or version a new ruleset; "
            "never run formal validation on drifted code.")
    run_id = _new_run_id()
    snapshot = snapshot_mod.freeze_record()
    store.insert("validation_runs", {
        "id": run_id,
        "dataset_id": dataset_id,
        "dataset_hash": ds["dataset_hash"],
        "dataset_hash_verified": 1,
        "detector_id": ds["detector_id"],
        "ruleset_version": current_ruleset,
        "ruleset_hash": snapshot["rules_dir_sha256"],
        "config_hash": snapshot["config_hash"],
        "snapshot_json": store.jdump(snapshot),
        "started_at": _now(),
        "completed_at": None,
        "sample_count": 0,
        "excluded_count": 0,
        "status": "RUNNING",
        "metrics_version": snapshot_mod.METRICS_VERSION,
        "environment_json": store.jdump(_environment()),
    })
    try:
        summary = _evaluate(run_id, ds)
    except Exception:
        store.update("validation_runs", run_id,
                     {"status": "FAILED", "completed_at": _now()})
        raise
    store.update("validation_runs", run_id, {
        "status": "COMPLETE",
        "completed_at": _now(),
        "sample_count": summary["sample_count"],
        "excluded_count": summary["excluded_count"],
    })
    if ds["status"] == "FROZEN":
        store.update("validation_datasets", dataset_id, {"status": "EVALUATED"})
    return get_run(run_id)


def _evaluate(run_id: str, ds: dict) -> dict:
    detector_id = ds["detector_id"]
    spec = datasets_mod._detector(detector_id)
    samples = datasets_mod.list_samples(ds["id"], included_only=True)
    pairs: list[tuple[str, str, str]] = []  # (human, predicted, sample_id)
    excluded = 0
    for sample in samples:
        ann = annotations_mod.latest_annotation(sample["id"])
        label, _how = annotations_mod.effective_label(ann)
        if label is None:
            excluded += 1
            continue
        pred = adapters.predict(detector_id, sample)
        store.insert("validation_predictions", {
            "id": f"VPRD-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{secrets.token_hex(3).upper()}",
            "run_id": run_id,
            "sample_id": sample["id"],
            "detector_id": detector_id,
            "predicted_label": pred["predicted_label"],
            "system_positive": (None if pred["system_positive"] is None
                                else int(pred["system_positive"])),
            "raw_output_json": store.jdump(pred["raw_detector_output"]),
            "evidence_json": store.jdump(pred["evidence"]),
            "ruleset_version": pred["ruleset_version"],
            "config_hash": pred["config_hash"],
            "predicted_at": pred["predicted_at"],
            "processing_ms": pred["processing_ms"],
        })
        pairs.append((label, pred["predicted_label"], sample["id"]))
    _persist_results(run_id, detector_id, spec, pairs)
    return {"sample_count": len(pairs), "excluded_count": excluded}


def _persist_results(run_id: str, detector_id: str, spec: dict,
                     pairs: list[tuple[str, str, str]]) -> None:
    if spec["validation_type"] == "BINARY":
        pos = spec["positive_label"]
        tp = sum(1 for h, p, _ in pairs if h == pos and p == pos)
        tn = sum(1 for h, p, _ in pairs if h != pos and p != pos)
        fp = sum(1 for h, p, _ in pairs if h != pos and p == pos)
        fn = sum(1 for h, p, _ in pairs if h == pos and p != pos)
        result = metrics_mod.binary_metrics(tp, tn, fp, fn)
        for human in (pos, spec["negative_label"]):
            for predicted in (pos, spec["negative_label"]):
                ids = [s for h, p, s in pairs if h == human and p == predicted]
                store.insert("validation_confusion_cells", {
                    "run_id": run_id, "human_label": human,
                    "predicted_label": predicted, "sample_count": len(ids),
                    "sample_ids_json": store.jdump(ids),
                })
        _store_metric_dict(run_id, {
            "N": {"value": float(result["N"])},
            "TP": {"value": float(tp)}, "TN": {"value": float(tn)},
            "FP": {"value": float(fp)}, "FN": {"value": float(fn)},
            "accuracy": result["accuracy"], "precision": result["precision"],
            "recall": result["recall"], "specificity": result["specificity"],
            "f1": result["f1"],
        })
    else:
        result = metrics_mod.multiclass_metrics(pairs, spec["labels"])
        for pred_label, col in result["matrix"]["cells"].items():
            for human_label, cell in col.items():
                store.insert("validation_confusion_cells", {
                    "run_id": run_id, "human_label": human_label,
                    "predicted_label": pred_label,
                    "sample_count": cell["count"],
                    "sample_ids_json": store.jdump(cell["sample_ids"]),
                })
        flat = {"N": {"value": float(result["N"])},
                "accuracy": result["accuracy"],
                "macro_precision": result["macro_precision"],
                "macro_recall": result["macro_recall"],
                "macro_f1": result["macro_f1"],
                "weighted_precision": result["weighted_precision"],
                "weighted_recall": result["weighted_recall"],
                "weighted_f1": result["weighted_f1"]}
        for cls in spec["labels"]:
            pc = result["per_class"][cls]
            flat[f"support_{cls}"] = {"value": float(pc["support"])}
            flat[f"precision_{cls}"] = pc["precision"]
            flat[f"recall_{cls}"] = pc["recall"]
            flat[f"f1_{cls}"] = pc["f1"]
        _store_metric_dict(run_id, flat)


def _store_metric_dict(run_id: str, flat: dict) -> None:
    for name, m in flat.items():
        store.insert("validation_metrics", {
            "run_id": run_id,
            "metric_name": name,
            "metric_value": m.get("value"),
            "status": m.get("status", "OK"),
            "reason": m.get("reason"),
            "extra_json": store.jdump({}),
        })


def get_run(run_id: str) -> dict | None:
    row = store.get_one("validation_runs", run_id)
    if row is None:
        return None
    return _decorate_run(row)


def result_markers(dataset_id: str) -> dict:
    """Structured demo/formal markers for any run representation.

    result_type is DEMO_DATA_NOT_RESEARCH_RESULTS for demo datasets and
    FORMAL_HUMAN_LABELED_VALIDATION otherwise. No run representation may
    rely on the researcher remembering which dataset produced it.
    """
    ds = datasets_mod.get_dataset(dataset_id)
    is_demo = bool(ds and ds.get("is_demo"))
    return {
        "is_demo": is_demo,
        "result_type": ("DEMO_DATA_NOT_RESEARCH_RESULTS" if is_demo
                        else "FORMAL_HUMAN_LABELED_VALIDATION"),
        "dataset_name": (ds or {}).get("name"),
    }


def _decorate_run(row: dict) -> dict:
    row = dict(row)
    row["snapshot"] = store.jload(row.pop("snapshot_json"), {})
    row["environment"] = store.jload(row.pop("environment_json"), {})
    row["dataset_hash_verified"] = bool(row.get("dataset_hash_verified"))
    row.update(result_markers(row.get("dataset_id", "")))
    return row


def list_runs(dataset_id: str | None = None) -> list[dict]:
    if dataset_id:
        rows = store.list_where("validation_runs", "dataset_id = ?", (dataset_id,))
    else:
        rows = store.list_where("validation_runs", "1=1")
    return sorted((_decorate_run(r) for r in rows), key=lambda r: r["started_at"])


def get_run_detail(run_id: str) -> dict:
    """Full reproducible record: run + cells + metrics + balance + warnings."""
    run = get_run(run_id)
    if run is None:
        raise datasets_mod.ValidationError(f"Run '{run_id}' not found.")
    cells = store.list_where("validation_confusion_cells", "run_id = ?", (run_id,))
    for c in cells:
        c["sample_ids"] = store.jload(c.pop("sample_ids_json"), [])
    metrics = store.list_where("validation_metrics", "run_id = ?", (run_id,))
    preds = store.list_where("validation_predictions", "run_id = ?", (run_id,))
    pairs = []
    for p in preds:
        ann = annotations_mod.latest_annotation(p["sample_id"])
        label, _ = annotations_mod.effective_label(ann)
        pairs.append((label, p["predicted_label"]))
    balance = metrics_mod.class_balance(pairs)
    warnings = []
    if balance["N"] < 50:
        warnings.append(
            f"Pilot dataset: N={balance['N']}. Metrics are preliminary and "
            "should not be treated as stable estimates.")
    if balance["imbalance_warning"]:
        warnings.append(
            "Class distribution is strongly imbalanced: accuracy may mislead; "
            "rely on precision, recall and F1.")
    rater = annotations_mod.inter_rater_status(run["dataset_id"])
    return {"run": run, "cells": cells, "metrics": metrics,
            "predictions": preds, "class_balance": balance,
            "warnings": warnings, "inter_rater": rater}


def _transparency_links(detector_id: str) -> dict:
    """Whitelisted source locations for the production detector behind a
    prediction. Viewed through the existing /api/source guard."""
    if detector_id == "THESIS_002":
        return {"detector_source": {"file": "rules/meta_rules.py",
                                    "function": "detect_meta_statements"},
                "segmentation_source": {"file": "services/nlp_service.py",
                                        "function": "analyze_text"}}
    if detector_id == "TOPIC_CLASSIFIER":
        return {"detector_source": {"file": "services/similarity.py",
                                    "function": "analyze_topic"},
                "classification_source": {"file": "services/similarity.py",
                                          "function": "classify"}}
    return {}


def error_cells(run_id: str, human: str | None = None,
                predicted: str | None = None) -> list[dict]:
    """ERROR ANALYSIS MODE: human label + system prediction + evidence visible.

    Only for COMPLETE runs. Each entry explains its matrix cell.
    """
    run = get_run(run_id)
    if run is None:
        raise datasets_mod.ValidationError(f"Run '{run_id}' not found.")
    if run["status"] != "COMPLETE":
        raise datasets_mod.ValidationError("Error analysis requires a COMPLETE run.")
    preds = store.list_where("validation_predictions", "run_id = ?", (run_id,))
    out = []
    for p in preds:
        sample = datasets_mod.get_sample(p["sample_id"])
        ann = annotations_mod.latest_annotation(p["sample_id"])
        label, how = annotations_mod.effective_label(ann)
        if human is not None and label != human:
            continue
        if predicted is not None and p["predicted_label"] != predicted:
            continue
        out.append({
            "sample_id": p["sample_id"],
            "raw_text": sample["raw_text"] if sample else None,
            "topic": sample["topic"] if sample else None,
            "human_label": label,
            "label_source": how,
            "system_prediction": p["predicted_label"],
            "system_positive": p["system_positive"],
            "system_evidence": store.jload(p["evidence_json"], {}),
            "raw_detector_output": store.jload(p["raw_output_json"], {}),
            "annotation_notes": (ann or {}).get("notes", ""),
            "correct": label == p["predicted_label"],
            "matrix_cell": f"human={label} / system={p['predicted_label']}",
            # Reuses existing transparency infrastructure: the live
            # detector source (whitelisted /api/source) for this prediction.
            "transparency_links": _transparency_links(p["detector_id"]),
        })
    return out
