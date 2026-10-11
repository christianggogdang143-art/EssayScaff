/* EssayScaff Stage 1 workspace client: idea -> scaffolding -> revision.
 * Student View stays a writing coach: concepts, questions, progress.
 * Technical gears render in the Transparency "Stage 1" tab. */
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

  /* Structured presentational helpers (display only — same data, no logic). */
  function kvHtml(obj) {
    var rows = Object.keys(obj || {}).map(function (k) {
      var v = obj[k];
      var s = Array.isArray(v) ? v.join(", ") : (v && typeof v === "object" ? JSON.stringify(v) : String(v));
      if (s === "") s = "—";
      return "<div><dt>" + esc(k) + "</dt><dd>" + esc(s) + "</dd></div>";
    }).join("");
    return '<dl class="kv">' + rows + "</dl>";
  }
  function chainHtml(items) {
    return '<ol class="chain">' + items.map(function (it) {
      return "<li><strong>" + esc(it.t) + "</strong>" +
        (it.s ? '<span class="chain-sub">' + esc(it.s) + "</span>" : "") +
        (it.h || "") + "</li>";
    }).join("") + "</ol>";
  }

  var sessionId = null;

  $("ideaSampleBtn").addEventListener("click", function () {
    $("s1Topic").value = "Effects of climate change on agriculture";
    $("s1Keywords").value = "climate, agriculture, farmers, crop, temperature, rainfall";
    $("ideaEditor").value = "Climate change affects agriculture.";
  });

  $("stage2Btn").addEventListener("click", function () {
    // Normal student flow: carry the REAL Stage 1 session id into Stage 2
    // automatically (populate link field + render read-only idea reference).
    // Directly clicking the Stage-2 tab does NOT do this — that path keeps
    // intentional unlinked/manual behavior for research/testing.
    try {
      var id = sessionId || (((window.EssayScaff || {}).lastStage1 || {}).session_id) || null;
      if (id && window.EssayScaffStage2 && window.EssayScaffStage2.applyContinueLink) {
        window.EssayScaffStage2.applyContinueLink(id);
      } else if (id) {
        var el = document.getElementById("s2Stage1");
        if (el && !el.value) {
          el.value = id;
          try { sessionStorage.setItem("essayscaff.s2Stage1", id); } catch (e) { /* private mode */ }
        }
      }
    } catch (e) { /* navigation must never break */ }
    var tab = document.querySelector('#workspaceTabs [data-ws="stage2Section"]');
    if (tab) tab.click();
  });

  $("ideaBtn").addEventListener("click", async function () {
    var text = $("ideaEditor").value;
    if (!text || !text.trim()) { $("ideaStatus").textContent = "Write your idea first."; return; }
    var kws = $("s1Keywords").value.split(",").map(function (s) { return s.trim(); }).filter(Boolean);
    $("ideaStatus").textContent = "Analyzing your idea...";
    try {
      const res = await fetch("/api/stage1/analyze", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          text: text,
          topic: $("s1Topic").value.trim() || null,
          teacher_keywords: kws.length ? kws : null,
          session_id: sessionId,
        }),
      });
      const d = await readJson(res);
      if (!res.ok) { $("ideaStatus").textContent = d.error || "Analysis failed."; return; }
      sessionId = d.session_id;
      window.EssayScaff = window.EssayScaff || {};
      window.EssayScaff.lastStage1 = d;
      $("ideaStatus").textContent = "Done — revision " + d.revision_number + ".";
      renderStudent(d);
      renderStage1Tab(d);
      loadHistory();
    } catch (e) { $("ideaStatus").textContent = "Request failed: " + e.message; }
  });

  function renderStudent(d) {
    var ev = d.evidence || {};
    $("conceptChips").innerHTML = (ev.selected_keywords || []).length
      ? (ev.selected_keywords || []).map(function (c) {
          return '<span class="chip">' + esc(c) + "</span>";
        }).join("")
      : "<p>No clear concepts yet — write a little more.</p>";
    // Progressive scaffolding: exactly one primary guidance card in the
    // active feed (backend priority order — main first). Full history stays
    // in Revisions/Progress/Transparency; nothing is deleted or rescored.
    var cards = renderGuidance(d.guidance, d.prompts);
    if (window.EssayScaffFeedback) {
      window.EssayScaffFeedback.renderOne("guidedPrompts", cards, "<p>No questions right now.</p>");
      window.EssayScaffFeedback.setWhy("guidedPrompts", primaryWhy(d));
      window.EssayScaffFeedback.updateFeedbackFocus();
    } else {
      $("guidedPrompts").innerHTML = cards.join("") || "<p>No questions right now.</p>";
    }
    var r = d.readiness || {};
    var cmp = (d.comparison.messages || []).map(function (m) {
      return "<li>" + esc(m.text) + "</li>";
    }).join("");
    $("stageStatus").innerHTML =
      "<p><strong>" + esc(r.decision || "") + "</strong></p>" +
      "<p>" + esc(r.student_message || "") + "</p>" +
      (cmp ? "<p>Since your last revision:</p><ul>" + cmp + "</ul>" : "");
    $("stage2Btn").disabled = !r.stage2_allowed;
  }

  function primaryWhy(d) {
    // Backing item for the single shown card, in student-friendly terms
    // (labels + student_why only — never rule IDs or file paths).
    var g = d.guidance || {};
    if (g.main) {
      return { stageLabel: "Stage 1", label: g.main.label || "Guidance",
        explanation: g.main.student_why || null, evidence: null };
    }
    var o = (g.others || [])[0];
    if (o) {
      return { stageLabel: "Stage 1", label: o.label || "Guidance",
        explanation: o.student_why || null, evidence: null };
    }
    var p = ((d.prompts || {}).prompts || [])[0];
    if (p) {
      return { stageLabel: "Stage 1", label: p.category || "Guidance",
        explanation: p.why_shown || null, evidence: null };
    }
    return null;
  }

  function renderGuidance(guidance, promptsFallback) {
    // Hierarchy: main guidance first, then other questions, then notes.
    // Priority levels stay professor-side (Transparency tab); students see
    // subtle category labels instead. Returns cards in backend priority
    // order so the progressive feed can show the single primary card.
    var prompts = (guidance && (guidance.main || (guidance.others || []).length))
      ? null : ((promptsFallback || {}).prompts || []);
    if (!guidance || (!guidance.main && !(guidance.others || []).length)) {
      return (prompts || []).map(function (p) {
        return '<div class="prompt"><strong>' + esc(p.text) + "</strong></div>";
      });
    }
    var cards = [];
    if (guidance.main) {
      cards.push('<div class="prompt main"><span class="plabel">' + esc(guidance.main.label || "") + "</span>" +
        '<p class="why">' + esc(guidance.main.student_why || "") + "</p>" +
        "<strong>" + esc(guidance.main.question.text) + "</strong></div>");
    }
    (guidance.others || []).forEach(function (o) {
      cards.push('<div class="prompt"><span class="plabel">' + esc(o.label || "") + "</span>" +
        '<p class="why">' + esc(o.student_why || "") + "</p>" +
        "<strong>" + esc(o.question.text) + "</strong></div>");
    });
    if (guidance.assignment_note) {
      cards.push('<div class="prompt"><span class="plabel">' + esc(guidance.assignment_note.label) + "</span>" +
        "<p>" + esc(guidance.assignment_note.text) + "</p></div>");
    }
    (guidance.writing_notes || []).forEach(function (n) {
      cards.push('<div class="prompt note"><span class="plabel">Writing Note</span>' +
        "<p>" + esc(n.message || "") + "</p></div>");
    });
    return cards;
  }

  async function loadHistory() {
    if (!sessionId) return;
    try {
      const res = await fetch("/api/stage1/session/" + encodeURIComponent(sessionId));
      if (!res.ok) return;
      const s = await readJson(res);
      $("revisionHistory").innerHTML = s.revisions.map(function (r) {
        return '<div class="rev"><strong>R' + r.revision_number + "</strong> — " +
          esc(r.readiness.decision) + "<br/><em>" + esc(r.idea_text.slice(0, 160)) +
          (r.idea_text.length > 160 ? "…" : "") + "</em></div>";
      }).join("");
    } catch (e) { /* history is secondary; never break the workspace */ }
  }

  function renderStage1Tab(d) {
    var gears = (d.stage1_transparency || []).map(function (g) {
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
      return "<p><code>" + esc(r.rule_id) + "</code> [" + esc(r.status) + "] — " + esc(r.condition) +
        " → " + (r.result ? "TRUE" : "FALSE") + "<br/><em>" + esc(r.reason) + "</em></p>";
    }).join("");
    var t = d.timings || {};
    $("tab-stage1").innerHTML =
      "<h4>Session " + esc(d.session_id) + " — revision " + d.revision_number + "</h4>" +
      "<h4>Prompt backtrace</h4>" + (d.prompts.prompts || []).map(function (p) {
        var rule = (d.rules || []).find(function (r) { return r.rule_id === p.rule_id; }) || {};
        var steps = [
          { t: "Prompt " + p.prompt_id, s: p.text },
          { t: "Rule " + p.rule_id, s: (rule.condition || "") + " = " + (rule.result ? "TRUE" : "FALSE") },
          { t: "Evidence", h: kvHtml(rule.evidence || {}) },
          { t: "Template " + (p.template_id || "n/a"),
            s: p.fallback_used ? "generic fallback, no slots" : (p.template_text || "") },
        ];
        if (!p.fallback_used && p.slot_values) {
          var prov = p.slot_provenance || {};
          var slotRows = Object.keys(p.slot_values).map(function (k) {
            var src = prov[k] ? prov[k].source || prov[k] : "";
            return "<div><dt>" + esc(k) + "</dt><dd>" + esc(p.slot_values[k]) +
              (src ? ' <span class="muted">← ' + esc(typeof src === "string" ? src : JSON.stringify(src)) + "</span>" : "") + "</dd></div>";
          }).join("");
          steps.push({ t: "Slots", h: '<dl class="kv">' + slotRows + "</dl>" });
        }
        steps.push({ t: "Concepts → tokens → original idea" });
        return '<div class="trace">' + chainHtml(steps) + "</div>";
      }).join("") +
      "<h4>Readiness</h4>" + (d.readiness.conditions || []).map(function (c) {
        return "<p>" + esc(c.id) + " " + esc(c.name) + ": <strong>" + esc(c.result) + "</strong> — " + esc(c.detail) + "</p>";
      }).join("") +
      "<h4>Stage timings (measured ms)</h4><pre>" + esc(JSON.stringify(t, null, 1)) + "</pre>" +
      "<h4>Rule evaluation</h4>" + rules + "<h4>Pipeline gears</h4>" + gears;
  }
})();
