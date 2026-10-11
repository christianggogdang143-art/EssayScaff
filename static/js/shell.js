/* EssayScaff application shell helper: editor statistics, stage pills,
 * and topic-connection label. Presentation only — every value shown here
 * comes from real editor text or real backend responses. Nothing invented. */
(function () {
  "use strict";

  function $(id) { return document.getElementById(id); }
  function words(s) { return ((s || "").trim().match(/\S+/g) || []).length; }
  function sents(s) {
    return (s || "").split(/[.!?…]+/).filter(function (x) { return x.trim().length > 0; }).length;
  }

  var EDITORS = [
    ["ideaEditor", "ideaWords", "ideaSents"],
    ["thesisEditor", "thesisWords", "thesisSents"],
    ["editor", "edWords", "edSents"]
  ];
  EDITORS.forEach(function (trio) {
    var ed = $(trio[0]);
    if (!ed) return;
    var update = function () {
      $(trio[1]).textContent = words(ed.value);
      $(trio[2]).textContent = sents(ed.value);
    };
    ed.addEventListener("input", update);
    update();
  });

  function pill(stage, state, label) {
    var el = document.querySelector('.stage-pill[data-stage="' + stage + '"]');
    if (!el) return;
    el.classList.remove("is-active", "is-ready");
    if (state === "ready") el.classList.add("is-ready");
    else if (state === "active") el.classList.add("is-active");
    var base = { 1: "Idea", 2: "Thesis", 3: "Outline", 4: "Reflection" }[stage];
    el.innerHTML = "<strong>" + stage + "</strong> " + (label || base);
  }

  function topicLabel(cls) {
    if (cls === "STRONG") return "Strong connection";
    if (cls === "MODERATE") return "Some connection";
    if (cls === "WEAK") return "Needs review";
    return null;
  }

  /* ---------------- workspace stage tabs ---------------- */
  // One workspace section visible at a time (Stage 1 default). Hide/show
  // only — drafts, histories, and listeners are untouched.
  var WS_SECTIONS = ["stage1Section", "stage2Section", "stage3Section", "stage4Section", "studentSection"];
  function showWorkspace(id) {
    document.querySelectorAll("#workspaceTabs .tab").forEach(function (x) {
      var on = x.getAttribute("data-ws") === id;
      x.classList.toggle("active", on);
      if (on) x.setAttribute("aria-selected", "true");
      else x.setAttribute("aria-selected", "false");
    });
    WS_SECTIONS.forEach(function (sid) {
      var el = document.getElementById(sid);
      if (el) el.hidden = sid !== id;
    });
  }
  document.querySelectorAll("#workspaceTabs .tab").forEach(function (b) {
    b.addEventListener("click", function () {
      showWorkspace(b.getAttribute("data-ws"));
      try { sessionStorage.setItem("essayscaff.ws", b.getAttribute("data-ws")); } catch (e) { /* private mode */ }
      if (window.EssayScaffWalkthrough) window.EssayScaffWalkthrough.refresh();
    });
  });
  // §45 refresh restore: active tab + Stage 2-4 link fields only (never drafts).
  // Values only — each stage module re-fetches its read-only reference, so
  // a Continued chain survives reload without ever inventing content.
  try {
    var savedWs = sessionStorage.getItem("essayscaff.ws");
    if (savedWs && WS_SECTIONS.indexOf(savedWs) !== -1) showWorkspace(savedWs);
    ["s2Stage1", "s3Stage2", "s4Stage1", "s4Stage2", "s4Stage3"].forEach(function (id) {
      var v = sessionStorage.getItem("essayscaff." + id), el = document.getElementById(id);
      if (v && el && !el.value) el.value = v;
    });
  } catch (e) { /* private mode */ }
  ["s2Stage1", "s3Stage2", "s4Stage1", "s4Stage2", "s4Stage3"].forEach(function (id) {
    var el = document.getElementById(id);
    if (el) el.addEventListener("change", function () {
      try { sessionStorage.setItem("essayscaff." + id, el.value); } catch (e) { /* private mode */ }
    });
  });

  function refreshCounts() {
    EDITORS.forEach(function (trio) {
      var ed = $(trio[0]), w = $(trio[1]), s = $(trio[2]);
      if (!ed || !w || !s) return;
      w.textContent = words(ed.value);
      s.textContent = sents(ed.value);
    });
  }

  // Null-safe setters for the periodic interval: one missing element must
  // never abort the whole tick (pills + remaining metas keep updating).
  function setText(id, value) {
    var el = $(id);
    if (el) el.textContent = value;
  }
  function setHTML(id, html) {
    var el = $(id);
    if (el) el.innerHTML = html;
  }

  // Keyboard support for tablists (ARIA authoring practices): arrows move
  // between tabs in a group, Home/End jump to first/last.
  ["workspaceTabs", "studentTabs", "transTabs"].forEach(function (listId) {
    var list = document.getElementById(listId);
    if (!list) return;
    list.addEventListener("keydown", function (e) {
      var tabs = Array.prototype.slice.call(list.querySelectorAll('[role="tab"]'));
      var i = tabs.indexOf(document.activeElement);
      if (i === -1) return;
      var j = null;
      if (e.key === "ArrowRight") j = (i + 1) % tabs.length;
      else if (e.key === "ArrowLeft") j = (i - 1 + tabs.length) % tabs.length;
      else if (e.key === "Home") j = 0;
      else if (e.key === "End") j = tabs.length - 1;
      if (j !== null) { e.preventDefault(); tabs[j].focus(); tabs[j].click(); }
    });
  });

  setInterval(function () {
    refreshCounts(); // also catches programmatic fills (Load Example) with no input event
    var S = window.EssayScaff || {};
    // Stage pills from real readiness decisions.
    var r1 = S.lastStage1 && S.lastStage1.readiness;
    pill(1, !r1 ? null : (r1.stage2_allowed ? "ready" : "active"), !r1 ? null : "Idea · " + r1.decision.charAt(0) + r1.decision.slice(1).toLowerCase());
    var r2 = S.lastStage2 && S.lastStage2.readiness;
    pill(2, !r2 ? null : (r2.stage3_allowed ? "ready" : "active"));
    var r3 = S.lastStage3 && S.lastStage3.readiness;
    pill(3, !r3 ? null : (r3.stage4_allowed ? "ready" : "active"));
    var r4 = S.lastStage4 && S.lastStage4.readiness;
    pill(4, !r4 ? null : (r4.reflection_complete ? "ready" : "active"),
      !r4 ? null : ("Reflection · " + r4.decision.charAt(0) + r4.decision.slice(1).toLowerCase()));
    // Revision / saved line for the writing lab.
    if (S.lastData) {
      setText("edMeta", "Analyzed · " + S.lastData.analysis_id);
      var cls = S.lastData.summary && S.lastData.summary.topic_classification;
      var label = topicLabel(cls);
      setHTML("topicConnection", label
        ? '<div class="topic-line">Topic connection: <strong>' + label + "</strong> (backend: " + cls + ")</div>"
        : "");
    }
    if (S.lastStage1) setText("ideaMeta", "Revision " + S.lastStage1.revision_number + " · Saved");
    if (S.lastStage2) setText("thesisMeta", "Revision " + S.lastStage2.revision_number + " · Saved");
    if (S.lastStage3) {
      var n = (S.lastStage3.outline || []).length;
      setText("outlineMeta", "Revision " + S.lastStage3.revision_number + " · " + n + " points · Saved");
    }
    if (S.lastStage4) setText("reflectMeta", "Revision " + S.lastStage4.revision_number + " · Saved");
  }, 1500);
})();
