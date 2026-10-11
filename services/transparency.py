"""Transparency Mode data builders (Phase 1B).

Pure, testable helpers that assemble the professor-facing trace from REAL
run data. No NLP logic lives here; this module only organizes what the
pipeline measured into forward (pipeline) and backward (backtrace) views.
"""

from __future__ import annotations

import platform
import subprocess
from importlib import metadata as importlib_metadata

import config

NOT_RECORDED = "not recorded"


def spacy_version() -> str:
    try:
        import spacy

        return spacy.__version__
    except Exception:  # noqa: BLE001
        return NOT_RECORDED


def spacy_model_version(model_name: str) -> str:
    try:
        return importlib_metadata.version(model_name.replace("-", "_"))
    except Exception:  # noqa: BLE001
        try:
            return importlib_metadata.version("en-core-web-sm")
        except Exception:  # noqa: BLE001
            return NOT_RECORDED


def languagetool_versions() -> dict:
    """Return {package_version, install_version} honestly (unknown allowed)."""
    try:
        pkg = importlib_metadata.version("language-tool-python")
    except Exception:  # noqa: BLE001
        pkg = NOT_RECORDED
    install = NOT_RECORDED
    try:
        from services.grammar_service import _resolve_jar_dir

        jar_dir = _resolve_jar_dir()
        if jar_dir:
            install = jar_dir.rsplit("LanguageTool-", 1)[-1] if "LanguageTool-" in jar_dir else jar_dir
    except Exception:  # noqa: BLE001
        pass
    return {"package_version": pkg, "install_version": install}


def git_commit() -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return out.stdout.strip() or None
    except Exception:  # noqa: BLE001
        return None


def build_run_info(total_ms: float, lt_status: str | None, spacy_model: str) -> dict:
    lt = languagetool_versions()
    return {
        "app_version": getattr(config, "APP_VERSION", NOT_RECORDED),
        "python_version": platform.python_version(),
        "spacy_version": spacy_version(),
        "spacy_model": spacy_model,
        "spacy_model_version": spacy_model_version(spacy_model),
        "languagetool_status": lt_status or NOT_RECORDED,
        "languagetool_package": lt["package_version"],
        "languagetool_install": lt["install_version"],
        "git_commit": git_commit() or NOT_RECORDED,
        "total_ms": total_ms,
    }


# --------------------------------------------------------------------------
# Pipeline step definitions. `file`/`function` use REAL existing names and are
# validated by tests (importable + attribute exists).
# kind "ours" = EssayScaff code; "external" = open-source library call.
# --------------------------------------------------------------------------
STEP_DEFS: list[dict] = [
    {
        "id": "raw_input",
        "number": 1,
        "name": "Raw Input Capture",
        "purpose": "Receive the student's exact text from the frontend request and validate it before any analysis.",
        "file": "routes/analysis_routes.py",
        "function": "analyze",
        "kind": "ours",
        "next": "normalization",
    },
    {
        "id": "normalization",
        "number": 2,
        "name": "Text Normalization",
        "purpose": "Build a conservative analysis copy (unicode NFC, CRLF/CR unified). The original text is preserved untouched so offsets stay exact.",
        "file": "services/nlp_service.py",
        "function": "normalize_text",
        "kind": "ours",
        "next": "sentence_segmentation",
    },
    {
        "id": "sentence_segmentation",
        "number": 3,
        "name": "Sentence Segmentation",
        "purpose": "Split the original text into sentences with exact character offsets using the spaCy sentence parser.",
        "file": "services/nlp_service.py",
        "function": "analyze_text",
        "kind": "ours",
        "library": "spaCy",
        "operations": ["nlp(text)", "doc.sents", "sent.start_char", "sent.end_char"],
        "next": "tokenization",
    },
    {
        "id": "tokenization",
        "number": 4,
        "name": "Tokenization",
        "purpose": "Break the spaCy document into linguistic tokens while preserving exact original-text offsets.",
        "file": "services/nlp_service.py",
        "function": "analyze_text",
        "kind": "ours",
        "library": "spaCy",
        "operations": ["token.text", "token.idx"],
        "next": "lemmatization",
    },
    {
        "id": "lemmatization",
        "number": 5,
        "name": "Lemmatization",
        "purpose": "Record each token's dictionary base form (lemma) next to its surface form. The student's word is never replaced.",
        "file": "services/nlp_service.py",
        "function": "analyze_text",
        "kind": "ours",
        "library": "spaCy",
        "operations": ["token.lemma_"],
        "timing_note": "Extracted in the same single spaCy pass as tokenization; shares the token-capture timing.",
        "next": "stopword_identification",
    },
    {
        "id": "stopword_identification",
        "number": 6,
        "name": "Stopword Identification",
        "purpose": "Flag whether spaCy classifies each token as a stopword. Nothing is deleted; flags stay visible in the trace.",
        "file": "services/nlp_service.py",
        "function": "analyze_text",
        "kind": "ours",
        "library": "spaCy",
        "operations": ["token.is_stop"],
        "timing_note": "Extracted in the same single spaCy pass as tokenization; shares the token-capture timing.",
        "next": "pos_tagging",
    },
    {
        "id": "pos_tagging",
        "number": 7,
        "name": "POS Tagging",
        "purpose": "Record each token's coarse part-of-speech, detailed tag, and dependency label from the spaCy parse.",
        "file": "services/nlp_service.py",
        "function": "analyze_text",
        "kind": "ours",
        "library": "spaCy",
        "operations": ["token.pos_", "token.tag_", "token.dep_"],
        "timing_note": "Extracted in the same single spaCy pass as tokenization; shares the token-capture timing.",
        "next": "rule_engine",
    },
    {
        "id": "rule_engine",
        "number": 8,
        "name": "EssayScaff Rule Engine",
        "purpose": "Run the six heuristic academic-writing detectors over sentences and dependency/POS evidence. Heuristic, honestly labeled.",
        "file": "rules/rule_engine.py",
        "function": "run_all_rules",
        "kind": "ours",
        "next": "languagetool",
    },
    {
        "id": "languagetool",
        "number": 9,
        "name": "LanguageTool Grammar Analysis",
        "purpose": "Ask the local open-source LanguageTool server for grammar matches. EssayScaff only wraps the call; matches are never auto-applied.",
        "file": "services/grammar_service.py",
        "function": "check_grammar",
        "kind": "ours",
        "library": "LanguageTool",
        "operations": ["LanguageTool.check(text)"],
        "next": "keyword_extraction",
    },
    {
        "id": "keyword_extraction",
        "number": 10,
        "name": "Keyword Extraction",
        "purpose": "Group real spaCy tokens by lemma, judge candidacy with reasons, and rank deterministically by a shown formula (frequency + POS + sentence distribution).",
        "file": "services/keywords.py",
        "function": "extract_candidates",
        "kind": "ours",
        "next": "wordnet_expansion",
    },
    {
        "id": "wordnet_expansion",
        "number": 11,
        "name": "WordNet Expansion",
        "purpose": "Look up teacher/topic terms in the real NLTK WordNet database, filter candidates with documented rules, and match retained terms against student content.",
        "file": "services/wordnet_service.py",
        "function": "analyze_terms",
        "kind": "ours",
        "library": "NLTK WordNet",
        "operations": ["wordnet.synsets(term, pos)"],
        "next": "tfidf",
    },
    {
        "id": "tfidf",
        "number": 12,
        "name": "TF-IDF Vectorization",
        "purpose": "Vectorize the 2-document corpus (topic doc vs student doc) with scikit-learn TF-IDF. Honest 2-doc IDF limitation documented.",
        "file": "services/similarity.py",
        "function": "vectorize",
        "kind": "ours",
        "library": "scikit-learn",
        "operations": ["TfidfVectorizer.fit_transform([topic_doc, student_doc])"],
        "next": "cosine_similarity",
    },
    {
        "id": "cosine_similarity",
        "number": 13,
        "name": "Cosine Similarity",
        "purpose": "Compute real cosine similarity between topic and student vectors (library), verified by a genuine manual dot/norm calculation.",
        "file": "services/similarity.py",
        "function": "cosine_similarity",
        "kind": "ours",
        "library": "scikit-learn",
        "operations": ["cosine_similarity([topic_vec], [student_vec])"],
        "next": "topic_classification",
    },
    {
        "id": "topic_classification",
        "number": 14,
        "name": "Topic Classification",
        "purpose": "Compare similarity against configurable development thresholds (WEAK/MODERATE/STRONG, pending empirical validation).",
        "file": "services/similarity.py",
        "function": "classify",
        "kind": "ours",
        "next": "feedback",
    },
    {
        "id": "feedback",
        "number": 15,
        "name": "Explainable Feedback",
        "purpose": "Convert rule, LanguageTool, and topic detections into student-facing guidance (what/where/why/source/what-to-review). Never rewrites text.",
        "file": "services/feedback_service.py",
        "function": "build_feedback",
        "kind": "ours",
        "next": "persistence",
    },
    {
        "id": "persistence",
        "number": 16,
        "name": "Persistence",
        "purpose": "Store the analysis, technical trace, and transparency data in SQLite under the analysis ID for later inspection.",
        "file": "services/db.py",
        "function": "save_run",
        "kind": "ours",
        "next": None,
    },
]

RULE_SOURCES: dict[str, dict] = {
    "THESIS_001": {"file": "rules/thesis_rules.py", "function": "detect_thesis_candidates"},
    "THESIS_002": {"file": "rules/meta_rules.py", "function": "detect_meta_statements"},
    "STYLE_001": {"file": "rules/style_rules.py", "function": "detect_passive_voice"},
    "STYLE_002": {"file": "rules/style_rules.py", "function": "detect_repeated_openings"},
    "MECHANICS_001": {"file": "rules/mechanics_rules.py", "function": "detect_fragments"},
    "MECHANICS_002": {"file": "rules/mechanics_rules.py", "function": "detect_runons"},
}


def _preview(text: str, limit: int = 300) -> str:
    return text if len(text) <= limit else text[:limit] + f"… [{len(text)} chars total]"


def build_pipeline(ctx: dict) -> list[dict]:
    """Assemble per-step transparency data from the real run context.

    ctx keys: raw_text, normalized, chars_before/after, sentences, tokens,
    timings (dict), rule_results, rule_timings, lt_result, lt_stats, feedback,
    feedback_ms, db_ms, validation_ms, spacy_model.
    """
    timings = ctx.get("timings", {})
    sentences = ctx.get("sentences", [])
    tokens = ctx.get("tokens", [])
    raw = ctx.get("raw_text", "")
    lt = ctx.get("lt_result", {}) or {}
    lt_stats = ctx.get("lt_stats", {}) or {}
    token_preview = [
        {
            "index": t["index"],
            "text": t["text"],
            "lemma": t["lemma"],
            "pos": t["pos"],
            "tag": t.get("tag"),
            "start": t["start"],
            "end": t["end"],
        }
        for t in tokens[:25]
    ]

    by_id: dict[str, dict] = {
        "raw_input": {
            "input": f"POST /api/analyze body.text ({len(raw)} chars)",
            "process": "Input validation: type check, empty/whitespace check, length cap.",
            "output": {"chars": len(raw), "preview": _preview(raw)},
            "timing_ms": ctx.get("validation_ms", 0.0),
        },
        "normalization": {
            "input": f"raw text ({ctx.get('chars_before', len(raw))} chars)",
            "process": "unicodedata NFC + CRLF/CR unification only.",
            "output": {
                "chars_before": ctx.get("chars_before"),
                "chars_after": ctx.get("chars_after"),
                "preview": _preview(ctx.get("normalized", "")),
            },
            "timing_ms": timings.get("normalization_ms", 0.0),
        },
        "sentence_segmentation": {
            "input": "original text parsed by spaCy",
            "process": f"spaCy doc.sents over model {ctx.get('spacy_model')}",
            "output": {"sentence_count": len(sentences), "sentences": sentences},
            "timing_ms": timings.get("segmentation_ms", 0.0),
        },
        "tokenization": {
            "input": f"{len(sentences)} sentences",
            "process": "spaCy Doc token iterator; offsets via token.idx",
            "output": {
                "token_count": len(tokens),
                "tokens_preview": token_preview,
                "tokens_truncated": len(tokens) > 25,
            },
            "timing_ms": timings.get("tokenization_ms", 0.0),
        },
        "lemmatization": {
            "input": f"{len(tokens)} tokens",
            "process": "token.lemma_ per token (surface form preserved)",
            "output": {
                "pairs": [f"{t['text']}→{t['lemma']}" for t in tokens[:25]],
                "pairs_truncated": len(tokens) > 25,
            },
            "timing_ms": timings.get("tokenization_ms", 0.0),
        },
        "stopword_identification": {
            "input": f"{len(tokens)} tokens",
            "process": "token.is_stop per token; nothing deleted",
            "output": {
                "stopword_count": sum(1 for t in tokens if t.get("is_stopword")),
                "stopwords": [t["text"] for t in tokens if t.get("is_stopword")][:25],
            },
            "timing_ms": timings.get("tokenization_ms", 0.0),
        },
        "pos_tagging": {
            "input": f"{len(tokens)} tokens",
            "process": "token.pos_ / token.tag_ / token.dep_ per token",
            "output": {
                "tagged": [f"{t['text']}/{t['pos']}/{t.get('tag')}" for t in tokens[:25]],
                "tagged_truncated": len(tokens) > 25,
            },
            "timing_ms": timings.get("tokenization_ms", 0.0),
        },
        "rule_engine": {
            "input": f"{len(sentences)} sentences + dependency/POS evidence",
            "process": {k: v for k, v in (ctx.get("rule_timings") or {}).items()},
            "output": {"result_count": len(ctx.get("rule_results", [])), "results": ctx.get("rule_results", [])},
            "timing_ms": timings.get("rules_total_ms", 0.0),
        },
        "languagetool": {
            "input": f"raw text ({len(raw)} chars)",
            "process": {
                "wrapper": "services/grammar_service.py :: check_grammar",
                "library_call": "LanguageTool.check(text) on the shared local server",
                "server_reused": bool(lt_stats.get("reused")),
                "init_ms": lt_stats.get("init_ms"),
                "check_ms": lt_stats.get("last_check_ms"),
            },
            "output": {"status": lt.get("status"), "issue_count": len(lt.get("issues", [])), "issues": lt.get("issues", [])},
            "timing_ms": lt.get("processing_ms", 0.0),
        },
        "feedback": {
            "input": f"{len(ctx.get('rule_results', []))} rule results + {len(lt.get('issues', []))} LanguageTool issues",
            "process": "build_feedback(): rule candidates filtered, guidance text attached, no rewriting",
            "output": {"feedback_count": len(ctx.get("feedback", [])), "feedback": ctx.get("feedback", [])},
            "timing_ms": ctx.get("feedback_ms", 0.0),
        },
        "persistence": {
            "input": "analysis record (summary + feedback + technical + transparency)",
            "process": "SQLite plain INSERT into analysis_runs (append-only; ID collisions retry with a fresh ID, never overwrite)",
            "output": {"stored": True},
            "timing_ms": ctx.get("db_ms", 0.0),
        },
    }

    phase2 = ctx.get("phase2") or {}
    phase2_ran = bool(phase2.get("ran"))
    kw = phase2.get("keywords") or {}
    wn = phase2.get("wordnet") or {}
    ta = phase2.get("topic_analysis") or {}
    tfidf_d = ta.get("tfidf") or {}
    cos_d = ta.get("cosine") or {}
    cls_d = ta.get("classification") or {}
    by_id.update(
        {
            "keyword_extraction": {
                "input": f"{len(tokens)} spaCy tokens ({len(sentences)} sentences)",
                "process": f"Candidate filter {sorted(config.KEYWORD_CANDIDATE_POS)} + ranking: {kw.get('formula', '')}",
                "output": {
                    "term_count": len(kw.get("terms", [])),
                    "selected": kw.get("selected", []),
                    "terms": kw.get("terms", []),
                }
                if phase2_ran or kw
                else None,
                "timing_ms": (phase2.get("timings") or {}).get("keyword_ms", 0.0),
            },
            "wordnet_expansion": {
                "input": f"{len(phase2.get('query_terms') or [])} teacher/topic query terms",
                "process": f"NLTK WordNet lookup + filtering ({len(wn.get('filter_rules', []))} documented rules)",
                "output": {
                    "terms": wn.get("terms", []),
                    "direct": wn.get("direct_count"),
                    "lemma": wn.get("lemma_count"),
                    "wordnet": wn.get("wordnet_count"),
                    "no_match": wn.get("no_match_count"),
                }
                if wn
                else None,
                "timing_ms": (phase2.get("timings") or {}).get("wordnet_ms", 0.0),
            },
            "tfidf": {
                "input": "2-document corpus (topic doc vs student doc)",
                "process": f"{tfidf_d.get('vectorizer', '')} via {tfidf_d.get('library', '')} {tfidf_d.get('library_version', '')}",
                "output": {
                    "vocabulary_size": tfidf_d.get("vocabulary_size"),
                    "dimensions": tfidf_d.get("dimensions"),
                    "vocabulary": tfidf_d.get("vocabulary"),
                    "idf": tfidf_d.get("idf"),
                    "topic_nonzero": tfidf_d.get("topic_nonzero"),
                    "student_nonzero": tfidf_d.get("student_nonzero"),
                    "topic_vector": tfidf_d.get("topic_vector"),
                    "student_vector": tfidf_d.get("student_vector"),
                    "corpus_limitation": (ta.get("corpus") or {}).get("limitation"),
                }
                if tfidf_d
                else None,
                "timing_ms": (phase2.get("timings") or {}).get("tfidf_ms", 0.0),
            },
            "cosine_similarity": {
                "input": "topic vector + student vector",
                "process": f"{cos_d.get('library', '')}; manual check {cos_d.get('formula', '')}",
                "output": {
                    "dot_product": cos_d.get("dot_product"),
                    "topic_norm": cos_d.get("topic_norm"),
                    "student_norm": cos_d.get("student_norm"),
                    "library_result": cos_d.get("library_result"),
                    "manual_result": cos_d.get("manual_result"),
                    "difference": cos_d.get("difference"),
                    "tolerance": cos_d.get("tolerance"),
                    "match": cos_d.get("match"),
                    "percentage": cos_d.get("percentage"),
                }
                if cos_d
                else None,
                "timing_ms": (phase2.get("timings") or {}).get("cosine_ms", 0.0),
            },
            "topic_classification": {
                "input": f"similarity {cls_d.get('similarity')}" if cls_d else "no similarity (topic pipeline did not run)",
                "process": "config thresholds (development values, pending validation)",
                "output": cls_d if cls_d else None,
                "timing_ms": (phase2.get("timings") or {}).get("classification_ms", 0.0),
            },
        }
    )

    PHASE2_STEPS = {"keyword_extraction", "wordnet_expansion", "tfidf", "cosine_similarity", "topic_classification"}
    steps = []
    for step in STEP_DEFS:
        data = by_id.get(step["id"], {})
        if step["id"] in PHASE2_STEPS and not phase2_ran and step["id"] != "keyword_extraction":
            status = "NOT_RUN"
        elif step["id"] == "keyword_extraction" and not (phase2_ran or kw):
            status = "NOT_RUN"
        elif step["id"] == "languagetool" and lt.get("status") == "unavailable":
            status = "UNAVAILABLE"
        else:
            status = "COMPLETE"
        entry = {
            **step,
            "status": status,
            "input": data.get("input"),
            "process": data.get("process"),
            "output": data.get("output"),
            "timing_ms": data.get("timing_ms", 0.0),
            "error": lt.get("error") if step["id"] == "languagetool" else None,
        }
        if status == "NOT_RUN":
            entry["reason"] = phase2.get("skip_reason") or "No topic/teacher keywords supplied."
        steps.append(entry)
    return steps


def _tokens_in_span(tokens: list[dict], start: int, end: int) -> list[int]:
    return [t["index"] for t in tokens if t["start"] < end and t["end"] > start]


TOPIC_SOURCE = "TOPIC_CLASSIFIER"


def build_backtraces(feedback: list[dict], rule_results: list[dict], sentences: list[dict], tokens: list[dict], raw_text: str, topic_ctx: dict | None = None) -> list[dict]:
    """Build feedback→…→raw provenance chains from real run data."""
    by_rule: dict[str, list[dict]] = {}
    for r in rule_results:
        by_rule.setdefault(r.get("rule_id", ""), []).append(r)

    chains = []
    for f in feedback:
        source = f.get("source", "")
        chain: dict = {
            "feedback_id": f.get("feedback_id"),
            "title": f.get("title"),
            "category": f.get("category"),
            "source": source,
            "original_text": raw_text,
        }
        if source in RULE_SOURCES:
            matches = [
                r
                for r in by_rule.get(source, [])
                if r.get("evidence") == f.get("text")
                and r.get("sentence_number") == f.get("sentence_number")
            ]
            if matches:
                rule = matches[0]
                link_status = "RESOLVED"
            else:
                # No exact rule record: say so honestly instead of borrowing
                # an unrelated result's evidence/reason/decision.
                rule = {}
                link_status = "UNRESOLVED"
            sent_no = f.get("sentence_number")
            sent = next((s for s in sentences if s["number"] == sent_no), None) if isinstance(sent_no, int) else None
            chain.update(
                {
                    "generated_by": source,
                    "link_status": link_status,
                    "rule_name": rule.get("rule_name"),
                    "rule_file": RULE_SOURCES[source]["file"],
                    "rule_function": RULE_SOURCES[source]["function"],
                    "evidence": f.get("text"),
                    "char_start": f.get("start"),
                    "char_end": f.get("end"),
                    "sentence": sent,
                    "token_indices": _tokens_in_span(tokens, f.get("start") or 0, f.get("end") or 0)
                    if isinstance(f.get("start"), int)
                    else [],
                    "reason": rule.get("reason") or f.get("reason"),
                    "decision": rule.get("status")
                    if link_status == "RESOLVED"
                    else "unknown (no matching rule record)",
                }
            )
        elif source.startswith("LanguageTool:"):
            chain.update(
                {
                    "generated_by": "LanguageTool (open-source library)",
                    "rule_name": source,
                    "rule_file": "services/grammar_service.py",
                    "rule_function": "check_grammar (wrapper around LanguageTool.check)",
                    "evidence": f.get("text"),
                    "char_start": f.get("start"),
                    "char_end": f.get("end"),
                    "sentence": next(
                        (s for s in sentences if s["number"] == f.get("sentence_number")), None
                    ),
                    "token_indices": _tokens_in_span(tokens, f.get("start") or 0, f.get("end") or 0)
                    if isinstance(f.get("start"), int)
                    else [],
                    "reason": f.get("reason"),
                    "decision": "SUGGESTION",
                }
            )
        elif source == TOPIC_SOURCE:
            tctx = topic_ctx or {}
            cls = ((tctx.get("topic_analysis") or {}).get("classification")) or {}
            cos = ((tctx.get("topic_analysis") or {}).get("cosine")) or {}
            sel = set((tctx.get("keywords") or {}).get("selected", []))
            kw_token_indices = [
                t["index"] for t in tokens if (t.get("lemma") or "").lower() in sel
            ]
            chain.update(
                {
                    "generated_by": "TOPIC_CLASSIFIER (services/similarity.py :: classify)",
                    "rule_name": f"Topic relevance {cls.get('classification', '')}",
                    "rule_file": "services/similarity.py",
                    "rule_function": "classify <- cosine_similarity <- vectorize",
                    "evidence": f.get("text"),
                    "char_start": f.get("start"),
                    "char_end": f.get("end"),
                    "sentence": None,
                    "token_indices": kw_token_indices,
                    "reason": f.get("reason"),
                    "decision": cls.get("classification"),
                    "topic_chain": {
                        "classification": cls.get("classification"),
                        "comparison": cls.get("comparison"),
                        "similarity": cls.get("similarity"),
                        "cosine_library_result": cos.get("library_result"),
                        "cosine_manual_result": cos.get("manual_result"),
                        "keyword_source": "services/keywords.py :: extract_candidates",
                        "wordnet_source": "services/wordnet_service.py :: analyze_terms",
                        "tfidf_source": "services/similarity.py :: vectorize",
                    },
                }
            )
        else:
            chain.update(
                {
                    "generated_by": source or "input-validation",
                    "rule_name": f.get("title"),
                    "rule_file": "routes/analysis_routes.py",
                    "rule_function": "analyze",
                    "evidence": f.get("text"),
                    "char_start": f.get("start"),
                    "char_end": f.get("end"),
                    "sentence": None,
                    "token_indices": [],
                    "reason": f.get("reason"),
                    "decision": "NOTICE",
                }
            )
        chains.append(chain)
    return chains


def token_detail(tokens: list[dict], index: int, sentences: list[dict], raw_text: str, spacy_model: str) -> dict | None:
    """Word-level traceability record for one token (testable)."""
    tok = next((t for t in tokens if t["index"] == index), None)
    if tok is None:
        return None
    sent = next((s for s in sentences if s["number"] == tok.get("sentence")), None)
    return {
        "index": tok["index"],
        "surface": tok["text"],
        "char_start": tok["start"],
        "char_end": tok["end"],
        "sentence": sent,
        "sentence_text_location": sent["text"] if sent else None,
        "lemma": tok["lemma"],
        "pos": tok["pos"],
        "tag": tok.get("tag"),
        "dependency": tok.get("dep"),
        "is_stopword": tok.get("is_stopword"),
        "is_punctuation": tok.get("is_punctuation"),
        "is_alpha": tok.get("is_alpha"),
        "produced_by": f"spaCy ({spacy_model})",
        "processed_in": "services/nlp_service.py :: analyze_text",
    }
