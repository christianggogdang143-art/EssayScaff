"""Validation ruleset snapshot (VR-2: VR-1 detectors plus Stage 4 REFLECT rules).

Builds the reproducibility record embedded in every validation run:
application/library versions, the frozen threshold set, and a sha256 over
the rules/ directory (the detector identity anchor; this repo has no git).
Any detector/threshold change requires a NEW ruleset version + new
evaluation — never a silent edit under the same version.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import config

# Explicit, reviewable list of frozen research-critical constants.
# Add new entries here ONLY together with a ruleset version bump.
FROZEN_THRESHOLDS = [
    "REPEATED_OPENING_THRESHOLD",
    "RUNON_LONG_SENTENCE_TOKENS",
    "RUNON_MIN_TOKENS",
    "KEYWORD_CANDIDATE_POS",
    "KEYWORD_MIN_LEMMA_LEN",
    "KEYWORD_EXCLUDED_LEMMAS",
    "KEYWORD_TOP_N",
    "KEYWORD_FREQ_WEIGHT",
    "KEYWORD_DIST_WEIGHT",
    "KEYWORD_POS_WEIGHTS",
    "WORDNET_MAX_PER_TERM",
    "TFIDF_MIN_DF",
    "COSINE_TOLERANCE",
    "PREWRITE_MIN_TOKENS",
    "PREWRITE_BROAD_MAX_KEYWORDS",
    "PREWRITE_MIN_CONCEPTS_RELATIONSHIP",
    "PREWRITE_MIN_CONCEPTS_FOCUSED",
    "STAGE1_MAX_PROMPTS",
    "PREWRITE_PRIORITY",
    "PREWRITE_CAUSAL_MARKERS",
    "PREWRITE_ISSUE_LEMMAS",
    "PREWRITE_STAKEHOLDERS",
    "STAGE1_MIN_SENTENCES",
    "THESIS_BROAD_MAX_TOKENS",
    "THESIS_BROAD_MAX_KEYWORDS",
    "THESIS_SCOPE_MIN_VERBS",
    "THESIS_OVERLOAD_MIN_KEYWORDS",
    "THESIS_OVERLOAD_MIN_VERBS",
    "STAGE2_MAX_PROMPTS",
    "THESIS_STANCE_LEMMAS",
    "THESIS_VAGUE_LEMMAS",
    "STAGE2_ALIGN_HIGH",
    "STAGE2_ALIGN_LOW",
    "OUTLINE_MIN_POINTS",
    "OUTLINE_MAX_POINTS",
    "OUTLINE_MIN_POINT_TOKENS",
    "OUTLINE_ALIGN_DIRECT_STRONG",
    "OUTLINE_ALIGN_COSINE_STRONG",
    "OUTLINE_ALIGN_COSINE_WEAK",
    "OUTLINE_DUP_JACCARD_POINTS",
    "OUTLINE_DUP_COSINE_POINTS",
    "OUTLINE_DUP_JACCARD_DETAILS",
    "OUTLINE_OVERLOAD_VERBS",
    "OUTLINE_OVERLOAD_KEYWORDS",
    "OUTLINE_COVERAGE_MIN",
    "STAGE3_MAX_PROMPTS",
    "THESIS_BROAD_OBJECTS",
    "THESIS_MIN_SUPPORT_MATCHES",
    "TOPIC_MODERATE_THRESHOLD",
    "TOPIC_STRONG_THRESHOLD",
    "STAGE4_RECURRING_MIN_PRIOR",
    "STAGE4_STABLE_MIN_QUIET",
    "STAGE4_MIN_REVISIONS_FOR_INDEPENDENT",
    "STAGE4_RECURRING_MAJOR_FOR_HIGH",
    "STAGE4_MAX_PROMPTS_HIGH",
    "STAGE4_MAX_PROMPTS_MODERATE",
    "STAGE4_MAX_PROMPTS_LIGHT",
    "STAGE4_MAX_PROMPTS_INDEPENDENT",
    "STAGE4_NOTE_MAX_CHARS",
]


def _rules_dir_hash() -> str | None:
    """sha256 over all rules/*.py bytes (sorted). None if unreadable."""
    try:
        rules_dir = Path(__file__).resolve().parent.parent.parent / "rules"
        digest = hashlib.sha256()
        for path in sorted(rules_dir.glob("*.py")):
            digest.update(path.read_bytes())
        return digest.hexdigest()
    except Exception:
        return None


def _lib_version(module_name: str, attr: str = "__version__") -> str | None:
    try:
        import importlib

        module = importlib.import_module(module_name)
        return getattr(module, attr, None)
    except Exception:
        return None


def _model_version() -> str | None:
    try:
        from services.transparency import spacy_model_version

        return spacy_model_version(config.SPACY_MODEL)
    except Exception:
        return None


VALIDATION_CODE_VERSION = "7A.1"

METRICS_VERSION = "7A.1"

# Pinned VR-2 freeze values (verified stable across processes in Phase 7B).
# No validation run may execute unless the live implementation reproduces
# BOTH hashes. Never refresh these silently: a new detector/threshold set
# requires a NEW ruleset version + new pinned values.
PINNED_VR2_RULES_HASH = "8ac38bf3b5b01354f679d1dbb20c3824bdbc9eb517a9ecdec543df1e85fe42c0"
PINNED_VR2_CONFIG_HASH = "401f3a4bce3910ec8ca63d846ddce84a9e61881fb619bdf75778ac7e3e95c915"


def verify_vr2_freeze() -> dict:
    """Compare live implementation against the pinned VR-2 freeze values."""
    live_rules = _rules_dir_hash()
    live_config = config_hash()
    problems = []
    if live_rules != PINNED_VR2_RULES_HASH:
        problems.append("rules_dir_sha256 differs from pinned VR-2 value")
    if live_config != PINNED_VR2_CONFIG_HASH:
        problems.append("config_hash differs from pinned VR-2 value")
    return {"rules_match": live_rules == PINNED_VR2_RULES_HASH,
            "config_match": live_config == PINNED_VR2_CONFIG_HASH,
            "problems": problems,
            "live_rules_hash": live_rules,
            "live_config_hash": live_config}


def config_hash() -> str | None:
    """sha256 over the frozen threshold set + ruleset version.

    Stored with every prediction and run so a later threshold change is
    detectable: same ruleset_version + different config_hash means the
    frozen configuration was altered.
    """
    try:
        canonical = {
            "ruleset_version": getattr(config, "VALIDATION_RULESET_VERSION", "<missing>"),
            # Sets normalize to sorted lists: str(set) order varies per
            # process (hash randomization) and must never affect the hash.
            "thresholds": _jsonable_thresholds(),
        }
        import json

        return hashlib.sha256(
            json.dumps(canonical, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()
    except Exception:
        return None


def _tfidf_params() -> dict | None:
    """Effective TF-IDF parameters from the live configured vectorizer."""
    try:
        from services import similarity

        return similarity.effective_vectorizer_params(
            similarity.default_vectorizer())
    except Exception:
        return None


def _jsonable_thresholds() -> dict:
    out = {}
    for name in FROZEN_THRESHOLDS:
        value = getattr(config, name, "<missing>")
        try:
            out[name] = sorted(value) if isinstance(value, (set, frozenset)) else value
        except Exception:
            out[name] = str(value)
    return out


def freeze_record() -> dict:
    """Explicit VR-2 validation freeze record. Never raises."""
    import datetime
    import sys

    return {
        "ruleset_version": getattr(config, "VALIDATION_RULESET_VERSION", "<missing>"),
        "status": "FROZEN_FOR_VALIDATION",
        "frozen_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "app_version": getattr(config, "APP_VERSION", "<missing>"),
        "python_version": sys.version.split()[0],
        "spacy_version": _lib_version("spacy"),
        "spacy_model": getattr(config, "SPACY_MODEL", "<missing>"),
        "spacy_model_version": _model_version(),
        "nltk_version": _lib_version("nltk"),
        "sklearn_version": _lib_version("sklearn"),
        "languagetool": _lib_version("language_tool_python"),
        "thresholds": _jsonable_thresholds(),
        "config_hash": config_hash(),
        "rules_dir_sha256": _rules_dir_hash(),
        "tfidf_effective_params": _tfidf_params(),
        "validation_code_version": VALIDATION_CODE_VERSION,
        "metrics_version": METRICS_VERSION,
    }


def build_snapshot() -> dict:
    """Collect the full reproducibility record. Never raises."""
    import sys

    thresholds = {}
    for name in FROZEN_THRESHOLDS:
        value = getattr(config, name, "<missing>")
        try:
            thresholds[name] = sorted(value) if isinstance(value, (set, frozenset)) else value
        except Exception:
            thresholds[name] = str(value)
    return {
        "ruleset_version": getattr(config, "VALIDATION_RULESET_VERSION", "<missing>"),
        "app_version": getattr(config, "APP_VERSION", "<missing>"),
        "git_commit": None,
        "python_version": sys.version.split()[0],
        "spacy_version": _lib_version("spacy"),
        "spacy_model": getattr(config, "SPACY_MODEL", "<missing>"),
        "spacy_model_version": _model_version(),
        "nltk_version": _lib_version("nltk"),
        "sklearn_version": _lib_version("sklearn"),
        "languagetool": _lib_version("language_tool_python"),
        "rules_dir_sha256": _rules_dir_hash(),
        "tfidf_effective_params": _tfidf_params(),
        "thresholds": thresholds,
    }
