"""Rhetorical-move grounding adopted from AcaWriter (UTS Connected Intelligence
Centre) — Apache 2.0, https://github.com/uts-cic/acawriter.

Adopted: the move TAXONOMY and feedback-message PATTERNS from Knight et al.
(2020), "AcaWriter: A learning analytics tool for formative feedback on
academic writing", Journal of Writing Research 12(1), 141-186.

Explicitly NOT adopted: the Athanor parser binary (retired upstream March
2026; Python 2.7-era toolchain incompatible with this app — evaluated and
declined, see ADOPTION_REGISTER.md). Move detection here is implemented with
EssayScaff's own spaCy pipeline; AcaWriter provides the validated vocabulary
for naming what was found, not the detection code.

Every rule and prompt in the app carries a move reference so the panel can
see the published basis. Grammar-convention findings (LanguageTool) are
outside rhetorical moves and say so honestly instead of being forced in.
"""

from __future__ import annotations

CITATION = (
    "Knight, S., Shibani, A., Abel, S., Gibson, A., Ryan, P., Sutton, N., "
    "Wight, R., Lucas, C., Sandor, A., Kitto, K., Liu, M., Mogarkar, R. & "
    "Buckingham Shum, S. (2020). AcaWriter: A learning analytics tool for "
    "formative feedback on academic writing. Journal of Writing Research, "
    "12(1), 141-186."
)
SOURCE = "AcaWriter rhetorical-move taxonomy (adapted) — Apache 2.0, github.com/uts-cic/acawriter"

MOVES: dict[str, dict] = {
    "CLAIM": {
        "name": "Claim move",
        "acawriter_basis": "AcaWriter flags whether a text makes an arguable scholarly claim vs. merely describing.",
        "note": "Adapted label; detection is EssayScaff's own (THESIS rules).",
    },
    "EVIDENCE": {
        "name": "Evidence move",
        "acawriter_basis": "AcaWriter checks that claims are accompanied by supporting evidence/grounds.",
        "note": "Adapted label; detection is EssayScaff's own (support/alignment rules).",
    },
    "ELABORATION": {
        "name": "Elaboration move",
        "acawriter_basis": "AcaWriter values expanding and explaining ideas, not just stating them.",
        "note": "Adapted label; used for specificity/clarity guidance.",
    },
    "CONTRAST": {
        "name": "Contrast / concession move",
        "acawriter_basis": "AcaWriter highlights contrastive markers as signals of critical thinking.",
        "note": "Adapted label; currently only referenced where ordering/relationship guidance applies.",
    },
    "ORGANIZATION": {
        "name": "Organization / coherence move",
        "acawriter_basis": "AcaWriter feedback addresses logical flow and connection between ideas.",
        "note": "Adapted label; used for unity, ordering, and repetition guidance.",
    },
    "REFLECTION": {
        "name": "Reflective move",
        "acawriter_basis": "AcaWriter (reflective-writing genre) rewards language that makes the writer's thinking visible.",
        "note": "Adapted label; used for self-monitoring prompts (topic connection, direction checks).",
    },
    "CONVENTIONS": {
        "name": "Language conventions (outside rhetorical moves)",
        "acawriter_basis": "Not a rhetorical move. Grammar/mechanics findings keep their own basis: the LanguageTool rule catalog.",
        "note": "Honest boundary: convention issues are classified, not forced into move vocabulary.",
    },
}

# rule_id -> move id. Covers every rule in the system (enforced by tests).
RULE_MOVE_MAP: dict[str, str] = {
    "THESIS_001": "CLAIM",
    "THESIS_002": "CLAIM",
    "THESIS_003": "CLAIM",
    "THESIS_004": "CLAIM",
    "THESIS_005": "ORGANIZATION",
    "THESIS_006": "REFLECTION",
    "THESIS_007": "CLAIM",
    "THESIS_008": "ORGANIZATION",
    "THESIS_009": "ELABORATION",
    "THESIS_010": "CLAIM",
    "STYLE_001": "ELABORATION",
    "STYLE_002": "ORGANIZATION",
    "MECHANICS_001": "CONVENTIONS",
    "MECHANICS_002": "CONVENTIONS",
    "PREWRITE_001": "ELABORATION",
    "PREWRITE_002": "ELABORATION",
    "PREWRITE_003": "ORGANIZATION",
    "PREWRITE_004": "CLAIM",
    "PREWRITE_005": "EVIDENCE",
    "PREWRITE_006": "ELABORATION",
    "PREWRITE_007": "REFLECTION",
    "PREWRITE_008": "CLAIM",
    "ALIGN_001": "REFLECTION",
    "OUTLINE_001": "ORGANIZATION",
    "OUTLINE_002": "ELABORATION",
    "OUTLINE_003": "EVIDENCE",
    "OUTLINE_004": "EVIDENCE",
    "OUTLINE_005": "EVIDENCE",
    "OUTLINE_006": "ORGANIZATION",
    "OUTLINE_007": "ORGANIZATION",
    "OUTLINE_008": "ORGANIZATION",
    "OUTLINE_009": "ORGANIZATION",
    "OUTLINE_010": "EVIDENCE",
    "OUTLINE_011": "EVIDENCE",
    "OUTLINE_012": "ORGANIZATION",
    "TOPIC_CLASSIFIER": "REFLECTION",
    "REFLECT_001": "REFLECTION",
    "REFLECT_002": "EVIDENCE",
    "REFLECT_003": "EVIDENCE",
    "REFLECT_004": "ORGANIZATION",
    "REFLECT_005": "ORGANIZATION",
    "REFLECT_006": "ORGANIZATION",
    "REFLECT_007": "REFLECTION",
    "REFLECT_008": "EVIDENCE",
    "REFLECT_009": "ORGANIZATION",
    "REFLECT_010": "REFLECTION",
    "REFLECT_011": "REFLECTION",
    "REFLECT_012": "REFLECTION",
    "REFLECT_013": "REFLECTION",
}

# Prompt category -> move id. Covers every bank category (enforced by tests).
CATEGORY_MOVE_MAP: dict[str, str] = {
    "FOCUS": "CLAIM",
    "PROBLEM": "CLAIM",
    "POSITION": "CLAIM",
    "SCOPE": "ELABORATION",
    "STAKEHOLDER": "EVIDENCE",
    "CAUSE": "ELABORATION",
    "EFFECT": "ELABORATION",
    "RELATIONSHIP": "ORGANIZATION",
    "EVIDENCE": "EVIDENCE",
    "CLARIFICATION": "ELABORATION",
    "TOPIC": "REFLECTION",
    "CLAIM": "CLAIM",
    "CLARITY": "ELABORATION",
    "SPECIFICITY": "ELABORATION",
    "META": "CLAIM",
    "ALIGNMENT": "REFLECTION",
    "SUPPORT": "EVIDENCE",
    "UNITY": "ORGANIZATION",
    "ORDER": "ORGANIZATION",
    "DISTINCTION": "ORGANIZATION",
    "DETAIL_ALIGNMENT": "EVIDENCE",
    "COMPLETENESS": "ORGANIZATION",
    "TRANSITION_PLANNING": "ORGANIZATION",
    "CONSISTENCY": "REFLECTION",
    "FLOW": "ORGANIZATION",
    "REVIEW": "REFLECTION",
}


def _grounding(move_id: str) -> dict:
    move = MOVES[move_id]
    return {
        "rhetorical_move": move_id,
        "move_name": move["name"],
        "acawriter_basis": move["acawriter_basis"],
        "citation": CITATION,
        "source": SOURCE,
    }


def ground_prompt(prompt: dict) -> dict:
    """Additive grounding for a selected prompt. Never alters selection."""
    rule_id = prompt.get("rule_id", "")
    move_id = RULE_MOVE_MAP.get(rule_id, CATEGORY_MOVE_MAP.get(prompt.get("category", ""), "ELABORATION"))
    prompt = dict(prompt)
    prompt["grounding"] = _grounding(move_id)
    return prompt


def ground_feedback_item(item: dict) -> dict:
    """Additive grounding for a feedback item. Never alters detection."""
    source = item.get("source", "")
    base_rule = source.split(":", 1)[0] if ":" in source else source
    if base_rule == "LanguageTool" or source.startswith("LanguageTool"):
        move_id = "CONVENTIONS"
    elif source == "input-validation":
        move_id = "ELABORATION"
    else:
        move_id = RULE_MOVE_MAP.get(source, "ELABORATION")
    item = dict(item)
    item["grounding"] = _grounding(move_id)
    return item
