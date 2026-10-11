"""Phase 7A DEMO fixtures — framework demonstration only.

Every demo dataset carries provenance DEMO_FIXTURE and the banner
"DEMO DATA — NOT RESEARCH RESULTS." Demo metrics must NEVER be
presented as EssayScaff findings.

Human labels below follow the V1 protocol rubrics; system outputs
are the observed frozen VR-2 predictions for these exact inputs
(deterministic — re-running yields identical cells).
"""

from __future__ import annotations

from services.validation import annotations as annotations_mod
from services.validation import datasets as datasets_mod
from services.validation import protocols

TOPIC = "Effects of climate change on agriculture"
KWS = ["climate", "agriculture", "farmers", "crop", "temperature", "rainfall"]

DEMO_ANNOTATOR = "DEMO_FIXTURE"

# (raw_text, human_label, notes). Observed VR-2: TP=2, TN=2, FP=1, FN=1.
DEMO_BINARY_SAMPLES = [
    ("This essay will discuss climate change and agriculture.",
     "META_STATEMENT", "Canonical meta announcement; pattern fires."),
    ("This paper will examine the effects of drought on farmers.",
     "META_STATEMENT", "Canonical meta announcement; pattern fires."),
    ("Extreme temperatures reduce crop production.",
     "NOT_META_STATEMENT", "Direct claim about the subject matter."),
    ("Farmers adapt to changing rainfall patterns.",
     "NOT_META_STATEMENT", "Direct claim about the subject matter."),
    ("In this essay assignment, the margins must be one inch.",
     "NOT_META_STATEMENT",
     "Boundary case: matches a surface pattern but states a formatting "
     "rule, not what the essay will argue. Expected system FALSE POSITIVE."),
    ("My paper sets out to explore the causes of drought.",
     "META_STATEMENT",
     "Paraphrased announcement with no literal pattern match. "
     "Expected system FALSE NEGATIVE."),
]

# (raw_text, human_label, notes). Observed VR-2 cells (rows=system):
#   SYSTEM WEAK:     WEAK=2, MODERATE=0, STRONG=0
#   SYSTEM MODERATE: WEAK=0, MODERATE=2, STRONG=1
#   SYSTEM STRONG:   WEAK=0, MODERATE=0, STRONG=1
DEMO_MULTICLASS_SAMPLES = [
    ("The effects of climate change on agriculture concern farmers: crop "
     "temperature and rainfall shape agriculture under a changing climate.",
     "STRONG", "Direct, consistent coverage of the central topic."),
    ("Agriculture and climate: temperature and rainfall determine crop "
     "outcomes for farmers. Climate change raises temperature variability, "
     "so farmers adjust crop selection and agriculture practices to "
     "rainfall availability.",
     "STRONG",
     "Consistent coverage of topic and major concepts; system scores just "
     "below the STRONG boundary. Expected HUMAN STRONG / SYSTEM MODERATE."),
    ("Climate change affects agriculture. Extreme temperatures reduce crop "
     "production and irregular rainfall disrupts planting schedules for farmers.",
     "MODERATE", "On-topic but brief/partial coverage."),
    ("Climate change affects crop production because extreme temperatures "
     "and irregular rainfall create difficulties for farmers.",
     "MODERATE", "On-topic single claim; partial coverage."),
    ("Online video games allow players to communicate with friends across "
     "different countries. Competitive games require teamwork and quick decisions.",
     "WEAK", "Substantially different subject."),
    ("Rainfall patterns shift across regions while markets respond to supply "
     "changes and economic pressures.",
     "WEAK", "One shared word; subject is markets, not the assigned topic."),
]


def ensure_demo_datasets() -> dict:
    """Create (or reuse) the two DEMO datasets with samples + annotations.

    Idempotent by name: existing demo datasets are returned as-is so demo
    metrics stay reproducible.
    """
    binary = _ensure_one(
        name="DEMO THESIS_002 binary fixture",
        detector_id="THESIS_002",
        description=(protocols.DEMO_BANNER + " Binary validation machinery "
                     "fixture for THESIS_002. NOT research results."),
        samples=[{"raw_text": t, "label": label, "notes": notes}
                 for t, label, notes in DEMO_BINARY_SAMPLES],
    )
    multi = _ensure_one(
        name="DEMO TOPIC_CLASSIFIER multiclass fixture",
        detector_id="TOPIC_CLASSIFIER",
        description=(protocols.DEMO_BANNER + " Multiclass validation machinery "
                     "fixture for TOPIC_CLASSIFIER. NOT research results."),
        samples=[{"raw_text": t, "label": label, "notes": notes}
                 for t, label, notes in DEMO_MULTICLASS_SAMPLES],
    )
    return {"binary": binary, "multiclass": multi}


def _ensure_one(name: str, detector_id: str, description: str,
                samples: list[dict]) -> dict:
    for ds in datasets_mod.list_datasets():
        if ds["name"] == name and ds["is_demo"]:
            return ds
    ds = datasets_mod.create_dataset(
        name=name, detector_id=detector_id, description=description,
        source="DEMO_FIXTURE", notes=protocols.DEMO_BANNER, is_demo=True)
    datasets_mod.set_status(ds["id"], "ANNOTATING")
    for s in samples:
        kwargs: dict = {"raw_text": s["raw_text"],
                        "source": "DEMO_FIXTURE",
                        "provenance": "DEMO_FIXTURE"}
        if detector_id == "TOPIC_CLASSIFIER":
            kwargs["topic"] = TOPIC
            kwargs["teacher_keywords"] = list(KWS)
        sample = datasets_mod.add_sample(ds["id"], **kwargs)
        annotations_mod.annotate(sample["id"], detector_id, DEMO_ANNOTATOR,
                                 s["label"], notes=s["notes"])
    return datasets_mod.get_dataset(ds["id"])
