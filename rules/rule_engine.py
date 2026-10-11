"""EssayScaff rule engine (Phase 1).

Runs the six heuristic detectors in a fixed, documented order and returns
structured, individually testable results. Kept separate from Flask routes.
"""

from __future__ import annotations

import time

from rules import mechanics_rules, style_rules, thesis_rules
from rules.meta_rules import detect_meta_statements


def run_all_rules(doc, sentences: list[dict], clock=None) -> dict:
    """Run all Phase 1 rules. Returns {results, timings, events?}.

    `clock`, when given, is a zero-argument callable returning milliseconds
    since analysis start; each rule completion is then recorded as a real
    measured event (used for the chronological execution trace).
    """
    timings: dict[str, float] = {}
    all_results: list[dict] = []
    events: list[dict] = []

    def run(name, fn):
        t0 = time.perf_counter()
        out = fn()
        timings[f"{name}_ms"] = (time.perf_counter() - t0) * 1000.0
        if clock is not None:
            events.append({"t_ms": clock(), "event": f"{name} completed"})
        return out

    meta_results, meta_by_sentence = run(
        "THESIS_002", lambda: detect_meta_statements(sentences)
    )
    all_results.extend(meta_results)

    all_results.extend(
        run("THESIS_001", lambda: thesis_rules.detect_thesis_candidates(doc, sentences, meta_by_sentence))
    )
    all_results.extend(run("STYLE_001", lambda: style_rules.detect_passive_voice(doc, sentences)))
    all_results.extend(run("STYLE_002", lambda: style_rules.detect_repeated_openings(sentences)))
    all_results.extend(run("MECHANICS_001", lambda: mechanics_rules.detect_fragments(doc, sentences)))
    all_results.extend(run("MECHANICS_002", lambda: mechanics_rules.detect_runons(doc, sentences)))

    out = {"results": all_results, "timings": timings}
    if clock is not None:
        out["events"] = events
    return out
