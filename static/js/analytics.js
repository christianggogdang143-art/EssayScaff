/* EssayScaff research interaction logging (client side).
 *
 * Measures ACTIVE time-on-task per stage plus meaningful pedagogical
 * events. Privacy by design:
 * - activity means timestamps only (input/click/keydown moments);
 *   NO keystroke content, NO essay text, NO clipboard, NO passwords.
 * - events reference session/analysis/revision/rule/feedback ids plus
 *   small metadata. Full essay text is never sent here (it already lives
 *   in revision records).
 * - aggregates shown anywhere come from the server; this file measures
 *   and reports, it never invents counts.
 *
 * Active-time definition: wall-clock milliseconds accumulated while the
 * document is visible AND recent activity (typing, clicking, analyzing)
 * occurred within the idle timeout. Hidden tabs, blurred windows beyond
 * the timeout, and idle gaps pause the clock and are never counted.
 */
(function () {
  "use strict";

  var IDLE_MS = 300000;   // ESSAYSCAFF development/research logging parameter
  var FLUSH_MS = 60000;   // (server /api/config may override both)
  // Test seam: harness may set window.__essayAnalyticsTickMs BEFORE this
  // file loads to speed up deterministic timing tests. Default identical.
  var TICK_MS = (typeof window !== "undefined" &&
    typeof window.__essayAnalyticsTickMs === "number")
    ? window.__essayAnalyticsTickMs : 5000;
  var STORE_KEY = "essayAnalytics.open";

  function $(id) { return document.getElementById(id); }

  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  function isoNow() { return new Date().toISOString(); }

  function fmtDur(ms) {
    if (ms == null) return "n/a";
    var s = Math.max(0, Math.floor(ms / 1000));
    var h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60);
    function pad(n) { return (n < 10 ? "0" : "") + n; }
    if (h > 0) return h + "h " + pad(m) + "m";
    return pad(m) + "m " + pad(s % 60) + "s";
  }

  function post(url, body, keepalive) {
    try {
      var opts = { method: "POST", headers: { "Content-Type": "application/json" },
                   body: JSON.stringify(body) };
      if (keepalive) opts.keepalive = true;
      return fetch(url, opts).catch(function () {});
    } catch (e) { return null; }
  }

  function postEvent(type, extra) {
    var body = { event_type: type };
    for (var k in (extra || {})) body[k] = extra[k];
    post("/api/analytics/events", body);
  }

  /* ---------------- stage / session tracking ---------------- */
  var SECTION_STAGE = {
    stage1Section: "stage1", stage2Section: "stage2",
    stage3Section: "stage3", stage4Section: "stage4",
    studentSection: "lab", reviewSection: "lab"
  };

  function currentTabStage() {
    var tabs = document.querySelectorAll("#workspaceTabs .tab");
    for (var i = 0; i < tabs.length; i++) {
      if (tabs[i].getAttribute("aria-selected") === "true")
        return SECTION_STAGE[tabs[i].getAttribute("data-ws")] || null;
    }
    return null;
  }

  function knownSession(stage) {
    try {
      var ES = window.EssayScaff || {};
      var key = { stage1: "lastStage1", stage2: "lastStage2",
                  stage3: "lastStage3", stage4: "lastStage4" }[stage];
      var d = key && ES[key];
      return (d && d.session_id) || null;
    } catch (e) { return null; }
  }

  /* ---------------- active-time engine ---------------- */
  var st = { stage: null, session: null, start: null, activeMs: 0,
             lastTick: 0, lastActivity: 0, paused: true,
             pendingStage: null, pendingStart: 0, pendingMs: 0 };

  function saveOpen() {
    try {
      if (st.stage && st.session && st.start) {
        sessionStorage.setItem(STORE_KEY, JSON.stringify({
          stage: st.stage, session: st.session, start: st.start,
          activeMs: st.activeMs, lastTick: st.lastTick }));
      } else {
        sessionStorage.removeItem(STORE_KEY);
      }
    } catch (e) {}
  }

  function closeInterval(reason, endedAt) {
    if (!(st.stage && st.session && st.start)) return;
    var end = endedAt || isoNow();
    post("/api/analytics/intervals", {
      session_id: st.session, stage: st.stage,
      started_at: st.start, ended_at: end,
      active_ms: Math.max(0, Math.round(st.activeMs)) });
    st.stage = null; st.session = null; st.start = null;
    st.activeMs = 0; st.paused = true;
    saveOpen();
  }

  function openInterval(stage, session) {
    st.stage = stage; st.session = session;
    st.start = isoNow(); st.activeMs = 0;
    st.lastTick = Date.now(); st.lastActivity = Date.now();
    st.paused = false;
    saveOpen();
  }

  function isVisible() {
    return !(document.hidden || document.visibilityState === "hidden");
  }

  function tick() {
    var now = Date.now();
    if (!st.stage || !st.session || st.paused || !isVisible()) return;
    if (now - st.lastActivity > IDLE_MS) {
      postEvent("SESSION_PAUSED", { stage: st.stage, session_id: st.session,
        metadata: { reason: "idle-timeout", idle_ms: IDLE_MS } });
      closeInterval("idle");
      return;
    }
    st.activeMs += Math.min(now - st.lastTick, 2 * TICK_MS);
    st.lastTick = now;
    saveOpen();
  }

  function markActivity() { st.lastActivity = Date.now(); }

  function ensureTracking() {
    // Open a fresh interval when the active tab has a known session.
    var stage = currentTabStage();
    if (!stage || stage === "lab") return;
    var session = knownSession(stage);
    if (!session) return;
    if (st.stage === stage && st.session === session && !st.paused) return;
    var hadOpen = !!(st.stage && !st.paused);
    if (st.stage) closeInterval("stage-change");
    // Attribute pre-first-revision activity measured while waiting.
    if (st.pendingStage === stage && st.pendingMs > 0) {
      post("/api/analytics/intervals", {
        session_id: session, stage: stage,
        started_at: new Date(st.pendingStart).toISOString(),
        ended_at: isoNow(), active_ms: Math.round(st.pendingMs) });
      st.pendingStage = null; st.pendingMs = 0;
    }
    openInterval(stage, session);
    if (!hadOpen) postEvent("SESSION_RESUMED", { stage: stage, session_id: session });
  }

  // Pre-first-revision typing accrues here (memory only, never persisted
  // unattributed); it is flushed once the first analysis response reveals
  // the real session id (see ensureTracking). Lost on refresh by design.
  setInterval(function () {
    var stage = currentTabStage();
    if (stage && stage !== "lab" && !knownSession(stage) && isVisible()) {
      if (st.pendingStage !== stage) {
        st.pendingStage = stage; st.pendingStart = Date.now();
        st.pendingMs = 0; st.pendingLast = 0;
      }
      if (Date.now() - (st.lastActivity || 0) <= IDLE_MS && st.pendingLast) {
        st.pendingMs += Math.min(Date.now() - st.pendingLast, 2 * TICK_MS);
      }
      st.pendingLast = Date.now();
    }
    tick();
  }, TICK_MS);

  setInterval(function () {
    // Periodic flush so ordinary navigation never loses much timing data.
    if (st.stage && st.session && !st.paused) {
      var stage = st.stage, session = st.session;
      closeInterval("flush");
      openInterval(stage, session);
    }
  }, FLUSH_MS);

  ["input", "keydown", "click"].forEach(function (ev) {
    document.addEventListener(ev, markActivity, { capture: true, passive: true });
  });

  document.addEventListener("visibilitychange", function () {
    if (document.hidden || document.visibilityState === "hidden") {
      if (st.stage && !st.paused) {
        postEvent("SESSION_PAUSED", { stage: st.stage, session_id: st.session,
          metadata: { reason: "tab-hidden" } });
        closeInterval("hidden");
      }
    } else {
      markActivity();
      ensureTracking();
    }
  });

  window.addEventListener("blur", function () {
    // Blurred-but-visible windows keep counting only inside the idle window;
    // the tick naturally pauses them once activity goes stale.
    markActivityBlip();
  });
  function markActivityBlip() { /* blur noted; idle timeout does the pausing */ }

  window.addEventListener("focus", function () { markActivity(); ensureTracking(); });

  window.addEventListener("pagehide", function () {
    try {
      if (st.stage && st.session) {
        var body = JSON.stringify({ session_id: st.session, stage: st.stage,
          started_at: st.start, ended_at: isoNow(),
          active_ms: Math.max(0, Math.round(st.activeMs)) });
        if (navigator.sendBeacon) navigator.sendBeacon("/api/analytics/intervals", body);
        else post("/api/analytics/intervals", JSON.parse(body), true);
      }
      var data = JSON.stringify({ event_type: "SESSION_ENDED",
        stage: currentTabStage(), session_id: currentSessionId() });
      if (navigator.sendBeacon) navigator.sendBeacon("/api/analytics/events", data);
    } catch (e) {}
    try { sessionStorage.removeItem(STORE_KEY); } catch (e2) {}
  });

  function currentSessionId() {
    var stage = currentTabStage();
    return (stage && stage !== "lab") ? knownSession(stage) : null;
  }

  // Refresh recovery: an interval left open across a reload is closed at
  // its last tick (marked recovered) instead of being silently dropped.
  try {
    var raw = sessionStorage.getItem(STORE_KEY);
    if (raw) {
      sessionStorage.removeItem(STORE_KEY);
      var rec = JSON.parse(raw);
      if (rec && rec.session && rec.stage && rec.start) {
        post("/api/analytics/intervals", {
          session_id: rec.session, stage: rec.stage,
          started_at: rec.start,
          ended_at: new Date(rec.lastTick || Date.now()).toISOString(),
          active_ms: Math.max(0, Math.round(rec.activeMs || 0)) });
        postEvent("SESSION_RESUMED", { stage: rec.stage, session_id: rec.session,
          metadata: { reason: "refresh-recovery" } });
      }
    }
  } catch (e) {}

  /* ---------------- pedagogical events ---------------- */
  postEvent("APP_OPENED", {});

  document.querySelectorAll("#workspaceTabs .tab").forEach(function (b) {
    b.addEventListener("click", function () {
      var to = SECTION_STAGE[b.getAttribute("data-ws")] || null;
      var from = st.enteredStage || null;
      if (from && from !== to) {
        postEvent("STAGE_LEFT", { stage: from, session_id: knownSession(from) });
        if (st.stage) closeInterval("stage-change");
      }
      if (to) {
        postEvent("STAGE_ENTERED", { stage: to, session_id: knownSession(to) });
        st.enteredStage = to;
        markActivity();
        ensureTracking();
        renderProcess();
      }
    });
  });

  [["stage2Btn", "stage2"], ["stage3Btn", "stage3"], ["stage4Btn", "stage4"]].forEach(function (pair) {
    var el = document.getElementById(pair[0]);
    if (el) el.addEventListener("click", function () {
      postEvent("CONTINUE_CLICKED", { stage: pair[1], session_id: knownSession(pair[1]),
        metadata: { from_button: pair[0] } });
    });
  });

  var reflectBtn = $("reflectBtn");
  if (reflectBtn) reflectBtn.addEventListener("click", function () {
    postEvent("REFLECTION_SUBMITTED", { stage: "stage4", session_id: knownSession("stage4") });
  });

  /* ---------------- fetch observation (never alters traffic) ---------------- */
  var ANALYZE_URLS = {
    "/api/stage1/analyze": "stage1", "/api/stage2/analyze": "stage2",
    "/api/stage3/analyze": "stage3", "/api/stage4/reflect": "stage4",
    "/api/analyze": "lab"
  };

  function readSessionFromBody(stage, opts) {
    try {
      var b = opts && opts.body ? JSON.parse(opts.body) : {};
      if (b && typeof b.session_id === "string" && b.session_id) return b.session_id;
    } catch (e) {}
    return knownSession(stage);
  }

  if (!window.__essayAnalyticsFetchWrapped) {
    window.__essayAnalyticsFetchWrapped = true;
    var origFetch = window.fetch.bind(window);
    window.fetch = function (url, opts) {
      var u = String((url && url.url) || url || "");
      var path = u.split("?")[0];
      var method = ((opts && opts.method) || "GET").toUpperCase();
      var key = Object.keys(ANALYZE_URLS).filter(function (k) { return path === k || path.endsWith(k); })[0];
      if (method === "POST" && key) {
        try {
          postEvent("ANALYSIS_REQUESTED", {
            stage: ANALYZE_URLS[key],
            session_id: readSessionFromBody(ANALYZE_URLS[key], opts || {}) });
        } catch (e) {}
      }
      return origFetch(url, opts).then(function (res) {
        if (method === "POST" && key) {
          try { observeAnalyzeResponse(key, res); } catch (e) {}
        }
        return res;
      });
    };
  }

  function observeAnalyzeResponse(key, res) {
    var stage = ANALYZE_URLS[key];
    var session = readSessionFromBody(stage, {});
    res.clone().json().then(function (d) {
      if (!res.ok || !d) return;
      var sid = d.session_id || session;
      var rev = d.revision_number;
      var aid = d.analysis_id || ((d.analysis || {}).analysis_id);
      postEvent("REVISION_SUBMITTED", { stage: stage, session_id: sid,
        analysis_id: aid, revision_number: (typeof rev === "number") ? rev : undefined });
      var items = Array.isArray(d.feedback) ? d.feedback.length : 0;
      postEvent("FEEDBACK_DISPLAYED", { stage: stage, session_id: sid,
        analysis_id: aid, revision_number: (typeof rev === "number") ? rev : undefined,
        metadata: { feedback_items: items } });
      if (sid) ensureTracking();
      renderProcess();
    }).catch(function () {});
  }

  /* ---------------- student progress UI (counts only, never scores) ---------------- */
  function deepestSession() {
    try {
      var ES = window.EssayScaff || {};
      for (var k = 4; k >= 1; k--) {
        var d = ES["lastStage" + k];
        if (d && d.session_id) return d.session_id;
      }
    } catch (e) {}
    return null;
  }

  function renderProcess() {
    var box = $("processAnalytics");
    if (!box) return;
    var sid = deepestSession();
    if (!sid) {
      box.innerHTML = '<p class="hint">Analyze writing in any stage to see your process here. Only counts — never scores.</p>';
      return;
    }
    fetch("/api/analytics/session/" + encodeURIComponent(sid)).then(function (r) {
      return r.json().then(function (j) { return { ok: r.ok, j: j }; });
    }).then(function (res) {
      if (!res.ok) return;
      var a = res.j;
      var names = { stage1: "Idea", stage2: "Thesis", stage3: "Outline", stage4: "Reflection" };
      var html = "<h4>My writing process <span class='ro'>counts only</span></h4>";
      ["stage1", "stage2", "stage3", "stage4"].forEach(function (st) {
        var p = (a.per_stage || {})[st] || {};
        var t = (p.active_time || {}).active_ms || {};
        var prog = p.stage_progress || {};
        html += "<p><strong>" + names[st] + "</strong> — active " +
          esc(fmtDur(t.value != null ? t.value : null)) +
          " · revisions " + esc(p.revision_count != null ? p.revision_count : 0) +
          " · feedback items " + esc(((p.feedback_items_server || {}).value != null) ?
            p.feedback_items_server.value : 0) +
          " · status " + esc(prog.status || "not started") + "</p>";
      });
      var tot = (a.active_time || {}).total_ms || {};
      html += "<p><strong>Total active writing time: " + esc(fmtDur(tot.value)) + "</strong> · " +
        "total revisions " + esc(a.total_revisions != null ? a.total_revisions : 0) + "</p>";
      box.innerHTML = html;
    }).catch(function () {});
  }

  /* ---------------- test seam (no production behavior change) ---------------- */
  window.EssayScaffAnalytics = {
    fmtDur: fmtDur,
    idleTimeoutMs: function () { return IDLE_MS; },
    setIdleTimeoutMs: function (v) { IDLE_MS = v; },
    currentTabStage: currentTabStage,
    knownSession: knownSession,
    renderProcess: renderProcess,
    markActivity: markActivity,
    forceFlush: function () {
      if (st.stage && st.session && !st.paused) {
        var stage = st.stage, session = st.session;
        closeInterval("test-flush");
        openInterval(stage, session);
      }
    },
    state: function () { return { stage: st.stage, session: st.session, paused: st.paused }; }
  };

  fetch("/api/config").then(function (r) { return r.json(); }).then(function (cfg) {
    if (cfg && typeof cfg.analytics_idle_timeout_ms === "number") IDLE_MS = cfg.analytics_idle_timeout_ms;
    if (cfg && typeof cfg.analytics_flush_ms === "number") FLUSH_MS = cfg.analytics_flush_ms;
  }).catch(function () {});

  renderProcess();
})();
