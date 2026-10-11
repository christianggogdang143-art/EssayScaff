"""Phase 6 Stage 4: reflection, cross-stage consistency, adaptive fading.

Deterministic and non-generative. Reads stored Stage 1/2/3 revision
histories, classifies every past issue as RESOLVED / STILL ACTIVE / NEW /
RECURRING / REGRESSION / STABLE, decides an explicit scaffold level
(3 HIGH … 0 INDEPENDENT), and selects fading reflective prompts.

Scaffold levels are pedagogical (Scaffolding Theory), never "AI confidence".
A single resolved revision is IMPROVING, not STABLE: stability requires
persistence across multiple revisions (STAGE4_STABLE_MIN_QUIET).
Support may INCREASE again on regression — fading is not one-directional.
"""

from __future__ import annotations

import time

import config

# rule_id -> (rule_name, prompt_category, priority_name)
REFLECT_RULE_DEFS: dict[str, tuple[str, str, str]] = {
    "REFLECT_001": ("Stage 1 idea and Stage 2 thesis are inconsistent", "CONSISTENCY", "CRITICAL"),
    "REFLECT_002": ("Body point weakly aligned to thesis remains", "ALIGNMENT", "HIGH"),
    "REFLECT_003": ("Supporting detail weakly aligned remains", "DETAIL_ALIGNMENT", "HIGH"),
    "REFLECT_004": ("Outline duplication unresolved", "DISTINCTION", "HIGH"),
    "REFLECT_005": ("Outline overload unresolved", "FOCUS", "MEDIUM"),
    "REFLECT_006": ("Logical progression still weak", "FLOW", "MEDIUM"),
    "REFLECT_007": ("Issue persists across multiple revisions", "CONSISTENCY", "HIGH"),
    "REFLECT_008": ("Previously detected issue was resolved", "COMPLETENESS", "LOW"),
    "REFLECT_009": ("Most critical scaffold issues resolved", "COMPLETENESS", "LOW"),
    "REFLECT_010": ("Stable improvement demonstrated", "REVIEW", "LOW"),
    "REFLECT_011": ("Independent reflection appropriate", "REVIEW", "LOW"),
    "REFLECT_012": ("Regression: resolved issue reappeared", "CONSISTENCY", "HIGH"),
    "REFLECT_013": ("Earlier-stage major issue still active", "REVIEW", "HIGH"),
}

MAJOR_PRIORITIES = {"CRITICAL", "HIGH"}

# Prompt bank: category -> scaffold level -> [(prompt_id, text)].
# Every string is a question or reflection cue. Nothing supplies student
# wording (protected by the authorship test).
REFLECT_PROMPT_BANK: dict[str, dict[str, list[tuple[str, str]]]] = {
    "CONSISTENCY": {
        "HIGH": [
            ("RCON_H1", "Does your thesis still represent the idea you developed at the beginning?"),
            ("RCON_H2", "Which part of your plan no longer matches your original idea, and why did it change?"),
        ],
        "MODERATE": [
            ("RCON_M1", "Does your thesis still reflect your Stage 1 idea?"),
        ],
        "LIGHT": [
            ("RCON_L1", "Quick check: thesis still matches your original idea?"),
        ],
        "INDEPENDENT": [
            ("RCON_I1", "If you reviewed this plan without system guidance, what would you revise first?"),
        ],
    },
    "ALIGNMENT": {
        "HIGH": [
            ("RALI_H1", "This main point appears only partly connected to your thesis. Review the main concepts in both statements. How does this point directly help explain or support your central claim?"),
            ("RALI_H2", "Which words in this body point connect back to your thesis, and which words pull away from it?"),
        ],
        "MODERATE": [
            ("RALI_M1", "How does this main point directly contribute to your thesis?"),
        ],
        "LIGHT": [
            ("RALI_L1", "Check this point ↔ thesis alignment."),
        ],
        "INDEPENDENT": [
            ("RALI_I1", "If you reviewed this plan without system guidance, what would you revise first?"),
        ],
    },
    "DETAIL_ALIGNMENT": {
        "HIGH": [
            ("RDET_H1", "This supporting detail appears to introduce a different topic from its main point. How does this detail directly support the main point above?"),
            ("RDET_H2", "What information would show that this detail belongs to this paragraph and not another one?"),
        ],
        "MODERATE": [
            ("RDET_M1", "Does each supporting detail explain its parent point?"),
        ],
        "LIGHT": [
            ("RDET_L1", "Check each detail against its parent point."),
        ],
        "INDEPENDENT": [
            ("RDET_I1", "If you reviewed this plan without system guidance, what would you revise first?"),
        ],
    },
    "DISTINCTION": {
        "HIGH": [
            ("RDIS_H1", "These two main points appear to cover very similar ideas. Do these points need to remain separate, or are they developing the same idea?"),
            ("RDIS_H2", "How is this main point different from your other points, in your own words?"),
        ],
        "MODERATE": [
            ("RDIS_M1", "Are any two main points still developing the same idea?"),
        ],
        "LIGHT": [
            ("RDIS_L1", "Check that each point adds something distinct."),
        ],
        "INDEPENDENT": [
            ("RDIS_I1", "If you reviewed this plan without system guidance, what would you revise first?"),
        ],
    },
    "FOCUS": {
        "HIGH": [
            ("RFOC_H1", "This main point may contain several different ideas. Which single idea should this paragraph mainly develop, and what would you move elsewhere?"),
            ("RFOC_H2", "Which idea is most important in this statement?"),
        ],
        "MODERATE": [
            ("RFOC_M1", "Is any main point trying to cover more than one idea?"),
        ],
        "LIGHT": [
            ("RFOC_L1", "Check each point holds one main idea."),
        ],
        "INDEPENDENT": [
            ("RFOC_I1", "If you reviewed this plan without system guidance, what would you revise first?"),
        ],
    },
    "FLOW": {
        "HIGH": [
            ("RFLO_H1", "These two points share no concepts and no ordering cue. What relationship should the reader understand between them, and which point should come first?"),
            ("RFLO_H2", "How does this point connect to the point before it?"),
        ],
        "MODERATE": [
            ("RFLO_M1", "Does the order of your main points create a clear progression?"),
        ],
        "LIGHT": [
            ("RFLO_L1", "Check the order of your main points."),
        ],
        "INDEPENDENT": [
            ("RFLO_I1", "If you reviewed this plan without system guidance, what would you revise first?"),
        ],
    },
    "COMPLETENESS": {
        "HIGH": [
            ("RCOM_H1", "Is there an important part of your thesis that your outline has not addressed yet?"),
        ],
        "MODERATE": [
            ("RCOM_M1", "Does your outline address the major direction of your thesis?"),
        ],
        "LIGHT": [
            ("RCOM_L1", "Check nothing central to your thesis is missing."),
        ],
        "INDEPENDENT": [
            ("RCOM_I1", "If you reviewed this plan without system guidance, what would you revise first?"),
        ],
    },
    "REVIEW": {
        "HIGH": [
            ("RREV_H1", "Which unresolved issue should you return to first: your idea, your thesis, or your outline?"),
        ],
        "MODERATE": [
            ("RREV_M1", "What still needs attention before you write?"),
        ],
        "LIGHT": [
            ("RREV_L1", "Review the alignment of your outline with your thesis."),
        ],
        "INDEPENDENT": [
            ("RREV_I1", "If you reviewed this plan without system guidance, what would you revise first?"),
        ],
    },
}

# Student-controlled checklist (LIGHT/INDEPENDENT). Display only; the
# backend never marks items checked.
CHECKLIST_ITEMS = [
    "My thesis clearly states my main direction.",
    "Each body point supports my thesis.",
    "Each supporting detail supports its body point.",
    "My body points are distinct.",
    "My points appear in a logical order.",
]

LEVEL_LABELS = {3: "HIGH SUPPORT", 2: "MODERATE SUPPORT", 1: "LIGHT SUPPORT", 0: "INDEPENDENT REFLECTION"}


def _rule(rule_id: str, status: str, evidence: dict, reason: str) -> dict:
    name, category, priority = REFLECT_RULE_DEFS[rule_id]
    return {"rule_id": rule_id, "rule_name": name, "status": status,
            "evidence": evidence, "reason": reason, "prompt_category": category,
            "priority": priority, "priority_rank": config.PREWRITE_PRIORITY[priority]}


def rule_stage(rule_id: str) -> int | None:
    """Which stage owns a rule, from its prefix. None if unknown."""
    if rule_id.startswith("PREWRITE_"):
        return 1
    if rule_id.startswith(("THESIS_", "ALIGN_")):
        return 2
    if rule_id.startswith("OUTLINE_"):
        return 3
    if rule_id.startswith("REFLECT_"):
        return 4
    return None


def _severity_of(rule_id: str) -> str:
    """Major = CRITICAL/HIGH from the owning module's RULE_DEFS.

    Unknown rule IDs default to MEDIUM but are logged, so a removed or
    misspelled rule can never silently misclassify a scaffold decision.
    """
    import logging

    entry = None
    if rule_id.startswith("PREWRITE_"):
        from services.prewriting import RULE_DEFS

        entry = RULE_DEFS.get(rule_id)
    elif rule_id.startswith(("THESIS_", "ALIGN_")):
        from services.thesis import THESIS_RULE_DEFS

        entry = THESIS_RULE_DEFS.get(rule_id)
    elif rule_id.startswith("OUTLINE_"):
        from services.outline import OUTLINE_RULE_DEFS

        entry = OUTLINE_RULE_DEFS.get(rule_id)
    elif rule_id.startswith("REFLECT_"):
        entry = REFLECT_RULE_DEFS.get(rule_id)
    if entry is None:
        logging.getLogger(__name__).warning(
            "Unknown rule id in severity lookup: %r; defaulting to MEDIUM", rule_id
        )
        return "MEDIUM"
    return entry[2]


def build_issue_history(stage_histories: dict[int, list[dict]]) -> dict:
    """Aggregate per-rule timelines across stage sessions.

    stage_histories: {stage_number: [{"revision": int, "fired": [rule_ids]}]}.
    Returns {"by_rule": {rid: {"stage", "timeline", "triggers"}}, "total_revisions"}.
    Pure function of stored records — no recomputation, no invention.
    """
    by_rule: dict[str, dict] = {}
    total = 0
    for stage in sorted(stage_histories):
        for entry in stage_histories[stage]:
            total += 1
            fired = set(entry.get("fired", []))
            for rid in fired:
                rec = by_rule.setdefault(rid, {"stage": stage, "timeline": [], "triggers": 0})
                rec["timeline"].append({"revision": entry.get("revision"), "active": True})
                rec["triggers"] += 1
            # Record inactive revisions only for rules already seen (known timeline).
            for rid, rec in by_rule.items():
                if rec["stage"] == stage and rid not in fired:
                    # Only extend timelines within the rule's own stage.
                    if any(t.get("revision") is not None for t in rec["timeline"]):
                        rec["timeline"].append({"revision": entry.get("revision"), "active": False})
    # Drop rules whose stage sessions were never linked (no timeline at all).
    by_rule = {rid: rec for rid, rec in by_rule.items() if rec["timeline"]}
    return {"by_rule": by_rule, "total_revisions": total}


def classify_history(history: dict) -> dict:
    """Classify each known issue. Deterministic; see config thresholds."""
    resolved, active, new, recurring, regressions, stable = [], [], [], [], [], []
    for rid, rec in history.get("by_rule", {}).items():
        timeline = rec.get("timeline", [])
        if not timeline:
            continue
        latest_active = bool(timeline[-1].get("active"))
        prior = timeline[:-1]
        prior_active = sum(1 for t in prior if t.get("active"))
        ever_active = rec.get("triggers", 0) > 0
        item = {"rule_id": rid, "stage": rec.get("stage"),
                "triggers": rec.get("triggers", 0),
                "timeline": [(t.get("revision"), bool(t.get("active"))) for t in timeline]}
        trailing_quiet = 0
        for t in reversed(timeline):
            if t.get("active"):
                break
            trailing_quiet += 1
        # Regression: inactive somewhere after an active revision, active again at latest.
        saw_inactive_after_active = False
        seen_active = False
        for t in timeline:
            if t.get("active"):
                if saw_inactive_after_active:
                    break
                seen_active = True
            elif seen_active:
                saw_inactive_after_active = True
        else:
            saw_inactive_after_active = False
        regressed = bool(latest_active and saw_inactive_after_active)
        if latest_active:
            active.append(item)
            if rec.get("triggers", 0) == 1 and not prior_active:
                new.append(item)
            if prior_active >= config.STAGE4_RECURRING_MIN_PRIOR:
                recurring.append(item)
            if regressed:
                regressions.append(item)
        elif ever_active:
            resolved.append(item)
            if trailing_quiet >= config.STAGE4_STABLE_MIN_QUIET:
                stable.append(item)
    return {"resolved": resolved, "active": active, "new": new,
            "recurring": recurring, "regressions": regressions, "stable": stable}


def build_consistency_snapshot(s1_last: dict | None, s2_last: dict | None, s3_last: dict | None) -> dict:
    """Cross-stage consistency from STORED records (no recomputation).

    Preserves the separate concepts: topic relevance vs thesis alignment vs
    parent-child alignment vs outline progression.
    """
    snap: dict = {"idea_thesis": None, "thesis_points": [], "point_details": {},
                  "progression": [], "stages_present": []}
    if s1_last is not None:
        snap["stages_present"].append(1)
    # IDEA <-> THESIS: recomputed deterministically from stored keywords
    # (pure set overlap; no NLP rerun).
    if s1_last is not None and s2_last is not None:
        snap["stages_present"].append(2)
        from services import thesis as thesis_mod

        s1_kw = list((s1_last.get("concepts", {}) or {}).get("selected", []))
        s2_kw = list((s2_last.get("components", {}) or {}).get("important_concepts", []))
        alignment = thesis_mod.check_alignment(s2_kw, s1_kw)
        snap["idea_thesis"] = {
            "classification": alignment.get("classification"),
            "overlap": alignment.get("overlap"),
            "shared": alignment.get("shared", []),
            "stage1_revision": s1_last.get("revision_number"),
            "stage2_revision": s2_last.get("revision_number"),
        }
    if s3_last is not None:
        snap["stages_present"].append(3)
        alignments = s3_last.get("alignments", {}) or {}
        for pa in alignments.get("points", []) or []:
            snap["thesis_points"].append({
                "point": pa.get("point"),
                "classification": pa.get("classification"),
                "direct": pa.get("direct", []),
                "cosine": pa.get("cosine"),
            })
        for key, da in (alignments.get("details", {}) or {}).items():
            snap["point_details"][key] = {
                "classification": da.get("classification"),
                "direct": da.get("direct", []),
            }
        for pr in s3_last.get("progression", []) or []:
            snap["progression"].append({
                "pair": pr.get("pair"),
                "shared_concepts": pr.get("shared_concepts", []),
                "ordering_cues": pr.get("ordering_cues", []),
                "abrupt_shift": bool(pr.get("abrupt_shift")),
            })
    return snap


def evaluate_reflect_rules(snapshot: dict, classes: dict, active_ids: set[str],
                           history: dict | None = None) -> list[dict]:
    """REFLECT_001-012 over snapshot + history classes. Deterministic.

    active_ids: underlying rule IDs active in the latest linked revisions.
    history: raw issue history (needed for critical-ever list); may be empty.
    """
    rules = []
    idea_thesis = snapshot.get("idea_thesis") or {}
    drifted = idea_thesis.get("classification") == "POSSIBLY DRIFTED"
    rules.append(_rule(
        "REFLECT_001", "TRIGGERED" if drifted else "INACTIVE",
        {"idea_thesis": idea_thesis or "not available"},
        f"Thesis/idea overlap {idea_thesis.get('overlap')} ({idea_thesis.get('classification')})."
        if drifted else "Idea and thesis are consistent, or no linked idea/thesis to compare."))
    weak_points = [p["point"] for p in snapshot.get("thesis_points", [])
                   if p.get("classification") == "WEAKLY ALIGNED"]
    rules.append(_rule(
        "REFLECT_002", "TRIGGERED" if weak_points else "INACTIVE",
        {"weak_points": weak_points},
        f"Body point(s) {weak_points} remain weakly aligned to the thesis."
        if weak_points else "No weakly aligned body point remains."))
    weak_details = [k for k, d in snapshot.get("point_details", {}).items()
                    if d.get("classification") == "WEAKLY ALIGNED"]
    rules.append(_rule(
        "REFLECT_003", "TRIGGERED" if weak_details else "INACTIVE",
        {"weak_details": weak_details},
        f"Supporting detail(s) {weak_details} remain weakly aligned."
        if weak_details else "No weakly aligned supporting detail remains."))
    dup_active = "OUTLINE_006" in active_ids
    rules.append(_rule(
        "REFLECT_004", "TRIGGERED" if dup_active else "INACTIVE",
        {"outline_duplication_active": dup_active},
        "Outline duplication is still active." if dup_active else "No active duplication."))
    overload_active = "OUTLINE_008" in active_ids
    rules.append(_rule(
        "REFLECT_005", "TRIGGERED" if overload_active else "INACTIVE",
        {"outline_overload_active": overload_active},
        "An overloaded body point remains." if overload_active else "No overloaded body point remains."))
    abrupt = [pr["pair"] for pr in snapshot.get("progression", []) if pr.get("abrupt_shift")]
    rules.append(_rule(
        "REFLECT_006", "TRIGGERED" if abrupt else "INACTIVE",
        {"abrupt_pairs": abrupt},
        f"Point pair(s) {abrupt} share no concepts and no ordering cue."
        if abrupt else "No abrupt progression shift remains."))
    rec_major = [r for r in classes.get("recurring", []) if _severity_of(r["rule_id"]) in MAJOR_PRIORITIES]
    rules.append(_rule(
        "REFLECT_007", "TRIGGERED" if rec_major else "INACTIVE",
        {"recurring_major": [r["rule_id"] for r in rec_major]},
        f"Persistent issue(s): {', '.join(r['rule_id'] for r in rec_major)}."
        if rec_major else "No issue persists across multiple revisions."))
    resolved = classes.get("resolved", [])
    rules.append(_rule(
        "REFLECT_008", "OBSERVED" if resolved else "INACTIVE",
        {"resolved": [r["rule_id"] for r in resolved]},
        f"Resolved since earlier revisions: {', '.join(r['rule_id'] for r in resolved)}."
        if resolved else "No resolved issue on record yet."))
    critical_hist = [rid for rid in (history or {}).get("by_rule", {})
                     if _severity_of(rid) == "CRITICAL"]
    critical_active_now = [rid for rid in active_ids if _severity_of(rid) == "CRITICAL"]
    cleared = [rid for rid in critical_hist if rid not in critical_active_now]
    rules.append(_rule(
        "REFLECT_009", "OBSERVED" if (critical_hist and not critical_active_now) else "INACTIVE",
        {"critical_ever": critical_hist, "critical_active": critical_active_now},
        f"Critical issue(s) cleared: {', '.join(cleared)}."
        if (critical_hist and not critical_active_now) else "Critical issues remain or none recorded."))
    stable = classes.get("stable", [])
    rules.append(_rule(
        "REFLECT_010", "OBSERVED" if stable else "INACTIVE",
        {"stable": [r["rule_id"] for r in stable]},
        f"Stable improvement on: {', '.join(r['rule_id'] for r in stable)}."
        if stable else "No stable improvement on record yet."))
    # REFLECT_011 is decided with the scaffold level (needs it as input).
    rules.append(_rule(
        "REFLECT_011", "INACTIVE", {"pending_level": True},
        "Independent reflection appropriate once the scaffold level reaches INDEPENDENT."))
    carried = sorted({rid for rid in active_ids if _severity_of(rid) in MAJOR_PRIORITIES})
    rules.append(_rule(
        "REFLECT_013", "TRIGGERED" if carried else "INACTIVE",
        {"carried_major": carried},
        f"Earlier-stage major issue(s) still active: {', '.join(carried)}."
        if carried else "No earlier-stage major issue is still active."))
    regressions = classes.get("regressions", [])
    rules.append(_rule(
        "REFLECT_012", "TRIGGERED" if regressions else "INACTIVE",
        {"regressions": [r["rule_id"] for r in regressions]},
        f"Reappeared after resolution: {', '.join(r['rule_id'] for r in regressions)}."
        if regressions else "No regression on record."))
    return rules


def finalize_reflect_011(rules: list[dict], level: int) -> list[dict]:
    """Set REFLECT_011 OBSERVED only at INDEPENDENT level (deterministic)."""
    for r in rules:
        if r["rule_id"] == "REFLECT_011":
            if level == 0:
                r["status"] = "OBSERVED"
                r["reason"] = "Scaffold level is INDEPENDENT; broad self-review is appropriate."
            else:
                r["status"] = "INACTIVE"
                r["reason"] = "Scaffold level is not INDEPENDENT yet."
    return rules


def decide_scaffold_level(snapshot: dict, classes: dict, reflect_rules: list[dict],
                          history: dict, previous_level: int | None = None) -> dict:
    """Explicit scaffold-level decision. Stateless except for reporting the
    previous level; support rises again naturally when new evidence appears."""
    crit_unresolved = sum(1 for r in reflect_rules
                          if r["status"] == "TRIGGERED" and r["priority"] == "CRITICAL")
    high_unresolved = sum(1 for r in reflect_rules
                          if r["status"] == "TRIGGERED" and r["priority"] == "HIGH")
    rec_major = sum(1 for r in classes.get("recurring", [])
                    if _severity_of(r["rule_id"]) in MAJOR_PRIORITIES)
    reg_major = sum(1 for r in classes.get("regressions", [])
                    if _severity_of(r["rule_id"]) in MAJOR_PRIORITIES)
    stable_n = len(classes.get("stable", []))
    total_revs = history.get("total_revisions", 0)
    major_unresolved = crit_unresolved + high_unresolved

    if crit_unresolved >= 1 or rec_major >= config.STAGE4_RECURRING_MAJOR_FOR_HIGH or reg_major >= 1:
        level = 3
        why = (f"{crit_unresolved} critical unresolved; {rec_major} recurring major; "
               f"{reg_major} major regression(s).")
    elif (major_unresolved == 0 and stable_n >= 1
            and total_revs >= config.STAGE4_MIN_REVISIONS_FOR_INDEPENDENT):
        level = 0
        why = (f"No major issue unresolved; {stable_n} stable resolution(s) across "
               f"{total_revs} revisions.")
    elif major_unresolved == 0:
        level = 1
        why = "Only minor/non-critical observations remain."
    else:
        level = 2
        why = f"{major_unresolved} major issue(s) remain; no forcing critical/recurring/regression condition."
    return {
        "level": level,
        "label": {3: "HIGH SUPPORT", 2: "MODERATE SUPPORT", 1: "LIGHT SUPPORT", 0: "INDEPENDENT REFLECTION"}[level],
        "evidence": {
            "critical_unresolved": crit_unresolved,
            "high_unresolved": high_unresolved,
            "recurring_major": rec_major,
            "major_regressions": reg_major,
            "stable_resolutions": stable_n,
            "total_revisions": total_revs,
            "resolved_since_previous": len(classes.get("resolved", [])),
        },
        "decision_rule": (
            "HIGH if critical_unresolved>=1 OR recurring_major>=2 OR major_regression>=1; "
            "else INDEPENDENT if major_unresolved==0 AND stable>=1 AND revisions>=3; "
            "else LIGHT if major_unresolved==0; else MODERATE."),
        "previous_level": previous_level,
        "reason": ("support reduced because critical issues were resolved"
                   if previous_level is not None and level < previous_level
                   else ("support increased: new or recurring evidence"
                         if previous_level is not None and level > previous_level
                         else "first assessment at this level")),
    }


def select_reflection_prompts(reflect_rules: list[dict], level: int,
                              shown_ids: set[str] | None = None) -> dict:
    """Map fired rules to level-appropriate template variants.

    Same issue type at different levels yields different template IDs
    (fading is structural, not string-length cosmetic).
    """
    shown_ids = set(shown_ids or [])
    level_key = {3: "HIGH", 2: "MODERATE", 1: "LIGHT", 0: "INDEPENDENT"}[level]
    max_n = {3: config.STAGE4_MAX_PROMPTS_HIGH, 2: config.STAGE4_MAX_PROMPTS_MODERATE,
             1: config.STAGE4_MAX_PROMPTS_LIGHT, 0: config.STAGE4_MAX_PROMPTS_INDEPENDENT}[level]
    candidates = [r for r in reflect_rules if r["status"] in ("TRIGGERED", "OBSERVED")]
    candidates.sort(key=lambda r: (r["priority_rank"], r["rule_id"]))
    prompts = []
    chosen: set[str] = set()
    for r in candidates[:max_n]:
        bank = REFLECT_PROMPT_BANK[r["prompt_category"]]
        # Prefer unseen variants at the requested level; then any unused
        # variant at this level; then nearest other level (highest first);
        # only then repeat. A repeated question inside one response would
        # look like a bug, so exact duplicates are the last resort.
        choice = next((p for p in bank[level_key]
                       if p[0] not in shown_ids and p[0] not in chosen), None)
        used_level = level_key
        if choice is None:
            choice = next((p for p in bank[level_key] if p[0] not in chosen), None)
        if choice is None:
            for lv in _near_levels(level_key):
                choice = next((p for p in bank[lv] if p[0] not in chosen), None)
                if choice is not None:
                    used_level = lv
                    break
        if choice is None:
            choice = bank[level_key][0]
        chosen.add(choice[0])
        prompts.append({
            "prompt_id": choice[0],
            "category": r["prompt_category"],
            "text": choice[1],
            "rule_id": r["rule_id"],
            "priority": r["priority"],
            "why_shown": r["reason"],
            "detail_level": used_level,
            "level_requested": level_key,
            "grounding": ground_reflect(r["rule_id"], r["prompt_category"]),
        })
    return {"prompts": prompts, "max_shown": max_n, "detail_level": level_key}


_LEVEL_ORDER = ["HIGH", "MODERATE", "LIGHT", "INDEPENDENT"]


def _near_levels(level_key: str) -> list[str]:
    """Other detail levels nearest-first (for variant exhaustion fallback)."""
    return sorted((lv for lv in _LEVEL_ORDER if lv != level_key),
                  key=lambda lv: abs(_LEVEL_ORDER.index(lv) - _LEVEL_ORDER.index(level_key)))


def ground_reflect(rule_id: str, category: str) -> dict:
    """Honest attribution: our rules are ESSAYSCAFF_RULE (Scaffolding Theory).

    A rhetorical_move is attached ONLY where the underlying AcaWriter-inspired
    vocabulary genuinely applies; LanguageTool-sourced content stays
    LANGUAGETOOL. Never claims external support a rule does not have.
    """
    from services.rhetorical_moves import CATEGORY_MOVE_MAP, CITATION
    from services.rhetorical_moves import RULE_MOVE_MAP

    move = RULE_MOVE_MAP.get(rule_id, CATEGORY_MOVE_MAP.get(category))
    base: dict = {"source_type": "ESSAYSCAFF_RULE",
                  "theoretical_basis": "Scaffolding Theory",
                  "external_basis": None,
                  "rhetorical_move": move,
                  "citation": None}
    if move is not None and rule_id.startswith("REFLECT_"):
        # The move vocabulary is adapted from AcaWriter; the rule itself is ours.
        base["external_basis"] = "rhetorical-move vocabulary only (not detection)"
        base["citation"] = CITATION
    return base


def check_reflection_readiness(level: int, classes: dict, reflect_rules: list[dict],
                               history_present: bool) -> dict:
    """Explicit completion conditions. No percentage; grammar never blocks;
    heuristic LOW observations never block COMPLETE."""
    conditions = []
    c_hist = bool(history_present)
    conditions.append({"id": "R0", "name": "Sufficient revision history",
                       "result": "PASS" if c_hist else "FAIL",
                       "detail": "Linked stage sessions with revisions present."
                                 if c_hist else "No linked revision history."})
    crit = [r["rule_id"] for r in reflect_rules
            if r["status"] == "TRIGGERED" and r["priority"] == "CRITICAL"]
    conditions.append({"id": "R1", "name": "No critical unresolved issue",
                       "result": "PASS" if not crit else "FAIL",
                       "detail": f"Active critical: {crit or 'none'}."})
    rec = [r["rule_id"] for r in classes.get("recurring", [])]
    conditions.append({"id": "R2", "name": "No recurring major issue",
                       "result": "PASS" if not [r for r in classes.get("recurring", [])
                                                if _severity_of(r["rule_id"]) in MAJOR_PRIORITIES] else "FAIL",
                       "detail": f"Recurring: {rec or 'none'}."})
    reg = [r["rule_id"] for r in classes.get("regressions", [])]
    conditions.append({"id": "R3", "name": "No active regression",
                       "result": "PASS" if not reg else "FAIL",
                       "detail": f"Regressions: {reg or 'none'}."})
    stable = [r["rule_id"] for r in classes.get("stable", [])]
    conditions.append({"id": "R4", "name": "Stable improvement demonstrated",
                       "result": "PASS" if stable else "FAIL",
                       "detail": f"Stable: {stable or 'none yet'}."})
    if not c_hist:
        decision = "REFLECTING"
        message = ("Not enough revision history yet to assess fading. "
                   "Review your plan in your own words; nothing here is final.")
    elif level == 3:
        decision = "REFLECTING"
        message = "Several important issues still need attention. Work through the guidance above."
    elif level == 2:
        decision = "REVISION_RECOMMENDED"
        message = "Good progress. A revision addressing the remaining points is recommended."
    elif level == 1:
        decision = "READY_FOR_INDEPENDENT_REVIEW"
        message = "Major scaffold issues are currently resolved. Review the checklist on your own."
    else:
        decision = "COMPLETE"
        message = ("Scaffolding cycle complete. Major scaffold issues are currently "
                   "resolved — this describes your plan's current state, not mastery.")
    return {"conditions": conditions, "decision": decision,
            "student_message": message,
            "reflection_complete": decision == "COMPLETE",
            "blocking": [c["id"] for c in conditions if c["result"] == "FAIL"]}


def compare_reflections(prev: dict | None, curr: dict) -> dict:
    """Level/support movement between consecutive Stage 4 revisions only."""
    if prev is None:
        return {"deltas": None, "messages": [
            {"text": "This is your first reflection. Review your whole plan before revising.",
             "evidence": "No prior Stage 4 revision."}]}
    deltas = {
        "level_before": prev.get("scaffold_level"),
        "level_after": curr.get("scaffold_level"),
        "unresolved_before": sorted(prev.get("unresolved", [])),
        "unresolved_after": sorted(curr.get("unresolved", [])),
        "resolved_now": sorted(set(prev.get("unresolved", [])) - set(curr.get("unresolved", []))),
        "new_now": sorted(set(curr.get("unresolved", [])) - set(prev.get("unresolved", []))),
    }
    messages = []
    if deltas["level_after"] is not None and deltas["level_before"] is not None:
        if deltas["level_after"] < deltas["level_before"]:
            messages.append({"text": "Support reduced: earlier issues stayed resolved.",
                             "evidence": "Scaffold level decreased."})
        elif deltas["level_after"] > deltas["level_before"]:
            messages.append({"text": "Support increased: new or returning evidence needs attention.",
                             "evidence": "Scaffold level increased."})
    for rid in deltas["resolved_now"]:
        messages.append({"text": f"{rid} is no longer active.", "evidence": "Rule left the unresolved set."})
    for rid in deltas["new_now"]:
        messages.append({"text": f"New attention point: {rid}.", "evidence": "Rule entered the unresolved set."})
    if not messages:
        messages.append({"text": "No measurable change since the last reflection.",
                         "evidence": "Same level and unresolved set."})
    return {"deltas": deltas, "messages": messages}
