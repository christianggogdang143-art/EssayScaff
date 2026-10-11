"""Phase 7A: datasets, samples, annotations, freeze, hashing, UNCLEAR."""

import pytest

from app import create_app
from services import db
from services.validation import annotations as annotations_mod
from services.validation import datasets as datasets_mod
from services.validation import protocols


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "db_path", lambda: tmp_path / "test.db")
    application = create_app(prewarm=False)
    application.config.update(TESTING=True)
    return application.test_client()


@pytest.fixture()
def ds():
    return datasets_mod.create_dataset(
        name="Pilot THESIS_002", detector_id="THESIS_002",
        description="formal pilot", source="HUMAN_CREATED_RESEARCH_SAMPLE")


def test_formal_dataset_starts_empty(ds):
    assert ds["status"] == "DRAFT"
    assert ds["sample_count"] == 0
    assert ds["is_demo"] is False
    assert datasets_mod.list_samples(ds["id"]) == []


def test_unknown_detector_rejected():
    with pytest.raises(datasets_mod.ValidationError):
        datasets_mod.create_dataset(name="X", detector_id="NOPE")


def test_illegal_status_transition_rejected(ds):
    with pytest.raises(datasets_mod.ValidationError):
        datasets_mod.set_status(ds["id"], "FROZEN")  # DRAFT -> FROZEN illegal
    with pytest.raises(datasets_mod.ValidationError):
        datasets_mod.set_status(ds["id"], "NOPE")


def test_sample_provenance_enforced(ds):
    with pytest.raises(datasets_mod.ValidationError):
        datasets_mod.add_sample(ds["id"], raw_text="Some text.", provenance="MADE_UP")


def test_excluded_sample_retained_with_reason(ds):
    s = datasets_mod.add_sample(ds["id"], raw_text="Climate change matters.")
    out = datasets_mod.exclude_sample(s["id"], "duplicate of VSMP-1")
    assert out["included"] is False
    assert out["exclusion_reason"] == "duplicate of VSMP-1"
    assert datasets_mod.get_sample(s["id"])["included"] is False
    assert datasets_mod.list_samples(ds["id"], included_only=True) == []


def test_invalid_human_label_rejected(ds):
    s = datasets_mod.add_sample(ds["id"], raw_text="This essay will discuss crops.")
    with pytest.raises(datasets_mod.ValidationError):
        annotations_mod.annotate(s["id"], "THESIS_002", "R1", "MAYBE_META")


def test_annotator_id_required(ds):
    s = datasets_mod.add_sample(ds["id"], raw_text="This essay will discuss crops.")
    with pytest.raises(datasets_mod.ValidationError):
        annotations_mod.annotate(s["id"], "THESIS_002", "  ", "META_STATEMENT")


def test_freeze_requires_annotations(ds):
    datasets_mod.add_sample(ds["id"], raw_text="This essay will discuss crops.")
    datasets_mod.set_status(ds["id"], "ANNOTATING")
    with pytest.raises(datasets_mod.ValidationError):
        datasets_mod.freeze_dataset(ds["id"])


def _annotated_frozen_pair(detector="THESIS_002", label="META_STATEMENT",
                           topic=None, kws=None):
    ds = datasets_mod.create_dataset(name="F", detector_id=detector)
    s = datasets_mod.add_sample(ds["id"], raw_text="This essay will discuss crops.",
                                topic=topic, teacher_keywords=kws)
    annotations_mod.annotate(s["id"], detector, "R1", label)
    datasets_mod.set_status(ds["id"], "ANNOTATING")
    return datasets_mod.freeze_dataset(ds["id"]), s["id"]


def test_freeze_records_hash_and_status():
    ds, _sid = _annotated_frozen_pair()
    assert ds["status"] == "FROZEN"
    assert ds["frozen_at"]
    assert ds["dataset_hash"]
    assert len(ds["dataset_hash"]) == 64
    assert datasets_mod.verify_dataset_hash(ds["id"])["verified"] is True


def test_post_freeze_annotation_rejected():
    ds, sid = _annotated_frozen_pair()
    with pytest.raises(datasets_mod.ValidationError):
        annotations_mod.annotate(sid, "THESIS_002", "R2", "NOT_META_STATEMENT")
    with pytest.raises(datasets_mod.ValidationError):
        datasets_mod.add_sample(ds["id"], raw_text="Another sentence.")


def test_adjudication_preserves_original_label():
    ds = datasets_mod.create_dataset(name="ADJ", detector_id="THESIS_002")
    s = datasets_mod.add_sample(ds["id"], raw_text="This essay will discuss crops.")
    annotations_mod.annotate(s["id"], "THESIS_002", "R1", "META_STATEMENT")
    datasets_mod.set_status(ds["id"], "ANNOTATING")
    out = annotations_mod.adjudicate(s["id"], "NOT_META_STATEMENT", "re-read: direct claim")
    assert out["human_label"] == "META_STATEMENT"
    assert out["adjudicated_label"] == "NOT_META_STATEMENT"
    assert out["adjudication_notes"] == "re-read: direct claim"
    label, how = annotations_mod.effective_label(out)
    assert (label, how) == ("NOT_META_STATEMENT", "adjudicated")


def test_post_freeze_adjudication_rejected():
    ds, sid = _annotated_frozen_pair()
    with pytest.raises(datasets_mod.ValidationError):
        annotations_mod.adjudicate(sid, "NOT_META_STATEMENT", "too late")


def test_unclear_excluded_not_forced():
    ds = datasets_mod.create_dataset(name="U", detector_id="THESIS_002")
    s = datasets_mod.add_sample(ds["id"], raw_text="This essay, well, discusses?")
    annotations_mod.annotate(s["id"], "THESIS_002", "R1", "UNCLEAR")
    label, how = annotations_mod.effective_label(
        annotations_mod.latest_annotation(s["id"]))
    assert label is None and how == "excluded-unclear"


def test_single_rater_kappa_not_applicable():
    ds, _sid = _annotated_frozen_pair()
    status = annotations_mod.inter_rater_status(ds["id"])
    assert status["status"] == "N/A"
    assert status["display"] == protocols.SINGLE_RATER_DISPLAY
    assert "1.00" not in status["display"] and "100%" not in status["display"]


def test_two_rater_kappa_computed():
    ds = datasets_mod.create_dataset(name="K", detector_id="THESIS_002")
    s1 = datasets_mod.add_sample(ds["id"], raw_text="This essay will discuss crops.")
    s2 = datasets_mod.add_sample(ds["id"], raw_text="Farmers adapt to rainfall.")
    annotations_mod.annotate(s1["id"], "THESIS_002", "A", "META_STATEMENT")
    annotations_mod.annotate(s1["id"], "THESIS_002", "B", "META_STATEMENT")
    annotations_mod.annotate(s2["id"], "THESIS_002", "A", "NOT_META_STATEMENT")
    annotations_mod.annotate(s2["id"], "THESIS_002", "B", "META_STATEMENT")
    status = annotations_mod.inter_rater_status(ds["id"])
    assert status["status"] == "OK"
    # Hand check: Po=0.5, Pe=0.5*0.5+0.5*0.5=0.5 -> kappa=0.0
    assert status["value"] == pytest.approx(0.0)
    assert status["shared_samples"] == 2


def test_blinded_view_hides_predictions():
    ds = datasets_mod.create_dataset(name="B", detector_id="THESIS_002")
    s = datasets_mod.add_sample(ds["id"], raw_text="This essay will discuss crops.")
    view = annotations_mod.blinded_sample_view(s["id"])
    blob = str(view).lower()
    for forbidden in ("prediction", "similarity", "cosine", "fired",
                      "correct", "matrix", "confidence"):
        assert forbidden not in blob, forbidden
    assert view["raw_text"] == "This essay will discuss crops."
    assert "META_STATEMENT" in view["allowed_labels"]
