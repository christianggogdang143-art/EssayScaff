/* EssayScaff Phase 1B Transparency Mode (professor / researcher view).
 * Read-only inspection of REAL run data from window.EssayScaff.lastData.
 * No animations, no fabricated states: block statuses come from the backend. */
(function () {
  "use strict";

  var FILES = [
    "config.py",
    "app.py",
    "routes/analysis_routes.py",
    "services/nlp_service.py",
    "services/grammar_service.py",
    "services/feedback_service.py",
    "services/analysis_service.py",
    "services/db.py",
    "services/transparency.py",
    "services/source_view.py",
    "services/keywords.py",
    "services/wordnet_service.py",
    "services/similarity.py",
    "rules/rule_engine.py",
    "rules/thesis_rules.py",
    "rules/meta_rules.py",
    "rules/style_rules.py",
    "rules/mechanics_rules.py",
    "services/prewriting.py",
    "services/stage1.py",
    "services/thesis.py",
    "services/stage2.py",
    "services/outline.py",
    "services/stage3.py",
    "services/reflection.py",
    "services/stage4.py",
    "services/knowledge_base/interface.py",
    "services/rhetorical_moves.py"
  ];

  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }
  function $(id) { return document.getElementById(id); }
  function fmtMs(v) {
    if (v == null) return "n/a";
    return Number(v).toFixed(2) + " ms";
  }
  function data() { return (window.EssayScaff || {}).lastData || null; }

  /* Structured presentational helpers (display only — same data, no logic).
     Note: kvHtml lives in stage1.js where key-value evidence is rendered;
     it is intentionally not duplicated here. */
  function chainHtml(items) {
    return '<ol class="chain">' + items.map(function (it) {
      return "<li><strong>" + esc(it.t) + "</strong>" +
        (it.s ? '<span class="chain-sub">' + esc(it.s) + "</span>" : "") +
        (it.h || "") + "</li>";
    }).join("") + "</ol>";
  }

  /* ---------------- view toggle ---------------- */
  function setView(which) {
    var trans = which === "transparency";
    document.body.setAttribute("data-view", trans ? "transparency" : "student");
    $("studentTabs").hidden = trans;
    $("transTabs").hidden = !trans;
    $("studentViewBtn").classList.toggle("active", !trans);
    $("transparencyViewBtn").classList.toggle("active", trans);
    activatePane(trans ? "pane-pipeline" : "pane-feedback");
    if (trans && data()) render(data(), false);
    else if (window.EssayScaffWalkthrough) window.EssayScaffWalkthrough.refresh();
  }
  $("studentViewBtn").addEventListener("click", function () { setView("student"); });
  $("transparencyViewBtn").addEventListener("click", function () { setView("transparency"); });

  /* ---------------- sidebar tabs (shared helper) ---------------- */
  function activatePane(paneId) {
    document.querySelectorAll("#studentTabs .tab, #transTabs .tab").forEach(function (x) {
      var on = x.getAttribute("data-pane") === paneId;
      x.classList.toggle("active", on);
      if (on) x.setAttribute("aria-selected", "true");
      else x.setAttribute("aria-selected", "false");
    });
    document.querySelectorAll(".side-panes .side-pane").forEach(function (p) {
      p.hidden = p.id !== paneId;
    });
  }
  document.querySelectorAll("#studentTabs .tab, #transTabs .tab").forEach(function (b) {
    b.addEventListener("click", function () { activatePane(b.getAttribute("data-pane")); });
  });
  // Legacy pane ids used internally (step detail, token detail).
  var PANE_FOR = { "tab-pipeline": "pane-pipeline", "tab-tokens": "pane-tokens" };
  function showTab(id) {
    activatePane(PANE_FOR[id] || "pane-pipeline");
  }
  /* ---------------- source code fetching ---------------- */
  function fetchSource(file, func, target) {
    var url = "/api/source?file=" + encodeURIComponent(file) +
      (func ? "&function=" + encodeURIComponent(func) : "");
    target.innerHTML = "<p>Loading " + esc(file) + "…</p>";
    fetch(url).then(function (r) { return r.json().then(function (j) { return { ok: r.ok, j: j }; }); })
      .then(function (res) {
        if (!res.ok || !res.j.allowed) {
          target.innerHTML = '<p class="denied">DENIED: ' + esc(res.j.error || "request refused") + "</p>";
          return;
        }
        var lines = res.j.source.split("\n");
        var numbered = lines.map(function (ln, i) {
          return '<span class="ln">' + (res.j.start_line + i) + "</span>" + esc(ln);
        }).join("\n");
        target.innerHTML =
          "<p><strong>" + esc(res.j.file) + "</strong>" +
          (res.j.function ? " :: <code>" + esc(res.j.function) + "</code>" : " (full module)") +
          " — lines " + res.j.start_line + "–" + res.j.end_line + "</p>" +
          '<p class="hint">' + esc(res.j.code_warning || "") + "</p>" +
          '<pre class="code">' + numbered + "</pre>";
      })
      .catch(function (e) { target.innerHTML = "<p>Request failed: " + esc(e.message) + "</p>"; });
  }

  var srcFile = $("srcFile");
  FILES.forEach(function (f) {
    var o = document.createElement("option"); o.value = f; o.textContent = f; srcFile.appendChild(o);
  });
  $("srcBtn").addEventListener("click", function () {
    fetchSource(srcFile.value, $("srcFunc").value.trim() || null, $("srcOut"));
  });

  /* ---------------- main render ---------------- */
  function render(d, historical) {
    if (!d.transparency || !d.transparency.pipeline) {
      $("transRunId").textContent = d.analysis_id + " (no transparency recorded)";
      $("runInfo").innerHTML = "<p>Transparency data was not recorded for this run (Phase 1A analysis).</p>";
      return;
    }
    var t = d.transparency, ri = t.run_info || {};
    $("transRunId").textContent = d.analysis_id + (historical ? " (historical)" : " (live)");
    var warn = $("histWarning");
    if (historical || t.historical_code_warning) {
      warn.hidden = false;
      warn.textContent = t.code_warning ||
        "The source code shown is the current application implementation. It may differ from the exact source used when this historical analysis was generated.";
    } else { warn.hidden = true; warn.textContent = ""; }

    var lt = (d.technical || {}).language_tool_results || {};
    $("runInfo").innerHTML =
      "<table>" +
      "<tr><th>Analysis ID</th><td><code>" + esc(d.analysis_id) + "</code></td>" +
      "<th>Timestamp</th><td>" + esc(d.created_at || "") + "</td></tr>" +
      "<tr><th>App version</th><td>" + esc(ri.app_version) + "</td>" +
      "<th>Git commit</th><td>" + esc(ri.git_commit) + "</td></tr>" +
      "<tr><th>Python</th><td>" + esc(ri.python_version) + "</td>" +
      "<th>spaCy</th><td>" + esc(ri.spacy_version) + " / model <code>" + esc(ri.spacy_model) + "</code> " + esc(ri.spacy_model_version || "") + "</td></tr>" +
      "<tr><th>LanguageTool</th><td>" + esc(lt.status || ri.languagetool_status) +
      " (pkg " + esc(ri.languagetool_package) + ", install " + esc(ri.languagetool_install) + ")" +
      (lt.cold_init_in_this_call ? " — <strong>COLD</strong> (server booted in this call)" : " — warm (reused server)") +
      "</td><th>Total</th><td>" + fmtMs((d.summary || {}).processing_ms) + "</td></tr>" +
      "</table>";

    /* pipeline blocks */
    $("pipeline").innerHTML = t.pipeline.map(function (s) {
      return '<button type="button" class="pblock ' + esc(s.status.toLowerCase()) + '" data-step="' + esc(s.id) + '">' +
        "<strong>" + s.number + ". " + esc(s.name) + "</strong>" +
        '<span class="pmeta">' + esc(s.status) + " · " + fmtMs(s.timing_ms) + "</span>" +
        '<span class="pmeta"><code>' + esc(s.file) + "</code> :: " + esc(s.function) + "</span>" +
        "</button>" + (s.next ? '<div class="parrow">↓ ' + esc(s.next) + "</div>" : "");
    }).join("");
    document.querySelectorAll("#pipeline .pblock").forEach(function (b) {
      b.addEventListener("click", function () { showStep(b.getAttribute("data-step")); showTab("tab-pipeline"); });
    });

    renderTokens(d);
    renderRules(d);
    renderKeywords(d);
    renderWordNet(d);
    renderTopic(d);
    renderLT(d);
    renderTrace(d);
    renderLog(d);
    if (window.EssayScaffWalkthrough) window.EssayScaffWalkthrough.refresh();
  }

  function stepById(id) {
    var d = data();
    return (d.transparency.pipeline || []).find(function (s) { return s.id === id; });
  }

  function showStep(id) {
    var s = stepById(id);
    if (!s) return;
    var kind = s.kind === "external" ? "OPEN-SOURCE LIBRARY" : "OUR CODE";
    var html = "<h4>STEP " + s.number + " — " + esc(s.name) +
      ' <span class="badge">' + esc(s.status) + "</span></h4>" +
      "<p><strong>Purpose:</strong> " + esc(s.purpose || "") + "</p>" +
      "<p><strong>Implementation source:</strong> <code>" + esc(s.file) + "</code> :: <code>" +
      esc(s.function) + "</code> (" + kind + ")</p>";
    if (s.library) {
      html += "<p><strong>Library:</strong> " + esc(s.library) +
        " — we did not create it; our code only calls it.</p>" +
        "<p><strong>Operations used:</strong> <code>" + esc((s.operations || []).join(", ")) + "</code></p>";
    }
    if (s.timing_note) html += '<p class="hint"><strong>Timing note:</strong> ' + esc(s.timing_note) + "</p>";
    html += "<p><strong>Input:</strong></p><pre>" + esc(typeof s.input === "string" ? s.input : JSON.stringify(s.input, null, 1)) + "</pre>" +
      "<p><strong>Process:</strong></p><pre>" + esc(typeof s.process === "string" ? s.process : JSON.stringify(s.process, null, 1)) + "</pre>" +
      "<p><strong>Output (truncated for display where large):</strong></p><pre>" +
      esc(JSON.stringify(s.output, null, 1).slice(0, 4000)) + "</pre>" +
      "<p><strong>Execution time (measured):</strong> " + fmtMs(s.timing_ms) + "</p>" +
      (s.error ? '<p class="denied">Backend error: ' + esc(s.error) + "</p>" : "") +
      "<p><strong>Next step:</strong> " + (s.next ? esc(s.next) : "(end of pipeline)") + "</p>" +
      '<div class="controls"><button type="button" id="stepCodeBtn">Show executing code (read-only)</button></div>' +
      '<div id="stepCode"></div>';
    $("tab-pipeline").innerHTML = html;
    $("stepCodeBtn").addEventListener("click", function () {
      fetchSource(s.file, s.function, $("stepCode"));
    });
  }

  /* ---------------- tokens ---------------- */
  function renderTokens(d) {
    var toks = (d.technical || {}).tokens || [];
    document.querySelector("#transTokenTable tbody").innerHTML = toks.map(function (tk) {
      return "<tr data-idx='" + tk.index + "' tabindex='0'><td>" + tk.index + "</td><td>" + esc(tk.text) +
        "</td><td>" + esc(tk.lemma) + "</td><td>" + esc(tk.pos) + "</td></tr>";
    }).join("");
    document.querySelectorAll("#transTokenTable tbody tr").forEach(function (tr) {
      var open = function () { showToken(Number(tr.getAttribute("data-idx"))); };
      tr.addEventListener("click", open);
      tr.addEventListener("keydown", function (e) {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); open(); }
      });
    });
  }

  function showToken(idx) {
    var d = data(), toks = (d.technical || {}).tokens || [];
    var tk = toks.find(function (x) { return x.index === idx; });
    if (!tk) return;
    var sents = (d.technical || {}).sentences || [];
    var sent = sents.find(function (s) { return s.number === tk.sentence; });
    var model = ((d.summary || {}).spacy_model) || "";
    $("tokenDetail").innerHTML =
      "<h4>Token T" + tk.index + " — <code>" + esc(tk.text) + "</code></h4>" +
      "<table><tr><th>Surface</th><td>" + esc(tk.text) + "</td><th>Offsets</th><td>" + tk.start + "–" + tk.end + "</td></tr>" +
      "<tr><th>Sentence</th><td>S" + tk.sentence + " — <code>" + esc(sent ? sent.text : "") + "</code></td>" +
      "<th>Location</th><td>chars " + (sent ? sent.start : "?") + "–" + (sent ? sent.end : "?") + "</td></tr>" +
      "<tr><th>Lemma</th><td>" + esc(tk.lemma) + "</td><th>POS / Tag / Dep</th><td>" + esc(tk.pos) +
      " / " + esc(tk.tag) + " / " + esc(tk.dep || "") + "</td></tr>" +
      "<tr><th>Stopword</th><td>" + tk.is_stopword + "</td><th>Punct / Alpha</th><td>" +
      tk.is_punctuation + " / " + tk.is_alpha + "</td></tr>" +
      "<tr><th>Produced by</th><td>spaCy (" + esc(model) + ")</td>" +
      "<th>Processed in</th><td><code>services/nlp_service.py :: analyze_text</code></td></tr></table>";
    showTab("tab-tokens");
  }

  /* ---------------- rules ---------------- */
  function renderRules(d) {
    var results = (d.technical || {}).rule_results || [];
    var fbByRule = {};
    (d.feedback || []).forEach(function (f) {
      (fbByRule[f.source] = fbByRule[f.source] || []).push(f.feedback_id);
    });
    var order = ["THESIS_001", "THESIS_002", "STYLE_001", "STYLE_002", "MECHANICS_001", "MECHANICS_002"];
    $("tab-rules").innerHTML = order.map(function (rid) {
      var rs = results.filter(function (r) { return r.rule_id === rid; });
      if (!rs.length) return "<h4><code>" + rid + "</code> — no results this run</h4>";
      var src = rs[0];
      return "<h4><code>" + rid + "</code> — " + esc(rs[0].rule_name || "") + "</h4>" +
        rs.map(function (r, i) {
          return '<div class="rule">' +
            "<p><strong>Source:</strong> <code>" + ruleFile(rid) + "</code> :: <code>" + ruleFunc(rid) + "</code></p>" +
            (r.details && r.details.pattern ? "<p><strong>Pattern tested:</strong> <code>" + esc(r.details.pattern) + "</code></p>" : "") +
            "<p><strong>Input:</strong> sentence " + esc(JSON.stringify(r.sentence_number)) + "</p>" +
            "<p><strong>Evidence:</strong> <code>" + esc(typeof r.evidence === "string" ? r.evidence : JSON.stringify(r.evidence)) + "</code>" +
            " — chars " + esc(r.start) + "–" + esc(r.end) + "</p>" +
            "<p><strong>Condition:</strong> " + esc(r.status) + " | <strong>Decision:</strong> " + esc(r.severity) + "</p>" +
            "<p><strong>Reason:</strong> " + esc(r.reason || "") + "</p>" +
            "<p><strong>Feedback generated:</strong> " + esc((fbByRule[rid] || []).join(", ") || "none (trace-only)") + "</p>" +
            '<div class="controls"><button type="button" data-code="' + rid + '">Show rule code</button></div>' +
            '<div id="rulecode-' + rid + "-" + i + '"></div></div>';
        }).join("");
      function ruleFile(id) {
        return { THESIS_001: "rules/thesis_rules.py", THESIS_002: "rules/meta_rules.py", STYLE_001: "rules/style_rules.py", STYLE_002: "rules/style_rules.py", MECHANICS_001: "rules/mechanics_rules.py", MECHANICS_002: "rules/mechanics_rules.py" }[id];
      }
      function ruleFunc(id) {
        return { THESIS_001: "detect_thesis_candidates", THESIS_002: "detect_meta_statements", STYLE_001: "detect_passive_voice", STYLE_002: "detect_repeated_openings", MECHANICS_001: "detect_fragments", MECHANICS_002: "detect_runons" }[id];
      }
    }).join("");
    document.querySelectorAll("#tab-rules [data-code]").forEach(function (b) {
      b.addEventListener("click", function () {
        var rid = b.getAttribute("data-code");
        var map = { THESIS_001: ["rules/thesis_rules.py", "detect_thesis_candidates"], THESIS_002: ["rules/meta_rules.py", "detect_meta_statements"], STYLE_001: ["rules/style_rules.py", "detect_passive_voice"], STYLE_002: ["rules/style_rules.py", "detect_repeated_openings"], MECHANICS_001: ["rules/mechanics_rules.py", "detect_fragments"], MECHANICS_002: ["rules/mechanics_rules.py", "detect_runons"] };
        fetchSource(map[rid][0], map[rid][1], b.parentElement.nextElementSibling);
      });
    });
  }

  /* ---------------- keywords ---------------- */
  function renderKeywords(d) {
    var p2 = ((d.technical || {}).phase2) || {};
    var kw = p2.keywords || {};
    var terms = kw.terms || [];
    $("tab-keywords").innerHTML =
      "<h4>Ranking formula</h4><p><code>" + esc(kw.formula || "") + "</code></p>" +
      "<p><strong>Source:</strong> <code>services/keywords.py :: extract_candidates</code> " +
      '<button type="button" id="kwCodeBtn">Show code</button></p><div id="kwCode"></div>' +
      '<div class="tablewrap table-scroll"><table class="kw-table"><thead><tr><th>Term</th><th>Lemma</th><th>POS</th><th>Freq</th><th>Cand.</th><th>Rank</th><th>Sel.</th><th>Reason</th></tr></thead><tbody>' +
      terms.map(function (t) {
        return "<tr><td>" + esc(t.surface) + "</td><td>" + esc(t.lemma) + "</td><td>" + esc(t.pos) +
          "</td><td>" + t.freq + "</td><td>" + t.candidate + "</td><td>" + (t.rank || "—") + "</td><td>" +
          t.selected + "</td><td>" + esc(t.candidate ? t.selection_reason : t.candidate_reason) + "</td></tr>";
      }).join("") + "</tbody></table></div>";
    $("kwCodeBtn").addEventListener("click", function () {
      fetchSource("services/keywords.py", "extract_candidates", $("kwCode"));
    });
  }

  /* ---------------- wordnet ---------------- */
  function renderWordNet(d) {
    var p2 = ((d.technical || {}).phase2) || {};
    var wn = p2.wordnet;
    if (!wn) { $("tab-wordnet").innerHTML = "<p>WordNet did not run (no topic/teacher keywords supplied).</p>"; return; }
    $("tab-wordnet").innerHTML =
      "<h4>Library vs our code</h4><p><strong>Library:</strong> NLTK WordNet (real database) — our wrapper only queries + filters.</p>" +
      "<p><strong>Filter rules:</strong></p><pre>" + esc((wn.filter_rules || []).join("\n")) + "</pre>" +
      '<p><button type="button" id="wnCodeBtn">Show wrapper code</button></p><div id="wnCode"></div>' +
      "<p><strong>Matches:</strong> DIRECT " + wn.direct_count + " · LEMMA " + wn.lemma_count +
      " · WORDNET " + wn.wordnet_count + " · NO MATCH " + wn.no_match_count + "</p>" +
      (wn.terms || []).map(function (t) {
        return '<div class="rule"><p><strong>' + esc(t.kind) + ":</strong> <code>" + esc(t.original_term) +
          "</code> → lookup <code>" + esc(t.lookup_term) + "</code> (" + esc(t.spacy_pos || "") + ") — <strong>" +
          esc(t.match_type) + "</strong></p>" +
          (t.status === "unavailable" ? '<p class="denied">WordNet unavailable: ' + esc(t.error) + "</p>" :
          "<p><strong>Synsets (" + t.synset_count + "):</strong> " +
          esc(t.synsets.map(function (s) { return s.name; }).join(", ")) + "</p>" +
          "<p><strong>Retained (" + t.retained.length + "):</strong> <code>" + esc(t.retained.join(", ")) + "</code></p>" +
          "<p><strong>Rejected:</strong></p>" + (t.rejected.length ?
            '<ul class="rej">' + t.rejected.map(function (c) {
              return "<li><code>" + esc(c.candidate_term) + "</code> <span class='muted'>" + esc(c.synset) + "</span> — " + esc(c.rejection_reason) + "</li>";
            }).join("") + "</ul>" : "<p>(none)</p>") +
          "<p><strong>Essay matches:</strong> <code>" + esc((t.matched_student_terms || []).join(", ") || "none") + "</code></p>");
      }).join("");
    var btn = $("wnCodeBtn");
    if (btn) btn.addEventListener("click", function () {
      fetchSource("services/wordnet_service.py", "analyze_terms", $("wnCode"));
    });
  }

  /* ---------------- topic (tf-idf / cosine / classification) ---------------- */
  function renderTopic(d) {
    var p2 = ((d.technical || {}).phase2) || {};
    var ta = p2.topic_analysis;
    if (!ta) { $("tab-topic").innerHTML = "<p>Topic analysis did not run (no topic/teacher keywords supplied).</p>"; return; }
    var tf = ta.tfidf || {}, co = ta.cosine || {}, cl = ta.classification || {}, cp = ta.corpus || {};
    var idfRows = Object.keys(tf.idf || {}).sort().map(function (k) {
      return "<tr><td><code>" + esc(k) + "</code></td><td>" + esc(tf.idf[k]) + "</td></tr>";
    }).join("");
    $("tab-topic").innerHTML =
      "<h4>Corpus design</h4><p>" + esc(cp.design || "") + "</p>" +
      '<p class="hint"><strong>Limitation (honest):</strong> ' + esc(cp.limitation || "") + "</p>" +
      "<h4>TF-IDF (scikit-learn " + esc(tf.library_version || "") + ")</h4>" +
      "<table><tr><th>Vocabulary size / dims</th><td>" + tf.vocabulary_size + " / " + tf.dimensions + "</td></tr>" +
      "<tr><th>Vocabulary</th><td><code>" + esc((tf.vocabulary || []).join(", ")) + "</code></td></tr>" +
      "<tr><th>Topic top terms</th><td><code>" + esc(JSON.stringify(tf.topic_nonzero)) + "</code></td></tr>" +
      "<tr><th>Student top terms</th><td><code>" + esc(JSON.stringify(tf.student_nonzero)) + "</code></td></tr></table>" +
      '<h4>IDF values</h4><div class="tablewrap table-scroll"><table class="idf-table"><thead><tr><th>Term</th><th>IDF</th></tr></thead><tbody>' +
      idfRows + "</tbody></table></div>" +
      "<h4>Cosine similarity</h4><table>" +
      "<tr><th>Formula</th><td><code>" + esc(co.formula || "") + "</code> via <code>" + esc(co.library || "") + "</code></td></tr>" +
      "<tr><th>Dot / norms</th><td>" + esc(co.dot_product) + " / " + esc(co.topic_norm) + " / " + esc(co.student_norm) + "</td></tr>" +
      "<tr><th>Library vs manual</th><td>" + esc(co.library_result) + " vs " + esc(co.manual_result) +
      " — diff " + esc(co.difference) + " (tol " + esc(co.tolerance) + ") → " + (co.match ? "MATCH" : "MISMATCH") + "</td></tr>" +
      "<tr><th>Raw / %</th><td>" + esc(co.library_result) + " / " + esc(co.percentage) + "%</td></tr></table>" +
      (co.zero_vector_note ? '<p class="hint">' + esc(co.zero_vector_note) + "</p>" : "") +
      "<h4>Classification</h4><table><tr><th>Comparison</th><td><code>" + esc(cl.comparison || "") +
      "</code> → <strong>" + esc(cl.classification || "") + "</strong></td></tr>" +
      "<tr><th>Thresholds</th><td>moderate ≥ " + esc(cl.weak_moderate_boundary) + ", strong ≥ " + esc(cl.strong_boundary) + "</td></tr></table>" +
      '<p class="hint">' + esc(cl.threshold_warning || "") + "</p>" +
      '<p><button type="button" id="simCodeBtn">Show similarity code</button></p><div id="simCode"></div>';
    $("simCodeBtn").addEventListener("click", function () {
      fetchSource("services/similarity.py", "cosine_similarity", $("simCode"));
    });
  }

  /* ---------------- LanguageTool ---------------- */
  function renderLT(d) {
    var t = d.transparency, ri = t.run_info || {};
    var step = (t.pipeline || []).find(function (s) { return s.id === "languagetool"; }) || {};
    var lt = (d.technical || {}).language_tool_results || {};
    var proc = step.process || {};
    $("tab-lt").innerHTML =
      "<h4>Library vs our code</h4>" +
      "<table><tr><th>Library</th><td>LanguageTool (open-source; package <code>" + esc(ri.languagetool_package) +
      "</code>, install <code>" + esc(ri.languagetool_install) + "</code>) — we did not create it</td></tr>" +
      "<tr><th>Application wrapper</th><td><code>services/grammar_service.py :: check_grammar</code></td></tr>" +
      "<tr><th>Library call</th><td><code>LanguageTool.check(text)</code> on one shared local server (reused: " + esc(proc.server_reused) + ")</td></tr>" +
      "<tr><th>Status</th><td>" + esc(lt.status) + (lt.error ? " — " + esc(lt.error) : "") + "</td></tr>" +
      "<tr><th>Init time (cold boot)</th><td>" + (lt.init_ms != null ? fmtMs(lt.init_ms) : "n/a (server already warm)") + "</td></tr>" +
      "<tr><th>Analysis time (this call)</th><td>" + fmtMs(lt.check_ms) + "</td></tr></table>" +
      "<h4>Issues (" + (lt.issues || []).length + ")</h4>" +
      ((lt.issues || []).map(function (m) {
        return "<p><code>" + esc(m.rule_id) + "</code> (" + esc(m.category) + ") S" + esc(m.sentence) +
          " [" + esc(m.offset) + "+" + esc(m.length) + "]: " + esc(m.message) + " — <code>" +
          esc(m.matched_text) + "</code> → " + esc(JSON.stringify(m.replacements)) + "</p>";
      }).join("") || "<p>None — genuine LanguageTool result, not hidden.</p>") +
      '<div class="controls"><button type="button" id="ltCodeBtn">Show wrapper code</button></div><div id="ltCode"></div>';
    $("ltCodeBtn").addEventListener("click", function () {
      fetchSource("services/grammar_service.py", "check_grammar", $("ltCode"));
    });
  }

  /* ---------------- feedback backtrace ---------------- */
  function renderTrace(d) {
    var chains = (d.transparency || {}).backtraces || [];
    $("tab-trace").innerHTML = chains.length ? chains.map(function (c, i) {
      return '<div class="fb">' +
        "<strong>[" + esc(c.feedback_id) + "] " + esc(c.category) + ": " + esc(c.title) + "</strong> " +
        '<button type="button" data-trace="' + i + '">Trace feedback</button>' +
        '<div id="chain-' + i + '" hidden>' +
        chainHtml([
          { t: "Generated by " + c.generated_by, s: (c.rule_file || "") + " :: " + (c.rule_function || "") },
          { t: "Evidence", s: (typeof c.evidence === "string" ? c.evidence : JSON.stringify(c.evidence)) + " — chars " + c.char_start + "–" + c.char_end },
          { t: "Sentence", s: c.sentence ? ("S" + c.sentence.number + ": " + c.sentence.text) : "n/a" },
          { t: "Related tokens", s: (c.token_indices || []).join(", ") || "none" },
          { t: "Decision: " + c.decision, s: c.reason || "" }
        ]) +
        (c.topic_chain ? "<h4>Topic chain</h4>" + chainHtml([
          { t: "Classification " + c.topic_chain.classification, s: c.topic_chain.comparison },
          { t: "Cosine", s: "library " + c.topic_chain.cosine_library_result + " / manual " + c.topic_chain.cosine_manual_result },
          { t: "TF-IDF", s: "services/similarity.py :: vectorize" },
          { t: "WordNet", s: "services/wordnet_service.py :: analyze_terms" },
          { t: "Keywords", s: "services/keywords.py :: extract_candidates" },
          { t: "Tokens → sentences → raw text" }
        ]) : "") +
        "<p><strong>Original source:</strong> <code>" + esc((c.original_text || "").slice(0, 200)) + "…</code></p>" +
        "</div></div>";
    }).join("") : "<p>No feedback this run.</p>";
    document.querySelectorAll("#tab-trace [data-trace]").forEach(function (b) {
      b.addEventListener("click", function () {
        var el = $("chain-" + b.getAttribute("data-trace"));
        el.hidden = !el.hidden;
      });
    });
  }

  /* ---------------- execution log ---------------- */
  function renderLog(d) {
    var log = ((d.transparency || {}).execution_log) || [];
    var timings = ((d.technical || {}).timings) || {};
    var rows = log.map(function (e) {
      return "<tr><td>" + Number(e.t_ms).toFixed(2) + "</td><td>" + esc(e.event) + "</td></tr>";
    }).join("");
    var wanted = ["validation_ms", "normalization_ms", "spacy_total_ms", "sentence_capture_ms",
      "token_property_capture_ms", "rules_ms", "language_tool_ms", "languagetool_init_ms",
      "languagetool_check_ms", "feedback_ms", "database_ms", "total_ms"];
    var trows = wanted.map(function (k) {
      return "<tr><td>" + esc(k) + "</td><td>" + (timings[k] == null ? "n/a" : fmtMs(timings[k])) + "</td></tr>";
    }).join("");
    $("tab-log").innerHTML = "<h4>Chronological execution (measured offsets, ms)</h4>" +
      "<table><thead><tr><th>t (ms)</th><th>Event</th></tr></thead><tbody>" + rows + "</tbody></table>" +
      "<h4>Stage timing summary (measured)</h4>" +
      "<table><thead><tr><th>Stage</th><th>Time</th></tr></thead><tbody>" + trows + "</tbody></table>";
  }

  /* ---------------- history ---------------- */
  $("historyBtn").addEventListener("click", function () {
    var id = $("historyId").value.trim();
    if (!id) return;
    fetch("/api/analysis/" + encodeURIComponent(id))
      .then(function (r) { return r.json().then(function (j) { return { ok: r.ok, j: j }; }); })
      .then(function (res) {
        if (!res.ok) { alert("Not found: " + (res.j.error || id)); return; }
        var rec = res.j;
        window.EssayScaff.lastData = {
          analysis_id: rec.id, created_at: rec.created_at, summary: rec.summary,
          feedback: rec.feedback,
          technical: Object.assign({}, rec.technical, { raw_input: rec.raw_text }),
          transparency: rec.transparency
        };
        setView("transparency");
        render(window.EssayScaff.lastData, true);
      })
      .catch(function (e) { alert("Load failed: " + e.message); });
  });

  /* auto-render when a new analysis lands while in transparency mode */
  setInterval(function () {
    var d = data();
    if (!d || document.body.getAttribute("data-view") !== "transparency") return;
    if ($("transRunId").textContent.indexOf(d.analysis_id) !== 0) render(d, false);
  }, 1000);
})();
