"""Pre-testing hardening: gates, adjudication freeze, hash enforcement,
markers, env snapshot, source dropdown, honest timings, CRLF, TF-IDF
provenance, rater wording. Detector behavior intentionally untouched."""

import json
import platform
import subprocess
import sys
from pathlib import Path

import pytest

import config
from app import create_app
from services import db
from services import grammar_service
from services import similarity
from services import source_view
from services.validation import annotations as annotations_mod
from services.validation import datasets as datasets_mod
from services.validation import demo as demo_mod
from services.validation import io as io_mod
from services.validation import protocols
from services.validation import runs as runs_mod
from services.validation import snapshot as snapshot_mod

ROOT = Path(__file__).resolve().parent.parent

TOPIC = "Effects of climate change on agriculture"
KWS = ["climate", "agriculture", "farmers", "crop", "temperature", "rainfall"]
READY_IDEA = ("Climate change affects crop production because extreme temperatures "
              "and irregular rainfall create difficulties for farmers.")
SHORT_IDEA = "Climate."
READY_THESIS = ("Extreme temperatures and irregular rainfall reduce crop production "
                "and create significant challenges for farmers.")


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "db_path", lambda: tmp_path / "test.db")
    application = create_app(prewarm=False)
    application.config.update(TESTING=True)
    return application.test_client()


def _ready_s1(client):
    d = client.post("/api/stage1/analyze", json={
        "text": READY_IDEA, "topic": TOPIC,
        "teacher_keywords": KWS}).get_json()
    assert d["readiness"]["stage2_allowed"] is True
    return d["session_id"]


def _short_s1(client):
    d = client.post("/api/stage1/analyze", json={
        "text": SHORT_IDEA, "topic": TOPIC,
        "teacher_keywords": KWS}).get_json()
    assert d["readiness"]["stage2_allowed"] is False
    return d["session_id"]


# ------------------------------------------------ stage gates
def test_stage2_linked_not_ready_refused(client):
    sid = _short_s1(client)
    res = client.post("/api/stage2/analyze", json={
        "text": READY_THESIS, "stage1_session_id": sid})
    assert res.status_code == 403
    assert "stage2_allowed" in res.get_json()["error"]


def test_stage2_linked_ready_allowed(client):
    sid = _ready_s1(client)
    res = client.post("/api/stage2/analyze", json={
        "text": READY_THESIS, "stage1_session_id": sid})
    assert res.status_code == 200
    assert res.get_json()["stage1_session_id"] == sid


def test_stage2_unlinked_direct_path_documented(client):
    from services import stage2 as stage2_service

    res = client.post("/api/stage2/analyze", json={"text": READY_THESIS})
    assert res.status_code == 200
    assert "Unlinked" in stage2_service.LINK_POLICY


def test_stage4_linked_not_ready_refused(client):
    s3 = client.post("/api/stage3/analyze", json={
        "thesis": READY_THESIS,
        "outline": [{"text": "Only one point here.", "details": []}]}).get_json()
    assert s3["readiness"]["stage4_allowed"] is False
    res = client.post("/api/stage4/reflect", json={
        "stage3_session_id": s3["session_id"]})
    assert res.status_code == 403


def test_stage4_unlinked_conservative_path(client):
    res = client.post("/api/stage4/reflect", json={})
    assert res.status_code == 200
    assert res.get_json()["scaffold"]["level"] == 2


# ------------------------------------------------ adjudication freeze
def _frozen_pair(detector="THESIS_002", label="META_STATEMENT"):
    ds = datasets_mod.create_dataset(name="HZ", detector_id=detector)
    s = datasets_mod.add_sample(ds["id"], raw_text="This essay will discuss crops.")
    annotations_mod.annotate(s["id"], detector, "R1", label)
    datasets_mod.set_status(ds["id"], "ANNOTATING")
    return datasets_mod.freeze_dataset(ds["id"]), s["id"]


def test_evaluated_dataset_adjudication_rejected(client):
    ds, sid = _frozen_pair()
    runs_mod.create_run(ds["id"])
    assert datasets_mod.get_dataset(ds["id"])["status"] == "EVALUATED"
    with pytest.raises(datasets_mod.ValidationError):
        annotations_mod.adjudicate(sid, "NOT_META_STATEMENT", "too late")


# ------------------------------------------------ hash enforcement
def test_pre_run_rules_hash_drift_rejected(client, monkeypatch):
    ds, _sid = _frozen_pair()
    monkeypatch.setattr(snapshot_mod, "_rules_dir_hash", lambda: "0" * 64)
    with pytest.raises(datasets_mod.ValidationError) as exc:
        runs_mod.create_run(ds["id"])
    assert "VR2_FREEZE_DRIFT_DETECTED" in str(exc.value)


def test_pre_run_config_hash_drift_rejected(client, monkeypatch):
    ds, _sid = _frozen_pair()
    monkeypatch.setattr(config, "TOPIC_MODERATE_THRESHOLD", 0.99)
    with pytest.raises(datasets_mod.ValidationError) as exc:
        runs_mod.create_run(ds["id"])
    assert "VR2_FREEZE_DRIFT_DETECTED" in str(exc.value)


def test_unchanged_vr2_run_accepted(client):
    ds, _sid = _frozen_pair()
    run = runs_mod.create_run(ds["id"])
    assert run["status"] == "COMPLETE"
    assert run["ruleset_hash"] == snapshot_mod.PINNED_VR2_RULES_HASH
    assert run["config_hash"] == snapshot_mod.PINNED_VR2_CONFIG_HASH


def test_config_hash_cross_process_stable():
    code = ("from services.validation.snapshot import config_hash; "
            "print(config_hash())")
    outs = []
    for _ in range(2):
        proc = subprocess.run([sys.executable, "-c", code],
                              capture_output=True, text=True, timeout=120,
                              cwd=str(ROOT))
        assert proc.returncode == 0, proc.stderr[-500:]
        outs.append(proc.stdout.strip())
    assert outs[0] == outs[1] == snapshot_mod.PINNED_VR2_CONFIG_HASH


# ------------------------------------------------ markers
def _demo_run(client):
    pair = demo_mod.ensure_demo_datasets()
    ds = datasets_mod.freeze_dataset(pair["binary"]["id"])
    return runs_mod.create_run(ds["id"])


def _formal_run():
    ds = datasets_mod.create_dataset(name="HF", detector_id="THESIS_002")
    for text, label in (("This essay will discuss crops.", "META_STATEMENT"),
                        ("Farmers adapt to rainfall.", "NOT_META_STATEMENT")):
        s = datasets_mod.add_sample(ds["id"], raw_text=text)
        annotations_mod.annotate(s["id"], "THESIS_002", "R1", label)
    datasets_mod.set_status(ds["id"], "ANNOTATING")
    datasets_mod.freeze_dataset(ds["id"])
    return runs_mod.create_run(ds["id"])


def test_demo_markers_everywhere(client):
    run = _demo_run(client)
    listed = next(r for r in runs_mod.list_runs() if r["id"] == run["id"])
    assert listed["is_demo"] is True
    assert listed["result_type"] == "DEMO_DATA_NOT_RESEARCH_RESULTS"
    detail = runs_mod.get_run_detail(run["id"])
    assert detail["run"]["is_demo"] is True
    assert detail["run"]["result_type"] == "DEMO_DATA_NOT_RESEARCH_RESULTS"
    env = io_mod.export_run_json(run["id"])
    assert env["is_demo"] is True
    assert env["result_type"] == "DEMO_DATA_NOT_RESEARCH_RESULTS"
    assert "NOT RESEARCH RESULTS" in env["demo_banner"]
    csv_text = io_mod.export_run_csv(run["id"])
    assert csv_text.splitlines()[0].startswith("# DEMO DATA")
    assert "result_type=DEMO_DATA_NOT_RESEARCH_RESULTS" in csv_text


def test_formal_markers_in_artifacts(client):
    run = _formal_run()
    listed = next(r for r in runs_mod.list_runs() if r["id"] == run["id"])
    assert listed["is_demo"] is False
    assert listed["result_type"] == "FORMAL_HUMAN_LABELED_VALIDATION"
    assert listed["dataset_name"] is not None
    env = io_mod.export_run_json(run["id"])
    assert env["is_demo"] is False
    assert "demo_banner" not in env
    csv_text = io_mod.export_run_csv(run["id"])
    assert csv_text.splitlines()[0].startswith("# FORMAL")
    ds_csv = io_mod.export_dataset_csv(run["dataset_id"])
    assert ds_csv.splitlines()[0].startswith("# FORMAL")


# ------------------------------------------------ environment
def test_python_version_recorded(client):
    rec = snapshot_mod.freeze_record()
    assert rec["python_version"] == platform.python_version().split()[0]
    snap = snapshot_mod.build_snapshot()
    assert snap["python_version"] == platform.python_version().split()[0]
    run = _formal_run()
    detail = runs_mod.get_run_detail(run["id"])
    assert detail["run"]["environment"]["python"] == \
        platform.python_version().split()[0]
    for key in ("spacy_version", "spacy_model", "nltk_version", "sklearn_version"):
        assert key in detail["run"]["environment"]
    assert detail["run"]["environment"]["spacy_version"] == "3.7.5"


# ------------------------------------------------ source dropdown
def test_stage4_sources_reachable(client):
    js = (ROOT / "static" / "js" / "transparency.js").read_text(encoding="utf-8")
    assert "services/reflection.py" in js
    assert "services/stage4.py" in js
    assert "services/reflection.py" in source_view.WHITELIST
    assert "services/stage4.py" in source_view.WHITELIST
    for f in ("services/reflection.py", "services/stage4.py"):
        res = client.get("/api/source", query_string={"file": f})
        assert res.status_code == 200, f


# ------------------------------------------------ honest timings
def test_unmeasured_gears_honest(client):
    d1 = client.post("/api/stage1/analyze", json={"text": READY_IDEA}).get_json()
    gear1 = d1["stage1_transparency"][0]
    assert gear1["timing_ms"] is None
    assert gear1["timing_status"] == "NOT_MEASURED_SEPARATELY"
    d2 = client.post("/api/stage2/analyze", json={"text": READY_THESIS}).get_json()
    by_id = {g["id"]: g for g in d2["stage2_transparency"]}
    assert by_id["thesis_input"]["timing_ms"] is None
    assert by_id["stage1_alignment_check"]["timing_ms"] is None
    assert by_id["thesis_rule_evaluation"]["timing_ms"] >= 0
    for key in ("rules_ms", "prompts_ms", "readiness_ms", "persist_ms"):
        assert d1["timings"][key] >= 0


# ------------------------------------------------ CRLF offsets
class _FakeMatch:
    def __init__(self, offset, length, text):
        self.category = "Grammar"
        self.rule_id = "FAKE_RULE"
        self.message = "Fake finding."
        self.offset = offset
        self.error_length = length
        self.matched_text = text
        self.replacements = ["x"]


class _FakeTool:
    def __init__(self, matches):
        self._matches = matches

    def check(self, _text):
        return self._matches


def test_crlf_offsets_mapped_to_unified_coordinates(client, monkeypatch):
    raw = "AB.\r\nCD have EF."
    # "have" starts at raw offset 8; unified text drops the \r -> offset 7.
    monkeypatch.setattr(grammar_service, "_tool",
                        _FakeTool([_FakeMatch(8, 4, "have")]))
    sentences = [{"number": 1, "text": "AB.\n", "start": 0, "end": 4},
                 {"number": 2, "text": "CD have EF.", "start": 4, "end": 14}]
    out = grammar_service.check_grammar(raw, sentences)
    assert out["status"] == "available"
    assert "coordinate_system" in out and "newline-unified" in out["coordinate_system"]
    issue = out["issues"][0]
    assert issue["offset"] == 7
    assert issue["length"] == 4
    assert issue["sentence"] == 2
    unified = raw.replace("\r\n", "\n").replace("\r", "\n")
    assert unified[issue["offset"]:issue["offset"] + issue["length"]] == "have"


def test_no_crlf_offsets_identity(client, monkeypatch):
    raw = "They have error here."
    monkeypatch.setattr(grammar_service, "_tool",
                        _FakeTool([_FakeMatch(5, 4, "have")]))
    out = grammar_service.check_grammar(
        raw, [{"number": 1, "text": raw, "start": 0, "end": len(raw)}])
    assert out["issues"][0]["offset"] == 5
    assert out["issues"][0]["sentence"] == 1


# ------------------------------------------------ TF-IDF provenance
def test_vectorizer_params_explicit_and_effective():
    vec = similarity.vectorize("climate change agriculture", "climate farmers crop")
    params = vec["vectorizer_params"]
    assert params["smooth_idf"] is True
    assert params["norm"] == "l2"
    assert params["sublinear_tf"] is False
    assert params["use_idf"] is True
    assert params["min_df"] == 1
    assert params["tokenizer"] == "str.split"
    assert list(params) == list(similarity.effective_vectorizer_params(
        similarity.default_vectorizer()))
    assert "smooth_idf=True" in similarity.CORPUS_DESIGN
    assert vec["dimensions"] > 0
    rec = snapshot_mod.freeze_record()
    assert rec["tfidf_effective_params"]["smooth_idf"] is True


# ------------------------------------------------ rater wording
def test_zero_annotator_wording(client):
    ds = datasets_mod.create_dataset(name="Z0", detector_id="THESIS_002")
    status = annotations_mod.inter_rater_status(ds["id"])
    assert status["status"] == "N/A"
    assert status["display"] == protocols.NO_ANNOTATIONS_DISPLAY
    assert "NO HUMAN ANNOTATIONS YET" in status["display"]
