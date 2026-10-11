"""Stage 1 orchestration: idea -> existing NLP -> scaffolding -> revision.

One analysis_service.analyze() call per revision (no duplicated NLP).
Every revision is INSERTed, never overwritten. Prompt history feeds back
into selection so students see fresh questions (adaptive foundation).
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone

from services import analysis_service, db
from services import prewriting


def new_session_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    return f"SES-{stamp}-{uuid.uuid4().hex[:6].upper()}"


def _concepts_snapshot(analysis: dict) -> dict:
    tech = (analysis.get("technical", {}) or {})
    phase2 = tech.get("phase2", {}) or {}
    kw = phase2.get("keywords", {}) or {}
    wn = phase2.get("wordnet", {}) or {}
    return {
        "selected": list(kw.get("selected", []) or []),
        "term_count": len(kw.get("terms", []) or []),
        "direct_count": wn.get("direct_count", 0),
        "lemma_count": wn.get("lemma_count", 0),
        "wordnet_count": wn.get("wordnet_count", 0),
    }


def analyze_idea(
    text: str,
    topic: str | None = None,
    teacher_keywords: list[str] | None = None,
    stage: str | None = None,
    session_id: str | None = None,
    validation_ms: float = 0.0,
) -> dict:
    """Run one Stage 1 revision: analyze, scaffold, compare, persist."""
    wall_start = time.perf_counter()
    session_id = session_id or new_session_id()

    analysis = analysis_service.analyze(
        text, stage=stage, validation_ms=validation_ms, topic=topic, teacher_keywords=teacher_keywords
    )
    evidence = prewriting.build_evidence(analysis)

    t0 = time.perf_counter()
    rules = prewriting.evaluate_rules(evidence)
    rules_ms = (time.perf_counter() - t0) * 1000.0

    history = db.get_stage1_session(session_id)
    shown: set[str] = set()
    for rev in history.get("revisions", []):
        for p in rev.get("prompts", {}).get("prompts", []):
            shown.add(p["prompt_id"])

    t0 = time.perf_counter()
    prompt_context = prewriting.build_prompt_context(analysis, topic, teacher_keywords)
    context_ms = (time.perf_counter() - t0) * 1000.0

    t0 = time.perf_counter()
    prompts = prewriting.select_prompts(rules, shown_ids=shown, context=prompt_context)
    prompts_ms = (time.perf_counter() - t0) * 1000.0

    writing_notes = prewriting.detect_meta_note(analysis)

    t0 = time.perf_counter()
    readiness = prewriting.check_readiness(evidence, rules)
    readiness_ms = (time.perf_counter() - t0) * 1000.0

    guidance = prewriting.build_student_guidance(
        prompts.get("prompts", []), readiness, writing_notes, evidence, prompt_context)

    concepts = _concepts_snapshot(analysis)
    summary = analysis.get("summary", {}) or {}
    fired = [r["rule_id"] for r in rules if r["status"] == "TRIGGERED"]
    curr_point = {
        "word_count": summary.get("token_count", 0),
        "sentence_count": summary.get("sentence_count", 0),
        "concept_count": len(concepts["selected"]),
        "keywords": concepts["selected"],
        "similarity": summary.get("topic_similarity"),
        "classification": summary.get("topic_classification"),
        "fired_rules": fired,
    }

    t0 = time.perf_counter()
    prev_point = None
    if history.get("revisions"):
        last = history["revisions"][-1]
        prev_point = {
            "word_count": last.get("word_count", 0),
            "sentence_count": last.get("sentence_count", 0),
            "concept_count": len(last.get("concepts", {}).get("selected", [])),
            "keywords": last.get("concepts", {}).get("selected", []),
            "similarity": last.get("topic_similarity"),
            "classification": last.get("topic_classification"),
            "fired_rules": last.get("fired_rules", []),
        }
        comparison = prewriting.compare_revisions(prev_point, curr_point)
    else:
        comparison = {"deltas": None, "messages": [{"text": "This is your first revision. Write what you think, then revise.", "evidence": "No prior revision."}]}
    compare_ms = (time.perf_counter() - t0) * 1000.0

    revision_number = db.next_stage1_revision(session_id)
    stats = _accumulate_stats(history, rules, prompts, revision_number)

    record = {
        "session_id": session_id,
        "revision_number": revision_number,
        "topic": topic,
        "teacher_keywords": teacher_keywords,
        "idea_text": text,
        "analysis_id": analysis["analysis_id"],
        "concepts": concepts,
        "prompts": prompts,
        "readiness": readiness,
        "writing_notes": writing_notes,
        "guidance": guidance,
        "comparison": comparison,
        "scaffold_stats": stats,
        "word_count": curr_point["word_count"],
        "sentence_count": curr_point["sentence_count"],
        "topic_similarity": curr_point["similarity"],
        "topic_classification": curr_point["classification"],
        "fired_rules": fired,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "processing_ms": (time.perf_counter() - wall_start) * 1000.0,
    }
    t0 = time.perf_counter()
    revision_number = db.save_stage1_revision(record)
    persist_ms = (time.perf_counter() - t0) * 1000.0

    gears = _transparency_gears(analysis, evidence, rules, prompts, readiness, record,
                                {"rules_ms": rules_ms, "prompts_ms": prompts_ms,
                                 "readiness_ms": readiness_ms, "compare_ms": compare_ms,
                                 "persist_ms": persist_ms},
                                prompt_context=prompt_context)
    return {
        "session_id": session_id,
        "revision_number": revision_number,
        "analysis": analysis,
        "evidence": evidence,
        "prompt_context": prompt_context,
        "rules": rules,
        "prompts": prompts,
        "readiness": readiness,
        "writing_notes": writing_notes,
        "guidance": guidance,
        "comparison": comparison,
        "scaffold_stats": stats,
        "stage1_transparency": gears,
        "timings": {
            "rules_ms": rules_ms,
            "context_ms": context_ms,
            "prompts_ms": prompts_ms,
            "readiness_ms": readiness_ms,
            "compare_ms": compare_ms,
            "persist_ms": persist_ms,
            "total_ms": record["processing_ms"],
        },
    }


def _accumulate_stats(history: dict, rules: list[dict], prompts: dict, revision_number: int) -> dict:
    counts: dict[str, int] = {}
    shown: list[str] = []
    resolved: list[dict] = []
    prev_fired: set[str] = set()
    for rev in history.get("revisions", []):
        for rid in rev.get("fired_rules", []):
            counts[rid] = counts.get(rid, 0) + 1
        for p in rev.get("prompts", {}).get("prompts", []):
            if p["prompt_id"] not in shown:
                shown.append(p["prompt_id"])
        prev_fired = set(rev.get("fired_rules", []))
    curr_fired = {r["rule_id"] for r in rules if r["status"] == "TRIGGERED"}
    for rid in curr_fired:
        counts[rid] = counts.get(rid, 0) + 1
    for p in prompts.get("prompts", []):
        if p["prompt_id"] not in shown:
            shown.append(p["prompt_id"])
    for rid in sorted(prev_fired - curr_fired):
        resolved.append({"rule": rid, "revision": revision_number})
    prior_resolved = []
    for rev in history.get("revisions", []):
        prior_resolved.extend(rev.get("scaffold_stats", {}).get("resolved", []))
    return {
        "revision_count": revision_number,
        "rule_trigger_counts": counts,
        "prompts_shown": shown,
        "resolved": prior_resolved + resolved,
    }


def _transparency_gears(analysis, evidence, rules, prompts, readiness, record, timings,
                        prompt_context: dict | None = None) -> list[dict]:
    summary = analysis.get("summary", {}) or {}
    return [
        {
            "id": "prewriting_analysis", "number": 1, "name": "Pre-writing Analysis",
            "purpose": "Reuse the existing NLP engine on the student's idea; collect observable evidence.",
            "file": "services/prewriting.py", "function": "build_evidence", "kind": "ours",
            "status": "COMPLETE",
            "input": {"analysis_id": analysis.get("analysis_id"), "sentences": summary.get("sentence_count"), "tokens": summary.get("token_count")},
            "process": "Tokens, keywords, and topic evidence summarized into observable characteristics.",
            "output": evidence, "timing_ms": None,
            "timing_status": "NOT_MEASURED_SEPARATELY",
            "next": "scaffold_rule_evaluation",
        },
        {
            "id": "scaffold_rule_evaluation", "number": 2, "name": "Scaffold Rule Evaluation",
            "purpose": "Evaluate the eight deterministic PREWRITE rules over real evidence.",
            "file": "services/prewriting.py", "function": "evaluate_rules", "kind": "ours",
            "status": "COMPLETE",
            "input": evidence,
            "process": "Each rule condition evaluated; statuses TRIGGERED/OBSERVED/INACTIVE/SKIPPED.",
            "output": rules, "timing_ms": timings["rules_ms"], "next": "prompt_selection",
        },
        {
            "id": "prompt_selection", "number": 3, "name": "Prompt Selection",
            "purpose": "Choose up to 3 reflective questions by explicit priority; prefer never-shown prompts.",
            "file": "services/prewriting.py", "function": "select_prompts", "kind": "ours",
            "status": "COMPLETE",
            "input": {"fired_rules": [r["rule_id"] for r in rules if r["status"] in ("TRIGGERED", "OBSERVED")],
                      "context_slots": {k: (v or {}).get("value") for k, v in (prompt_context or {}).items()
                                        if isinstance(v, dict)}},
            "process": f"Sort by priority, take {prompts.get('max_shown')}, fill contextual templates from provenanced slots, fall back to prompt bank.",
            "output": prompts, "timing_ms": timings["prompts_ms"], "next": "readiness_check",
        },
        {
            "id": "readiness_check", "number": 4, "name": "Readiness Check",
            "purpose": "Apply explicit C1-C4 conditions; decide DEVELOPING/NEARLY READY/READY. No percentage, grammar never blocks.",
            "file": "services/prewriting.py", "function": "check_readiness", "kind": "ours",
            "status": "COMPLETE",
            "input": {"evidence_keys": sorted(evidence.keys()), "fired": [r["rule_id"] for r in rules if r["status"] == "TRIGGERED"]},
            "process": "C1 development, C2 concepts, C3 focus, C4 no critical remaining.",
            "output": readiness, "timing_ms": timings["readiness_ms"], "next": "revision_storage",
        },
        {
            "id": "revision_storage", "number": 5, "name": "Revision Storage",
            "purpose": "Append this revision; never overwrite history. Record scaffold stats for future adaptive fading.",
            "file": "services/db.py", "function": "save_stage1_revision", "kind": "ours",
            "status": "COMPLETE",
            "input": {"session_id": record["session_id"], "revision_number": record["revision_number"]},
            "process": "SQLite INSERT into stage1_revisions.",
            "output": {"stored": True}, "timing_ms": timings["persist_ms"], "next": None,
        },
    ]
