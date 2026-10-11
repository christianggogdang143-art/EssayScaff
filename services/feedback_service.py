"""Convert technical detections into student-facing scaffolding guidance.

Every feedback item tells the student WHAT was detected, WHERE, WHY, WHICH
rule/tool detected it, and WHAT to review. Suggestions guide revision —
they never supply rewritten sentences or ready-made thesis statements.
"""

from __future__ import annotations

CATEGORY_BY_RULE = {
    "THESIS_001": "Thesis",
    "THESIS_002": "Thesis",
    "STYLE_001": "Style",
    "STYLE_002": "Style",
    "MECHANICS_001": "Mechanics",
    "MECHANICS_002": "Mechanics",
}

TITLE_BY_RULE = {
    "THESIS_001": "Central-claim candidate (heuristic)",
    "THESIS_002": "Meta-statement detected",
    "STYLE_001": "Possible passive construction",
    "STYLE_002": "Repeated sentence opening",
    "MECHANICS_001": "Possible sentence fragment",
    "MECHANICS_002": "Possible run-on sentence",
}

SUGGESTION_BY_RULE = {
    "THESIS_001": "Review this sentence: does it state your main position directly, with a clear subject and verb? Strengthen it in your own words.",
    "THESIS_002": "Review this sentence and state your main position more directly instead of describing what the essay will do. Keep authorship of the claim.",
    "STYLE_001": "Review this sentence: who performs the action? Consider revising into the active voice in your own words if the agent matters.",
    "STYLE_002": "Review these sentences and vary how each one opens, using your own phrasing.",
    "MECHANICS_001": "Review this sentence: does it express a complete thought with a subject and verb? Revise it into a complete sentence yourself.",
    "MECHANICS_002": "Review this sentence: it may join too many clauses. Consider splitting it or adjusting punctuation yourself.",
}


def _feedback_id(n: int) -> str:
    return f"FB-{n:04d}"


def build_topic_feedback(topic_bundle: dict) -> dict | None:
    """Student-facing topic guidance. Never writes replacement sentences."""
    cls = (topic_bundle.get("topic_analysis") or {}).get("classification") or {}
    label = cls.get("classification", "UNKNOWN")
    wn = topic_bundle.get("wordnet") or {}
    terms = wn.get("terms", [])
    direct = [t["original_term"] for t in terms if t["match_type"] == "DIRECT"]
    related = []
    for t in terms:
        if t["match_type"] == "WORDNET":
            for m in t.get("matched_student_terms", []):
                related.append(f"{m} → {t['original_term']}")
    missing = [t["original_term"] for t in terms if t["match_type"] == "NO_MATCH"]
    sim = cls.get("similarity")
    if label == "STRONG":
        reason = (
            f"Topic connection is STRONG (cosine similarity {sim:.4f}). "
            f"Direct matches: {', '.join(direct) or 'none'}. "
            f"Related matches: {', '.join(related) or 'none'}."
        )
        suggestion = "Your writing contains several concepts related to the assignment topic. Make sure each paragraph continues supporting the main topic."
    elif label == "MODERATE":
        reason = (
            f"Topic connection is MODERATE (cosine similarity {sim:.4f}). "
            f"Direct matches: {', '.join(direct) or 'none'}. "
            f"Related matches: {', '.join(related) or 'none'}."
        )
        suggestion = "Some assignment concepts were detected. Review whether each paragraph directly supports the assigned topic, using your own words."
    else:
        sim_str = f"{sim:.4f}" if sim is not None else "n/a"
        reason = (
            f"Topic connection is WEAK (cosine similarity {sim_str}). "
            "Few of the main assignment concepts were detected in this text. "
            f"Missing concepts include: {', '.join(missing) or 'none listed'}."
        )
        suggestion = (
            "Review whether your writing directly supports the assigned topic. "
            "You do not need to insert every listed word mechanically — focus on addressing the topic in your own words."
        )
    return {
        "category": "Topic",
        "title": f"Topic connection: {label}",
        "severity": "warning" if label == "WEAK" else "info",
        "sentence_number": None,
        "text": topic_bundle.get("topic") or "",
        "start": None,
        "end": None,
        "source": "TOPIC_CLASSIFIER",
        "reason": reason,
        "suggestion": suggestion,
        "details": {
            "similarity": sim,
            "classification": label,
            "direct_matches": direct,
            "related_matches": related,
            "missing": missing,
        },
    }


def build_feedback(rule_results: list[dict], lt_result: dict, topic_bundle: dict | None = None) -> list[dict]:
    """Build student-facing feedback from rule + LanguageTool (+topic) results."""
    feedback: list[dict] = []
    n = 0

    for r in rule_results:
        # THESIS_001 non-candidates are trace-only; candidates guide the student.
        if r.get("rule_id") == "THESIS_001" and r.get("status") != "CANDIDATE":
            continue
        n += 1
        rule_id = r.get("rule_id", "UNKNOWN")
        sent = r.get("sentence_number")
        feedback.append(
            {
                "feedback_id": _feedback_id(n),
                "category": CATEGORY_BY_RULE.get(rule_id, "General"),
                "title": TITLE_BY_RULE.get(rule_id, rule_id),
                "severity": r.get("severity", "info"),
                "sentence_number": sent,
                "text": r.get("evidence"),
                "start": r.get("start"),
                "end": r.get("end"),
                "source": rule_id,
                "reason": r.get("reason"),
                "suggestion": SUGGESTION_BY_RULE.get(rule_id, "Review the highlighted text in your own words."),
            }
        )

    for issue in lt_result.get("issues", []):
        n += 1
        feedback.append(
            {
                "feedback_id": _feedback_id(n),
                "category": "Grammar",
                "title": f"Grammar suggestion ({issue.get('rule_id') or 'LanguageTool'})",
                "severity": "info",
                "sentence_number": issue.get("sentence"),
                "text": issue.get("matched_text"),
                "start": issue.get("offset"),
                "end": (issue.get("offset") or 0) + (issue.get("length") or 0),
                "source": f"LanguageTool:{issue.get('rule_id')}",
                "reason": issue.get("message"),
                "suggestion": (
                    "Review the highlighted text against the suggestion(s) "
                    f"{issue.get('replacements') or []} and revise it yourself. "
                    "The system does not apply corrections automatically."
                ),
            }
        )

    if topic_bundle and (topic_bundle.get("topic_analysis") or {}).get("classification"):
        item = build_topic_feedback(topic_bundle)
        if item:
            n += 1
            item["feedback_id"] = _feedback_id(n)
            feedback.append(item)

    from services.rhetorical_moves import ground_feedback_item

    return [ground_feedback_item(f) for f in feedback]
