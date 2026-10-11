/* EssayScaff progressive student feedback (presentation only).
 *
 * Student Mode shows ONE primary card for the CURRENT task:
 * current stage + current revision + current primary guidance.
 * Historical prompts stay in Revisions / Progress / Reflection and in
 * Transparency Mode, which keeps every finding. Nothing here changes
 * detection, storage, analytics, or readiness — it only decides what the
 * active Guided Feedback area displays.
 */
(function () {
  "use strict";

  function $(id) { return document.getElementById(id); }
  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  /* Starter guidance: shown when a Writing Lab stage is selected but empty.
   * Fixed instructional copy (guidance only — never generated sentences). */
  var STARTERS = {
    introduction: {
      title: "Start your introduction",
      message: "Introduce the topic so your reader knows what the essay is about. " +
        "Give a hint of the main argument you plan to develop.",
      question: "What does your reader need to know before seeing your thesis?",
    },
    body: {
      title: "Develop your first body point",
      message: "Use one main point from your outline and explain how it supports your thesis.",
      question: "Which outline point will you develop first?",
    },
    conclusion: {
      title: "Bring your argument together",
      message: "Return to your main direction and explain the main idea the reader " +
        "should take away after reading your essay.",
      question: "What final idea should your reader remember?",
    },
  };

  /* Constructive next step when the current analysis reports no problem.
   * Shown only because the backend reported zero findings — never invented. */
  var NEXT_STEPS = {
    introduction: "Your introduction has a clear direction. Continue developing your essay.",
    body: "This section reads clearly. Continue developing your next point.",
    conclusion: "Your conclusion holds together. Continue polishing your essay.",
  };

  /* Existing backend rank vocabularies, mirrored read-only for display
   * ordering (lower rank = shown first). Uses the numeric priority_rank
   * the backend already returns whenever present. */
  var NAME_RANK = { CRITICAL: 0, ERROR: 0, HIGH: 1, WARNING: 2, WARN: 2, MEDIUM: 2, INFO: 3, LOW: 3 };
  function rankOf(it) {
    it = it || {};
    if (typeof it.priority_rank === "number") return it.priority_rank * 10;
    var p = String(it.priority || it.severity || "").toUpperCase();
    if (Object.prototype.hasOwnProperty.call(NAME_RANK, p)) return 100 + NAME_RANK[p];
    return 150;
  }
  function idOf(it) { return String((it && (it.prompt_id || it.feedback_id)) || ""); }

  /* Pure display sequencing: highest-priority candidate first. The backend
   * already returns prioritized lists; this only selects the head so the
   * student sees one primary card. Resolving it surfaces the next item on
   * the next analysis (backend fading), nothing is deleted. */
  function selectPrimary(items) {
    var list = (items || []).slice();
    if (!list.length) return null;
    list.sort(function (a, b) {
      var d = rankOf(a) - rankOf(b);
      if (d !== 0) return d;
      var x = idOf(a), y = idOf(b);
      return x < y ? -1 : (x > y ? 1 : 0);
    });
    return list[0];
  }

  function starterCard(stage) {
    var s = STARTERS[stage] || STARTERS.introduction;
    return '<div class="prompt starter"><strong>' + esc(s.title) + "</strong>" +
      "<p>" + esc(s.message) + "</p>" +
      "<p><em>" + esc(s.question) + "</em></p></div>";
  }
  function nextStepCard(stage) {
    var s = NEXT_STEPS[stage] || NEXT_STEPS.introduction;
    return '<div class="prompt next"><strong>Next step</strong><p>' + esc(s) + "</p></div>";
  }

  /* Render exactly one card (or a fallback) into a Guided Feedback slot.
   * itemsHtml must already be in backend priority order; the head wins. */
  function renderOne(containerId, itemsHtml, emptyHtml) {
    var el = $(containerId);
    if (!el) return;
    var list = itemsHtml || [];
    el.innerHTML = list.length ? list[0] : (emptyHtml || "<p>No questions right now.</p>");
  }

  var STAGE_SLOTS = {
    stage1Section: "guidedPrompts",
    stage2Section: "thesisPrompts",
    stage3Section: "outlinePrompts",
    stage4Section: "reflectionPrompts",
    studentSection: "feedback",
  };
  var STAGE_NAMES = {
    stage1Section: "Stage 1 — Idea",
    stage2Section: "Stage 2 — Thesis",
    stage3Section: "Stage 3 — Outline",
    stage4Section: "Stage 4 — Reflection",
  };

  function activeWorkspace() {
    var t = document.querySelector('#workspaceTabs .tab[aria-selected="true"]');
    return t ? t.getAttribute("data-ws") : null;
  }
  function isTransparency() {
    return document.body.getAttribute("data-view") === "transparency";
  }

  /* Deterministic static stage guidance (presentation copy only — the
   * backend never generates these; they orient, never analyze). */
  var GOALS = {
    stage1Section: "Develop one focused idea about the assignment topic.",
    stage2Section: "Turn your idea into one clear thesis direction.",
    stage3Section: "Organize your thesis into clear body points and supporting details.",
    stage4Section: "Review your writing plan and identify what still needs improvement.",
    introduction: "Introduce the topic and lead the reader toward your main argument.",
    body: "Develop one main point and show how it supports your thesis.",
    conclusion: "Bring the main argument together and leave the reader with a clear takeaway.",
  };
  var NEXTS = {
    stage1Section: "Once your idea is focused, turn it into one clear thesis.",
    stage2Section: "Once your thesis is clear, organize the ideas that will support it.",
    stage3Section: "Once your outline is complete, review the plan before drafting.",
    stage4Section: "When your plan is ready, start writing your essay in the Writing Lab.",
    introduction: "After establishing your direction, develop the body of the essay.",
    body: "After developing your supporting points, prepare to bring them together.",
    conclusion: "After completing the conclusion, review the essay as a whole.",
  };
  var STAGE_SHORT = {
    stage1Section: "Idea", stage2Section: "Thesis",
    stage3Section: "Outline", stage4Section: "Reflection",
  };

  /* Checklist specs: readiness condition id -> plain-language label plus
   * the blocking rule ids that make a FAIL critical (!). Labels never show
   * raw C-ids; markers derive from real condition results. Capped at 5
   * rows: blocking failures first, then other failures, then passes. */
  var CHECKLISTS = {
    stage1Section: [
      { cond: "C1", label: "Enough development", block: ["PREWRITE_001"] },
      { cond: "C2", label: "Topic concepts found", block: ["PREWRITE_007"] },
      { cond: "C3", label: "Focus narrowed", block: ["PREWRITE_002"] },
      { cond: "C4", label: "No critical issues", block: ["PREWRITE_001", "PREWRITE_007"] },
    ],
    stage2Section: [
      { cond: "C1", label: "Clear thesis claim", block: [] },
      { cond: "C2", label: "No meta-statement", block: ["THESIS_002"] },
      { cond: "C3", label: "Complete structure", block: [] },
      { cond: "C4", label: "Topic connection", block: ["THESIS_006"] },
      { cond: "C5", label: "Specific and focused", block: ["THESIS_003"] },
      { cond: "C6", label: "Scope manageable", block: ["THESIS_005", "THESIS_008"] },
      { cond: "C7", label: "Central direction present", block: [] },
    ],
    stage3Section: [
      { cond: "C1", label: "Outline structure", block: ["OUTLINE_001"] },
      { cond: "C2", label: "Meaningful points", block: ["OUTLINE_002"] },
      { cond: "C3", label: "Thesis alignment", block: ["OUTLINE_003"] },
      { cond: "C4", label: "Supporting details", block: ["OUTLINE_005"] },
      { cond: "C5", label: "Details on point", block: ["OUTLINE_004"] },
      { cond: "C6", label: "No duplicates", block: ["OUTLINE_006"] },
      { cond: "C7", label: "Thesis coverage", block: [] },
      { cond: "C8", label: "Focused points", block: ["OUTLINE_008"] },
    ],
    stage4Section: [
      { cond: "R0", label: "Revision history present", block: [] },
      { cond: "R1", label: "No critical issues", block: ["R1"] },
      { cond: "R2", label: "No recurring major issues", block: [] },
      { cond: "R3", label: "No regressions", block: [] },
      { cond: "R4", label: "Stable improvement", block: [] },
    ],
  };

  function stageDatum(ws) {
    try {
      var ES = window.EssayScaff || {};
      if (ws === "stage1Section") return ES.lastStage1 || null;
      if (ws === "stage2Section") return ES.lastStage2 || null;
      if (ws === "stage3Section") return ES.lastStage3 || null;
      if (ws === "stage4Section") return ES.lastStage4 || null;
    } catch (e) { /* memory only */ }
    return null;
  }
  function ruleStatus(datum, id) {
    var rules = (datum && (datum.rules || datum.thesis_rules)) || [];
    for (var i = 0; i < rules.length; i++) {
      if (rules[i] && rules[i].rule_id === id) return rules[i].status;
    }
    return null;
  }
  function condResult(datum, id) {
    var conds = ((datum && datum.readiness) || {}).conditions || [];
    for (var i = 0; i < conds.length; i++) {
      if (conds[i] && conds[i].id === id) return conds[i].result;
    }
    return null;
  }

  /* What's Working: at most 3 positives, each traceable to real evidence
   * (readiness PASS, affirmative rule status, or measured classification).
   * data-ev carries the source id; nothing here is praise without proof. */
  function computeWorking(ws) {
    var out = [];
    function push(text, ev) { out.push({ text: text, ev: ev }); }
    if (ws === "stage1Section") {
      var d = stageDatum(ws);
      if (!d) return out;
      if (condResult(d, "C2") === "PASS") push("Topic is connected", "C2");
      if (ruleStatus(d, "PREWRITE_006") === "OBSERVED") push("Cause-and-effect direction detected", "PREWRITE_006");
      if (ruleStatus(d, "PREWRITE_005") === "INACTIVE") push("Subject identified", "PREWRITE_005");
      if (ruleStatus(d, "PREWRITE_004") === "INACTIVE") push("Problem indicator detected", "PREWRITE_004");
      if (condResult(d, "C1") === "PASS") push("Sufficient idea development", "C1");
      if (condResult(d, "C3") === "PASS") push("Focus narrowed", "C3");
      if (ruleStatus(d, "PREWRITE_008") === "OBSERVED") push("Idea focused", "PREWRITE_008");
      if (ruleStatus(d, "PREWRITE_007") === "INACTIVE") push("Topic not critically weak", "PREWRITE_007");
    } else if (ws === "stage2Section") {
      var d2 = stageDatum(ws);
      if (!d2) return out;
      if (condResult(d2, "C1") === "PASS") push("Thesis candidate detected", "C1");
      if (condResult(d2, "C2") === "PASS") push("No meta-statement", "C2");
      if (condResult(d2, "C3") === "PASS") push("Structurally complete", "C3");
      var al = (d2.alignment || {}).classification;
      if (al === "ALIGNED" || al === "PARTIALLY ALIGNED") push("Aligned with Stage 1", "alignment");
      if (condResult(d2, "C6") === "PASS") push("No critical scope issue", "C6");
      if (condResult(d2, "C4") === "PASS") push("Topic connection OK", "C4");
      if (condResult(d2, "C7") === "PASS") push("Clear central direction", "C7");
      if (condResult(d2, "C5") === "PASS") push("Focus acceptable", "C5");
    } else if (ws === "stage3Section") {
      var d3 = stageDatum(ws);
      if (!d3) return out;
      if (condResult(d3, "C3") === "PASS") push("Points align with thesis", "C3");
      if (condResult(d3, "C4") === "PASS") push("Support exists", "C4");
      if (condResult(d3, "C6") === "PASS") push("No severe duplicates", "C6");
      if (condResult(d3, "C5") === "PASS") push("Details stay on point", "C5");
      if (condResult(d3, "C7") === "PASS") push("Thesis coverage sufficient", "C7");
      if (condResult(d3, "C8") === "PASS") push("Points stay focused", "C8");
      if (condResult(d3, "C1") === "PASS") push("Structure complete", "C1");
    } else if (ws === "stage4Section") {
      var d4 = stageDatum(ws);
      if (!d4) return out;
      ["R0", "R1", "R2", "R3", "R4"].forEach(function (id) {
        if (condResult(d4, id) === "PASS") {
          var names = { R0: "Revision history present", R1: "No critical unresolved issue",
            R2: "No recurring major issue", R3: "No active regression",
            R4: "Stable improvement demonstrated" };
          push(names[id], id);
        }
      });
    } else if (ws === "studentSection") {
      var ES = window.EssayScaff || {};
      var a = ES.lastData || null;
      if (!a) return out;
      var cls = ((a.summary || {}).topic_classification) || null;
      if (cls === "MODERATE" || cls === "STRONG") push("Topic is connected", "topic_classification");
      var fbs = a.feedback || [];
      var crit = fbs.some(function (f) {
        return /^(warning|error|critical)$/i.test(String((f && f.severity) || ""));
      });
      if (!crit) push("No critical writing finding", "feedback-severity");
      var rr = ((a.technical || {}).rule_results) || [];
      var claim = rr.some(function (r) { return r && r.rule_id === "THESIS_001" && r.status === "CANDIDATE"; });
      if (claim) push("Central claim candidate detected", "THESIS_001");
      var ns = ((a.technical || {}).sentences) || [];
      if (ns.length >= 2) push("Text developing (" + ns.length + " sentences)", "sentence_count");
    }
    return out.slice(0, 3);
  }

  function computeChecklist(ws) {
    var spec = CHECKLISTS[ws];
    var d = stageDatum(ws);
    if (!spec || !d) return [];
    var r = d.readiness || {};
    var blocking = r.blocking_rules || r.blocking || [];
    var rows = spec.map(function (s) {
      var res = condResult(d, s.cond);
      if (res !== "PASS" && res !== "FAIL") return null;
      var mark = res === "PASS" ? "ok"
        : (s.block.some(function (b) { return blocking.indexOf(b) !== -1; }) ? "crit" : "open");
      return { cond: s.cond, label: s.label, mark: mark, result: res };
    }).filter(Boolean);
    var order = { crit: 0, open: 1, ok: 2 };
    rows.sort(function (a, b) { return (order[a.mark] - order[b.mark]) || 0; });
    return rows.slice(0, 5);
  }

  /* "Why am I seeing this?" contexts, one per slot. Renderers store the
   * backing item for the card they just showed; the box explains it in
   * student-friendly language with no rule IDs, paths, or vectors. */
  var whyBySlot = {};
  function setWhy(slot, ctx) {
    if (ctx) whyBySlot[slot] = ctx;
    else delete whyBySlot[slot];
    refreshWhy();
  }
  function whyNeutral(stageLabel) {
    return "Shown first because it has the highest priority among your current " +
      stageLabel + " findings.";
  }
  function refreshWhy() {
    var box = $("dashWhy"), body = $("dashWhyBody");
    if (!box || !body) return;
    var ws = activeWorkspace();
    var slot = STAGE_SLOTS[ws];
    var ctx = (slot && whyBySlot[slot]) || null;
    if (isTransparency() || !ctx) { box.hidden = true; body.innerHTML = ""; return; }
    var html = "";
    if (ctx.label) html += "<p><strong>" + esc(ctx.label) + "</strong></p>";
    html += "<p>" + esc(ctx.explanation || whyNeutral(ctx.stageLabel || "current")) + "</p>";
    if (ctx.evidence) html += "<p>" + esc(ctx.evidence) + "</p>";
    body.innerHTML = html;
    box.hidden = false;
  }

  /* Blocking-vs-advisory marker for the single primary card.
   * Display only: readiness (including blocking_rules) is read, never
   * altered. "Blocking" = this card's rule is in the readiness blocking
   * set; "Advisory" = the stage gate is open so this is optional polish;
   * otherwise nothing is shown rather than risk misleading the student. */
  function markBlocking(containerId, ruleId, readiness, allowedFlag) {
    var el = $(containerId);
    if (!el || !readiness) return;
    var blocking = readiness.blocking_rules || readiness.blocking || [];
    var badge = "";
    if (ruleId && blocking.indexOf(ruleId) !== -1) {
      badge = '<span class="badge badge-block" title="This issue blocks continuing. Resolve it to move on.">Blocking</span>';
    } else if (readiness[allowedFlag] === true) {
      badge = '<span class="badge badge-open" title="Optional improvement — you may continue.">Advisory</span>';
    } else {
      return;
    }
    var card = el.querySelector(".prompt, .fb");
    if (card) card.insertAdjacentHTML("afterbegin", badge + " ");
  }

  function stageRevision(ws) {
    try {
      var ES = window.EssayScaff || {};
      var d = ws === "stage1Section" ? ES.lastStage1
        : ws === "stage2Section" ? ES.lastStage2
        : ws === "stage3Section" ? ES.lastStage3
        : ws === "stage4Section" ? ES.lastStage4 : null;
      return (d && d.revision_number != null) ? d.revision_number : null;
    } catch (e) { return null; }
  }

  /* Current-stage-only visibility for the ACTIVE Guided Feedback area.
   * Student Mode: only the slot matching the active workspace tab shows.
   * Transparency Mode: everything stays visible (complete evidence). */
  function updateFeedbackFocus() {
    var ws = activeWorkspace();
    var trans = isTransparency();
    Object.keys(STAGE_SLOTS).forEach(function (key) {
      var el = $(STAGE_SLOTS[key]);
      if (el) el.hidden = !trans && key !== ws;
    });
    var line = $("feedbackFocusLine");
    if (line) {
      var label;
      if (ws === "studentSection") {
        var sel = $("stage");
        var mode = sel ? sel.value : "introduction";
        label = mode.charAt(0).toUpperCase() + mode.slice(1) + " · live";
      } else if (STAGE_SHORT[ws]) {
        var rev = stageRevision(ws);
        label = STAGE_SHORT[ws] + " · Revision " + (rev != null ? rev : "—");
      } else {
        label = "current stage";
      }
      line.textContent = label;
    }
    refreshWhy();
    refreshDashboard();
  }

  function labMode() {
    var sel = $("stage");
    return sel ? sel.value : "introduction";
  }

  /* The coaching dashboard: goal + primary (existing slots) + why +
   * working + next + checklist + snapshot + previous. Everything reflects
   * the CURRENT workspace tab; sections without supported data hide. */
  function refreshDashboard() {
    var ws = activeWorkspace();
    var goalEl = $("dashGoal");
    if (goalEl) {
      var goal = ws === "studentSection" ? GOALS[labMode()] : GOALS[ws];
      if (goal) {
        goalEl.innerHTML = '<p class="dash-eyebrow">Current goal</p><p>' + esc(goal) + "</p>";
        goalEl.hidden = false;
      } else { goalEl.hidden = true; goalEl.innerHTML = ""; }
    }
    var nextEl = $("dashNext");
    if (nextEl) {
      var next = ws === "studentSection" ? NEXTS[labMode()] : NEXTS[ws];
      if (next) {
        nextEl.innerHTML = '<p class="dash-eyebrow">Next step</p><p>' + esc(next) + "</p>";
        nextEl.hidden = false;
      } else { nextEl.hidden = true; nextEl.innerHTML = ""; }
    }
    var workEl = $("dashWorking");
    if (workEl) {
      var items = computeWorking(ws);
      if (!items.length) { workEl.hidden = true; workEl.innerHTML = ""; }
      else {
        workEl.innerHTML = '<p class="dash-eyebrow">What\u2019s working</p><ul class="dash-working">' +
          items.map(function (it) {
            return '<li data-ev="' + esc(it.ev) + '"><span class="ok">✓</span> ' + esc(it.text) + "</li>";
          }).join("") + "</ul>";
        workEl.hidden = false;
      }
    }
    var checkEl = $("dashChecklist");
    if (checkEl) {
      var rows = computeChecklist(ws);
      var titles = { stage1Section: "Idea checklist", stage2Section: "Thesis checklist",
        stage3Section: "Outline checklist", stage4Section: "Reflection checklist" };
      if (!rows.length) { checkEl.hidden = true; checkEl.innerHTML = ""; }
      else {
        var marks = { ok: ["✓", "ok"], open: ["○", "open"], crit: ["!", "crit"] };
        checkEl.innerHTML = '<p class="dash-eyebrow">' + esc(titles[ws] || "Checklist") + "</p>" +
          '<ul class="dash-check">' + rows.map(function (r) {
            return '<li data-cond="' + esc(r.cond) + '"><span class="mark ' + marks[r.mark][1] + '">' +
              marks[r.mark][0] + "</span> " + esc(r.label) + "</li>";
          }).join("") + "</ul>";
        checkEl.hidden = false;
      }
    }
    refreshSnapshot(ws);
    refreshPrevCount();
  }

  function analysisFor(ws) {
    if (ws === "studentSection") {
      try { return (window.EssayScaff || {}).lastData || null; }
      catch (e) { return null; }
    }
    var d = stageDatum(ws);
    return (d && d.analysis) || null;
  }

  function fmtDur(ms) {
    var s = Math.max(0, Math.floor(ms / 1000));
    var m = Math.floor(s / 60);
    function pad(n) { return (n < 10 ? "0" : "") + n; }
    return pad(m) + ":" + pad(s % 60);
  }
  var snapToken = 0;
  function refreshSnapshot(ws) {
    var el = $("dashSnapshot");
    if (!el) return;
    var a = analysisFor(ws);
    if (!a) { el.hidden = true; el.innerHTML = ""; return; }
    var toks = ((a.technical || {}).tokens) || [];
    var sents = ((a.technical || {}).sentences) || [];
    var words = toks.filter(function (t) { return t && t.is_alpha; }).length;
    var d = stageDatum(ws);
    var rev = d ? d.revision_number : null;
    var cls = ((a.summary || {}).topic_classification) || null;
    var html = '<p class="dash-eyebrow">Writing snapshot</p><div class="dash-snap">' +
      "<div><span>Words</span><strong>" + words + "</strong></div>" +
      "<div><span>Sentences</span><strong>" + sents.length + "</strong></div>" +
      "<div><span>Revision</span><strong>" + (rev != null ? esc(rev) : "live") + "</strong></div>" +
      '<div><span>Active time</span><strong id="dashSnapTime">—</strong></div>' +
      "</div>";
    if (cls) {
      html += '<p class="snap-topic">Topic connection: <strong>' + esc(cls) + "</strong></p>" +
        '<p class="hint">Lexical topic evidence — not a grade.</p>';
    }
    el.innerHTML = html;
    el.hidden = false;
    // Active time comes from analytics time-on-task aggregates — never from
    // processing_ms. Lab analyses have no stage session: honestly "—".
    var stageKey = { stage1Section: "stage1", stage2Section: "stage2",
      stage3Section: "stage3", stage4Section: "stage4" }[ws] || null;
    var sid = (d && d.session_id) || null;
    var my = ++snapToken;
    if (!stageKey || !sid) return;
    fetch("/api/analytics/session/" + encodeURIComponent(sid)).then(function (r) {
      return r.json().then(function (j) { return { ok: r.ok, j: j }; });
    }).then(function (res) {
      if (my !== snapToken) return;
      var v = res.ok && res.j && res.j.per_stage && res.j.per_stage[stageKey] &&
        res.j.per_stage[stageKey].active_time && res.j.per_stage[stageKey].active_time.active_ms;
      v = (v && v.value) || null;
      var t = $("dashSnapTime");
      if (t) t.textContent = (typeof v === "number") ? fmtDur(v) : "—";
    }).catch(function () {
      if (my !== snapToken) return;
      var t = $("dashSnapTime");
      if (t) t.textContent = "—";
    });
  }

  function prevRevisionCount() {
    var n = 0;
    try {
      var ES = window.EssayScaff || {};
      ["lastStage1", "lastStage2", "lastStage3", "lastStage4"].forEach(function (k) {
        var r = ES[k] && ES[k].revision_number;
        if (typeof r === "number") n += r;
      });
      if (typeof ES.labAnalyses === "number") n += ES.labAnalyses;
    } catch (e) { /* memory only */ }
    return n;
  }
  function refreshPrevCount() {
    var el = $("dashPrevCount");
    if (el) el.textContent = String(prevRevisionCount());
  }

  function showRevisionsPane() {
    if (isTransparency()) return;
    var tab = document.querySelector('#studentTabs [data-pane="pane-revisions"]');
    if (tab) tab.click();
  }

  var histBtn = $("feedbackHistoryBtn");
  if (histBtn) histBtn.addEventListener("click", showRevisionsPane);

  document.querySelectorAll("#workspaceTabs .tab").forEach(function (b) {
    b.addEventListener("click", function () {
      // Deferred on purpose: other tab handlers (shell.js showWorkspace)
      // run in registration order, which differs between index.html and
      // test harnesses. Reading the active tab on the next tick always
      // sees the settled state, independent of script order.
      setTimeout(function () {
        updateFeedbackFocus();
        refreshLabStarter();
      }, 0);
    });
  });
  ["studentViewBtn", "transparencyViewBtn"].forEach(function (id) {
    var b = $(id);
    if (b) b.addEventListener("click", function () {
      // setView() in transparency.js runs first (bound earlier); read the
      // settled view mode on the next tick.
      setTimeout(updateFeedbackFocus, 0);
    });
  });

  /* Writing Lab starter: exactly one guidance card while the editor for the
   * selected lab stage is empty. Replaced by the primary problem card (or
   * the no-issue next step) as soon as an analysis for real text renders. */
  function refreshLabStarter() {
    var ed = $("editor"), box = $("feedback"), sel = $("stage");
    if (!ed || !box) return;
    if (activeWorkspace() !== "studentSection") return;
    if (ed.value && ed.value.trim()) return;
    box.innerHTML = starterCard(sel ? sel.value : "introduction");
    setWhy("feedback", null);
    updateFeedbackFocus();
  }

  var stageSel = $("stage");
  if (stageSel) stageSel.addEventListener("change", function () {
    refreshLabStarter();
    updateFeedbackFocus();
    var ed = $("editor");
    if (ed && ed.value && ed.value.trim()) {
      var btn = $("analyzeBtn");
      if (btn) btn.click();
    }
  });
  var editor = $("editor");
  if (editor) editor.addEventListener("input", function () {
    if (!editor.value.trim()) refreshLabStarter();
  });

  // Restore lab context carried from Stage 4 (values only, never drafts).
  // Only fills empty fields so later manual edits are never overwritten.
  try {
    ["labTopic:topic", "labKeywords:teacherKeywords"].forEach(function (pair) {
      var parts = pair.split(":");
      var v = sessionStorage.getItem("essayscaff." + parts[0]);
      var el = document.getElementById(parts[1]);
      if (v && el && !el.value) el.value = v;
    });
  } catch (e) { /* private mode */ }

  updateFeedbackFocus();
  refreshLabStarter();

  window.EssayScaffFeedback = {
    selectPrimary: selectPrimary,
    renderOne: renderOne,
    updateFeedbackFocus: updateFeedbackFocus,
    refreshDashboard: refreshDashboard,
    refreshLabStarter: refreshLabStarter,
    starterCard: starterCard,
    nextStepCard: nextStepCard,
    setWhy: setWhy,
    markBlocking: markBlocking,
    goalText: function (ws) {
      if (ws === "studentSection") return null;
      return GOALS[ws] || null;
    },
    goalTextForLab: function (mode) { return GOALS[mode] || null; },
    nextText: function (ws, labMode) {
      if (ws === "studentSection") return NEXTS[labMode] || null;
      return NEXTS[ws] || null;
    },
    computeWorking: computeWorking,
    computeChecklist: computeChecklist,
    prevRevisionCount: prevRevisionCount,
    currentSlot: function () { return STAGE_SLOTS[activeWorkspace()] || null; },
  };
})();
