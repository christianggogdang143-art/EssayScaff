"""Frontend consistency: every DOM id referenced in static/js must exist in
templates/index.html (or be explicitly allowlisted as dynamically created).
Guards the exact bug class where deleted elements crashed renders."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HTML = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
HTML_RESEARCH = (ROOT / "templates" / "validation.html").read_text(encoding="utf-8")
JS_DIR = ROOT / "static" / "js"

# Elements created at runtime via innerHTML (verified present in renderers).
ALLOW_EXACT = {
    "stepCode", "stepCodeBtn",
    "kwCode", "kwCodeBtn",
    "wnCode", "wnCodeBtn",
    "simCode", "simCodeBtn",
    "ltCode", "ltCodeBtn",
    "wt-kwtop",  # walkthrough keyword worked-display slot (rendered by sKeywords)
    "dashSnapTime",  # dashboard snapshot active-time slot (rendered by refreshSnapshot)
}
ALLOW_PREFIX = ("chain-", "rulecode-")


def _html_ids():
    # Student workspace + researcher workspace (validation.js targets live
    # only in validation.html; the bug class guarded is identical).
    return set(re.findall(r'id="([A-Za-z0-9_-]+)"', HTML + HTML_RESEARCH))


def _js_ids():
    found = set()
    for path in sorted(JS_DIR.glob("*.js")):
        src = path.read_text(encoding="utf-8")
        for pat in (r'getElementById\("([A-Za-z0-9_-]+)"\)',
                    r'\$\("([A-Za-z0-9_-]+)"\)',
                    r'querySelector(?:All)?\("#([A-Za-z0-9_-]+)'):
            found.update(re.findall(pat, src))
    return found


def test_all_js_targets_exist_in_html():
    html_ids = _html_ids()
    missing = sorted(
        i for i in _js_ids()
        if i not in html_ids
        and i not in ALLOW_EXACT
        and not i.startswith(ALLOW_PREFIX)
    )
    assert not missing, f"JS references missing DOM ids: {missing}"


def test_workspace_tabs_cover_all_sections():
    assert 'id="workspaceTabs"' in HTML
    for section in ("stage1Section", "stage2Section", "stage3Section", "studentSection"):
        assert f'data-ws="{section}"' in HTML, section
        assert f'id="{section}"' in HTML, section
    # Exactly one workspace section visible by default (Stage 1).
    for section in ("stage2Section", "stage3Section", "studentSection"):
        m = re.search(rf'<section class="card" id="{section}"[^>]*>', HTML)
        assert m and "hidden" in m.group(0), section
    css = (ROOT / "static" / "css" / "style.css").read_text(encoding="utf-8")
    assert re.search(r"\[hidden\]\s*\{\s*display\s*:\s*none", css), (
        "hidden sections must be visually hidden, not just semantically marked")
