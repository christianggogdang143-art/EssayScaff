"""Phase 5 Stage 3: outline analysis (no generative AI).

Hierarchy preserved: THESIS > BODY POINT > SUPPORTING DETAIL, each
analyzed at its own level with existing services (spaCy tokens, keyword
extraction, WordNet via the knowledge-base provider, TF-IDF/cosine as ONE
lexical signal — never "coherence"). Three concepts stay separate:
TOPIC RELEVANCE vs THESIS ALIGNMENT vs PARENT-CHILD ALIGNMENT.
"""

from __future__ import annotations

import time

import config
from services.thesis import FINITE_TAGS

ORDER_CUES = {
    "first", "second", "third", "then", "next", "finally", "also",
    "moreover", "however", "therefore", "furthermore", "in addition",
}

OUTLINE_PROMPT_BANK: dict[str, list[tuple[str, str]]] = {
    "ALIGNMENT": [
        ("ALIGN_O001", "How does this main point support your thesis?"),
        ("ALIGN_O002", "Which words in this point connect back to your thesis?"),
    ],
    "SUPPORT": [
        ("SUPPORT_001", "What detail or evidence will help explain this main point?"),
        ("SUPPORT_002", "What example would help explain this idea?"),
    ],
    "UNITY": [
        ("UNITY_001", "Do all of these details support the same central idea?"),
        ("UNITY_002", "Does any detail here belong to a different point?"),
    ],
    "FOCUS": [
        ("FOCUS_O001", "Is this main point trying to cover more than one idea?"),
        ("FOCUS_O002", "Which single idea should this paragraph mainly develop?"),
    ],
    "ORDER": [
        ("ORDER_001", "Why should this point come before the next one?"),
        ("ORDER_002", "Would a different order make your argument clearer?"),
    ],
    "RELATIONSHIP": [
        ("REL_O001", "How does this point connect with the point before it?"),
        ("REL_O002", "What idea carries over from the previous point?"),
    ],
    "DISTINCTION": [
        ("DIST_001", "How is this main point different from your other points?"),
        ("DIST_002", "Do these points need to remain separate, or are they developing the same idea?"),
    ],
    "DETAIL_ALIGNMENT": [
        ("DETAIL_001", "How does this supporting detail explain or support the main point above?"),
        ("DETAIL_002", "What information would show that this detail supports the point?"),
    ],
    "COMPLETENESS": [
        ("COMPLETE_001", "Is there an important part of your thesis that your outline has not addressed yet?"),
        ("COMPLETE_002", "Does every body point have the support it needs?"),
    ],
    "TRANSITION_PLANNING": [
        ("TRANS_001", "What relationship connects these two main points?"),
        ("TRANS_002", "What idea could link this point to the next one?"),
    ],
}

OUTLINE_RULE_DEFS: dict[str, tuple[str, str, str]] = {
    "OUTLINE_001": ("Insufficient body points (heuristic)", "COMPLETENESS", "CRITICAL"),
    "OUTLINE_002": ("Empty / underdeveloped main point (heuristic)", "SUPPORT", "HIGH"),
    "OUTLINE_003": ("Body point weakly aligned with thesis (heuristic)", "ALIGNMENT", "HIGH"),
    "OUTLINE_004": ("Supporting detail weakly aligned with parent point (heuristic)", "DETAIL_ALIGNMENT", "HIGH"),
    "OUTLINE_005": ("Body point has insufficient support (heuristic)", "SUPPORT", "HIGH"),
    "OUTLINE_006": ("Body points highly repetitive (heuristic)", "DISTINCTION", "HIGH"),
    "OUTLINE_007": ("Possible duplicate supporting details (heuristic)", "UNITY", "MEDIUM"),
    "OUTLINE_008": ("Body point contains multiple competing ideas (heuristic)", "FOCUS", "MEDIUM"),
    "OUTLINE_009": ("Logical ordering may be unclear (heuristic)", "ORDER", "MEDIUM"),
    "OUTLINE_010": ("All main points reasonably support thesis (heuristic)", "RELATIONSHIP", "LOW"),
    "OUTLINE_011": ("Supporting details reasonably support their points (heuristic)", "UNITY", "LOW"),
    "OUTLINE_012": ("Outline structure reasonably complete (heuristic)", "TRANSITION_PLANNING", "LOW"),
}


def _content_lemmas(item: dict) -> set[str]:
    return {(t.get("lemma") or t.get("text", "")).lower()
            for t in item.get("tokens", []) if t.get("is_alpha") and not t.get("is_stopword")}


def analyze_item(text: str) -> dict:
    """NLP for ONE outline item (tokens, keywords). No rules/LT per item."""
    from services import keywords
    from services.nlp_service import analyze_text

    out = analyze_text(text)
    kw = keywords.extract_candidates(out["tokens"], max(len(out["sentences"]), 1))
    lemmas = {(t.get("lemma") or t.get("text", "")).lower() for t in out["tokens"] if t.get("is_alpha")}
    finite = [t["text"] for t in out["tokens"] if t.get("tag") in FINITE_TAGS and t.get("is_alpha")]
    return {
        "text": text,
        "tokens": out["tokens"],
        "sentences": out["sentences"],
        "alpha_count": sum(1 for t in out["tokens"] if t.get("is_alpha")),
        "lemmas": sorted(lemmas),
        "content_lemmas": sorted(_content_lemmas({"tokens": out["tokens"]})),
        "selected": list(kw.get("selected", []) or []),
        "finite_verbs": finite,
        "keyword_terms": kw.get("terms", []),
    }


def cosine_of(doc_a: str, doc_b: str) -> float:
    """Lexical cosine between two texts (honest supporting signal only)."""
    from services.similarity import vectorize

    vec = vectorize(doc_a, doc_b)
    a, b = vec["topic_vector"], vec["student_vector"]
    import math

    dot = sum(x * y for x, y in zip(a, b))
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def classify_alignment(direct: int, wordnet_hits: int, cosine: float) -> tuple[str, str]:
    """Shared bands for thesis<->point and point<->detail (heuristic)."""
    if direct >= config.OUTLINE_ALIGN_DIRECT_STRONG or (
        direct >= 1 and (wordnet_hits >= 1 or cosine >= config.OUTLINE_ALIGN_COSINE_STRONG)
    ):
        return "ALIGNED", (
            f"{direct} shared concept(s)"
            + (f" + {wordnet_hits} WordNet relation(s)" if wordnet_hits else "")
            + f", lexical cosine {cosine:.3f}."
        )
    if direct >= 1 or wordnet_hits >= 1 or cosine >= config.OUTLINE_ALIGN_COSINE_WEAK:
        return "PARTIALLY ALIGNED", (
            f"Weak overlap: {direct} shared, {wordnet_hits} WordNet, cosine {cosine:.3f}."
        )
    return "WEAKLY ALIGNED", f"No shared concepts (cosine {cosine:.3f})."


def jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 1.0
    return len(a & b) / len(a | b) if (a | b) else 0.0


def _rule(rule_id: str, status: str, evidence: dict, reason: str) -> dict:
    name, category, priority = OUTLINE_RULE_DEFS[rule_id]
    return {"rule_id": rule_id, "rule_name": name, "status": status,
            "evidence": evidence, "reason": reason, "prompt_category": category,
            "priority": priority, "priority_rank": config.PREWRITE_PRIORITY[priority]}


def evaluate_outline(structure: list[dict], items: dict, thesis: dict) -> dict:
    """Full outline evaluation. Timed by caller (per-stage timings kept)."""
    t00 = time.perf_counter()
    points = items["points"]
    timings: dict[str, float] = {}

    # ---- thesis<->point alignment ----
    t0 = time.perf_counter()
    thesis_lemmas = set(thesis["lemmas"])
    thesis_retained = set(thesis.get("wordnet_retained", []))
    point_alignments = []
    for i, p in enumerate(points):
        pset, tset = set(p["content_lemmas"]), thesis_lemmas
        direct = sorted(pset & tset)
        wn_hits = sorted((set(p["lemmas"]) & thesis_retained) - set(direct))
        cos = cosine_of(" ".join(sorted(tset)) or " ", " ".join(sorted(pset)) or " ")
        label, reason = classify_alignment(len(direct), len(wn_hits), cos)
        point_alignments.append({"point": i + 1, "direct": direct, "wordnet_hits": wn_hits,
                                 "cosine": round(cos, 6), "classification": label, "reason": reason})
    timings["thesis_point_ms"] = (time.perf_counter() - t0) * 1000.0

    # ---- point<->detail alignment + unity ----
    t0 = time.perf_counter()
    detail_alignments: dict[str, dict] = {}
    unity = []
    for i, p in enumerate(points):
        pset = set(p["content_lemmas"])
        point_wn = set(p.get("wordnet_retained", []))
        det_results = []
        for j, d in enumerate(p["details"]):
            dset = set(d["content_lemmas"])
            direct = sorted(dset & pset)
            wn_hits = sorted((set(d["lemmas"]) & point_wn) - set(direct))
            cos = cosine_of(" ".join(sorted(pset)) or " ", " ".join(sorted(dset)) or " ")
            label, reason = classify_alignment(len(direct), len(wn_hits), cos)
            det_results.append({"point": i + 1, "detail": j + 1, "direct": direct,
                                "wordnet_hits": wn_hits, "cosine": round(cos, 6),
                                "classification": label, "reason": reason})
            detail_alignments[f"{i + 1}.{j + 1}"] = det_results[-1]
        weak = sum(1 for r in det_results if r["classification"] == "WEAKLY ALIGNED")
        if not det_results:
            status = "NO SUPPORT"
        elif weak == 0:
            status = "COHESIVE"
        elif weak == len(det_results):
            status = "POSSIBLY OFF-TOPIC"
        else:
            status = "MIXED"
        unity.append({"point": i + 1, "status": status,
                      "weak_details": [r["detail"] for r in det_results if r["classification"] == "WEAKLY ALIGNED"]})
    timings["point_detail_ms"] = (time.perf_counter() - t0) * 1000.0

    # ---- progression (adjacent pairs) ----
    t0 = time.perf_counter()
    progression = []
    for i in range(len(points) - 1):
        a, b = points[i], points[i + 1]
        shared = sorted(set(a["content_lemmas"]) & set(b["content_lemmas"]))
        cues = sorted((set(a["lemmas"]) | set(b["lemmas"])) & ORDER_CUES)
        abrupt = not shared and not cues
        progression.append({"pair": [i + 1, i + 2], "shared_concepts": shared,
                            "ordering_cues": cues, "abrupt_shift": abrupt})
    timings["progression_ms"] = (time.perf_counter() - t0) * 1000.0

    # ---- duplication ----
    t0 = time.perf_counter()
    dup_points = []
    for i in range(len(points)):
        for k in range(i + 1, len(points)):
            a, b = set(points[i]["content_lemmas"]), set(points[k]["content_lemmas"])
            jac = jaccard(a, b)
            cos = cosine_of(" ".join(sorted(a)) or " ", " ".join(sorted(b)) or " ")
            if jac >= config.OUTLINE_DUP_JACCARD_POINTS or cos >= config.OUTLINE_DUP_COSINE_POINTS:
                dup_points.append({"points": [i + 1, k + 1], "jaccard": round(jac, 4),
                                   "cosine": round(cos, 4), "shared": sorted(a & b)})
    seen_norm: dict[str, list] = {}
    dup_details = []
    for i, p in enumerate(points):
        for j, d in enumerate(p["details"]):
            norm = " ".join(d["text"].lower().split())
            if norm in seen_norm:
                dup_details.append({"details": seen_norm[norm] + [f"{i + 1}.{j + 1}"], "kind": "exact"})
            else:
                for other_norm, locs in list(seen_norm.items()):
                    other_set, this_set = set(other_norm.split()), set(norm.split())
                    if jaccard(other_set, this_set) >= config.OUTLINE_DUP_JACCARD_DETAILS and norm:
                        dup_details.append({"details": locs + [f"{i + 1}.{j + 1}"], "kind": "near-duplicate"})
                        break
                seen_norm.setdefault(norm, []).append(f"{i + 1}.{j + 1}")
    timings["duplication_ms"] = (time.perf_counter() - t0) * 1000.0

    # ---- rules ----
    t0 = time.perf_counter()
    rules = _build_rules(structure, points, point_alignments, detail_alignments, unity, progression, dup_points, dup_details)
    timings["rules_ms"] = (time.perf_counter() - t0) * 1000.0
    timings["total_ms"] = (time.perf_counter() - t00) * 1000.0
    return {"point_alignments": point_alignments, "detail_alignments": detail_alignments,
            "unity": unity, "progression": progression,
            "duplicate_points": dup_points, "duplicate_details": dup_details,
            "rules": rules, "timings": timings}


def _build_rules(structure, points, point_alignments, detail_alignments, unity, progression, dup_points, dup_details) -> list[dict]:
    rules = []
    n = len(points)
    rules.append(_rule("OUTLINE_001", "TRIGGERED" if n < config.OUTLINE_MIN_POINTS else "INACTIVE",
        {"point_count": n, "minimum": config.OUTLINE_MIN_POINTS},
        f"Only {n} body point(s); at least {config.OUTLINE_MIN_POINTS} suggested." if n < 2 else f"{n} body points present."))
    for i, p in enumerate(points):
        empty = not p["text"].strip()
        thin = p["alpha_count"] < config.OUTLINE_MIN_POINT_TOKENS
        if empty or thin:
            rules.append(_rule("OUTLINE_002", "TRIGGERED",
                {"point": i + 1, "alpha_tokens": p["alpha_count"], "empty": empty},
                f"Body Point {i + 1} is {'empty' if empty else 'underdeveloped (' + str(p['alpha_count']) + ' tokens)'}."))

    for pa in point_alignments:
        if pa["classification"] == "WEAKLY ALIGNED":
            rules.append(_rule("OUTLINE_003", "TRIGGERED",
                {"point": pa["point"], "direct": pa["direct"], "cosine": pa["cosine"]},
                f"Body Point {pa['point']} shares no concepts with the thesis (cosine {pa['cosine']})."))
    for key, da in detail_alignments.items():
        if da["classification"] == "WEAKLY ALIGNED":
            rules.append(_rule("OUTLINE_004", "TRIGGERED",
                {"detail": key, "direct": da["direct"], "cosine": da["cosine"]},
                f"Supporting Detail {key} shares no concepts with Body Point {da['point']}."))
    for i, p in enumerate(points):
        if not p["details"]:
            rules.append(_rule("OUTLINE_005", "TRIGGERED", {"point": i + 1},
                f"Body Point {i + 1} has no supporting details."))
    for dp in dup_points:
        rules.append(_rule("OUTLINE_006", "TRIGGERED",
            {"points": dp["points"], "jaccard": dp["jaccard"], "cosine": dp["cosine"], "shared": dp["shared"]},
            f"Body Points {dp['points'][0]} and {dp['points'][1]} cover very similar ideas (Jaccard {dp['jaccard']})."))
    for dd in dup_details:
        rules.append(_rule("OUTLINE_007", "TRIGGERED",
            {"details": dd["details"], "kind": dd["kind"]},
            f"Supporting details {', '.join(dd['details'])} look like {dd['kind']} duplicates."))
    for i, p in enumerate(points):
        if len(p["finite_verbs"]) >= config.OUTLINE_OVERLOAD_VERBS and len(p["selected"]) >= config.OUTLINE_OVERLOAD_KEYWORDS:
            rules.append(_rule("OUTLINE_008", "TRIGGERED",
                {"point": i + 1, "finite_verbs": p["finite_verbs"], "concept_count": len(p["selected"])},
                f"Body Point {i + 1} has {len(p['finite_verbs'])} predicates across {len(p['selected'])} concepts."))
    abrupt = [pr for pr in progression if pr["abrupt_shift"]]
    if abrupt:
        rules.append(_rule("OUTLINE_009", "TRIGGERED",
            {"abrupt_pairs": [pr["pair"] for pr in abrupt]},
            f"Point pairs {[pr['pair'] for pr in abrupt]} share no concepts and no ordering cue."))

    if n >= config.OUTLINE_MIN_POINTS and not any(r["rule_id"] == "OUTLINE_003" and r["status"] == "TRIGGERED" for r in rules):
        rules.append(_rule("OUTLINE_010", "OBSERVED", {"point_count": n}, "All main points relate to the thesis."))
    if points and not any(r["rule_id"] in ("OUTLINE_004", "OUTLINE_005") and r["status"] == "TRIGGERED" for r in rules):
        rules.append(_rule("OUTLINE_011", "OBSERVED", {"point_count": n}, "Details support their points."))
    # Structural completeness: blocked only by structural problems (missing/
    # empty/unsupported/duplicated/overloaded points). Alignment, wording,
    # and ordering refinements (003/004/007/009) do not make a structure
    # incomplete; they remain visible as guidance.
    structural_blockers = {"OUTLINE_001", "OUTLINE_002", "OUTLINE_005", "OUTLINE_006", "OUTLINE_008"}
    if not any(r["status"] == "TRIGGERED" and r["rule_id"] in structural_blockers for r in rules):
        rules.append(_rule("OUTLINE_012", "OBSERVED", {"point_count": n},
            "Outline structure looks complete: no missing/empty/unsupported/duplicated/overloaded points "
            "(refinement guidance such as ordering may still apply)."))
    return rules


def select_outline_prompts(rule_results: list[dict], shown_ids: set[str] | None = None, max_n: int | None = None) -> dict:
    shown_ids = set(shown_ids or [])
    max_n = config.STAGE3_MAX_PROMPTS if max_n is None else max_n
    candidates = [r for r in rule_results if r["status"] in ("TRIGGERED", "OBSERVED")]
    candidates.sort(key=lambda r: (r["priority_rank"], r["rule_id"], str(r["evidence"].get("point", "")), str(r["evidence"].get("detail", ""))))
    prompts = []
    chosen: set[str] = set()
    for r in candidates[:max_n]:
        options = OUTLINE_PROMPT_BANK[r["prompt_category"]]
        choice = next((p for p in options if p[0] not in shown_ids and p[0] not in chosen), options[0])
        chosen.add(choice[0])
        label = f"point {r['evidence'].get('point')}" if r["evidence"].get("point") else ""
        if r["evidence"].get("detail"):
            label = f"detail {r['evidence'].get('detail')}"
        prompts.append({"prompt_id": choice[0], "category": r["prompt_category"], "text": choice[1],
                        "rule_id": r["rule_id"], "target": label, "priority": r["priority"],
                        "why_shown": r["reason"]})
    from services.rhetorical_moves import ground_prompt

    return {"prompts": [ground_prompt(p) for p in prompts], "max_shown": max_n}


def check_outline_readiness(structure: list[dict], rules: list[dict], coverage: dict) -> dict:
    fired = {(r["rule_id"], str(r["evidence"].get("point", "")), str(r["evidence"].get("detail", ""))) for r in rules if r["status"] == "TRIGGERED"}
    fired_ids = {r["rule_id"] for r in rules if r["status"] == "TRIGGERED"}
    n = len(structure)
    c1 = config.OUTLINE_MIN_POINTS <= n <= config.OUTLINE_MAX_POINTS
    c2 = "OUTLINE_002" not in fired_ids
    c3 = "OUTLINE_003" not in fired_ids
    c4 = "OUTLINE_005" not in fired_ids
    c5 = "OUTLINE_004" not in fired_ids
    c6 = "OUTLINE_006" not in fired_ids
    c7 = coverage["ratio"] >= config.OUTLINE_COVERAGE_MIN
    c8 = "OUTLINE_008" not in fired_ids
    conditions = [
        {"id": "C1", "name": "Minimum outline structure exists", "result": "PASS" if c1 else "FAIL",
         "detail": f"{n} body points (suggested {config.OUTLINE_MIN_POINTS}-{config.OUTLINE_MAX_POINTS})."},
        {"id": "C2", "name": "Each main point has meaningful text", "result": "PASS" if c2 else "FAIL",
         "detail": "An empty/underdeveloped point remains." if not c2 else "All points have text."},
        {"id": "C3", "name": "Main points sufficiently align with thesis", "result": "PASS" if c3 else "FAIL",
         "detail": "A point is weakly aligned." if not c3 else "Points relate to the thesis."},
        {"id": "C4", "name": "Each main point has at least one support item", "result": "PASS" if c4 else "FAIL",
         "detail": "OUTLINE_005 active." if not c4 else "Every point has support."},
        {"id": "C5", "name": "No critical off-topic detail remains", "result": "PASS" if c5 else "FAIL",
         "detail": "OUTLINE_004 active." if not c5 else "Details stay on their points."},
        {"id": "C6", "name": "No severe duplication among main points", "result": "PASS" if c6 else "FAIL",
         "detail": "OUTLINE_006 active." if not c6 else "Points are distinct."},
        {"id": "C7", "name": "Outline covers the thesis direction sufficiently", "result": "PASS" if c7 else "FAIL",
         "detail": f"Thesis-concept coverage {coverage['ratio']:.2f} (needs {config.OUTLINE_COVERAGE_MIN})."},
        {"id": "C8", "name": "No critical overloaded point remains", "result": "PASS" if c8 else "FAIL",
         "detail": "OUTLINE_008 active." if not c8 else "Points are singly focused."},
    ]
    if all(c["result"] == "PASS" for c in conditions):
        decision = "READY FOR REFLECTION & REVISION"
        message = "Your outline is organized and supported. You can continue to reflection and revision."
    elif not c1:
        decision = "DEVELOPING"
        message = "Your outline needs more structure. Add body points with your own ideas."
    else:
        decision = "NEARLY READY"
        message = "Your outline is taking shape. Review the open guidance before moving on."
    return {"conditions": conditions, "decision": decision, "student_message": message,
            "stage4_allowed": decision == "READY FOR REFLECTION & REVISION",
            "blocking_rules": sorted({r for (r, _p, _d) in fired if r in (
                "OUTLINE_001", "OUTLINE_003", "OUTLINE_004", "OUTLINE_005", "OUTLINE_006", "OUTLINE_008")})}


def compare_outline_revisions(prev: dict, curr: dict) -> dict:
    """Evidence-only revision comparison (structure + rules)."""
    def norm_points(o):
        return [" ".join(p["text"].lower().split()) + "||" + "||".join(" ".join(d.lower().split()) for d in p["details"]) for p in o]
    pn, cn = norm_points(prev["outline"]), norm_points(curr["outline"])
    deltas = {
        "point_delta": len(cn) - len(pn),
        "detail_delta": sum(len(p["details"]) for p in curr["outline"]) - sum(len(p["details"]) for p in prev["outline"]),
        "added_points": [i + 1 for i, p in enumerate(cn) if p not in pn],
        "removed_points": [i + 1 for i, p in enumerate(pn) if p not in cn],
        "order_changed": sorted(pn) == sorted(cn) and pn != cn,
        "resolved": sorted(set(prev["fired"]) - set(curr["fired"])),
        "newly": sorted(set(curr["fired"]) - set(prev["fired"])),
        "support_added": [i + 1 for i in range(len(cn)) if _support_key(cn, i) > _support_key(pn, i)] if len(cn) == len(pn) else [],
    }
    messages = []
    for i in deltas["support_added"]:
        messages.append({"text": f"You added support to Body Point {i}.", "evidence": "Detail-count increase."})
    if "OUTLINE_006" in deltas["resolved"]:
        messages.append({"text": "Body points are now more distinct.", "evidence": "OUTLINE_006 resolved."})
    if "OUTLINE_004" in deltas["resolved"]:
        messages.append({"text": "A previously off-topic detail was removed.", "evidence": "OUTLINE_004 resolved."})
    if "OUTLINE_005" in curr["fired"]:
        pts = sorted({p for (r, p, _d) in _fired_with(curr, "OUTLINE_005")})
        messages.append({"text": f"Body Point {', '.join(map(str, pts))} still lacks supporting detail." if pts else "A point still lacks supporting detail.",
                         "evidence": "OUTLINE_005 still active."})
    if "OUTLINE_006" in curr["fired"]:
        messages.append({"text": "Two main points still appear very similar.", "evidence": "OUTLINE_006 still active."})
    if deltas["order_changed"]:
        messages.append({"text": "You reordered your points; progression was reanalyzed.", "evidence": "Point order differs."})
    if not messages:
        messages.append({"text": "No measurable changes yet — revise your outline in your own words, then re-analyze.",
                         "evidence": "No structural/rule movement."})
    return {"deltas": deltas, "messages": messages}


def _support_key(normed, i):
    return normed[i].count("||") if i < len(normed) else 0


def _fired_with(curr, rule_id):
    return [(r, p, d) for (r, p, d) in curr.get("fired_with", []) if r == rule_id]
