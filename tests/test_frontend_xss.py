"""XSS regression tests (F-01, F-02): hostile payloads must render as inert
text, never as live DOM elements. Executes the REAL shipped JS in jsdom;
see tests/frontend_smoke/xss.js for the harness and its documented limits
(no subresource loading, so handler *firing* is proven separately by the
absence of live handler attributes, not by execution)."""

import json
import os
import subprocess
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
XSS_JS = ROOT / "tests" / "frontend_smoke" / "xss.js"


def _harness_dir() -> Path:
    d = Path(tempfile.gettempdir()) / "opencode" / "jsharness"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _ensure_jsdom() -> Path:
    d = _harness_dir()
    marker = d / "node_modules" / "jsdom" / "package.json"
    if not marker.exists():
        subprocess.run(
            ["npm", "install", "--prefix", str(d), "--no-save",
             "--no-audit", "--no-fund", "jsdom"],
            check=True, capture_output=True, timeout=300)
    assert marker.exists(), "jsdom is required for frontend XSS tests"
    return d


@pytest.fixture(scope="module")
def xss_verdict():
    harness = _ensure_jsdom()
    env = dict(os.environ, JSDOM_PATH=str(
        harness / "node_modules" / "jsdom"))
    proc = subprocess.run(
        ["node", str(XSS_JS),
         "--htmlroot", str(ROOT / "templates"),
         "--jsdir", str(ROOT / "static" / "js")],
        capture_output=True, text=True, timeout=180, env=env,
        cwd=str(ROOT))
    assert proc.returncode == 0, (
        f"xss harness failed (exit {proc.returncode}):\n"
        f"STDOUT: {proc.stdout[-3000:]}\nSTDERR: {proc.stderr[-2000:]}")
    return json.loads(proc.stdout.strip().splitlines()[-1])["verdict"]


def _flow(xss_verdict, name):
    assert name in xss_verdict, f"flow {name} missing from harness verdict"
    assert xss_verdict[name]["ok"] is True, (
        f"flow {name} failed: {xss_verdict[name].get('error')}")


def test_xss_validation_errors_inert(xss_verdict):
    _flow(xss_verdict, "xss_validation_errors_inert")


def test_xss_validation_datasets_inert(xss_verdict):
    _flow(xss_verdict, "xss_validation_datasets_inert")


def test_xss_stage3_outline_values_literal(xss_verdict):
    _flow(xss_verdict, "xss_stage3_outline_values_literal")


def test_xss_stage3_detail_and_ampersand(xss_verdict):
    _flow(xss_verdict, "xss_stage3_detail_and_ampersand")
