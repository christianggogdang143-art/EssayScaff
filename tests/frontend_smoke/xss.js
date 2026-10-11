/* EssayScaff XSS regression probe (jsdom harness).
 *
 * Drives the REAL validation.js error renderer and the REAL stage3.js
 * outline editor against hostile payloads and asserts the resulting DOM
 * contains inert text, NOT live injected elements.
 *
 * Limitation (documented): jsdom does not fetch subresources, so an
 * onerror/onload handler that WOULD fire in a real browser may sit inert
 * here. The assertions therefore target DOM structure (no live injected
 * elements, no event-handler attributes, exact value round-trip), which
 * is the security boundary these renderers must guarantee.
 *
 * Usage: node xss.js --htmlroot <templates dir> --jsdir <static/js>
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

const htmlRoot = arg("htmlroot");
const jsDir = arg("jsdir");

function resp(body, status) {
  const text = JSON.stringify(body);
  const r = { ok: status >= 200 && status < 300, status, json: async () => body, text: async () => text };
  r.clone = () => resp(body, status);
  return r;
}

function stripScripts(html) {
  return html.replace(/<script\s+src="[^"]*"\s*><\/script>/g, "");
}

function inject(window, file) {
  const src = fs.readFileSync(path.join(jsDir, file), "utf8");
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

const verdict = {};
async function flow(name, fn) {
  try {
    verdict[name] = { ok: true, detail: await fn() };
  } catch (e) {
    verdict[name] = { ok: false, error: String((e && e.message) || e).slice(0, 500) };
  }
}

const EVIL = [
  "\"><img src=x onerror=\"window.__xss=1\">",
  "\"><svg onload=\"window.__xss=2\">",
  "<script>window.__xss=3</script>",
];

(async () => {
  // ---- Part A: validation.js error-analysis renderer ----
  {
    const html = stripScripts(fs.readFileSync(path.join(htmlRoot, "validation.html"), "utf8"));
    const dom = new JSDOM(html, { url: "http://127.0.0.1:5000/", pretendToBeVisual: true, runScripts: "dangerously" });
    const { window } = dom;
    window.fetch = async (url, opts) => {
      if (String(url).indexOf("/errors") >= 0) {
        return resp({ errors: EVIL.map(function (t, i) {
          return { sample_id: "VSMP-X" + i, matrix_cell: "h/n", correct: false,
            raw_text: t, human_label: "WEAK", label_source: "primary",
            system_prediction: "WEAK", system_evidence: { note: t },
            annotation_notes: t };
        }) }, 200);
      }
      if (String(url).indexOf("/api/validation/runs") >= 0) return resp({ runs: [] }, 200);
      if (String(url).indexOf("/api/validation/datasets") >= 0) return resp({ datasets: [] }, 200);
      if (String(url).indexOf("/api/validation/error-categories") >= 0) return resp({ categories: [] }, 200);
      return resp({}, 200);
    };
    window.alert = () => {};
    window.confirm = () => true;
    inject(window, "validation.js");
    await settle();

    await flow("xss_validation_errors_inert", async () => {
      const doc = window.document;
      const sel = doc.getElementById("resRun");
      const opt = doc.createElement("option");
      opt.value = "VRUN-XSS";
      sel.appendChild(opt);
      sel.value = "VRUN-XSS";
      doc.getElementById("errLoad").click();
      await settle();
      const host = doc.getElementById("errList");
      if (!host) throw new Error("missing #errList");
      if (host.querySelector("img")) throw new Error("live <img> element materialized in errList");
      if (host.querySelector("svg")) throw new Error("live <svg> element materialized in errList");
      if (host.querySelector("script")) throw new Error("live <script> element materialized in errList");
      if (host.querySelector("[onerror],[onload],[onclick],[onfocus]"))
        throw new Error("live event-handler attribute materialized in errList");
      const txt = host.textContent;
      EVIL.forEach(function (t) {
        if (txt.indexOf(t) < 0) throw new Error("payload text missing (renderer dropped content?): " + t.slice(0, 40));
      });
      if (window.__xss_test || window.__xss === 1 || window.__xss === 2 || window.__xss === 3)
        throw new Error("payload script executed");
      return "3 hostile payloads inert as text";
    });

    await flow("xss_validation_datasets_inert", async () => {
      // dataset list / run options interpolate names and ids
      const doc = window.document;
      if (doc.querySelector("#dsList img") || doc.querySelector("#dsList svg"))
        throw new Error("live element in dsList");
      return "dataset list clean";
    });
  }

  // ---- Part B: stage3.js outline editor value injection ----
  {
    const html = stripScripts(fs.readFileSync(path.join(htmlRoot, "index.html"), "utf8"));
    const dom = new JSDOM(html, { url: "http://127.0.0.1:5000/", pretendToBeVisual: true, runScripts: "dangerously" });
    const { window } = dom;
    window.fetch = async () => resp({}, 200);
    window.alert = () => {};
    window.confirm = () => true;
    ["shell.js", "stage3.js"].forEach(function (f) { inject(window, f); });
    await settle();

    await flow("xss_stage3_outline_values_literal", async () => {
      const doc = window.document;
      const payloads = [
        "\"><img src=x onerror=\"window.__xss=1\">",
        "\" onfocus=\"window.__xss=2\" autofocus=\"",
        "Fish & Chips <b>bold</b> \"quoted\" 'single'",
        "'><svg onload=\"window.__xss=3\">",
      ];
      const inputs = doc.querySelectorAll(".point-input");
      if (inputs.length < 2) throw new Error("expected outline inputs, got " + inputs.length);
      inputs[0].value = payloads[0];
      inputs[0].dispatchEvent(new window.Event("input", { bubbles: true }));
      inputs[1].value = payloads[1];
      inputs[1].dispatchEvent(new window.Event("input", { bubbles: true }));
      // force re-render through a structural action (add a detail row)
      doc.querySelector("[data-add-detail]").click();
      await settle();
      // detail payload via the newly added row's input is covered by typing;
      // also verify detail path by direct DOM value round-trip below
      const host = doc.getElementById("outlineEditor");
      if (host.querySelector("img")) throw new Error("live <img> element materialized in outlineEditor");
      if (host.querySelector("svg")) throw new Error("live <svg> element materialized in outlineEditor");
      if (host.querySelector("script")) throw new Error("live <script> element materialized in outlineEditor");
      if (host.querySelector("[onerror],[onload],[onclick],[onfocus]"))
        throw new Error("live event-handler attribute materialized in outlineEditor");
      const vals = Array.from(doc.querySelectorAll(".point-input")).map(function (el) { return el.value; });
      if (vals[0] !== payloads[0]) throw new Error("point value not round-tripped literally");
      if (vals[1] !== payloads[1]) throw new Error("point value not round-tripped literally");
      if (window.__xss === 1 || window.__xss === 2 || window.__xss === 3)
        throw new Error("payload script executed");
      return "outline values literal, no live elements";
    });

    await flow("xss_stage3_detail_and_ampersand", async () => {
      const doc = window.document;
      const det = doc.querySelector(".detail-input");
      if (!det) throw new Error("no detail input rendered");
      const payload = "Fish & Chips <b>bold</b> \"quoted\" 'single'";
      det.value = payload;
      det.dispatchEvent(new window.Event("input", { bubbles: true }));
      doc.querySelector("[data-add-detail]").click();
      await settle();
      const first = doc.querySelector(".detail-input");
      if (!first || first.value !== payload) throw new Error("detail value not round-tripped literally");
      if (doc.querySelector("#outlineEditor b")) throw new Error("live <b> element materialized");
      if (doc.querySelector("#outlineEditor img, #outlineEditor svg"))
        throw new Error("live media element materialized");
      return "detail + ampersand payload literal";
    });
  }

  console.log(JSON.stringify({ verdict }));
  const failed = Object.values(verdict).filter((v) => !v.ok);
  process.exit(failed.length ? 1 : 0);
})().catch((e) => {
  console.log(JSON.stringify({ fatal: String((e && e.message) || e) }));
  process.exit(2);
});
