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

  /* Writing Lab section model (presentation state only — the server owns
   * revisions). One draft buffer per section; switching sections stashes
   * the current text and loads the other section's draft (memory first,
   * then the server's latest saved revision, else empty). Nothing is ever
   * generated: drafts hold only text the student typed. */
  const drafts = { introduction: "", body: "", conclusion: "" };
  let labSessionId = null;
  try { labSessionId = sessionStorage.getItem("essayscaff.labSession") || null; } catch (e) { /* private */ }

  function currentMode() {
    return (stageEl && stageEl.value) || "introduction";
  }
  function lastLab() {
    window.EssayScaff = window.EssayScaff || {};
    window.EssayScaff.lastLab = window.EssayScaff.lastLab || {};
    return window.EssayScaff.lastLab;
  }
  function chainIds() {
    // Current chain wins: in-memory chain (Stage-4 Continue) first, then
    // live stage responses, then link fields. Strings and input elements
    // both accepted; first non-empty value wins, else null (unlinked).
    function val() {
      for (var i = 0; i < arguments.length; i++) {
        var v = arguments[i];
        if (typeof v === "string" && v) return v;
        if (v && v.value && v.value.trim()) return v.value.trim();
      }
      return null;
    }
    var ES = window.EssayScaff || {};
    var lc = ES.labChain || {};
    return {
      stage1_session_id: val(lc.stage1_session_id, ES.lastStage1 && ES.lastStage1.session_id),
      stage2_session_id: val(lc.stage2_session_id,
        ES.lastStage2 && ES.lastStage2.session_id, document.getElementById("s3Stage2")),
      stage3_session_id: val(lc.stage3_session_id, ES.lastStage3 && ES.lastStage3.session_id),
      stage4_session_id: val(lc.stage4_session_id, ES.lastStage4 && ES.lastStage4.session_id),
    };
  }

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
    var mode = currentMode();
    var text = editor.value;
    drafts[mode] = text;
    if (!text || !text.trim()) {
      statusEl.textContent = "Type something to analyze.";
      return;
    }
    const myId = ++lastRequestId;
    statusEl.textContent = "Analyzing...";
    const topicEl = document.getElementById("topic");
    const kwEl = document.getElementById("teacherKeywords");
    const topic = topicEl ? topicEl.value.trim() : "";
    const kws = kwEl ? kwEl.value.split(",").map(function (s) { return s.trim(); }).filter(Boolean) : [];
    const chain = chainIds();
    try {
      const res = await fetch("/api/lab/analyze", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: text, section: mode,
          topic: topic || null, teacher_keywords: kws.length ? kws : null,
          lab_session_id: labSessionId,
          stage1_session_id: chain.stage1_session_id,
          stage2_session_id: chain.stage2_session_id,
          stage3_session_id: chain.stage3_session_id,
          stage4_session_id: chain.stage4_session_id }),
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
      if (data.lab_session_id && data.lab_session_id !== labSessionId) {
        labSessionId = data.lab_session_id;
        try { sessionStorage.setItem("essayscaff.labSession", labSessionId); } catch (e) { /* private */ }
      }
      window.EssayScaff = window.EssayScaff || {};
      window.EssayScaff.lastData = data; // Phase 1B: Transparency Mode reads this
      // Client-side count of lab analyses (previous-feedback counter only).
      window.EssayScaff.labAnalyses = (window.EssayScaff.labAnalyses || 0) + 1;
      lastLab()[mode] = { readiness: data.lab_readiness || {},
        revision_number: data.revision_number, analysis: data.analysis,
        lab_rules: data.lab_rules || [], lab_session_id: data.lab_session_id };
      renderAll(data, text);
      updateProgression();
    } catch (err) {
      if (myId !== lastRequestId) return;
      statusEl.textContent = "Request failed.";
      feedbackEl.innerHTML = "<p>Request failed: " + esc(err.message) + "</p>";
      if (window.EssayScaffHighlight) window.EssayScaffHighlight.clear();
    }
  }

  /* Section switching: stash the current draft, load the other section's
   * draft (memory, else the server's latest saved revision, else empty).
   * Bound here (loads before feedback_focus.js) so the draft is swapped
   * before any follow-up analysis runs. */
  var prevMode = currentMode();
  if (stageEl) stageEl.addEventListener("change", function () {
    drafts[prevMode] = editor.value;
    var next = currentMode();
    prevMode = next;
    if (drafts[next]) {
      editor.value = drafts[next];
    } else {
      editor.value = "";
      if (labSessionId) fetchLatestDraft(next);
    }
    if (window.EssayScaffHighlight) window.EssayScaffHighlight.clear();
  });

  async function fetchLatestDraft(mode) {
    if (!labSessionId) return;
    try {
      const res = await fetch("/api/lab/session/" + encodeURIComponent(labSessionId));
      if (!res.ok) return;
      const s = await readJson(res);
      // GET /session carries the assembled essay map (section -> text).
      var txt = s && s.essay ? s.essay[mode] : null;
      if (txt && !editor.value.trim()
          && currentMode() === mode && !drafts[mode]) {
        drafts[mode] = txt;
        editor.value = txt;
        // The restored text was not typed: drop any debounce scheduled for
        // older user input so a stale timer can never auto-analyze text the
        // student did not just write (e.g. right after clearing the box).
        if (timer) { clearTimeout(timer); timer = null; }
        var FF = window.EssayScaffFeedback || null;
        if (FF) FF.updateFeedbackFocus();
      }
    } catch (e) { /* drafts stay empty; never break the workspace */ }
  }

  /* Section progression gates (display only; readiness computed server-side).
   * Buttons stay disabled until the previous section is READY. */
  function sectionReady(mode) {
    var entry = lastLab()[mode];
    var map = { introduction: "READY FOR BODY", body: "READY FOR CONCLUSION",
      conclusion: "READY FOR FINAL REVIEW" };
    return !!entry && ((entry.readiness || {}).decision) === map[mode];
  }
  function updateProgression() {
    function setBtn(id, enabled) {
      var b = document.getElementById(id);
      if (b) b.disabled = !enabled;
    }
    var introOk = sectionReady("introduction");
    var bodyOk = sectionReady("body");
    var concOk = sectionReady("conclusion");
    setBtn("labToBody", introOk);
    setBtn("labToConc", bodyOk);
    setBtn("labToReview", concOk);
    var line = document.getElementById("labGateLine");
    if (line) {
      var mode = currentMode();
      if (!lastLab()[mode]) line.textContent = "";
      else if (sectionReady(mode)) line.textContent = "READY TO CONTINUE";
      else line.textContent = "REVISION NEEDED — see guidance above.";
    }
    if (window.EssayScaffFeedback) window.EssayScaffFeedback.updateFeedbackFocus();
  }

  function gotoSection(mode) {
    if (stageEl) {
      stageEl.value = mode;
      stageEl.dispatchEvent(new window.Event("change", { bubbles: true }));
    }
    var tab = document.querySelector('#workspaceTabs [data-ws="studentSection"]');
    if (tab) tab.click();
    editor.focus();
  }

  /* Final Review: read-only assembled essay + process summary, loaded from
   * stored revisions only. Never generates or rewrites student text. */
  async function loadReview() {
    var statusBox = document.getElementById("reviewStatus");
    var essayBox = document.getElementById("reviewEssay");
    var sumBox = document.getElementById("processSummary");
    if (!labSessionId) {
      if (statusBox) statusBox.innerHTML = "<p>Analyze all three essay sections first.</p>";
      if (essayBox) essayBox.innerHTML = "<p>No saved essay sections yet.</p>";
      if (sumBox) sumBox.innerHTML = "";
      return;
    }
    if (statusBox) statusBox.innerHTML = "<p>Loading…</p>";
    try {
      const res = await fetch("/api/lab/session/" + encodeURIComponent(labSessionId) + "/summary");
      if (!res.ok) {
        if (statusBox) statusBox.innerHTML = "<p>Could not load the review.</p>";
        return;
      }
      const s = await readJson(res);
      renderReviewEssay(s);
      renderSummary(s);
    } catch (e) {
      if (statusBox) statusBox.innerHTML = "<p>Request failed.</p>";
    }
  }

  function renderReviewEssay(s) {
    var essayBox = document.getElementById("reviewEssay");
    var statusBox = document.getElementById("reviewStatus");
    var essay = (s && s.student_essay) || {};
    var final = (s && s.process_status && s.process_status.final_review) || {};
    if (essayBox) {
      essayBox.textContent = "";
      [["INTRODUCTION", "introduction"], ["BODY", "body"], ["CONCLUSION", "conclusion"]].forEach(function (pair) {
        var h = document.createElement("h3");
        h.textContent = pair[0];
        essayBox.appendChild(h);
        var p = document.createElement("p");
        // textContent only: student text stays literal, never markup.
        p.textContent = essay[pair[1]] || "Not written yet.";
        essayBox.appendChild(p);
      });
    }
    if (statusBox) {
      // Exact backend strings: structural state, never a quality grade.
      statusBox.innerHTML = "<p><strong>" + esc(final.decision || "REVISION NEEDED") + "</strong></p>" +
        "<p>" + esc(final.student_message || "") + "</p>";
    }
  }

  function renderSummary(s) {
    var sumBox = document.getElementById("processSummary");
    if (!sumBox || !s) return;
    function row(k, v) {
      return "<div><span>" + esc(k) + "</span><strong>" + esc(v) + "</strong></div>";
    }
    var st = s.process_status || {};
    var stages = st.stages || {};
    var procRows = ["stage1", "stage2", "stage3", "stage4"].map(function (k) {
      var g = stages[k] || {};
      return "<div><span>" + esc(g.label || k) + "</span><strong>" +
        esc(!g.linked ? "Not linked" : (g.decision || "—")) + "</strong></div>";
    }).join("");
    var labSecs = st.lab_sections || {};
    procRows += ["introduction", "body", "conclusion"].map(function (k) {
      var g = labSecs[k] || {};
      var cap = k.charAt(0).toUpperCase() + k.slice(1);
      return "<div><span>" + cap + "</span><strong>" +
        esc(!g.revision_count ? "Not written" : (g.decision || "—")) + "</strong></div>";
    }).join("");
    var rev = s.revision_info || {};
    var tm = s.time || {};
    var fb = s.feedback || {};
    var plan = s.planning_artifacts || {};
    var outlineTxt = ((plan.outline || []).map(function (p, i) {
      return "Point " + (i + 1) + ": " + (p.text || "") + " — " + (p.details || []).join("; ");
    }).join("\n")) || "No outline linked.";
    var timeline = (s.timeline || []).map(function (e) {
      return (e.created_at || "?") + " — " + (e.kind || "?") + " R" +
        (e.revision_number != null ? e.revision_number : "?") + " (" + (e.decision || "?") + ")";
    }).join("\n");
    sumBox.innerHTML =
      "<h3>Writing Process Summary</h3>" +
      "<h4>Assignment</h4><p>" + esc(((s.assignment || {}).topic) || "No topic linked.") + "</p>" +
      "<p>" + esc((((s.assignment || {}).teacher_keywords) || []).join(", ") || "No keywords linked.") + "</p>" +
      // Overall structural state, exact backend strings (never a grade).
      "<h4>Overall status</h4><p><strong>" + esc((st.final_review || {}).decision || "REVISION NEEDED") + "</strong></p>" +
      "<p>" + esc((st.final_review || {}).student_message || "") + "</p>" +
      "<h4>Process status</h4>" + '<div class="dash-snap">' + procRows + "</div>" +
      "<h4>Process snapshot</h4>" + '<div class="dash-snap">' +
      row("Total active time", fmtDurShort(((tm.active_ms || {}).value) || 0)) +
      row("Total revisions", rev.total_revisions != null ? rev.total_revisions : "—") +
      row("Started", (tm.started_at || "").slice(0, 10) || "—") +
      row("Last activity", (tm.latest_activity_at || "").slice(0, 10) || "—") +
      "</div>" +
      "<details><summary>Planning journey (read-only)</summary>" +
      "<h4>Final idea</h4><p>" + esc(plan.idea || "Not linked.") + "</p>" +
      "<h4>Final thesis</h4><p>" + esc(plan.thesis || "Not linked.") + "</p>" +
      "<h4>Final outline</h4><pre>" + esc(outlineTxt) + "</pre>" +
      "<h4>Final reflection</h4><p>" +
      esc(plan.reflection ? (plan.reflection.decision || "") + " / " + (plan.reflection.scaffold || "") : "Not linked.") +
      "</p></details>" +
      "<details><summary>Feedback counts (stored records only)</summary><p>" +
      "Lab feedback items: " + esc(fb.lab_feedback_items != null ? fb.lab_feedback_items : "unknown") + "<br/>" +
      "Currently unresolved: " + esc(JSON.stringify(fb.current_unresolved_lab_rules || {})) +
      "</p></details>" +
      "<details><summary>Revision timeline</summary><pre>" +
      esc(timeline || "No revisions yet.") + "</pre></details>";
  }

  function fmtDurShort(ms) {
    var s = Math.max(0, Math.floor((ms || 0) / 1000));
    var m = Math.floor(s / 60);
    function pad(n) { return (n < 10 ? "0" : "") + n; }
    return pad(m) + ":" + pad(s % 60);
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
    drafts[currentMode()] = SAMPLE_TEXT;
    runAnalysis();
  });

  /* Restore server-saved drafts + readiness after reload (read-only). Only
   * fills sections with no in-memory state, so fresh typing is never lost. */
  async function restoreLabFromServer() {
    if (!labSessionId) return;
    var mem = lastLab();
    if (mem.introduction || mem.body || mem.conclusion) return;
    try {
      const res = await fetch("/api/lab/session/" + encodeURIComponent(labSessionId));
      if (!res.ok) return;
      const s = await readJson(res);
      (s.revisions || []).forEach(function (r) {
        if (!r || ["introduction", "body", "conclusion"].indexOf(r.section) === -1) return;
        var prev = mem[r.section];
        if (!prev || (r.revision_number || 0) > (prev.revision_number || 0)) {
          mem[r.section] = { readiness: r.readiness || {},
            revision_number: r.revision_number, analysis: null,
            lab_session_id: labSessionId };
        }
        if (!drafts[r.section] && r.essay_text
            && currentMode() === r.section && !editor.value.trim()) {
          drafts[r.section] = r.essay_text;
          editor.value = r.essay_text;
          // Same stale-timer guard as fetchLatestDraft: restored text was
          // not typed, so no pending auto-analysis may fire for it.
          if (timer) { clearTimeout(timer); timer = null; }
        }
      });
      updateProgression();
    } catch (e) { /* restore is best-effort only */ }
  }

  document.querySelectorAll("#workspaceTabs .tab").forEach(function (b) {
    b.addEventListener("click", function () {
      var ws = b.getAttribute("data-ws");
      if (ws === "reviewSection") {
        setTimeout(loadReview, 0);
      } else if (ws === "studentSection") {
        setTimeout(restoreLabFromServer, 0);
      }
    });
  });
  [["labToBody", "body"], ["labToConc", "conclusion"]].forEach(function (pair) {
    var b = document.getElementById(pair[0]);
    if (b) b.addEventListener("click", function () { gotoSection(pair[1]); });
  });
  var toReview = document.getElementById("labToReview");
  if (toReview) toReview.addEventListener("click", function () {
    var tab = document.querySelector('#workspaceTabs [data-ws="reviewSection"]');
    if (tab) tab.click();
  });
  var sumBtn = document.getElementById("summaryBtn");
  if (sumBtn) sumBtn.addEventListener("click", function () {
    var el = document.getElementById("processSummary");
    if (el) {
      if (!el.textContent.trim() || el.textContent.indexOf("Analyze") !== -1) loadReview();
      try { el.scrollIntoView({ block: "nearest" }); } catch (e) { /* jsdom */ }
    }
  });
  var sumRefresh = document.getElementById("summaryRefreshBtn");
  if (sumRefresh) sumRefresh.addEventListener("click", loadReview);

  // Test seam + cross-module hook (Stage-4 Continue clears stale drafts).
  window.EssayScaffLab = {
    updateProgression: updateProgression,
    loadReview: loadReview,
    sectionReady: sectionReady,
    drafts: drafts,
    getSessionId: function () { return labSessionId; },
    resetDrafts: function () {
      drafts.introduction = ""; drafts.body = ""; drafts.conclusion = "";
      labSessionId = null;
      try { sessionStorage.removeItem("essayscaff.labSession"); } catch (e) { /* private */ }
      var ES = window.EssayScaff || {};
      ES.lastLab = {};
      editor.value = "";
      updateProgression();
    },
  };
  updateProgression();
})();
