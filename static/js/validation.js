/* Phase 7A researcher validation workspace.
 * ANNOTATION MODE (annotate tab): blinded — no predictions fetched or shown.
 * ERROR ANALYSIS MODE (errors tab): predictions visible, COMPLETE runs only.
 */
(function () {
  "use strict";

  function $(id) { return document.getElementById(id); }

  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  async function readJson(res) {
    const text = await res.text();
    try { return { status: res.status, body: JSON.parse(text) }; }
    catch (e) { return { status: res.status, body: { error: text.slice(0, 300) } }; }
  }

  function setText(id, value) {
    const el = $(id);
    if (el) el.textContent = value;
  }

  // ---- tabs ----
  const tabs = Array.from(document.querySelectorAll("[data-vtab]"));
  tabs.forEach(function (btn) {
    btn.addEventListener("click", function () {
      tabs.forEach(function (b) { b.setAttribute("aria-selected", b === btn ? "true" : "false"); });
      ["datasets", "annotate", "quality", "freezerun", "results", "errors", "analytics", "provenance"].forEach(function (name) {
        const pane = $("vtab-" + name);
        if (pane) pane.hidden = name !== btn.dataset.vtab;
      });
    });
  });

  // ---- datasets ----
  async function refreshDatasets() {
    const r = await readJson(await fetch("/api/validation/datasets"));
    if (r.status !== 200) return;
    const list = r.body.datasets || [];
    const html = list.map(function (d) {
      return "<div>" + (d.is_demo ? "<strong>DEMO — NOT RESEARCH RESULTS. </strong>" : "") +
        esc(d.id) + " | " + esc(d.name) + " | " + esc(d.detector_id) + " | " + esc(d.status) +
        " | N=" + esc(d.sample_count) + "</div>";
    }).join("") || "<p class='hint'>No datasets yet. Formal datasets start empty.</p>";
    setText("dsList", "");
    $("dsList").innerHTML = html;
    const opts = list.map(function (d) {
      return "<option value='" + esc(d.id) + "'>" + esc(d.id) + " (" + esc(d.status) + ")</option>";
    }).join("");
    ["sDataset", "frDataset", "qDataset"].forEach(function (id) { $(id).innerHTML = opts; });
    const banner = list.some(function (d) { return d.is_demo; });
    $("demoBanner").hidden = !banner;
    if (banner) setText("demoBanner", "DEMO DATA — NOT RESEARCH RESULTS. Demo fixtures validate framework machinery only.");
  }

  $("dsCreate").addEventListener("click", async function () {
    const r = await readJson(await fetch("/api/validation/datasets", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: $("dsName").value, detector_id: $("dsDetector").value, description: $("dsDesc").value })
    }));
    if (r.status !== 201) { setText("dsList", "Error: " + (r.body.error || r.status)); return; }
    await refreshDatasets();
  });

  $("demoEnsure").addEventListener("click", async function () {
    await readJson(await fetch("/api/validation/demo/ensure", { method: "POST" }));
    await refreshDatasets();
  });

  $("sAdd").addEventListener("click", async function () {
    const kws = $("sKws").value.split(";").map(function (k) { return k.trim(); }).filter(Boolean);
    const r = await readJson(await fetch("/api/validation/datasets/" + $("sDataset").value + "/samples", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ raw_text: $("sText").value, topic: $("sTopic").value || null, teacher_keywords: kws.length ? kws : null })
    }));
    setText("dsList", r.status === 201 ? "Sample added: " + r.body.id : "Error: " + (r.body.error || r.status));
    await refreshDatasets();
  });

  $("csvImport").addEventListener("click", async function () {
    const r = await readJson(await fetch("/api/validation/datasets/" + $("sDataset").value + "/import", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ csv_text: $("csvText").value, annotator_id: $("csvAnnotator").value })
    }));
    setText("csvOut", "added=" + (r.body.added || 0) + " errors=" + JSON.stringify(r.body.errors || r.body.error || []));
    await refreshDatasets();
  });

  // ---- annotation (BLINDED: only annotate-view + annotations endpoints) ----
  $("annLoad").addEventListener("click", async function () {
    const id = $("annSample").value.trim();
    const r = await readJson(await fetch("/api/validation/samples/" + encodeURIComponent(id) + "/annotate-view"));
    if (r.status !== 200) { setText("annView", "Error: " + (r.body.error || r.status)); return; }
    const v = r.body;
    annDetector = v.detector_id;
    setText("annProto", v.annotation_instructions + " [" + v.protocol_version + "]");
    setText("annView", "TEXT: " + v.raw_text + (v.topic ? "\nTOPIC: " + v.topic : "") +
      (v.teacher_keywords && v.teacher_keywords.length ? "\nKEYWORDS: " + v.teacher_keywords.join(", ") : "") +
      "\nEXISTING: " + JSON.stringify(v.existing_annotation));
    $("annLabel").innerHTML = v.allowed_labels.map(function (l) {
      return "<option value='" + esc(l) + "'>" + esc(l) + "</option>";
    }).join("");
    $("annForm").hidden = false;
  });

  let annDetector = null;
  $("annSave").addEventListener("click", async function () {
    const id = $("annSample").value.trim();
    const r = await readJson(await fetch("/api/validation/samples/" + encodeURIComponent(id) + "/annotations", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        detector_id: annDetector,
        annotator_id: $("annAnnotator").value, human_label: $("annLabel").value, notes: $("annNotes").value
      })
    }));
    setText("annView", r.status === 201 ? "Saved annotation " + r.body.id : "Error: " + (r.body.error || r.status));
  });

  // ---- quality (human labels only; never predictions) ----
  async function qGet(suffix) {
    const r = await readJson(await fetch("/api/validation/datasets/" + $("qDataset").value + suffix));
    setText("qOut", "");
    setText("qPre", JSON.stringify(r.body, null, 2).slice(0, 4000));
  }
  $("qProgress").addEventListener("click", function () { qGet("/progress"); });
  $("qQuality").addEventListener("click", function () { qGet("/quality"); });
  $("qDupes").addEventListener("click", function () { qGet("/duplicates"); });
  $("qPreview").addEventListener("click", function () { qGet("/freeze-preview"); });

  // ---- freeze & run ----
  async function frPost(suffix, body) {
    const r = await readJson(await fetch("/api/validation/datasets/" + $("frDataset").value + suffix, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {})
    }));
    setText("frOut", JSON.stringify(r.body).slice(0, 2000));
    await refreshDatasets();
    return r;
  }
  $("frToAnnotating").addEventListener("click", function () { frPost("/status", { status: "ANNOTATING" }); });
  $("frFreeze").addEventListener("click", function () { frPost("/freeze", {}); });
  $("frRun").addEventListener("click", async function () {
    const r = await frPost("/runs", {});
    if (r.status === 201 && r.body && r.body.id) {
      await refreshRuns(r.body.id);
      setText("frOut", "Run COMPLETE: " + r.body.id + " N=" + r.body.sample_count + " excluded=" + r.body.excluded_count);
    }
  });

  // ---- results ----
  async function refreshRuns(selectId) {
    const r = await readJson(await fetch("/api/validation/runs"));
    if (r.status !== 200) return;
    $("resRun").innerHTML = (r.body.runs || []).map(function (x) {
      var tag = x.is_demo ? "[DEMO] " : "[FORMAL] ";
      var name = x.dataset_name ? " " + x.dataset_name : "";
      return "<option value='" + esc(x.id) + "'>" + esc(tag + x.id + name + " (" + x.detector_id + "/" + x.status + ")") + "</option>";
    }).join("");
    if (selectId) $("resRun").value = selectId;
  }

  function fmtMetric(m) {
    if (!m || m.status !== "OK" || m.value === null || m.value === undefined) {
      return "N/A (" + ((m && m.reason) || "undefined") + ")";
    }
    return m.value.toFixed(4) + " (" + (m.value * 100).toFixed(2) + "%)";
  }

  $("resLoad").addEventListener("click", async function () {
    const r = await readJson(await fetch("/api/validation/runs/" + $("resRun").value));
    if (r.status !== 200) { setText("resMatrix", "Error: " + (r.body.error || r.status)); return; }
    const d = r.body;
    const lbl = await readJson(await fetch("/api/validation/runs/" + $("resRun").value + "/label"));
    setText("resBadge", (lbl.body && lbl.body.result_label) || "");
    setText("resWarn", (d.warnings || []).join("\n") || "No warnings.");
    const orient = "Rows = system prediction, columns = human ground truth.";
    let html = "<p class='hint'>" + orient + "</p><table border='1'><tr><th></th>";
    const labels = d.cells.length ? Array.from(new Set(d.cells.map(function (c) { return c.human_label; }))) : [];
    html += labels.map(function (l) { return "<th>human " + esc(l) + "</th>"; }).join("") + "</tr>";
    const preds = Array.from(new Set(d.cells.map(function (c) { return c.predicted_label; })));
    preds.forEach(function (p) {
      html += "<tr><th>system " + esc(p) + "</th>";
      labels.forEach(function (h) {
        const cell = d.cells.find(function (c) { return c.predicted_label === p && c.human_label === h; });
        html += "<td>" + (cell ? cell.sample_count : 0) + "</td>";
      });
      html += "</tr>";
    });
    html += "</table>";
    $("resMatrix").innerHTML = html;
    const byName = {};
    (d.metrics || []).forEach(function (m) { byName[m.metric_name] = m; });
    const order = ["N", "TP", "TN", "FP", "FN", "accuracy", "precision", "recall", "specificity", "f1",
      "macro_precision", "macro_recall", "macro_f1", "weighted_precision", "weighted_recall", "weighted_f1"];
    let mh = "<ul>";
    order.forEach(function (k) {
      if (byName[k]) mh += "<li>" + esc(k) + ": " + esc(byName[k].status === "OK" && byName[k].metric_value !== null ? fmtMetric({ status: "OK", value: byName[k].metric_value }) : "N/A (" + (byName[k].reason || "undefined") + ")") + "</li>";
    });
    Object.keys(byName).filter(function (k) { return order.indexOf(k) < 0; }).sort().forEach(function (k) {
      mh += "<li>" + esc(k) + ": " + esc(byName[k].metric_value === null ? "N/A (" + (byName[k].reason || "") + ")" : byName[k].metric_value) + "</li>";
    });
    mh += "</ul>";
    $("resMetrics").innerHTML = mh;
    setText("resBalance", "N=" + d.class_balance.N + " counts=" + JSON.stringify(d.class_balance.counts));
    setText("resRater", (d.inter_rater && d.inter_rater.display) || JSON.stringify(d.inter_rater));
  });

  $("expJson").addEventListener("click", async function () {
    const r = await readJson(await fetch("/api/validation/runs/" + $("resRun").value + "/export.json"));
    setText("expOut", JSON.stringify(r.body).slice(0, 3000));
  });
  $("expCsv").addEventListener("click", async function () {
    const res = await fetch("/api/validation/runs/" + $("resRun").value + "/export.csv");
    setText("expOut", (await res.text()).slice(0, 3000));
  });
  $("expPkg").addEventListener("click", async function () {
    const r = await readJson(await fetch("/api/validation/runs/" + $("resRun").value + "/export-package.json"));
    setText("expOut", JSON.stringify(r.body).slice(0, 3000));
  });
  $("manuscriptBtn").addEventListener("click", async function () {
    const r = await readJson(await fetch("/api/validation/runs/" + $("resRun").value + "/manuscript"));
    setText("expOut", (r.body.result_label + "\n\n" + r.body.text).slice(0, 3000));
  });

  // ---- error analysis (COMPLETE runs only; endpoint enforces) ----
  $("errLoad").addEventListener("click", async function () {
    const mode = $("errFilter").value;
    const q = mode === "all" ? "" : (mode === "correct" ? "?correct=yes" : "?correct=no");
    const r = await readJson(await fetch("/api/validation/runs/" + $("resRun").value + "/errors" + q));
    if (r.status !== 200) { setText("errList", "Error: " + (r.body.error || r.status)); return; }
    $("errList").innerHTML = (r.body.errors || []).map(function (e) {
      return "<div class='card'><p><strong>" + esc(e.sample_id) + "</strong> [" + esc(e.matrix_cell) + "] " +
        (e.correct ? "CORRECT" : "ERROR") + "</p><p>TEXT: " + esc(e.raw_text || "") + "</p>" +
        "<p>HUMAN: " + esc(e.human_label) + " (" + esc(e.label_source) + ") | SYSTEM: " + esc(e.system_prediction) + "</p>" +
        "<p>EVIDENCE: " + esc(JSON.stringify(e.system_evidence).slice(0, 500)) + "</p>" +
        "<p>NOTE: " + esc(e.annotation_notes || "") + "</p></div>";
    }).join("") || "<p class='hint'>No cases.</p>";
  });

  // ---- error categorization (documents only) ----
  async function loadCategories() {
    const r = await readJson(await fetch("/api/validation/error-categories"));
    if (r.status === 200) {
      $("catCategory").innerHTML = (r.body.categories || []).map(function (c) {
        return "<option value='" + esc(c) + "'>" + esc(c) + "</option>";
      }).join("");
    }
  }
  $("catSave").addEventListener("click", async function () {
    const r = await readJson(await fetch("/api/validation/runs/" + $("resRun").value + "/error-notes", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sample_id: $("catSample").value, category: $("catCategory").value, note: $("catNote").value, analyst: $("catAnalyst").value })
    }));
    setText("catOut", r.status === 201 ? "Saved error note #" + r.body.id : "Error: " + (r.body.error || r.status));
  });

  // ---- interaction analytics (counts only — never scores) ----
  // (uses the file-wide esc() above, which also covers quotes)
  function anVal(m) {
    if (!m || m.status !== "OK" || m.value == null) return "n/a";
    return m.value;
  }
  $("anLoad").addEventListener("click", async function () {
    const sid = $("anSession").value.trim();
    if (!sid) { setText("anSummary", "Enter a stage session ID first."); return; }
    const a = await readJson(await fetch("/api/analytics/session/" + encodeURIComponent(sid)));
    if (a.status !== 200) { setText("anSummary", "Error: " + (a.body.error || a.status)); return; }
    const d = a.body, names = { stage1: "Stage 1", stage2: "Stage 2", stage3: "Stage 3", stage4: "Stage 4" };
    let html = "<p>Entry: " + esc(d.entry) + " · total revisions " + esc(d.total_revisions) + "</p>";
    html += "<table><thead><tr><th>Stage</th><th>Active ms</th><th>Revisions</th><th>Server analyses</th>" +
      "<th>Feedback items</th><th>Ready at rev</th><th>Status</th></tr></thead><tbody>";
    ["stage1", "stage2", "stage3", "stage4"].forEach(function (st) {
      const p = (d.per_stage || {})[st] || {};
      const t = (p.active_time || {}).active_ms || {};
      const fb = (p.feedback_items_server || {});
      const ready = (p.analyses_before_ready || {});
      const prog = p.stage_progress || {};
      html += "<tr><td>" + names[st] + "</td><td>" + esc(t.value) + "</td><td>" +
        esc(p.revision_count) + "</td><td>" + esc(p.server_analyses) + "</td><td>" +
        esc(fb.value) + "</td><td>" + esc(ready.value) + "</td><td>" +
        esc(prog.status) + "</td></tr>";
    });
    html += "</tbody></table>";
    const groups = d.indicator_groups || {};
    html += "<h3>Rule-based indicator groups (occurrences, not scores)</h3>";
    ["thesis_clarity_indicators", "structural_coherence_indicators",
     "grammar_style_indicators", "other_indicators"].forEach(function (g) {
      const rows = (groups[g] || []).map(function (r) {
        return "<li><code>" + esc(r.rule_id) + "</code> × " + esc(r.occurrences) +
          " (" + esc((r.stages || []).join(", ")) + ")</li>";
      }).join("") || "<li>none recorded</li>";
      html += "<h4>" + esc(g) + "</h4><ul>" + rows + "</ul>";
    });
    $("anSummary").innerHTML = html;
    const e = await readJson(await fetch(
      "/api/analytics/session/" + encodeURIComponent(sid) + "/events"));
    if (e.status !== 200) { setText("anEvents", "Error: " + (e.body.error || e.status)); return; }
    const rows = (e.body.events || []).map(function (ev) {
      return "<tr><td>" + esc(ev.server_timestamp) + "</td><td>" + esc(ev.stage) +
        "</td><td>" + esc(ev.event_type) + "</td><td>" + esc(ev.analysis_id) +
        "</td><td>" + esc(ev.revision_number) + "</td><td>" + esc(ev.rule_id) +
        "</td><td>" + esc(ev.provenance) + "</td></tr>";
    }).join("");
    $("anEvents").innerHTML = "<table><thead><tr><th>Server time</th><th>Stage</th>" +
      "<th>Event</th><th>Analysis</th><th>Rev</th><th>Rule</th><th>Provenance</th></tr></thead>" +
      "<tbody>" + rows + "</tbody></table><p>" + e.body.count + " event(s), oldest first.</p>";
  });

  // ---- provenance ----
  $("provLoad").addEventListener("click", async function () {
    const r = await readJson(await fetch("/api/validation/freeze-record"));
    setText("provOut", JSON.stringify(r.body, null, 2));
  });
  loadCategories();

  refreshDatasets();
  refreshRuns();
})();
