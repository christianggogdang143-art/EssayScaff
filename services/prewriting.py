"""Phase 3 Stage 1: rule-based pre-writing scaffolding (no generative AI).

Deterministic PREWRITE rules observe the student's idea through REAL NLP
evidence (tokens, keywords, topic analysis) and select reflective questions
from a fixed local prompt bank. The system asks and guides; the student
answers. Nothing here writes ideas, theses, or sentences for the student.

Concept source (honest label): assignment topic + teacher keywords + NLTK
WordNet expansion (see services/keywords.py, services/wordnet_service.py).
A future explicit academic knowledge-base module can replace/augment this
source; keep the CONCEPT_SOURCE descriptor updated if that happens.
"""

from __future__ import annotations

import time

import config

# Active concept source. NOT an "academic knowledge base" — labeled honestly.
CONCEPT_SOURCE = "assignment topic + teacher keywords + WordNet expansion"
# Future hook: a dedicated knowledge-base module should implement
# `expand_concepts(query_terms) -> {related, provenance}` and be wired in
# services/stage1.py. Do not call WordNet alone the knowledge base.

# --------------------------------------------------------------------------
# Transparent local prompt bank: category -> [(prompt_id, text)].
# Every string is a question or guidance. None supplies wording for the
# student's idea (protected by the authorship test).
# --------------------------------------------------------------------------
PROMPT_BANK: dict[str, list[tuple[str, str]]] = {
    "FOCUS": [
        ("FOCUS_001", "What specific aspect of this topic will you focus on?"),
        ("FOCUS_002", "Can you narrow this idea to one main issue?"),
    ],
    "PROBLEM": [
        ("PROBLEM_001", "What problem or issue does your idea address?"),
        ("PROBLEM_002", "Why is this issue important enough to write about?"),
    ],
    "POSITION": [
        ("POSITION_001", "What main point do you want your essay to communicate?"),
        ("POSITION_002", "What do you want your reader to understand after reading your essay?"),
    ],
    "SCOPE": [
        ("SCOPE_001", "Is your topic too broad for one essay?"),
        ("SCOPE_002", "Which smaller part of this topic interests you most?"),
    ],
    "STAKEHOLDER": [
        ("STAKEHOLDER_001", "Who or what is most affected by this issue?"),
        ("STAKEHOLDER_002", "Whose perspective could you focus on?"),
    ],
    "CAUSE": [
        ("CAUSE_001", "What do you think causes this situation?"),
        ("CAUSE_002", "What leads to the problem you are describing?"),
        ("CAUSE_003", "What cause or reason behind this issue do you want to examine?"),
    ],
    "EFFECT": [
        ("EFFECT_001", "What important effect do you want to examine?"),
        ("EFFECT_002", "What happens because of this situation?"),
    ],
    "RELATIONSHIP": [
        ("RELATIONSHIP_001", "How are the main concepts in your idea connected?"),
        ("RELATIONSHIP_002", "Which word in your idea shows how the concepts relate?"),
    ],
    "EVIDENCE": [
        ("EVIDENCE_001", "What kind of information would support this idea?"),
        ("EVIDENCE_002", "Where could you look for facts about this issue?"),
    ],
    "CLARIFICATION": [
        ("CLARIFICATION_001", "Which part of your idea needs to be explained more clearly?"),
        ("CLARIFICATION_002", "What would a reader ask you about this idea?"),
    ],
    "TOPIC": [
        ("TOPIC_001", "How does your idea connect to the assignment topic?"),
        ("TOPIC_002", "Which part of the assignment topic does your idea address?"),
    ],
}

# --------------------------------------------------------------------------
# Contextual templates: same categories, slots filled ONLY from provenanced
# context (assignment topic, teacher keywords, student concepts). Rendering
# is template filling, not generation: every slot value cites its source.
# --------------------------------------------------------------------------
CTX_TEMPLATES: dict[str, list[dict]] = {
    "FOCUS": [
        {"template_id": "FOCUS_CTX_001",
         "template": "What specific effect of {focus} on {target} will you focus on?",
         "slots": ("focus", "target")},
        {"template_id": "FOCUS_CTX_002",
         "template": "What specific aspect of {topic} will you focus on?",
         "slots": ("topic",)},
    ],
    "PROBLEM": [
        {"template_id": "PROBLEM_CTX_001",
         "template": "What specific problem involving {issue} does your idea address?",
         "slots": ("issue",)},
    ],
    "STAKEHOLDER": [
        {"template_id": "STAKEHOLDER_CTX_001",
         "template": "How is {stakeholder} affected by the issue you described?",
         "slots": ("stakeholder",)},
    ],
    "RELATIONSHIP": [
        {"template_id": "RELATIONSHIP_CTX_001",
         "template": "How are {focus} and {target} connected in your idea?",
         "slots": ("focus", "target")},
    ],
    "POSITION": [
        {"template_id": "POSITION_CTX_001",
         "template": "What main point do you want to communicate about {focus}?",
         "slots": ("focus",)},
    ],
    "CAUSE": [
        {"template_id": "CAUSE_CTX_001",
         "template": "What do you think causes the problem involving {focus}?",
         "slots": ("focus",)},
    ],
    "EFFECT": [
        {"template_id": "EFFECT_CTX_001",
         "template": "What important effect of {focus} do you want to examine?",
         "slots": ("focus",)},
    ],
    "TOPIC": [
        {"template_id": "TOPIC_CTX_001",
         "template": "Which part of {topic} does your idea address?",
         "slots": ("topic",)},
    ],
}

# Subtle student-facing category labels (priority stays professor-side).
CATEGORY_LABELS = {
    "FOCUS": "Focus", "PROBLEM": "Problem", "POSITION": "Direction",
    "SCOPE": "Scope", "STAKEHOLDER": "Voices", "CAUSE": "Direction",
    "EFFECT": "Direction", "RELATIONSHIP": "Connections",
    "EVIDENCE": "Support", "CLARIFICATION": "Clarification",
    "TOPIC": "Topic Connection",
}

# rule_id -> (rule_name, prompt_category, priority_name)
RULE_DEFS: dict[str, tuple[str, str, str]] = {
    "PREWRITE_001": ("Idea too short / insufficient development", "CLARIFICATION", "CRITICAL"),
    "PREWRITE_002": ("Broad topic with little specificity", "FOCUS", "HIGH"),
    "PREWRITE_003": ("Multiple concepts but relationship unclear", "RELATIONSHIP", "MEDIUM"),
    "PREWRITE_004": ("No clear issue/problem indicator", "PROBLEM", "HIGH"),
    "PREWRITE_005": ("No clear subject/stakeholder", "STAKEHOLDER", "HIGH"),
    "PREWRITE_006": ("Cause/effect direction detected", "EFFECT", "LOW"),
    "PREWRITE_007": ("Topic relationship weak", "TOPIC", "CRITICAL"),
    "PREWRITE_008": ("Idea appears reasonably focused", "POSITION", "LOW"),
}


def build_evidence(analysis: dict) -> dict:
    """Collect observable characteristics from a REAL analysis result."""
    tech = analysis.get("technical", {}) or {}
    tokens = tech.get("tokens", []) or []
    sentences = tech.get("sentences", []) or []
    phase2 = tech.get("phase2", {}) or {}
    kw = phase2.get("keywords", {}) or {}
    wn = phase2.get("wordnet", {}) or {}
    ta = phase2.get("topic_analysis", {}) or {}
    cls = ta.get("classification", {}) or {}

    lemmas = {(t.get("lemma") or t.get("text", "")).lower() for t in tokens if t.get("is_alpha")}
    alpha_count = sum(1 for t in tokens if t.get("is_alpha"))
    causal = sorted(config.PREWRITE_CAUSAL_MARKERS & lemmas)
    issues = sorted(config.PREWRITE_ISSUE_LEMMAS & lemmas)
    stakeholders = sorted(config.PREWRITE_STAKEHOLDERS & lemmas)
    broad_markers = sorted(config.PREWRITE_BROAD_MARKERS & lemmas)
    has_propn = any(t.get("pos") == "PROPN" for t in tokens if t.get("is_alpha"))
    selected = list(kw.get("selected", []) or [])
    return {
        "alpha_token_count": alpha_count,
        "sentence_count": len(sentences),
        "selected_keywords": selected,
        "concept_count": len(selected),
        "causal_markers": causal,
        "issue_indicators": issues,
        "stakeholders": stakeholders,
        "has_proper_noun": has_propn,
        "topic_ran": bool(phase2.get("ran")),
        "topic_classification": cls.get("classification"),
        "topic_similarity": cls.get("similarity"),
        "broad_markers": broad_markers,
        "direct_count": wn.get("direct_count", 0),
        "lemma_count": wn.get("lemma_count", 0),
        "wordnet_count": wn.get("wordnet_count", 0),
        "concept_source": CONCEPT_SOURCE,
    }


def _rule(rule_id: str, status: str, condition: str, result: bool, evidence: dict, reason: str) -> dict:
    name, category, priority = RULE_DEFS[rule_id]
    return {
        "rule_id": rule_id,
        "rule_name": name,
        "status": status,  # TRIGGERED | OBSERVED | INACTIVE | SKIPPED
        "condition": condition,
        "result": result,
        "evidence": evidence,
        "reason": reason,
        "prompt_category": category,
        "priority": priority,
        "priority_rank": config.PREWRITE_PRIORITY[priority],
    }


def evaluate_rules(evidence: dict) -> list[dict]:
    """Run all PREWRITE rules over real evidence. Deterministic, timed by caller."""
    n_alpha = evidence["alpha_token_count"]
    n_sent = evidence["sentence_count"]
    n_concepts = evidence["concept_count"]
    causal = evidence["causal_markers"]
    ev = {
        "alpha_token_count": n_alpha,
        "sentence_count": n_sent,
        "concept_count": n_concepts,
        "causal_markers": causal,
        "topic_classification": evidence["topic_classification"],
    }
    rules = []

    hit = n_alpha < config.PREWRITE_MIN_TOKENS
    rules.append(
        _rule(
            "PREWRITE_001",
            "TRIGGERED" if hit else "INACTIVE",
            f"alpha_token_count < {config.PREWRITE_MIN_TOKENS}",
            hit,
            ev,
            f"Idea has {n_alpha} alphabetic tokens (needs {config.PREWRITE_MIN_TOKENS} for development)."
            if hit
            else f"Idea has {n_alpha} alphabetic tokens.",
        )
    )

    branch_a = n_sent <= 1 and n_concepts < config.PREWRITE_BROAD_MAX_KEYWORDS and not causal
    branch_b = (
        n_sent >= config.PREWRITE_BRANCHB_MIN_SENTENCES
        and n_concepts >= config.PREWRITE_BRANCHB_MIN_CONCEPTS
        and bool(evidence.get("broad_markers"))
    )
    hit = branch_a or branch_b
    rules.append(
        _rule(
            "PREWRITE_002",
            "TRIGGERED" if hit else "INACTIVE",
            f"(sentences<=1 AND concepts<{config.PREWRITE_BROAD_MAX_KEYWORDS} AND no causal marker) "
            f"OR (sentences>={config.PREWRITE_BRANCHB_MIN_SENTENCES} AND "
            f"concepts>={config.PREWRITE_BRANCHB_MIN_CONCEPTS} AND broad-scope marker present)",
            hit,
            {**ev, "broad_markers": evidence.get("broad_markers", []),
             "broad_branch": "B" if (hit and not branch_a) else ("A" if hit else None)},
            (
                (f"One sentence with {n_concepts} concepts and no causal direction; likely too broad."
                 if branch_a else
                 f"{n_sent} sentences name {n_concepts} concepts with generic scope "
                 f"({', '.join(evidence.get('broad_markers', []))}); no single focus.")
                if hit
                else "Idea shows specificity signals (length, concepts, or causal direction)."
            ),
        )
    )

    hit = n_concepts >= config.PREWRITE_MIN_CONCEPTS_RELATIONSHIP and not causal
    rules.append(
        _rule(
            "PREWRITE_003",
            "TRIGGERED" if hit else "INACTIVE",
            f"concepts>={config.PREWRITE_MIN_CONCEPTS_RELATIONSHIP} AND no relational marker",
            hit,
            ev,
            (
                f"{n_concepts} concepts named but no word showing how they connect."
                if hit
                else "Concept relationships signaled or too few concepts to judge."
            ),
        )
    )

    hit = not evidence["issue_indicators"]
    rules.append(
        _rule(
            "PREWRITE_004",
            "TRIGGERED" if hit else "INACTIVE",
            "no issue/problem indicator lemma present",
            hit,
            {**ev, "issue_indicators": evidence["issue_indicators"]},
            "No problem/issue indicator found; the issue may be unstated."
            if hit
            else f"Issue indicators present: {evidence['issue_indicators']}.",
        )
    )

    stakeholder_hit = bool(evidence["stakeholders"]) or evidence["has_proper_noun"]
    rules.append(
        _rule(
            "PREWRITE_005",
            "INACTIVE" if stakeholder_hit else "TRIGGERED",
            "no stakeholder lemma and no proper noun",
            not stakeholder_hit,
            {**ev, "stakeholders": evidence["stakeholders"]},
            "No affected group or subject identified."
            if not stakeholder_hit
            else f"Subject present: {evidence['stakeholders'] or 'proper noun'}.",
        )
    )

    hit = bool(causal)
    category = "EFFECT" if "because" in causal else "CAUSE"
    r = _rule(
        "PREWRITE_006",
        "OBSERVED" if hit else "INACTIVE",
        "causal/relational marker present",
        hit,
        ev,
        f"Causal direction signaled by: {causal}." if hit else "No causal direction detected yet.",
    )
    r["prompt_category"] = category
    rules.append(r)

    if not evidence["topic_ran"]:
        rules.append(
            _rule(
                "PREWRITE_007", "SKIPPED",
                "topic pipeline did not run (no topic/keywords supplied)",
                False, ev, "Topic relationship unknown: no assignment topic supplied.",
            )
        )
    else:
        weak = evidence["topic_classification"] == "WEAK"
        rules.append(
            _rule(
                "PREWRITE_007",
                "TRIGGERED" if weak else "INACTIVE",
                "topic_classification == WEAK",
                weak,
                ev,
                f"Topic connection is WEAK (similarity {evidence['topic_similarity']})."
                if weak
                else f"Topic connection is {evidence['topic_classification']}.",
            )
        )

    calm = all(r["status"] != "TRIGGERED" for r in rules if r["rule_id"] in ("PREWRITE_001", "PREWRITE_002", "PREWRITE_004", "PREWRITE_005"))
    hit = calm and n_concepts >= config.PREWRITE_MIN_CONCEPTS_FOCUSED
    rules.append(
        _rule(
            "PREWRITE_008",
            "OBSERVED" if hit else "INACTIVE",
            "no critical rule active AND concepts>=3",
            hit,
            ev,
            "Idea names clear concepts with no critical gap; ready to sharpen into a position."
            if hit
            else "Critical scaffolding needs remain.",
        )
    )
    return rules


def _teacher_term_records(analysis: dict) -> list[dict]:
    """TEACHER_KEYWORD / TOPIC_TERM records with real match status (Phase 2)."""
    tech = (analysis.get("technical", {}) or {})
    phase2 = tech.get("phase2", {}) or {}
    wn = phase2.get("wordnet", {}) or {}
    return wn.get("terms", []) or []


def _word_parts(text: str) -> list[str]:
    import re

    return re.findall(r"[a-z']+", (text or "").lower())


def build_prompt_context(analysis: dict, topic: str | None, teacher_keywords: list[str] | None) -> dict:
    """Derive safe template slots with per-slot provenance.

    Every value comes from the assignment topic, teacher keywords, or the
    student's own analyzed text. Nothing is invented: a slot is present only
    when its source exists, otherwise templates fall back to generic prompts.
    """
    tech = (analysis.get("technical", {}) or {})
    tokens = tech.get("tokens", []) or []
    surfaces = {t.get("text", "").lower() for t in tokens if t.get("is_alpha")}
    propns = [t.get("text", "") for t in tokens
              if t.get("is_alpha") and t.get("pos") == "PROPN"]

    terms = _teacher_term_records(analysis)
    teacher_terms = [t for t in terms if t.get("kind") == "TEACHER_KEYWORD"]
    topic_terms = [t for t in terms if t.get("kind") == "TOPIC_TERM"]
    matched_teacher = [t for t in teacher_terms if t.get("student_match")]

    def slot(value, source, reason):
        return {"value": value, "source": source, "reason": reason}

    ctx: dict = {
        "topic": None, "focus": None, "target": None,
        "stakeholder": None, "issue": None,
        "teacher_concepts": [t.get("original_term", "") for t in teacher_terms],
        "matched_teacher_concepts": [t.get("original_term", "") for t in matched_teacher],
    }

    clean_topic = (topic or "").strip()
    if clean_topic:
        ctx["topic"] = slot(clean_topic, "assignment_topic",
                            "assignment topic supplied with the request")

    multi = [t for t in matched_teacher if " " in (t.get("original_term") or "").strip()]
    focus_term = (multi or matched_teacher or [None])[0]
    if focus_term is not None:
        ctx["focus"] = slot(focus_term.get("original_term", ""),
                            "teacher_keyword",
                            "first matched teacher concept (multi-word preferred), also present in student idea")
        for t in teacher_terms + topic_terms:
            if (t.get("original_term", "").lower() != focus_term.get("original_term", "").lower()
                    and t.get("student_match")):
                ctx["target"] = slot(t.get("original_term", ""),
                                     "teacher_keyword" if t.get("kind") == "TEACHER_KEYWORD" else "assignment_topic",
                                     "matched assignment concept distinct from the focus")
                break

    stakeholder_lemmas = sorted(
        {(t.get("lemma") or t.get("text", "")).lower() for t in tokens
         if t.get("is_alpha") and (t.get("lemma") or t.get("text", "")).lower() in config.PREWRITE_STAKEHOLDERS})
    surface = None
    surface_source = "student_concept"
    outer = None
    for lemma in stakeholder_lemmas:
        for t in teacher_terms:
            forms = set(_word_parts(t.get("original_term", "")))
            forms.update((t.get("lookup_term", "") or "").split("_"))
            if lemma in forms:
                surface, surface_source = t.get("original_term", ""), "teacher_keyword"
                outer = lemma
                break
        if surface:
            break
    if surface is None and propns:
        surface, surface_source = propns[0], "student_concept"
        outer = "proper noun in student idea"
    elif surface is None and stakeholder_lemmas:
        surface, surface_source = stakeholder_lemmas[0], "student_concept"
        outer = "stakeholder lemma in student idea"
    if surface:
        ctx["stakeholder"] = slot(surface, surface_source,
                                  f"affected group evidence ({outer})")

    issue_lemmas = sorted(
        {(t.get("lemma") or t.get("text", "")).lower() for t in tokens
         if t.get("is_alpha") and (t.get("lemma") or t.get("text", "")).lower() in config.PREWRITE_ISSUE_LEMMAS})
    if issue_lemmas:
        picked, src = issue_lemmas[0], "student_concept"
        for t in teacher_terms:
            forms = set(_word_parts(t.get("original_term", "")))
            forms.update((t.get("lookup_term", "") or "").split("_"))
            if picked in forms:
                picked, src = t.get("original_term", ""), "teacher_keyword"
                break
        ctx["issue"] = slot(picked, src, "issue indicator present in student idea")
    return ctx


def _render_template(template: dict, context: dict) -> dict | None:
    """Fill a template from provenanced slots. None if any slot is missing."""
    slots = {}
    for key in template["slots"]:
        entry = context.get(key)
        if not entry or not entry.get("value"):
            return None
        slots[key] = entry
    return {
        "prompt_id": template["template_id"],
        "template_id": template["template_id"],
        "template_text": template["template"],
        "rendered_text": template["template"].format(**{k: v["value"] for k, v in slots.items()}),
        "slot_values": {k: v["value"] for k, v in slots.items()},
        "slot_provenance": {k: {"value": v["value"], "source": v["source"], "reason": v["reason"]}
                            for k, v in slots.items()},
        "fallback_used": False,
    }


def select_prompts(rule_results: list[dict], shown_ids: set[str] | None = None, max_n: int | None = None,
                   context: dict | None = None) -> dict:
    """Pick up to max_n prompts by priority. Prefers prompts never shown.

    With a prompt context, tries contextual templates first (unused ones
    first), falling back to the generic bank. With context=None the behavior
    is exactly the historical bank rotation.
    """
    shown_ids = set(shown_ids or [])
    max_n = config.STAGE1_MAX_PROMPTS if max_n is None else max_n
    candidates = [r for r in rule_results if r["status"] in ("TRIGGERED", "OBSERVED")]
    candidates.sort(key=lambda r: (r["priority_rank"], r["rule_id"]))
    prompts = []
    chosen: set[str] = set()
    for r in candidates[:max_n]:
        rendered = None
        if context:
            for template in CTX_TEMPLATES.get(r["prompt_category"], []):
                if template["template_id"] in shown_ids or template["template_id"] in chosen:
                    continue
                rendered = _render_template(template, context)
                if rendered is not None:
                    chosen.add(template["template_id"])
                    break
        if rendered is None:
            options = PROMPT_BANK[r["prompt_category"]]
            choice = next((p for p in options if p[0] not in shown_ids and p[0] not in chosen), options[0])
            chosen.add(choice[0])
            rendered = {
                "prompt_id": choice[0],
                "template_id": choice[0],
                "template_text": choice[1],
                "rendered_text": choice[1],
                "slot_values": {},
                "slot_provenance": {},
                "fallback_used": True,
            }
        rendered.update({
            "category": r["prompt_category"],
            "text": rendered["rendered_text"],
            "rule_id": r["rule_id"],
            "priority": r["priority"],
            "why_shown": r["reason"],
        })
        prompts.append(rendered)
    from services.rhetorical_moves import ground_prompt

    return {"prompts": [ground_prompt(p) for p in prompts], "max_shown": max_n}


def check_readiness(evidence: dict, rule_results: list[dict]) -> dict:
    """Explicit rule-based readiness. No percentage, grammar never blocks."""
    by_id = {r["rule_id"]: r for r in rule_results}
    fired = {r["rule_id"] for r in rule_results if r["status"] == "TRIGGERED"}

    c1 = evidence["alpha_token_count"] >= config.PREWRITE_MIN_TOKENS
    if evidence["topic_ran"]:
        match_total = evidence["direct_count"] + evidence["lemma_count"] + evidence["wordnet_count"]
        c2 = match_total >= 1
        c2_note = f"{match_total} topic concept match(es) detected."
    else:
        c2 = evidence["concept_count"] >= 3
        c2_note = f"{evidence['concept_count']} selected concepts (no topic supplied)."
    c3 = "PREWRITE_002" not in fired
    c4 = "PREWRITE_001" not in fired and "PREWRITE_007" not in fired

    conditions = [
        {"id": "C1", "name": "Sufficient idea development", "result": "PASS" if c1 else "FAIL",
         "detail": f"{evidence['alpha_token_count']} tokens (needs {config.PREWRITE_MIN_TOKENS})."},
        {"id": "C2", "name": "Topic concepts detected", "result": "PASS" if c2 else "FAIL", "detail": c2_note},
        {"id": "C3", "name": "Focus sufficiently narrowed", "result": "PASS" if c3 else "FAIL",
         "detail": "PREWRITE_002 active." if not c3 else "No broad-idea flag active."},
        {"id": "C4", "name": "No critical scaffold issue remaining", "result": "PASS" if c4 else "FAIL",
         "detail": f"Active critical: {sorted(fired & {'PREWRITE_001', 'PREWRITE_007'}) or 'none'}."},
    ]
    if all(c["result"] == "PASS" for c in conditions):
        decision = "READY FOR THESIS FORMULATION"
        message = "Your idea is focused and connected to the topic. You can continue to thesis formulation."
    elif not c1:
        decision = "DEVELOPING"
        message = "Your idea needs more development. Write a little more about what you think, in your own words."
    else:
        decision = "NEARLY READY"
        message = "Your main idea is taking shape. Before moving to your thesis statement, review the focus of your topic."
    return {
        "conditions": conditions,
        "decision": decision,
        "student_message": message,
        "stage2_allowed": decision == "READY FOR THESIS FORMULATION",
        "blocking_rules": sorted(fired & {"PREWRITE_001", "PREWRITE_002", "PREWRITE_007"}),
    }


def compare_revisions(prev: dict, curr: dict) -> dict:
    """Measurable revision-to-revision changes. Only supported claims."""
    deltas = {
        "word_delta": curr["word_count"] - prev["word_count"],
        "sentence_delta": curr["sentence_count"] - prev["sentence_count"],
        "concept_delta": curr["concept_count"] - prev["concept_count"],
        "added_keywords": sorted(set(curr["keywords"]) - set(prev["keywords"])),
        "removed_keywords": sorted(set(prev["keywords"]) - set(curr["keywords"])),
        "similarity_before": prev.get("similarity"),
        "similarity_after": curr.get("similarity"),
        "class_before": prev.get("classification"),
        "class_after": curr.get("classification"),
        "resolved_rules": sorted(set(prev["fired_rules"]) - set(curr["fired_rules"])),
        "new_rules": sorted(set(curr["fired_rules"]) - set(prev["fired_rules"])),
    }
    messages = []
    if "PREWRITE_002" in deltas["resolved_rules"]:
        messages.append({"text": "Your idea is more specific.", "evidence": "PREWRITE_002 resolved."})
    if "PREWRITE_005" in deltas["resolved_rules"]:
        messages.append({"text": "You added a clear affected group.", "evidence": "PREWRITE_005 resolved."})
    if "PREWRITE_002" in curr["fired_rules"]:
        messages.append({"text": "Your main issue could still be narrowed.", "evidence": "PREWRITE_002 still active."})
    if deltas["added_keywords"]:
        messages.append({
            "text": f"You added {len(deltas['added_keywords'])} new concept(s): {', '.join(deltas['added_keywords'])}.",
            "evidence": "Selected-keyword set comparison.",
        })
    if deltas["class_before"] != deltas["class_after"] and deltas["class_before"] is not None:
        messages.append({
            "text": f"Your topic connection changed from {deltas['class_before']} to {deltas['class_after']} "
                    f"(similarity {deltas['similarity_before']:.4f} to {deltas['similarity_after']:.4f})."
            if deltas["similarity_before"] is not None else
            f"Your topic connection changed from {deltas['class_before']} to {deltas['class_after']}.",
            "evidence": "Topic classification comparison.",
        })
    if not messages and not (deltas["word_delta"] or deltas["concept_delta"]):
        messages.append({
            "text": "No measurable changes yet — revise your idea in your own words, then re-analyze.",
            "evidence": "No keyword/rule/similarity movement.",
        })
    return {"deltas": deltas, "messages": messages}


def student_why(rule: dict, evidence: dict) -> str:
    """Short student-friendly reason derived only from evidence counts."""
    rid = rule.get("rule_id", "")
    n = evidence.get("concept_count", 0)
    s = evidence.get("sentence_count", 0)
    if rid == "PREWRITE_001":
        return "Your idea is still very short — add more of what you think."
    if rid == "PREWRITE_002":
        return (f"Your idea mentions {n} different concepts across {s} "
                f"{'sentence' if s == 1 else 'sentences'} without settling on one focus.")
    if rid == "PREWRITE_003":
        return f"Your idea names {n} concepts without showing how they connect."
    if rid == "PREWRITE_004":
        return "Your idea doesn't name a clear problem yet."
    if rid == "PREWRITE_005":
        return "Your idea doesn't name who is affected yet."
    if rid == "PREWRITE_006":
        return "Your idea already shows a cause-and-effect direction — build on it."
    if rid == "PREWRITE_007":
        return "Your idea doesn't connect strongly to the assignment topic yet."
    if rid == "PREWRITE_008":
        return "Your idea names clear concepts — sharpen them into a position."
    return rule.get("reason", "")


def build_student_guidance(prompts: list[dict], readiness: dict, writing_notes: list[dict],
                           evidence: dict, context: dict) -> dict:
    """Student-facing hierarchy: status, main guidance, others, notes.

    Main guidance = highest-priority scaffold first. Assignment concepts may
    be listed as options (never requirements) when the focus came from the
    teacher list and other teacher concepts exist.
    """
    def entry(p):
        return {
            "rule_id": p.get("rule_id"),
            "category": p.get("category"),
            "label": CATEGORY_LABELS.get(p.get("category", ""), p.get("category", "")),
            "student_why": student_why(
                {"rule_id": p.get("rule_id"), "reason": p.get("why_shown", "")}, evidence),
            "question": {"prompt_id": p.get("prompt_id"), "text": p.get("text")},
            "template_id": p.get("template_id"),
            "fallback_used": p.get("fallback_used", True),
        }

    main = entry(prompts[0]) if prompts else None
    assignment_note = None
    if main and main["rule_id"] == "PREWRITE_002":
        unmatched = [c for c in (context.get("teacher_concepts", []) or [])
                     if c.lower() != (context.get("focus") or {}).get("value", "").lower()]
        if unmatched:
            assignment_note = {
                "label": "Assignment concepts — not required words",
                "text": ("Your assignment includes several possible areas of focus: "
                         + ", ".join(unmatched)
                         + ". Which one best matches the idea you want to develop?"),
            }
    return {
        "status": readiness.get("decision"),
        "status_message": readiness.get("student_message"),
        "main": main,
        "others": [entry(p) for p in prompts[1:]],
        "assignment_note": assignment_note,
        "writing_notes": writing_notes or [],
    }


def detect_meta_note(analysis: dict) -> list[dict]:
    """Secondary Stage 1 writing note for THESIS_002 hits.

    Never blocks readiness (readiness conditions C1-C4 ignore THESIS_002).
    Never rewrites the sentence.
    """
    tech = (analysis.get("technical", {}) or {})
    notes = []
    for r in tech.get("rule_results", []) or []:
        if r.get("rule_id") == "THESIS_002" and r.get("status") == "ISSUE":
            notes.append({
                "type": "meta-statement",
                "source_rule": "THESIS_002",
                "evidence": r.get("evidence"),
                "sentence_number": r.get("sentence_number"),
                "start": r.get("start"),
                "end": r.get("end"),
                "message": (f"A meta-statement was detected: \"{r.get('evidence')}\". "
                            "You will work more directly on thesis formulation during Stage 2."),
            })
    return notes
