/* EssayScaff Stage 4 workspace client: reflection over stored histories.
 * Read-only plan review, fading reflective questions, student checklist.
 * Nothing is generated: the student revises in Stages 1-3 themselves. */
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
   * Continue-to-Stage-4 carries the real Stage 1 + Stage 2 + Stage 3 session
   * ids here. A stored Stage-4 session from a different chain is never
   * silently reused: session state resets so the next reflection belongs to
   * the current chain. No DB rows are touched — session selection only. */
  function currentChain() {
    return {
      s1: ($("s4Stage1") && $("s4Stage1").value.trim()) || null,
      s2: ($("s4Stage2") && $("s4Stage2").value.trim()) || null,
      s3: ($("s4Stage3") && $("s4Stage3").value.trim()) || null,
    };
  }
  function lastChain() {
    try {
      var d = (window.EssayScaff || {}).lastStage4 || {};
      return {
        s1: d.stage1_session_id || null,
        s2: d.stage2_session_id || null,
        s3: d.stage3_session_id || null,
      };
    } catch (e) { return { s1: null, s2: null, s3: null }; }
  }
  function resetForChain(chain) {
    var prev = lastChain();
    if (sessionId && (prev.s1 !== chain.s1 || prev.s2 !== chain.s2 || prev.s3 !== chain.s3)) {
      sessionId = null;
      try {
        window.EssayScaff = window.EssayScaff || {};
        window.EssayScaff.lastStage4 = null;
      } catch (e) { /* memory only */ }
      var m = $("reflectMeta"); if (m) m.textContent = "";
      var h = $("reflectionHistory");
      if (h) h.innerHTML = '<p class="hint">No reflection revisions yet.</p>';
      var r = $("reflectionReadiness");
      if (r) r.innerHTML = '<p class="hint">Stage 4 not assessed yet.</p>';
    }
  }
  async function fetchPlanRef(id1, id2, id3) {
    if (!id1 && !id2 && !id3) {
      $("stage4PlanRef").innerHTML = "<p>Link at least one session first.</p>";
      return;
    }
    try {
      var parts = [];
      for (const [label, sid, url] of [["Stage 1", id1, "/api/stage1/session/"], ["Stage 2", id2, "/api/stage2/session/"], ["Stage 3", id3, "/api/stage3/session/"]]) {
        if (!sid) continue;
        const res = await fetch(url + encodeURIComponent(sid));
        if (!res.ok) { parts.push("<p>" + label + " session not found.</p>"); continue; }
        const s = await readJson(res);
        const last = s.revisions[s.revisions.length - 1];
        var text = last.idea_text || last.thesis_text || (last.outline || []).map(function (p) { return p.text; }).join(" / ");
        parts.push("<p><strong>" + label + " " + esc(sid) + " — R" + last.revision_number + ":</strong></p><p><em>" +
          esc((text || "").slice(0, 220)) + "</em></p>");
      }
      $("stage4PlanRef").innerHTML = parts.join("") || "<p>No linked sessions.</p>";
    } catch (e) { $("stage4PlanRef").innerHTML = "<p>Link failed: " + esc(e.message) + "</p>"; }
  }
  function applyContinueLink(chain) {
    chain = chain || {};
    var c = { s1: chain.s1 || null, s2: chain.s2 || null, s3: chain.s3 || null };
    resetForChain(c);
    var map = [["s4Stage1", c.s1, "essayscaff.s4Stage1"],
               ["s4Stage2", c.s2, "essayscaff.s4Stage2"],
               ["s4Stage3", c.s3, "essayscaff.s4Stage3"]];
    map.forEach(function (trio) {
      if (!trio[1]) return;
      var el = $(trio[0]);
      if (el) {
        el.value = trio[1];
        try { sessionStorage.setItem(trio[2], trio[1]); } catch (e) { /* private mode */ }
      }
    });
    return fetchPlanRef(c.s1, c.s2, c.s3);
  }
  window.EssayScaffStage4 = {
    applyContinueLink: applyContinueLink,
    fetchPlanRef: fetchPlanRef,
    resetForChain: resetForChain,
    getSessionId: function () { return sessionId; },
  };
  // Refresh restore: Continued links survive reload (values only); the
  // read-only plan reference is re-fetched, never invented.
  try {
    var r1 = sessionStorage.getItem("essayscaff.s4Stage1"),
        r2 = sessionStorage.getItem("essayscaff.s4Stage2"),
        r3 = sessionStorage.getItem("essayscaff.s4Stage3");
    var needsRef = false;
    [["s4Stage1", r1], ["s4Stage2", r2], ["s4Stage3", r3]].forEach(function (pair) {
      var el = $(pair[0]);
      if (pair[1] && el && !el.value) { el.value = pair[1]; needsRef = true; }
    });
    if (needsRef) {
      var cc = currentChain();
      fetchPlanRef(cc.s1, cc.s2, cc.s3);
    }
  } catch (e) { /* private mode */ }

  function wsTab(sectionId) {
    var tab = document.querySelector('#workspaceTabs [data-ws="' + sectionId + '"]');
    if (tab) tab.click();
  }

  /* Stage 4 → Writing Lab (normal student flow; direct-tab access stays).
   * The button appears only once reflection reaches an appropriate state
   * (READY_FOR_INDEPENDENT_REVIEW or COMPLETE — readiness itself is
   * untouched; this only gates the affordance). Clicking carries the
   * CURRENT chain context into the lab (overwriting stale browser state)
   * and opens the Writing Lab. The student still writes everything. */
  var LAB_READY = { READY_FOR_INDEPENDENT_REVIEW: 1, COMPLETE: 1 };
  function updateLabButton(readiness) {
    var btn = $("labBtn");
    if (!btn) return;
    var dec = (readiness || {}).decision;
    btn.hidden = !LAB_READY[dec];
  }
  /* Read-only topic/keyword lookup across response shapes: top-level
   * fields (Stage 2), embedded phase-2 echo (every analysis object), or
   * the Stage-4 snapshot. No invention — null when absent everywhere. */
  function datumTopic(d) {
    if (!d) return null;
    if (d.topic) return d.topic;
    var ph = d.analysis && d.analysis.technical && d.analysis.technical.phase2;
    if (ph && ph.topic) return ph.topic;
    if (d.snapshot && d.snapshot.topic) return d.snapshot.topic;
    return null;
  }
  function datumKeywords(d) {
    if (!d) return null;
    function arr(v) {
      return v.filter(function (k) { return k && String(k).trim(); });
    }
    if (Array.isArray(d.teacher_keywords) && d.teacher_keywords.length) return arr(d.teacher_keywords);
    var ph = d.analysis && d.analysis.technical && d.analysis.technical.phase2;
    if (ph && Array.isArray(ph.teacher_keywords) && ph.teacher_keywords.length) return arr(ph.teacher_keywords);
    if (d.snapshot && Array.isArray(d.snapshot.teacher_keywords) && d.snapshot.teacher_keywords.length) {
      return arr(d.snapshot.teacher_keywords);
    }
    return null;
  }
  function chainTopic() {
    try {
      var ES = window.EssayScaff || {};
      return datumTopic(ES.lastStage1) || datumTopic(ES.lastStage2) ||
        datumTopic(ES.lastStage3) || datumTopic(ES.lastStage4);
    } catch (e) { return null; }
  }
  function chainKeywords() {
    try {
      var ES = window.EssayScaff || {};
      return datumKeywords(ES.lastStage1) || datumKeywords(ES.lastStage2) ||
        datumKeywords(ES.lastStage3) || datumKeywords(ES.lastStage4);
    } catch (e) { return null; }
  }
  function chainSessions() {
    try {
      var ES = window.EssayScaff || {};
      return {
        stage1_session_id: ((ES.lastStage1 || {}).session_id) || null,
        stage2_session_id: ((ES.lastStage2 || {}).session_id) || null,
        stage3_session_id: ((ES.lastStage3 || {}).session_id) || null,
        stage4_session_id: ((ES.lastStage4 || {}).session_id) || null,
      };
    } catch (e) {
      return { stage1_session_id: null, stage2_session_id: null, stage3_session_id: null, stage4_session_id: null };
    }
  }
  function carryChainToLab() {
    var topic = chainTopic(), kws = chainKeywords();
    var tEl = $("topic"), kEl = $("teacherKeywords");
    // Current chain wins: overwrite stale lab/browser values outright.
    if (tEl && topic) tEl.value = topic;
    if (kEl && kws && kws.length) kEl.value = kws.join(", ");
    try {
      if (topic) sessionStorage.setItem("essayscaff.labTopic", topic);
      if (kws && kws.length) sessionStorage.setItem("essayscaff.labKeywords", kws.join(", "));
      sessionStorage.setItem("essayscaff.labChain", JSON.stringify(chainSessions()));
      window.EssayScaff = window.EssayScaff || {};
      window.EssayScaff.labChain = chainSessions();
    } catch (e) { /* private mode */ }
    if (window.EssayScaffFeedback) window.EssayScaffFeedback.refreshLabStarter();
  }
  window.EssayScaffStage4 = window.EssayScaffStage4 || {};
  window.EssayScaffStage4.updateLabButton = updateLabButton;
  window.EssayScaffStage4.carryChainToLab = carryChainToLab;
  window.EssayScaffStage4.chainSessions = chainSessions;

  $("labBtn").addEventListener("click", function () {
    carryChainToLab();
    wsTab("studentSection");
  });

  $("s4LinkBtn").addEventListener("click", async function () {
    var id1 = $("s4Stage1").value.trim(), id2 = $("s4Stage2").value.trim(), id3 = $("s4Stage3").value.trim();
    resetForChain({ s1: id1 || null, s2: id2 || null, s3: id3 || null });
    try {
      [["s4Stage1", id1], ["s4Stage2", id2], ["s4Stage3", id3]].forEach(function (pair) {
        if (pair[1]) sessionStorage.setItem("essayscaff." + pair[0], pair[1]);
      });
    } catch (e) { /* private mode */ }
    await fetchPlanRef(id1, id2, id3);
  });

  $("reflectBtn").addEventListener("click", async function () {
    // Never silently append to a stale session from another chain.
    resetForChain(currentChain());
    $("reflectStatus").textContent = "Reflecting on your plan...";
    try {
      const res = await fetch("/api/stage4/reflect", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: sessionId,
          stage1_session_id: $("s4Stage1").value.trim() || null,
          stage2_session_id: $("s4Stage2").value.trim() || null,
          stage3_session_id: $("s4Stage3").value.trim() || null,
          student_note: $("reflectNote").value || null,
          conclusion: $("conclusionText").value.trim() || null,
        }),
      });
      const d = await readJson(res);
      if (!res.ok) { $("reflectStatus").textContent = d.error || "Reflection failed."; return; }
      sessionId = d.session_id;
      window.EssayScaff = window.EssayScaff || {};
      window.EssayScaff.lastStage4 = d;
      $("reflectStatus").textContent = "Done — revision " + d.revision_number + ".";
      renderStudent(d);
      renderStage4Tab(d);
      loadHistory();
    } catch (e) { $("reflectStatus").textContent = "Request failed: " + e.message; }
  });

  function renderStudent(d) {
    // Progressive scaffolding: exactly one primary card in the active feed
    // (backend priority order). Full history stays in Revisions/Progress.
    var reflectCards = (d.prompts.prompts || []).map(function (p) {
      return '<div class="prompt"><strong>' + esc(p.text) + "</strong>" +
        '<div class="meta">Detail: ' + esc(p.detail_level || "") + "</div></div>";
    });
    if (window.EssayScaffFeedback) {
      window.EssayScaffFeedback.renderOne("reflectionPrompts", reflectCards, "<p>No questions right now.</p>");
      var p4 = (d.prompts.prompts || [])[0] || null;
      window.EssayScaffFeedback.setWhy("reflectionPrompts", p4 ? {
        stageLabel: "Stage 4", label: "Reflection guidance",
        explanation: null, evidence: null,
      } : null);
    } else {
      $("reflectionPrompts").innerHTML = reflectCards.join("") || "<p>No questions right now.</p>";
    }
    var r = d.readiness || {};
    var cmp = (d.comparison.messages || []).map(function (m) {
      return "<li>" + esc(m.text) + "</li>";
    }).join("");
    var sc = d.scaffold || {};
    var checklist = "";
    if (sc.level === 1 || sc.level === 0) {
      checklist = "<p><strong>Review checklist (yours to check):</strong></p><ul>" +
        (d.checklist || []).map(function (item) {
          return '<li><label><input type="checkbox" /> ' + esc(item) + "</label></li>";
        }).join("") + "</ul>";
    }
    var links = (d.return_links || []).map(function (l) {
      return '<button type="button" data-goto="' + esc({ 1: "stage1Section", 2: "stage2Section", 3: "stage3Section" }[l.stage] || "stage1Section") + '">' +
        esc(l.action) + (l.rule_id ? " (" + esc(l.rule_id) + ")" : "") + "</button>";
    }).join(" ");
    $("reflectionStatus").innerHTML =
      "<p><strong>" + esc(r.decision || "") + "</strong></p><p>" + esc(r.student_message || "") + "</p>" +
      "<p>Scaffold: <strong>" + esc(sc.label || "") + "</strong> — " + esc(sc.reason || "") + "</p>" +
      checklist +
      (links ? '<div class="controls">' + links + "</div>" : "") +
      (cmp ? "<p>Since your last reflection:</p><ul>" + cmp + "</ul>" : "");
    document.querySelectorAll("#reflectionStatus [data-goto]").forEach(function (b) {
      b.addEventListener("click", function () { wsTab(b.getAttribute("data-goto")); });
    });
    $("reflectionReadiness").innerHTML =
      "<p><strong>" + esc(r.decision || "") + "</strong></p><p>" + esc(r.student_message || "") + "</p>";
    // The Writing Lab affordance appears only at an appropriate Stage-4
    // state; readiness itself is untouched.
    updateLabButton(r);
    if (window.EssayScaffFeedback) window.EssayScaffFeedback.updateFeedbackFocus();
  }

  async function loadHistory() {
    if (!sessionId) return;
    try {
      const res = await fetch("/api/stage4/session/" + encodeURIComponent(sessionId));
      if (!res.ok) return;
      const s = await readJson(res);
      $("reflectionHistory").innerHTML = s.revisions.map(function (r) {
        var lvl = (r.scaffold || {}).label || "";
        return '<div class="rev"><strong>R' + r.revision_number + "</strong> — " +
          esc(r.readiness.decision) + " (" + esc(lvl) + ")</div>";
      }).join("");
    } catch (e) { /* secondary */ }
  }

  function renderStage4Tab(d) {
    var gears = (d.stage4_transparency || []).map(function (g) {
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
    var rules = (d.rules || []).map(function (r) {
      return "<p><code>" + esc(r.rule_id) + "</code> [" + esc(r.status) + "] — " + esc(r.reason || "") + "</p>";
    }).join("");
    var sc = d.scaffold || {};
    $("tab-stage4").innerHTML =
      "<h4>Session " + esc(d.session_id) + " — revision " + d.revision_number + "</h4>" +
      "<h4>Scaffold decision</h4>" +
      "<p>Level <strong>" + esc(sc.level) + " (" + esc(sc.label || "") + ")</strong></p>" +
      "<pre>" + esc(JSON.stringify(sc.evidence || {}, null, 1)) + "</pre>" +
      "<p><strong>Rule:</strong> " + esc(sc.decision_rule || "") + "</p>" +
      "<p><strong>Reason:</strong> " + esc(sc.reason || "") + "</p>" +
      "<h4>Prompt backtrace</h4>" + (d.prompts.prompts || []).map(function (p) {
        return '<div class="trace"><ol class="chain">' +
          "<li><strong>" + esc("Prompt " + p.prompt_id) + "</strong>" +
            '<span class="chain-sub">' + esc(p.text) + " [" + esc(p.detail_level || "") + "]</span></li>" +
          "<li><strong>" + esc("Rule " + p.rule_id) + "</strong>" +
            '<span class="chain-sub">' + esc(p.why_shown || "") + "</span></li>" +
          "<li><strong>Issue history → scaffold level → template variant</strong></li>" +
          "</ol></div>";
      }).join("") +
      "<h4>Issue history</h4><pre>" +
      esc(JSON.stringify((d.history || {}).by_rule || {}, null, 1).slice(0, 4000)) + "</pre>" +
      "<h4>Readiness</h4>" + (d.readiness.conditions || []).map(function (c) {
        return "<p>" + esc(c.id) + " " + esc(c.name) + ": <strong>" + esc(c.result) + "</strong> — " + esc(c.detail) + "</p>";
      }).join("") +
      "<h4>Stage timings (measured ms)</h4><pre>" + esc(JSON.stringify(d.timings, null, 1)) + "</pre>" +
      "<h4>Reflect rules</h4>" + rules + "<h4>Pipeline gears</h4>" + gears;
  }
})();
