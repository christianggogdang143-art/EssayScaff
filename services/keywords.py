"""Phase 2 keyword candidate extraction + deterministic ranking.

Starts from REAL spaCy tokens (never invented). Every lemma group gets a
row with WHY it was accepted/rejected as a candidate and WHY it was
selected/rejected by ranking. Fully deterministic: ties break
alphabetically by lemma.

Ranking formula (also centralized in config.py):
    score = FREQ_W * ln(1 + freq) + POS_W[pos] + DIST_W * (sentences_with_term / n_sentences)
"""

from __future__ import annotations

import math
import time

import config

RANKING_FORMULA = (
    "score = KEYWORD_FREQ_WEIGHT * ln(1 + freq)"
    " + KEYWORD_POS_WEIGHTS[pos]"
    " + KEYWORD_DIST_WEIGHT * (sentences_with_term / n_sentences)"
)


def keyword_score(freq: int, pos: str, sent_count: int, n_sentences: int) -> float:
    """Transparent ranking score. Pure function, directly testable."""
    freq_part = config.KEYWORD_FREQ_WEIGHT * math.log(1 + freq)
    pos_part = config.KEYWORD_POS_WEIGHTS.get(pos, 0.0)
    dist_part = config.KEYWORD_DIST_WEIGHT * (sent_count / max(n_sentences, 1))
    return freq_part + pos_part + dist_part


def extract_candidates(tokens: list[dict], n_sentences: int) -> dict:
    """Group alpha tokens by lemma and judge candidacy with reasons."""
    t0 = time.perf_counter()
    groups: dict[str, dict] = {}
    for t in tokens:
        if not t.get("is_alpha"):
            continue
        lemma = (t.get("lemma") or t["text"]).lower()
        g = groups.setdefault(
            lemma, {"lemma": lemma, "surfaces": {}, "pos_counts": {}, "sentences": set(), "stop_count": 0, "total": 0}
        )
        g["surfaces"][t["text"]] = g["surfaces"].get(t["text"], 0) + 1
        g["pos_counts"][t.get("pos", "")] = g["pos_counts"].get(t.get("pos", ""), 0) + 1
        if t.get("sentence") is not None:
            g["sentences"].add(t["sentence"])
        if t.get("is_stopword"):
            g["stop_count"] += 1
        g["total"] += 1

    terms = []
    for lemma, g in groups.items():
        # Representative POS: most frequent, ties broken alphabetically.
        pos = sorted(g["pos_counts"].items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
        surface = sorted(g["surfaces"].items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
        freq = g["total"]
        sent_list = sorted(g["sentences"])
        candidate, reason = True, ""
        if pos not in config.KEYWORD_CANDIDATE_POS:
            candidate, reason = False, f"POS {pos} is not content-bearing (need NOUN/PROPN/ADJ/VERB)."
        elif lemma in config.KEYWORD_EXCLUDED_LEMMAS:
            candidate, reason = False, f"Lemma '{lemma}' is a light verb excluded by config."
        elif len(lemma) < config.KEYWORD_MIN_LEMMA_LEN:
            candidate, reason = False, f"Lemma shorter than {config.KEYWORD_MIN_LEMMA_LEN} chars."
        elif g["stop_count"] == g["total"]:
            candidate, reason = False, "All occurrences flagged as stopwords."
        else:
            reason = f"Content POS {pos}, length ok, not a light verb/stopword."
        score = keyword_score(freq, pos, len(sent_list), n_sentences) if candidate else 0.0
        terms.append(
            {
                "lemma": lemma,
                "surface": surface,
                "pos": pos,
                "freq": freq,
                "sentences": sent_list,
                "is_stopword_majority": g["stop_count"] > g["total"] / 2,
                "candidate": candidate,
                "candidate_reason": reason,
                "score": round(score, 6),
                "score_parts": {
                    "freq_component": round(config.KEYWORD_FREQ_WEIGHT * math.log(1 + freq), 6),
                    "pos_component": config.KEYWORD_POS_WEIGHTS.get(pos, 0.0),
                    "dist_component": round(
                        config.KEYWORD_DIST_WEIGHT * (len(sent_list) / max(n_sentences, 1)), 6
                    ),
                }
                if candidate
                else None,
                "rank": None,
                "selected": False,
                "selection_reason": "",
            }
        )

    # Deterministic ranking: score desc, lemma asc.
    ranked = sorted([t for t in terms if t["candidate"]], key=lambda t: (-t["score"], t["lemma"]))
    for i, t in enumerate(ranked, start=1):
        t["rank"] = i
        if i <= config.KEYWORD_TOP_N:
            t["selected"] = True
            t["selection_reason"] = f"Rank {i} of {len(ranked)} (top-{config.KEYWORD_TOP_N}) by score {t['score']}."
        else:
            t["selection_reason"] = f"Rank {i} of {len(ranked)}: below top-{config.KEYWORD_TOP_N} cutoff."
    for t in terms:
        if not t["candidate"]:
            t["selection_reason"] = "Not ranked: rejected as candidate."

    elapsed = (time.perf_counter() - t0) * 1000.0
    return {
        "terms": sorted(terms, key=lambda t: (-t["score"], t["lemma"])),
        "selected": [t["lemma"] for t in ranked[: config.KEYWORD_TOP_N]],
        "formula": RANKING_FORMULA,
        # Configuration echo (provenance): lets transparency displays read
        # the active weights instead of duplicating constants in frontend code.
        "weights": {
            "freq_weight": config.KEYWORD_FREQ_WEIGHT,
            "dist_weight": config.KEYWORD_DIST_WEIGHT,
            "pos_weights": dict(config.KEYWORD_POS_WEIGHTS),
            "top_n": config.KEYWORD_TOP_N,
        },
        "processing_ms": elapsed,
    }


def build_query_terms(topic: str | None, teacher_keywords: list[str] | None) -> list[dict]:
    """Build provenance-separated query terms (never merged early).

    TEACHER_KEYWORD records come from the teacher list; TOPIC_TERM records
    come from content-lemma groups of the assignment topic text itself.
    """
    from services.nlp_service import get_nlp

    nlp = get_nlp()
    terms: list[dict] = []
    for kw in teacher_keywords or []:
        rec = lemmatize_phrase(kw)
        doc = nlp(rec["normalized"])
        alpha = [t for t in doc if t.is_alpha]
        pos = alpha[0].pos_ if len(alpha) == 1 else "NOUN"
        terms.append(
            {
                "kind": "TEACHER_KEYWORD",
                "original": kw,
                "normalized": rec["normalized"],
                "lemmas": rec["lemmas"],
                "primary_lemma": rec["primary_lemma"],
                "spacy_pos": pos,
            }
        )
    if topic:
        doc = nlp(topic)
        groups: dict[str, dict] = {}
        for t in doc:
            if not t.is_alpha or t.is_stop:
                continue
            lemma = t.lemma_.lower()
            g = groups.setdefault(lemma, {"pos_counts": {}, "total": 0})
            g["pos_counts"][t.pos_] = g["pos_counts"].get(t.pos_, 0) + 1
            g["total"] += 1
        for lemma, g in groups.items():
            pos = sorted(g["pos_counts"].items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
            if pos not in config.KEYWORD_CANDIDATE_POS:
                continue
            if lemma in config.KEYWORD_EXCLUDED_LEMMAS or len(lemma) < config.KEYWORD_MIN_LEMMA_LEN:
                continue
            terms.append(
                {
                    "kind": "TOPIC_TERM",
                    "original": lemma,
                    "normalized": lemma,
                    "lemmas": [lemma],
                    "primary_lemma": lemma,
                    "spacy_pos": pos,
                }
            )
    return terms


def lemmatize_phrase(text: str) -> dict:
    """Normalize + lemmatize a teacher keyword or topic fragment.

    Returns {original, normalized, lemmas, primary_lemma}. Uses the real
    spaCy pipeline; never invents lemmas.
    """
    from services.nlp_service import get_nlp

    normalized = " ".join(text.lower().split())
    doc = get_nlp()(normalized)
    lemmas = [t.lemma_.lower() for t in doc if t.is_alpha]
    return {
        "original": text,
        "normalized": normalized,
        "lemmas": lemmas,
        "primary_lemma": " ".join(lemmas),
    }
