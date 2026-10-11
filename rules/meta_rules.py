"""THESIS_002: meta-statement detection.

Detects sentences that describe what the essay/paper will do instead of
directly stating the main position. Case-insensitive regex matching with
word boundaries. Testable in isolation.
"""

from __future__ import annotations

import re

# Required minimum patterns (case-insensitive).
META_PATTERNS = [
    r"this\s+essay\s+will",
    r"this\s+paper\s+will",
    r"this\s+essay\s+discusses",
    r"this\s+paper\s+discusses",
    r"in\s+this\s+essay",
    r"in\s+this\s+paper",
]

_COMPILED = [(p, re.compile(p, re.IGNORECASE)) for p in META_PATTERNS]


def detect_meta_statements(sentences: list[dict]) -> tuple[list[dict], dict[int, bool]]:
    """Return (rule_results, {sentence_number: bool}).

    Offsets are absolute character offsets into the original text.
    """
    results = []
    by_sentence: dict[int, bool] = {s["number"]: False for s in sentences}
    for s in sentences:
        text = s["text"]
        for pattern, rx in _COMPILED:
            m = rx.search(text)
            if m:
                by_sentence[s["number"]] = True
                results.append(
                    {
                        "rule_id": "THESIS_002",
                        "rule_name": "Meta-statement detection",
                        "status": "ISSUE",
                        "severity": "warning",
                        "sentence_number": s["number"],
                        "evidence": m.group(0),
                        "start": s["start"] + m.start(),
                        "end": s["start"] + m.end(),
                        "details": {
                            "pattern": pattern,
                            "matched_text": m.group(0),
                        },
                        "reason": "The sentence describes what the essay will do instead of directly presenting the main claim.",
                    }
                )
    return results, by_sentence
