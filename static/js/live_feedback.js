/* EssayScaff Phase 1 live-feedback client (vanilla JS, debounced). */
(function () {
  "use strict";

  // Easy to configure: debounce delay in ms (spec: ~1500-2500 for this phase).
  // Server value from /api/config overrides this default when available.
  let DEBOUNCE_MS = 2000;

  const SAMPLE_TEXT =
    "This essay will discuss climate change and agriculture. Climate change have serious effects on farmers. Farmers experience lower crop production because extreme temperatures affect crops. Farmers also experience problems because rainfall patterns continue to change.";

  const editor = document.getElementById("editor");
  const statusEl = document.getElementById("status");
  const feedbackEl = document.getElementById("feedback");
  const overviewEl = document.getElementById("overview");
  const stageEl = document.getElementById("stage");

  let timer = null;
  let lastRequestId = 0;

  fetch("/api/config")
    .then((r) => (r.ok ? r.json() : null))
    .then((cfg) => {
      if (cfg && typeof cfg.debounce_ms === "number") DEBOUNCE_MS = cfg.debounce_ms;
    })
    .catch(() => {});

  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }

  async function readJson(res) {
    try { return await res.json(); }
    catch (e) { return { error: "Request failed (HTTP " + res.status + ")." }; }
  }

  function schedule() {
    // Student types -> reset timer; only analyze after they pause.
    if (timer) clearTimeout(timer);
    timer = setTimeout(runAnalysis, DEBOUNCE_MS);
  }

  async function runAnalysis() {
    timer = null;
    const text = editor.value;
    if (!text || !text.trim()) {
      statusEl.textContent = "Type something to analyze.";
      return;
    }
    const myId = ++lastRequestId;
    statusEl.textContent = "Analyzing...";
    // Phase 2: optional topic inputs (empty = topic pipeline skipped).
    const topicEl = document.getElementById("topic");
    const kwEl = document.getElementById("teacherKeywords");
    const topic = topicEl ? topicEl.value.trim() : "";
    const kws = kwEl ? kwEl.value.split(",").map(function (s) { return s.trim(); }).filter(Boolean) : [];
    try {
      const res = await fetch("/api/analyze", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: text, stage: stageEl.value, topic: topic || null, teacher_keywords: kws.length ? kws : null }),
      });
      const data = await readJson(res);
      if (myId !== lastRequestId) return; // superseded by newer request
      if (!res.ok) {
        statusEl.textContent = "Analysis unavailable.";
        feedbackEl.innerHTML = "<p>" + esc(data.error || "Analysis failed.") + "</p>";
        if (window.EssayScaffHighlight) window.EssayScaffHighlight.clear();
        return;
      }
      statusEl.textContent = "Done (" + data.analysis_id + ").";
      window.EssayScaff = window.EssayScaff || {};
      window.EssayScaff.lastData = data; // Phase 1B: Transparency Mode reads this
      // Client-side count of lab analyses (previous-feedback counter only).
      window.EssayScaff.labAnalyses = (window.EssayScaff.labAnalyses || 0) + 1;
      renderAll(data, text);
    } catch (err) {
      if (myId !== lastRequestId) return;
      statusEl.textContent = "Request failed.";
      feedbackEl.innerHTML = "<p>Request failed: " + esc(err.message) + "</p>";
      if (window.EssayScaffHighlight) window.EssayScaffHighlight.clear();
    }
  }

  // Guarded write: a missing element logs instead of throwing, so one
  // stale reference can never blank the render or fake a "Request failed".
  function setHTML(id, html) {
    const el = document.getElementById(id);
    if (!el) {
      if (window.console && window.console.warn) window.console.warn("EssayScaff: missing element #" + id);
      return;
    }
    el.innerHTML = html;
  }

  function currentLabStage() {
    return stageEl ? stageEl.value : "introduction";
  }

  function labCardFor(item) {
    return '<div class="fb ' + esc(item.severity || "info") + '" data-fb="' + esc(item.feedback_id) + '">' +
      "<strong>[" + esc(item.feedback_id) + "] " + esc(item.category) + ": " + esc(item.title) + "</strong>" +
      '<div class="meta">Sentence ' + esc(item.sentence_number) + " &middot; source <code>" + esc(item.source) + "</code>" +
      " &middot; offsets " + esc(item.start) + "-" + esc(item.end) + "</div>" +
      "<div><em>Text:</em> " + esc(item.text) + "</div>" +
      "<div><em>Why:</em> " + esc(item.reason) + "</div>" +
      "<div><em>Review:</em> " + esc(item.suggestion) + "</div>" +
      "</div>";
  }

  function renderAll(data, analyzedText) {
    const s = data.summary || {};
    overviewEl.innerHTML =
      "<p><strong>" + esc(data.analysis_id) + "</strong> &middot; " +
      esc(s.sentence_count) + " sentences &middot; " + esc(s.token_count) + " tokens &middot; " +
      esc(s.feedback_count) + " feedback items &middot; " + Number(s.processing_ms || 0).toFixed(1) +
      " ms &middot; spaCy <code>" + esc(s.spacy_model || "") + "</code> &middot; LanguageTool: " +
      esc(s.language_tool_status || "") + "</p>";

    // Progressive scaffolding: exactly one primary card (backend priority
    // order) or one constructive next step — never the full finding dump.
    // All findings stay stored and visible in Transparency Mode.
    var FF = window.EssayScaffFeedback || null;
    var primary = FF ? FF.selectPrimary(data.feedback || []) : undefined;
    if (!data.feedback || !data.feedback.length) {
      feedbackEl.innerHTML = FF
        ? FF.nextStepCard(currentLabStage())
        : "<p>No issues detected. Keep writing.</p>";
      if (FF) FF.setWhy("feedback", null);
    } else if (FF) {
      feedbackEl.innerHTML = primary ? labCardFor(primary) : "<p>No issues detected. Keep writing.</p>";
      FF.setWhy("feedback", primary ? {
        stageLabel: currentLabStage(),
        label: primary.category || "Writing feedback",
        explanation: primary.reason || null,
        evidence: (primary.sentence_number != null || primary.text)
          ? "Sentence " + primary.sentence_number + ': "' + (primary.text || "").slice(0, 160) + '"'
          : null,
      } : null);
    } else {
      feedbackEl.innerHTML = data.feedback.map(labCardFor).join("");
    }
    if (FF) FF.updateFeedbackFocus();
    // Highlights for the text just analyzed (refused if the editor moved on).
    // Only the primary item is marked, matching the visible card exactly.
    if (window.EssayScaffHighlight) window.EssayScaffHighlight.renderFor(analyzedText, data, primary);

    const t = data.technical || {};
    // NOTE: rule results and LanguageTool issues are rendered by
    // transparency.js (tab-rules / tab-lt); the dead #techRules / #techLT
    // writes that used to live here were removed — they threw on every
    // analysis and made feedback appear as "Request failed".
    setHTML("techOverview",
      "<p>analysis_id <code>" + esc(data.analysis_id) + "</code> &middot; chars " +
      esc(t.chars_before) + " -&gt; " + esc(t.chars_after) + "</p>" +
      "<p><em>Normalized copy (first 200 chars):</em> <code>" + esc((t.normalized_input || "").slice(0, 200)) + "</code></p>");

    setHTML("techSentences", (t.sentences || []).map(function (x) {
      return "<p>S" + x.number + " [" + x.start + "-" + x.end + "]: <code>" + esc(x.text) + "</code></p>";
    }).join(""));

    const rows = (t.tokens || []).map(function (tk) {
      return "<tr><td>" + tk.index + "</td><td>" + esc(tk.text) + "</td><td>" + esc(tk.lemma) +
        "</td><td>" + esc(tk.pos) + "</td><td>" + esc(tk.tag) + "</td><td>" + esc(tk.dep || "") +
        "</td><td>" + tk.is_stopword + "</td><td>" + tk.sentence + "</td><td>" + tk.start +
        "</td><td>" + tk.end + "</td></tr>";
    }).join("");
    const tokenBody = document.querySelector("#tokenTable tbody");
    if (tokenBody) tokenBody.innerHTML = rows;
    else if (window.console && window.console.warn) window.console.warn("EssayScaff: missing element #tokenTable tbody");

    setHTML("techLemmas",
      "<p><code>" + esc((t.tokens || []).map(function (tk) { return tk.text + "->" + tk.lemma; }).join(", ")) + "</code></p>");
    const stops = (t.tokens || []).filter(function (tk) { return tk.is_stopword; });
    setHTML("techStopwords",
      "<p>" + stops.length + " of " + (t.tokens || []).length + " tokens flagged stopword: <code>" +
      esc(stops.map(function (tk) { return tk.text; }).join(", ")) + "</code></p>");
    setHTML("techPos",
      "<p><code>" + esc((t.tokens || []).map(function (tk) { return tk.text + "/" + tk.pos + "/" + tk.tag; }).join(" ")) + "</code></p>");

    setHTML("techTimings",
      "<pre class=\"timings\">" + esc(JSON.stringify(t.timings, null, 2)) + "</pre>");
  }

  editor.addEventListener("input", schedule);
  document.getElementById("analyzeBtn").addEventListener("click", runAnalysis);
  document.getElementById("sampleBtn").addEventListener("click", function () {
    editor.value = SAMPLE_TEXT;
    runAnalysis();
  });
})();
