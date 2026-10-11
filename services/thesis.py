"""Phase 4 Stage 2: rule-based thesis formulation scaffolding (no generative AI).

Reuses THESIS_001/THESIS_002 unchanged (rules/thesis_rules.py,
rules/meta_rules.py) and adds deterministic THESIS_003–THESIS_010
heuristics plus a Stage1->Stage2 alignment check. Extracts transparent
thesis components (subject, predicate, concepts, stance/vagueness markers)
with cautious DETECTED/POSSIBLE labels — dependency parsing does not
perfectly understand argumentation. Never writes a thesis for the student.
"""

from __future__ import annotations

import config

# --------------------------------------------------------------------------
# Deterministic thesis prompt bank. Questions and guidance only.
# Protected by the authorship test (no replacement-thesis phrasing).
# --------------------------------------------------------------------------
THESIS_PROMPT_BANK: dict[str, list[tuple[str, str]]] = {
    "CLAIM": [
        ("CLAIM_001", "What main point do you want your reader to understand?"),
        ("CLAIM_002", "In one sentence of your own, what are you claiming?"),
    ],
    "SPECIFICITY": [
        ("SPECIFICITY_001", "What specific aspect of the topic does this thesis focus on?"),
        ("SPECIFICITY_002", "What specific effect, group, or situation will your argument focus on?"),
    ],
    "SCOPE": [
        ("SCOPE_001", "Can this thesis be fully developed within one essay?"),
        ("SCOPE_002", "Which one of these claims is most important to your essay?"),
    ],
    "FOCUS": [
        ("FOCUS_T001", "Which idea is most important in this statement?"),
        ("FOCUS_T002", "If you had to keep only one claim, which would it be?"),
    ],
    "RELATIONSHIP": [
        ("RELATIONSHIP_T001", "How are the main concepts in your thesis connected?"),
        ("RELATIONSHIP_T002", "What word shows the relationship between your main concepts?"),
    ],
    "POSITION": [
        ("POSITION_T001", "What position or direction does this thesis establish?"),
        ("POSITION_T002", "Does your thesis explain a situation, argue a point, or both?"),
    ],
    "CLARITY": [
        ("CLARITY_001", "Which part of this statement could be expressed more clearly?"),
        ("CLARITY_002", "Is there a vague word here a reader might misunderstand?"),
    ],
    "ALIGNMENT": [
        ("ALIGNMENT_001", "Does this thesis still reflect the idea you developed during pre-writing?"),
        ("ALIGNMENT_002", "Did you intentionally change direction from your Stage 1 idea?"),
    ],
    "TOPIC": [
        ("TOPIC_T001", "How does this thesis connect to the assignment topic?"),
        ("TOPIC_T002", "Which teacher keyword does your thesis address most directly?"),
    ],
    "META": [
        ("META_001", "Can you state the main claim directly instead of describing what the essay will discuss?"),
        ("META_002", "What main position or claim do you want the reader to understand?"),
    ],
}

# rule_id -> (rule_name, prompt_category, priority_name)
THESIS_RULE_DEFS: dict[str, tuple[str, str, str]] = {
    "THESIS_003": ("Overly broad / unspecific thesis (heuristic)", "SPECIFICITY", "HIGH"),
    "THESIS_004": ("Clear central claim observed (heuristic)", "POSITION", "LOW"),
    "THESIS_005": ("Logical scope overloaded (heuristic)", "SCOPE", "HIGH"),
    "THESIS_006": ("Topic alignment weak (heuristic)", "TOPIC", "CRITICAL"),
    "THESIS_007": ("Factual-description-only statement (heuristic)", "POSITION", "MEDIUM"),
    "THESIS_008": ("Multiple competing claims (heuristic)", "FOCUS", "HIGH"),
    "THESIS_009": ("Excessive vagueness (heuristic)", "CLARITY", "MEDIUM"),
    "THESIS_010": ("Reasonably focused thesis observed (heuristic)", "CLAIM", "LOW"),
}

FINITE_TAGS = {"VBZ", "VBP", "VBD", "MD"}


def extract_components(analysis: dict) -> dict:
    """Transparent component extraction from real token/POS/dependency data."""
    tech = analysis.get("technical", {}) or {}
    tokens = tech.get("tokens", []) or []
    sentences = tech.get("sentences", []) or []
    phase2 = tech.get("phase2", {}) or {}
    selected = list((phase2.get("keywords", {}) or {}).get("selected", []) or [])

    alpha = [t for t in tokens if t.get("is_alpha")]
    lemmas = {(t.get("lemma") or t.get("text", "")).lower() for t in alpha}
    focus = sentences[0] if sentences else None
    in_focus = [t for t in alpha if focus and focus["start"] <= t["start"] < focus["end"]] or alpha

    subjects = [t for t in in_focus if t.get("dep") in ("nsubj", "nsubjpass")]
    subject = subjects[0] if subjects else None
    broad_object = next(
        (t["text"] for t in in_focus
         if t.get("dep") in ("dobj", "pobj", "attr", "oprd")
         and (t.get("lemma") or t.get("text", "")).lower() in config.THESIS_BROAD_OBJECTS),
        None,
    )
    roots = [t for t in in_focus if t.get("dep") == "ROOT"]
    root = roots[0] if roots else None
    finite = [t for t in in_focus if t.get("tag") in FINITE_TAGS]
    main_verb = None
    if root and root.get("pos") in ("VERB", "AUX"):
        main_verb = root["text"]
    elif finite:
        main_verb = finite[0]["text"]
    qualifiers = sorted({t["text"].lower() for t in in_focus if t.get("dep") in ("amod", "advmod") and t.get("is_alpha")})
    causal = sorted(config.PREWRITE_CAUSAL_MARKERS & lemmas)
    stance = sorted(config.THESIS_STANCE_LEMMAS & lemmas)
    vague = sorted(config.THESIS_VAGUE_LEMMAS & lemmas)
    cc_count = sum(1 for t in in_focus if t.get("dep") == "cc")
    declarative = bool(focus and focus["text"].strip().endswith("."))
    return {
        "focus_sentence": focus["text"] if focus else "",
        "multi_sentence_note": f"Thesis has {len(sentences)} sentences; first analyzed as the claim."
        if len(sentences) > 1 else None,
        "detected_subject": subject["text"] if subject else None,
        "subject_pos": subject.get("pos") if subject else None,
        "pronoun_subject": bool(subject and subject.get("pos") == "PRON"),
        "possible_main_claim": (root["text"] if root else None),
        "main_verb": main_verb,
        "finite_verb_count": len(finite),
        "finite_verbs": [t["text"] for t in finite],
        "conjunction_count": cc_count,
        "possible_qualifiers": qualifiers,
        "important_concepts": selected,
        "concept_count": len(selected),
        "possible_cause_effect": causal,
        "possible_stance_markers": stance,
        "vague_markers": vague,
        "alpha_token_count": len(alpha),
        "declarative": declarative,
        "complete_structure": declarative and subject is not None and bool(finite),
        "broad_object": broad_object,
    }


def _rule(rule_id: str, status: str, condition: str, result: bool, evidence: dict, reason: str) -> dict:
    name, category, priority = THESIS_RULE_DEFS[rule_id]
    return {
        "rule_id": rule_id, "rule_name": name, "status": status,
        "condition": condition, "result": result, "evidence": evidence,
        "reason": reason, "prompt_category": category, "priority": priority,
        "priority_rank": config.PREWRITE_PRIORITY[priority],
    }


def evaluate_new_rules(components: dict, topic_classification: str | None, topic_ran: bool, support_matches: int = 0) -> list[dict]:
    """THESIS_003–THESIS_010 over component evidence. Deterministic."""
    n_alpha = components["alpha_token_count"]
    n_kw = components["concept_count"]
    n_fin = components["finite_verb_count"]
    causal = components["possible_cause_effect"]
    stance = components["possible_stance_markers"]
    vague = components["vague_markers"]
    ev = {
        "alpha_token_count": n_alpha, "concept_count": n_kw,
        "finite_verb_count": n_fin, "conjunction_count": components["conjunction_count"],
        "causal_markers": causal, "stance_markers": stance, "vague_markers": vague,
        "topic_classification": topic_classification,
    }
    rules = []

    broad_obj = components.get("broad_object")
    narrow = n_alpha <= config.THESIS_BROAD_MAX_TOKENS and n_kw <= config.THESIS_BROAD_MAX_KEYWORDS and not (causal or stance)
    hit = narrow or bool(broad_obj)
    rules.append(_rule("THESIS_003", "TRIGGERED" if hit else "INACTIVE",
        f"(tokens<={config.THESIS_BROAD_MAX_TOKENS} AND keywords<={config.THESIS_BROAD_MAX_KEYWORDS} AND no anchor) OR broad object",
        hit, {**ev, "broad_object": broad_obj},
        (f"Maximally broad object '{broad_obj}': focus is the whole, not a part." if broad_obj
         else f"Short generic statement ({n_alpha} tokens, {n_kw} concepts) with no narrowed anchor.") if hit
        else "Statement shows specificity signals (length, concepts, or anchored direction)."))

    obs = components["complete_structure"]
    rules.append(_rule("THESIS_004", "OBSERVED" if obs else "INACTIVE",
        "declarative AND subject AND finite verb", obs, ev,
        "Declarative sentence with subject and finite verb: readable as a central claim." if obs
        else "No complete declarative claim structure detected."))

    hit = n_fin >= config.THESIS_SCOPE_MIN_VERBS
    rules.append(_rule("THESIS_005", "TRIGGERED" if hit else "INACTIVE",
        f"finite_verbs>={config.THESIS_SCOPE_MIN_VERBS}", hit, {**ev, "finite_verbs": components["finite_verbs"]},
        f"{n_fin} finite verbs suggest several claims competing in one sentence." if hit
        else f"Predicate load ok ({n_fin} finite verbs)."))

    if not topic_ran:
        rules.append(_rule("THESIS_006", "SKIPPED", "topic pipeline did not run", False, ev,
            "Topic alignment unknown: no assignment topic supplied."))
    else:
        # Composite supporting-evidence rule (cosine untouched): WEAK cosine
        # alone misleads on single sentences, so it only counts when fewer
        # than THESIS_MIN_SUPPORT_MATCHES direct/lemma/WordNet matches exist.
        weak = topic_classification == "WEAK" and support_matches < config.THESIS_MIN_SUPPORT_MATCHES
        rules.append(_rule("THESIS_006", "TRIGGERED" if weak else "INACTIVE",
            f"WEAK cosine AND support_matches<{config.THESIS_MIN_SUPPORT_MATCHES}", weak,
            {**ev, "support_matches": support_matches},
            f"Weak topic connection with only {support_matches} supporting match(es)." if weak
            else f"Topic supported ({support_matches} match(es), classification {topic_classification})."))

    hit = not stance and not causal and components["declarative"]
    rules.append(_rule("THESIS_007", "TRIGGERED" if hit else "INACTIVE",
        "declarative AND no stance marker AND no causal marker", hit, ev,
        "Statement describes without signaling a direction; explanatory theses are still respected — consider whether a direction is intended." if hit
        else "Direction signals present."))

    hit = n_kw >= config.THESIS_OVERLOAD_MIN_KEYWORDS and n_fin >= config.THESIS_OVERLOAD_MIN_VERBS
    rules.append(_rule("THESIS_008", "TRIGGERED" if hit else "INACTIVE",
        f"keywords>={config.THESIS_OVERLOAD_MIN_KEYWORDS} AND finite_verbs>={config.THESIS_OVERLOAD_MIN_VERBS}",
        hit, ev,
        f"{n_kw} concepts across {n_fin} predicates: possibly overloaded." if hit
        else "Concept load within one focus."))

    hit = len(vague) >= 2 or components["pronoun_subject"]
    rules.append(_rule("THESIS_009", "TRIGGERED" if hit else "INACTIVE",
        "vague_markers>=2 OR pronoun subject", hit, {**ev},
        f"Vague references detected: {vague} / pronoun subject." if hit else "No excessive vagueness detected."))

    critical = any(r["status"] == "TRIGGERED" for r in rules if r["rule_id"] in ("THESIS_003", "THESIS_005", "THESIS_007", "THESIS_008", "THESIS_009"))
    hit = components["complete_structure"] and not critical
    rules.append(_rule("THESIS_010", "OBSERVED" if hit else "INACTIVE",
        "complete structure AND no critical thesis flag", hit, ev,
        "Statement is structurally complete with no critical flag; ready to sharpen." if hit
        else "Critical thesis flags remain."))
    return rules


def check_alignment(thesis_keywords: list[str], stage1_keywords: list[str] | None) -> dict:
    """Stage1->Stage2 consistency via keyword-overlap ratio (heuristic)."""
    if stage1_keywords is None:
        return {"status": "SKIPPED", "reason": "No linked Stage 1 idea supplied.",
                "classification": None, "overlap": None, "shared": [], "thesis_only": [], "stage1_only": []}
    t_set, s_set = set(thesis_keywords), set(stage1_keywords)
    overlap = len(t_set & s_set) / len(t_set) if t_set else 0.0
    if overlap >= config.STAGE2_ALIGN_HIGH:
        cls = "ALIGNED"
    elif overlap >= config.STAGE2_ALIGN_LOW:
        cls = "PARTIALLY ALIGNED"
    else:
        cls = "POSSIBLY DRIFTED"
    return {"status": "EVALUATED", "classification": cls, "overlap": round(overlap, 4),
            "shared": sorted(t_set & s_set), "thesis_only": sorted(t_set - s_set),
            "stage1_only": sorted(s_set - t_set),
            "reason": f"Keyword overlap {overlap:.2f} (thresholds {config.STAGE2_ALIGN_LOW}/{config.STAGE2_ALIGN_HIGH})."}


def select_thesis_prompts(rule_results: list[dict], alignment: dict, shown_ids: set[str] | None = None, max_n: int | None = None) -> dict:
    """Map fired rules (+drifted alignment) to up to max_n questions."""
    shown_ids = set(shown_ids or [])
    max_n = config.STAGE2_MAX_PROMPTS if max_n is None else max_n
    # THESIS_002 speaks "ISSUE" (native rule vocabulary): include it and give
    # it selection metadata without changing the rule's own meaning.
    for r in rule_results:
        if r["rule_id"] == "THESIS_002" and r["status"] == "ISSUE":
            r.setdefault("prompt_category", "META")
            r.setdefault("priority_rank", config.PREWRITE_PRIORITY["CRITICAL"])
            r.setdefault("priority", "CRITICAL")
    candidates = [r for r in rule_results if r["status"] in ("TRIGGERED", "OBSERVED", "ISSUE")]
    if alignment.get("classification") == "POSSIBLY DRIFTED":
        candidates.append({"rule_id": "ALIGN_001", "prompt_category": "ALIGNMENT",
                           "priority_rank": config.PREWRITE_PRIORITY["HIGH"], "priority": "HIGH",
                           "reason": "Thesis focus differs from the Stage 1 idea (" + alignment["reason"] + ")"})
    candidates = [r for r in candidates if r["rule_id"] != "THESIS_001"]
    candidates.sort(key=lambda r: (r["priority_rank"], r["rule_id"]))
    prompts = []
    chosen: set[str] = set()
    for r in candidates[:max_n]:
        options = THESIS_PROMPT_BANK[r["prompt_category"]]
        choice = next((p for p in options if p[0] not in shown_ids and p[0] not in chosen), options[0])
        chosen.add(choice[0])
        prompts.append({"prompt_id": choice[0], "category": r["prompt_category"], "text": choice[1],
                        "rule_id": r["rule_id"], "priority": r["priority"], "why_shown": r["reason"]})
    from services.rhetorical_moves import ground_prompt

    return {"prompts": [ground_prompt(p) for p in prompts], "max_shown": max_n}


def check_thesis_readiness(components: dict, all_rules: list[dict], alignment: dict, topic_ran: bool, topic_classification: str | None, support_matches: int = 0) -> dict:
    """Explicit C1-C7 readiness. Grammar never blocks (only structure does)."""
    fired = {r["rule_id"] for r in all_rules if r["status"] == "TRIGGERED"}
    has_candidate = any(r["rule_id"] == "THESIS_001" and r["status"] == "CANDIDATE" for r in all_rules)
    c1 = has_candidate
    c2 = not any(r["rule_id"] == "THESIS_002" and r["status"] == "ISSUE" for r in all_rules)
    c3 = components["complete_structure"]
    # Same composite as THESIS_006 (cosine untouched): WEAK cosine is only
    # critical without supporting matches.
    c4 = ((topic_classification != "WEAK") or (support_matches >= config.THESIS_MIN_SUPPORT_MATCHES)) if topic_ran else True
    c4_note = (f"Topic connection is {topic_classification} with {support_matches} supporting match(es)."
               if topic_ran else "No assignment topic supplied.")
    c5 = "THESIS_003" not in fired
    c6 = not (fired & {"THESIS_005", "THESIS_008"})
    c7 = any(r["rule_id"] in ("THESIS_004", "THESIS_010") and r["status"] == "OBSERVED" for r in all_rules) or bool(
        components["possible_stance_markers"] or components["possible_cause_effect"])
    conditions = [
        {"id": "C1", "name": "Thesis candidate detected", "result": "PASS" if c1 else "FAIL",
         "detail": "THESIS_001 candidate present." if c1 else "No declarative claim candidate found."},
        {"id": "C2", "name": "Meta-statement absent", "result": "PASS" if c2 else "FAIL",
         "detail": "No meta-statement." if c2 else "THESIS_002 meta-statement active."},
        {"id": "C3", "name": "Basic structural completeness", "result": "PASS" if c3 else "FAIL",
         "detail": f"Declarative={components['declarative']}, subject={components['detected_subject']}, verb={components['main_verb']}."},
        {"id": "C4", "name": "Topic alignment not critically weak", "result": "PASS" if c4 else "FAIL", "detail": c4_note},
        {"id": "C5", "name": "Specificity/focus acceptable", "result": "PASS" if c5 else "FAIL",
         "detail": "THESIS_003 active." if not c5 else "No broad-thesis flag."},
        {"id": "C6", "name": "No critical scope problem", "result": "PASS" if c6 else "FAIL",
         "detail": f"Active scope flags: {sorted(fired & {'THESIS_005', 'THESIS_008'}) or 'none'}."},
        {"id": "C7", "name": "Identifiable central direction/claim", "result": "PASS" if c7 else "FAIL",
         "detail": "Direction signals present." if c7 else "No clear direction detected."},
    ]
    if all(c["result"] == "PASS" for c in conditions):
        decision = "READY FOR OUTLINE DEVELOPMENT"
        message = "Your thesis is clear and focused. You can continue to outline development."
    elif not (c1 and c2 and c3):
        decision = "DEVELOPING"
        message = "Your thesis needs more work on its basic form. State one clear claim in your own words."
    else:
        decision = "NEARLY READY"
        message = "Your thesis is taking shape. Review the guidance questions before moving on."
    return {"conditions": conditions, "decision": decision, "student_message": message,
            "stage3_allowed": decision == "READY FOR OUTLINE DEVELOPMENT",
            "blocking_rules": sorted(fired & {"THESIS_002", "THESIS_003", "THESIS_005", "THESIS_006", "THESIS_008"})}


def compare_thesis_revisions(prev: dict, curr: dict) -> dict:
    """Supported-claims-only thesis comparison."""
    deltas = {
        "word_delta": curr["word_count"] - prev["word_count"],
        "concept_delta": curr["concept_count"] - prev["concept_count"],
        "added_keywords": sorted(set(curr["keywords"]) - set(prev["keywords"])),
        "removed_keywords": sorted(set(prev["keywords"]) - set(curr["keywords"])),
        "subject_before": prev.get("subject"), "subject_after": curr.get("subject"),
        "alignment_before": prev.get("alignment"), "alignment_after": curr.get("alignment"),
        "resolved_rules": sorted(set(prev["fired_rules"]) - set(curr["fired_rules"])),
        "new_rules": sorted(set(curr["fired_rules"]) - set(prev["fired_rules"])),
    }
    messages = []
    if "THESIS_002" in deltas["resolved_rules"]:
        messages.append({"text": "The meta-statement is no longer present.", "evidence": "THESIS_002 resolved."})
    if "THESIS_003" in deltas["resolved_rules"]:
        messages.append({"text": "Your thesis has a clearer focus.", "evidence": "THESIS_003 resolved."})
    if deltas["subject_before"] != deltas["subject_after"] and deltas["subject_after"]:
        messages.append({"text": f"Your main subject changed from '{deltas['subject_before']}' to '{deltas['subject_after']}'.",
                         "evidence": "Detected-subject comparison."})
    if deltas["alignment_before"] != deltas["alignment_after"] and deltas["alignment_before"]:
        messages.append({"text": f"Stage 1 alignment changed from {deltas['alignment_before']} to {deltas['alignment_after']}.",
                         "evidence": "Keyword-overlap comparison."})
    if "THESIS_005" in curr["fired_rules"] or "THESIS_008" in curr["fired_rules"]:
        messages.append({"text": "The scope may still be broad.", "evidence": "Scope rule still active."})
    if deltas["added_keywords"]:
        messages.append({"text": f"New concepts: {', '.join(deltas['added_keywords'][:6])}.",
                         "evidence": "Selected-keyword comparison."})
    if not messages:
        messages.append({"text": "No measurable changes yet — revise your thesis in your own words, then re-analyze.",
                         "evidence": "No rule/component movement."})
    return {"deltas": deltas, "messages": messages}
