"""Phase 7A researcher validation API.

Separate blueprint from the student workflow: nothing here is part of
Idea -> Thesis -> Outline -> Reflection. Annotation endpoints never
expose system predictions; error-analysis endpoints require a COMPLETE
run. No endpoint accepts file paths (imports take pasted CSV text).
"""

from __future__ import annotations

from flask import Blueprint, jsonify, request, Response

from services.validation import annotations as annotations_mod
from services.validation import datasets as datasets_mod
from services.validation import demo as demo_mod
from services.validation import errornotes as errornotes_mod
from services.validation import io as io_mod
from services.validation import protocols
from services.validation import quality as quality_mod
from services.validation import reporting as reporting_mod
from services.validation import runs as runs_mod
from services.validation import snapshot as snapshot_mod

validation_bp = Blueprint("validation", __name__)

CSV_MAX_CHARS = 500_000


def _err(exc: datasets_mod.ValidationError):
    msg = str(exc)
    status = 409 if ("drift" in msg or "hash mismatch" in msg) else 400
    return jsonify({"error": msg}), status


# ------------------------------------------------------------ datasets
@validation_bp.post("/api/validation/datasets")
def create_dataset():
    data = request.get_json(silent=True) or {}
    try:
        ds = datasets_mod.create_dataset(
            name=data.get("name", ""),
            detector_id=data.get("detector_id", ""),
            description=data.get("description", ""),
            source=data.get("source"),
            notes=data.get("notes", ""),
        )
    except datasets_mod.ValidationError as exc:
        return _err(exc)
    return jsonify(ds), 201


@validation_bp.get("/api/validation/datasets")
def list_datasets():
    include_demo = request.args.get("include_demo", "1") != "0"
    return jsonify({"datasets": datasets_mod.list_datasets(include_demo=include_demo)})


@validation_bp.get("/api/validation/datasets/<dataset_id>")
def dataset_detail(dataset_id):
    ds = datasets_mod.get_dataset(dataset_id)
    if ds is None:
        return jsonify({"error": "Dataset not found."}), 404
    samples = datasets_mod.list_samples(dataset_id)
    for s in samples:
        s["annotation"] = annotations_mod.latest_annotation(s["id"])
    return jsonify({
        "dataset": ds,
        "samples": samples,
        "hash_verification": datasets_mod.verify_dataset_hash(dataset_id),
        "inter_rater": annotations_mod.inter_rater_status(dataset_id),
    })


@validation_bp.post("/api/validation/datasets/<dataset_id>/status")
def dataset_status(dataset_id):
    data = request.get_json(silent=True) or {}
    try:
        return jsonify(datasets_mod.set_status(dataset_id, data.get("status", "")))
    except datasets_mod.ValidationError as exc:
        return _err(exc)


@validation_bp.post("/api/validation/datasets/<dataset_id>/samples")
def add_sample(dataset_id):
    data = request.get_json(silent=True) or {}
    try:
        sample = datasets_mod.add_sample(
            dataset_id,
            raw_text=data.get("raw_text", ""),
            topic=data.get("topic"),
            teacher_keywords=data.get("teacher_keywords"),
            source=data.get("source"),
            provenance=data.get("provenance", "HUMAN_CREATED_RESEARCH_SAMPLE"),
        )
    except datasets_mod.ValidationError as exc:
        return _err(exc)
    return jsonify(sample), 201


@validation_bp.post("/api/validation/samples/<sample_id>/exclude")
def exclude_sample(sample_id):
    data = request.get_json(silent=True) or {}
    try:
        return jsonify(datasets_mod.exclude_sample(sample_id, data.get("reason", "")))
    except datasets_mod.ValidationError as exc:
        return _err(exc)


@validation_bp.post("/api/validation/datasets/<dataset_id>/freeze")
def freeze(dataset_id):
    try:
        return jsonify(datasets_mod.freeze_dataset(dataset_id))
    except datasets_mod.ValidationError as exc:
        return _err(exc)


@validation_bp.get("/api/validation/datasets/<dataset_id>/protocol")
def protocol(dataset_id):
    ds = datasets_mod.get_dataset(dataset_id)
    if ds is None:
        return jsonify({"error": "Dataset not found."}), 404
    spec = datasets_mod._detector(ds["detector_id"])
    return jsonify({
        "detector_id": ds["detector_id"],
        "protocol_version": spec["protocol_version"],
        "protocol_text": spec["protocol_text"],
        "allowed_labels": spec["labels"] + [annotations_mod.UNCLEAR],
    })


# ------------------------------------------------------------ annotation (BLINDED)
@validation_bp.get("/api/validation/samples/<sample_id>/annotate-view")
def annotate_view(sample_id):
    try:
        return jsonify(annotations_mod.blinded_sample_view(sample_id))
    except datasets_mod.ValidationError as exc:
        return _err(exc)


@validation_bp.post("/api/validation/samples/<sample_id>/annotations")
def annotate(sample_id):
    data = request.get_json(silent=True) or {}
    try:
        ann = annotations_mod.annotate(
            sample_id,
            detector_id=data.get("detector_id", ""),
            annotator_id=data.get("annotator_id", ""),
            human_label=data.get("human_label", ""),
            confidence=data.get("confidence"),
            notes=data.get("notes", ""),
        )
    except datasets_mod.ValidationError as exc:
        return _err(exc)
    return jsonify(ann), 201


@validation_bp.post("/api/validation/samples/<sample_id>/adjudicate")
def adjudicate(sample_id):
    data = request.get_json(silent=True) or {}
    try:
        return jsonify(annotations_mod.adjudicate(
            sample_id, data.get("adjudicated_label", ""),
            data.get("adjudication_notes", "")))
    except datasets_mod.ValidationError as exc:
        return _err(exc)


# ------------------------------------------------------------ import/export
@validation_bp.post("/api/validation/datasets/<dataset_id>/import")
def import_csv(dataset_id):
    data = request.get_json(silent=True) or {}
    csv_text = data.get("csv_text", "")
    if not isinstance(csv_text, str) or len(csv_text) > CSV_MAX_CHARS:
        return jsonify({"error": "CSV text missing or too large."}), 400
    try:
        result = io_mod.import_csv(
            dataset_id, csv_text,
            annotator_id=data.get("annotator_id", ""),
            provenance=data.get("provenance", "HUMAN_CREATED_RESEARCH_SAMPLE"),
        )
    except datasets_mod.ValidationError as exc:
        return _err(exc)
    status = 200 if result["errors"] else 201
    return jsonify(result), status


@validation_bp.get("/api/validation/datasets/<dataset_id>/export.csv")
def export_dataset_csv(dataset_id):
    try:
        text = io_mod.export_dataset_csv(dataset_id)
    except datasets_mod.ValidationError as exc:
        return _err(exc)
    return Response(text, mimetype="text/csv",
                    headers={"Content-Disposition":
                             f"attachment; filename={dataset_id}.csv"})


# ------------------------------------------------------------ runs + results
@validation_bp.post("/api/validation/datasets/<dataset_id>/runs")
def create_run(dataset_id):
    try:
        run = runs_mod.create_run(dataset_id)
    except datasets_mod.ValidationError as exc:
        return _err(exc)
    return jsonify(run), 201


@validation_bp.get("/api/validation/runs")
def list_runs():
    return jsonify({"runs": runs_mod.list_runs(request.args.get("dataset_id"))})


@validation_bp.get("/api/validation/runs/<run_id>")
def run_detail(run_id):
    try:
        return jsonify(runs_mod.get_run_detail(run_id))
    except datasets_mod.ValidationError as exc:
        return _err(exc)


@validation_bp.get("/api/validation/runs/<run_id>/errors")
def run_errors(run_id):
    try:
        cells = runs_mod.error_cells(
            run_id,
            human=request.args.get("human"),
            predicted=request.args.get("predicted"),
        )
    except datasets_mod.ValidationError as exc:
        return _err(exc)
    wanted = request.args.get("correct")
    if wanted in ("yes", "no"):
        flag = wanted == "yes"
        cells = [c for c in cells if c["correct"] is flag]
    return jsonify({"errors": cells, "count": len(cells)})


@validation_bp.get("/api/validation/runs/<run_id>/export.json")
def export_run_json(run_id):
    try:
        return jsonify(io_mod.export_run_json(run_id))
    except datasets_mod.ValidationError as exc:
        return _err(exc)


@validation_bp.get("/api/validation/runs/<run_id>/export.csv")
def export_run_csv(run_id):
    try:
        text = io_mod.export_run_csv(run_id)
    except datasets_mod.ValidationError as exc:
        return _err(exc)
    return Response(text, mimetype="text/csv",
                    headers={"Content-Disposition":
                             f"attachment; filename={run_id}.csv"})


@validation_bp.get("/api/validation/datasets/<dataset_id>/rater")
def rater_status(dataset_id):
    if datasets_mod.get_dataset(dataset_id) is None:
        return jsonify({"error": "Dataset not found."}), 404
    return jsonify(annotations_mod.inter_rater_status(dataset_id))


# ------------------------------------------------------------ quality (7B)
@validation_bp.get("/api/validation/datasets/<dataset_id>/progress")
def dataset_progress(dataset_id):
    try:
        return jsonify(quality_mod.progress(dataset_id))
    except datasets_mod.ValidationError as exc:
        return _err(exc)


@validation_bp.get("/api/validation/datasets/<dataset_id>/quality")
def dataset_quality(dataset_id):
    try:
        return jsonify(quality_mod.quality_summary(dataset_id))
    except datasets_mod.ValidationError as exc:
        return _err(exc)


@validation_bp.get("/api/validation/datasets/<dataset_id>/duplicates")
def dataset_duplicates(dataset_id):
    try:
        return jsonify({"duplicates": quality_mod.duplicates(dataset_id)})
    except datasets_mod.ValidationError as exc:
        return _err(exc)


@validation_bp.get("/api/validation/datasets/<dataset_id>/freeze-preview")
def freeze_preview(dataset_id):
    try:
        return jsonify(quality_mod.freeze_preview(dataset_id))
    except datasets_mod.ValidationError as exc:
        return _err(exc)


# ------------------------------------------------------------ error notes (7B)
@validation_bp.get("/api/validation/error-categories")
def error_categories():
    return jsonify({"categories": list(errornotes_mod.ERROR_CATEGORIES),
                    "note": "Categories document failure modes for future VR-3. "
                            "They never modify VR-2."})


@validation_bp.post("/api/validation/runs/<run_id>/error-notes")
def add_error_note(run_id):
    data = request.get_json(silent=True) or {}
    try:
        note = errornotes_mod.add_error_note(
            run_id, data.get("sample_id", ""), data.get("category", ""),
            data.get("note", ""), data.get("analyst", ""))
    except datasets_mod.ValidationError as exc:
        return _err(exc)
    return jsonify(note), 201


@validation_bp.get("/api/validation/runs/<run_id>/error-notes")
def list_error_notes(run_id):
    if runs_mod.get_run(run_id) is None:
        return jsonify({"error": "Run not found."}), 404
    return jsonify({"notes": errornotes_mod.list_error_notes(run_id)})


# ------------------------------------------------------------ reporting (7B)
@validation_bp.get("/api/validation/runs/<run_id>/label")
def run_label(run_id):
    try:
        return jsonify({"result_label": reporting_mod.result_label(run_id)})
    except datasets_mod.ValidationError as exc:
        return _err(exc)


@validation_bp.get("/api/validation/runs/<run_id>/manuscript")
def run_manuscript(run_id):
    try:
        return jsonify(reporting_mod.manuscript_summary(run_id))
    except datasets_mod.ValidationError as exc:
        return _err(exc)


@validation_bp.get("/api/validation/runs/<run_id>/export-package.json")
def export_package(run_id):
    try:
        return jsonify(reporting_mod.research_package(run_id))
    except datasets_mod.ValidationError as exc:
        return _err(exc)


# ------------------------------------------------------------ provenance + demo
@validation_bp.get("/api/validation/freeze-record")
def freeze_record():
    return jsonify(snapshot_mod.freeze_record())


@validation_bp.post("/api/validation/demo/ensure")
def ensure_demo():
    result = demo_mod.ensure_demo_datasets()
    return jsonify({
        "banner": protocols.DEMO_BANNER,
        "binary": result["binary"],
        "multiclass": result["multiclass"],
    }), 201
