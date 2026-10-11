"""MECHANICS_001 (possible fragment) and MECHANICS_002 (possible run-on).

Both are conservative heuristics and always reported as POSSIBLE, never
as certain diagnoses.
"""

from __future__ import annotations

import config

FINITE_TAGS = {"VBZ", "VBP", "VBD", "MD"}
SUBORDINATORS = {
    "because", "although", "though", "while", "whereas", "since", "unless",
    "until", "if", "when", "whenever", "where", "wherever", "after",
    "before", "as", "so", "that", "which", "who", "whom", "whose",
}


def _sent_tokens(doc, sent_info):
    return [t for t in doc if sent_info["start"] <= t.idx < sent_info["end"]]


# ---------------------------------------------------------- MECHANICS_001
def detect_fragments(doc, sentences: list[dict]) -> list[dict]:
    """Flag POSSIBLE sentence fragments.

    Signals: no finite/main verb, or a lone subordinate phrase, or an
    extremely short phrase without clause structure.
    """
    results = []
    for s in sentences:
        tokens = _sent_tokens(doc, s)
        alpha = [t for t in tokens if t.is_alpha]
        if len(alpha) <= 1:
            continue  # punctuation-only / one-word inputs handled elsewhere
        finite = [t for t in tokens if t.tag_ in FINITE_TAGS]
        has_root_verb = any(t.dep_ == "ROOT" and t.pos_ in ("VERB", "AUX") for t in tokens)
        first = alpha[0].text.lower() if alpha else ""
        starts_subordinator = first in SUBORDINATORS
        signals = []
        if not finite:
            signals.append("no finite/main verb (VBZ/VBP/VBD/MD)")
        if not has_root_verb:
            signals.append("no verbal ROOT in dependency structure")
        if starts_subordinator and len(finite) <= 1 and len(alpha) < 10:
            signals.append(f"begins with subordinator '{alpha[0].text}' with no independent clause")
        if len(alpha) < 5 and not finite:
            signals.append(f"extremely short phrase ({len(alpha)} words) without a verb")
        if signals:
            results.append(
                {
                    "rule_id": "MECHANICS_001",
                    "rule_name": "Possible sentence-fragment indicator (heuristic)",
                    "status": "ISSUE",
                    "severity": "warning",
                    "sentence_number": s["number"],
                    "evidence": s["text"],
                    "start": s["start"],
                    "end": s["end"],
                    "details": {"signals": signals, "alpha_token_count": len(alpha)},
                    "reason": "POSSIBLE fragment: " + "; ".join(signals) + ". Review whether this sentence expresses a complete thought.",
                }
            )
    return results


# ---------------------------------------------------------- MECHANICS_002
def detect_runons(doc, sentences: list[dict]) -> list[dict]:
    """Flag POSSIBLE run-on sentences.

    Signals: unusually long sentences, multiple independent-clause
    indicators (finite verbs + coordinating conjunctions) with weak or
    missing separating punctuation.
    """
    results = []
    for s in sentences:
        tokens = _sent_tokens(doc, s)
        alpha = [t for t in tokens if t.is_alpha]
        n = len(tokens)
        finite = [t for t in tokens if t.tag_ in FINITE_TAGS]
        cc = [t for t in tokens if t.dep_ == "cc" and t.pos_ == "CCONJ"]
        commas = sum(1 for t in tokens if t.text == ",")
        strong = sum(1 for t in tokens if t.text in (";", ":", "\u2014", "--"))
        signals = []
        if n >= config.RUNON_LONG_SENTENCE_TOKENS:
            signals.append(f"unusually long sentence ({n} tokens)")
        if len(finite) >= 3 and commas >= 2 and strong == 0:
            signals.append(
                f"multiple finite verbs ({len(finite)}) joined with commas but no semicolon/colon"
            )
        if len(cc) >= 2 and n >= config.RUNON_MIN_TOKENS and strong == 0 and commas == 0:
            signals.append(
                f"multiple coordinating conjunctions ({len(cc)}) with no separating punctuation"
            )
        if signals:
            results.append(
                {
                    "rule_id": "MECHANICS_002",
                    "rule_name": "Possible run-on sentence indicator (heuristic)",
                    "status": "ISSUE",
                    "severity": "warning",
                    "sentence_number": s["number"],
                    "evidence": s["text"],
                    "start": s["start"],
                    "end": s["end"],
                    "details": {
                        "signals": signals,
                        "token_count": n,
                        "finite_verb_count": len(finite),
                        "conjunction_count": len(cc),
                        "comma_count": commas,
                    },
                    "reason": "POSSIBLE run-on: " + "; ".join(signals) + ". Review whether this should be split or punctuated differently.",
                }
            )
    return results
