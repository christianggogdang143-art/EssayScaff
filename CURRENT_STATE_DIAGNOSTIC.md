# EssayScaff — Current-State Diagnostic (2026-10-11)

> The audit below is preserved as written. It describes the state **before**
> the Writing Lab implementation. A dated addendum (§10) records what has
> changed since. Old bug reports are history, not retractions.

Read-only audit; no behavior was changed to produce this document.
Baseline: `pytest` **400 passed**; VR-2 rules `8ac38bf3…`, config `401f3a4b…`, problems `[]`.
Repo state: `master` branch, **zero commits** (no git history — deletions are unrecoverable except via backups).

## 1. Startup & architecture

- `python app.py` → `create_app()` (`app.py:27`): sets 5 MB body cap, registers `api_bp` + `validation_bp`,
  runs `init_db()` (15 tables + generic column migration + interaction-stage nullability migration),
  prewarms LanguageTool on a daemon thread. Routes: `GET /` (student), `GET /research/validation`.
- Thin-route design holds: `routes/analysis_routes.py` validates and delegates to `services/*`;
  `routes/validation_routes.py` fronts the 14-file `services/validation/` framework.
- Request flow: validate → stage service (NLP + rules + prompts + readiness, timed) → append revision →
  transparency payload → `log_stage_completion`. Stage-link gates enforced per linked call (403 otherwise);
  unlinked calls are an intentional, documented research path (route header overstates this as "never bypass" —
  direct unlinked POSTs bypass gates by design).

## 2. NLP pipeline (attribution)

- **Ours:** conservative normalization (NFC + newline unification); keyword formula
  `freq_weight·ln(1+freq) + POS + dist·(sents/total)`; 2-doc corpus prep; prompt templating with slot provenance;
  readiness conditions; all stage rules (PREWRITE_001–008, THESIS_003–010, OUTLINE_001–012, REFLECT_001–013);
  feedback assembly; backtraces; aggregates.
- **spaCy (`en_core_web_sm`):** sentences, tokens (+lemma/POS/tag/dep/offsets/stopword). Parsed text is
  newline-unified, so the "offsets into original text" docstring is inexact for `\r\n` input (grammar_service
  remaps; nothing else does).
- **NLTK WordNet:** synset lookup + documented filters; DIRECT/LEMMA/WORDNET/NO_MATCH; never fed into TF-IDF.
- **scikit-learn:** TF-IDF (`IDF=ln((1+N)/(1+DF))+1`), cosine with independent manual MATCH verification,
  WEAK/MODERATE/STRONG bands (labeled pending-empirical-validation).
- **LanguageTool:** lazy singleton + daemon prewarm (double-init race possible); advisory only, never blocks.
- Generic detectors: THESIS_001 (candidate), THESIS_002 (meta, ISSUE), STYLE_001/002, MECHANICS_001/002.

## 3. Stages, revisions, linking

- Each stage: `analyze_*` → `analysis_service.analyze` → components/rules/prompts/readiness/comparison →
  `UNIQUE(session, revision)` + `MAX()+1` numbering with 5-collision-retry → transparency gears.
- Continue buttons carry real parent session IDs (Stage 1→2→3→4→Lab incl. topic/keywords); manual link +
  direct-tab research paths preserved; parent-mismatch resets in-memory session (no rows touched);
  refresh restores link values only. Verified end-to-end in Chrome.
- Readiness decisions: DEVELOPING / NEARLY READY / READY_* (stages 1–3); REFLECTING / REVISION_RECOMMENDED /
  READY_FOR_INDEPENDENT_REVIEW / COMPLETE (stage 4). Gates: `stage2/3/4_allowed`, `reflection_complete`.
- **READY-vs-feedback semantics (reported, not changed):** READY requires only its C-conditions, so a READY
  decision can coexist with TRIGGERED non-blocking prompts (e.g. PREWRITE_003/004/005 at Stage 1). This is the
  designed blocking-vs-advisory split (only critical scaffold issues block), but the student UI can show
  "Ready for thesis formulation" above a HIGH-priority card — potentially unclear. Blocking rules are listed
  in each readiness payload (`blocking_rules`/`blocking`).

## 4. Writing Lab (honest scope)

- Introduction/Body/Conclusion select is **validated, stored, and echoed — detection does not branch on it**.
  There is no section-specific detector, no section gate, no canonical essay record, no essay-complete state.
- What exists: debounced live analysis, one primary card, per-mode starter guidance, topic/keyword carryover
  **only** via the Stage-4 button (direct-tab lab keeps manual fields by design), stale-clear on typing.
- A "Writing Process Summary" was deferred and does not exist.

## 5. Progressive feedback & dashboard (presentation only)

- One primary card (backend priority order; resolving surfaces next via existing fading). History stays in
  Revisions/Progress/Transparency; backend stores everything.
- Dashboard sections all trace to live data: static per-stage goal/next copy; "Why am I seeing this?"
  (labels + student_why/why_shown/reason — no rule IDs/paths/vectors, neutral priority sentence otherwise);
  What's Working ≤3 with `data-ev` (C-PASS, OBSERVED 006/008, INACTIVE 004/005/007, alignment
  ALIGNED/PARTIALLY, topic MODERATE/STRONG, THESIS_001 CANDIDATE, ≥2 sentences); checklist ≤5 from real
  conditions (✓/○/!, FAILs first, no raw C-ids); snapshot (alpha-token words, sentence count, revision or
  "live", analytics mm:ss or "—", topic + not-a-grade note); Previous (revision sum + lab count) → Revisions.
- Deliberate omissions: outline "abrupt shift" praise (no grounding rule found); lab section-length praise
  replaced by a descriptive sentence count.

## 6. Highlighting

- Marks render **only the primary item's** integer `[start,end)` spans from the live response (1:1
  mark↔visible-card coherence); partial overlaps split at boundaries; no invented text.
- Colors encode severity/type only (warning amber, info blue, mechanics slate) with a visible legend.
- Overlay: transparent textarea over metrics-identical backdrop; real clicks hit-test to the textarea and are
  forwarded via `elementFromPoint` (textarea briefly removed from hit-testing, same task); selection drags
  excluded; scroll synced; textarea input/stage-change clears marks; render refused on text mismatch.
- **Known risks (not fixed here):** backend offsets count Python code points while JS slices UTF-16 units —
  emojiastral-plane characters after position 0 will drift highlights; NFC-decomposed input can drift similarly.
  `markAtPoint` restore runs in a separate try but a throw between set/restore would leave the editor
  unclickable until reload (no such path observed). Flash timing (1200 ms) is presentation-only.

## 7. Transparency, analytics, validation

- Transparency Mode complete: 16-step pipeline, token/rule/keyword/WordNet/topic/LT/trace/log panes, source
  viewer (28-file whitelist), historical run loading. Doc mismatches found (not changed): `db.py` "One table
  is enough" (15 tables exist); transparency "INSERT OR REPLACE" (plain INSERT + fresh-ID retry);
  route header "can never bypass" (unlinked path exists); outline hardcoded `n<2` message vs
  `OUTLINE_MIN_POINTS`; health `"phase":"1B"` (pipeline is newer).
- Analytics: 14 event types; `stage` nullable only for APP_OPENED/SESSION_ENDED (strict, tested); intervals
  idempotent; aggregates count-only. Limitation: overlapping intervals sum naively (dedup covers identical
  replays only). Production DB holds 854 events (27 null-stage APP_OPENED/SESSION_ENDED rows by design),
  178 intervals, zero orphan parent links (s2→s1, s3→s2 all resolve).
- Validation: framework complete (datasets→annotate→adjudicate→freeze→run→metrics/reporting/provenance);
  **formal state: 2 DRAFT datasets, 0 samples, 0 runs** — validation has not started. VR-2 pins verified.

## 8. Tests & dependencies

- 400 pytest (27 files: unit/integration/jsdom-frontend/validation/analytics/cross-stage, incl. 61 runtime
  flows driving shipped JS + real payloads, XSS suite, concurrency, hardening, terminology guards). No CI
  config, no pytest.ini/tox. Baseline recorded pre-cleanup: 400 passed.
- Deps (`requirements.txt`): Flask, spaCy (+ `en_core_web_sm` model), scikit-learn, language-tool-python
  (+Java), NLTK (+wordnet corpora), pytest, requests. `requests` has no direct import (transitive via
  language-tool-python) — documented, left untouched. No NLTK-download step in code (corpora expected in env).
- Security posture: `esc()` on all HTML sinks + XSS suite; no `eval`/`document.write`; no localStorage;
  sessionStorage keys namespaced with private-mode guards; 5 MB body cap (Flask-level abort bypasses the
  JSON envelope — cosmetic); validation API unauthenticated (local-research-tool assumption, documented).

## 9. Debt & unfinished work (ranked in final report §14–15/§21)

## 10. Addendum — Writing Lab implementation (2026-10-11, verified, uncommitted at time of writing)

Baseline at addendum time: `pytest` **430 passed**; frontend harness
**68/68**; `node --check` clean on all production JS; VR-2
`verify_vr2_freeze()` clean (`rules_match: True`, `config_match: True`,
problems `[]`). Branch `main` now has history (`8808f69` + this work).

### 10.1 Resolved since the audit above

- **§4 (Writing Lab scope):** superseded. Section selection now drives
  section-specific LAB_* detectors (`services/lab_rules.py`), section
  gates, a canonical essay record (`writing_lab_sessions` +
  `essay_revisions`), per-section READY states, a Final Review assembly,
  and a Writing Process Summary with an Overall Status block. Details in
  `CURRENT_ARCHITECTURE.md` §8.
- **§6 (highlight offset risks):** fixed. `static/js/highlight.js` maps
  backend code-point offsets to UTF-16 units, so emoji/astral-plane
  characters can never drift later marks; two-way mark↔card navigation;
  typing/stage-change clears stale marks; render refused on text
  mismatch. Covered by `hl_*` harness flows and confirmed in live Chrome
  (mark→card, card→mark, typing clears, emoji analysis clean).
- **§7 (analytics overlap):** fixed. Aggregates merge overlapping
  intervals (`_union_active_ms`, overlap-adjusted); identical replays
  still deduped. `processing_ms` is never used as writing time
  (snapshot shows analytics active time or "—").
- **Validation API:** researcher routes accept an optional
  `X-Research-Token` for non-localhost deployments (401 when configured
  and absent); student/analysis routes never gated. Formal state
  unchanged and honestly reported: **2 DRAFT datasets, 0 samples,
  0 runs** (read directly from `essayscaff.db`, 2026-10-11).
- **Migration safety:** interaction-events migration copies the legacy
  table to `interaction_events_backup` and restores (not rebuilds) on
  failure. LanguageTool singleton init is lock-guarded.
- **Two bugs found and fixed during verification** (both covered by
  harness flows and confirmed in live Chrome on 2026-10-11, 78/78 E2E
  checkpoints on a fresh part-time-work chain):
  1. A pending debounce could auto-analyze server-restored draft text
     right after the student cleared the box, clobbering starter
     guidance. Server fills now cancel pending debounce timers;
     restored drafts never auto-analyze.
  2. The Process Summary omitted the overall status. It now renders an
     Overall Status block with the exact backend decision +
     student message.

### 10.2 Still true (unchanged limits)

- No generative LLM; student is sole author of every essay word —
  assembly uses only latest stored section revisions, nothing from
  planning artifacts, no transitions generated.
- LAB_* rules are experimental and outside VR-2; all thresholds are
  development values (`DATA_MODE_DEFAULT = "development"`); no accuracy,
  grade, coherence, clarity, or factual-correctness claims anywhere.
- `READY FOR INDEPENDENT REVIEW` means only: three sections exist, each
  meets its blocking conditions, no active blocking lab condition
  remains. Never excellent/accurate/persuasive/teacher-approved.
- Stage 1–4 detectors, readiness, and VR-2 pins untouched by lab work.

### 10.3 Debt carried forward

- LAB_* thresholds await formal empirical validation (human-dependent,
  not started).
- No consent workflow in the software; approvals for real student data
  stay the researcher's responsibility (unchanged).
- jsdom harness is not a layout/paint engine (documented in
  `tests/frontend_smoke/smoke.js`); live-browser verification remains
  the complement, recorded in the release report.
