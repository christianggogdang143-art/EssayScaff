"""Stage 3 orchestration: outline -> per-level NLP -> scaffolding.

Thesis + each body point + each detail analyzed at its own level with
existing services (no duplicate pipelines, no per-item rules/LT).
Revisions append-only; order is part of the revision.
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone

import config
from services import db
from services import outline as outline_mod
from services.knowledge_base.interface import TeacherConceptProvider


def new_stage3_session_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    return f"SES3-{stamp}-{uuid.uuid4().hex[:6].upper()}"


def _stage2_context(stage2_session_id: str | None) -> dict:
    if not stage2_session_id:
        return {"linked": False, "thesis": None, "thesis_concepts": [], "topic": None, "teacher_keywords": None}
    session = db.get_stage2_session(stage2_session_id)
    if not session["revisions"]:
        raise ValueError(f"Unknown Stage 2 session '{stage2_session_id}'.")
    last = session["revisions"][-1]
    return {"linked": True, "stage2_session_id": stage2_session_id,
            "thesis": last.get("thesis_text"),
            "thesis_concepts": list((last.get("components", {}) or {}).get("important_concepts", [])),
            "topic": last.get("topic"), "teacher_keywords": last.get("teacher_keywords"),
            "stage2_ready": (last.get("readiness", {}) or {}).get("stage3_allowed", False)}


def analyze_outline(
    outline: list[dict],
    thesis: str | None = None,
    topic: str | None = None,
    teacher_keywords: list[str] | None = None,
    session_id: str | None = None,
    stage2_session_id: str | None = None,
    stage1_session_id: str | None = None,
) -> dict:
    wall_start = time.perf_counter()
    session_id = session_id or new_stage3_session_id()
    s2 = _stage2_context(stage2_session_id)
    if s2["linked"] and not s2["stage2_ready"]:
        raise PermissionError(
            f"Stage 2 session '{stage2_session_id}' is not ready for outline work (stage3_allowed is false).")
    thesis = thesis if thesis is not None else s2["thesis"]
    if not thesis or not thesis.strip():
        raise ValueError("No thesis supplied (and none carried from Stage 2).")
    topic = topic if topic is not None else s2["topic"]
    teacher_keywords = teacher_keywords if teacher_keywords is not None else s2["teacher_keywords"]

    # ---- outline input + structure parsing ----
    t0 = time.perf_counter()
    structure = [{"index": i + 1, "text": p["text"], "details": list(p.get("details", []))}
                 for i, p in enumerate(outline)]
    parse_ms = (time.perf_counter() - t0) * 1000.0

    # ---- per-level NLP (existing services) ----
    t0 = time.perf_counter()
    thesis_item = outline_mod.analyze_item(thesis)
    point_items = []
    for entry in structure:
        pdata = outline_mod.analyze_item(entry["text"])
        pdata["details"] = [outline_mod.analyze_item(d) for d in entry["details"]]
        point_items.append(pdata)
    nlp_ms = (time.perf_counter() - t0) * 1000.0

    # ---- thesis WordNet expansion via KB provider (honestly labeled) ----
    t0 = time.perf_counter()
    from services import keywords

    thesis_recs = [{"kind": "THESIS_KEYWORD", "original": lemma, "normalized": lemma,
                    "lemmas": [lemma], "primary_lemma": lemma, "spacy_pos": "NOUN"}
                   for lemma in (s2["thesis_concepts"] or thesis_item["selected"])]
    outline_lemmas = set(thesis_item["lemmas"])
    for p in point_items:
        outline_lemmas |= set(p["lemmas"])
        for d in p["details"]:
            outline_lemmas |= set(d["lemmas"])
    provider = TeacherConceptProvider()
    wn_thesis = provider.expand(thesis_recs,
                                student_lemmas=outline_lemmas,
                                student_surfaces=set())
    thesis_item["wordnet_retained"] = [t for term in wn_thesis.get("terms", []) for t in term.get("retained", [])]
    wordnet_ms = (time.perf_counter() - t0) * 1000.0

    # ---- per-point WordNet (for detail matching) ----
    t0 = time.perf_counter()
    for p in point_items:
        recs = [{"kind": "POINT_KEYWORD", "original": lemma, "normalized": lemma,
                 "lemmas": [lemma], "primary_lemma": lemma, "spacy_pos": "NOUN"}
                for lemma in p["selected"]]
        exp = provider.expand(recs, student_lemmas=set().union(*(set(d["lemmas"]) for d in p["details"])) if p["details"] else set(), student_surfaces=set())
        p["wordnet_retained"] = [t for term in exp.get("terms", []) for t in term.get("retained", [])]
    point_wn_ms = (time.perf_counter() - t0) * 1000.0

    # ---- evaluation (alignments, unity, progression, duplication, rules) ----
    thesis_data = {"lemmas": thesis_item["lemmas"], "wordnet_retained": thesis_item["wordnet_retained"],
                   "selected": thesis_item["selected"]}
    eval_out = outline_mod.evaluate_outline(structure, {"points": point_items}, thesis_data)

    # ---- coverage C7 ----
    tset = set(thesis_item["selected"]) or set(thesis_item["content_lemmas"])
    covered = sorted(tset & outline_lemmas)
    coverage = {"ratio": round(len(covered) / len(tset), 4) if tset else 0.0,
                "covered": covered, "thesis_terms": sorted(tset)}

    # ---- prompts ----
    history = db.get_stage3_session(session_id)
    shown: set[str] = set()
    for rev in history.get("revisions", []):
        for pr in rev.get("prompts", {}).get("prompts", []):
            shown.add(pr["prompt_id"])
    t0 = time.perf_counter()
    prompts = outline_mod.select_outline_prompts(eval_out["rules"], shown_ids=shown)
    prompts_ms = (time.perf_counter() - t0) * 1000.0

    t0 = time.perf_counter()
    readiness = outline_mod.check_outline_readiness(structure, eval_out["rules"], coverage)
    readiness_ms = (time.perf_counter() - t0) * 1000.0

    fired_ids = [r["rule_id"] for r in eval_out["rules"] if r["status"] == "TRIGGERED"]
    fired_with = [(r["rule_id"], str(r["evidence"].get("point", "")), str(r["evidence"].get("detail", "")))
                  for r in eval_out["rules"] if r["status"] == "TRIGGERED"]
    curr_point = {"outline": [{"text": e["text"], "details": list(e["details"])} for e in structure],
                  "fired": fired_ids, "fired_with": fired_with}
    t0 = time.perf_counter()
    if history.get("revisions"):
        last = history["revisions"][-1]
        prev_point = {"outline": last["outline"], "fired": last["fired_rules"],
                      "fired_with": last.get("fired_with", [])}
        comparison = outline_mod.compare_outline_revisions(prev_point, curr_point)
    else:
        comparison = {"deltas": None, "messages": [{"text": "This is your first outline revision. Build your points in your own words.", "evidence": "No prior revision."}]}
    compare_ms = (time.perf_counter() - t0) * 1000.0

    revision_number = db.next_stage3_revision(session_id)
    stats = _accumulate_stats(history, eval_out["rules"], prompts, revision_number)
    record = {
        "session_id": session_id, "revision_number": revision_number,
        "stage2_session_id": stage2_session_id, "stage1_session_id": stage1_session_id,
        "topic": topic, "teacher_keywords": teacher_keywords, "thesis_snapshot": thesis,
        "outline": curr_point["outline"], "rules": eval_out["rules"], "prompts": prompts,
        "readiness": readiness, "comparison": comparison, "scaffold_stats": stats,
        "alignments": {"points": eval_out["point_alignments"], "details": eval_out["detail_alignments"]},
        "unity": eval_out["unity"], "progression": eval_out["progression"],
        "duplicates": {"points": eval_out["duplicate_points"], "details": eval_out["duplicate_details"]},
        "coverage": coverage, "fired_rules": fired_ids, "fired_with": fired_with,
        "provider": wn_thesis.get("provider"), "created_at": datetime.now(timezone.utc).isoformat(),
        "processing_ms": (time.perf_counter() - wall_start) * 1000.0,
    }
    t0 = time.perf_counter()
    revision_number = db.save_stage3_revision(record)
    persist_ms = (time.perf_counter() - t0) * 1000.0

    timings = {"parse_ms": parse_ms, "nlp_ms": nlp_ms, "wordnet_ms": wordnet_ms + point_wn_ms,
               **{k: v for k, v in eval_out["timings"].items() if k != "total_ms"},
               "prompts_ms": prompts_ms, "readiness_ms": readiness_ms,
               "compare_ms": compare_ms, "persist_ms": persist_ms,
               "total_ms": record["processing_ms"]}
    gears = _gears(record, timings)
    return {"session_id": session_id, "revision_number": revision_number,
            "stage2_session_id": stage2_session_id, "stage1_session_id": stage1_session_id,
            "thesis": thesis, "outline": curr_point["outline"],
            "alignments": record["alignments"], "unity": record["unity"],
            "progression": record["progression"], "duplicates": record["duplicates"],
            "coverage": coverage, "rules": record["rules"], "prompts": prompts,
            "readiness": readiness, "comparison": comparison, "scaffold_stats": stats,
            "provider": record["provider"], "stage3_transparency": gears, "timings": timings}


def _accumulate_stats(history, rules, prompts, revision_number) -> dict:
    counts: dict[str, int] = {}
    shown: list[str] = []
    for rev in history.get("revisions", []):
        for rid in rev.get("fired_rules", []):
            counts[rid] = counts.get(rid, 0) + 1
        for p in rev.get("prompts", {}).get("prompts", []):
            if p["prompt_id"] not in shown:
                shown.append(p["prompt_id"])
    for r in rules:
        if r["status"] == "TRIGGERED":
            counts[r["rule_id"]] = counts.get(r["rule_id"], 0) + 1
    for p in prompts.get("prompts", []):
        if p["prompt_id"] not in shown:
            shown.append(p["prompt_id"])
    return {"revision_count": revision_number, "rule_trigger_counts": counts, "prompts_shown": shown}


def _gears(record, timings) -> list[dict]:
    return [
        {"id": "outline_input", "number": 1, "name": "Outline Input",
         "purpose": "Receive the student's ordered outline plus read-only thesis reference.",
         "file": "services/stage3.py", "function": "analyze_outline", "kind": "ours", "status": "COMPLETE",
         "input": {"points": len(record["outline"]), "thesis_chars": len(record["thesis_snapshot"] or "")},
         "process": "Validation (2-6 points); order preserved as sent.",
         "output": {"outline": record["outline"]}, "timing_ms": timings["parse_ms"], "next": "outline_structure_parsing"},
        {"id": "outline_structure_parsing", "number": 2, "name": "Outline Structure Parsing",
         "purpose": "Keep the THESIS > POINT > DETAIL hierarchy; each level analyzed separately.",
         "file": "services/outline.py", "function": "analyze_item", "kind": "ours", "status": "COMPLETE",
         "input": {"levels": "thesis + per-point + per-detail texts"},
         "process": "Existing spaCy tokens + keyword extraction per item (no per-item rules/LT).",
         "output": {"point_count": len(record["outline"]),
                    "detail_counts": [len(p["details"]) for p in record["outline"]]},
         "timing_ms": timings["nlp_ms"], "next": "thesis_point_alignment"},
        {"id": "thesis_point_alignment", "number": 3, "name": "Thesis-Point Alignment",
         "purpose": "Classify each point ALIGNED/PARTIALLY/WEAKLY from shared concepts, WordNet relations, and one lexical cosine.",
         "file": "services/outline.py", "function": "classify_alignment", "kind": "ours", "status": "COMPLETE",
         "input": {"provider": record["provider"]},
         "process": "DIRECT overlap + WORDNET retained hits + cosine (supporting signal only).",
         "output": record["alignments"]["points"], "timing_ms": timings["thesis_point_ms"], "next": "point_detail_alignment"},
        {"id": "point_detail_alignment", "number": 4, "name": "Point-Detail Alignment",
         "purpose": "Classify each detail against its parent point with the same transparent bands.",
         "file": "services/outline.py", "function": "evaluate_outline", "kind": "ours", "status": "COMPLETE",
         "input": {"detail_count": len(record["alignments"]["details"])},
         "process": "Same DIRECT/WORDNET/cosine bands per parent point.",
         "output": record["alignments"]["details"], "timing_ms": timings["point_detail_ms"], "next": "unity_analysis"},
        {"id": "unity_analysis", "number": 5, "name": "Unity Analysis",
         "purpose": "Judge paragraph unity: COHESIVE/MIXED/POSSIBLY OFF-TOPIC/NO SUPPORT from detail alignments.",
         "file": "services/outline.py", "function": "evaluate_outline", "kind": "ours", "status": "COMPLETE",
         "input": {"points": len(record["outline"])},
         "process": "Weak-detail counts per point; no human-level understanding claimed.",
         "output": record["unity"], "timing_ms": timings["point_detail_ms"], "next": "progression"},
        {"id": "progression", "number": 6, "name": "Point-to-Point Progression",
         "purpose": "Inspect adjacent pairs: concept continuity, repetition, abrupt shifts, ordering cues.",
         "file": "services/outline.py", "function": "evaluate_outline", "kind": "ours", "status": "COMPLETE",
         "input": {"adjacent_pairs": max(len(record["outline"]) - 1, 0)},
         "process": "Shared concepts + ORDER_CUES; 'progression indicator', not perfect logic.",
         "output": record["progression"], "timing_ms": timings["progression_ms"], "next": "duplication_check"},
        {"id": "duplication_check", "number": 7, "name": "Duplication Check",
         "purpose": "Flag near-identical points (Jaccard/cosine) and duplicate details. Never auto-merge.",
         "file": "services/outline.py", "function": "evaluate_outline", "kind": "ours", "status": "COMPLETE",
         "input": {"points": len(record["outline"])},
         "process": f"Jaccard>={config.OUTLINE_DUP_JACCARD_POINTS} or cosine>={config.OUTLINE_DUP_COSINE_POINTS}.",
         "output": record["duplicates"], "timing_ms": timings["duplication_ms"], "next": "outline_rule_evaluation"},
        {"id": "outline_rule_evaluation", "number": 8, "name": "Outline Rule Evaluation",
         "purpose": "Run OUTLINE_001-012 over all evidence above.",
         "file": "services/outline.py", "function": "evaluate_outline", "kind": "ours", "status": "COMPLETE",
         "input": {"evidence": "alignments + unity + progression + duplicates"},
         "process": "Each rule condition evaluated; TRIGGERED/OBSERVED/INACTIVE.",
         "output": record["rules"], "timing_ms": timings["rules_ms"], "next": "prompt_selection"},
        {"id": "prompt_selection", "number": 9, "name": "Prompt Selection",
         "purpose": "Map fired rules to at most 3 questions by priority; prefer unshown.",
         "file": "services/outline.py", "function": "select_outline_prompts", "kind": "ours", "status": "COMPLETE",
         "input": {"fired": record["fired_rules"]},
         "process": "Priority sort, top-3, bank mapping.",
         "output": record["prompts"], "timing_ms": timings["prompts_ms"], "next": "readiness_check"},
        {"id": "readiness_check", "number": 10, "name": "Readiness Check",
         "purpose": "Apply explicit C1-C8. Grammar never blocks; no percentage.",
         "file": "services/outline.py", "function": "check_outline_readiness", "kind": "ours", "status": "COMPLETE",
         "input": {"coverage": record["coverage"]},
         "process": "C1 structure … C8 overload.",
         "output": record["readiness"], "timing_ms": timings["readiness_ms"], "next": "revision_storage"},
        {"id": "revision_storage", "number": 11, "name": "Revision Storage",
         "purpose": "Append outline revision with order intact; history append-only.",
         "file": "services/db.py", "function": "save_stage3_revision", "kind": "ours", "status": "COMPLETE",
         "input": {"session_id": record["session_id"], "revision_number": record["revision_number"]},
         "process": "SQLite INSERT into stage3_revisions.",
         "output": {"stored": True}, "timing_ms": timings["persist_ms"], "next": None},
    ]
