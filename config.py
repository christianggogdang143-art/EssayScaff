# EssayScaff — Phase 1 configuration.
# Keep research-critical constants centralized and documented here.

# Maximum accepted input length (characters). Longer inputs get HTTP 413.
MAX_TEXT_CHARS = 20000

# Accepted essay-section labels (frontend select sends exactly these).
# These describe parts of the student's ESSAY STRUCTURE, not application
# navigation: EssayScaff's scaffold stages are Idea -> Thesis -> Outline
# -> Reflection (see CURRENT_ARCHITECTURE.md). Values unchanged.
STAGE_VALUES = {"introduction", "body", "conclusion"}

# Outline size guardrail: max supporting details per body point (DoS cap).
OUTLINE_MAX_DETAILS_PER_POINT = 20

# Live-feedback debounce delay (milliseconds). Single place to configure.
# Frontend reads this value from /api/config.
DEBOUNCE_MS = 2000

# --- Research interaction logging (development/research logging parameters,
# NOT classifier thresholds). These names are deliberately absent from
# services/validation/snapshot.py FROZEN_THRESHOLDS, so the VR-2 classifier
# snapshot hash can never change because of logging configuration.
# Inactivity longer than this pauses the active-time clock; the idle period
# itself is never counted as writing time.
ANALYTICS_IDLE_TIMEOUT_MS = 300000
# Client progress heartbeat: closed active-time intervals are flushed at
# least this often so ordinary navigation never loses much timing data.
ANALYTICS_FLUSH_MS = 60000
# Safety caps for analytics ingest (DoS guard, not pedagogy).
ANALYTICS_MAX_BATCH = 100
ANALYTICS_MAX_METADATA_CHARS = 2000

# spaCy model name. Professor must be able to see exactly which model ran.
SPACY_MODEL = "en_core_web_sm"

# LanguageTool language.
LANGUAGETOOL_LANG = "en-US"

# Local LanguageTool install directory (real jars, no re-download).
# language-tool-python 3.x looks for `LanguageTool-<hardcoded-version>` in its
# cache and re-downloads a 263 MB snapshot on EVERY new process when the folder
# name does not match its expectation. Pointing LTP_JAR_DIR_PATH at the actual
# installed directory avoids that and uses the genuine local backend.
# Resolved dynamically in services/grammar_service.py; None = auto-detect.
LANGUAGETOOL_JAR_DIR = None

# SQLite database file (relative to project root).
DATABASE_PATH = "essayscaff.db"
# Application version, recorded with each analysis for reproducibility.
# Phase 1A runs predate versioning and honestly report "not recorded".
APP_VERSION = "1.1.0"

# Validation ruleset version. VR-1 froze the pre-Stage-4 detectors when formal
# detector evaluation began. VR-2 adds the Stage 4 REFLECT rules below; all
# earlier detector logic and thresholds are byte-identical to VR-1.
# DO NOT change detector logic, thresholds, or boundaries under the same
# ruleset version: any later modification requires a NEW version + new
# evaluation. Weaknesses found during validation are REPORTED, not patched.
VALIDATION_RULESET_VERSION = "VR-2"

# ============================================================
# PHASE 6 STAGE 4 — reflection & adaptive fading (centralized).
# Scaffold levels are pedagogical (3 HIGH … 0 INDEPENDENT), never
# "AI confidence". A single resolved revision is IMPROVING, not STABLE:
# stability requires persistence across multiple revisions.
# ============================================================

# Recurring issue: active in the latest revision AND in at least this many
# earlier revisions of the same stage session.
STAGE4_RECURRING_MIN_PRIOR = 2
# Stable resolution: resolved (inactive) in the latest revision AND quiet
# for at least this many consecutive trailing revisions overall.
STAGE4_STABLE_MIN_QUIET = 2
# Minimum total cross-stage revisions examined before INDEPENDENT is allowed.
STAGE4_MIN_REVISIONS_FOR_INDEPENDENT = 3
# Recurring MAJOR issues at or above this count force HIGH support.
STAGE4_RECURRING_MAJOR_FOR_HIGH = 2
# Max reflection prompts shown at once (by scaffold level below).
STAGE4_MAX_PROMPTS_HIGH = 3
STAGE4_MAX_PROMPTS_MODERATE = 2
STAGE4_MAX_PROMPTS_LIGHT = 1
STAGE4_MAX_PROMPTS_INDEPENDENT = 1
# Optional student reflection note cap (stored, never analyzed).
STAGE4_NOTE_MAX_CHARS = 2000

# Repeated-opening rule threshold: minimum count to flag.
REPEATED_OPENING_THRESHOLD = 3

# Run-on rule: token-count / signal thresholds (documented, not magic).
RUNON_LONG_SENTENCE_TOKENS = 35
RUNON_MIN_TOKENS = 25

# ============================================================
# PHASE 2 — topic analysis (lexical overlap + TF-IDF/cosine evidence;
# centralized, documented). "Semantic" here means word-level matching
# only — there is no deep semantic or entailment model.
# ============================================================

# Assignment-topic input limits.
TOPIC_MAX_CHARS = 500
TEACHER_KEYWORDS_MAX = 50

# --- Keyword candidate filter ---
# Only these spaCy POS tags can become keyword candidates.
KEYWORD_CANDIDATE_POS = {"NOUN", "PROPN", "ADJ", "VERB"}
# Minimum lemma length for a candidate.
KEYWORD_MIN_LEMMA_LEN = 3
# Light verbs carry little topic meaning; excluded even when tagged VERB.
KEYWORD_EXCLUDED_LEMMAS = {"be", "have", "do"}
# How many top-ranked keywords are selected (deterministic).
KEYWORD_TOP_N = 15

# --- Keyword ranking formula (deterministic, fully shown in trace) ---
# score = FREQ_W * ln(1 + freq) + POS_W[pos] + DIST_W * (sentences_with_term / n_sentences)
# Ties broken alphabetically by lemma. No hidden components.
KEYWORD_FREQ_WEIGHT = 1.0
KEYWORD_DIST_WEIGHT = 1.0
KEYWORD_POS_WEIGHTS = {
    "NOUN": 2.0,
    "PROPN": 2.0,
    "ADJ": 1.5,
    "VERB": 1.0,
}

# --- WordNet expansion ---
# Max retained related terms per teacher/topic term (rest recorded as rejected).
WORDNET_MAX_PER_TERM = 20

# --- TF-IDF (scikit-learn) ---
# Corpus = exactly 2 documents: [topic_doc, student_doc].
# topic_doc   = assignment topic text + teacher keywords, lemmatized.
# student_doc = student essay text, lemmatized the same way.
# LIMITATION (honest): with 2 documents, IDF only distinguishes
# "term in both docs" (idf ~1.0) from "term in one doc" (idf ~1.41).
# This is a transparent starting point, NOT a trained semantic model.
TFIDF_MIN_DF = 1

# --- Cosine verification tolerance (manual vs library) ---
COSINE_TOLERANCE = 1e-9

# ============================================================
# PHASE 3 STAGE 1 — pre-writing scaffolding (centralized).
# All PREWRITE rules are deterministic heuristics, honestly labeled.
# ============================================================

# Minimum meaningful tokens for a developed idea (PREWRITE_001).
PREWRITE_MIN_TOKENS = 8
# Broad-idea rule: <=1 sentence, fewer selected keywords than this,
# and no causal marker (PREWRITE_002).
PREWRITE_BROAD_MAX_KEYWORDS = 6
# Unclear-relationship rule: at least this many keywords with no
# relational marker present (PREWRITE_003).
PREWRITE_MIN_CONCEPTS_RELATIONSHIP = 3
# Focused-idea rule needs at least this many concepts (PREWRITE_008).
PREWRITE_MIN_CONCEPTS_FOCUSED = 3
# Max reflective prompts shown to the student at once.
STAGE1_MAX_PROMPTS = 3

# Priority levels (explicit, deterministic). Lower number = shown first.
PREWRITE_PRIORITY = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}

# Causal/relational markers (lemmas, deterministic): presence signals that
# the student already connects concepts (PREWRITE_003 negative, PREWRITE_006).
PREWRITE_CAUSAL_MARKERS = {
    "because", "since", "through", "between", "cause", "causes",
    "affect", "affects", "effect", "lead", "leads", "due",
}
# Issue/problem indicators (lemmas, PREWRITE_004).
PREWRITE_ISSUE_LEMMAS = {
    "problem", "issue", "difficult", "difficulty", "challenge",
    "effect", "impact", "crisis", "threat", "concern", "risk",
    "damage", "loss", "decline", "problematic",
}
# Broad-scope markers (lemma set, documented heuristic): generic quantifier /
# scope words suggesting an idea lists many directions without settling on one
# (PREWRITE_002 branch B for multi-sentence ideas).
PREWRITE_BROAD_MARKERS = {
    "many", "much", "various", "several", "different",
    "every", "everything", "everyone", "always", "never",
}
# PREWRITE_002 branch B: multi-sentence idea with at least this many
# sentences and concepts plus a broad-scope marker above.
PREWRITE_BRANCHB_MIN_SENTENCES = 2
PREWRITE_BRANCHB_MIN_CONCEPTS = 8
# Stakeholder gazetteer (documented heuristic) + any PROPN (PREWRITE_005).
PREWRITE_STAKEHOLDERS = {
    "farmer", "people", "community", "student", "worker", "child",
    "family", "citizen", "government", "country", "society",
    "population", "grower", "consumer", "patient",
}

# Readiness thresholds (explicit conditions, no hidden percentage).
# C1 development + C2 concepts covered by rules above; C3/C4 below.
STAGE1_MIN_SENTENCES = 1

# ============================================================
# PHASE 4 STAGE 2 — thesis formulation (centralized).
# All THESIS_003+ rules are deterministic heuristics, honestly labeled.
# Existing THESIS_001/THESIS_002 are reused unchanged (rules/ dir).
# ============================================================

# Specificity rule (THESIS_003): broad when alpha tokens <= this AND
# selected keywords <= this AND no causal/stance anchor.
THESIS_BROAD_MAX_TOKENS = 8
THESIS_BROAD_MAX_KEYWORDS = 3
# Scope rule (THESIS_005): overloaded when finite verbs >= this.
THESIS_SCOPE_MIN_VERBS = 4
# Overloaded-claims rule (THESIS_008): keywords >= this AND verbs >= this.
THESIS_OVERLOAD_MIN_KEYWORDS = 8
THESIS_OVERLOAD_MIN_VERBS = 3
# Max thesis prompts shown at once.
STAGE2_MAX_PROMPTS = 3

# Stance/position markers (lemma set, documented heuristic): presence
# suggests the statement takes a direction (THESIS_007 negative evidence).
THESIS_STANCE_LEMMAS = {
    "should", "must", "need", "needs", "important", "importantly",
    "significant", "significantly", "serious", "seriously", "crucial",
    "essential", "vital", "argue", "argues", "claim", "claims",
    "contend", "demonstrate", "prove", "critical", "key", "major", "primary",
}
# Vagueness markers (lemma set, documented heuristic) for THESIS_009.
THESIS_VAGUE_LEMMAS = {
    "thing", "things", "stuff", "something", "anything", "everything",
    "aspect", "aspects", "factor", "factors", "somehow", "very",
    "really", "quite", "much", "lots", "good", "bad", "big",
}
# Stage1->Stage2 alignment: keyword-overlap ratio thresholds (heuristic).
STAGE2_ALIGN_HIGH = 0.5
STAGE2_ALIGN_LOW = 0.25

# ============================================================
# PHASE 5 STAGE 3 — outline development (centralized).
# All OUTLINE rules are deterministic heuristics, honestly labeled.
# Cosine is ONE supporting lexical signal, never "coherence".
# ============================================================

# Outline size guardrails (do NOT imply "every essay needs 3 paragraphs").
OUTLINE_MIN_POINTS = 2
OUTLINE_MAX_POINTS = 6
# Underdeveloped point: fewer alpha tokens than this.
OUTLINE_MIN_POINT_TOKENS = 5
# Alignment bands (direct shared lemmas + cosine support).
OUTLINE_ALIGN_DIRECT_STRONG = 2
OUTLINE_ALIGN_COSINE_STRONG = 0.30
OUTLINE_ALIGN_COSINE_WEAK = 0.20
# Duplication: lemma Jaccard >= this (points) flags repetition.
OUTLINE_DUP_JACCARD_POINTS = 0.60
OUTLINE_DUP_COSINE_POINTS = 0.75
# Near-duplicate details: Jaccard >= this (or exact normalized match).
OUTLINE_DUP_JACCARD_DETAILS = 0.85
# Overloaded point: finite verbs >= this AND keywords >= this.
OUTLINE_OVERLOAD_VERBS = 3
OUTLINE_OVERLOAD_KEYWORDS = 6
# C7 coverage: share of thesis keywords present anywhere in the outline.
OUTLINE_COVERAGE_MIN = 0.5
# Max outline prompts shown at once.
STAGE3_MAX_PROMPTS = 3
# Maximally broad thesis objects (lemma set, documented heuristic):
# a claim whose object is one of these is flagged unspecific (THESIS_003).
THESIS_BROAD_OBJECTS = {
    "world", "everything", "everyone", "everybody", "society",
    "humanity", "history", "life",
}
# THESIS_006 / readiness C4 composite (Stage 2 use of Phase 2 evidence;
# the Phase 2 cosine formula itself is untouched): a WEAK cosine only
# counts as misalignment when fewer than this many direct/lemma/WordNet
# matches support the thesis. Single-sentence theses score low cosine
# even when clearly on-topic, so cosine alone would mislead here.
THESIS_MIN_SUPPORT_MATCHES = 2

# --- Topic-relevance classification thresholds ---
# *** CONFIGURABLE DEVELOPMENT THRESHOLDS — PENDING EMPIRICAL VALIDATION ***
# These are initial round-number development values. They are NOT
# scientifically proven or validated; do not present them as such.
# similarity < MODERATE  -> WEAK
# MODERATE <= similarity < STRONG -> MODERATE
# similarity >= STRONG -> STRONG
TOPIC_MODERATE_THRESHOLD = 0.30
TOPIC_STRONG_THRESHOLD = 0.60

# ============================================================
# WRITING LAB experimental section rules (development parameters).
# *** EXPERIMENTAL / NOT FORMALLY VALIDATED / NOT PART OF VR-2 ***
# These names are deliberately ABSENT from
# services/validation/snapshot.py FROZEN_THRESHOLDS, so the VR-2
# classifier snapshot hash can never change because of them. They live
# here (centralized, documented) instead of scattered through code.
# Surface/lexical/structural evidence only — never persuasiveness,
# credibility, factual correctness, or any quality grade.
# ============================================================
# Minimum alphabetic tokens for a section draft to count as developed.
LAB_INTRO_MIN_TOKENS = 20
LAB_BODY_MIN_TOKENS = 30
LAB_CONC_MIN_TOKENS = 15
# Keyword-overlap-coefficient bands for thesis/outline lexical connection
# (shared / min(len(section_kw), len(reference_kw))).
LAB_BODY_ALIGN_LOW = 0.25
LAB_BODY_ALIGN_HIGH = 0.50
# Conclusion novelty heuristic: all-concepts-novel triggers only with at
# least this many conclusion concepts (advisory, never blocking).
LAB_CONC_NOVEL_MIN_CONCEPTS = 3
# Default data-mode label for newly written rows (see services/db.py).
# Override per environment with ESSAYSCAFF_DATA_MODE=development|demo|pilot.
DATA_MODE_DEFAULT = "development"
