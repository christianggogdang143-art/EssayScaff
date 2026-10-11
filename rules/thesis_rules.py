"""THESIS_001: thesis / central-claim candidate detection (heuristic).

Conservative heuristic — NOT human-level thesis identification.
A sentence is reported as a CANDIDATE when it has linguistic evidence of
a declarative claim: ends declaratively, has a subject + a finite main
verb, is long enough to state a position, and is not a meta-statement.

Every candidate/non-candidate carries its evidence so it is testable and
explainable.
"""

from __future__ import annotations

FINITE_TAGS = {"VBZ", "VBP", "VBD", "MD"}  # finite verb forms (documented)


def _sent_tokens(doc, sent_info):
    return [t for t in doc if sent_info["start"] <= t.idx < sent_info["end"]]


def assess_sentence(doc, sent_info, has_metastatement: bool) -> dict:
    tokens = _sent_tokens(doc, sent_info)
    alpha = [t for t in tokens if t.is_alpha]
    text = sent_info["text"].strip()

    is_declarative = text.endswith(".")
    subjects = [t.text for t in tokens if t.dep_ in ("nsubj", "nsubjpass")]
    has_subject = len(subjects) > 0
    finite_verbs = [t.text for t in tokens if t.tag_ in FINITE_TAGS]
    main_verbs = [t.text for t in tokens if t.dep_ == "ROOT" and t.pos_ in ("VERB", "AUX")]
    main_verb = main_verbs[0] if main_verbs else (finite_verbs[0] if finite_verbs else None)

    reasons = []
    if not is_declarative:
        reasons.append("Sentence does not end declaratively.")
    if not has_subject:
        reasons.append("No nominal subject (nsubj) found.")
    if not finite_verbs:
        reasons.append("No finite verb (VBZ/VBP/VBD/MD) found.")
    if has_metastatement:
        reasons.append("Meta-statement detected in this sentence; it describes the essay instead of stating a claim.")
    # Minimum length for a claim candidate (documented heuristic threshold).
    # Six alphabetic tokens keeps short declarations ("Climate change threatens
    # smallholder farmers most severely." = 7) eligible while filtering stubs.
    if len(alpha) < 6:
        reasons.append(f"Only {len(alpha)} alphabetic tokens; too short for a central claim.")

    is_candidate = bool(is_declarative and has_subject and finite_verbs and not has_metastatement and len(alpha) >= 6)

    return {
        "rule_id": "THESIS_001",
        "rule_name": "Thesis / central-claim candidate detection (heuristic)",
        "status": "CANDIDATE" if is_candidate else "NOT_CANDIDATE",
        "severity": "info",
        "sentence_number": sent_info["number"],
        "evidence": sent_info["text"],
        "start": sent_info["start"],
        "end": sent_info["end"],
        "details": {
            "candidate_sentence": sent_info["text"],
            "main_verb_detected": main_verb,
            "finite_verbs": finite_verbs,
            "subject_available": has_subject,
            "subjects": subjects,
            "is_declarative": is_declarative,
            "meta_statement_detected": has_metastatement,
            "alpha_token_count": len(alpha),
        },
        "reason": (
            "Sentence shows declarative claim structure (subject + finite verb, sufficient length, no meta-statement)."
            if is_candidate
            else "Sentence rejected as claim candidate: " + (" ".join(reasons) if reasons else "insufficient claim evidence.")
        ),
    }


def detect_thesis_candidates(doc, sentences, metastatement_by_sentence: dict[int, bool]) -> list[dict]:
    """Assess every sentence. Callable/testable in isolation."""
    return [assess_sentence(doc, s, bool(metastatement_by_sentence.get(s["number"], False))) for s in sentences]
