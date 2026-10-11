/* EssayScaff Stage 3 workspace client: student-owned outline editor.
 * Points/details, reorder (Move Up/Down), add/delete with confirm.
 * Nothing is generated: empty nodes stay empty until the student writes. */
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
  var points = [{ text: "", details: [""] }, { text: "", details: [""] }];

  /* Cross-stage chain linking (normal student flow; research mode untouched).
   * Continue-to-Stage-3 carries the real Stage 2 session id here. A stored
   * Stage-3 session from a different parent chain is never silently reused:
   * session state resets so the next analysis belongs to the current chain.
   * No DB rows are touched — session selection only. */
  function currentParent() {
    var el = $("s3Stage2");
    return (el && el.value.trim()) || null;
  }
  function lastParent() {
    try {
      var d = (window.EssayScaff || {}).lastStage3;
      return (d && d.stage2_session_id) || null;
    } catch (e) { return null; }
  }
  function resetForParent(parentId) {
    if (sessionId && lastParent() !== parentId) {
      sessionId = null;
      try {
        window.EssayScaff = window.EssayScaff || {};
        window.EssayScaff.lastStage3 = null;
      } catch (e) { /* memory only */ }
      var m = $("outlineMeta"); if (m) m.textContent = "";
      var h = $("outlineHistory");
      if (h) h.innerHTML = '<p class="hint">No outline revisions yet.</p>';
      var r = $("outlineReadiness");
      if (r) r.innerHTML = '<p class="hint">Stage 3 not assessed yet.</p>';
      var t = $("outlineTree");
      if (t) t.innerHTML = '<p class="hint">Your outline tree will appear here.</p>';
      var p = $("outlinePrompts");
      if (p) p.innerHTML = '<p class="hint">Stage 3 reflective questions will appear here.</p>';
    }
  }
  async function fetchStage2Ref(id) {
    if (!id) {
      $("stage2ThesisRef").innerHTML = "<p class=\"hint\">Link a Stage 2 session to see your thesis here. It is never turned into outline points for you.</p>";
      return;
    }
    try {
      const res = await fetch("/api/stage2/session/" + encodeURIComponent(id));
      if (!res.ok) { $("stage2ThesisRef").innerHTML = "<p>Stage 2 session not found.</p>"; return; }
      const s = await readJson(res);
      const last = s.revisions[s.revisions.length - 1];
      $("stage2ThesisRef").innerHTML = "<p><strong>Session " + esc(id) + " — thesis (R" +
        last.revision_number + "):</strong></p><p><em>" + esc(last.thesis_text) + "</em></p>";
    } catch (e) { $("stage2ThesisRef").innerHTML = "<p>Link failed: " + esc(e.message) + "</p>"; }
  }
  function applyContinueLink(id) {
    if (!id) return Promise.resolve();
    resetForParent(id);
    var el = $("s3Stage2");
    if (el) {
      el.value = id;
      try { sessionStorage.setItem("essayscaff.s3Stage2", id); } catch (e) { /* private mode */ }
    }
    return fetchStage2Ref(id);
  }
  window.EssayScaffStage3 = {
    applyContinueLink: applyContinueLink,
    fetchStage2Ref: fetchStage2Ref,
    resetForParent: resetForParent,
    getSessionId: function () { return sessionId; },
  };
  try {
    var savedS2 = sessionStorage.getItem("essayscaff.s3Stage2");
    var s2el = $("s3Stage2");
    if (savedS2 && s2el && !s2el.value) { s2el.value = savedS2; fetchStage2Ref(savedS2); }
  } catch (e) { /* private mode */ }

  $("stage4Btn").addEventListener("click", async function () {
    // Normal student flow: carry the REAL chain (Stage 1 + Stage 2 +
    // Stage 3 session ids) into Stage 4 automatically.
    try {
      var ES = window.EssayScaff || {};
      var s3 = sessionId || ((ES.lastStage3 || {}).session_id) || null;
      var s2 = ((ES.lastStage2 || {}).session_id) || null;
      if (!s2) {
        var f2 = document.getElementById("s3Stage2");
        if (f2 && f2.value.trim()) s2 = f2.value.trim();
      }
      var s1 = ((ES.lastStage1 || {}).session_id) || null;
      if (!s1) {
        var f1 = document.getElementById("s2Stage1");
        if (f1 && f1.value.trim()) s1 = f1.value.trim();
      }
      // Manual/research fallback: this browser never held Stage-1 data, but
      // Stage 3 has a linked Stage-2 session. Resolve the stored Stage-1
      // parent from the Stage-2 record via the existing session endpoint —
      // never invented, never inferred from UI history. Unlinked Stage 3
      // (no/unknown Stage-2 session) stays honestly partial.
      if (!s1 && s2) {
        try {
          const res = await fetch("/api/stage2/session/" + encodeURIComponent(s2));
          if (res.ok) {
            const s = await readJson(res);
            const revs = s.revisions || [];
            const last = revs[revs.length - 1] || {};
            if (last.stage1_session_id) s1 = last.stage1_session_id;
          }
        } catch (e) { /* honestly partial: s1 stays empty */ }
      }
      if ((s1 || s2 || s3) && window.EssayScaffStage4 && window.EssayScaffStage4.applyContinueLink) {
        window.EssayScaffStage4.applyContinueLink({ s1: s1, s2: s2, s3: s3 });
      }
    } catch (e) { /* navigation must never break */ }
    var tab = document.querySelector('#workspaceTabs [data-ws="stage4Section"]');
    if (tab) tab.click();
  });

  $("s3LinkBtn").addEventListener("click", async function () {
    var id = $("s3Stage2").value.trim();
    if (!id) { fetchStage2Ref(null); return; }
    resetForParent(id);
    try { sessionStorage.setItem("essayscaff.s3Stage2", id); } catch (e) { /* private mode */ }
    await fetchStage2Ref(id);
  });

  function outlineButton(label, attrs, onClick, disabled) {
    var b = document.createElement("button");
    b.type = "button";
    b.textContent = label;
    Object.keys(attrs).forEach(function (k) { b.setAttribute(k, attrs[k]); });
    if (disabled) b.disabled = true;
    b.addEventListener("click", onClick);
    return b;
  }

  function renderEditor() {
    // Student text is assigned via input.value / textContent only — it is
    // never interpolated into HTML markup, so quotes and angle brackets in
    // outline content stay literal text and cannot break out of attributes.
    // Only computed integers flow into data-* attributes.
    var host = $("outlineEditor");
    host.textContent = "";
    points.forEach(function (p, i) {
      var block = document.createElement("div");
      block.className = "point-block";
      var h = document.createElement("h4");
      h.textContent = "Body Point " + (i + 1);
      block.appendChild(h);
      var lab = document.createElement("label");
      lab.textContent = "Main Point / Topic Sentence:";
      block.appendChild(lab);
      var input = document.createElement("input");
      input.setAttribute("data-p", String(i));
      input.className = "point-input";
      input.type = "text";
      input.value = p.text == null ? "" : String(p.text);
      input.size = 60;
      input.setAttribute("aria-label", "Main point for body point " + (i + 1));
      input.addEventListener("input", function () {
        points[Number(input.getAttribute("data-p"))].text = input.value;
      });
      block.appendChild(input);
      var controls = document.createElement("div");
      controls.className = "controls";
      controls.appendChild(outlineButton("+ Add Supporting Detail", { "data-add-detail": String(i) },
        function (ev) {
          points[Number(ev.currentTarget.getAttribute("data-add-detail"))].details.push("");
          renderEditor();
        }));
      controls.appendChild(outlineButton("Move Up", { "data-move-up": String(i) },
        function (ev) {
          var k = Number(ev.currentTarget.getAttribute("data-move-up"));
          var tmp = points[k - 1]; points[k - 1] = points[k]; points[k] = tmp; renderEditor();
        }, i === 0));
      controls.appendChild(outlineButton("Move Down", { "data-move-down": String(i) },
        function (ev) {
          var k = Number(ev.currentTarget.getAttribute("data-move-down"));
          var tmp = points[k + 1]; points[k + 1] = points[k]; points[k] = tmp; renderEditor();
        }, i === points.length - 1));
      controls.appendChild(outlineButton("Delete Point", { "data-del-point": String(i) },
        function (ev) {
          if (!confirm("Delete this body point and its details?")) return;
          points.splice(Number(ev.currentTarget.getAttribute("data-del-point")), 1); renderEditor();
        }));
      block.appendChild(controls);
      p.details.forEach(function (d, j) {
        var row = document.createElement("div");
        row.className = "detail-row";
        var dlab = document.createElement("label");
        dlab.textContent = "Supporting Detail " + (j + 1) + ":";
        row.appendChild(dlab);
        var din = document.createElement("input");
        din.setAttribute("data-p", String(i));
        din.setAttribute("data-d", String(j));
        din.className = "detail-input";
        din.type = "text";
        din.value = d == null ? "" : String(d);
        din.size = 60;
        din.setAttribute("aria-label", "Supporting detail " + (j + 1) + " for body point " + (i + 1));
        din.addEventListener("input", function () {
          points[Number(din.getAttribute("data-p"))].details[Number(din.getAttribute("data-d"))] = din.value;
        });
        row.appendChild(din);
        row.appendChild(document.createTextNode(" "));
        row.appendChild(outlineButton("Delete", { "data-del-detail": i + ":" + j },
          function (ev) {
            var parts = ev.currentTarget.getAttribute("data-del-detail").split(":");
            if (!confirm("Delete this supporting detail?")) return;
            points[Number(parts[0])].details.splice(Number(parts[1]), 1); renderEditor();
          }));
        block.appendChild(row);
      });
      host.appendChild(block);
    });
  }

  $("addPointBtn").addEventListener("click", function () {
    if (points.length >= 6) { alert("Maximum 6 body points for this workspace."); return; }
    points.push({ text: "", details: [""] }); renderEditor();
  });

  $("outlineBtn").addEventListener("click", async function () {
    // Never silently append to a stale session from another chain.
    resetForParent(currentParent());
    var outline = points.map(function (p) {
      return { text: p.text, details: p.details.filter(function (d) { return d.trim() !== ""; }) };
    });
    $("outlineStatus").textContent = "Analyzing your outline...";
    try {
      const res = await fetch("/api/stage3/analyze", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ outline: outline, session_id: sessionId, stage2_session_id: $("s3Stage2").value.trim() || null }),
      });
      const d = await readJson(res);
      if (!res.ok) { $("outlineStatus").textContent = d.error || "Analysis failed."; return; }
      sessionId = d.session_id;
      window.EssayScaff = window.EssayScaff || {};
      window.EssayScaff.lastStage3 = d;
      $("outlineStatus").textContent = "Done — revision " + d.revision_number + ".";
      renderStudent(d);
      renderStage3Tab(d);
      loadHistory();
    } catch (e) { $("outlineStatus").textContent = "Request failed: " + e.message; }
  });

  function renderStudent(d) {
    // Progressive scaffolding: exactly one primary card in the active feed
    // (backend priority order). Full history stays in Revisions/Progress.
    var outlineCards = (d.prompts.prompts || []).map(function (p) {
      var tgt = p.target ? " (" + esc(p.target) + ")" : "";
      return '<div class="prompt"><strong>' + esc(p.text) + "</strong>" +
        '<div class="meta">Priority: ' + esc(p.priority) + tgt + "</div></div>";
    });
    if (window.EssayScaffFeedback) {
      window.EssayScaffFeedback.renderOne("outlinePrompts", outlineCards, "<p>No questions right now.</p>");
      var p3 = (d.prompts.prompts || [])[0] || null;
      window.EssayScaffFeedback.setWhy("outlinePrompts", p3 ? {
        stageLabel: "Stage 3", label: "Priority " + (p3.priority || "guidance"),
        explanation: p3.why_shown || null,
        evidence: p3.target ? "About: " + p3.target : null,
      } : null);
      window.EssayScaffFeedback.markBlocking("outlinePrompts",
        p3 ? p3.rule_id : null, d.readiness, "stage4_allowed");
      window.EssayScaffFeedback.updateFeedbackFocus();
    } else {
      $("outlinePrompts").innerHTML = outlineCards.join("") || "<p>No questions right now.</p>";
    }
    var tree = "<p><strong>Thesis</strong></p><ul>" + (d.outline || []).map(function (p, i) {
      return "<li><strong>Point " + (i + 1) + ":</strong> " + esc(p.text || "<em>Supporting detail not added yet</em>") + "<ul>" +
        (p.details.length ? p.details.map(function (x) { return "<li>" + esc(x) + "</li>"; }).join("")
          : "<li><em>Supporting detail not added yet</em></li>") + "</ul></li>";
    }).join("") + "</ul>";
    $("outlineTree").innerHTML = tree;
    var r = d.readiness || {};
    var cmp = (d.comparison.messages || []).map(function (m) {
      return "<li>" + esc(m.text) + "</li>";
    }).join("");
    $("outlineReadiness").innerHTML =
      "<p><strong>" + esc(r.decision || "") + "</strong></p><p>" + esc(r.student_message || "") + "</p>" +
      (cmp ? "<p>Since your last revision:</p><ul>" + cmp + "</ul>" : "");
    $("stage4Btn").disabled = !r.stage4_allowed;
  }

  async function loadHistory() {
    if (!sessionId) return;
    try {
      const res = await fetch("/api/stage3/session/" + encodeURIComponent(sessionId));
      if (!res.ok) return;
      const s = await readJson(res);
      $("outlineHistory").innerHTML = s.revisions.map(function (r) {
        return '<div class="rev"><strong>R' + r.revision_number + "</strong> — " + esc(r.readiness.decision) +
          " (" + r.outline.length + " points)</div>";
      }).join("");
    } catch (e) { /* secondary */ }
  }

  function renderStage3Tab(d) {
    var gears = (d.stage3_transparency || []).map(function (g) {
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
    $("tab-stage3").innerHTML =
      "<h4>Session " + esc(d.session_id) + " — revision " + d.revision_number + "</h4>" +
      "<h4>Feedback backtrace</h4>" + (d.prompts.prompts || []).map(function (p) {
        return '<div class="trace"><ol class="chain">' +
          "<li><strong>" + esc("Prompt " + p.prompt_id) + "</strong>" +
            '<span class="chain-sub">' + esc(p.text) + "</span></li>" +
          "<li><strong>" + esc("Rule " + p.rule_id) + "</strong>" +
            '<span class="chain-sub">' + esc(p.why_shown || "") + "</span></li>" +
          "<li><strong>Alignment / unity evidence → item concepts → tokens → outline texts → original outline</strong></li>" +
          "</ol></div>";
      }).join("") +
      "<h4>Alignments</h4><pre>" + esc(JSON.stringify(d.alignments, null, 1).slice(0, 3000)) + "</pre>" +
      "<h4>Unity / progression / duplicates</h4><pre>" +
      esc(JSON.stringify({ unity: d.unity, progression: d.progression, duplicates: d.duplicates }, null, 1).slice(0, 3000)) + "</pre>" +
      "<h4>Readiness</h4>" + (d.readiness.conditions || []).map(function (c) {
        return "<p>" + esc(c.id) + " " + esc(c.name) + ": <strong>" + esc(c.result) + "</strong> — " + esc(c.detail) + "</p>";
      }).join("") +
      "<h4>Stage timings (measured ms)</h4><pre>" + esc(JSON.stringify(d.timings, null, 1)) + "</pre>" +
      "<h4>Outline rules</h4>" + rules + "<h4>Pipeline gears</h4>" + gears;
  }

  renderEditor();
})();
