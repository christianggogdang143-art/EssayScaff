"""AcaWriter grounding tests: every rule and prompt carries a valid,
cited rhetorical-move reference; grounding never alters selection/content."""

from services import feedback_service, outline, prewriting, rhetorical_moves, thesis
from services.rhetorical_moves import (
    CATEGORY_MOVE_MAP,
    MOVES,
    RULE_MOVE_MAP,
    ground_feedback_item,
    ground_prompt,
)

EXPECTED_RULES = (
    [f"THESIS_{i:03d}" for i in range(1, 11)]
    + ["STYLE_001", "STYLE_002", "MECHANICS_001", "MECHANICS_002"]
    + [f"PREWRITE_{i:03d}" for i in range(1, 9)]
    + ["ALIGN_001"]
    + [f"OUTLINE_{i:03d}" for i in range(1, 13)]
    + ["TOPIC_CLASSIFIER"]
)


def test_every_rule_has_valid_move():
    for rule_id in EXPECTED_RULES:
        assert rule_id in RULE_MOVE_MAP, rule_id
        assert RULE_MOVE_MAP[rule_id] in MOVES, rule_id


def test_every_prompt_category_has_valid_move():
    banks = [prewriting.PROMPT_BANK, thesis.THESIS_PROMPT_BANK, outline.OUTLINE_PROMPT_BANK]
    for bank in banks:
        for category in bank:
            assert category in CATEGORY_MOVE_MAP, category
            assert CATEGORY_MOVE_MAP[category] in MOVES, category


def test_moves_carry_citation_and_basis():
    for move_id, move in MOVES.items():
        assert move.get("acawriter_basis"), move_id
        assert move.get("name"), move_id
    assert "Knight" in rhetorical_moves.CITATION
    assert "Apache" in rhetorical_moves.SOURCE
    grounded = ground_feedback_item({"source": "THESIS_001"})
    assert "Knight" in grounded["grounding"]["citation"]
    assert "acawriter" in grounded["grounding"]["source"].lower()


def test_ground_prompt_preserves_selection():
    prompt = {"prompt_id": "FOCUS_001", "category": "FOCUS", "text": "What?",
              "rule_id": "PREWRITE_002", "priority": "HIGH", "why_shown": "broad"}
    grounded = ground_prompt(prompt)
    assert grounded["prompt_id"] == "FOCUS_001"
    assert grounded["text"] == "What?"
    # Rule-level mapping (ELABORATION for broad-idea rule) wins over category default.
    assert grounded["grounding"]["rhetorical_move"] == "ELABORATION"
    assert "Knight" in grounded["grounding"]["citation"]
    assert "grounding" not in prompt  # input untouched


def test_ground_feedback_item_routing():
    assert ground_feedback_item({"source": "THESIS_002"})["grounding"]["rhetorical_move"] == "CLAIM"
    assert ground_feedback_item({"source": "OUTLINE_005"})["grounding"]["rhetorical_move"] == "EVIDENCE"
    assert ground_feedback_item({"source": "LanguageTool:HE_VERB_AGR"})["grounding"]["rhetorical_move"] == "CONVENTIONS"
    assert ground_feedback_item({"source": "TOPIC_CLASSIFIER"})["grounding"]["rhetorical_move"] == "REFLECTION"


def test_build_feedback_items_all_grounded():
    rule_results = [
        {"rule_id": "THESIS_002", "rule_name": "Meta", "status": "ISSUE", "severity": "warning",
         "sentence_number": 1, "evidence": "This essay will", "start": 0, "end": 15,
         "reason": "Meta-statement."},
    ]
    lt_result = {"issues": [{"rule_id": "HE_VERB_AGR", "category": "GRAMMAR", "message": "Agreement.",
                             "matched_text": "go", "offset": 3, "length": 2, "sentence": 1, "replacements": ["goes"]}]}
    out = feedback_service.build_feedback(rule_results, lt_result)
    assert len(out) == 2
    for item in out:
        assert item["grounding"]["rhetorical_move"] in MOVES
        assert item["feedback_id"].startswith("FB-")


def test_stage_prompt_outputs_all_grounded():
    rules = [
        {"rule_id": "PREWRITE_002", "status": "TRIGGERED", "priority_rank": 1, "priority": "HIGH",
         "prompt_category": "FOCUS", "reason": "broad"},
    ]
    for p in prewriting.select_prompts(rules)["prompts"]:
        assert p["grounding"]["rhetorical_move"] in MOVES
    rules_t = [
        {"rule_id": "THESIS_003", "status": "TRIGGERED", "priority_rank": 1, "priority": "HIGH",
         "prompt_category": "SPECIFICITY", "reason": "broad"},
    ]
    for p in thesis.select_thesis_prompts(rules_t, {})["prompts"]:
        assert p["grounding"]["rhetorical_move"] in MOVES
    rules_o = [
        {"rule_id": "OUTLINE_005", "status": "TRIGGERED", "priority_rank": 1, "priority": "HIGH",
         "prompt_category": "SUPPORT", "reason": "no support", "evidence": {"point": 1}},
    ]
    for p in outline.select_outline_prompts(rules_o)["prompts"]:
        assert p["grounding"]["rhetorical_move"] in MOVES
