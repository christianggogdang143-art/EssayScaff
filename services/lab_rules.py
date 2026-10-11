"""Writing Lab experimental section rules (LAB_* namespace).

*** EXPERIMENTAL / DEVELOPMENT RULES — NOT FORMALLY VALIDATED, NOT PART OF VR-2 ***
These rules live outside rules/ and outside the frozen threshold set on
purpose: they must never affect the VR-2 classifier hashes. They judge
only surface/lexical/structural evidence already present in a standard
analysis response (token counts, keyword sets, existing rule statuses,
topic classification). They MUST NOT claim persuasiveness, credibility,
factual correctness, evidence quality, depth, originality, logical
validity, or any quality grade — the reason strings below are audited
for exactly that (see tests/test_lab.py banned-phrase scan).

Every rule declares `blocking` explicitly; it is never inferred from
severity. Statuses: TRIGGERED (condition present), INACTIVE (absent),
SKIPPED (prerequisite input absent — counts as pass for gates).
"""

from __future__ import annotations

import re

import config


def _tokens(analysis: dict) -> list[dict]:
    return ((analysis.get("technical") or {}).get("tokens")) or []


def _sentences(analysis: dict) -> list[dict]:
    return ((analysis.get("technical") or {}).get("sentences")) or []


def _alpha_count(analysis: dict) -> int:
    return sum(1 for t in _tokens(analysis) if t.get("is_alpha"))


def _selected(analysis: dict) -> list[str]:
    tech = analysis.get("technical", {}) or {}
    return list((((tech.get("phase2") or {}).get("keywords") or {}).get("selected")) or [])


def _topic_info(analysis: dict) -> tuple[bool, str | None]:
    """(topic pipeline ran, classification or None)."""
    tech = analysis.get("technical", {}) or {}
    phase2 = tech.get("phase2", {}) or {}
    if not phase2.get("ran"):
        return False, None
    cls = ((phase2.get("topic_analysis") or {}).get("classification")) or {}
    return True, cls.get("classification")


def _rule_status(analysis: dict, rule_id: str) -> str | None:
    for r in ((analysis.get("technical") or {}).get("rule_results")) or []:
        if r.get("rule_id") == rule_id:
            return r.get("status")
    return None


def _lt_issue_count(analysis: dict) -> int:
    tech = analysis.get("technical", {}) or {}
    issues = (tech.get("language_tool_results") or {}).get("issues")
    return len(issues) if isinstance(issues, list) else 0


def _rule(rule_id: str, name: str, status: str, condition: str,
          evidence: dict, reason: str, blocking: bool) -> dict:
    return {
        "rule_id": rule_id,
        "rule_name": name,
        "status": status,
        "condition": condition,
        "result": status == "TRIGGERED",
        "evidence": evidence,
        "reason": reason,
        # Display ordering reuses the existing rank scale (read-only);
        # gating uses ONLY the explicit `blocking` flag below.
        "priority": "HIGH" if blocking else "LOW",
        "priority_rank": config.PREWRITE_PRIORITY["HIGH" if blocking else "LOW"],
        "blocking": blocking,
    }


def _alpha_words(text: str) -> set[str]:
    return set(re.findall(r"[a-z']+", (text or "").lower()))


def _overlap_class(shared: int, n_sec: int, n_ref: int) -> str:
    denom = min(n_sec, n_ref)
    ratio = (len(shared) / denom) if denom else 0.0
    if ratio >= config.LAB_BODY_ALIGN_HIGH:
        return "ALIGNED"
    if ratio >= config.LAB_BODY_ALIGN_LOW:
        return "PARTIALLY ALIGNED"
    return "WEAKLY ALIGNED"


# ------------------------------------------------ introduction
def evaluate_intro(analysis: dict) -> list[dict]:
    n_alpha = _alpha_count(analysis)
    ran, cls = _topic_info(analysis)
    cand = _rule_status(analysis, "THESIS_001") == "CANDIDATE"
    meta = _rule_status(analysis, "THESIS_002") == "ISSUE"
    frag = _rule_status(analysis, "MECHANICS_001") == "ISSUE"
    runon = _rule_status(analysis, "MECHANICS_002") == "ISSUE"
    lt_n = _lt_issue_count(analysis)
    rules = [
        _rule("LAB_INTRO_001", "Insufficient introduction development",
              "TRIGGERED" if n_alpha < config.LAB_INTRO_MIN_TOKENS else "INACTIVE",
              f"alpha_token_count < {config.LAB_INTRO_MIN_TOKENS}",
              {"alpha_token_count": n_alpha},
              f"Introduction has {n_alpha} alphabetic tokens."
              if n_alpha < config.LAB_INTRO_MIN_TOKENS else
              f"Introduction has {n_alpha} alphabetic tokens.", True),
        _rule("LAB_INTRO_002", "Topic connection critically weak",
              "SKIPPED" if not ran else ("TRIGGERED" if cls == "WEAK" else "INACTIVE"),
              "topic_classification == WEAK",
              {"topic_ran": ran, "topic_classification": cls},
              "No assignment topic supplied; topic connection unknown."
              if not ran else (f"Topic connection is WEAK." if cls == "WEAK"
                               else f"Topic connection is {cls}."), True),
        _rule("LAB_INTRO_003", "No central direction detected",
              "TRIGGERED" if not cand else "INACTIVE",
              "THESIS_001 status != CANDIDATE",
              {"thesis_001": _rule_status(analysis, "THESIS_001")},
              "No sentence reads as a central claim yet."
              if not cand else "A sentence reads as a central claim.", True),
        _rule("LAB_INTRO_004", "Blocking meta/structural issue present",
              "TRIGGERED" if (meta or frag or runon) else "INACTIVE",
              "THESIS_002 ISSUE or MECHANICS_001/002 ISSUE",
              {"meta_statement": meta, "fragment": frag, "run_on": runon},
              "A meta-statement, fragment, or run-on needs fixing first."
              if (meta or frag or runon) else "No meta-statement, fragment, or run-on found.", True),
        _rule("LAB_INTRO_005", "Mechanics findings present (advisory)",
              "TRIGGERED" if lt_n else "INACTIVE",
              "language_tool issue count > 0",
              {"lt_issue_count": lt_n},
              f"{lt_n} mechanics note(s) present; they never block progress."
              if lt_n else "No mechanics notes reported.", False),
    ]
    return rules


def check_intro_readiness(rules: list[dict]) -> dict:
    fired = {r["rule_id"] for r in rules if r["status"] == "TRIGGERED" and r["blocking"]}

    def cond(cid: str, name: str, ok: bool, detail: str) -> dict:
        return {"id": cid, "name": name, "result": "PASS" if ok else "FAIL", "detail": detail}

    t = {r["rule_id"]: r["status"] for r in rules}
    conditions = [
        cond("I1", "Sufficient development", t.get("LAB_INTRO_001") != "TRIGGERED",
             "Blocking: introduction too short." if t.get("LAB_INTRO_001") == "TRIGGERED"
             else "Introduction has enough text."),
        cond("I2", "Topic connection is not critically weak", t.get("LAB_INTRO_002") != "TRIGGERED",
             "No topic supplied (not blocking)." if t.get("LAB_INTRO_002") == "SKIPPED"
             else ("Blocking: topic connection is WEAK." if t.get("LAB_INTRO_002") == "TRIGGERED"
                   else "Topic connection holds.")),
        cond("I3", "Central direction/thesis candidate exists", t.get("LAB_INTRO_003") != "TRIGGERED",
             "Blocking: no central claim detected." if t.get("LAB_INTRO_003") == "TRIGGERED"
             else "A central claim is present."),
        cond("I4", "No blocking meta/structural issue", t.get("LAB_INTRO_004") != "TRIGGERED",
             "Blocking: meta-statement or fragment/run-on present."
             if t.get("LAB_INTRO_004") == "TRIGGERED" else "No blocking issue present."),
    ]
    ready = all(c["result"] == "PASS" for c in conditions)
    return {
        "conditions": conditions,
        "decision": "READY FOR BODY" if ready else "NEEDS INTRODUCTION REVISION",
        "student_message": ("Your introduction is ready. Continue with the body of your essay."
                            if ready else
                            "Revise your introduction in your own words, then analyze it again."),
        "intro_ready": ready,
        "blocking_rules": sorted(fired),
    }


# ------------------------------------------------ body
def evaluate_body(analysis: dict, thesis_keywords: list[str] | None,
                  outline_points: list[dict] | None) -> list[dict]:
    n_alpha = _alpha_count(analysis)
    n_sent = len(_sentences(analysis))
    selected = _selected(analysis)
    cand = _rule_status(analysis, "THESIS_001") == "CANDIDATE"
    lt_n = _lt_issue_count(analysis)
    thesis_kw = [k.lower() for k in (thesis_keywords or [])]
    body_kw = [k.lower() for k in selected]
    shared_thesis = sorted(set(body_kw) & set(thesis_kw))
    thesis_cls = _overlap_class(shared_thesis, len(body_kw), len(thesis_kw))
    if thesis_keywords is None:
        thesis_status, thesis_reason = "SKIPPED", "No linked thesis to compare against."
    else:
        thesis_status = "TRIGGERED" if thesis_cls == "WEAKLY ALIGNED" else "INACTIVE"
        thesis_reason = (f"Weak lexical connection to the thesis "
                         f"(shared: {', '.join(shared_thesis[:10]) or 'none'})."
                         if thesis_status == "TRIGGERED" else
                         f"Lexical connection to the thesis holds ({thesis_cls.lower()}).")
    best = {"index": None, "shared": [], "classification": None}
    if outline_points is None:
        outline_status, outline_reason = "SKIPPED", "No linked outline to compare against."
    else:
        for i, p in enumerate(outline_points):
            # Crude lexical sets (lowercased alpha words, no stopword removal):
            # transparent by design, documented as experimental.
            words = _alpha_words(p.get("text", "") + " " + " ".join(p.get("details") or []))
            shared = sorted(set(body_kw) & words)
            cls = _overlap_class(shared, len(body_kw), len(words))
            rank = {"ALIGNED": 2, "PARTIALLY ALIGNED": 1, "WEAKLY ALIGNED": 0}[cls]
            best_rank = {"ALIGNED": 2, "PARTIALLY ALIGNED": 1, "WEAKLY ALIGNED": 0}.get(
                best["classification"], -1)
            if rank > best_rank:
                best = {"index": i + 1, "shared": shared, "classification": cls}
        outline_status = "TRIGGERED" if best["classification"] == "WEAKLY ALIGNED" else "INACTIVE"
        outline_reason = (f"Weak lexical connection to every outline point."
                          if outline_status == "TRIGGERED" else
                          f"Connects to outline point {best['index']} ({best['classification'].lower()}).")
    seen: dict[str, int] = {}
    for s in _sentences(analysis):
        key = " ".join((s.get("text") or "").lower().split())
        if key:
            seen[key] = seen.get(key, 0) + 1
    dupes = sorted(k for k, v in seen.items() if v > 1)
    rules = [
        _rule("LAB_BODY_001", "Insufficient body development",
              "TRIGGERED" if n_alpha < config.LAB_BODY_MIN_TOKENS else "INACTIVE",
              f"alpha_token_count < {config.LAB_BODY_MIN_TOKENS}",
              {"alpha_token_count": n_alpha},
              f"Body text has {n_alpha} alphabetic tokens."
              if n_alpha < config.LAB_BODY_MIN_TOKENS else
              f"Body text has {n_alpha} alphabetic tokens.", True),
        _rule("LAB_BODY_002", "No main claim candidate",
              "TRIGGERED" if not cand else "INACTIVE",
              "THESIS_001 status != CANDIDATE",
              {"thesis_001": _rule_status(analysis, "THESIS_001")},
              "No sentence reads as a main claim yet."
              if not cand else "A sentence reads as a main claim.", True),
        _rule("LAB_BODY_003", "Weak lexical connection to thesis",
              thesis_status, "thesis overlap WEAKLY ALIGNED",
              {"shared": shared_thesis[:10], "classification": thesis_cls},
              thesis_reason, True),
        _rule("LAB_BODY_004", "Weak lexical connection to outline",
              outline_status, "best outline-point overlap WEAKLY ALIGNED",
              {"best_point": best["index"], "shared": best["shared"][:10],
               "classification": best["classification"]},
              outline_reason, True),
        _rule("LAB_BODY_005", "Support/detail text thin",
              "TRIGGERED" if n_sent < 2 else "INACTIVE",
              "sentence_count < 2",
              {"sentence_count": n_sent},
              "Only one sentence so far; a claim plus support reads stronger. Advisory only."
              if n_sent < 2 else f"{n_sent} sentences present.", False),
        _rule("LAB_BODY_006", "Repeated sentence detected",
              "TRIGGERED" if dupes else "INACTIVE",
              "exact duplicate sentence present",
              {"duplicates": [d[:120] for d in dupes[:3]], "duplicate_count": len(dupes)},
              "A sentence repeats word-for-word; vary or remove it. Advisory only."
              if dupes else "No repeated sentences.", False),
        _rule("LAB_BODY_007", "Mechanics findings present (advisory)",
              "TRIGGERED" if lt_n else "INACTIVE",
              "language_tool issue count > 0",
              {"lt_issue_count": lt_n},
              f"{lt_n} mechanics note(s) present; they never block progress."
              if lt_n else "No mechanics notes reported.", False),
    ]
    return rules


def check_body_readiness(rules: list[dict]) -> dict:
    t = {r["rule_id"]: r["status"] for r in rules}
    fired = {r["rule_id"] for r in rules if r["status"] == "TRIGGERED" and r["blocking"]}

    def cond(cid: str, name: str, ok: bool, detail: str) -> dict:
        return {"id": cid, "name": name, "result": "PASS" if ok else "FAIL", "detail": detail}

    t3 = "TRIGGERED" if (t.get("LAB_BODY_003") == "TRIGGERED"
                         or t.get("LAB_BODY_004") == "TRIGGERED") else t.get("LAB_BODY_003", "INACTIVE")
    conditions = [
        cond("B1", "Minimum body structure exists", t.get("LAB_BODY_001") != "TRIGGERED",
             "Blocking: body text too short." if t.get("LAB_BODY_001") == "TRIGGERED"
             else "Body structure present."),
        cond("B2", "Main claim present", t.get("LAB_BODY_002") != "TRIGGERED",
             "Blocking: no main claim detected." if t.get("LAB_BODY_002") == "TRIGGERED"
             else "A main claim is present."),
        cond("B3", "Thesis/outline connection not weak", t3 != "TRIGGERED",
             "Blocking: weak connection to thesis/outline." if t3 == "TRIGGERED"
             else "Thesis/outline connection holds."),
    ]
    ready = all(c["result"] == "PASS" for c in conditions)
    return {
        "conditions": conditions,
        "decision": "READY FOR CONCLUSION" if ready else "NEEDS BODY REVISION",
        "student_message": ("Your body section is ready. Continue with your conclusion."
                            if ready else
                            "Revise your body section in your own words, then analyze it again."),
        "body_ready": ready,
        "blocking_rules": sorted(fired),
    }


# ------------------------------------------------ conclusion
def evaluate_conclusion(analysis: dict, thesis_keywords: list[str] | None) -> list[dict]:
    n_alpha = _alpha_count(analysis)
    selected = _selected(analysis)
    concl_kw = [k.lower() for k in selected]
    ran, cls = _topic_info(analysis)
    thesis_kw = [k.lower() for k in (thesis_keywords or [])]
    if thesis_keywords is None and not ran:
        ret_status, ret_reason = "SKIPPED", "No linked thesis and no topic to return to."
        ret_ev = {"thesis_linked": False, "topic_ran": False}
    else:
        shared = sorted(set(concl_kw) & set(thesis_kw))
        overlap = _overlap_class(shared, len(concl_kw), max(len(thesis_kw), 1))
        weak_return = (overlap == "WEAKLY ALIGNED") and not (ran and cls in ("MODERATE", "STRONG"))
        ret_status = "TRIGGERED" if weak_return else "INACTIVE"
        ret_reason = ("Little lexical return to the thesis or topic; restate the main direction."
                      if weak_return else "The conclusion returns to the main direction.")
        ret_ev = {"shared": shared[:10], "overlap": overlap,
                  "topic_classification": cls, "thesis_linked": thesis_keywords is not None}
    novel = sorted(set(concl_kw) - set(thesis_kw))
    novel_hit = bool(concl_kw) and len(novel) == len(concl_kw) and len(concl_kw) >= config.LAB_CONC_NOVEL_MIN_CONCEPTS
    frag = _rule_status(analysis, "MECHANICS_001") == "ISSUE"
    runon = _rule_status(analysis, "MECHANICS_002") == "ISSUE"
    struct_hit = frag or runon
    rules = [
        _rule("LAB_CONC_001", "Insufficient conclusion development",
              "TRIGGERED" if n_alpha < config.LAB_CONC_MIN_TOKENS else "INACTIVE",
              f"alpha_token_count < {config.LAB_CONC_MIN_TOKENS}",
              {"alpha_token_count": n_alpha},
              f"Conclusion has {n_alpha} alphabetic tokens."
              if n_alpha < config.LAB_CONC_MIN_TOKENS else
              f"Conclusion has {n_alpha} alphabetic tokens.", True),
        _rule("LAB_CONC_002", "Weak lexical return to thesis/topic",
              ret_status, "no shared thesis/topic concepts",
              ret_ev, ret_reason, True),
        _rule("LAB_CONC_003", "Possibly new competing ideas (advisory)",
              "TRIGGERED" if novel_hit else "INACTIVE",
              "all conclusion concepts novel",
              {"novel": novel[:10], "concept_count": len(concl_kw)},
              "Every concept here is new to the essay; check nothing competing was added. Advisory only."
              if novel_hit else "Conclusion stays with established concepts.", False),
        _rule("LAB_CONC_004", "Fragment/run-on present (advisory)",
              "TRIGGERED" if struct_hit else "INACTIVE",
              "MECHANICS_001/002 ISSUE",
              {"fragment": frag, "run_on": runon},
              "A fragment or run-on is present; fix it when polishing. Advisory only."
              if struct_hit else "No fragment or run-on found.", False),
    ]
    return rules


def check_conc_readiness(rules: list[dict]) -> dict:
    t = {r["rule_id"]: r["status"] for r in rules}
    fired = {r["rule_id"] for r in rules if r["status"] == "TRIGGERED" and r["blocking"]}

    def cond(cid: str, name: str, ok: bool, detail: str) -> dict:
        return {"id": cid, "name": name, "result": "PASS" if ok else "FAIL", "detail": detail}

    conditions = [
        cond("C1", "Sufficient conclusion text", t.get("LAB_CONC_001") != "TRIGGERED",
             "Blocking: conclusion too short." if t.get("LAB_CONC_001") == "TRIGGERED"
             else "Conclusion has enough text."),
        cond("C2", "Lexical return to thesis/topic", t.get("LAB_CONC_002") != "TRIGGERED",
             "No thesis/topic link to check (not blocking)." if t.get("LAB_CONC_002") == "SKIPPED"
             else ("Blocking: weak return to the main direction." if t.get("LAB_CONC_002") == "TRIGGERED"
                   else "Conclusion returns to the main direction.")),
    ]
    ready = all(c["result"] == "PASS" for c in conditions)
    return {
        "conditions": conditions,
        "decision": "READY FOR FINAL REVIEW" if ready else "NEEDS CONCLUSION REVISION",
        "student_message": ("Your conclusion is ready. Review the full essay before submitting."
                            if ready else
                            "Revise your conclusion in your own words, then analyze it again."),
        "conc_ready": ready,
        "blocking_rules": sorted(fired),
    }
