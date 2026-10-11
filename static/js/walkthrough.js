/* EssayScaff Full Analysis Walkthrough (Transparency Mode, below workspace).
 * Renders ONLY values from the live analysis response
 * (window.EssayScaff.lastData + lastStage1..4). Missing data is labeled
 * "Not available" — never invented. No NLP is duplicated here; per-term
 * numbers are displayed from backend score_parts, never recomputed.
 */
(function () {
  "use strict";

  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }
  function $(id) { return document.getElementById(id); }
  function fmtMs(v) {
    if (v == null) return "n/a";
    return Number(v).toFixed(2) + " ms";
  }
  function fmtNum(v, digits) {
    if (v == null || isNaN(Number(v))) return "n/a";
    return Number(v).toFixed(digits == null ? 4 : digits);
  }
  function na(reason) {
    return '<p class="hint">Not available' + (reason ? " — " + esc(reason) : "") + ".</p>";
  }
  function badge(src) { return ' <span class="badge">' + esc(src) + "</span>"; }
  function kv(pairs) {
    return '<dl class="wt-kv">' + pairs.map(function (p) {
      return "<div><dt>" + esc(p[0]) + "</dt><dd>" + p[1] + "</dd></div>";
    }).join("") + "</dl>";
  }
  function step(num, id, title, src, why, body) {
    return '<section class="wt-step" id="' + id + '" aria-label="' + esc(title) + '">' +
      "<h3><span class='wt-stepnum'>" + num + "</span>" + esc(title) + badge(src) + "</h3>" +
      '<p class="why">' + esc(why) + "</p>" + body + "</section>";
  }
  function ioBlock(inputHtml, processHtml, outputHtml) {
    return '<div class="wt-io">' +
      "<div><h4>INPUT</h4>" + inputHtml + "</div>" +
      "<div><h4>PROCESS</h4>" + processHtml + "</div>" +
      "<div><h4>OUTPUT</h4>" + outputHtml + "</div></div>";
  }

  function stageSessions() {
    var ES = window.EssayScaff || {};
    var out = [];
    if (ES.lastStage1) out.push({ n: 1, label: "Stage 1 — Idea", d: ES.lastStage1 });
    if (ES.lastStage2) out.push({ n: 2, label: "Stage 2 — Thesis", d: ES.lastStage2 });
    if (ES.lastStage3) out.push({ n: 3, label: "Stage 3 — Outline", d: ES.lastStage3 });
    if (ES.lastStage4) out.push({ n: 4, label: "Stage 4 — Reflection", d: ES.lastStage4 });
    return out;
  }

  function activeWs() {
    var t = document.querySelector('#workspaceTabs .tab[aria-selected="true"]');
    return t ? t.getAttribute("data-ws") : null;
  }

  /* The walkthrough follows the ACTIVE workspace tab, so the exact input
     shown below is always that tab's own analyzed text. Writing Lab and
     Stages 1–2 responses embed the full phase-1 analysis object, which
     renders the complete pipeline. Stage 3/4 revisions carry no full
     text analysis, so only their own rules, readiness and stored record
     render there. Nothing is ever borrowed silently from another tab:
     an empty tab shows an explicit placeholder naming that tab. */
  function walkthroughSource() {
    var ES = window.EssayScaff || {};
    var sec = activeWs();
    function labelFor(key, tab) {
      var datum = ES[key] || null;
      return tab + (datum ? (" — session " + (datum.session_id || "?") +
        " · revision " + (datum.revision_number != null ? datum.revision_number : "?")) : "");
    }
    function empty(tab) { return { empty: true, tab: tab }; }
    if (sec === "studentSection") {
      if (!ES.lastData) return empty("Writing Lab");
      return { analysis: ES.lastData, stageDatum: null,
        sourceLabel: "Writing Lab — " + (ES.lastData.analysis_id || "?") };
    }
    var map = { stage1Section: ["lastStage1", "Stage 1"], stage2Section: ["lastStage2", "Stage 2"],
      stage3Section: ["lastStage3", "Stage 3"], stage4Section: ["lastStage4", "Stage 4"] };
    if (map[sec]) {
      var key = map[sec][0], tab = map[sec][1];
      var datum = ES[key] || null;
      if (!datum) return empty(tab);
      if (datum.analysis) return { analysis: datum.analysis, stageDatum: datum,
        sourceLabel: labelFor(key, tab) };
      return { stageOnly: true, stageKey: key, stageDatum: datum, stageLabel: tab,
        sourceLabel: labelFor(key, tab) };
    }
    return empty("workspace");
  }

  /* ---------------- section builders (pure presentation of response data) ---------------- */

  function sOverview(d) {
    var s = d.summary || {};
    var t = d.technical || {};
    var ta = ((t.phase2 || {}).topic_analysis) || {};
    var co = ta.cosine || {};
    var body = kv([
      ["Analysis ID", "<code>" + esc(d.analysis_id) + "</code>"],
      ["Stage", esc(s.stage || "standalone analysis")],
      ["Sentences", esc(s.sentence_count)],
      ["Tokens", esc(s.token_count)],
      ["Topic classification", esc(s.topic_classification != null ? s.topic_classification : "n/a (no topic supplied)")],
      ["Cosine similarity", esc(co.library_result != null ? co.library_result : "n/a")],
      ["Writing findings", esc((d.feedback || []).length + " feedback item(s)")],
      ["Processing time", esc(fmtMs(s.processing_ms))]
    ]);
    body += '<p class="hint">Topic similarity is lexical evidence, not an essay grade.</p>' +
      "<p>EssayScaff is an NLP-supported, rule-based writing scaffolding system. " +
      "It uses NLP libraries and deterministic rules (badged per step below). " +
      "It does not use a generative language model to write or rewrite student text.</p>";
    return step("00", "wt-s0", "Analysis overview", "ESSAYSCAFF LOGIC",
      "One screen stating what was analyzed and what came out, before the details.",
      body);
  }

  function sRawInput(d) {
    var t = d.technical || {};
    if (t.raw_input == null) return step("01", "wt-s1", "Original student input", "DATABASE",
      "The exact essay as submitted — everything below derives from this text.", na("no raw text in response"));
    var body = ioBlock(
      "<p>HTTP request body <code>text</code> field.</p>",
      "<p>Stored verbatim; analysis works on a normalized copy (Step 02).</p>",
      '<pre class="wt-pre"><code>' + esc(t.raw_input) + "</code></pre>" +
      kv([["Characters", esc(t.chars_before != null ? t.chars_before : String(t.raw_input.length))],
        ["Analysis ID", "<code>" + esc(d.analysis_id) + "</code>"],
        ["Stage", esc((d.summary || {}).stage || "standalone analysis")]])
    );
    return step("01", "wt-s1", "Original student input", "DATABASE",
      "The exact essay as submitted — everything below derives from this text.", body);
  }

  function sNormalization(d) {
    var t = d.technical || {};
    if (t.normalized_input == null && t.chars_before == null)
      return step("02", "wt-s2", "Text normalization", "ESSAYSCAFF LOGIC",
        "A conservative copy is prepared so offsets stay exact.", na("no normalization data in response"));
    var body = ioBlock(
      "<p>Original text (" + esc(t.chars_before) + " chars).</p>",
      "<ul><li>Unicode NFC normalization</li><li>CRLF → LF</li><li>CR → LF</li></ul>" +
      "<p><strong>Does NOT happen here:</strong> no general lowercase conversion, no punctuation stripping, " +
      "no whitespace collapse, stopwords are not deleted from the token stream.</p>",
      "<p>Normalized copy (" + esc(t.chars_after) + " chars):</p>" +
      '<pre class="wt-pre"><code>' + esc((t.normalized_input || "").slice(0, 600)) + "</code></pre>"
    );
    return step("02", "wt-s2", "Text normalization", "ESSAYSCAFF LOGIC",
      "A conservative copy is prepared so character offsets stay exact.", body);
  }

  function sSentences(d) {
    var sents = ((d.technical || {}).sentences) || [];
    if (!sents.length) return step("03", "wt-s3", "Sentence segmentation", "SPACY",
      "The essay is split into sentences; every later finding points back to these spans.", na("no sentences in response"));
    var body = sents.map(function (x) {
      return "<p><strong>Sentence " + x.number + "</strong> <span class='wt-src'>chars " +
        esc(x.start) + "–" + esc(x.end) + "</span></p>" +
        '<pre class="wt-pre"><code>' + esc(x.text) + "</code></pre>";
    }).join("");
    return step("03", "wt-s3", "Sentence segmentation", "SPACY",
      "The essay is split into sentences; every later finding points back to these spans. EssayScaff reads spaCy's spans — it does not implement segmentation itself.", body);
  }

  function sTokens(d) {
    var toks = ((d.technical || {}).tokens) || [];
    if (!toks.length) return step("04", "wt-s4", "Tokenization", "SPACY",
      "Words and punctuation become tokens with positions, lemmas, and grammar tags.", na("no tokens in response"));
    var rows = toks.map(function (tk) {
      return "<tr><td>" + tk.index + "</td><td>" + esc(tk.text) + "</td><td>" + esc(tk.lemma) +
        "</td><td>" + esc(tk.pos) + "</td><td>" + esc(tk.tag) + "</td><td>" + esc(tk.dep || "") +
        "</td><td>" + (tk.is_stopword ? "Yes" : "No") + "</td><td>" + tk.start + "</td><td>" + tk.end +
        "</td><td>S" + tk.sentence + "</td></tr>";
    }).join("");
    var body = "<p><strong>PROVIDED BY:</strong> spaCy (" +
      esc(((d.summary || {}).spacy_model) || "en_core_web_sm") + "). " +
      "<strong>ESSAYSCAFF ROLE:</strong> reads the linguistic properties and uses them downstream. " +
      "EssayScaff does not manually tokenize the text.</p>" +
      '<details open><summary>Full token table (' + toks.length + ' tokens)</summary>' +
      '<div class="tablewrap table-scroll"><table><thead><tr><th>#</th><th>Token</th><th>Lemma</th><th>POS</th>' +
      "<th>Tag</th><th>Dependency</th><th>Stopword?</th><th>Start</th><th>End</th><th>Sent</th></tr></thead><tbody>" +
      rows + "</tbody></table></div></details>";
    return step("04", "wt-s4", "Tokenization", "SPACY",
      "Words and punctuation become tokens with positions, lemmas, and grammar tags.", body);
  }

  function sLemmaSummary(d) {
    var toks = ((d.technical || {}).tokens) || [];
    if (!toks.length) return step("05", "wt-s5", "Lemmas / stopwords / POS", "SPACY",
      "A teaching summary of the token table above.", na("no tokens in response"));
    var seen = {}, lemmas = [];
    toks.forEach(function (tk) {
      if (tk.text !== tk.lemma && !seen[tk.text + "->" + tk.lemma]) {
        seen[tk.text + "->" + tk.lemma] = 1;
        lemmas.push("<code>" + esc(tk.text) + " → " + esc(tk.lemma) + "</code>");
      }
    });
    var stops = toks.filter(function (tk) { return tk.is_stopword; }).map(function (tk) { return tk.text; });
    var posCounts = {};
    toks.forEach(function (tk) { posCounts[tk.pos] = (posCounts[tk.pos] || 0) + 1; });
    var posRows = Object.keys(posCounts).sort().map(function (p) {
      return "<tr><td>" + esc(p) + "</td><td>" + posCounts[p] + "</td></tr>";
    }).join("");
    var body = "<h4>LEMMAS (surface → base form)</h4><p>" + (lemmas.join(", ") || "No changed forms — every token already is its lemma.") + "</p>" +
      "<h4>STOPWORD IDENTIFICATION (SELECTIVE FILTERING, NOT REMOVAL)</h4><p>" + stops.length + " of " + toks.length + " tokens flagged: <code>" +
      esc(stops.join(", ")) + "</code>. Flagged, not deleted — the token stream keeps every token, and stopword " +
      "flags are used only by selected downstream operations (e.g. keyword candidacy, topic-term grouping).</p>" +
      "<h4>POS SUMMARY</h4><table><thead><tr><th>POS</th><th>Count</th></tr></thead><tbody>" + posRows + "</tbody></table>";
    return step("05", "wt-s5", "Lemmas / stopwords / POS", "SPACY",
      "A teaching summary of the token table above.", body);
  }

  function sKeywords(d) {
    var kw = (((d.technical || {}).phase2) || {}).keywords || {};
    var terms = kw.terms || [];
    if (!terms.length) return step("06", "wt-s6", "Keyword extraction", "ESSAYSCAFF LOGIC",
      "EssayScaff's own transparent ranking — separate from TF-IDF.", na("no keyword data in response"));
    var w = kw.weights || null;
    var body = "<p><strong>ESSAYSCAFF HAND-WRITTEN KEYWORD RANKING.</strong> " +
      "This is separate from TF-IDF.</p>" +
      "<h4>Formula (from this analysis)</h4>" +
      '<div class="wt-formula">Keyword Score = Frequency Contribution + POS Contribution + Sentence Distribution<br/>' +
      "<code>" + esc(kw.formula || "") + "</code></div>" +
      (w ? "<h4>Active configuration (from this analysis)</h4>" +
        "<p>Frequency Contribution = " + esc(w.freq_weight) + " × ln(1 + frequency)<br/>" +
        "Sentence Distribution = " + esc(w.dist_weight) + " × (sentences containing term / total sentences)</p>" +
        "<p>POS weights: " + Object.keys(w.pos_weights || {}).sort().map(function (p) {
          return esc(p) + " = " + esc(w.pos_weights[p]);
        }).join(" · ") + " · top-" + esc(w.top_n) + " selected</p>"
        : na("configuration echo absent (older analysis record)")) +
      "<h4>Ranked candidates</h4>" +
      '<div class="tablewrap table-scroll"><table><thead><tr><th>Term</th><th>Freq</th><th>Sentences</th>' +
      "<th>Freq part</th><th>POS</th><th>POS part</th><th>Dist. part</th><th>Score</th><th>Rank</th></tr></thead><tbody>" +
      terms.map(function (t) {
        var sp = t.score_parts || {};
        return "<tr><td><code>" + esc(t.surface || t.lemma) + "</code></td><td>" + esc(t.freq) +
          "</td><td>" + esc((t.sentences || []).join(", ")) +
          "</td><td>" + esc(sp.freq_component) + "</td><td>" + esc(t.pos) +
          "</td><td>" + esc(sp.pos_component) + "</td><td>" + esc(sp.distribution) +
          "</td><td><strong>" + esc(t.score) + "</strong></td><td>" + esc(t.rank || "—") + "</td></tr>";
      }).join("") + "</tbody></table></div>" +
      '<details><summary>Worked display: top selected term</summary><div id="wt-kwtop"></div></details>';
    var html = step("06", "wt-s6", "Keyword extraction", "ESSAYSCAFF LOGIC",
      "EssayScaff's own transparent ranking — separate from TF-IDF.", body);
    return { html: html, topTerm: terms[0] };
  }

  function sWordNet(d) {
    var wn = (((d.technical || {}).phase2) || {}).wordnet;
    if (!wn) return step("07", "wt-s7", "WordNet analysis", "WORDNET",
      "Lexical relationships for teacher/topic concepts.", na("WordNet did not run (no topic/keywords supplied)"));
    var body = "<p><strong>Library:</strong> NLTK WordNet (real database) — EssayScaff only queries and filters.</p>" +
      kv([["DIRECT", esc(wn.direct_count)], ["LEMMA", esc(wn.lemma_count)],
        ["WORDNET", esc(wn.wordnet_count)], ["NO MATCH", esc(wn.no_match_count)]]) +
      (wn.terms || []).map(function (t) {
        return '<div class="rule"><p><strong>' + esc(t.kind) + ":</strong> <code>" + esc(t.original_term) +
          "</code> → lookup <code>" + esc(t.lookup_term) + "</code> — <strong>" + esc(t.match_type) + "</strong></p>" +
          "<p>Synsets (" + esc(t.synset_count) + "): <code>" +
          esc((t.synsets || []).map(function (s) { return s.name; }).join(", ")) + "</code></p>" +
          "<p>Retained: <code>" + esc((t.retained || []).join(", ") || "none") + "</code></p>" +
          "<p>Essay matches: <code>" + esc((t.matched_student_terms || []).join(", ") || "none") + "</code></p>" +
          '<details><summary>Rejected candidates + filter reasons (' + ((t.rejected || []).length) + ")</summary><ul>" +
          ((t.rejected || []).map(function (c) {
            return "<li><code>" + esc(c.candidate_term) + "</code> — " + esc(c.rejection_reason) + "</li>";
          }).join("") || "<li>none</li>") + "</ul></details></div>";
      }).join("") +
      '<p class="hint">WordNet provides lexical relationships. It is not deep semantic understanding. ' +
      "WordNet expansions are not inserted into the TF-IDF corpus in the current implementation.</p>" +
      "<p><strong>Concept support in EssayScaff comes from a teacher-guided concept provider:</strong> " +
      "the assignment topic + teacher-provided keywords + WordNet lexical expansion. " +
      "This is not a large academic knowledge database — no curated domain knowledge base exists in the system.</p>";
    return step("07", "wt-s7", "WordNet analysis", "WORDNET",
      "Lexical relationships for teacher/topic concepts.", body);
  }

  function sDocs(d) {
    var cp2 = (((d.technical || {}).phase2 || {}).topic_analysis || {}).corpus || {};
    if (cp2.topic_doc == null) return step("08", "wt-s8", "TF-IDF document preparation", "ESSAYSCAFF LOGIC",
      "Exactly what scikit-learn receives.", na("no topic analysis in response (supply a topic)"));
    var body = ioBlock(
      "<p>Assignment topic + teacher keywords, lemmatized identically to the essay.</p>",
      "<p>EssayScaff prepares the documents. scikit-learn performs the TF-IDF computation.</p>",
      "<h4>DOCUMENT 0 — TOPIC DOCUMENT</h4>" +
      '<pre class="wt-pre"><code>' + esc(cp2.topic_doc) + "</code></pre>" +
      "<h4>DOCUMENT 1 — STUDENT DOCUMENT</h4>" +
      '<pre class="wt-pre"><code>' + esc(cp2.student_doc) + "</code></pre>" +
      "<p><strong>Number of documents: N = 2.</strong></p>"
    );
    return step("08", "wt-s8", "TF-IDF document preparation", "ESSAYSCAFF LOGIC",
      "Exactly what scikit-learn receives.", body);
  }

  function sVectorizer(d) {
    var tf = (((((d.technical || {}).phase2) || {}).topic_analysis) || {}).tfidf || {};
    var vp = tf.vectorizer_params;
    if (!vp) return step("09", "wt-s9", "TF-IDF configuration", "SCIKIT-LEARN",
      "The actual vectorizer settings from this analysis.", na("no vectorizer provenance in response"));
    var rows = Object.keys(vp).map(function (k) {
      var v = vp[k];
      return "<tr><td><code>" + esc(k) + "</code></td><td><code>" +
        esc(v === null ? "None" : (Array.isArray(v) ? "(" + v.join(", ") + ")" : String(v))) +
        "</code></td></tr>";
    }).join("");
    return step("09", "wt-s9", "TF-IDF configuration", "SCIKIT-LEARN",
      "The actual vectorizer settings from this analysis.",
      "<table><thead><tr><th>Parameter</th><th>Effective value</th></tr></thead><tbody>" + rows + "</tbody></table>" +
      '<p class="hint">Only lowercase / preprocessor / tokenizer / token_pattern / min_df are set by EssayScaff; the rest are the library\u2019s effective defaults, recorded per call.</p>');
  }

  function sMath(d) {
    var tf = (((((d.technical || {}).phase2) || {}).topic_analysis) || {}).tfidf || {};
    var idf = tf.idf || {};
    var keys = Object.keys(idf);
    if (!keys.length) return step("10", "wt-s10", "TF-IDF mathematics", "SCIKIT-LEARN",
      "How the weights are defined — library behavior, not handwritten.", na("no IDF values in response"));
    var both = null, single = null;
    keys.forEach(function (k) {
      if (idf[k] === 1.0 && both === null) both = k;
      if (idf[k] !== 1.0 && single === null) single = k;
    });
    var body = '<div class="wt-formula">TF-IDF(t,d) = TF(t,d) × IDF(t)<br/>' +
      "IDF(t) = ln((1 + N) / (1 + DF(t))) + 1 &nbsp;(N = 2 documents)</div>" +
      "<p><strong>From this analysis:</strong></p><ul>" +
      (both !== null ? "<li><code>" + esc(both) + "</code>: IDF = " + esc(idf[both]) + " — appears in both documents</li>" : "") +
      (single !== null ? "<li><code>" + esc(single) + "</code>: IDF = " + esc(idf[single]) + " — appears in one document</li>" : "") +
      "</ul><p>In general with N = 2: shared term → ln(3/3) + 1 = 1.0; single-document term → ln(3/2) + 1 ≈ 1.405465.</p>" +
      '<p><span class="badge">COMPUTED BY: scikit-learn</span></p>';
    return step("10", "wt-s10", "TF-IDF mathematics", "SCIKIT-LEARN",
      "How the weights are defined — library behavior, not handwritten.", body);
  }

  function sVectors(d) {
    var tf = (((((d.technical || {}).phase2) || {}).topic_analysis) || {}).tfidf || {};
    if (!tf.vocabulary || !tf.vocabulary.length)
      return step("11", "wt-s11", "Vocabulary + TF-IDF vectors", "SCIKIT-LEARN",
        "Every feature and both document vectors.", na("no vocabulary in response"));
    var order = "<p><strong>Feature order (" + tf.vocabulary.length + "):</strong> " +
      tf.vocabulary.map(function (v, i) { return (i + 1) + ". <code>" + esc(v) + "</code>"; }).join(" ") + "</p>";
    var rows = tf.vocabulary.map(function (v, i) {
      return "<tr><td><code>" + esc(v) + "</code></td><td>" + esc((tf.idf || {})[v]) +
        "</td><td>" + esc((tf.topic_vector || [])[i]) + "</td><td>" + esc((tf.student_vector || [])[i]) + "</td></tr>";
    }).join("");
    var body = order +
      '<details open><summary>Full feature table (all ' + tf.vocabulary.length + ' features)</summary>' +
      '<div class="tablewrap table-scroll"><table><thead><tr><th>Feature</th><th>IDF</th><th>Topic weight</th><th>Student weight</th></tr></thead><tbody>' +
      rows + "</tbody></table></div></details>";
    return step("11", "wt-s11", "Vocabulary + TF-IDF vectors", "SCIKIT-LEARN",
      "Every feature and both document vectors.", body);
  }

  function sCosine(d) {
    var co = (((((d.technical || {}).phase2) || {}).topic_analysis) || {}).cosine || {};
    if (co.library_result == null) return step("12", "wt-s12", "Cosine similarity", "SCIKIT-LEARN",
      "Angle between the two document vectors, independently verified.", na("no cosine result in response"));
    var body = '<div class="wt-formula">cos(A,B) = (A · B) / (||A|| × ||B||)<br/>A = Topic TF-IDF vector · B = Student TF-IDF vector</div>' +
      kv([["Dot product", "<code>" + esc(co.dot_product) + "</code>"],
        ["Topic norm", "<code>" + esc(co.topic_norm) + "</code>"],
        ["Student norm", "<code>" + esc(co.student_norm) + "</code>"],
        ["scikit-learn result", "<code>" + esc(co.library_result) + "</code>"],
        ["Manual verification", "<code>" + esc(co.manual_result) + "</code>"],
        ["Difference", "<code>" + esc(co.difference) + "</code>"],
        ["Tolerance", "<code>" + esc(co.tolerance) + "</code>"],
        ["Verification", co.match ? "MATCH" : "MISMATCH"]]) +
      '<p class="hint">Because the vectors are L2 normalized, their norms are approximately 1, so the dot product is essentially the cosine. ' +
      "This is topic-vector similarity, NOT an essay grade.</p>";
    return step("12", "wt-s12", "Cosine similarity", "SCIKIT-LEARN",
      "Angle between the two document vectors, independently verified.", body);
  }

  function sClassification(d) {
    var cl = (((((d.technical || {}).phase2) || {}).topic_analysis) || {}).classification || {};
    if (cl.classification == null) return step("13", "wt-s13", "Topic classification", "ESSAYSCAFF CONFIG",
      "The similarity number becomes a WEAK / MODERATE / STRONG band.", na("no classification in response"));
    var body = kv([["Comparison", "<code>" + esc(cl.comparison) + "</code>"],
      ["Decision", "<strong>" + esc(cl.classification) + "</strong>"],
      ["Thresholds", "moderate ≥ " + esc(cl.weak_moderate_boundary) + ", strong ≥ " + esc(cl.strong_boundary)]]) +
      "<p>This label is based on lexical TF-IDF/cosine evidence using the configurable thresholds above. " +
      "It is not a semantic-quality score and not an essay grade.</p>" +
      '<p class="hint">' + esc(cl.threshold_warning || "These are configurable EssayScaff development thresholds pending formal empirical validation.") + "</p>";
    return step("13", "wt-s13", "Topic classification", "ESSAYSCAFF CONFIG",
      "The similarity number becomes a WEAK / MODERATE / STRONG band.", body);
  }

  function sRules(d) {
    var results = ((d.technical || {}).rule_results) || [];
    if (!results.length) return step("14", "wt-s14", "Writing rule evaluation", "ESSAYSCAFF LOGIC",
      "Every heuristic rule, in backend evaluation order — triggered or not.", na("no rule results in response"));
    var body = results.map(function (r) {
      return '<div class="rule"><h4><code>' + esc(r.rule_id) + "</code> — " + esc(r.rule_name || "") +
        " <span class='badge'>" + esc(r.status) + "</span></h4>" +
        kv([["Severity", esc(r.severity || "n/a")],
          ["Sentence", esc(r.sentence_number != null ? r.sentence_number : "n/a")],
          ["Evidence", "<code>" + esc(typeof r.evidence === "string" ? r.evidence : JSON.stringify(r.evidence)) + "</code>"],
          ["Offsets", esc(r.start) + "–" + esc(r.end)],
          ["Pattern", (r.details && r.details.pattern) ? "<code>" + esc(r.details.pattern) + "</code>" : "n/a (not a pattern rule)"],
          ["Reason", esc(r.reason || "")]]) + "</div>";
    }).join("");
    return step("14", "wt-s14", "Writing rule evaluation", "ESSAYSCAFF LOGIC",
      "Every heuristic rule, in backend evaluation order — triggered or not.", body);
  }

  function sStageRules() {
    var stages = stageSessions();
    if (!stages.length) return step("15", "wt-s15", "Stage-specific analysis", "ESSAYSCAFF LOGIC",
      "PREWRITE / THESIS / OUTLINE / REFLECT rules for the current stage work.", na("no stage analysis in this session yet — use the Stage 1–4 tabs"));
    var hasOutline = stages.some(function (st) {
      return ((st.d.rules || st.d.thesis_rules) || []).some(function (r) {
        return (r.rule_id || "").indexOf("OUTLINE_") === 0;
      });
    });
    var body = stages.map(function (st) {
      var rules = st.d.rules || st.d.thesis_rules || [];
      var rows = (rules || []).map(function (r) {
        return "<tr><td><code>" + esc(r.rule_id) + "</code></td><td>" + esc(r.status) +
          "</td><td>" + esc(r.priority || r.severity || "n/a") + "</td><td>" + esc(r.reason || r.condition || "") + "</td></tr>";
      }).join("");
      return "<h4>" + esc(st.label) + " <span class='wt-src'>session " + esc(st.d.session_id || "?") +
        " · revision " + esc(st.d.revision_number) + "</span></h4>" +
        (rows ? '<div class="tablewrap table-scroll"><table><thead><tr><th>Rule</th><th>Result</th><th>Priority</th><th>Explanation</th></tr></thead><tbody>' +
          rows + "</tbody></table></div>" : na("no rule list in " + st.label + " response"));
    }).join("") +
      (hasOutline ? '<p class="hint">Unity, alignment, and progression statuses above are rule-based structural ' +
        "indicators derived from lexical concept alignments — not deep semantic judgments. EssayScaff may not " +
        "reliably detect grammatically valid but semantically nonsensical statements.</p>" : "");
    return step("15", "wt-s15", "Stage-specific analysis", "ESSAYSCAFF LOGIC",
      "PREWRITE / THESIS / OUTLINE / REFLECT rules for the current stage work. Never mixes stages.", body);
  }

  function sTrace(d) {
    var chains = ((d.transparency || {}).backtraces) || [];
    if (!chains.length) return step("16", "wt-s16", "How the problem became feedback", "ESSAYSCAFF LOGIC",
      "The exact evidence chain behind each feedback card.", na("no backtraces in response"));
    var body = chains.map(function (c) {
      return '<div class="rule"><h4>[' + esc(c.feedback_id) + "] " + esc(c.category) + ": " + esc(c.title) + "</h4>" +
        '<ol class="chain">' +
        "<li><strong>ORIGINAL TEXT</strong><span class='chain-sub'><code>" +
        esc((c.original_text || "").slice(0, 160)) + "…</code></span></li>" +
        "<li><strong>DETECTED EVIDENCE</strong><span class='chain-sub'><code>" +
        esc(typeof c.evidence === "string" ? c.evidence : JSON.stringify(c.evidence)) +
        "</code> — chars " + esc(c.char_start) + "–" + esc(c.char_end) + "</span></li>" +
        "<li><strong>RULE</strong><span class='chain-sub'><code>" + esc(c.generated_by || "") + "</code> " +
        esc((c.rule_file || "") + (c.rule_function ? " :: " + c.rule_function : "")) + "</span></li>" +
        "<li><strong>PROBLEM</strong><span class='chain-sub'>" + esc(c.title || "") + " (" + esc(c.decision || "") + ")</span></li>" +
        "<li><strong>FEEDBACK CATEGORY</strong><span class='chain-sub'>" + esc(c.category || "") + "</span></li>" +
        "<li><strong>SENTENCE</strong><span class='chain-sub'>" +
        esc(c.sentence ? ("S" + c.sentence.number + ": " + c.sentence.text) : "n/a") + "</span></li>" +
        "<li><strong>REASON</strong><span class='chain-sub'>" + esc(c.reason || "") + "</span></li>" +
        "</ol>" +
        (c.topic_chain ? "<p><strong>Topic chain:</strong> " + esc(c.topic_chain.classification) + " · <code>" +
          esc(c.topic_chain.comparison) + "</code> · cosine lib " + esc(c.topic_chain.cosine_library_result) +
          " / manual " + esc(c.topic_chain.cosine_manual_result) + "</p>" : "") +
        "<p><strong>FINAL STUDENT FEEDBACK:</strong> see the matching card above (suggestion text is static per rule; the template source is not exposed separately by the backend).</p></div>";
    }).join("");
    return step("16", "wt-s16", "How the problem became feedback", "ESSAYSCAFF LOGIC",
      "The exact evidence chain behind each feedback card.", body);
  }

  function allowedFlags(r) {
    var flags = [];
    ["stage2_allowed", "stage3_allowed", "stage4_allowed", "reflection_complete"].forEach(function (k) {
      if (r[k] !== undefined) flags.push(k + ": " + (r[k] ? "TRUE" : "FALSE"));
    });
    return flags.length ? flags.join(" · ") : null;
  }

  function sReadiness() {
    var stages = stageSessions();
    var names = { 1: "stage2_allowed", 2: "stage3_allowed", 3: "stage4_allowed", 4: "reflection_complete" };
    if (!stages.length) return step("17", "wt-s17", "Readiness / stage decision", "ESSAYSCAFF LOGIC",
      "Each readiness condition, the final decision, and the gate flag.", na("no stage analysis in this session yet — run Stage 1–4"));
    var body = stages.map(function (st) {
      var r = st.d.readiness || {};
      var conds = (r.conditions || []).map(function (c) {
        return "<tr><td><code>" + esc(c.id) + "</code></td><td>" + esc(c.name) + "</td><td><strong>" +
          esc(c.result) + "</strong></td><td>" + esc(c.detail || "") + "</td></tr>";
      }).join("");
      return "<h4>" + esc(st.label) + "</h4>" +
        (conds ? '<div class="tablewrap table-scroll"><table><thead><tr><th>ID</th><th>Condition</th><th>Result</th><th>Detail</th></tr></thead><tbody>' +
          conds + "</tbody></table></div>" : na("no condition list in " + st.label + " response")) +
        "<p><strong>FINAL DECISION:</strong> " + esc(r.decision || "n/a") + "</p>" +
        (r.student_message ? "<p>" + esc(r.student_message) + "</p>" : "") +
        (names[st.n] ? "<p>Gate flag <code>" + names[st.n] + "</code>: <strong>" +
          esc(r[names[st.n]] === undefined ? "n/a" : (r[names[st.n]] ? "TRUE" : "FALSE")) + "</strong></p>"
          : (allowedFlags(r) ? "<p>" + esc(allowedFlags(r)) + "</p>" : "")) +
        ((r.blocking_rules && r.blocking_rules.length) ? "<p>Blocking rules: <code>" + esc(r.blocking_rules.join(", ")) + "</code></p>"
          : "<p>Blocking rules: none.</p>");
    }).join("");
    return step("17", "wt-s17", "Readiness / stage decision", "ESSAYSCAFF LOGIC",
      "Each readiness condition, the final decision, and the gate flag.", body);
  }

  function sPersistence(d) {
    var tr = d.transparency || {};
    var stored = tr.persistence_ok;
    var body = kv([["Analysis ID", "<code>" + esc(d.analysis_id) + "</code>"],
      ["Created at", esc(d.created_at || "n/a")],
      ["Stored?", stored === undefined ? "Not available" : (stored ? "Yes" : "No — see transparency log")],
      ["Processing time", esc(fmtMs((d.summary || {}).processing_ms))]]) +
      "<p>This analysis is preserved as a revision rather than replacing earlier revisions.</p>";
    return step("18", "wt-s18", "Persistence / revision", "DATABASE",
      "Where this analysis lives and why history is never overwritten.", body);
  }

  function sSummary(d) {
    var s = d.summary || {};
    var t = d.technical || {};
    var kw = (((t.phase2) || {}).keywords) || {};
    var results = (t.rule_results) || [];
    var issue = null, claim = null;
    results.forEach(function (r) {
      if (!issue && r.status === "ISSUE") issue = r;
      if (!claim && r.rule_id === "THESIS_001" && r.status === "CANDIDATE") claim = r;
    });
    var fb0 = (d.feedback || [])[0];
    var body = kv([["Topic connection", "<strong>" + esc(s.topic_classification != null ? s.topic_classification : "n/a") + "</strong>"],
      ["Important concepts", "<code>" + esc((kw.selected || []).join(", ") || "n/a") + "</code>"],
      ["Detected writing issue", issue ? "<code>" + esc(issue.rule_id) + "</code> — " + esc(issue.rule_name || "") : "none this run"],
      ["Claim candidate", claim ? "Sentence " + esc(claim.sentence_number) : "none this run"],
      ["Stage readiness", esc((function () {
        var st = stageSessions();
        if (!st.length) return "n/a — run Stage 1–4";
        var last = st[st.length - 1];
        return last.label + ": " + (((last.d.readiness || {}).decision) || "n/a");
      })())],
      ["Feedback shown", fb0 ? "<strong>" + esc(fb0.title) + "</strong> — " + esc(fb0.suggestion || fb0.reason || "") : "none"]]) +
      "<h4>WHAT THE SYSTEM DOES NOT CLAIM</h4><ul>" +
      "<li>This is not an essay grade.</li>" +
      "<li>TF-IDF does not prove semantic understanding.</li>" +
      "<li>WordNet does not provide deep contextual reasoning.</li>" +
      "<li>Grammatically valid nonsense may still pass some checks.</li>" +
      "<li>Formal accuracy has not yet been established.</li></ul>";
    return step("19", "wt-s19", "Final analysis summary", "ESSAYSCAFF LOGIC",
      "What was found — and the limits stated plainly.", body);
  }

  /* ---------------- Copy Full Analysis (Markdown export) ----------------
   * Presentation only: serializes the SAME current-walkthrough source
   * (walkthroughSource()) into readable Markdown for the clipboard. Every
   * value below is read from the live response objects — nothing is
   * recomputed (no keyword/TF-IDF/cosine/threshold/readiness math here)
   * and missing fields render as "N/A". No fetch, no revision, no DB write.
   */
  function mdV(v) {
    if (v === null || v === undefined) return "N/A";
    if (typeof v === "string" && v === "") return "N/A";
    return String(v);
  }
  function mdJ(v) {
    if (v === null || v === undefined) return "N/A";
    return (typeof v === "string") ? v : JSON.stringify(v);
  }
  function mdCell(v) {
    return mdV(v).replace(/\|/g, "\\|").replace(/\r?\n/g, " ");
  }
  function mdKV(label, v) { return label + ": " + mdV(v); }

  function copyOverview(L, d, stageDatum, src) {
    var s = d.summary || {};
    var t = d.technical || {};
    var co = (((t.phase2 || {}).topic_analysis) || {}).cosine || {};
    L.push("## Analysis Overview", "");
    L.push(mdKV("Source", src.sourceLabel));
    L.push(mdKV("Analysis ID", d.analysis_id));
    L.push(mdKV("Stage", s.stage || (stageDatum ? src.stageLabel : null)));
    if (stageDatum) {
      L.push(mdKV("Session", stageDatum.session_id));
      L.push(mdKV("Revision", stageDatum.revision_number));
    } else {
      L.push("Session: N/A (Writing Lab analysis is not a staged session)");
      L.push("Revision: N/A (Writing Lab analysis is not versioned)");
    }
    L.push(mdKV("Sentences", (t.sentences || []).length));
    L.push(mdKV("Tokens", (t.tokens || []).length));
    L.push(mdKV("Topic Classification", s.topic_classification));
    L.push(mdKV("Cosine Similarity", co.library_result));
    L.push(mdKV("Processing Time",
      s.processing_ms == null ? "N/A" : Number(s.processing_ms).toFixed(2) + " ms"));
    L.push(mdKV("spaCy Model", s.spacy_model || "en_core_web_sm"));
    L.push(mdKV("Created", d.created_at));
    L.push("", "---", "");
  }

  function copyPipeline(L, d) {
    var t = d.technical || {};
    var sents = t.sentences || [];
    var toks = t.tokens || [];
    L.push("## 1. Original Student Input", "", mdV(t.raw_input), "", "---", "");
    L.push("## 2. Text Normalization", "",
      mdKV("Input chars", t.chars_before),
      "Process:",
      "- Unicode NFC normalization",
      "- CRLF → LF",
      "- CR → LF",
      "- No general lowercase conversion, no punctuation stripping, no whitespace collapse;",
      "  stopwords are not deleted from the token stream.",
      mdKV("Output chars", t.chars_after),
      "Output:",
      mdV(t.normalized_input), "", "---", "");
    L.push("## 3. Sentence Segmentation", "");
    if (!sents.length) { L.push("N/A (no sentences in response)", "", "---", ""); }
    else {
      sents.forEach(function (x) {
        L.push("Sentence " + mdV(x.number), "Chars " + mdV(x.start) + "–" + mdV(x.end), mdV(x.text), "");
      });
      L.push("---", "");
    }
    L.push("## 4. Tokenization", "");
    if (!toks.length) { L.push("N/A (no tokens in response)", "", "---", ""); }
    else {
      L.push("| # | Token | Lemma | POS | Tag | Dependency | Stopword | Start | End | Sentence |",
        "|---|---|---|---|---|---|---|---|---|---|");
      toks.forEach(function (tk) {
        L.push("| " + mdCell(tk.index) + " | " + mdCell(tk.text) + " | " + mdCell(tk.lemma) +
          " | " + mdCell(tk.pos) + " | " + mdCell(tk.tag) + " | " + mdCell(tk.dep || "") +
          " | " + (tk.is_stopword ? "Yes" : "No") + " | " + mdCell(tk.start) + " | " +
          mdCell(tk.end) + " | S" + mdCell(tk.sentence) + " |");
      });
      L.push("", "Provided by: spaCy (EssayScaff reads the properties; it does not tokenize manually).", "", "---", "");
    }
    var seen = {}, lemmas = [];
    toks.forEach(function (tk) {
      if (tk.text !== tk.lemma && !seen[tk.text + "->" + tk.lemma]) {
        seen[tk.text + "->" + tk.lemma] = 1;
        lemmas.push(tk.text + " → " + tk.lemma);
      }
    });
    var stops = toks.filter(function (tk) { return tk.is_stopword; }).map(function (tk) { return tk.text; });
    var posCounts = {};
    toks.forEach(function (tk) { posCounts[tk.pos] = (posCounts[tk.pos] || 0) + 1; });
    L.push("## 5. Lemmas / Stopwords / POS", "");
    if (!toks.length) { L.push("N/A (no tokens in response)", "", "---", ""); }
    else {
      L.push("Lemmas (surface → base form): " + (lemmas.length ? lemmas.join(", ") : "none — every token already is its lemma."));
      L.push("Stopwords flagged: " + stops.length + " of " + toks.length + " (" + (stops.join(", ") || "none") + "). Flagged, not deleted.");
      Object.keys(posCounts).sort().forEach(function (p) { L.push("POS " + p + ": " + posCounts[p]); });
      L.push("", "---", "");
    }
    var kw = ((t.phase2 || {}).keywords) || {};
    var terms = kw.terms || [];
    L.push("## 6. Keyword Extraction", "");
    if (!terms.length) { L.push("N/A (no keyword data in response)", "", "---", ""); }
    else {
      var w = kw.weights || null;
      L.push("Formula: Keyword Score = Frequency Contribution + POS Contribution + Sentence Distribution");
      L.push("Formula (from this analysis): " + mdV(kw.formula));
      if (w) {
        L.push("Frequency Contribution = " + mdV(w.freq_weight) + " × ln(1 + frequency)");
        L.push("Sentence Distribution = " + mdV(w.dist_weight) + " × (sentences containing term / total sentences)");
        L.push("POS weights: " + Object.keys(w.pos_weights || {}).sort().map(function (p) {
          return p + " = " + w.pos_weights[p];
        }).join(" · ") + " · top-" + mdV(w.top_n) + " selected");
      } else { L.push("Active configuration: N/A (configuration echo absent — older analysis record)"); }
      L.push("", "| Term | Frequency | Sentences | Freq part | POS | POS part | Dist. part | Score | Rank |",
        "|---|---|---|---|---|---|---|---|---|");
      terms.forEach(function (tm) {
        var sp = tm.score_parts || {};
        L.push("| " + mdCell(tm.surface || tm.lemma) + " | " + mdCell(tm.freq) + " | " +
          mdCell((tm.sentences || []).join(", ")) + " | " + mdCell(sp.freq_component) + " | " +
          mdCell(tm.pos) + " | " + mdCell(sp.pos_component) + " | " + mdCell(sp.distribution) +
          " | " + mdCell(tm.score) + " | " + mdCell(tm.rank) + " |");
      });
      L.push("", "---", "");
    }
    var wn = ((t.phase2 || {}).wordnet) || null;
    L.push("## 7. WordNet Analysis", "");
    if (!wn) { L.push("N/A (WordNet did not run — no topic/keywords supplied)", "", "---", ""); }
    else {
      L.push("Library: NLTK WordNet (real database) — EssayScaff only queries and filters.");
      L.push("DIRECT: " + mdV(wn.direct_count) + " · LEMMA: " + mdV(wn.lemma_count) +
        " · WORDNET: " + mdV(wn.wordnet_count) + " · NO MATCH: " + mdV(wn.no_match_count));
      (wn.terms || []).forEach(function (x) {
        L.push("", "Candidate: " + mdV(x.kind) + " " + mdV(x.original_term) +
          " → lookup " + mdV(x.lookup_term) + " — " + mdV(x.match_type));
        L.push("Synsets (" + mdV(x.synset_count) + "): " + (((x.synsets || []).map(function (x2) { return x2.name; }).join(", ")) || "none"));
        L.push("Retained: " + (((x.retained || []).join(", ")) || "none"));
        L.push("Essay matches: " + (((x.matched_student_terms || []).join(", ")) || "none"));
        L.push("Rejected candidates + filter reasons (" + ((x.rejected || []).length) + "): " +
          (((x.rejected || []).map(function (c) { return c.candidate_term + " — " + c.rejection_reason; }).join("; ")) || "none"));
      });
      L.push("", "WordNet provides lexical relationships. It is not deep semantic understanding.",
        "WordNet expansions are not inserted into the TF-IDF corpus in the current implementation.", "", "---", "");
    }
    var ta = ((t.phase2 || {}).topic_analysis) || {};
    var cp = ta.corpus || {};
    L.push("## 8. TF-IDF Document Preparation", "");
    if (cp.topic_doc == null) { L.push("N/A (no topic analysis in response — supply a topic)", "", "---", ""); }
    else {
      L.push("DOCUMENT 0 — TOPIC DOCUMENT (assignment topic + teacher keywords, lemmatized identically to the essay):",
        mdV(cp.topic_doc), "", "DOCUMENT 1 — STUDENT DOCUMENT:", mdV(cp.student_doc), "", "N = 2", "", "---", "");
    }
    var tf = ta.tfidf || {};
    L.push("## 9. TF-IDF Configuration", "");
    if (!tf.vectorizer_params) { L.push("N/A (no vectorizer provenance in response)", "", "---", ""); }
    else {
      Object.keys(tf.vectorizer_params).forEach(function (k) {
        var v = tf.vectorizer_params[k];
        L.push(k + ": " + (v === null ? "None" : (Array.isArray(v) ? "(" + v.join(", ") + ")" : String(v))));
      });
      L.push("Only lowercase / preprocessor / tokenizer / token_pattern / min_df are set by EssayScaff; the rest are the library's effective defaults, recorded per call.", "", "---", "");
    }
    var idf = tf.idf || {};
    var idfKeys = Object.keys(idf);
    L.push("## 10. TF-IDF Mathematics", "");
    if (!idfKeys.length) { L.push("N/A (no IDF values in response)", "", "---", ""); }
    else {
      var both = null, single = null;
      idfKeys.forEach(function (k) {
        if (idf[k] === 1.0 && both === null) both = k;
        if (idf[k] !== 1.0 && single === null) single = k;
      });
      L.push("TF-IDF(t,d) = TF(t,d) × IDF(t)");
      L.push("IDF(t) = ln((1 + N) / (1 + DF(t))) + 1 (N = 2 documents)");
      if (both !== null) L.push(both + ": IDF = " + idf[both] + " — appears in both documents");
      if (single !== null) L.push(single + ": IDF = " + idf[single] + " — appears in one document");
      L.push("In general with N = 2: shared term → ln(3/3) + 1 = 1.0; single-document term → ln(3/2) + 1 ≈ 1.405465.",
        "Computed by: scikit-learn", "", "---", "");
    }
    L.push("## 11. Vocabulary + TF-IDF Vectors", "");
    if (!tf.vocabulary || !tf.vocabulary.length) { L.push("N/A (no vocabulary in response)", "", "---", ""); }
    else {
      L.push("Feature order (" + tf.vocabulary.length + "): " +
        tf.vocabulary.map(function (v, i) { return (i + 1) + ". " + v; }).join(" "));
      L.push("", "| Feature | IDF | Topic weight | Student weight |",
        "|---|---|---|---|");
      tf.vocabulary.forEach(function (v, i) {
        L.push("| " + mdCell(v) + " | " + mdCell((tf.idf || {})[v]) + " | " +
          mdCell((tf.topic_vector || [])[i]) + " | " + mdCell((tf.student_vector || [])[i]) + " |");
      });
      L.push("", "---", "");
    }
    var co = ta.cosine || {};
    L.push("## 12. Cosine Similarity", "");
    if (co.library_result == null) { L.push("N/A (no cosine result in response)", "", "---", ""); }
    else {
      L.push("cos(A,B) = (A · B) / (||A|| × ||B||); A = Topic TF-IDF vector, B = Student TF-IDF vector");
      L.push("Dot product: " + mdV(co.dot_product));
      L.push("Topic norm: " + mdV(co.topic_norm));
      L.push("Student norm: " + mdV(co.student_norm));
      L.push("scikit-learn: " + mdV(co.library_result));
      L.push("manual: " + mdV(co.manual_result));
      L.push("difference: " + mdV(co.difference));
      L.push("tolerance: " + mdV(co.tolerance));
      L.push("verification: " + (co.match ? "MATCH" : "MISMATCH"));
      L.push("This is topic-vector similarity, NOT an essay grade.", "", "---", "");
    }
    var cl = ta.classification || {};
    L.push("## 13. Topic Classification", "");
    if (cl.classification == null) { L.push("N/A (no classification in response)", "", "---", ""); }
    else {
      L.push("Comparison: " + mdV(cl.comparison));
      L.push("Decision: " + mdV(cl.classification));
      L.push("Thresholds: moderate ≥ " + mdV(cl.weak_moderate_boundary) + ", strong ≥ " + mdV(cl.strong_boundary));
      L.push(mdV(cl.threshold_warning || "These are configurable EssayScaff development thresholds pending formal empirical validation."));
      L.push("This label is based on lexical TF-IDF/cosine evidence. It is not a semantic-quality score and not an essay grade.", "", "---", "");
    }
    var results = (t.rule_results) || [];
    L.push("## 14. Generic Writing Rules", "");
    if (!results.length) { L.push("N/A (no rule results in response)", "", "---", ""); }
    else {
      results.forEach(function (r) {
        L.push("Rule: " + mdV(r.rule_id));
        L.push("Name: " + mdV(r.rule_name));
        L.push("Result: " + mdV(r.status));
        L.push("Severity: " + mdV(r.severity));
        L.push("Sentence: " + mdV(r.sentence_number));
        L.push("Evidence: " + mdJ(typeof r.evidence === "string" ? r.evidence : JSON.stringify(r.evidence)));
        L.push("Offsets: " + mdV(r.start) + "–" + mdV(r.end));
        L.push("Pattern: " + ((r.details && r.details.pattern) ? r.details.pattern : "N/A (not a pattern rule)"));
        L.push("Reason: " + mdV(r.reason));
        L.push("");
      });
      L.push("---", "");
    }
  }

  function copyStageRuleBlock(L, label, datum) {
    var rules = datum.rules || datum.thesis_rules || [];
    L.push("### " + label + " (session " + mdV(datum.session_id) + " · revision " + mdV(datum.revision_number) + ")");
    if (!rules.length) { L.push("N/A (no rule list in response)", ""); return; }
    rules.forEach(function (r) {
      L.push("Rule ID: " + mdV(r.rule_id));
      L.push("Result: " + mdV(r.status));
      L.push("Priority: " + mdV(r.priority || r.severity));
      L.push("Explanation: " + mdV(r.reason || r.condition));
      if (r.evidence !== undefined) L.push("Evidence: " + mdJ(typeof r.evidence === "string" ? r.evidence : JSON.stringify(r.evidence)));
      if (r.why_shown !== undefined) L.push("Why shown: " + mdV(r.why_shown));
      L.push("");
    });
  }

  function copyStagePayload(L, label, datum, n) {
    if (n === 3) {
      L.push("Thesis under revision: " + mdV(datum.thesis));
      L.push("Thesis snapshot: " + mdV(datum.thesis_snapshot));
      (datum.outline || []).forEach(function (p, i) {
        L.push("Body Point " + (i + 1) + ": " + mdV(p.text));
        (p.details || []).forEach(function (x, j) { L.push("Supporting Detail " + (i + 1) + "." + (j + 1) + ": " + mdV(x)); });
      });
      L.push("Alignments: " + mdJ(JSON.stringify(datum.alignments)));
      L.push("Unity: " + mdJ(JSON.stringify(datum.unity)));
      L.push("Progression: " + mdJ(JSON.stringify(datum.progression)));
      L.push("Duplicates: " + mdJ(JSON.stringify(datum.duplicates)));
      L.push("Coverage: " + mdJ(JSON.stringify(datum.coverage)));
      L.push("Concept provider: " + mdV(datum.provider));
    } else if (n === 4) {
      var sc = datum.scaffold || {};
      L.push("Scaffold level: " + mdV(sc.level) + " (" + mdV(sc.label) + ")");
      L.push("Scaffold reason: " + mdV(sc.reason));
      L.push("Scaffold evidence: " + mdJ(JSON.stringify(sc.evidence)));
      L.push("Unresolved rules: " + (((datum.unresolved_rules || []).join(", ")) || "none"));
      L.push("Return links: " + mdJ(JSON.stringify(datum.return_links)));
      L.push("Student note stored: " + mdV(datum.student_note_stored));
      L.push("Conclusion present: " + mdV(datum.conclusion && datum.conclusion.present));
      L.push("Checklist: " + mdJ(JSON.stringify(datum.checklist)));
      L.push("Snapshot: " + mdJ(JSON.stringify(datum.snapshot)));
      L.push("Classes: " + mdJ(JSON.stringify(datum.classes)));
      L.push("History: " + mdJ(JSON.stringify((datum.history || {}).by_rule)));
    } else if (n === 2) {
      var comp = datum.components || {};
      L.push("Detected subject: " + mdV(comp.detected_subject));
      L.push("Main predicate: " + mdV(comp.main_verb));
      L.push("Important concepts: " + (((comp.important_concepts || []).join(", ")) || "none"));
      L.push("Alignment: " + mdJ(JSON.stringify(datum.alignment)));
      var ref = datum.stage1_reference || {};
      L.push("Stage-1 linked: " + mdV(ref.linked));
      if (ref.final_idea) L.push("Stage-1 final idea: " + mdV(ref.final_idea));
    } else if (n === 1) {
      var ev = datum.evidence || {};
      L.push("Selected keywords: " + (((ev.selected_keywords || []).join(", ")) || "none"));
      L.push("Topic: " + mdV(datum.topic !== undefined ? datum.topic : (datum.analysis || {}).topic));
      var cmp = datum.comparison || {};
      L.push("Comparison: " + mdJ(JSON.stringify((cmp.messages || []).map(function (m) { return m.text; }))));
    }
    var prs = ((datum.prompts || {}).prompts) || [];
    L.push("Scaffolding prompts shown (" + prs.length + "):");
    if (!prs.length) { L.push("N/A (no prompts in response)"); }
    else {
      prs.forEach(function (p) {
        L.push("- [" + mdV(p.prompt_id) + "] " + mdV(p.text) +
          " (rule " + mdV(p.rule_id) + ", priority " + mdV(p.priority) +
          (p.detail_level !== undefined ? ", detail " + mdV(p.detail_level) : "") +
          (p.target !== undefined ? ", target " + mdV(p.target) : "") + ")");
        if (p.why_shown !== undefined) L.push("  Why shown: " + mdV(p.why_shown));
      });
    }
    L.push("");
  }

  function copyStageSections(L) {
    var stages = stageSessions();
    var names = { 1: "Stage 1 — Idea", 2: "Stage 2 — Thesis", 3: "Stage 3 — Outline", 4: "Stage 4 — Reflection" };
    L.push("## 15. Stage-Specific Analysis", "");
    if (!stages.length) { L.push("N/A (no stage analysis in this session yet)", "", "---", ""); return; }
    stages.forEach(function (st) {
      copyStageRuleBlock(L, names[st.n] || ("Stage " + st.n), st.d);
      copyStagePayload(L, names[st.n] || ("Stage " + st.n), st.d, st.n);
    });
    L.push("---", "");
  }

  function copyFeedbackTrace(L, d) {
    var chains = ((d.transparency || {}).backtraces) || [];
    var fbs = d.feedback || [];
    function byId(fid) {
      for (var i = 0; i < fbs.length; i++) {
        if (fbs[i] && fbs[i].feedback_id === fid) return fbs[i];
      }
      return null;
    }
    L.push("## 16. Feedback Trace", "");
    if (!chains.length) { L.push("N/A (no backtraces in response)", "", "---", ""); return; }
    chains.forEach(function (c) {
      var fb = byId(c.feedback_id);
      L.push("Feedback item: [" + mdV(c.feedback_id) + "] " + mdV(c.title));
      L.push("Original text: " + mdV((c.original_text || "").slice(0, 1000)));
      L.push("Evidence: " + mdJ(typeof c.evidence === "string" ? c.evidence : JSON.stringify(c.evidence)));
      L.push("Rule: " + mdV(c.generated_by) + " (" + mdV(c.rule_file) + (c.rule_function ? " :: " + c.rule_function : "") + ")");
      L.push("Problem: " + mdV(c.title) + " (" + mdV(c.decision) + ")");
      L.push("Feedback category: " + mdV(c.category));
      L.push("Sentence: " + (c.sentence ? ("S" + mdV(c.sentence.number) + ": " + mdV(c.sentence.text)) : "N/A"));
      L.push("Reason: " + mdV(c.reason));
      if (c.topic_chain) {
        L.push("Topic chain: " + mdV(c.topic_chain.classification) + " · " + mdV(c.topic_chain.comparison) +
          " · cosine lib " + mdV(c.topic_chain.cosine_library_result) + " / manual " + mdV(c.topic_chain.cosine_manual_result));
      }
      if (fb) {
        L.push("Final student feedback: " + mdV(fb.title) + " — " + mdV(fb.suggestion || fb.text || fb.reason));
      } else {
        L.push("Final student feedback: N/A (no matching feedback card in response)");
      }
      L.push("");
    });
    L.push("---", "");
  }

  function copyReadinessBlock(L, label, r, gateName) {
    L.push("### " + label);
    (r.conditions || []).forEach(function (c) {
      L.push(mdV(c.id) + ": " + mdV(c.result));
      L.push("Condition: " + mdV(c.name));
      L.push("Detail: " + mdV(c.detail));
      L.push("");
    });
    if (!(r.conditions || []).length) L.push("Conditions: N/A (no condition list in response)");
    L.push("Final decision: " + mdV(r.decision));
    if (r.student_message) L.push("Student message: " + mdV(r.student_message));
    if (gateName) {
      L.push("Gate: " + gateName + " = " +
        (r[gateName] === undefined ? "N/A" : (r[gateName] ? "TRUE" : "FALSE")));
    }
    L.push("Blocking rules: " + (((r.blocking_rules || []).join(", ")) || "none"));
    L.push("");
  }

  function copyReadiness(L) {
    var stages = stageSessions();
    var names = { 1: "Stage 1 — Idea", 2: "Stage 2 — Thesis", 3: "Stage 3 — Outline", 4: "Stage 4 — Reflection" };
    var gates = { 1: "stage2_allowed", 2: "stage3_allowed", 3: "stage4_allowed", 4: "reflection_complete" };
    L.push("## 17. Readiness / Stage Decision", "");
    if (!stages.length) { L.push("N/A (no stage analysis in this session yet)", "", "---", ""); return; }
    stages.forEach(function (st) {
      copyReadinessBlock(L, names[st.n] || ("Stage " + st.n), st.d.readiness || {}, gates[st.n]);
    });
    L.push("---", "");
  }

  function copyPersistence(L, d, stageDatum) {
    var tr = d.transparency || {};
    L.push("## 18. Persistence / Revision", "");
    L.push(mdKV("Analysis ID", d.analysis_id));
    if (stageDatum) {
      L.push(mdKV("Session", stageDatum.session_id));
      L.push(mdKV("Revision", stageDatum.revision_number));
    }
    L.push(mdKV("Created", d.created_at || (stageDatum && stageDatum.created_at)));
    L.push("Stored: " + (tr.persistence_ok === undefined
      ? (stageDatum ? "Yes — append-only revision; earlier revisions are never overwritten." : "N/A")
      : (tr.persistence_ok ? "Yes" : "No — see transparency log")));
    L.push(mdKV("Processing Time",
      ((d.summary || {}).processing_ms == null) ? "N/A"
      : Number(d.summary.processing_ms).toFixed(2) + " ms"));
    L.push("This analysis is preserved as a revision rather than replacing earlier revisions.", "", "---", "");
  }

  function copySummary(L, src, d, stageDatum) {
    var stages = stageSessions();
    L.push("## 19. Final Summary", "");
    if (d) {
      var s = d.summary || {};
      var t = d.technical || {};
      var kw = ((t.phase2 || {}).keywords) || {};
      var results = t.rule_results || [];
      var issue = null, claim = null;
      results.forEach(function (r) {
        if (!issue && r.status === "ISSUE") issue = r;
        if (!claim && r.rule_id === "THESIS_001" && r.status === "CANDIDATE") claim = r;
      });
      var fb0 = (d.feedback || [])[0];
      L.push("### GENERIC WRITING FINDINGS (phase-1 pipeline)");
      L.push("Topic connection: " + mdV(s.topic_classification));
      L.push("Important concepts: " + (((kw.selected || []).join(", ")) || "N/A"));
      L.push("Detected writing issue: " + (issue ? issue.rule_id + " — " + mdV(issue.rule_name) : "none this run"));
      L.push("Claim candidate: " + (claim ? "Sentence " + mdV(claim.sentence_number) : "none this run"));
      L.push("Feedback shown: " + (fb0 ? mdV(fb0.title) + " — " + mdV(fb0.suggestion || fb0.reason) : "none"));
      L.push("");
    } else {
      L.push("### GENERIC WRITING FINDINGS (phase-1 pipeline)");
      L.push("N/A — this revision carries no full text-analysis pipeline (token → cosine sections unavailable here).", "");
    }
    L.push("### STAGE-SPECIFIC SCAFFOLDING FINDINGS (never merged with generic findings)");
    if (!stages.length) { L.push("N/A (no stage analysis in this session yet)"); }
    else {
      stages.forEach(function (st) {
        var rules = st.d.rules || st.d.thesis_rules || [];
        var fired = rules.filter(function (r) { return r.status === "TRIGGERED" || r.status === "ISSUE"; });
        var names = { 1: "Stage 1 — Idea", 2: "Stage 2 — Thesis", 3: "Stage 3 — Outline", 4: "Stage 4 — Reflection" };
        L.push((names[st.n] || ("Stage " + st.n)) + ": " +
          (fired.length ? fired.map(function (r) { return r.rule_id + " " + r.status; }).join(", ") : "no triggered rules this run") +
          " · readiness " + mdV((st.d.readiness || {}).decision));
      });
    }
    L.push("");
    if (stageDatum) {
      L.push("Stage readiness: " + mdV((stageDatum.readiness || {}).decision));
    } else if (stages.length) {
      var last = stages[stages.length - 1];
      L.push("Stage readiness: " + (last.n === 1 ? "Stage 1 — Idea" : last.n === 2 ? "Stage 2 — Thesis" : last.n === 3 ? "Stage 3 — Outline" : "Stage 4 — Reflection") +
        ": " + mdV((last.d.readiness || {}).decision));
    }
    L.push("System limitations:");
    L.push("- not an essay grade");
    L.push("- TF-IDF does not prove semantic understanding");
    L.push("- WordNet lexical only (no deep contextual reasoning)");
    L.push("- grammatically valid nonsense may still pass some checks");
    L.push("- formal accuracy has not yet been established");
  }

  function buildCopyReport() {
    var src = walkthroughSource();
    if (!src || src.empty) return { ok: false, reason: "no-analysis" };
    var L = [];
    L.push("# ESSAYSCAFF FULL ANALYSIS", "");
    L.push("Source: " + src.sourceLabel, "");
    if (src.analysis) {
      var d = src.analysis;
      copyOverview(L, d, src.stageDatum, src);
      copyPipeline(L, d);
      copyFeedbackTrace(L, d);
    } else if (src.stageOnly) {
      L.push("Note: this revision carries no full text-analysis pipeline " +
        "(token → cosine sections are unavailable here) — only its own rules, " +
        "readiness and stored record are copied below. For the complete pipeline, " +
        "analyze text in the Writing Lab or Stages 1–2.", "");
      L.push("## Analysis Overview", "");
      L.push(mdKV("Source", src.sourceLabel));
      L.push(mdKV("Session", src.stageDatum.session_id));
      L.push(mdKV("Revision", src.stageDatum.revision_number));
      L.push(mdKV("Created", src.stageDatum.created_at));
      L.push("", "---", "");
      L.push("## 1.–14. Text-Analysis Pipeline", "");
      L.push("N/A (not present in this stage revision — see note above)", "", "---", "");
      L.push("## 16. Feedback Trace", "");
      L.push("N/A (stage revisions carry scaffolding prompts, not generic feedback — see section 15)", "", "---", "");
    }
    copyStageSections(L);
    copyReadiness(L);
    if (src.analysis) {
      copyPersistence(L, src.analysis, src.stageDatum);
    } else {
      var sd = src.stageDatum;
      L.push("## 18. Persistence / Revision", "");
      L.push(mdKV("Session", sd.session_id));
      L.push(mdKV("Revision", sd.revision_number));
      L.push(mdKV("Created", sd.created_at));
      L.push("Stored: Yes — append-only revision; earlier revisions are never overwritten.", "", "---", "");
    }
    copySummary(L, src, src.analysis || null, src.stageDatum || null);
    return { ok: true, markdown: L.join("\n"), sourceLabel: src.sourceLabel };
  }

  async function copyTextToClipboard(text) {
    try {
      if (window.navigator && window.navigator.clipboard && window.navigator.clipboard.writeText) {
        await window.navigator.clipboard.writeText(text);
        return true;
      }
    } catch (e) { /* fall through to legacy fallback */ }
    try {
      if (typeof document.execCommand !== "function") return false;
      var ta = document.createElement("textarea");
      ta.value = text;
      ta.setAttribute("readonly", "");
      ta.style.position = "fixed";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.select();
      var ok = false;
      try { ok = document.execCommand("copy"); } catch (e2) { ok = false; }
      document.body.removeChild(ta);
      return !!ok;
    } catch (e3) { return false; }
  }

  function currentSource() { return walkthroughSource(); }

  /* ---------------- entry points ---------------- */

  function sourceHeader(src) {
    return "<p class='wt-src'><strong>Source:</strong> " + esc(src.sourceLabel) +
      " — the exact input below is this analysis's own text.</p>";
  }

  function oneDatumRules(datum, label) {
    var rules = datum.rules || datum.thesis_rules || [];
    var rows = (rules || []).map(function (r) {
      return "<tr><td><code>" + esc(r.rule_id) + "</code></td><td>" + esc(r.status) +
        "</td><td>" + esc(r.priority || r.severity || "n/a") + "</td><td>" + esc(r.reason || r.condition || "") + "</td></tr>";
    }).join("");
    return "<h4>" + esc(label) + "</h4>" +
      (rows ? '<div class="tablewrap table-scroll"><table><thead><tr><th>Rule</th><th>Result</th><th>Priority</th><th>Explanation</th></tr></thead><tbody>' +
        rows + "</tbody></table></div>" : na("no rule list in " + label + " response"));
  }

  function oneDatumReadiness(datum, label) {
    var r = datum.readiness || {};
    var conds = (r.conditions || []).map(function (c) {
      return "<tr><td><code>" + esc(c.id) + "</code></td><td>" + esc(c.name) + "</td><td><strong>" +
        esc(c.result) + "</strong></td><td>" + esc(c.detail || "") + "</td></tr>";
    }).join("");
    var flags = [];
    ["stage2_allowed", "stage3_allowed", "stage4_allowed", "reflection_complete"].forEach(function (k) {
      if (r[k] !== undefined) flags.push(k + ": " + (r[k] ? "TRUE" : "FALSE"));
    });
    return "<h4>" + esc(label) + "</h4>" +
      (conds ? '<div class="tablewrap table-scroll"><table><thead><tr><th>ID</th><th>Condition</th><th>Result</th><th>Detail</th></tr></thead><tbody>' +
        conds + "</tbody></table></div>" : na("no condition list in " + label + " response")) +
      "<p><strong>FINAL DECISION:</strong> " + esc(r.decision || "n/a") + "</p>" +
      (flags.length ? "<p>" + esc(flags.join(" · ")) + "</p>" : "") +
      ((r.blocking_rules && r.blocking_rules.length) ? "<p>Blocking rules: <code>" + esc(r.blocking_rules.join(", ")) + "</code></p>"
        : "<p>Blocking rules: none.</p>");
  }

  function renderStageOnly(box, src) {
    var datum = src.stageDatum;
    var body = sourceHeader(src) +
      "<p>This revision carries no full text-analysis pipeline " +
      "(token → cosine sections are not available here) — only its own rules, readiness and stored record render below. " +
      "For the complete pipeline, analyze text in the Writing Lab or Stages 1–2.</p>" +
      step("15", "wt-s15", "Stage-specific analysis", "ESSAYSCAFF LOGIC",
        "This revision's own rules — never another stage's.", oneDatumRules(datum, src.stageLabel)) +
      step("17", "wt-s17", "Readiness / stage decision", "ESSAYSCAFF LOGIC",
        "This revision's own readiness.", oneDatumReadiness(datum, src.stageLabel)) +
      step("18", "wt-s18", "Persistence / revision", "DATABASE",
        "Where this revision lives.", kv([
          ["Session ID", "<code>" + esc(datum.session_id || "n/a") + "</code>"],
          ["Revision", esc(datum.revision_number != null ? datum.revision_number : "n/a")],
          ["Created at", esc(datum.created_at || "n/a")],
          ["Stored?", "Yes — append-only revision; earlier revisions are never overwritten."]]));
    box.innerHTML = body;
  }

  function renderWalkthrough() {
    var box = $("walkthroughBody");
    if (!box) return;
    var src = walkthroughSource();
    if (!src || src.empty) {
      box.innerHTML = '<p class="hint">No ' + esc(src ? src.tab : "workspace") +
        " analysis yet — analyze here first, or switch to a tab with results. " +
        "The walkthrough always follows the active workspace tab above.</p>";
      return;
    }
    if (src.stageOnly) { renderStageOnly(box, src); return; }
    var d = src.analysis;
    var kwHtml = sKeywords(d);
    var parts = [
      sourceHeader(src),
      sOverview(d), sRawInput(d), sNormalization(d), sSentences(d), sTokens(d),
      sLemmaSummary(d), kwHtml.html || kwHtml, sWordNet(d), sDocs(d), sVectorizer(d),
      sMath(d), sVectors(d), sCosine(d), sClassification(d), sRules(d),
      sStageRules(), sTrace(d), sReadiness(), sPersistence(d), sSummary(d)
    ];
    box.innerHTML = parts.map(function (p) { return (p && p.html) || p; }).join("");
    var top = kwHtml.topTerm, slot = $("wt-kwtop");
    if (slot) {
      if (top && top.score_parts) {
        var sp = top.score_parts;
        slot.innerHTML = "<p><code>" + esc(top.surface || top.lemma) + "</code> (rank " + esc(top.rank) + ")</p>" +
          "<p>Frequency: " + esc(top.freq) + " → ln(1 + " + esc(top.freq) + ") part = <strong>" + esc(sp.freq_component) + "</strong> (from analysis)</p>" +
          "<p>POS: " + esc(top.pos) + " → part = <strong>" + esc(sp.pos_component) + "</strong> (from analysis)</p>" +
          "<p>Appears in " + esc((top.sentences || []).length) + " sentence(s) → distribution part = <strong>" + esc(sp.distribution) + "</strong> (from analysis)</p>" +
          "<p><strong>FINAL KEYWORD SCORE: " + esc(top.score) + "</strong></p>";
      } else {
        slot.innerHTML = "<p>Score parts not present in this analysis record.</p>";
      }
    }
  }

  function refresh() {
    var sec = $("walkthrough");
    if (!sec) return;
    var trans = document.body.getAttribute("data-view") === "transparency";
    var src = walkthroughSource();
    var ready = trans && src && !src.empty;
    sec.hidden = !ready;
    var btn = $("copyAnalysisBtn");
    if (btn) btn.hidden = !ready;
    var msg = $("copyAnalysisMsg");
    if (msg) msg.textContent = "";
    if (ready) renderWalkthrough();
  }

  var copyBtn = $("copyAnalysisBtn");
  if (copyBtn) {
    copyBtn.addEventListener("click", async function () {
      var msg = $("copyAnalysisMsg");
      var rep = null;
      try { rep = buildCopyReport(); } catch (e) { rep = null; }
      if (!rep || !rep.ok) {
        if (msg) msg.textContent = "Nothing to copy yet — analyze first.";
        return;
      }
      var done = await copyTextToClipboard(rep.markdown);
      if (done) {
        copyBtn.textContent = "Copied!";
        if (msg) msg.textContent = "";
        setTimeout(function () {
          if (document.body.contains(copyBtn)) copyBtn.textContent = "Copy Full Analysis";
        }, 2000);
      } else if (msg) {
        msg.textContent = "Copy failed in this browser — clipboard unavailable.";
      }
    });
  }

  window.EssayScaffWalkthrough = {
    refresh: refresh, render: renderWalkthrough,
    buildCopyReport: buildCopyReport, currentSource: currentSource,
  };
})();
