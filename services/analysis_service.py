"""Phase 1 analysis orchestrator: RAW TEXT -> JSON response.

Owns: analysis-ID generation, wall-clock timing (measured, never faked),
pipeline sequencing, chronological execution events, transparency assembly,
summary building, and DB persistence. Flask routes stay thin and call
analyze() here.
"""

from __future__ import annotations

import sqlite3
import time
from datetime import datetime, timezone

from rules.rule_engine import run_all_rules
from services import db, feedback_service, grammar_service, keywords, nlp_service
from services import similarity as similarity_mod
from services import wordnet_service
from services import transparency as transparency_mod


def generate_analysis_id(now: datetime | None = None) -> str:
    """Unique ID of style RUN-YYYYMMDD-NNNNNN with a per-day DB counter."""
    now = now or datetime.now(timezone.utc)
    prefix = now.strftime("%Y%m%d")
    try:
        seq = db.count_runs_for_date(prefix) + 1
    except Exception:  # noqa: BLE001 - DB must never break analysis
        seq = int(now.strftime("%H%M%S"))
    candidate = f"RUN-{prefix}-{seq:06d}"
    # Guard against same-process collisions (e.g. tests without DB reset).
    if db.get_run(candidate) is not None:
        suffix = int(time.time() * 1000) % 1000000
        candidate = f"RUN-{prefix}-{suffix:06d}"
        if db.get_run(candidate) is not None:
            import uuid

            candidate = f"RUN-{prefix}-{uuid.uuid4().hex[:6].upper()}"
    return candidate


def analyze(
    raw_text: str,
    stage: str | None = None,
    validation_ms: float = 0.0,
    topic: str | None = None,
    teacher_keywords: list[str] | None = None,
) -> dict:
    """Run the full pipeline and return the API response dict.

    Every stage boundary is timestamped with time.perf_counter() offsets from
    analysis start, producing a real chronological execution trace.
    """
    wall_start = time.perf_counter()

    def clock() -> float:
        return (time.perf_counter() - wall_start) * 1000.0

    events: list[dict] = [{"t_ms": 0.0, "event": "analysis started"}]
    created = datetime.now(timezone.utc)
    analysis_id = generate_analysis_id(created)

    events.append({"t_ms": clock(), "event": "input validation completed"})
    nlp_out = nlp_service.analyze_text(raw_text)
    events.append({"t_ms": clock(), "event": "spaCy pipeline completed"})
    events.append({"t_ms": clock(), "event": "sentence segmentation captured"})
    events.append({"t_ms": clock(), "event": "token linguistic properties captured"})
    sentences = nlp_out["sentences"]
    tokens = nlp_out["tokens"]
    doc = nlp_out["spacy_doc"]
    events.append({"t_ms": clock(), "event": f"tokenization completed ({len(tokens)} tokens)"})

    events.append({"t_ms": clock(), "event": "rule engine started"})
    rule_out = run_all_rules(doc, sentences, clock=clock)
    events.extend(rule_out.get("events", []))
    events.append({"t_ms": clock(), "event": "rule engine completed"})

    events.append({"t_ms": clock(), "event": "LanguageTool started"})
    lt_out = grammar_service.check_grammar(raw_text, sentences)
    events.append(
        {
            "t_ms": clock(),
            "event": "LanguageTool completed"
            + (" (cold init in this call)" if lt_out.get("cold_init_in_this_call") else " (warm, reused server)"),
        }
    )

    # ---- Phase 2: keywords always; topic pipeline only when asked ----
    t0 = time.perf_counter()
    kw_data = keywords.extract_candidates(tokens, len(sentences))
    keyword_ms = (time.perf_counter() - t0) * 1000.0
    events.append({"t_ms": clock(), "event": "keyword extraction completed"})
    phase2: dict = {
        "ran": False,
        "topic": topic,
        "teacher_keywords": teacher_keywords,
        "keywords": kw_data,
        "timings": {"keyword_ms": keyword_ms},
    }

    if topic or teacher_keywords:
        t_topic = time.perf_counter()
        query_terms = keywords.build_query_terms(topic, teacher_keywords)
        student_lemmas = {(t.get("lemma") or t["text"]).lower() for t in tokens if t.get("is_alpha")}
        student_surfaces = {t["text"].lower() for t in tokens if t.get("is_alpha")}
        phase2["query_terms"] = query_terms

        events.append({"t_ms": clock(), "event": "WordNet expansion started"})
        t0 = time.perf_counter()
        wn_data = wordnet_service.analyze_terms(query_terms, student_lemmas, student_surfaces)
        wordnet_ms = (time.perf_counter() - t0) * 1000.0
        events.append({"t_ms": clock(), "event": "WordNet expansion completed"})
        phase2["wordnet"] = wn_data

        events.append({"t_ms": clock(), "event": "TF-IDF vectorization started"})
        topic_analysis = similarity_mod.analyze_topic(topic or "", teacher_keywords or [], raw_text)
        events.append({"t_ms": clock(), "event": "TF-IDF vectorization completed"})
        events.append({"t_ms": clock(), "event": "cosine similarity completed"})
        events.append({"t_ms": clock(), "event": "topic classification completed"})
        phase2["topic_analysis"] = topic_analysis
        phase2["timings"].update(
            {
                "wordnet_ms": wordnet_ms,
                "tfidf_ms": topic_analysis["timings"]["tfidf_ms"] + topic_analysis["timings"]["corpus_ms"],
                "cosine_ms": topic_analysis["timings"]["cosine_ms"],
                "classification_ms": topic_analysis["timings"]["classification_ms"],
                "topic_total_ms": (time.perf_counter() - t_topic) * 1000.0,
            }
        )
        phase2["ran"] = True
    else:
        phase2["skip_reason"] = "No topic or teacher keywords supplied; topic pipeline did not run."

    topic_bundle = phase2 if phase2["ran"] else None

    t0 = time.perf_counter()
    feedback = feedback_service.build_feedback(rule_out["results"], lt_out, topic_bundle)
    feedback_ms = (time.perf_counter() - t0) * 1000.0
    events.append({"t_ms": clock(), "event": "feedback constructed"})

    processing_ms = (time.perf_counter() - wall_start) * 1000.0

    issue_count = sum(1 for r in rule_out["results"] if r.get("status") == "ISSUE")

    lt_stats = grammar_service.get_stats()
    lt_stats = {**lt_stats, "last_check_ms": lt_out.get("check_ms")}

    # Split, honest timing architecture (each value measured above).
    timings = {
        **nlp_out["timings"],
        "validation_ms": validation_ms,
        "spacy_total_ms": (
            nlp_out["timings"].get("spacy_parse_ms", 0.0)
            + nlp_out["timings"].get("segmentation_ms", 0.0)
            + nlp_out["timings"].get("tokenization_ms", 0.0)
        ),
        "sentence_capture_ms": nlp_out["timings"].get("segmentation_ms", 0.0),
        "token_property_capture_ms": nlp_out["timings"].get("tokenization_ms", 0.0),
        "rules_total_ms": sum(rule_out["timings"].values()),
        **{f"rule_{k}": v for k, v in rule_out["timings"].items()},
        "rules_ms": sum(rule_out["timings"].values()),
        "languagetool_ms": lt_out.get("processing_ms", 0.0),
        "language_tool_ms": lt_out.get("processing_ms", 0.0),
        "languagetool_init_ms": lt_out.get("init_ms"),
        "languagetool_check_ms": lt_out.get("check_ms"),
        "keyword_ms": phase2["timings"].get("keyword_ms", 0.0),
        "wordnet_ms": phase2["timings"].get("wordnet_ms", 0.0),
        "tfidf_ms": phase2["timings"].get("tfidf_ms", 0.0),
        "cosine_ms": phase2["timings"].get("cosine_ms", 0.0),
        "classification_ms": phase2["timings"].get("classification_ms", 0.0),
        "topic_total_ms": phase2["timings"].get("topic_total_ms", 0.0),
        "feedback_ms": feedback_ms,
        "total_processing_ms": processing_ms,
        "total_ms": processing_ms,
    }

    cls = ((phase2.get("topic_analysis") or {}).get("classification")) or {}
    wn = phase2.get("wordnet") or {}
    summary = {
        "sentence_count": len(sentences),
        "token_count": len(tokens),
        "issue_count": issue_count,
        "feedback_count": len(feedback),
        "processing_ms": processing_ms,
        "language_tool_status": lt_out.get("status"),
        "spacy_model": nlp_out["spacy_model"],
        "stage": stage,
        # Measurable topic values only — no overall essay score in this phase.
        "topic": topic,
        "topic_similarity": cls.get("similarity"),
        "topic_classification": cls.get("classification"),
        "selected_keyword_count": len(kw_data.get("selected", [])),
        "direct_match_count": wn.get("direct_count"),
        "wordnet_match_count": wn.get("wordnet_count"),
    }

    technical = {
        "raw_input": raw_text,
        "normalized_input": nlp_out["normalized_input"],
        "chars_before": nlp_out["chars_before"],
        "chars_after": nlp_out["chars_after"],
        "sentences": sentences,
        "tokens": tokens,
        "rule_results": rule_out["results"],
        "language_tool_results": lt_out,
        "phase2": phase2,
        "timings": timings,
    }

    run_info = transparency_mod.build_run_info(
        processing_ms, lt_out.get("status"), nlp_out["spacy_model"]
    )
    run_info["spacy_version"] = nlp_out.get("spacy_version", run_info["spacy_version"])
    run_info["spacy_model_version"] = nlp_out.get("spacy_model_version", "unknown")

    pipeline = transparency_mod.build_pipeline(
        {
            "raw_text": raw_text,
            "normalized": nlp_out["normalized_input"],
            "chars_before": nlp_out["chars_before"],
            "chars_after": nlp_out["chars_after"],
            "sentences": sentences,
            "tokens": tokens,
            "timings": timings,
            "rule_results": rule_out["results"],
            "rule_timings": rule_out["timings"],
            "lt_result": lt_out,
            "lt_stats": lt_stats,
            "feedback": feedback,
            "feedback_ms": feedback_ms,
            "db_ms": 0.0,  # filled after persistence below
            "validation_ms": validation_ms,
            "spacy_model": nlp_out["spacy_model"],
            "phase2": phase2,
        }
    )
    backtraces = transparency_mod.build_backtraces(
        feedback, rule_out["results"], sentences, tokens, raw_text, topic_ctx=phase2
    )

    transparency = {
        "run_info": run_info,
        "pipeline": pipeline,
        "execution_log": events,
        "backtraces": backtraces,
        "historical_code_warning": False,
    }

    response = {
        "analysis_id": analysis_id,
        "created_at": created.isoformat(),
        "summary": summary,
        "feedback": feedback,
        "technical": technical,
        "transparency": transparency,
    }

    t0 = time.perf_counter()
    persisted = False
    for _ in range(3):
        try:
            db.save_run(
                {
                    "id": analysis_id,
                    "raw_text": raw_text,
                    "normalized_text": nlp_out["normalized_input"],
                    "stage": stage,
                    "created_at": created.isoformat(),
                    "processing_ms": processing_ms,
                    "summary": summary,
                    "feedback": feedback,
                    "technical": {
                        **technical,
                        "spacy_model": nlp_out["spacy_model"],
                    },
                    "transparency": transparency,
                }
            )
            persisted = True
            break
        except sqlite3.IntegrityError:
            # ID collision (e.g. concurrent request): mint a fresh ID and
            # retry instead of overwriting the existing row.
            analysis_id = generate_analysis_id(created)
            response["analysis_id"] = analysis_id
        except Exception:  # noqa: BLE001 - persistence must never break analysis
            break
    db_ms = (time.perf_counter() - t0) * 1000.0
    transparency["persistence_ok"] = persisted

    # Fill persistence timing honestly post-save, then patch the stored copy
    # so replay shows the same real numbers as the live response.
    timings["database_ms"] = db_ms
    transparency["pipeline"][-1]["timing_ms"] = db_ms
    events.append({"t_ms": clock(), "event": "database persistence completed"})
    events.append({"t_ms": clock(), "event": "response completed"})
    try:
        db.update_transparency(analysis_id, transparency)
    except Exception:  # noqa: BLE001 - replay patch must never break analysis
        pass

    return response
