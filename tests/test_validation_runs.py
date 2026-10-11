"""Phase 7A: demo fixtures, runs, immutability, freeze enforcement."""

import pytest

import config
from app import create_app
from services import db
from services.validation import annotations as annotations_mod
from services.validation import datasets as datasets_mod
from services.validation import demo as demo_mod
from services.validation import protocols
from services.validation import runs as runs_mod


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "db_path", lambda: tmp_path / "test.db")
    application = create_app(prewarm=False)
    application.config.update(TESTING=True)
    return application.test_client()


@pytest.fixture()
def demo_pair(client):
    return demo_mod.ensure_demo_datasets()


def _freeze(ds):
    assert ds["status"] == "ANNOTATING"
    return datasets_mod.freeze_dataset(ds["id"])


def _metric(detail, name):
    return next(m for m in detail["metrics"] if m["metric_name"] == name)


def test_demo_datasets_flagged_and_idempotent(client, demo_pair):
    for key in ("binary", "multiclass"):
        ds = demo_pair[key]
        assert ds["is_demo"] is True
        assert protocols.DEMO_BANNER in ds["notes"]
    again = demo_mod.ensure_demo_datasets()
    assert again["binary"]["id"] == demo_pair["binary"]["id"]
    assert again["multiclass"]["id"] == demo_pair["multiclass"]["id"]
    formal = [d for d in datasets_mod.list_datasets(include_demo=False)]
    assert all(not d["is_demo"] for d in formal)


def test_demo_binary_run_cells_and_metrics(client, demo_pair):
    ds = _freeze(demo_pair["binary"])
    run = runs_mod.create_run(ds["id"])
    assert run["status"] == "COMPLETE"
    assert run["ruleset_version"] == "VR-2"
    assert run["dataset_hash_verified"] is True
    assert run["sample_count"] == 6 and run["excluded_count"] == 0
    detail = runs_mod.get_run_detail(run["id"])
    cells = {(c["human_label"], c["predicted_label"]): c["sample_count"]
             for c in detail["cells"]}
    assert cells[("META_STATEMENT", "META_STATEMENT")] == 2  # TP
    assert cells[("NOT_META_STATEMENT", "NOT_META_STATEMENT")] == 2  # TN
    assert cells[("NOT_META_STATEMENT", "META_STATEMENT")] == 1  # FP
    assert cells[("META_STATEMENT", "NOT_META_STATEMENT")] == 1  # FN
    for name in ("accuracy", "precision", "recall", "specificity", "f1"):
        m = _metric(detail, name)
        assert m["status"] == "OK"
        assert m["metric_value"] == pytest.approx(2 / 3)
    # Raw sample IDs stored per cell.
    fp_cell = next(c for c in detail["cells"]
                   if c["human_label"] == "NOT_META_STATEMENT"
                   and c["predicted_label"] == "META_STATEMENT")
    assert len(fp_cell["sample_ids"]) == 1
    # Small-N warning is shown, not hidden.
    assert any("N=6" in w for w in detail["warnings"])
    # Single rater: kappa N/A.
    assert detail["inter_rater"]["status"] == "N/A"


def test_demo_multiclass_run_cells_and_metrics(client, demo_pair):
    ds = _freeze(demo_pair["multiclass"])
    run = runs_mod.create_run(ds["id"])
    detail = runs_mod.get_run_detail(run["id"])
    cells = {(c["human_label"], c["predicted_label"]): c["sample_count"]
             for c in detail["cells"]}
    assert cells[("WEAK", "WEAK")] == 2
    assert cells[("MODERATE", "MODERATE")] == 2
    assert cells[("STRONG", "STRONG")] == 1
    assert cells[("STRONG", "MODERATE")] == 1
    assert sum(cells.values()) == 6
    assert _metric(detail, "accuracy")["metric_value"] == pytest.approx(5 / 6)
    assert _metric(detail, "macro_precision")["metric_value"] == pytest.approx(8 / 9)
    assert _metric(detail, "macro_recall")["metric_value"] == pytest.approx(2.5 / 3)
    assert _metric(detail, "support_WEAK")["metric_value"] == 2.0
    assert _metric(detail, "support_MODERATE")["metric_value"] == 2.0
    assert _metric(detail, "support_STRONG")["metric_value"] == 2.0
    assert _metric(detail, "recall_STRONG")["metric_value"] == pytest.approx(0.5)
    bal = detail["class_balance"]
    assert bal["N"] == 6
    assert bal["counts"] == {"STRONG": 2, "MODERATE": 2, "WEAK": 2}


def test_runs_are_append_only(client, demo_pair):
    ds = _freeze(demo_pair["binary"])
    first = runs_mod.create_run(ds["id"])
    second = runs_mod.create_run(ds["id"])
    assert first["id"] != second["id"]
    d1 = runs_mod.get_run_detail(first["id"])
    d2 = runs_mod.get_run_detail(second["id"])
    assert _metric(d1, "f1")["metric_value"] == pytest.approx(
        _metric(d2, "f1")["metric_value"])
    assert len(runs_mod.list_runs(ds["id"])) == 2


def test_run_requires_frozen_dataset(client):
    ds = datasets_mod.create_dataset(name="R", detector_id="THESIS_002")
    with pytest.raises(datasets_mod.ValidationError):
        runs_mod.create_run(ds["id"])


def test_ruleset_drift_blocks_run(client, demo_pair, monkeypatch):
    ds = _freeze(demo_pair["binary"])
    monkeypatch.setattr(config, "VALIDATION_RULESET_VERSION", "VR-99")
    with pytest.raises(datasets_mod.ValidationError) as exc:
        runs_mod.create_run(ds["id"])
    assert "drift" in str(exc.value).lower()


def test_unclear_samples_excluded_with_count(client):
    ds = datasets_mod.create_dataset(name="U", detector_id="THESIS_002")
    s1 = datasets_mod.add_sample(ds["id"], raw_text="This essay will discuss crops.")
    s2 = datasets_mod.add_sample(ds["id"], raw_text="Farmers adapt to rainfall.")
    annotations_mod.annotate(s1["id"], "THESIS_002", "R1", "META_STATEMENT")
    annotations_mod.annotate(s2["id"], "THESIS_002", "R1", "UNCLEAR")
    datasets_mod.set_status(ds["id"], "ANNOTATING")
    # Phase 7B rule: UNCLEAR must be adjudicated or excluded before freeze.
    with pytest.raises(datasets_mod.ValidationError):
        datasets_mod.freeze_dataset(ds["id"])
    datasets_mod.exclude_sample(s2["id"], "UNCLEAR: genuinely ambiguous reference")
    datasets_mod.freeze_dataset(ds["id"])
    run = runs_mod.create_run(ds["id"])
    assert run["sample_count"] == 1
    assert run["excluded_count"] == 0
    assert datasets_mod.get_sample(s2["id"])["exclusion_reason"].startswith("UNCLEAR")


def test_error_cells_filtering(client, demo_pair):
    ds = _freeze(demo_pair["binary"])
    run = runs_mod.create_run(ds["id"])
    all_cells = runs_mod.error_cells(run["id"])
    assert len(all_cells) == 6
    errors = runs_mod.error_cells(run["id"], human="NOT_META_STATEMENT",
                                  predicted="META_STATEMENT")
    assert len(errors) == 1
    assert errors[0]["correct"] is False
    assert "margins must be one inch" in errors[0]["raw_text"]
    assert errors[0]["system_prediction"] == "META_STATEMENT"
    assert errors[0]["matrix_cell"] == \
        "human=NOT_META_STATEMENT / system=META_STATEMENT"
    assert errors[0]["transparency_links"]["detector_source"] == {
        "file": "rules/meta_rules.py", "function": "detect_meta_statements"}
    correct = [e for e in all_cells if e["correct"]]
    assert len(correct) == 4
