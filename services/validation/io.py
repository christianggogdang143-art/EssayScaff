"""Phase 7A CSV import / CSV+JSON export.

Import is strict: unknown labels are rejected with row numbers, never
silently coerced. Exports are machine-readable and carry the full
provenance envelope (ruleset, dataset hash, run id, timestamp).
CSV cells are sanitized against formula injection.
"""

from __future__ import annotations

import csv
import io
from datetime import datetime, timezone

from services.validation import annotations as annotations_mod
from services.validation import datasets as datasets_mod
from services.validation import protocols, runs as runs_mod
from services.validation import store


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sanitize_csv_cell(value) -> str:
    """Prefix spreadsheet-formula triggers. Returns a plain string."""
    text = "" if value is None else str(value)
    if text[:1] in ("=", "+", "-", "@"):
        return "'" + text
    return text


THESIS_CSV_COLUMNS = ["sample_id", "text", "human_label", "source", "notes"]
TOPIC_CSV_COLUMNS = ["sample_id", "topic", "teacher_keywords",
                     "text", "human_label", "source", "notes"]


def expected_columns(detector_id: str) -> list[str]:
    if detector_id == "THESIS_002":
        return THESIS_CSV_COLUMNS
    if detector_id == "TOPIC_CLASSIFIER":
        return TOPIC_CSV_COLUMNS
    raise datasets_mod.ValidationError(f"Unknown detector '{detector_id}'.")


def import_csv(dataset_id: str, csv_text: str, annotator_id: str,
               provenance: str = "HUMAN_CREATED_RESEARCH_SAMPLE") -> dict:
    """Import samples + primary annotations into a DRAFT/ANNOTATING dataset.

    sample_id column is accepted but ignored for identity (new IDs are
    minted); it is preserved in the sample 'source' note when present.
    """
    ds = datasets_mod.get_dataset(dataset_id)
    if ds is None:
        raise datasets_mod.ValidationError(f"Dataset '{dataset_id}' not found.")
    if ds["status"] not in ("DRAFT", "ANNOTATING"):
        raise datasets_mod.ValidationError(
            f"Dataset is {ds['status']}: imports only before freeze.")
    if provenance not in protocols.PROVENANCE_VALUES:
        raise datasets_mod.ValidationError(
            f"Unknown provenance '{provenance}'.")
    try:
        reader = csv.DictReader(io.StringIO(csv_text))
    except Exception as exc:
        raise datasets_mod.ValidationError(f"CSV parse failure: {exc}.")
    if reader.fieldnames != expected_columns(ds["detector_id"]):
        raise datasets_mod.ValidationError(
            f"CSV header must be exactly {expected_columns(ds['detector_id'])}; "
            f"got {reader.fieldnames}.")
    added, errors = 0, []
    for lineno, row in enumerate(reader, start=2):
        try:
            text = (row.get("text") or "").strip()
            label = (row.get("human_label") or "").strip()
            if not text:
                raise datasets_mod.ValidationError("empty text")
            allowed = (datasets_mod._detector(ds["detector_id"])["labels"]
                       + [annotations_mod.UNCLEAR])
            if label not in allowed:
                raise datasets_mod.ValidationError(
                    f"invalid label '{row.get('human_label')}'")
            kwargs: dict = {
                "raw_text": text,
                "source": (row.get("source") or "").strip() or None,
                "provenance": provenance,
            }
            if ds["detector_id"] == "TOPIC_CLASSIFIER":
                topic = (row.get("topic") or "").strip()
                kws = [k.strip() for k in
                       (row.get("teacher_keywords") or "").split(";") if k.strip()]
                if not topic:
                    raise datasets_mod.ValidationError("empty topic")
                if not kws:
                    raise datasets_mod.ValidationError("empty teacher_keywords")
                kwargs["topic"] = topic
                kwargs["teacher_keywords"] = kws
            sample = datasets_mod.add_sample(dataset_id, **kwargs)
            annotations_mod.annotate(
                sample["id"], ds["detector_id"], annotator_id, label,
                notes=(row.get("notes") or "").strip())
            added += 1
        except datasets_mod.ValidationError as exc:
            errors.append({"row": lineno, "error": str(exc)})
    return {"added": added, "errors": errors, "dataset": datasets_mod.get_dataset(dataset_id)}


def _csv_preamble_lines(markers: dict, run_id: str | None = None) -> list[str]:
    """Prominent `#` metadata lines so no CSV is mistaken for bare numbers.

    Spreadsheet importers treat `#`-led lines as text, and strict parsers
    can skip them; the header row itself is unchanged.
    """
    banner = ("DEMO DATA \u2014 NOT RESEARCH RESULTS" if markers["is_demo"]
              else "FORMAL HUMAN-LABELED RESEARCH DATA")
    lines = [f"# {banner}",
             f"# result_type={markers['result_type']}"]
    if run_id:
        lines.append(f"# validation_run_id={run_id}")
    return lines


def export_dataset_csv(dataset_id: str) -> str:
    ds = datasets_mod.get_dataset(dataset_id)
    if ds is None:
        raise datasets_mod.ValidationError(f"Dataset '{dataset_id}' not found.")
    from services.validation import runs as runs_mod

    cols = expected_columns(ds["detector_id"])
    buf = io.StringIO()
    buf.write("\n".join(_csv_preamble_lines(runs_mod.result_markers(dataset_id))) + "\n")
    writer = csv.writer(buf)
    writer.writerow(cols + ["annotation_status", "ruleset_version", "dataset_hash"])
    for s in datasets_mod.list_samples(dataset_id):
        ann = annotations_mod.latest_annotation(s["id"])
        label, how = annotations_mod.effective_label(ann)
        row = {
            "sample_id": s["id"], "text": s["raw_text"],
            "human_label": label or "", "source": s["source"] or "",
            "notes": (ann or {}).get("notes", "") or "",
            "topic": s["topic"] or "",
            "teacher_keywords": ";".join(s["teacher_keywords"]),
        }
        writer.writerow([sanitize_csv_cell(row.get(c, "")) for c in cols]
                        + [sanitize_csv_cell(how or "unannotated"),
                           ds["ruleset_version"], ds["dataset_hash"] or ""])
    return buf.getvalue()


def export_run_json(run_id: str) -> dict:
    """Full machine-readable run envelope with provenance."""
    detail = runs_mod.get_run_detail(run_id)
    run = detail["run"]
    markers = runs_mod.result_markers(run["dataset_id"])
    envelope = {
        "envelope": "essayscaff-validation-run",
        "exported_at": _now(),
        "is_demo": markers["is_demo"],
        "result_type": markers["result_type"],
        "ruleset_version": run["ruleset_version"],
        "dataset_id": run["dataset_id"],
        "dataset_hash": run["dataset_hash"],
        "dataset_hash_verified": run["dataset_hash_verified"],
        "validation_run_id": run["id"],
        "detector_id": run["detector_id"],
        "metrics_version": run["metrics_version"],
        "snapshot": run["snapshot"],
        "environment": run["environment"],
        "cells": detail["cells"],
        "metrics": detail["metrics"],
        "class_balance": detail["class_balance"],
        "warnings": detail["warnings"],
        "inter_rater": detail["inter_rater"],
    }
    if markers["is_demo"]:
        envelope["demo_banner"] = "DEMO DATA \u2014 NOT RESEARCH RESULTS."
    return envelope


def export_run_csv(run_id: str) -> str:
    detail = runs_mod.get_run_detail(run_id)
    run = detail["run"]
    markers = runs_mod.result_markers(run["dataset_id"])
    buf = io.StringIO()
    buf.write("\n".join(_csv_preamble_lines(markers, run_id=run["id"])) + "\n")
    writer = csv.writer(buf)
    writer.writerow(["sample_id", "human_label", "system_prediction", "correct",
                     "matrix_cell", "ruleset_version", "validation_run_id"])
    for e in runs_mod.error_cells(run_id):
        writer.writerow([sanitize_csv_cell(e["sample_id"]),
                         sanitize_csv_cell(e["human_label"]),
                         sanitize_csv_cell(e["system_prediction"]),
                         "yes" if e["correct"] else "no",
                         sanitize_csv_cell(e["matrix_cell"]),
                         run["ruleset_version"], run["id"]])
    return buf.getvalue()
