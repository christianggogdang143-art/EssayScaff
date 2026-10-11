/* EssayScaff Writing Lab text highlighting (presentation only).
 *
 * Renders the CURRENT analysis's feedback spans as color-coded <mark>
 * elements in a layer behind the editor, and links marks <-> feedback
 * cards with two-way scroll + flash. All spans come from the live
 * response (integer start/end offsets into the analyzed text); items
 * without usable offsets are skipped, never invented. Typing clears
 * highlights immediately so stale offsets can never sit on new text.
 * No fetch, no revision, no analytics, no DB write here.
 *
 * Technique: transparent-text textarea over a identically-metrics
 * backdrop div (same font/padding/line-height/wrapping). Backdrop has
 * pointer-events:none except on marks, so the editor keeps focus.
 */
(function () {
  "use strict";

  function $(id) { return document.getElementById(id); }
  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  /* Display-only color mapping (severity/type -> class). Documented in the
   * visible legend; it never alters detection or priority. */
  function colorClass(item) {
    var src = String(((item && item.source) || "") + " " + ((item && item.category) || ""));
    if (/languagetool|grammar|mechanic/i.test(src)) return "hl-mech";
    var sev = String((item && item.severity) || "").toLowerCase();
    if (sev === "warning" || sev === "error" || sev === "critical") return "hl-warn";
    return "hl-info";
  }
  function fbId(item) { return esc((item && item.feedback_id) || ""); }

  function isInt(n) { return typeof n === "number" && isFinite(n) && Math.floor(n) === n; }

  /* Logical spans for one text: 1:1 with usable feedback items, sorted.
   * Pure function (no DOM) so tests can verify offset fidelity exactly.
   * Backend offsets count Unicode code points (Python str indices) while
   * JS strings index UTF-16 code units, so spans are converted through a
   * code-point map: astral-plane characters (emoji) can never drift the
   * highlights that follow them. Returned indices are UTF-16 (for slice). */
  function spansFor(text, items) {
    text = String(text == null ? "" : text);
    var chars = Array.from(text);
    var cuAt = [0];
    for (var i = 0; i < chars.length; i++) cuAt.push(cuAt[i] + chars[i].length);
    var n = chars.length, out = [];
    (items || []).forEach(function (it) {
      if (!it) return;
      var s = it.start, e = it.end;
      if (!isInt(s) || !isInt(e) || s < 0 || e <= s || e > n) return;
      out.push({ fb: (it.feedback_id == null ? "" : String(it.feedback_id)),
        start: cuAt[s], end: cuAt[e], cls: colorClass(it) });
    });
    out.sort(function (a, b) {
      if (a.start !== b.start) return a.start - b.start;
      return b.end - a.end;
    });
    return out;
  }

  /* Render text with marks. Partially overlapping spans are split at every
   * boundary so each segment nests the marks covering it (no invented or
   * dropped characters — output text always equals input text). */
  function spansToHtml(text, spans) {
    text = String(text == null ? "" : text);
    if (!spans.length) return esc(text);
    var bounds = [0, text.length];
    spans.forEach(function (s) { bounds.push(s.start, s.end); });
    bounds = bounds.filter(function (b, i, a) {
      return b >= 0 && b <= text.length && a.indexOf(b) === i;
    }).sort(function (a, b) { return a - b; });
    var html = "";
    for (var i = 0; i + 1 < bounds.length; i++) {
      var a = bounds[i], b = bounds[i + 1];
      if (b <= a) continue;
      var seg = text.slice(a, b);
      var covering = spans.filter(function (s) { return s.start <= a && s.end >= b; });
      if (!covering.length) { html += esc(seg); continue; }
      covering.forEach(function (s) {
        html += '<mark class="' + s.cls + '" data-fb="' + esc(s.fb) + '">';
      });
      html += esc(seg);
      for (var k = covering.length - 1; k >= 0; k--) html += "</mark>";
    }
    return html;
  }

  function editor() { return $("editor"); }
  function backdrop() { return $("editorBackdrop"); }

  function syncScroll() {
    var ed = editor(), bd = backdrop();
    if (!ed || !bd) return;
    try { bd.scrollTop = ed.scrollTop; bd.scrollLeft = ed.scrollLeft || 0; } catch (e) { /* never break typing */ }
  }

  /* Mirror the current editor text with NO marks (used on every keystroke). */
  function syncText() {
    var ed = editor(), bd = backdrop();
    if (!ed || !bd) return;
    bd.innerHTML = esc(ed.value);
    syncScroll();
  }

  function clear() {
    var bd = backdrop();
    if (!bd) return;
    var ed = editor();
    bd.innerHTML = esc(ed ? ed.value : "");
  }

  /* Render marks for a finished analysis. Only the PRIMARY item is marked,
   * so every highlight always has its visible feedback card (same color,
   * same explanation) — no orphan spans. Refuses when the editor text no
   * longer equals the analyzed text (stale offsets must never display).
   * primary === undefined keeps the legacy all-usable behavior (tests). */
  function renderFor(analyzedText, data, primary) {
    var ed = editor(), bd = backdrop();
    if (!ed || !bd) return false;
    if (ed.value !== String(analyzedText == null ? "" : analyzedText)) { clear(); return false; }
    var items = (primary === undefined)
      ? ((data && data.feedback) || [])
      : (primary ? [primary] : []);
    var spans = spansFor(ed.value, items);
    bd.innerHTML = spansToHtml(ed.value, spans);
    syncScroll();
    return true;
  }

  function flash(el) {
    if (!el) return;
    try {
      el.classList.add("hl-flash");
      setTimeout(function () {
        try { el.classList.remove("hl-flash"); } catch (e) { /* gone */ }
      }, 1200);
    } catch (e) { /* never break the UI */ }
  }
  function safeScrollIntoView(el) {
    if (!el || typeof el.scrollIntoView !== "function") return;
    try { el.scrollIntoView({ block: "nearest" }); } catch (e) { /* jsdom / old browsers */ }
  }

  function cardFor(fb) {
    if (fb == null || fb === "") return null;
    return document.querySelector('#feedback .fb[data-fb="' + String(fb).replace(/"/g, "") + '"]');
  }
  function marksFor(fb) {
    var bd = backdrop();
    if (!bd || fb == null || fb === "") return [];
    return Array.prototype.slice.call(
      bd.querySelectorAll('mark[data-fb="' + String(fb).replace(/"/g, "") + '"]'));
  }

  function scrollEditorTo(mark) {
    var ed = editor();
    if (!ed || !mark) return;
    try {
      var top = mark.offsetTop - ed.clientHeight / 2;
      ed.scrollTop = top < 0 ? 0 : top;
      syncScroll();
    } catch (e) { /* never break the UI */ }
  }

  /* Hit-test through the overlay: briefly remove the textarea from
   * hit-testing (same task, no paint in between), then restore. */
  function markAtPoint(x, y) {
    var ed = editor();
    if (!ed || typeof document.elementFromPoint !== "function") return null;
    var prev = ed.style.pointerEvents;
    var el = null;
    try {
      ed.style.pointerEvents = "none";
      el = document.elementFromPoint(x, y);
    } catch (e) { el = null; }
    try { ed.style.pointerEvents = prev; } catch (e2) { /* restore */ }
    if (el && el.closest) return el.closest("mark[data-fb]");
    return null;
  }

  function handleMarkClick(m) {
    if (!m) return;
    var card = cardFor(m.getAttribute("data-fb"));
    if (card) { safeScrollIntoView(card); flash(card); }
    flash(m);
  }
  function bind() {
    var ed = editor(), bd = backdrop(), feed = $("feedback");
    if (ed) {
      ed.addEventListener("input", function () { syncText(); });
      ed.addEventListener("scroll", syncScroll);
      // The transparent textarea sits above the backdrop, so real clicks
      // hit-test to the textarea, never to the marks beneath. Forward a
      // plain click (not a text-selection drag) to the mark under the point.
      ed.addEventListener("click", function (ev) {
        try {
          var sel = window.getSelection ? String(window.getSelection()) : "";
          if (sel) return;
        } catch (e) { /* treat as click */ }
        var m = markAtPoint(ev.clientX, ev.clientY);
        if (m) handleMarkClick(m);
      });
    }
    var stageSel = $("stage");
    if (stageSel) stageSel.addEventListener("change", function () { clear(); });
    if (bd) {
      bd.addEventListener("click", function (ev) {
        var m = ev.target && ev.target.closest ? ev.target.closest("mark[data-fb]") : null;
        handleMarkClick(m);
      });
    }
    if (feed) {
      feed.addEventListener("click", function (ev) {
        var c = ev.target && ev.target.closest ? ev.target.closest(".fb[data-fb]") : null;
        if (!c) return;
        var marks = marksFor(c.getAttribute("data-fb"));
        if (marks.length) { scrollEditorTo(marks[0]); marks.forEach(flash); }
        flash(c);
      });
    }
    window.addEventListener("resize", syncScroll);
    syncText();
  }

  bind();

  window.EssayScaffHighlight = {
    renderFor: renderFor,
    clear: clear,
    syncText: syncText,
    spansFor: spansFor,
    spansToHtml: spansToHtml,
    colorClass: colorClass,
    marksFor: marksFor,
    cardFor: cardFor,
  };
})();
