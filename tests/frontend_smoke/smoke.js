/* EssayScaff frontend runtime smoke test (jsdom harness).
 *
 * Executes the REAL student JS files (stage1-4, live_feedback, shell,
 * transparency) against a REAL DOM built from templates/index.html, with
 * fetch stubbed to replay REAL backend payloads captured by pytest.
 * Catches runtime bugs (e.g. recursive readJson) that syntax checks miss.
 *
 * Limitation (documented): jsdom is not a real browser engine — no layout,
 * paint, or real event-loop timing. fetch/XHR and timers are stubbed.
 * What IS real: the shipped JS sources, the shipped markup, DOM semantics,
 * and backend response shapes.
 *
 * Usage: node smoke.js --html <index.html> --jsdir <static/js> --payloads <dir>
 * Prints a JSON verdict object to stdout; exit code 0 iff all flows pass.
 */
"use strict";

const fs = require("fs");
const path = require("path");
const { JSDOM } = require(process.env.JSDOM_PATH || "jsdom");

function arg(name) {
  const i = process.argv.indexOf("--" + name);
  if (i < 0 || i + 1 >= process.argv.length) throw new Error("missing --" + name);
  return process.argv[i + 1];
}

const htmlPath = arg("html");
const jsDir = arg("jsdir");
const payloadDir = arg("payloads");

function load(name) {
  return JSON.parse(fs.readFileSync(path.join(payloadDir, name + ".json"), "utf8"));
}

const P = {
  stage1: load("stage1"), stage1session: load("stage1session"),
  stage2: load("stage2"), stage2session: load("stage2session"),
  stage3: load("stage3"), stage3session: load("stage3session"),
  stage4: load("stage4"), stage4session: load("stage4session"),
  live: load("live"),
};

let html = fs.readFileSync(htmlPath, "utf8");
html = html.replace(/<script\s+src="[^"]*"\s*><\/script>/g, "");

const alerts = [];
const dom = new JSDOM(html, {
  url: "http://127.0.0.1:5000/",
  pretendToBeVisual: true,
  // Script elements execute with full window globals (document, etc.).
  // window.eval() does not provide them in this jsdom version.
  runScripts: "dangerously",
});
const { window } = dom;

// Copy Full Analysis support: capture clipboard writes (jsdom has no real
// clipboard). Installed before any shipped script loads.
window.__copiedReports = [];
try {
  Object.defineProperty(window.navigator, "clipboard", {
    value: { writeText: async function (t) { window.__copiedReports.push(String(t)); } },
    configurable: true,
  });
} catch (e) {
  window.navigator.clipboard = {
    writeText: async function (t) { window.__copiedReports.push(String(t)); },
  };
}

// Cross-stage-link regression support: record every stage analyze/reflect
// payload AND replay dynamic session/revision semantics (echo session_id
// when reusing, mint a fresh id otherwise, count revisions per session).
// The old canned-only replay masked stale-session reuse because every
// response carried the same canned session id regardless of the request.
const analyzeCalls = [];
const revCount = {};
let mintN = 0;
function mint(prefix) { mintN += 1; return prefix + "-HARNESS-" + mintN; }
function dynAnalyze(base, body, prefix, parentKeys) {
  const out = JSON.parse(JSON.stringify(base));
  let sid = null;
  try { sid = (body && typeof body.session_id === "string" && body.session_id) ? body.session_id : null; } catch (e) {}
  if (!sid) sid = mint(prefix);
  revCount[sid] = (revCount[sid] || 0) + 1;
  out.session_id = sid;
  out.revision_number = revCount[sid];
  (parentKeys || []).forEach(function (k) {
    out[k] = (body && body[k] !== undefined) ? body[k] : ((out[k] !== undefined) ? out[k] : null);
  });
  return out;
}
function reqBody(opts) {
  try { return opts && opts.body ? JSON.parse(opts.body) : null; } catch (e) { return null; }
}

function resp(body, status) {
  const text = JSON.stringify(body);
  const r = { ok: status >= 200 && status < 300, status, json: async () => body, text: async () => text };
  r.clone = () => resp(body, status); // faithful Response.clone for observer code
  return r;
}

window.fetch = async (url, opts) => {
  const method = (opts && opts.method) || "GET";
  const key = method + " " + url;
  if (url.startsWith("/api/analytics/")) {
    let body = null;
    try { body = opts && opts.body ? JSON.parse(opts.body) : null; } catch (e) {}
    analyticsCalls.push({ method, url, body });
    if (key === "POST /api/analytics/events") return resp({ logged: 1, event_ids: [1] }, 201);
    if (key === "POST /api/analytics/intervals") return resp({ stored: 1, duplicates_ignored: 0 }, 201);
    if (url.indexOf("/events") >= 0) return resp({ entry_stage: "stage1", count: 0, events: [] }, 200);
    return resp({ entry: "stage1", total_revisions: 4,
      active_time: { total_ms: { value: 123456, status: "OK", reason: null } },
      per_stage: {
        stage1: { revision_count: 1, server_analyses: 1,
          active_time: { active_ms: { value: 42442, status: "OK", reason: null } },
          feedback_items_server: { value: 3, status: "OK", reason: null },
          analyses_before_ready: { value: 1, status: "OK", reason: null },
          stage_progress: { status: "READY FOR THESIS FORMULATION" } },
        stage2: { revision_count: 1, server_analyses: 1,
          active_time: { active_ms: { value: 31000, status: "OK", reason: null } },
          feedback_items_server: { value: 2, status: "OK", reason: null },
          analyses_before_ready: { value: 1, status: "OK", reason: null },
          stage_progress: { status: "READY FOR OUTLINE DEVELOPMENT" } },
        stage3: { revision_count: 1, server_analyses: 1,
          active_time: { active_ms: { value: 25000, status: "OK", reason: null } },
          feedback_items_server: { value: null, status: "N/A", reason: "x" },
          analyses_before_ready: { value: null, status: "N/A", reason: "x" },
          stage_progress: { status: "READY FOR REFLECTION & REVISION" } },
        stage4: { revision_count: 1, server_analyses: 1,
          active_time: { active_ms: { value: 25014, status: "OK", reason: null } },
          feedback_items_server: { value: null, status: "N/A", reason: "x" },
          analyses_before_ready: { value: null, status: "N/A", reason: "x" },
          stage_progress: { status: "COMPLETE" } } } }, 200);
  }
  if (key === "GET /api/config") return resp({ debounce_ms: 50 }, 200);
  if (key === "POST /api/stage1/analyze") {
    const body = reqBody(opts);
    analyzeCalls.push({ url, body });
    return resp(dynAnalyze(P.stage1, body, "SES", []), 200);
  }
  if (url.startsWith("/api/stage1/session/")) return resp(P.stage1session, 200);
  if (key === "POST /api/stage2/analyze") {
    const body = reqBody(opts);
    analyzeCalls.push({ url, body });
    return resp(dynAnalyze(P.stage2, body, "SES2", ["stage1_session_id"]), 200);
  }
  if (url.startsWith("/api/stage2/session/")) return resp(P.stage2session, 200);
  if (key === "POST /api/stage3/analyze") {
    const body = reqBody(opts);
    analyzeCalls.push({ url, body });
    return resp(dynAnalyze(P.stage3, body, "SES3", ["stage2_session_id", "stage1_session_id"]), 200);
  }
  if (url.startsWith("/api/stage3/session/")) return resp(P.stage3session, 200);
  if (key === "POST /api/stage4/reflect") {
    const body = reqBody(opts);
    analyzeCalls.push({ url, body });
    return resp(dynAnalyze(P.stage4, body, "SES4",
      ["stage1_session_id", "stage2_session_id", "stage3_session_id"]), 200);
  }
  if (url.startsWith("/api/stage4/session/")) return resp(P.stage4session, 200);
  if (key === "POST /api/analyze") return resp(P.live, 200);
  return resp({ error: "harness: unknown route " + key }, 404);
};
window.alert = (m) => { alerts.push(String(m)); };
window.confirm = () => true;

window.__essayAnalyticsTickMs = 200;
const analyticsCalls = [];
for (const f of ["shell.js", "live_feedback.js", "highlight.js", "transparency.js", "walkthrough.js", "analytics.js", "stage1.js", "stage2.js", "stage3.js", "stage4.js", "feedback_focus.js"]) {
  const src = fs.readFileSync(path.join(jsDir, f), "utf8");
  const el = window.document.createElement("script");
  el.textContent = src;
  window.document.body.appendChild(el);
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function settle() {
  for (let i = 0; i < 12; i++) {
    await sleep(25);
    await Promise.resolve();
  }
}
function setVal(id, v) {
  const el = window.document.getElementById(id);
  if (!el) throw new Error("missing element #" + id);
  el.value = v;
  el.dispatchEvent(new window.Event("input", { bubbles: true }));
}
function click(id) {
  const el = window.document.getElementById(id);
  if (!el) throw new Error("missing element #" + id);
  el.click();
}
function clickWs(section) {
  const el = window.document.querySelector('#workspaceTabs [data-ws="' + section + '"]');
  if (!el) throw new Error("missing workspace tab " + section);
  el.click();
}
function text(id) {
  const el = window.document.getElementById(id);
  if (!el) throw new Error("missing element #" + id);
  return el.textContent;
}
function visible(id) {
  const el = window.document.getElementById(id);
  if (!el) throw new Error("missing element #" + id);
  return !el.hidden;
}
function setStage(v) {
  const el = window.document.getElementById("stage");
  if (!el) throw new Error("missing element #stage");
  el.value = v;
  el.dispatchEvent(new window.Event("change", { bubbles: true }));
}
function promptCards(id) {
  const el = window.document.getElementById(id);
  if (!el) throw new Error("missing element #" + id);
  return el.querySelectorAll(".prompt, .fb");
}
// Exact IDEA text the canned backend payloads were captured with. The stub
// replays canned offsets, so marking flows must analyze THIS text for the
// offsets to be valid (production always analyzes the displayed text).
const FIXTURE_IDEA = "Climate change affects crop production because extreme temperatures and irregular rainfall create difficulties for farmers.";

const verdict = {};
async function flow(name, fn) {
  try {
    verdict[name] = { ok: true, detail: await fn() };
  } catch (e) {
    verdict[name] = { ok: false, error: String((e && e.message) || e).slice(0, 500) };
  }
}

(async () => {
  await settle();

  await flow("copy_hidden_before_analysis", async () => {
    // Presentation gate: no button before Transparency Mode + real analysis.
    if (!window.document.getElementById("copyAnalysisBtn").hidden) {
      throw new Error("copy button visible with no analysis in student mode");
    }
    return "hidden before analysis";
  });

  await flow("stage1_analyze", async () => {
    setVal("ideaEditor", "Climate change affects crop production because extreme heat harms farmers.");
    setVal("s1Topic", "Effects of climate change on agriculture");
    setVal("s1Keywords", "climate, agriculture, farmers, crop, temperature, rainfall");
    click("ideaBtn");
    await settle();
    const s = text("ideaStatus");
    if (s.indexOf("Done — revision 1.") !== 0) throw new Error("ideaStatus=" + JSON.stringify(s));
    if (window.document.getElementById("stage2Btn").disabled !== false) throw new Error("stage2Btn still disabled");
    if (!window.EssayScaff || !window.EssayScaff.lastStage1) throw new Error("lastStage1 not set");
    return s;
  });

  await flow("direct_tab_2_stays_unlinked", async () => {
    // Research/manual path: opening Stage 2 via its tab (NOT Continue) must
    // not invent a link. The field stays empty and the hint stays put.
    clickWs("stage2Section");
    await settle();
    const v = window.document.getElementById("s2Stage1").value;
    if (v !== "") throw new Error("direct tab click auto-linked s2Stage1=" + JSON.stringify(v));
    const ref = text("stage1IdeaRef");
    if (ref.indexOf("Link a Stage 1 session") < 0) {
      throw new Error("idea ref hint clobbered without Continue: " + JSON.stringify(ref.slice(0, 120)));
    }
    clickWs("stage1Section");
    await settle();
    return "direct tab keeps manual/unlinked behavior";
  });

  await flow("stale_stage2_not_reused_setup", async () => {
    // Simulate the reported bug precondition: an older unlinked Stage-2
    // session exists in this browser state (research/test analysis done
    // before the normal Continue navigation).
    clickWs("stage2Section");
    await settle();
    setVal("thesisEditor", "Unlinked research thesis draft written before continuing the real chain.");
    click("thesisBtn");
    await settle();
    const posts = analyzeCalls.filter((c) => c.url === "/api/stage2/analyze");
    const last = posts[posts.length - 1].body;
    if (last.stage1_session_id) {
      throw new Error("setup analysis should be unlinked, got " + JSON.stringify(last.stage1_session_id));
    }
    const staleSid = window.EssayScaff.lastStage2.session_id;
    clickWs("stage1Section");
    await settle();
    return staleSid;
  });

  await flow("continue_1_to_2", async () => {
    const s1 = window.EssayScaff.lastStage1.session_id;
    const stale = (verdict.stale_stage2_not_reused_setup || {}).detail || null;
    click("stage2Btn");
    await settle();
    if (!visible("stage2Section") || visible("stage1Section")) throw new Error("tab did not switch to stage2");
    // 1. Real Stage 1 session id carried automatically.
    const v = window.document.getElementById("s2Stage1").value;
    if (v !== s1) throw new Error("s2Stage1=" + JSON.stringify(v) + " expected real id " + JSON.stringify(s1));
    // 2. Developed idea rendered read-only from the linked session.
    const ref = text("stage1IdeaRef");
    const wantIdea = P.stage1session.revisions[P.stage1session.revisions.length - 1].idea_text.slice(0, 30);
    if (ref.indexOf(wantIdea) < 0) throw new Error("developed idea absent from Stage 2 reference");
    if (ref.indexOf(s1) < 0) throw new Error("real Stage 1 id absent from Stage 2 reference");
    // 3. Stale session from another chain is dropped, never silently reused.
    if (window.EssayScaffStage2.getSessionId() !== null) {
      throw new Error("stale stage-2 session kept: " + window.EssayScaffStage2.getSessionId());
    }
    if (window.EssayScaff.lastStage2 !== null) throw new Error("stale lastStage2 kept");
    if (stale && window.EssayScaffStage2.getSessionId() === stale) throw new Error("reused stale session " + stale);
    const meta = text("thesisMeta");
    if (meta !== "") throw new Error("stale revision meta leaked into new chain: " + JSON.stringify(meta));
    return "stage2Section visible + linked " + s1;
  });

  await flow("stage2_analyze", async () => {
    const s1 = window.EssayScaff.lastStage1.session_id;
    const stale = (verdict.stale_stage2_not_reused_setup || {}).detail || null;
    setVal("thesisEditor", "Extreme temperatures and irregular rainfall reduce crop production and create significant challenges for farmers.");
    click("thesisBtn");
    await settle();
    const s = text("thesisStatus");
    // Fresh linked session: revision 1, NOT revision N of the stale session.
    if (s.indexOf("Done — revision 1.") !== 0) throw new Error("thesisStatus=" + JSON.stringify(s));
    if (window.document.getElementById("stage3Btn").disabled !== false) throw new Error("stage3Btn still disabled");
    if (!window.EssayScaff || !window.EssayScaff.lastStage2) throw new Error("lastStage2 not set");
    const posts = analyzeCalls.filter((c) => c.url === "/api/stage2/analyze");
    const last = posts[posts.length - 1].body;
    if (last.stage1_session_id !== s1) throw new Error("stage2 payload not linked: " + JSON.stringify(last));
    if (last.session_id) throw new Error("stale session_id sent in payload: " + JSON.stringify(last.session_id));
    const d = window.EssayScaff.lastStage2;
    if (d.stage1_session_id !== s1) throw new Error("stage2 response not linked to " + s1);
    if (d.revision_number !== 1) throw new Error("expected fresh revision 1, got " + d.revision_number);
    if (stale && d.session_id === stale) throw new Error("analysis reused stale session " + stale);
    return s;
  });

  await flow("direct_tab_3_stays_unlinked", async () => {
    clickWs("stage3Section");
    await settle();
    const v = window.document.getElementById("s3Stage2").value;
    if (v !== "") throw new Error("direct tab click auto-linked s3Stage2=" + JSON.stringify(v));
    const ref = text("stage2ThesisRef");
    if (ref.indexOf("Link a Stage 2 session") < 0) {
      throw new Error("thesis ref hint clobbered without Continue: " + JSON.stringify(ref.slice(0, 120)));
    }
    clickWs("stage2Section");
    await settle();
    return "direct tab keeps manual/unlinked behavior";
  });

  await flow("continue_2_to_3", async () => {
    const s2 = window.EssayScaff.lastStage2.session_id;
    click("stage3Btn");
    await settle();
    if (!visible("stage3Section")) throw new Error("tab did not switch to stage3");
    const v = window.document.getElementById("s3Stage2").value;
    if (v !== s2) throw new Error("s3Stage2=" + JSON.stringify(v) + " expected real id " + JSON.stringify(s2));
    const ref = text("stage2ThesisRef");
    const wantThesis = P.stage2session.revisions[P.stage2session.revisions.length - 1].thesis_text.slice(0, 30);
    if (ref.indexOf(wantThesis) < 0) throw new Error("thesis absent from Stage 3 reference");
    if (ref.indexOf(s2) < 0) throw new Error("real Stage 2 id absent from Stage 3 reference");
    if (window.EssayScaffStage3.getSessionId() !== null) {
      throw new Error("stale stage-3 session kept: " + window.EssayScaffStage3.getSessionId());
    }
    return "stage3Section visible + linked " + s2;
  });

  await flow("stage3_analyze", async () => {
    const s2 = window.EssayScaff.lastStage2.session_id;
    const inputs = window.document.querySelectorAll(".point-input");
    if (inputs.length < 2) throw new Error("expected 2 point inputs, got " + inputs.length);
    inputs[0].value = "Extreme temperatures reduce crop production.";
    inputs[0].dispatchEvent(new window.Event("input", { bubbles: true }));
    inputs[1].value = "Irregular rainfall disrupts planting schedules.";
    inputs[1].dispatchEvent(new window.Event("input", { bubbles: true }));
    click("outlineBtn");
    await settle();
    const s = text("outlineStatus");
    if (s.indexOf("Done — revision 1.") !== 0) throw new Error("outlineStatus=" + JSON.stringify(s));
    if (window.document.getElementById("stage4Btn").disabled !== false) throw new Error("stage4Btn still disabled");
    if (!window.EssayScaff || !window.EssayScaff.lastStage3) throw new Error("lastStage3 not set");
    const posts = analyzeCalls.filter((c) => c.url === "/api/stage3/analyze");
    const last = posts[posts.length - 1].body;
    if (last.stage2_session_id !== s2) throw new Error("stage3 payload not linked: " + JSON.stringify(last));
    if (window.EssayScaff.lastStage3.stage2_session_id !== s2) {
      throw new Error("stage3 response not linked to " + s2);
    }
    return s;
  });

  await flow("direct_tab_4_stays_manual", async () => {
    // Stage 4 has no chain yet only if no Continue populated it; at this
    // point stages 1-3 are linked but Stage 4 was never Continued to, so a
    // direct tab visit must not invent links.
    clickWs("stage4Section");
    await settle();
    ["s4Stage1", "s4Stage2", "s4Stage3"].forEach(function (id) {
      const v = window.document.getElementById(id).value;
      if (v !== "") throw new Error("direct tab click auto-linked " + id + "=" + JSON.stringify(v));
    });
    clickWs("stage3Section");
    await settle();
    return "direct tab keeps manual/unlinked behavior";
  });

  await flow("continue_3_to_4", async () => {
    const s1 = window.EssayScaff.lastStage1.session_id;
    const s2 = window.EssayScaff.lastStage2.session_id;
    const s3 = window.EssayScaff.lastStage3.session_id;
    click("stage4Btn");
    await settle();
    if (!visible("stage4Section")) throw new Error("tab did not switch to stage4");
    const got = ["s4Stage1", "s4Stage2", "s4Stage3"].map(function (id) {
      return window.document.getElementById(id).value;
    });
    if (got[0] !== s1 || got[1] !== s2 || got[2] !== s3) {
      throw new Error("stage4 links=" + JSON.stringify(got) +
        " expected [" + JSON.stringify(s1) + "," + JSON.stringify(s2) + "," + JSON.stringify(s3) + "]");
    }
    const ref = text("stage4PlanRef");
    [s1, s2, s3].forEach(function (sid) {
      if (ref.indexOf(sid) < 0) throw new Error("chain id absent from plan reference: " + sid);
    });
    if (window.EssayScaffStage4.getSessionId() !== null) {
      throw new Error("stale stage-4 session kept: " + window.EssayScaffStage4.getSessionId());
    }
    return "stage4Section visible + linked chain";
  });

  await flow("stage4_reflect", async () => {
    click("reflectBtn");
    await settle();
    const s = text("reflectStatus");
    if (s.indexOf("Done — revision 1.") !== 0) throw new Error("reflectStatus=" + JSON.stringify(s));
    if (!window.EssayScaff || !window.EssayScaff.lastStage4) throw new Error("lastStage4 not set");
    const posts = analyzeCalls.filter((c) => c.url === "/api/stage4/reflect");
    const last = posts[posts.length - 1].body;
    const d = window.EssayScaff.lastStage4;
    if (last.stage1_session_id !== window.EssayScaff.lastStage1.session_id ||
        last.stage2_session_id !== window.EssayScaff.lastStage2.session_id ||
        last.stage3_session_id !== window.EssayScaff.lastStage3.session_id) {
      throw new Error("stage4 payload broke the chain: " + JSON.stringify(last));
    }
    if (d.stage1_session_id !== last.stage1_session_id ||
        d.stage2_session_id !== last.stage2_session_id ||
        d.stage3_session_id !== last.stage3_session_id) {
      throw new Error("stage4 response broke the chain: " + JSON.stringify(d));
    }
    return s;
  });

  await flow("live_feedback_parse", async () => {
    setVal("editor", "Climate change affects crop production because extreme heat harms farmers.");
    await sleep(400);
    await settle();
    const s = text("status");
    if (s.indexOf("Done (") !== 0) throw new Error("status=" + JSON.stringify(s));
    if (!window.EssayScaff || !window.EssayScaff.lastData) throw new Error("lastData not set");
    return s;
  });

  await flow("labbtn_visibility_policy", async () => {
    // Gating policy: only appropriate Stage-4 states offer the lab move.
    const btn = window.document.getElementById("labBtn");
    if (!btn) throw new Error("missing #labBtn");
    window.EssayScaffStage4.updateLabButton({ decision: "READY_FOR_INDEPENDENT_REVIEW" });
    if (btn.hidden) throw new Error("labBtn hidden at READY_FOR_INDEPENDENT_REVIEW");
    window.EssayScaffStage4.updateLabButton({ decision: "COMPLETE" });
    if (btn.hidden) throw new Error("labBtn hidden at COMPLETE");
    window.EssayScaffStage4.updateLabButton({ decision: "REVISION_RECOMMENDED" });
    if (!btn.hidden) throw new Error("labBtn shown at REVISION_RECOMMENDED");
    window.EssayScaffStage4.updateLabButton({ decision: "REFLECTING" });
    if (!btn.hidden) throw new Error("labBtn shown at REFLECTING");
    window.EssayScaffStage4.updateLabButton({});
    if (!btn.hidden) throw new Error("labBtn shown with no readiness");
    // Restore the live state for later flows.
    window.EssayScaffStage4.updateLabButton(
      (window.EssayScaff.lastStage4 || {}).readiness || {});
    return "policy READY/COMPLETE only";
  });

  await flow("labbtn_hidden_for_unready_live", async () => {
    const dec = ((window.EssayScaff.lastStage4 || {}).readiness || {}).decision;
    const btn = window.document.getElementById("labBtn");
    const shouldShow = (dec === "READY_FOR_INDEPENDENT_REVIEW" || dec === "COMPLETE");
    if (btn.hidden === shouldShow) {
      throw new Error("labBtn visibility mismatches live decision " + JSON.stringify(dec));
    }
    return "live decision " + dec + " -> hidden=" + btn.hidden;
  });

  await flow("lab_continue_carries_chain", async () => {
    // Simulate the reported stale-lab bug: the lab still shows an older
    // unrelated topic while the current chain is about sleep.
    const SLEEP_TOPIC = "Effects of insufficient sleep on students' academic performance";
    const SLEEP_KWS = ["sleep", "students", "performance", "memory", "concentration"];
    window.EssayScaff.lastStage1.topic = SLEEP_TOPIC;
    window.EssayScaff.lastStage1.analysis.technical.phase2.topic = SLEEP_TOPIC;
    window.EssayScaff.lastStage1.analysis.technical.phase2.teacher_keywords = SLEEP_KWS.slice();
    setVal("topic", "Effects of climate change on agriculture");
    setVal("teacherKeywords", "climate, agriculture");
    window.EssayScaffStage4.updateLabButton({ decision: "READY_FOR_INDEPENDENT_REVIEW" });
    click("labBtn");
    await settle();
    if (!visible("studentSection") || visible("stage4Section")) {
      throw new Error("labBtn did not open the Writing Lab");
    }
    const t = window.document.getElementById("topic").value;
    const k = window.document.getElementById("teacherKeywords").value;
    if (t !== SLEEP_TOPIC) throw new Error("lab topic not carried: " + JSON.stringify(t));
    if (k !== SLEEP_KWS.join(", ")) throw new Error("lab keywords not carried: " + JSON.stringify(k));
    const chain = window.EssayScaff.labChain || {};
    if (!chain.stage1_session_id || !chain.stage2_session_id || !chain.stage3_session_id) {
      throw new Error("lab chain ids missing: " + JSON.stringify(chain));
    }
    const line = text("feedbackFocusLine");
    if (line.indexOf("Introduction") < 0) throw new Error("focus header wrong: " + JSON.stringify(line));
    return "lab opened with current chain context";
  });

  await flow("lab_hides_stage_prompts", async () => {
    ["guidedPrompts", "thesisPrompts", "outlinePrompts"].forEach(function (id) {
      const el = window.document.getElementById(id);
      if (!el.hidden) throw new Error("historical slot still active in lab: " + id);
    });
    if (window.document.getElementById("feedback").hidden) {
      throw new Error("current lab slot hidden");
    }
    return "only the current lab slot is active";
  });

  await flow("lab_starter_introduction", async () => {
    setVal("editor", "");
    setStage("introduction");
    clickWs("studentSection");
    await settle();
    const cards = promptCards("feedback");
    if (cards.length !== 1) throw new Error("expected 1 starter card, got " + cards.length);
    const html = window.document.getElementById("feedback").textContent;
    ["Start your introduction", "What does your reader need to know before seeing your thesis?"].forEach(function (m) {
      if (html.indexOf(m) < 0) throw new Error("intro starter missing: " + m);
    });
    return "one intro starter card";
  });

  await flow("lab_starter_body", async () => {
    setStage("body");
    clickWs("studentSection");
    await settle();
    const cards = promptCards("feedback");
    if (cards.length !== 1) throw new Error("expected 1 starter card, got " + cards.length);
    const html = window.document.getElementById("feedback").textContent;
    ["Develop your first body point", "Which outline point will you develop first?"].forEach(function (m) {
      if (html.indexOf(m) < 0) throw new Error("body starter missing: " + m);
    });
    return "one body starter card";
  });

  await flow("lab_starter_conclusion", async () => {
    setStage("conclusion");
    clickWs("studentSection");
    await settle();
    const cards = promptCards("feedback");
    if (cards.length !== 1) throw new Error("expected 1 starter card, got " + cards.length);
    const html = window.document.getElementById("feedback").textContent;
    ["Bring your argument together", "What final idea should your reader remember?"].forEach(function (m) {
      if (html.indexOf(m) < 0) throw new Error("conclusion starter missing: " + m);
    });
    return "one conclusion starter card";
  });

  await flow("lab_single_primary_card", async () => {
    setStage("introduction");
    setVal("editor", "Climate change affects crop production because extreme heat harms farmers.");
    await sleep(400);
    await settle();
    const items = (window.EssayScaff.lastData || {}).feedback || [];
    if (items.length < 2) throw new Error("fixture yields <2 findings, cannot prove one-card (" + items.length + ")");
    const cards = promptCards("feedback");
    if (cards.length !== 1) throw new Error("expected 1 primary card, got " + cards.length);
    const html = window.document.getElementById("feedback").textContent;
    if (html.indexOf(items[0].title) < 0) throw new Error("primary card is not the top finding");
    return "1 card from " + items.length + " findings";
  });

  await flow("hl_spans_match_offsets", async () => {
    clickWs("studentSection");
    await settle();
    setVal("editor", FIXTURE_IDEA);
    click("analyzeBtn");
    await settle();
    await settle();
    const ed = window.document.getElementById("editor").value;
    const items = (window.EssayScaff.lastData || {}).feedback || [];
    const HL = window.EssayScaffHighlight;
    if (!HL) throw new Error("highlight module missing");
    // Production contract: marks cover exactly the PRIMARY item (the one
    // visible card), so every highlight always has its explanation.
    const primary = window.EssayScaffFeedback.selectPrimary(items);
    if (!primary) throw new Error("no primary finding in fixture");
    const spans = HL.spansFor(ed, [primary]);
    const usable = Number.isInteger(primary.start) && Number.isInteger(primary.end) &&
      primary.start >= 0 && primary.end > primary.start && primary.end <= ed.length;
    const marks = HL.marksFor(primary.feedback_id);
    if (usable && !marks.length) throw new Error("primary span not rendered");
    if (!usable && marks.length) throw new Error("unusable primary rendered");
    if (usable) {
      const covered = marks.map((m) => m.textContent).join("");
      if (covered !== ed.slice(primary.start, primary.end)) throw new Error("mark text mismatch");
      // No other item's spans may render (no orphan highlights).
      const stray = window.document.querySelectorAll("#editorBackdrop mark").length - marks.length;
      if (stray !== 0) throw new Error("orphan marks rendered: " + stray);
    }
    return "primary span exact" + (usable ? "" : " (primary unspannable, correctly empty)");
  });

  await flow("hl_colors_match_legend", async () => {
    const HL = window.EssayScaffHighlight;
    const chips = window.document.querySelectorAll("#hlLegend .hl-chip");
    if (chips.length !== 3) throw new Error("legend chips != 3");
    const ed = window.document.getElementById("editor").value;
    const items = {};
    ((window.EssayScaff.lastData || {}).feedback || []).forEach((f) => { if (f) items[f.feedback_id] = f; });
    const primary = window.EssayScaffFeedback.selectPrimary(
      (window.EssayScaff.lastData || {}).feedback || []);
    const usable = primary && Number.isInteger(primary.start) && Number.isInteger(primary.end) &&
      primary.start >= 0 && primary.end > primary.start && primary.end <= ed.length;
    const marks = Array.from(window.document.querySelectorAll("#editorBackdrop mark"));
    if (usable && !marks.length) throw new Error("no marks rendered");
    if (!usable && marks.length) throw new Error("marks without usable primary");
    marks.forEach((m) => {
      const want = HL.colorClass(items[m.getAttribute("data-fb")]);
      if (!m.classList.contains(want)) throw new Error("color mismatch");
    });
    return marks.length + " marks colored per legend";
  });

  await flow("hl_null_offsets_skipped", async () => {
    const HL = window.EssayScaffHighlight;
    const out = HL.spansFor("abcdef", [
      { feedback_id: "A", start: 0, end: 3 },
      { feedback_id: "B", start: null, end: 4 },
      { feedback_id: "C", start: 2, end: 2 },
      { feedback_id: "D", start: -1, end: 4 },
      { feedback_id: "E", start: 1, end: 99 },
      { feedback_id: "F", start: 4 },
      null,
    ]);
    if (out.length !== 1 || out[0].fb !== "A") throw new Error("bad filtering: " + JSON.stringify(out));
    return "invalid spans skipped, nothing invented";
  });

  await flow("hl_typing_clears", async () => {
    setVal("editor", "A completely new draft about sleep and memory.");
    const n = window.document.querySelectorAll("#editorBackdrop mark").length;
    if (n !== 0) throw new Error("marks survived typing: " + n);
    await settle();
    return "cleared on input";
  });

  await flow("hl_card_mark_link", async () => {
    // Restore analyzable text first: the previous flow typed a short draft
    // for which the canned offsets are out of range (correctly unrendered).
    setVal("editor", FIXTURE_IDEA);
    click("analyzeBtn");
    await settle();
    await settle();
    const HL = window.EssayScaffHighlight;
    const cards = window.document.querySelectorAll("#feedback .fb[data-fb]");
    if (!cards.length) throw new Error("no cards with data-fb");
    let card = null, marks = [];
    for (const c of cards) {
      const m = HL.marksFor(c.getAttribute("data-fb"));
      if (m.length) { card = c; marks = m; break; }
    }
    if (!card) throw new Error("no card has rendered marks");
    card.click();
    await settle();
    if (marks.filter((m) => m.classList.contains("hl-flash")).length === 0) {
      throw new Error("mark not flashed");
    }
    if (!card.classList.contains("hl-flash")) throw new Error("card not flashed");
    marks[0].click();
    await settle();
    if (!card.classList.contains("hl-flash")) throw new Error("card not flashed via mark");
    return "two-way link works";
  });

  await flow("hl_no_new_requests", async () => {
    const before = analyzeCalls.length;
    const cards = window.document.querySelectorAll("#feedback .fb[data-fb]");
    if (cards.length) { cards[0].click(); await settle(); }
    const marks = window.document.querySelectorAll("#editorBackdrop mark");
    if (marks.length) { marks[0].click(); await settle(); }
    if (analyzeCalls.length !== before) throw new Error("highlight interaction fetched");
    return "interactions fetch-free";
  });

  await flow("select_primary_sequencing", async () => {
    const sel = window.EssayScaffFeedback.selectPrimary;
    if (typeof sel !== "function") throw new Error("selectPrimary not exposed");
    const A = { prompt_id: "P-A", priority: "HIGH" };
    const B = { prompt_id: "P-B", priority: "MEDIUM" };
    const C = { prompt_id: "P-C", priority: "LOW" };
    if (sel([C, B, A]) !== A) throw new Error("did not pick highest priority");
    if (sel([C, B]) !== B) throw new Error("resolved head did not reveal next issue");
    if (sel([]) !== null) throw new Error("empty list should yield null");
    const w1 = { feedback_id: "FB-1", severity: "info" };
    const w2 = { feedback_id: "FB-2", severity: "warning" };
    if (sel([w1, w2]) !== w2) throw new Error("warning should outrank info");
    return "resolve-first reveals next";
  });

  await flow("dash_goal_next_stages", async () => {
    const cases = [
      ["stage1Section", "Develop one focused idea about the assignment topic.",
       "Once your idea is focused, turn it into one clear thesis."],
      ["stage2Section", "Turn your idea into one clear thesis direction.",
       "Once your thesis is clear, organize the ideas that will support it."],
      ["stage3Section", "Organize your thesis into clear body points and supporting details.",
       "Once your outline is complete, review the plan before drafting."],
      ["stage4Section", "Review your writing plan and identify what still needs improvement.",
       "When your plan is ready, start writing your essay in the Writing Lab."],
    ];
    for (const [ws, goal, next] of cases) {
      clickWs(ws);
      await settle();
      if (text("dashGoal").indexOf(goal) < 0) throw new Error(ws + " goal wrong");
      if (text("dashNext").indexOf(next) < 0) throw new Error(ws + " next wrong");
    }
    const labModes = [
      ["introduction", "Introduce the topic and lead the reader toward your main argument.",
       "After establishing your direction, develop the body of the essay."],
      ["body", "Develop one main point and show how it supports your thesis.",
       "After developing your supporting points, prepare to bring them together."],
      ["conclusion", "Bring the main argument together and leave the reader with a clear takeaway.",
       "After completing the conclusion, review the essay as a whole."],
    ];
    for (const [mode, goal, next] of labModes) {
      setStage(mode);
      clickWs("studentSection");
      await settle();
      if (text("dashGoal").indexOf(goal) < 0) throw new Error(mode + " goal wrong");
      if (text("dashNext").indexOf(next) < 0) throw new Error(mode + " next wrong");
      const want = mode.charAt(0).toUpperCase() + mode.slice(1);
      if (text("feedbackFocusLine").indexOf(want) < 0) throw new Error("header missing " + mode);
    }
    setStage("introduction");
    await settle();
    return "goal+next correct for 4 stages + 3 lab modes";
  });

  await flow("dash_working_stage1", async () => {
    clickWs("stage1Section");
    await settle();
    const box = window.document.getElementById("dashWorking");
    if (box.hidden) throw new Error("working hidden with evidence available");
    const items = box.querySelectorAll("li");
    if (!items.length || items.length > 3) throw new Error("working items out of range: " + items.length);
    const allowed = ["C1", "C2", "C3", "PREWRITE_004", "PREWRITE_005", "PREWRITE_006", "PREWRITE_007", "PREWRITE_008"];
    const seen = [];
    for (const li of items) {
      const ev = li.getAttribute("data-ev");
      if (allowed.indexOf(ev) < 0) throw new Error("unproven working item: " + ev);
      seen.push(ev);
    }
    const d = window.EssayScaff.lastStage1;
    const c2 = d.readiness.conditions.filter((c) => c.id === "C2")[0].result;
    if ((c2 === "PASS") !== (seen.indexOf("C2") >= 0)) throw new Error("C2 item mismatches readiness");
    return seen.length + " proven items";
  });

  await flow("dash_checklist_stage2", async () => {
    clickWs("stage2Section");
    await settle();
    const box = window.document.getElementById("dashChecklist");
    if (box.hidden) throw new Error("checklist hidden with readiness available");
    const rows = box.querySelectorAll("li");
    if (!rows.length || rows.length > 5) throw new Error("checklist rows out of range: " + rows.length);
    const d = window.EssayScaff.lastStage2;
    const conds = {};
    d.readiness.conditions.forEach((c) => { conds[c.id] = c.result; });
    for (const li of rows) {
      const id = li.getAttribute("data-cond");
      if (!(id in conds)) throw new Error("row is not a real condition: " + id);
      const mark = li.querySelector(".mark").textContent;
      if (conds[id] === "PASS" && mark !== "✓") throw new Error(id + " PASS without check");
      if (conds[id] !== "PASS" && !(mark === "○" || mark === "!")) throw new Error(id + " FAIL without open/crit");
      if (/\b[CR][0-9]\b/.test(li.textContent)) throw new Error("raw readiness id leaked: " + li.textContent.slice(0, 80));
    }
    return rows.length + " rows traceable to readiness";
  });

  await flow("dash_snapshot_lab", async () => {
    clickWs("studentSection");
    setStage("introduction");
    await settle();
    await settle();
    const d = window.EssayScaff.lastData;
    const toks = ((d.technical || {}).tokens) || [];
    const alpha = toks.filter((t) => t && t.is_alpha).length;
    const ns = (((d.technical || {}).sentences) || []).length;
    const box = text("dashSnapshot");
    if (box.indexOf("Revision") < 0 || box.indexOf("live") < 0) throw new Error("lab revision wrong");
    if (box.indexOf(String(alpha)) < 0) throw new Error("word count wrong, want " + alpha);
    if (box.indexOf(String(ns)) < 0) throw new Error("sentence count wrong, want " + ns);
    if (box.indexOf("Active time") < 0) throw new Error("active time row missing");
    const cls = (d.summary || {}).topic_classification;
    if (cls && box.indexOf(cls) < 0) throw new Error("topic connection missing");
    if (box.indexOf("not a grade") < 0) throw new Error("lexical-evidence note missing");
    ["dashGoal", "dashWorking", "dashNext", "dashChecklist", "dashSnapshot"].forEach(function (id) {
      const t = text(id);
      if (/score|coherence|clarity|%/i.test(t)) throw new Error("fake-score language in " + id);
      const grades = (t.match(/grade/gi) || []).length;
      if (grades > 1 || (grades === 1 && t.indexOf("not a grade") < 0)) {
        throw new Error("grade language in " + id);
      }
    });
    return "snapshot honest, no fake scores";
  });

  await flow("dash_snapshot_stage_time", async () => {
    clickWs("stage1Section");
    await settle();
    const d = window.EssayScaff.lastStage1;
    let t = "";
    for (let i = 0; i < 20; i++) {
      t = text("dashSnapTime");
      if (t !== "—") break;
      await sleep(100);
    }
    if (!/^\d\d:\d\d$/.test(t)) throw new Error("active time not analytics mm:ss: " + JSON.stringify(t));
    const proc = ((d.summary || {}).processing_ms || 0).toFixed(2);
    if (t === proc) throw new Error("active time equals processing_ms");
    const box = text("dashSnapshot");
    if (!/Revision\s*1/.test(box)) throw new Error("stage revision wrong");
    return "active time " + t + " from analytics, not processing";
  });

  await flow("dash_prev_and_switch", async () => {
    clickWs("studentSection");
    await settle();
    const n = parseInt(text("dashPrevCount"), 10);
    if (!(n >= 1)) throw new Error("prev count wrong: " + n);
    click("feedbackHistoryBtn");
    await settle();
    if (!visible("pane-revisions")) throw new Error("history did not open");
    clickWs("stage1Section");
    await settle();
    if (text("dashGoal").indexOf("Develop one focused idea") < 0) throw new Error("goal not refreshed");
    if (!window.document.getElementById("thesisPrompts").hidden) throw new Error("old stage content leaked");
    clickWs("stage2Section");
    await settle();
    if (text("dashGoal").indexOf("Turn your idea into one clear thesis") < 0) throw new Error("goal not refreshed s2");
    if (!window.document.getElementById("guidedPrompts").hidden) throw new Error("old stage content leaked s1");
    return "prev=" + n + ", switching isolates + refreshes";
  });

  await flow("dash_one_primary_visible", async () => {
    clickWs("studentSection");
    await settle();
    const vis = ["feedback", "guidedPrompts", "thesisPrompts", "outlinePrompts", "reflectionPrompts"]
      .filter((id) => !window.document.getElementById(id).hidden);
    if (vis.join(",") !== "feedback") throw new Error("active slots wrong: " + vis);
    if (promptCards("feedback").length !== 1) throw new Error("primary cards != 1");
    return "exactly one primary card";
  });

  await flow("transparency_keeps_all_findings", async () => {
    click("transparencyViewBtn");
    await settle();
    const rules = text("tab-rules");
    const ids = rules.match(/[A-Z]+_\d{3}/g) || [];
    if (new Set(ids).size < 2) throw new Error("transparency rules incomplete: " + JSON.stringify(rules.slice(0, 200)));
    click("studentViewBtn");
    await settle();
    return new Set(ids).size + " distinct rule ids still inspectable";
  });

  await flow("revisions_keep_history", async () => {
    const h = text("revisionHistory");
    if (h.indexOf("R1") < 0) throw new Error("stage-1 revision history lost: " + JSON.stringify(h.slice(0, 200)));
    return "history preserved";
  });

  await flow("student_transparency_toggle", async () => {
    setVal("editor", "KEEPME-12345");
    click("transparencyViewBtn");
    await settle();
    click("studentViewBtn");
    await settle();
    const v = window.document.getElementById("editor").value;
    if (v !== "KEEPME-12345") throw new Error("editor text lost across toggle");
    return "editor preserved";
  });

  await flow("walkthrough_hidden_in_student", async () => {
    if (visible("walkthrough")) throw new Error("walkthrough visible in student mode");
    return "hidden in student mode";
  });

  await flow("walkthrough_shows_in_transparency", async () => {
    clickWs("studentSection");
    await settle();
    click("transparencyViewBtn");
    await settle();
    if (!visible("walkthrough")) throw new Error("walkthrough hidden in transparency mode");
    ["wt-s0", "wt-s4", "wt-s6", "wt-s8", "wt-s11", "wt-s12", "wt-s13", "wt-s14", "wt-s16", "wt-s17"].forEach(function (id) {
      if (window.document.getElementById(id) == null) throw new Error("missing section " + id);
    });
    return "walkthrough rendered";
  });

  await flow("walkthrough_renders_real_data", async () => {
    const body = text("walkthroughBody");
    ["Keyword Score", "DOCUMENT 0 — TOPIC DOCUMENT", "Cosine similarity",
     "THESIS_001", "FINAL KEYWORD SCORE", "Topic classification",
     "How the problem became feedback",
     "not an essay grade", "ESSAYSCAFF LOGIC", "SCIKIT-LEARN"].forEach(function (marker) {
      if (body.indexOf(marker) < 0) throw new Error("missing marker: " + marker);
    });
    return "real-data markers present";
  });

  await flow("walkthrough_follows_stage_tab", async () => {
    clickWs("stage1Section");
    await settle();
    if (!visible("walkthrough")) throw new Error("walkthrough hidden on stage tab");
    const body = text("walkthroughBody");
    // NOTE: the stub replays the canned backend payload regardless of typed
    // input, so the exact input text is the payload's raw_input below.
    if (body.indexOf("extreme temperatures") < 0) throw new Error("stage-1 exact input text absent");
    if (body.indexOf("Stage 1") < 0) throw new Error("stage source label absent");
    if (body.indexOf("Writing Lab") >= 0) throw new Error("stale writing-lab source leaked into stage view");
    return "exact stage-1 essay shown";
  });

  await flow("walkthrough_stage4_honest", async () => {
    clickWs("stage4Section");
    await settle();
    if (!visible("walkthrough")) throw new Error("walkthrough hidden on stage-4 tab");
    const body = text("walkthroughBody").toLowerCase();
    if (body.indexOf("not available") < 0) throw new Error("stage-4 honesty note absent");
    if (body.indexOf("stage 4") < 0) throw new Error("stage source label absent");
    return "stage-4 limited mode honest";
  });

  await flow("copy_stage1_report", async () => {
    click("transparencyViewBtn");
    await settle();
    clickWs("stage1Section");
    await settle();
    if (window.document.getElementById("copyAnalysisBtn").hidden) {
      throw new Error("copy button hidden in transparency mode with analysis");
    }
    const before = analyzeCalls.length;
    window.__copiedReports.length = 0;
    click("copyAnalysisBtn");
    await settle();
    await settle();
    if (!window.__copiedReports.length) throw new Error("copy click produced no clipboard write");
    if (window.document.getElementById("copyAnalysisBtn").textContent.indexOf("Copied") < 0) {
      throw new Error("no Copied! success state");
    }
    const md = window.__copiedReports[window.__copiedReports.length - 1];
    const s1 = window.EssayScaff.lastStage1.session_id;
    ["# ESSAYSCAFF FULL ANALYSIS", "Source: Stage 1", s1,
     "## 14. Generic Writing Rules", "## 15. Stage-Specific Analysis",
     "## 16. Feedback Trace", "## 17. Readiness", "## 19. Final Summary",
     "### GENERIC WRITING FINDINGS", "### STAGE-SPECIFIC SCAFFOLDING FINDINGS",
     "| # | Token |", "## 6. Keyword Extraction", "## 12. Cosine Similarity",
     "PREWRITE", "stage2_allowed"].forEach(function (m) {
      if (md.indexOf(m) < 0) throw new Error("stage-1 report missing: " + m);
    });
    // ALL token rows / keyword candidates / vocabulary — no truncation.
    window.EssayScaff.lastStage1.analysis.technical.tokens.forEach(function (tk) {
      if (md.indexOf("| " + tk.text + " |") < 0) throw new Error("token row missing: " + tk.text);
    });
    window.EssayScaff.lastStage1.analysis.technical.phase2.keywords.terms.forEach(function (t) {
      if (md.indexOf("| " + (t.surface || t.lemma) + " |") < 0) throw new Error("keyword candidate missing");
    });
    window.EssayScaff.lastStage1.analysis.technical.phase2.topic_analysis.tfidf.vocabulary.forEach(function (v) {
      if (md.indexOf("| " + v + " |") < 0) throw new Error("vocabulary row missing: " + v);
    });
    if (analyzeCalls.length !== before) throw new Error("copy triggered an analyze request");
    return md.length + " chars, active source Stage 1";
  });

  await flow("copy_stage2_report", async () => {
    clickWs("stage2Section");
    await settle();
    const before = analyzeCalls.length;
    window.__copiedReports.length = 0;
    click("copyAnalysisBtn");
    await settle();
    await settle();
    const md = window.__copiedReports[window.__copiedReports.length - 1];
    if (!md) throw new Error("nothing copied");
    const s2 = window.EssayScaff.lastStage2.session_id;
    ["Source: Stage 2", s2, "THESIS_001", "stage3_allowed",
     "## 15. Stage-Specific Analysis", "## 17. Readiness"].forEach(function (m) {
      if (md.indexOf(m) < 0) throw new Error("stage-2 report missing: " + m);
    });
    if (analyzeCalls.length !== before) throw new Error("copy triggered an analyze request");
    return md.length + " chars, active source Stage 2";
  });

  await flow("copy_stage3_report", async () => {
    clickWs("stage3Section");
    await settle();
    const before = analyzeCalls.length;
    window.__copiedReports.length = 0;
    click("copyAnalysisBtn");
    await settle();
    await settle();
    const md = window.__copiedReports[window.__copiedReports.length - 1];
    if (!md) throw new Error("nothing copied");
    const s3 = window.EssayScaff.lastStage3.session_id;
    ["Source: Stage 3", s3, "OUTLINE", "stage4_allowed",
     "Extreme temperatures reduce crop production."].forEach(function (m) {
      if (md.indexOf(m) < 0) throw new Error("stage-3 report missing: " + m);
    });
    if (analyzeCalls.length !== before) throw new Error("copy triggered an analyze request");
    return md.length + " chars, active source Stage 3 (stage-only)";
  });

  await flow("copy_stage4_report", async () => {
    clickWs("stage4Section");
    await settle();
    const before = analyzeCalls.length;
    window.__copiedReports.length = 0;
    click("copyAnalysisBtn");
    await settle();
    await settle();
    const md = window.__copiedReports[window.__copiedReports.length - 1];
    if (!md) throw new Error("nothing copied");
    const s4 = window.EssayScaff.lastStage4.session_id;
    ["Source: Stage 4", s4, "REFLECT", "reflection_complete"].forEach(function (m) {
      if (md.indexOf(m) < 0) throw new Error("stage-4 report missing: " + m);
    });
    if (analyzeCalls.length !== before) throw new Error("copy triggered an analyze request");
    return md.length + " chars, active source Stage 4 (stage-only)";
  });

  await flow("copy_lab_report", async () => {
    clickWs("studentSection");
    await settle();
    const before = analyzeCalls.length;
    window.__copiedReports.length = 0;
    click("copyAnalysisBtn");
    await settle();
    await settle();
    const md = window.__copiedReports[window.__copiedReports.length - 1];
    if (!md) throw new Error("nothing copied");
    const aid = window.EssayScaff.lastData.analysis_id;
    ["Source: Writing Lab", aid, "## 14. Generic Writing Rules",
     "## 12. Cosine Similarity"].forEach(function (m) {
      if (md.indexOf(m) < 0) throw new Error("lab report missing: " + m);
    });
    if (analyzeCalls.length !== before) throw new Error("copy triggered an analyze request");
    return md.length + " chars, active source Writing Lab";
  });

  await flow("copy_missing_data_safe", async () => {
    const saved = window.EssayScaff.lastData;
    window.EssayScaff.lastData = { analysis_id: "COPY-PROBE" };
    let rep = null;
    try {
      rep = window.EssayScaffWalkthrough.buildCopyReport();
    } finally {
      window.EssayScaff.lastData = saved;
    }
    if (!rep || !rep.ok) throw new Error("sparse source should still copy");
    if (rep.markdown.indexOf("N/A") < 0) throw new Error("missing values not labeled N/A");
    if (rep.markdown.indexOf("COPY-PROBE") < 0) throw new Error("report left the active source");
    return "sparse copies safely with N/A labels";
  });

  await flow("copy_hidden_in_student", async () => {
    click("studentViewBtn");
    await settle();
    if (!window.document.getElementById("copyAnalysisBtn").hidden) {
      throw new Error("copy button visible in student mode");
    }
    click("transparencyViewBtn");
    await settle();
    return "hidden in student mode, back in transparency";
  });

  await flow("walkthrough_missing_data_safe", async () => {
    clickWs("studentSection");
    await settle();
    window.EssayScaff.lastData = { analysis_id: "WT-PROBE" };
    window.EssayScaffWalkthrough.refresh();
    await settle();
    const body = text("walkthroughBody");
    if (body.indexOf("Not available") < 0) throw new Error("missing-data fallback absent");
    return "sparse payload renders safely";
  });

  await flow("analytics_app_opened", async () => {
    const hits = analyticsCalls.filter((c) => c.url === "/api/analytics/events" &&
      c.body && c.body.event_type === "APP_OPENED");
    if (!hits.length) throw new Error("APP_OPENED not posted");
    return "APP_OPENED posted";
  });

  await flow("analytics_stage_events", async () => {
    const types = analyticsCalls.filter((c) => c.url === "/api/analytics/events" && c.body)
      .map((c) => c.body.event_type);
    ["STAGE_ENTERED", "ANALYSIS_REQUESTED", "REVISION_SUBMITTED", "FEEDBACK_DISPLAYED"].forEach(function (t) {
      if (types.indexOf(t) < 0) throw new Error("missing client event " + t);
    });
    return "stage event types posted";
  });

  await flow("analytics_active_interval", async () => {
    clickWs("stage1Section");
    await settle();
    setVal("ideaEditor", "typing for active-time measurement");
    await sleep(700);
    await settle();
    window.EssayScaffAnalytics.forceFlush();
    await settle();
    const posts = analyticsCalls.filter((c) => c.url === "/api/analytics/intervals" && c.body);
    if (!posts.length) throw new Error("no interval posted");
    const last = posts[posts.length - 1].body;
    if (last.stage !== "stage1") throw new Error("interval stage=" + last.stage);
    if (typeof last.active_ms !== "number" || last.active_ms < 0) throw new Error("bad active_ms");
    if (!last.started_at || !last.ended_at) throw new Error("interval bounds missing");
    return "interval posted active_ms=" + last.active_ms;
  });

  await flow("analytics_idle_pause", async () => {
    window.EssayScaffAnalytics.setIdleTimeoutMs(300);
    await sleep(900);
    await settle();
    const paused = analyticsCalls.filter((c) => c.url === "/api/analytics/events" && c.body &&
      c.body.event_type === "SESSION_PAUSED");
    if (!paused.length) throw new Error("SESSION_PAUSED not posted after idle timeout");
    window.EssayScaffAnalytics.setIdleTimeoutMs(300000);
    return "idle pause posted";
  });

  await flow("analytics_progress_renders", async () => {
    const body = text("processAnalytics");
    if (body.indexOf("My writing process") < 0) throw new Error("progress block absent");
    if (body.indexOf("Total active writing time") < 0) throw new Error("totals absent");
    if (body.indexOf("02m 03s") < 0) throw new Error("total duration not rendered: " + body.slice(0, 300));
    return "progress block rendered";
  });

  await flow("analytics_no_essay_text", async () => {
    const blob = JSON.stringify(analyticsCalls);
    if (blob.indexOf("extreme heat harms farmers") >= 0) throw new Error("essay text leaked into analytics");
    if (blob.indexOf("typing for active-time") >= 0) throw new Error("keystroke content leaked into analytics");
    return "no essay text in analytics traffic";
  });

  await flow("analytics_refresh_recovery", async () => {
    const sid = window.EssayScaff.lastStage1.session_id;
    const now = Date.now();
    window.sessionStorage.setItem("essayAnalytics.open", JSON.stringify({
      stage: "stage1", session: sid,
      start: new Date(now - 500000).toISOString(),
      activeMs: 424242, lastTick: now }));
    const src = fs.readFileSync(path.join(jsDir, "analytics.js"), "utf8");
    const el = window.document.createElement("script");
    el.textContent = src;
    window.document.body.appendChild(el);
    await settle();
    const rec = analyticsCalls.filter((c) => c.url === "/api/analytics/intervals" && c.body &&
      c.body.active_ms === 424242);
    if (!rec.length) throw new Error("refresh-recovered interval not flushed");
    return "refresh recovery flushed";
  });

  // NOTE: these two run LAST on purpose. Both navigate to Stage 4 with a
  // different (or empty) chain, which by design resets the in-memory
  // Stage-4 session of the main chain (stale-session protection). Nothing
  // after them depends on that session.
  await flow("manual_stage3_to_4_recovers_s1", async () => {
    // Manual/research entry: this browser lost ALL Stage-1 state, but
    // Stage 3 holds a linked Stage-2 session. Continue must recover the
    // Stage-1 parent from the stored Stage-2 record — never invent it.
    window.EssayScaff.lastStage1 = null;
    window.document.getElementById("s2Stage1").value = "";
    try { window.sessionStorage.removeItem("essayscaff.s2Stage1"); } catch (e) {}
    clickWs("stage3Section");
    await settle();
    const s2 = window.document.getElementById("s3Stage2").value;
    if (!s2) throw new Error("no linked Stage-2 session in Stage 3 for fallback test");
    const storedS1 = P.stage2session.revisions[P.stage2session.revisions.length - 1].stage1_session_id;
    if (!storedS1) throw new Error("canned Stage-2 record has no stored Stage-1 parent");
    click("stage4Btn");
    await settle();
    await settle();
    if (!visible("stage4Section")) throw new Error("tab did not switch to stage4");
    const gotS1 = window.document.getElementById("s4Stage1").value;
    if (gotS1 !== storedS1) {
      throw new Error("s4Stage1=" + JSON.stringify(gotS1) + " expected server-resolved " + JSON.stringify(storedS1));
    }
    return "Stage-1 recovered from server: " + gotS1;
  });

  await flow("unlinked_stage3_stays_honestly_partial", async () => {
    // Unlinked research Stage 3 with no valid parent chain: Continue must
    // NOT fabricate a Stage-1 id.
    const r = await window.EssayScaffStage4.applyContinueLink({ s1: null, s2: null, s3: null });
    void r;
    await settle();
    const ref = text("stage4PlanRef");
    if (ref.indexOf("Link at least one session first.") < 0) {
      throw new Error("empty chain should stay honestly partial, got: " + JSON.stringify(ref.slice(0, 120)));
    }
    return "honestly partial, no fake id";
  });

  console.log(JSON.stringify({ verdict, alerts: alerts.slice(0, 5) }));
  const failed = Object.values(verdict).filter((v) => !v.ok);
  process.exit(failed.length ? 1 : 0);
})().catch((e) => {
  console.log(JSON.stringify({ fatal: String((e && e.message) || e) }));
  process.exit(2);
});
