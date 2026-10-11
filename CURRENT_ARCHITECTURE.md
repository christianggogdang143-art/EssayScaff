# EssayScaff — Current Implementation Source-of-Truth Architecture

> This document describes what the application **actually does**, verified
> against the current source in `C:\Users\My Pc\Desktop\SeApp`.
> **Code is the source of truth.** Where any other document disagrees with
> this file, verify against source before trusting either.
>
> One-line description: **EssayScaff is a lightweight NLP-supported,
> rule-based writing scaffolding system.** It uses NLP libraries and
> deterministic rules. It does **not** use a generative language model to
> write or rewrite student text.

## 0. Stage vocabulary (canonical)

Application scaffold stages (navigation + methodology):

- **Stage 1 — Idea Generation / Pre-Writing** (short nav: **Idea**)
- **Stage 2 — Thesis Formulation** (short nav: **Thesis**)
- **Stage 3 — Outline Development** (short nav: **Outline**)
- **Stage 4 — Reflection and Revision** (short nav: **Reflection**)

**Important distinction:** Introduction, Body, and Conclusion describe
**essay structure**, not application navigation. They are worked as
essay sections in the Writing Lab (§8, with section-specific LAB_*
rules); the Stage 4 conclusion draft is stored student data used only
as a planning artifact, never analyzed as an essay section. The API
`stage` tag (`config.py:8`, values `introduction`/`body`/`conclusion`)
labels which part of the student's essay a Writing Lab text comes from.
Do not confuse the two.

## 1. Frontend — `templates/`, `static/js/`, `static/css/`

- Student workspace (`templates/index.html`): stage tab sections
  (Idea / Thesis / Outline / Reflection / Writing Lab / Review), editors, Analyze
  buttons, Continue buttons (disabled until the backend readiness flag
  allows), sidebar (Feedback / Concepts / Progress / Reflection /
  Revisions in Student Mode; Pipeline / Tokens / NLP / Rules / Source /
  Timing in Transparency Mode).
- Writing Lab client (`static/js/live_feedback.js`): per-section draft
  buffers (introduction/body/conclusion; switching stashes/restores, memory
  first, then the server's latest saved revision, else empty), debounced
  analysis (`DEBOUNCE_MS = 2000`, `config.py:15`, server value via
  `/api/config`), `POST /api/lab/analyze`, section progression gates
  (`labToBody`/`labToConc`/`labToReview`, display only — readiness is
  server-computed), Final Review assembly + Writing Process Summary
  (`GET /api/lab/session/<id>`, `.../summary`; includes the Overall Status
  block with the exact backend decision + student message). Restored
  server drafts are programmatic fills: they cancel any pending debounce
  timer, so restored text is **never** auto-analyzed — analysis runs only
  from real typing pauses or explicit Analyze clicks.
- Stage clients (`static/js/stage1-4.js`): click-driven analyses,
  revision histories, Continue navigation, optional upstream session links;
  Stage 4 offers `labBtn` ("Start Writing My Essay") only at
  `READY_FOR_INDEPENDENT_REVIEW`/`COMPLETE`, carrying topic/keywords/chain
  into the lab (values only — never essay drafts).
- Copy Full Analysis (`static/js/walkthrough.js`, `#copyAnalysisBtn`):
  Markdown export of the active analysis (Transparency Mode only),
  assembled from stored response data, never generated prose.
- Transparency renderer (`static/js/transparency.js`): pipeline gears,
  token drill-down, keyword/WordNet/topic/LT tabs, rule backtraces,
  read-only source viewer.
- Walkthrough renderer (`static/js/walkthrough.js`): full scrollable
  analysis walkthrough below the workspace, Transparency Mode only,
  rendering **only** values from the live analysis response.
- Shell (`static/js/shell.js`): tab switching, pills, counters, refresh
  restore (active tab + Stage-4 link fields only, never drafts).
  Workspace sections: `stage1Section`, `stage2Section`, `stage3Section`,
  `stage4Section`, `studentSection` (Writing Lab), `reviewSection`
  (Final Review + Process Summary).
- Progressive student feedback (`static/js/feedback_focus.js`): one
  primary card for the current task, per-section starter guidance while a
  lab editor is empty, lab section checklists (`LAB_CHECKLISTS`, same
  marker policy as stages, capped at 5 rows), goal/next/checklist/
  snapshot dashboard — all presentation-only, all traceable to live data.
- Highlight layer (`static/js/highlight.js`): marks render **only the
  primary item's** integer `[start,end)` spans from the live response.
  Backend offsets count Python code points; the frontend converts through
  a code-point map so astral-plane characters (emoji) can never drift
  later marks. Two-way navigation (click mark → card, click card → mark),
  typing or stage-change clears stale marks immediately, render refused on
  text mismatch. Nothing is ever invented.
- No generative AI, no embeddings, no browser-executed NLP.

## 2. Flask routes — `app.py`, `routes/`

- `app.py`: `create_app()` registers `api_bp` (student/transparency)
  and `validation_bp` (researcher-only); serves `/` and
  `/research/validation`; LanguageTool prewarms on a daemon thread.
- `routes/analysis_routes.py`: `POST /api/analyze` (+ history GET),
  `POST /api/stage1-3/analyze`, `POST /api/stage4/reflect`, session
  history GETs, `POST /api/lab/analyze` (section + chain + optional
  `lab_session_id`), `GET /api/lab/session/<id>` (assembled essay map +
  per-section status), `GET /api/lab/session/<id>/summary` (process
  summary payload), `GET /api/source` (exact-match whitelist, traversal
  denied), `/api/health`, `/api/config`. Server-side stage gates return
  **403** for ineligible linked sessions; unlinked calls are the explicit
  direct/research path (`LINK_POLICY`, `services/stage2.py:27-32`).
- `routes/validation_routes.py`: dataset/sample/annotation/freeze/run/
  error-analysis/export endpoints. Researcher area only — never a fifth
  student stage. Optional researcher token for non-localhost deployments
  (`X-Research-Token` → 401 when configured and absent); student/analysis
  routes are never gated by it.

## 3. Analysis orchestration — `services/analysis_service.py :: analyze`

Fixed order per call: clock/events → `nlp_service.analyze_text` (single
spaCy parse, reused downstream) → `rule_engine.run_all_rules` →
`grammar_service.check_grammar` (LanguageTool singleton behind a
threading init lock; daemon prewarm from `app.py` never blocks boot;
advisory only, never blocks) → `keywords.extract_candidates` (always)
→ if topic/keywords: query terms + `wordnet_service.analyze_terms` +
`similarity.analyze_topic` (build_corpus → vectorize → cosine →
classify), else recorded skip → `feedback_service.build_feedback` →
summary/timings assembly → transparency assembly →
`db.save_run` (plain INSERT, fresh-ID retry) → transparency patched with
measured `db_ms`. Returns `{analysis_id, created_at, summary, feedback,
technical, transparency}`.

## 4. NLP layer — `services/nlp_service.py` (calls spaCy)

- Model `en_core_web_sm` (`config.py:18`), lazy singleton.
- Normalization: Unicode NFC + CRLF/CR→LF only. No lowercase, no
  punctuation stripping, no whitespace collapse.
- Sentences `{number, text, start, end}`; tokens `{index, text, lemma,
  pos, tag, dep, is_stopword, is_punctuation, is_alpha, sentence,
  start, end}`. Offsets index the newline-unified text.
- **Stopword identification and selective filtering** (not removal):
  spaCy flags `is_stop`; tokens stay in the stream; only selected
  downstream operations filter (keyword all-stopword rejection,
  topic-term grouping). Teacher keywords skip stopword checks.
- Segmentation/lemmas/POS/deps/stop decisions are **spaCy library
  behavior**; EssayScaff owns normalization, offset mapping, numbering,
  and all downstream use.

## 5. Lexical/topic layer

- **EssayScaff keyword ranking** (`services/keywords.py`,
  ESSAYSCAFF CODE — not TF-IDF):
  `score = 1.0·ln(1+freq) + POS_W[pos] + 1.0·(sentences_with_term /
  n_sentences)`, POS weights NOUN/PROPN 2.0, ADJ 1.5, VERB 1.0, top-15,
  deterministic score-desc/lemma-asc order, per-term `score_parts`
  exposed. Candidate filter: content POS, lemma length ≥ 3, not a light
  verb (`be/have/do`), not all-stopword.
- **WordNet lexical evidence** (`services/wordnet_service.py` + NLTK
  data): synset lookup (POS-first, fallback), synonym lemmas, recorded
  definitions; filters F1–F6; cap 20 per term; match priority
  DIRECT > LEMMA > WORDNET > NO_MATCH. Feeds feedback lists and the
  Stage-2 support composite. **Never enters the TF-IDF corpus.**
  Provides lexical relationships, not deep semantic understanding.
- **Teacher-guided concept provider**
  (`services/knowledge_base/interface.py`,
  `TeacherConceptProvider`): assignment topic + teacher keywords +
  WordNet expansion. **This is not a large academic knowledge database**
  — no curated domain knowledge base exists in the system.
- **scikit-learn TF-IDF** (`services/similarity.py`, EXTERNAL MATH):
  exactly-2-document corpus (`topic_doc` = topic + keywords,
  lemmatized; `student_doc` = essay, lemmatized identically),
  `TfidfVectorizer` with effective params recorded per call
  (`smooth_idf=True`, L2 norm, unigram, `min_df=1`).
- **Cosine similarity** (EXTERNAL primary + ESSAYSCAFF manual check):
  library result vs independent dot/norm recomputation, tolerance
  1e-9, zero-vector defined as 0.0 with note. Topic-vector similarity,
  never an essay grade.
- **Topic classification** (ESSAYSCAFF CONFIG): WEAK < 0.30 ≤
  MODERATE < 0.60 ≤ STRONG. Configurable development thresholds,
  **pending formal empirical validation** — never validated scores.

## 6. Rule layer — `rules/`

Fixed-order engine (`rules/rule_engine.py`): THESIS_002 (6
case-insensitive meta regexes) → THESIS_001 (declarative + subject +
finite verb + no-meta + ≥6 alpha tokens) → STYLE_001 (passive
dependencies) → STYLE_002 (≥3 repeated 2-word openings) →
MECHANICS_001 (fragment signals) → MECHANICS_002 (run-on signals).
Each result carries rule_id, status, severity, sentence, evidence,
offsets, reason. The engine never gates progression; readiness
functions do. All detectors are heuristic and honestly labeled
(`severity`, `POSSIBLE`/`HEURISTIC` wording where approximate).

## 7. Stage layer — `services/prewriting.py`, `thesis.py`, `outline.py`, `reflection.py`, `stage1-4.py`

- **Stage 1:** PREWRITE_001–008 over token/concept/topic evidence;
  readiness C1–C4 → DEVELOPING / NEARLY READY /
  `READY FOR THESIS FORMULATION` (+ `stage2_allowed`); contextual
  prompt templates fill slots **only** from provenanced topic/keywords/
  student concepts, else generic fallback. Nothing generates prose.
- **Stage 2:** reuses THESIS_001/002 unchanged + THESIS_003–010
  (broad/claim/overload/topic-weak/factual/competing/vague/focused)
  over extracted components (subject, finite verbs, stance/vague
  markers); Stage-1 alignment is keyword-overlap bands, **advisory
  only**; readiness C1–C7 → `READY FOR OUTLINE DEVELOPMENT`
  (+ `stage3_allowed`).
- **Stage 3:** 12 OUTLINE rules over thesis↔point and point↔detail
  alignments (direct-match counts, WordNet hits, cosine bands),
  unity (COHESIVE/MIXED/POSSIBLY OFF-TOPIC/NO SUPPORT),
  duplication (Jaccard/cosine), progression cues, coverage ≥ 0.5;
  readiness C1–C8 → `READY FOR REFLECTION & REVISION`
  (+ `stage4_allowed`). Unity/alignment statuses are **rule-based
  structural indicators**, not deep semantic judgments.
- **Stage 4:** REFLECT_001–013 over stored histories only (**no NLP
  rerun** — no nlp/grammar/analysis imports); history classes
  active/new/recurring/regressions/resolved/stable; scaffold fading
  HIGH (critical≥1 or recurring-major≥2 or major-regression≥1) /
  INDEPENDENT (no major + stable≥1 + revisions≥3) / LIGHT (no major)
  / MODERATE otherwise; prompt budgets 3/2/1/1; reversible on new
  evidence; readiness up to COMPLETE.

## 8. Writing Lab — `services/lab.py`, `services/lab_rules.py`, `config.py` LAB_*

Canonical essay sessions. `POST /api/lab/analyze` runs the student's
section text through the **unchanged** `analysis_service.analyze`, then
evaluates section rules and stores the exact student text as an
append-only revision. Chain links are immutable after session creation:
presenting different non-null parent ids mints a NEW session (stale
chains are never silently re-linked); provided-but-unknown parent ids
raise (no dangling links). Stage histories are only read
(latest thesis keywords, latest outline points) — Stage 1–4 machinery
is called, never modified, and lab code paths are excluded from the
VR-2 freeze check.

- **Introduction rules** (`LAB_INTRO_001–004`): minimum 20 alpha tokens
  (`LAB_INTRO_MIN_TOKENS`), topic connection not WEAK (lexical cosine
  band), central-claim candidate present, no blocking meta/fragment/
  run-on. Readiness I1–I4 → `READY FOR BODY`.
- **Body rules** (`LAB_BODY_001–004`): minimum 30 alpha tokens,
  main-claim candidate present, thesis overlap and best-outline-point
  overlap bands (`LAB_BODY_ALIGN_LOW = 0.25`,
  `LAB_BODY_ALIGN_HIGH = 0.50`; WEAKLY ALIGNED blocks). Readiness B1–B3
  → `READY FOR CONCLUSION`.
- **Conclusion rules** (`LAB_CONC_001–004`): minimum 15 alpha tokens,
  lexical return to the thesis/topic (blocking unless nothing is linked),
  plus two advisory-only guards: all-concepts-novel
  (`LAB_CONC_003`, fires only when every conclusion concept is new and
  there are at least `LAB_CONC_NOVEL_MIN_CONCEPTS = 3`) and
  fragment/run-on (`LAB_CONC_004`). Readiness C1–C2
  → `READY FOR FINAL REVIEW`.
- Every rule declares `blocking` explicitly; LanguageTool mechanics
  notes never block. All LAB_* rules are **EXPERIMENTAL and outside
  VR-2**; thresholds are development values (`config.py:294-304`,
  `DATA_MODE_DEFAULT = "development"`, overridable via
  `ESSAYSCAFF_DATA_MODE`), pending formal empirical validation.
- Final Review (`GET .../summary`): `student_essay` assembles ONLY the
  latest stored revision per section — no idea/thesis/outline/
  reflection text is inserted, no transitions generated. The student is
  the sole author of every essay word.

### Lab status vocabulary (exact backend semantics)

- **BLOCKING**: the visible card's source rule is in the readiness
  `blocking_rules` set. The student must resolve it to continue. Badge
  shows the word "Blocking" only — never a rule id.
- **ADVISORY**: the gate is open (`stageN_allowed` / section READY), so
  the card is optional polish. Shown only when true — otherwise no
  badge rather than a misleading one.
- **READY TO CONTINUE** (lab gate line): the current section's decision
  is its READY value; the next-section button is enabled.
- **REVISION NEEDED**: a section decision is not its READY value, or
  the essay has missing/not-ready sections.
- **READY FOR INDEPENDENT REVIEW** (`services/lab.py:32,161-178`):
  all three sections exist and each meets its blocking conditions
  (`READY FOR BODY` + `READY FOR CONCLUSION` + `READY FOR FINAL
  REVIEW`, no active blocking lab condition). It means ONLY that —
  never "excellent", "accurate", "persuasive", "high-quality", or
  "teacher-approved". Student message: "Your essay has no unresolved
  blocking scaffold issues. Review the full essay using your own
  judgment before submitting."
- **Writing Process Summary**: Overall Status (exact backend decision +
  student message), assignment topic/keywords, planning journey
  (final idea/thesis/outline/reflection, read-only), per-stage and
  per-section process status, snapshot (active time, revision counts,
  timestamps), feedback counts, revision timeline. No percentages, no
  quality/coherence/clarity scores, no accuracy claims.

## 9. Persistence — `services/db.py` → SQLite

`analysis_runs` + `stage1-4_revisions` (+ 8 `validation_*` tables) +
`writing_lab_sessions` + `essay_revisions` (one row per analyzed lab
draft: `UNIQUE(lab_session_id, section, revision_number)`, append-only;
re-analyzing unchanged text reuses the revision — a restore never mints
a fake new revision).
Append-only INSERTs with `UNIQUE(session_id, revision_number)` and
`MAX()+1` numbering; readers return full oldest-first histories;
latest = last element. Old evidence is preserved per revision. Only
UPDATEs in the system: same-run transparency timing patch and
validation status transitions. No student-identity tables (privacy by
absence).
Crash-safe migration: additive-only (new columns/tables, never
rewrites); the interaction-events nullability migration copies the
legacy table to `interaction_events_backup` first and restores (not
rebuilds) on failure, so original rows always survive.

## 10. Transparency — `services/transparency.py`, `source_view.py`, frontend tabs + walkthrough

16 phase pipeline gears + 5/7/11/8 stage gears, each with
input/process/output/timing/source/next. Feedback backtraces link
feedback → rule file/function → evidence chars → sentence → tokens →
raw text (`UNRESOLVED` when unmatched — never borrowed). Source viewer:
28-key exact whitelist, traversal/absolute/`.env`/DB denial,
`inspect`-based live source. Timings measured via `perf_counter`;
unmeasured gears report `timing_ms: null` +
`NOT_MEASURED_SEPARATELY`, never fake 0 ms. The walkthrough
(`walkthrough.js`) reorganizes the same response data into 20
scrollable steps with per-step source badges
(SPACY / SCIKIT-LEARN / WORDNET / LANGUAGETOOL / ESSAYSCAFF LOGIC /
DATABASE / ESSAYSCAFF CONFIG), visible only in Transparency Mode.

## 11. Validation — `services/validation/`, `routes/validation_routes.py`

Pilot scope: THESIS_002 (binary META/NOT_META) and TOPIC_CLASSIFIER
(multiclass WEAK/MODERATE/STRONG) vs frozen VR-2 production adapters
(same functions students use; duplication forbidden by test).
Lifecycle: empty DRAFT → samples/strict-CSV → ANNOTATING (blinded:
prediction fields structurally absent) → quality/duplicates/freeze
preview → sha256 freeze → pinned-hash-enforced immutable runs
(`VR2_FREEZE_DRIFT_DETECTED` → 409) → raw-first confusion matrices →
UNDEFINED-safe metrics (accuracy/precision/recall/specificity/F1;
per-class/macro/weighted; human-only kappa gating) → categorized
error notes (document-only) → demo/formal-labeled exports. Pinned
hashes: rules `8ac38bf3…e42c`, config `401f3a4b…5c915`. No SUS,
embeddings, LLMs, or overall essay scores — by design.

## ESSAYSCAFF CODE vs EXTERNAL LIBRARY BEHAVIOR

| ESSAYSCAFF CODE | EXTERNAL LIBRARY |
|---|---|
| Normalization, offset mapping, numbering | spaCy segmentation/tokens/lemmas/POS/deps/stop flags |
| Keyword formula + candidacy + ranking | NLTK WordNet synsets/definitions (data) |
| Corpus prep, vectorizer construction + provenance | scikit-learn TF-IDF math + cosine math |
| Thresholds, comparison strings | LanguageTool grammar match detection |
| All rules, readiness, gates, fading, prompts | AcaWriter taxonomy vocabulary (cited, naming only) |
| Persistence, transparency, validation, metrics | — (all EssayScaff) |

## What the system does NOT do (and does not claim)

No generative LLM; no essay grades or holistic clarity/coherence/tone
percentages (only rule-based indicators with PASS/FAIL/status labels);
no deep semantic understanding, entailment, truth checking, evidence
credibility checking, or argument-quality scoring (grammatically valid
nonsense may pass — stated in-app); topic similarity is lexical
(TF-IDF/cosine over lemmas + keyword/WordNet overlap), never a meaning
judgment; Writing Lab section rules (LAB_*) are experimental unless
formally validated; formal validation data is human-dependent and has
not started (2 DRAFT datasets, 0 samples, 0 runs — verified 2026-10-11);
no validated thresholds (all development values, labeled pending);
no curated academic knowledge base; no stopword deletion; no silent
history rewrites; no auto-written essay prose (student is sole author).

## 12. Research interaction analytics — `services/learning_analytics.py`, `static/js/analytics.js`

Append-only `interaction_events` + `stage_time_intervals` tables feed a
read-only aggregation service. No NLP rerun, no analysis mutation, no
predictions. Server-confirmed rows (ANALYSIS_COMPLETED, READINESS_CHANGED,
STAGE_UNLOCKED, `LAB_SECTION_READY`, `ESSAY_READY_FOR_REVIEW`,
`PROCESS_SUMMARY_VIEWED`, provenance `server`) vs client-reported rows
(provenance `client`); aggregates prefer server rows. Active time =
client-measured engaged milliseconds (visible tab + activity within
`ANALYTICS_IDLE_TIMEOUT_MS` = 300000, a development/research logging
parameter, not a validated threshold); idle/hidden/blurred gaps pause the
clock and are never counted. Overlapping intervals are merged
(`_union_active_ms`, overlap-adjusted — overlaps can never inflate
aggregates; `processing_ms` is never used as writing time). Interval
bounds are client-measured; server receipt timestamps are authoritative.
Pre-first-revision typing accrues in memory and is attributed once the
first response reveals the session id (lost on refresh by design). The
lab and review workspaces aggregate under stage key `lab`. All
frequencies are counts of stored conditions — never scores.

### Interaction-logging privacy: what is logged, why, what is not

LOGGED (why in parentheses): app open/close lifecycle, stage enter/leave
(session scope), analysis requested/completed (ids + revision),
feedback displayed (item counts only), readiness transitions and stage
unlocks (server-confirmed), continue clicks, reflection submits,
pause/resume episodes, closed active-time intervals (bounds + active ms).
WHY: time-on-task, stage progression, revision activity, feedback
interaction, reproducible research aggregates.
NOT LOGGED: keystroke content, essay text (lives only in revision
records; essay-text keys are rejected from event metadata), clipboard,
passwords, browsing history, activity outside this app. Analytics
endpoints expose only scoped, capped reads — no arbitrary queries.
No consent workflow exists in the software; do not claim consent was
collected. Required approvals for real student data remain the
researcher's responsibility outside this codebase.

## 13. Environment setup / reproducibility

Verified working environment (do not treat looser bounds as tested):

- Python 3.11 (developed/tested on 3.11.9) + `pip install -r requirements.txt`
  (Flask, spaCy, scikit-learn, language-tool-python, NLTK, pytest, requests).
- spaCy model: `python -m spacy download en_core_web_sm` (verified with 3.7.1
  against spaCy 3.7.5). No model download happens automatically at runtime.
- NLTK corpora: `wordnet` and `stopwords` (English) must be present for
  WordNet expansion and stopword filtering; absence degrades honestly to
  `unavailable`/skipped paths, never fabricated output.
- Java (verified with OpenJDK 21) for the local LanguageTool server, which
  `app.py` prewarms on a daemon thread; boot never blocks on it.
- Node.js (verified with v24) + `npm install jsdom` (test harness only,
  `tests/frontend_smoke/`) for the frontend runtime tests.
- SQLite ships with Python; no server database to configure.
- First boot creates `essayscaff.db` in the project root via `init_db()`;
  schema migration is additive-only (new columns/tables, never rewrites).
