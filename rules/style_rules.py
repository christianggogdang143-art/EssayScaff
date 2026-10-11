"""STYLE_001 (passive voice) and STYLE_002 (repeated sentence openings).

STYLE_001 uses dependency/POS evidence (auxpass / nsubjpass), never a
bare search for the word "was".
STYLE_002 compares normalized sentence beginnings.
Both are heuristic detectors and labeled as such.
"""

from __future__ import annotations

import re
import string

import config


def _sent_tokens(doc, sent_info):
    return [t for t in doc if sent_info["start"] <= t.idx < sent_info["end"]]


# ---------------------------------------------------------------- STYLE_001
def detect_passive_voice(doc, sentences: list[dict]) -> list[dict]:
    """Flag sentences with dependency-based passive evidence.

    Evidence required: a token with dep_ auxpass/nsubjpass, or a
    be-lemma auxiliary governing a VBN participle. Returns one result per
    affected sentence at most.
    """
    results = []
    for s in sentences:
        tokens = _sent_tokens(doc, s)
        passive_aux = [t for t in tokens if t.dep_ == "auxpass"]
        passive_subj = [t for t in tokens if t.dep_ == "nsubjpass"]
        # Fallback pattern: be-verb + VBN with aux dependency.
        be_vbn = [
            t
            for t in tokens
            if t.tag_ == "VBN"
            and any(c.lemma_.lower() == "be" and c.dep_ in ("aux", "auxpass") for c in t.children)
        ]
        if passive_aux or passive_subj or be_vbn:
            anchor = (passive_aux or passive_subj or be_vbn)[0]
            # Evidence: the auxiliary + participle span when available.
            span_tokens = sorted({anchor.i} | {c.i for c in anchor.children} | {anchor.head.i})
            evidence = doc[span_tokens[0] : span_tokens[-1] + 1].text
            results.append(
                {
                    "rule_id": "STYLE_001",
                    "rule_name": "Passive voice indicator (heuristic)",
                    "status": "ISSUE",
                    "severity": "info",
                    "sentence_number": s["number"],
                    "evidence": evidence,
                    "start": s["start"],
                    "end": s["end"],
                    "details": {
                        "auxpass_tokens": [t.text for t in passive_aux],
                        "nsubjpass_tokens": [t.text for t in passive_subj],
                        "be_vbn_tokens": [t.text for t in be_vbn],
                    },
                    "reason": "Dependency/POS evidence of passive construction (auxpass/nsubjpass or be + VBN participle). Consider whether an active formulation would state the agent more directly.",
                }
            )
    return results


# ---------------------------------------------------------------- STYLE_002
def _opening_key(text: str) -> str | None:
    # Compare the first TWO words: spec example "The student..." x3 differs in
    # the third word ("reads"/"writes"/"revises"), so a 3-word key would miss it.
    words = re.findall(r"[A-Za-z']+", text.lower())
    if len(words) >= 2:
        return " ".join(words[:2])
    if len(words) >= 1:
        return " ".join(words)
    return None


def detect_repeated_openings(sentences: list[dict]) -> list[dict]:
    """Flag sentence openings repeated >= REPEATED_OPENING_THRESHOLD times."""
    groups: dict[str, list[dict]] = {}
    for s in sentences:
        key = _opening_key(s["text"])
        if key:
            groups.setdefault(key, []).append(s)
    results = []
    for opening, members in groups.items():
        if len(members) >= config.REPEATED_OPENING_THRESHOLD:
            results.append(
                {
                    "rule_id": "STYLE_002",
                    "rule_name": "Repeated sentence-opening indicator (heuristic)",
                    "status": "ISSUE",
                    "severity": "info",
                    "sentence_number": [m["number"] for m in members],
                    "evidence": opening,
                    "start": members[0]["start"],
                    "end": members[-1]["end"],
                    "details": {
                        "repeated_opening": opening,
                        "count": len(members),
                        "affected_sentences": [m["number"] for m in members],
                    },
                    "reason": f"The opening '{opening}' starts {len(members)} sentences. Varying sentence openings can improve readability.",
                }
            )
    return results


def _punct_only(text: str) -> bool:
    stripped = text.strip().strip(string.punctuation + " \t\n")
    return len(stripped) == 0
