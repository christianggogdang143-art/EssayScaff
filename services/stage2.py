"""Stage 2 orchestration: thesis -> existing NLP -> thesis scaffolding.

One analysis_service.analyze() call per revision plus one lightweight
spaCy parse whose ONLY purpose is reusing THESIS_001/THESIS_002 unchanged
(measured and disclosed as thesis_doc_parse_ms). Revisions append-only.
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone

import config
from rules import thesis_rules
from rules.meta_rules import detect_meta_statements
from services import analysis_service, db
from services import thesis as thesis_mod
from services.nlp_service import get_nlp


def new_stage2_session_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    return f"SES2-{stamp}-{uuid.uuid4().hex[:6].upper()}"


LINK_POLICY = (
    "Linked Stage 1 sessions must be eligible (readiness.stage2_allowed "
    "is true); otherwise the call is refused. Unlinked calls (no "
    "stage1_session_id) remain allowed as the explicit direct/research "
    "path: they analyze the thesis standalone without Stage 1 history."
)


def _stage1_context(stage1_session_id: str | None) -> dict:
    """Carry forward topic, keywords, final idea, and concepts (read-only).

    Enforces the linked-workflow gate: a linked Stage 1 session whose
    latest revision is not eligible for thesis work refuses the call so
    students cannot bypass readiness. Re-analyzing the idea in Stage 1
    mints a fresh revision with current readiness (recovery path).
    """
    if not stage1_session_id:
        return {"linked": False, "stage1_keywords": None, "final_idea": None,
                "topic": None, "teacher_keywords": None}
    session = db.get_stage1_session(stage1_session_id)
    if not session["revisions"]:
        raise ValueError(f"Unknown Stage 1 session '{stage1_session_id}'.")
    last = session["revisions"][-1]
    if not (last.get("readiness", {}) or {}).get("stage2_allowed", False):
        raise PermissionError(
            f"Stage 1 session '{stage1_session_id}' is not ready for thesis "
            "work (stage2_allowed is false). Develop the idea further in "
            "Stage 1, then continue.")
    return {"linked": True, "stage1_session_id": stage1_session_id,
            "stage1_keywords": list(last.get("concepts", {}).get("selected", [])),
            "final_idea": last.get("idea_text"),
            "topic": last.get("topic"),
            "teacher_keywords": last.get("teacher_keywords"),
            "stage1_readiness": (last.get("readiness", {}) or {}).get("decision")}


def analyze_thesis(
    text: str,
    topic: str | None = None,
    teacher_keywords: list[str] | None = None,
    stage: str | None = None,
    session_id: str | None = None,
    stage1_session_id: str | None = None,
    validation_ms: float = 0.0,
) -> dict:
    wall_start = time.perf_counter()
    session_id = session_id or new_stage2_session_id()
    s1 = _stage1_context(stage1_session_id)
    # Carry forward Stage 1 reference material (never auto-transformed).
    topic = topic if topic is not None else s1["topic"]
    teacher_keywords = teacher_keywords if teacher_keywords is not None else s1["teacher_keywords"]

    analysis = analysis_service.analyze(
        text, stage=stage, validation_ms=validation_ms, topic=topic, teacher_keywords=teacher_keywords
    )
    sentences = analysis["technical"]["sentences"]

    t0 = time.perf_counter()
    doc = get_nlp()(text.replace("\r\n", "\n").replace("\r", "\n"))
    doc_parse_ms = (time.perf_counter() - t0) * 1000.0

    # Reuse THESIS_001/THESIS_002 with identical meaning (same call order).
    meta_results, meta_by = detect_meta_statements(sentences)
    thesis01 = thesis_rules.detect_thesis_candidates(doc, sentences, meta_by)

    components = thesis_mod.extract_components(analysis)
    phase2 = analysis["technical"].get("phase2", {}) or {}
    ta = phase2.get("topic_analysis", {}) or {}
    cls = ta.get("classification", {}) or {}
    wn = phase2.get("wordnet", {}) or {}
    support_matches = wn.get("direct_count", 0) + wn.get("lemma_count", 0) + wn.get("wordnet_count", 0)

    t0 = time.perf_counter()
    new_rules = thesis_mod.evaluate_new_rules(
        components, cls.get("classification"), bool(phase2.get("ran")), support_matches)
    rules_ms = (time.perf_counter() - t0) * 1000.0
    all_rules = thesis01 + meta_results + new_rules

    selected = list((phase2.get("keywords", {}) or {}).get("selected", []) or [])
    alignment = thesis_mod.check_alignment(selected, s1["stage1_keywords"])

    history = db.get_stage2_session(session_id)
    shown: set[str] = set()
    for rev in history.get("revisions", []):
        for p in rev.get("prompts", {}).get("prompts", []):
            shown.add(p["prompt_id"])
    t0 = time.perf_counter()
    prompts = thesis_mod.select_thesis_prompts(all_rules, alignment, shown_ids=shown)
    prompts_ms = (time.perf_counter() - t0) * 1000.0

    t0 = time.perf_counter()
    readiness = thesis_mod.check_thesis_readiness(
        components, all_rules, alignment, bool(phase2.get("ran")), cls.get("classification"), support_matches)
    readiness_ms = (time.perf_counter() - t0) * 1000.0

    summary = analysis.get("summary", {}) or {}
    # THESIS_002 natively reports "ISSUE": a real finding, include it.
    fired = [r["rule_id"] for r in all_rules if r["status"] in ("TRIGGERED", "ISSUE")]
    curr_point = {"word_count": summary.get("token_count", 0),
                  "concept_count": len(selected), "keywords": selected,
                  "subject": components["detected_subject"],
                  "alignment": alignment.get("classification"), "fired_rules": fired}
    t0 = time.perf_counter()
    if history.get("revisions"):
        last = history["revisions"][-1]
        prev_point = {"word_count": last.get("word_count", 0),
                      "concept_count": len(last.get("components", {}).get("important_concepts", [])),
                      "keywords": last.get("components", {}).get("important_concepts", []),
                      "subject": (last.get("components", {}) or {}).get("detected_subject"),
                      "alignment": (last.get("alignment", {}) or {}).get("classification"),
                      "fired_rules": last.get("fired_rules", [])}
        comparison = thesis_mod.compare_thesis_revisions(prev_point, curr_point)
    else:
        comparison = {"deltas": None, "messages": [{"text": "This is your first thesis attempt. State one clear claim in your own words.", "evidence": "No prior revision."}]}
    compare_ms = (time.perf_counter() - t0) * 1000.0

    revision_number = db.next_stage2_revision(session_id)
    stats = _accumulate_stats(history, all_rules, prompts, revision_number)
    record = {
        "session_id": session_id, "revision_number": revision_number,
        "stage1_session_id": stage1_session_id, "topic": topic,
        "teacher_keywords": teacher_keywords, "thesis_text": text,
        "analysis_id": analysis["analysis_id"], "components": components,
        "alignment": alignment, "prompts": prompts, "readiness": readiness,
        "comparison": comparison, "scaffold_stats": stats,
        "word_count": curr_point["word_count"], "fired_rules": fired,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "processing_ms": (time.perf_counter() - wall_start) * 1000.0,
    }
    t0 = time.perf_counter()
    revision_number = db.save_stage2_revision(record)
    persist_ms = (time.perf_counter() - t0) * 1000.0

    gears = _gears(analysis, components, all_rules, new_rules, alignment, prompts, readiness, record,
                   {"doc_parse_ms": doc_parse_ms, "rules_ms": rules_ms, "prompts_ms": prompts_ms,
                    "readiness_ms": readiness_ms, "compare_ms": compare_ms, "persist_ms": persist_ms})
    return {
        "session_id": session_id, "revision_number": revision_number,
        "stage1_session_id": stage1_session_id,
        "stage1_reference": {"final_idea": s1["final_idea"], "linked": s1["linked"]},
        "analysis": analysis, "components": components,
        "thesis_rules": all_rules, "alignment": alignment,
        "prompts": prompts, "readiness": readiness, "comparison": comparison,
        "scaffold_stats": stats, "stage2_transparency": gears,
        "timings": {"doc_parse_ms": doc_parse_ms, "rules_ms": rules_ms, "prompts_ms": prompts_ms,
                    "readiness_ms": readiness_ms, "compare_ms": compare_ms,
                    "persist_ms": persist_ms, "total_ms": record["processing_ms"]},
    }


def _accumulate_stats(history, all_rules, prompts, revision_number) -> dict:
    counts: dict[str, int] = {}
    shown: list[str] = []
    for rev in history.get("revisions", []):
        for rid in rev.get("fired_rules", []):
            counts[rid] = counts.get(rid, 0) + 1
        for p in rev.get("prompts", {}).get("prompts", []):
            if p["prompt_id"] not in shown:
                shown.append(p["prompt_id"])
    for r in all_rules:
        if r["status"] in ("TRIGGERED", "ISSUE"):
            counts[r["rule_id"]] = counts.get(r["rule_id"], 0) + 1
    for p in prompts.get("prompts", []):
        if p["prompt_id"] not in shown:
            shown.append(p["prompt_id"])
    return {"revision_count": revision_number, "rule_trigger_counts": counts, "prompts_shown": shown}


def _gears(analysis, components, all_rules, new_rules, alignment, prompts, readiness, record, timings) -> list[dict]:
    return [
        {"id": "thesis_input", "number": 1, "name": "Thesis Input",
         "purpose": "Receive the student's thesis plus carried-forward Stage 1 reference (read-only).",
         "file": "services/stage2.py", "function": "analyze_thesis", "kind": "ours", "status": "COMPLETE",
         "input": {"thesis_chars": len(record["thesis_text"]), "stage1_linked": record["stage1_session_id"]},
         "process": "Validation; Stage 1 topic/keywords/idea carried forward, never transformed.",
          "output": {"analysis_id": analysis.get("analysis_id")}, "timing_ms": None,
          "timing_status": "NOT_MEASURED_SEPARATELY", "next": "thesis_component_extraction"},
        {"id": "thesis_component_extraction", "number": 2, "name": "Thesis Component Extraction",
         "purpose": "Identify subject, predicate, concepts, and stance/vagueness markers with cautious labels.",
         "file": "services/thesis.py", "function": "extract_components", "kind": "ours", "status": "COMPLETE",
         "input": {"sentences": len(analysis["technical"]["sentences"]), "tokens": len(analysis["technical"]["tokens"])},
         "process": "nsubj/ROOT/finite-verb lookup over real dependency data (one extra parse reuses THESIS_001/002).",
         "output": components, "timing_ms": timings["doc_parse_ms"], "next": "thesis_rule_evaluation"},
        {"id": "thesis_rule_evaluation", "number": 3, "name": "Thesis Rule Evaluation",
         "purpose": "Run reused THESIS_001/002 plus new THESIS_003-010 heuristics over component evidence.",
         "file": "services/thesis.py", "function": "evaluate_new_rules", "kind": "ours", "status": "COMPLETE",
         "input": {"components_keys": sorted(components.keys())},
         "process": "Each rule condition evaluated; TRIGGERED/OBSERVED/INACTIVE/SKIPPED.",
         "output": all_rules, "timing_ms": timings["rules_ms"], "next": "stage1_alignment_check"},
        {"id": "stage1_alignment_check", "number": 4, "name": "Stage 1 Alignment Check",
         "purpose": "Compare thesis keywords with Stage 1 final-idea keywords (overlap ratio). Advisory only.",
         "file": "services/thesis.py", "function": "check_alignment", "kind": "ours", "status": "COMPLETE",
         "input": {"stage1_linked": record["stage1_session_id"]},
         "process": f"overlap = shared/thesis_terms; bands {config.STAGE2_ALIGN_LOW}/{config.STAGE2_ALIGN_HIGH}.",
          "output": alignment, "timing_ms": None,
          "timing_status": "NOT_MEASURED_SEPARATELY", "next": "thesis_prompt_selection"},
        {"id": "thesis_prompt_selection", "number": 5, "name": "Thesis Prompt Selection",
         "purpose": "Map fired rules to at most 3 reflective questions by priority; prefer unshown prompts.",
         "file": "services/thesis.py", "function": "select_thesis_prompts", "kind": "ours", "status": "COMPLETE",
         "input": {"fired": [r["rule_id"] for r in all_rules if r["status"] in ("TRIGGERED", "OBSERVED")]},
         "process": "Priority sort, top-3, prompt-bank mapping.",
         "output": prompts, "timing_ms": timings["prompts_ms"], "next": "thesis_readiness"},
        {"id": "thesis_readiness", "number": 6, "name": "Thesis Readiness",
         "purpose": "Apply explicit C1-C7 conditions. Grammar never blocks; only structure does.",
         "file": "services/thesis.py", "function": "check_thesis_readiness", "kind": "ours", "status": "COMPLETE",
         "input": {"fired": [r["rule_id"] for r in all_rules if r["status"] == "TRIGGERED"]},
         "process": "C1 candidate … C7 direction.",
         "output": readiness, "timing_ms": timings["readiness_ms"], "next": "revision_storage"},
        {"id": "revision_storage", "number": 7, "name": "Revision Storage",
         "purpose": "Append thesis revision; history stays append-only.",
         "file": "services/db.py", "function": "save_stage2_revision", "kind": "ours", "status": "COMPLETE",
         "input": {"session_id": record["session_id"], "revision_number": record["revision_number"]},
         "process": "SQLite INSERT into stage2_revisions.",
         "output": {"stored": True}, "timing_ms": timings["persist_ms"], "next": None},
    ]
