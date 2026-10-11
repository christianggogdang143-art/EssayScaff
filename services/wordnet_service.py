"""Phase 2 WordNet expansion (NLTK WordNet — real database, not a custom list).

For each teacher/topic term: normalize, query WordNet synsets, extract
related lemma names, apply OUR documented conservative filter, then compare
retained terms against real student content. Every candidate records
retained true/false + rejection reason. OUR filtering logic is always
distinguishable from WORDNET database results in the trace.
"""

from __future__ import annotations

import time

import config

# Documented filtering rules (shown to the professor in the trace).
FILTER_RULES = [
    "F1: query synsets of the term's own POS first (POS compatibility); fall back to all POS only if none found.",
    "F2: normalize candidates (lowercase, underscores to spaces).",
    "F3: reject candidates identical to the lookup term itself (duplicates).",
    "F4: reject candidates already covered by another teacher/topic query term.",
    "F5: reject stopwords, tokens shorter than 3 chars, and multi-word terms (single-token matching only).",
    "F6: keep at most WORDNET_MAX_PER_TERM retained terms per query term; the rest are rejected with reason.",
]

_SPACY_TO_WORDNET = {"NOUN": "n", "VERB": "v", "ADJ": "a", "PROPN": "n", "ADV": "r"}


def _stopwords() -> set:
    try:
        from nltk.corpus import stopwords

        return set(stopwords.words("english"))
    except Exception:  # noqa: BLE001 - corpus may be absent; filter then skips
        return set()


def _synsets(lookup: str, pos: str | None):
    """Query the real WordNet database. Raises LookupError if data missing."""
    from nltk.corpus import wordnet as wn

    if pos:
        return wn.synsets(lookup, pos=pos)
    return wn.synsets(lookup)


def expand_term(original: str, lookup: str, spacy_pos: str, known_query_lemmas: set[str]) -> dict:
    """Expand one term. Returns full trace incl. retained/rejected candidates."""
    wn_pos = _SPACY_TO_WORDNET.get(spacy_pos)
    try:
        synsets = _synsets(lookup, wn_pos)
        pos_fallback = False
        if not synsets and wn_pos:
            synsets = _synsets(lookup, None)
            pos_fallback = True
    except Exception as exc:  # noqa: BLE001 - missing data etc.: honest status
        return {
            "original_term": original,
            "lookup_term": lookup,
            "status": "unavailable",
            "error": f"{type(exc).__name__}: {exc}",
            "synsets": [],
            "candidates": [],
            "retained": [],
            "rejected": [],
        }

    stop = _stopwords()
    candidates = []
    retained: list[str] = []
    seen: set[str] = set()
    for syn in synsets:
        for lemma in syn.lemmas():
            term = lemma.name().lower().replace("_", " ").strip()
            reason, keep = "", True
            if term == lookup or term in seen:
                keep, reason = False, "F3: duplicate of lookup term or already seen."
            elif term in known_query_lemmas:
                keep, reason = False, "F4: already covered by another teacher/topic query term."
            elif term in stop:
                keep, reason = False, "F5: stopword."
            elif len(term.replace(" ", "")) < 3:
                keep, reason = False, "F5: shorter than 3 chars."
            elif " " in term:
                keep, reason = False, "F5: multi-word term (single-token matching only)."
            elif len(retained) >= config.WORDNET_MAX_PER_TERM:
                keep, reason = False, f"F6: beyond per-term cap ({config.WORDNET_MAX_PER_TERM})."
            if keep:
                retained.append(term)
                seen.add(term)
            candidates.append(
                {
                    "candidate_term": term,
                    "synset": syn.name(),
                    "synset_definition": syn.definition(),
                    "retained": keep,
                    "rejection_reason": reason,
                }
            )

    return {
        "original_term": original,
        "lookup_term": lookup,
        "status": "ok",
        "pos_used": wn_pos if not pos_fallback else f"{wn_pos} (empty: fell back to all POS)",
        "synsets": [{"name": s.name(), "definition": s.definition(), "pos": s.pos()} for s in synsets],
        "synset_count": len(synsets),
        "candidates": candidates,
        "retained": retained,
        "rejected": [c for c in candidates if not c["retained"]],
    }


def analyze_terms(query_terms: list[dict], student_lemmas: set[str], student_surfaces: set[str]) -> dict:
    """Expand all teacher/topic terms and match against student content.

    query_terms: [{kind, original, normalized, lemmas, primary_lemma, spacy_pos}]
    Match priority: DIRECT > LEMMA > WORDNET > NO_MATCH.
    """
    t0 = time.perf_counter()
    known = {q["primary_lemma"] for q in query_terms} | {
        lemma for q in query_terms for lemma in q.get("lemmas", [])
    }
    results = []
    for q in query_terms:
        lookup = q["primary_lemma"].replace(" ", "_")
        exp = expand_term(q["original"], lookup or q["normalized"], q.get("spacy_pos", "NOUN"), known)
        matched_via = []
        if q["normalized"] in student_surfaces:
            match_type = "DIRECT"
            matched_via = [q["normalized"]]
        elif any(lemma in student_lemmas for lemma in q.get("lemmas", [])):
            match_type = "LEMMA"
            matched_via = [lemma for lemma in q.get("lemmas", []) if lemma in student_lemmas]
        else:
            retained_hits = [t for t in exp.get("retained", []) if t in student_lemmas]
            if retained_hits:
                match_type = "WORDNET"
                matched_via = retained_hits
            else:
                match_type = "NO_MATCH"
        # Annotate retained candidates with student_match flags.
        for c in exp.get("candidates", []):
            c["student_match"] = bool(c["retained"] and c["candidate_term"] in student_lemmas)
        results.append(
            {
                "kind": q["kind"],
                "spacy_pos": q.get("spacy_pos"),
                **exp,
                "student_match": match_type != "NO_MATCH",
                "match_type": match_type,
                "matched_student_terms": matched_via,
            }
        )
    try:
        import nltk

        nltk_version = nltk.__version__
    except Exception:  # noqa: BLE001
        nltk_version = "unknown"
    return {
        "terms": results,
        "library": "NLTK WordNet",
        "nltk_version": nltk_version,
        "filter_rules": FILTER_RULES,
        "direct_count": sum(1 for r in results if r["match_type"] == "DIRECT"),
        "lemma_count": sum(1 for r in results if r["match_type"] == "LEMMA"),
        "wordnet_count": sum(1 for r in results if r["match_type"] == "WORDNET"),
        "no_match_count": sum(1 for r in results if r["match_type"] == "NO_MATCH"),
        "processing_ms": (time.perf_counter() - t0) * 1000.0,
    }
