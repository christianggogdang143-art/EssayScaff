"""Terminology guards: user-facing copy must describe the actual implementation.

These tests lock the Issue 1-7 wording fixes. They scan copy (templates,
frontend JS, route strings), never detector logic. Denials ("not an essay
grade") are legitimate and must not trip the guards — bans target positive
misleading claims only.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INDEX = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
JS = {p.name: p.read_text(encoding="utf-8")
      for p in sorted((ROOT / "static" / "js").glob("*.js"))}
WALK = JS["walkthrough.js"]
ARCH = (ROOT / "CURRENT_ARCHITECTURE.md").read_text(encoding="utf-8")


def test_no_stopword_removal_claims():
    for name, src in [("index.html", INDEX)] + sorted(JS.items()):
        for pat in ("Stopword Removal", "stopword removal",
                    "remove stopwords", "removes stopwords",
                    "stopwords are removed", "stopwords are deleted"):
            assert pat not in src, f"{name}: misleading {pat!r}"
    assert "NOT_MEASURED_SEPARATELY" not in INDEX  # sanity: walkthrough-only token


def test_stopword_honest_wording_present():
    assert "Flagged, not deleted" in WALK
    assert "STOPWORD IDENTIFICATION (SELECTIVE FILTERING, NOT REMOVAL)" in WALK


def test_no_holistic_score_claims():
    blob = INDEX + "\n".join(JS.values())
    for pat in ("Coherence Score", "Clarity Score", "Tone Score",
                "Essay Score", "Overall Essay Score", "overall essay score",
                "Coherence:", "CLARITY:"):
        assert pat not in blob, f"holistic metric claim {pat!r}"
    # Denials must exist instead.
    assert "not an essay grade" in WALK


def test_no_ai_understanding_claims():
    for name, src in [("index.html", INDEX)] + sorted(JS.items()):
        for i, line in enumerate(src.splitlines(), start=1):
            if re.search(r"understand(s|ing)?\b", line, re.IGNORECASE):
                assert re.search(r"\b(not|n't|never|no)\b", line, re.IGNORECASE), \
                    f"{name}:{i} claims understanding without negation: {line.strip()[:100]}"


def test_ai_terminology_line_present():
    assert "does not use a generative language model" in WALK
    assert "NLP-supported, rule-based writing scaffolding system" in WALK


def test_knowledge_base_clarification_present():
    assert "teacher-guided concept provider" in WALK
    assert "not a large academic knowledge database" in WALK
    for name, src in [("index.html", INDEX)] + sorted(JS.items()):
        assert "Academic Knowledge Base" not in src, f"{name}: overstated KB label"


def test_lexical_evidence_wording_present():
    assert "based on lexical TF-IDF/cosine evidence" in WALK
    assert "not a semantic-quality score" in WALK


def test_unity_limitation_noted():
    # Phrase spans two JS string literals; check both halves.
    assert "rule-based structural" in WALK
    assert "indicators derived from lexical concept alignments" in WALK
    assert "not deep semantic judgments" in WALK


def test_architecture_doc_present_and_canonical():
    assert "Code is the source of truth" in ARCH
    assert "Stage 1 — Idea Generation / Pre-Writing" in ARCH
    assert "Stage 2 — Thesis Formulation" in ARCH
    assert "Stage 3 — Outline Development" in ARCH
    assert "Stage 4 — Reflection and Revision" in ARCH
    assert "Introduction, Body, and Conclusion describe" in ARCH
    assert "does **not** use a generative language model" in ARCH


def test_nav_stages_canonical():
    assert 'data-ws="stage1Section"' in INDEX
    tabs = re.findall(r'data-ws="([a-zA-Z0-9]+)"', INDEX)
    assert "stage1Section" in tabs and "studentSection" in tabs
    for bad in ("Introduction → Body", "Body → Conclusion"):
        assert bad not in INDEX
