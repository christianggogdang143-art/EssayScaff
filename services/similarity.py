"""Phase 2 TF-IDF vectorization + cosine similarity + topic classification.

Libraries do the math (scikit-learn, honestly attributed); EssayScaff owns
corpus construction, verification, thresholds, and feedback. Manual cosine
components are genuinely computed from the same vectors and must reproduce
the library result within COSINE_TOLERANCE (tested).
"""

from __future__ import annotations

import math
import time

import config

CORPUS_DESIGN = (
    "Corpus = exactly 2 documents. "
    "topic_doc = assignment topic text + teacher keywords, lowercased + lemmatized. "
    "student_doc = student essay text, lowercased + lemmatized identically. "
    "Vectorizer = sklearn TfidfVectorizer(lowercase=False, preprocessor=None, "
    "tokenizer=str.split, token_pattern=None, min_df=1, max_df=1.0, "
    "ngram_range=(1, 1), analyzer='word', binary=False, norm='l2', use_idf=True, "
    "smooth_idf=True, sublinear_tf=False). "
    "Only lowercase/preprocessor/tokenizer/token_pattern/min_df are set by "
    "EssayScaff; the rest are the library's effective defaults, also recorded "
    "per-call in vectorizer_params."
)


def effective_vectorizer_params(vectorizer) -> dict:
    """JSON-safe record of the ACTUAL vectorizer configuration in force.

    Read from the live instance, never restated from memory, so provenance
    cannot drift from behavior.
    """
    return {
        "lowercase": bool(vectorizer.lowercase),
        "preprocessor": None,
        "tokenizer": "str.split",
        "token_pattern": vectorizer.token_pattern,
        "min_df": vectorizer.min_df,
        "max_df": vectorizer.max_df,
        "ngram_range": list(vectorizer.ngram_range),
        "analyzer": vectorizer.analyzer,
        "binary": bool(vectorizer.binary),
        "norm": vectorizer.norm,
        "use_idf": bool(vectorizer.use_idf),
        "smooth_idf": bool(vectorizer.smooth_idf),
        "sublinear_tf": bool(vectorizer.sublinear_tf),
    }
CORPUS_LIMITATION = (
    "With 2 documents, IDF only distinguishes 'term in both docs' "
    "(idf ~1.0) from 'term in one doc' (idf ~1.405). "
    "This is a transparent starting point, NOT a trained semantic model."
)

COSINE_FORMULA = "cos(A,B) = (A.B) / (||A|| * ||B||)"


def sklearn_version() -> str:
    try:
        import sklearn

        return sklearn.__version__
    except Exception:  # noqa: BLE001
        return "unknown"


def lemmatized_text(raw_text: str) -> str:
    """Lowercase + lemmatize alpha tokens with the real spaCy pipeline."""
    from services.nlp_service import get_nlp

    doc = get_nlp()(raw_text.replace("\r\n", "\n").replace("\r", "\n"))
    return " ".join(t.lemma_.lower() for t in doc if t.is_alpha)


def build_corpus(topic: str, teacher_keywords: list[str], student_text: str) -> dict:
    """Build the 2-document corpus with documented design + limitation."""
    t0 = time.perf_counter()
    topic_blob = " ".join([topic or ""] + list(teacher_keywords or []))
    topic_doc = lemmatized_text(topic_blob)
    student_doc = lemmatized_text(student_text)
    return {
        "topic_doc": topic_doc,
        "student_doc": student_doc,
        "design": CORPUS_DESIGN,
        "limitation": CORPUS_LIMITATION,
        "processing_ms": (time.perf_counter() - t0) * 1000.0,
    }


def default_vectorizer():
    """The single configured vectorizer constructor (behavior unchanged).

    Shared by vectorize() and provenance so the recorded parameters can
    never drift from the executed configuration.
    """
    from sklearn.feature_extraction.text import TfidfVectorizer

    return TfidfVectorizer(
        lowercase=False,
        preprocessor=None,
        tokenizer=str.split,
        token_pattern=None,
        min_df=config.TFIDF_MIN_DF,
    )


def vectorize(topic_doc: str, student_doc: str) -> dict:
    """Real sklearn TF-IDF on the 2-document corpus with full trace."""
    t0 = time.perf_counter()
    vectorizer = default_vectorizer()
    matrix = vectorizer.fit_transform([topic_doc, student_doc])
    vocab = vectorizer.vocabulary_  # term -> index
    idf = dict(zip(vectorizer.get_feature_names_out().tolist(), vectorizer.idf_.tolist()))
    topic_vec = matrix[0].toarray()[0].tolist()
    student_vec = matrix[1].toarray()[0].tolist()

    def nonzero(vec):
        names = vectorizer.get_feature_names_out().tolist()
        pairs = [(names[i], vec[i]) for i in range(len(vec)) if vec[i] != 0.0]
        return sorted(pairs, key=lambda p: (-p[1], p[0]))

    return {
        "library": "scikit-learn",
        "library_version": sklearn_version(),
        "vectorizer": "TfidfVectorizer(lowercase=False, tokenizer=str.split, min_df=1)",
        "vectorizer_params": effective_vectorizer_params(vectorizer),
        "vocabulary": sorted(vocab.keys()),
        "vocabulary_size": len(vocab),
        "idf": {k: round(v, 6) for k, v in sorted(idf.items())},
        "topic_vector": [round(v, 6) for v in topic_vec],
        "student_vector": [round(v, 6) for v in student_vec],
        "dimensions": len(topic_vec),
        "topic_nonzero": [(t, round(w, 6)) for t, w in nonzero(topic_vec)][:20],
        "student_nonzero": [(t, round(w, 6)) for t, w in nonzero(student_vec)][:20],
        "processing_ms": (time.perf_counter() - t0) * 1000.0,
    }


def cosine_similarity(topic_vec: list[float], student_vec: list[float]) -> dict:
    """Library cosine + genuine manual verification from the same vectors."""
    from sklearn.metrics.pairwise import cosine_similarity as sk_cosine

    t0 = time.perf_counter()
    lib = float(sk_cosine([topic_vec], [student_vec])[0][0])
    dot = sum(a * b for a, b in zip(topic_vec, student_vec))
    norm_t = math.sqrt(sum(a * a for a in topic_vec))
    norm_s = math.sqrt(sum(b * b for b in student_vec))
    if norm_t == 0.0 or norm_s == 0.0:
        manual = 0.0
        note = "Zero vector (no overlapping vocabulary terms): similarity defined as 0.0."
    else:
        manual = dot / (norm_t * norm_s)
        note = None
    diff = abs(manual - lib)
    return {
        "library": "sklearn.metrics.pairwise.cosine_similarity",
        "formula": COSINE_FORMULA,
        "dot_product": dot,
        "topic_norm": norm_t,
        "student_norm": norm_s,
        "library_result": lib,
        "manual_result": manual,
        "difference": diff,
        "tolerance": config.COSINE_TOLERANCE,
        "match": diff <= config.COSINE_TOLERANCE,
        "raw_similarity": lib,
        "percentage": lib * 100.0,
        "zero_vector_note": note,
        "processing_ms": (time.perf_counter() - t0) * 1000.0,
    }


def predict_relevance(similarity: float) -> str:
    """Clean callable prediction: float similarity -> WEAK/MODERATE/STRONG.

    Kept separate so later phases can evaluate actual human labels vs.
    these system predictions (confusion-matrix ready).
    """
    if similarity >= config.TOPIC_STRONG_THRESHOLD:
        return "STRONG"
    if similarity >= config.TOPIC_MODERATE_THRESHOLD:
        return "MODERATE"
    return "WEAK"


def classify(similarity: float) -> dict:
    """Threshold comparison with every value exposed (all real)."""
    t0 = time.perf_counter()
    weak_b = config.TOPIC_MODERATE_THRESHOLD
    strong_b = config.TOPIC_STRONG_THRESHOLD
    label = predict_relevance(similarity)
    if label == "STRONG":
        comparison = f"{similarity:.4f} >= {strong_b:.2f}"
    elif label == "MODERATE":
        comparison = f"{weak_b:.2f} <= {similarity:.4f} < {strong_b:.2f}"
    else:
        comparison = f"{similarity:.4f} < {weak_b:.2f}"
    return {
        "similarity": similarity,
        "weak_moderate_boundary": weak_b,
        "strong_boundary": strong_b,
        "threshold_warning": (
            "CONFIGURABLE DEVELOPMENT THRESHOLDS — PENDING EMPIRICAL "
            "VALIDATION. Not scientifically proven."
        ),
        "comparison": comparison,
        "classification": label,
        "processing_ms": (time.perf_counter() - t0) * 1000.0,
    }


def analyze_topic(topic: str, teacher_keywords: list[str], student_text: str) -> dict:
    """Full topic pipeline with per-stage measured timings."""
    corpus = build_corpus(topic, teacher_keywords, student_text)
    vec = vectorize(corpus["topic_doc"], corpus["student_doc"])
    cos = cosine_similarity(vec["topic_vector"], vec["student_vector"])
    cls = classify(cos["raw_similarity"])
    return {
        "corpus": corpus,
        "tfidf": vec,
        "cosine": cos,
        "classification": cls,
        "timings": {
            "corpus_ms": corpus["processing_ms"],
            "tfidf_ms": vec["processing_ms"],
            "cosine_ms": cos["processing_ms"],
            "classification_ms": cls["processing_ms"],
        },
    }
