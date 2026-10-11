"""Phase 7A annotation protocols + detector registry.

Versioned labeling instructions. If definitions change, create V2 —
never silently alter already-completed labels.
"""

from __future__ import annotations

THESIS002_PROTOCOL_V1 = "THESIS002_PROTOCOL_V1"
TOPIC_PROTOCOL_V1 = "TOPIC_PROTOCOL_V1"

THESIS002_PROTOCOL_TEXT = """THESIS_002 annotation protocol V1.
Question: does the target sentence contain a meta-discourse statement
where the writer announces what the essay/paper/text will do, rather
than directly expressing the academic claim?
Labels: META_STATEMENT (announces the text's own actions, e.g. forms
like "This essay will discuss..." / "This paper examines..." / "In this
essay, I will explain..."), NOT_META_STATEMENT (directly expresses a
claim, evidence, or reasoning about the subject matter), UNCLEAR
(genuinely cannot decide reliably; will be adjudicated or excluded
with reason, never silently forced into a class).
Judge the communicative function, not only literal phrases."""

TOPIC_PROTOCOL_TEXT = """TOPIC_CLASSIFIER annotation protocol V1.
Assess the semantic/topic relationship between the ASSIGNMENT TOPIC
and the STUDENT TEXT, independently of any system score. Do NOT use
numeric thresholds (0.30 / 0.60) to define labels.
WEAK: text has little meaningful relationship to the assigned topic
or discusses a substantially different subject.
MODERATE: text clearly addresses the general topic but coverage,
focus, or conceptual connection is partial.
STRONG: text consistently and directly addresses the central topic
and its major concepts.
UNCLEAR (genuinely cannot decide reliably) will be adjudicated or
excluded with reason, never silently forced into a class."""

# detector_id -> validation contract. Pilot scope: these two detectors only.
DETECTORS = {
    "THESIS_002": {
        "validation_type": "BINARY",
        "labels": ["META_STATEMENT", "NOT_META_STATEMENT"],
        "positive_label": "META_STATEMENT",
        "negative_label": "NOT_META_STATEMENT",
        # System emits positive/negative; mapped into label space for cells.
        "system_positive": "META_STATEMENT",
        "system_negative": "NOT_META_STATEMENT",
        "protocol_version": THESIS002_PROTOCOL_V1,
        "protocol_text": THESIS002_PROTOCOL_TEXT,
    },
    "TOPIC_CLASSIFIER": {
        "validation_type": "MULTICLASS",
        "labels": ["WEAK", "MODERATE", "STRONG"],
        "protocol_version": TOPIC_PROTOCOL_V1,
        "protocol_text": TOPIC_PROTOCOL_TEXT,
    },
}

DATASET_STATUSES = ("DRAFT", "ANNOTATING", "FROZEN", "EVALUATED", "ARCHIVED")

# Allowed forward transitions. ARCHIVED reachable from any status.
STATUS_TRANSITIONS = {
    "DRAFT": ("ANNOTATING", "ARCHIVED"),
    "ANNOTATING": ("FROZEN", "ARCHIVED"),
    "FROZEN": ("EVALUATED", "ARCHIVED"),
    "EVALUATED": ("ARCHIVED",),
    "ARCHIVED": (),
}

RUN_ELIGIBLE_STATUSES = ("FROZEN", "EVALUATED")

PROVENANCE_VALUES = (
    "HUMAN_CREATED_RESEARCH_SAMPLE",
    "DEIDENTIFIED_STUDENT_SAMPLE",
    "OPEN_CORPUS",
    "DEMO_FIXTURE",
    "OTHER",
)

DEMO_BANNER = "DEMO DATA \u2014 NOT RESEARCH RESULTS."

SINGLE_RATER_DISPLAY = "INTER-RATER RELIABILITY: NOT APPLICABLE \u2014 SINGLE RATER"
NO_ANNOTATIONS_DISPLAY = "INTER-RATER RELIABILITY: NOT APPLICABLE \u2014 NO HUMAN ANNOTATIONS YET"
