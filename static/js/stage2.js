/* EssayScaff Stage 2 workspace client: thesis -> scaffolding -> revision.
 * Mentor tone: components, questions, progress. No scores, no vectors. */
(function () {
  "use strict";

  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }
  function $(id) { return document.getElementById(id); }
  async function readJson(res) {
    try { return await res.json(); }
    catch (e) { return { error: "Request failed (HTTP " + res.status + ")." }; }
  }

  var sessionId = null;

  /* Cross-stage chain linking (normal student flow; research mode untouched).
   * Continue-to-Stage-2 carries the real Stage 1 session id here. The link
   * field stays manually editable for researcher/testing use. If the stored
   * in-memory Stage-2 session belongs to a DIFFERENT parent (e.g. an older
   * unlinked test session), it is NOT reused: session state resets so the
   * next analysis mints/loads the session for the current chain. No DB rows
   * are touched — this is session selection only. */
  function currentParent() {
    var el = $("s2Stage1");
    return (el && el.value.trim()) || null;
  }
  function lastParent() {
    try {
      var d = (window.EssayScaff || {}).lastStage2;
      return (d && d.stage1_session_id) || null;
    } catch (e) { return null; }
  }
  function resetForParent(parentId) {
    if (sessionId && lastParent() !== parentId) {
      sessionId = null;
      try {
        window.EssayScaff = window.EssayScaff || {};
        window.EssayScaff.lastStage2 = null;
      } catch (e) { /* memory only */ }
      var m = $("thesisMeta"); if (m) m.textContent = "";
      var h = $("thesisHistory");
      if (h) h.innerHTML = '<p class="hint">No thesis revisions yet.</p>';
      var r = $("thesisReadiness");
      if (r) r.innerHTML = '<p class="hint">Stage 2 not assessed yet.</p>';
      var c = $("thesisComponents");
      if (c) c.innerHTML = '<p class="hint">Thesis components will appear here.</p>';
      var p = $("thesisPrompts");
      if (p) p.innerHTML = '<p class="hint">Stage 2 reflective questions will appear here.</p>';
    }
  }
  async function fetchStage1Ref(id) {
    if (!id) {
      $("stage1IdeaRef").innerHTML = "<p class=\"hint\">Link a Stage 1 session to see your developed idea here. Your idea is never rewritten into a thesis.</p>";
      return;
    }
    try {
      const res = await fetch("/api/stage1/session/" + encodeURIComponent(id));
      if (!res.ok) { $("stage1IdeaRef").innerHTML = "<p>Stage 1 session not found.</p>"; return; }
      const s = await readJson(res);
      const last = s.revisions[s.revisions.length - 1];
      $("stage1IdeaRef").innerHTML = "<p><strong>Session " + esc(id) + " — final idea (R" +
        last.revision_number + "):</strong></p><p><em>" + esc(last.idea_text) + "</em></p>";
    } catch (e) { $("stage1IdeaRef").innerHTML = "<p>Link failed: " + esc(e.message) + "</p>"; }
  }
  function applyContinueLink(id) {
    if (!id) return Promise.resolve();
    resetForParent(id);
    var el = $("s2Stage1");
    if (el) {
      el.value = id;
      try { sessionStorage.setItem("essayscaff.s2Stage1", id); } catch (e) { /* private mode */ }
    }
    return fetchStage1Ref(id);
  }
  // Test seam + Continue-navigation hook (no production behavior change
  // beyond the documented auto-link on Continue).
  window.EssayScaffStage2 = {
    applyContinueLink: applyContinueLink,
    fetchStage1Ref: fetchStage1Ref,
    resetForParent: resetForParent,
    getSessionId: function () { return sessionId; },
  };
  // Refresh restore: a Continued link survives reload (value only); the
  // read-only reference is re-fetched, never invented.
  try {
    var savedS1 = sessionStorage.getItem("essayscaff.s2Stage1");
    var s1el = $("s2Stage1");
    if (savedS1 && s1el && !s1el.value) { s1el.value = savedS1; fetchStage1Ref(savedS1); }
  } catch (e) { /* private mode */ }

  $("stage3Btn").addEventListener("click", function () {
    try {
      var id = sessionId || (((window.EssayScaff || {}).lastStage2 || {}).session_id) || null;
      if (id && window.EssayScaffStage3 && window.EssayScaffStage3.applyContinueLink) {
        window.EssayScaffStage3.applyContinueLink(id);
      } else if (id) {
        var el = document.getElementById("s3Stage2");
        if (el && !el.value) el.value = id;
      }
    } catch (e) { /* navigation must never break */ }
    var tab = document.querySelector('#workspaceTabs [data-ws="stage3Section"]');
    if (tab) tab.click();
  });

  $("s2LinkBtn").addEventListener("click", async function () {
    var id = $("s2Stage1").value.trim();
    if (!id) { fetchStage1Ref(null); return; }
    resetForParent(id);
    try { sessionStorage.setItem("essayscaff.s2Stage1", id); } catch (e) { /* private mode */ }
    await fetchStage1Ref(id);
  });

  $("thesisBtn").addEventListener("click", async function () {
    var text = $("thesisEditor").value;
    if (!text || !text.trim()) { $("thesisStatus").textContent = "Write your thesis first."; return; }
    // Never silently append to a stale session from another chain: the
    // current link field wins, and a mismatch starts a fresh session.
    resetForParent(currentParent());
    $("thesisStatus").textContent = "Analyzing your thesis...";
    try {
      const res = await fetch("/api/stage2/analyze", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: text, session_id: sessionId, stage1_session_id: $("s2Stage1").value.trim() || null }),
      });
      const d = await readJson(res);
      if (!res.ok) { $("thesisStatus").textContent = d.error || "Analysis failed."; return; }
      sessionId = d.session_id;
      window.EssayScaff = window.EssayScaff || {};
      window.EssayScaff.lastStage2 = d;
      $("thesisStatus").textContent = "Done — revision " + d.revision_number + ".";
      renderStudent(d);
      renderStage2Tab(d);
      loadHistory();
    } catch (e) { $("thesisStatus").textContent = "Request failed: " + e.message; }
  });

  function renderStudent(d) {
    var c = d.components || {};
    $("thesisComponents").innerHTML =
      "<table>" +
      "<tr><th>Main subject</th><td>" + esc(c.detected_subject || "not detected") + "</td>" +
      "<th>Main predicate</th><td>" + esc(c.main_verb || "not detected") + "</td></tr>" +
      "<tr><th>Important concepts</th><td colspan='3'>" +
      ((c.important_concepts || []).map(function (x) { return '<span class="chip">' + esc(x) + "</span>"; }).join("") || "none") +
      "</td></tr></table>" +
      (d.alignment && d.alignment.classification ? "<p>Stage 1 idea connection: <strong>" + esc(d.alignment.classification) + "</strong></p>" : "");
    // Progressive scaffolding: exactly one primary card in the active feed
    // (backend priority order). Full history stays in Revisions/Progress.
    var thesisCards = (d.prompts.prompts || []).map(function (p) {
      return '<div class="prompt"><strong>' + esc(p.text) + "</strong>" +
        '<div class="meta">Priority: ' + esc(p.priority) + "</div></div>";
    });
    if (window.EssayScaffFeedback) {
      window.EssayScaffFeedback.renderOne("thesisPrompts", thesisCards, "<p>No questions right now.</p>");
      var p2 = (d.prompts.prompts || [])[0] || null;
      window.EssayScaffFeedback.setWhy("thesisPrompts", p2 ? {
        stageLabel: "Stage 2", label: "Priority " + (p2.priority || "guidance"),
        explanation: p2.why_shown || null,
        evidence: p2.target ? "About: " + p2.target : null,
      } : null);
      window.EssayScaffFeedback.markBlocking("thesisPrompts",
        p2 ? p2.rule_id : null, d.readiness, "stage3_allowed");
      window.EssayScaffFeedback.updateFeedbackFocus();
    } else {
      $("thesisPrompts").innerHTML = thesisCards.join("") || "<p>No questions right now.</p>";
    }
    var r = d.readiness || {};
    var cmp = (d.comparison.messages || []).map(function (m) {
      return "<li>" + esc(m.text) + "</li>";
    }).join("");
    $("thesisReadiness").innerHTML =
      "<p><strong>" + esc(r.decision || "") + "</strong></p>" +
      "<p>" + esc(r.student_message || "") + "</p>" +
      (cmp ? "<p>Since your last revision:</p><ul>" + cmp + "</ul>" : "");
    $("stage3Btn").disabled = !r.stage3_allowed;
  }

  async function loadHistory() {
    if (!sessionId) return;
    try {
      const res = await fetch("/api/stage2/session/" + encodeURIComponent(sessionId));
      if (!res.ok) return;
      const s = await readJson(res);
      $("thesisHistory").innerHTML = s.revisions.map(function (r) {
        return '<div class="rev"><strong>R' + r.revision_number + "</strong> — " +
          esc(r.readiness.decision) + "<br/><em>" + esc(r.thesis_text.slice(0, 160)) +
          (r.thesis_text.length > 160 ? "…" : "") + "</em></div>";
      }).join("");
    } catch (e) { /* secondary; never break the workspace */ }
  }

  function renderStage2Tab(d) {
    var gears = (d.stage2_transparency || []).map(function (g) {
      return "<h4>" + g.number + ". " + esc(g.name) +
        ' <span class="badge">' + esc(g.status) + "</span></h4>" +
        "<p><strong>Purpose:</strong> " + esc(g.purpose) + "</p>" +
        "<p><strong>Source:</strong> <code>" + esc(g.file) + "</code> :: <code>" + esc(g.function) + "</code></p>" +
        "<p><strong>Input:</strong></p><pre>" + esc(JSON.stringify(g.input, null, 1).slice(0, 2000)) + "</pre>" +
        "<p><strong>Process:</strong> " + esc(typeof g.process === "string" ? g.process : JSON.stringify(g.process)) + "</p>" +
        "<p><strong>Output (truncated):</strong></p><pre>" + esc(JSON.stringify(g.output, null, 1).slice(0, 4000)) + "</pre>" +
        "<p><strong>Timing:</strong> " + (g.timing_ms === null || g.timing_ms === undefined
          ? esc(g.timing_status || "NOT_MEASURED_SEPARATELY")
          : Number(g.timing_ms).toFixed(2) + " ms (measured)") +
        (g.next ? " → <strong>Next:</strong> " + esc(g.next) : "") + "</p>";
    }).join("");
    var rules = (d.thesis_rules || []).map(function (r) {
      return "<p><code>" + esc(r.rule_id) + "</code> [" + esc(r.status) + "] — " + esc(r.condition || "") +
        " → " + (r.result ? "TRUE" : (r.status === "OBSERVED" ? "OBSERVED" : "FALSE")) + "<br/><em>" + esc(r.reason || "") + "</em></p>";
    }).join("");
    $("tab-stage2").innerHTML =
      "<h4>Session " + esc(d.session_id) + " — revision " + d.revision_number +
      (d.stage1_session_id ? " (linked " + esc(d.stage1_session_id) + ")" : " (no Stage 1 link)") + "</h4>" +
      "<h4>Prompt backtrace</h4>" + (d.prompts.prompts || []).map(function (p) {
        var rule = (d.thesis_rules || []).find(function (r) { return r.rule_id === p.rule_id; }) || {};
        return '<div class="trace"><ol class="chain">' +
          "<li><strong>" + esc("Prompt " + p.prompt_id) + "</strong>" +
            '<span class="chain-sub">' + esc(p.text) + "</span></li>" +
          "<li><strong>" + esc("Rule " + p.rule_id) + "</strong>" +
            '<span class="chain-sub">' + esc(rule.condition || p.rule_id) + "</span></li>" +
          "<li><strong>Components</strong><dl class=\"kv\"><div><dt>subject</dt><dd>" +
            esc((d.components || {}).detected_subject || "—") + "</dd></div><div><dt>verb</dt><dd>" +
            esc((d.components || {}).main_verb || "—") + "</dd></div></dl></li>" +
          "<li><strong>Thesis sentence → raw thesis text</strong></li>" +
          "</ol></div>";
      }).join("") +
      "<h4>Alignment</h4><pre>" + esc(JSON.stringify(d.alignment, null, 1)) + "</pre>" +
      "<h4>Readiness</h4>" + (d.readiness.conditions || []).map(function (c) {
        return "<p>" + esc(c.id) + " " + esc(c.name) + ": <strong>" + esc(c.result) + "</strong> — " + esc(c.detail) + "</p>";
      }).join("") +
      "<h4>Stage timings (measured ms)</h4><pre>" + esc(JSON.stringify(d.timings, null, 1)) + "</pre>" +
      "<h4>Thesis rules</h4>" + rules + "<h4>Pipeline gears</h4>" + gears;
  }
})();
