/* HTML-отчёт v2 (№14): фильтры, подсветка, вкладки, тема, печать. Без библиотек. */
(function () {
  "use strict";
  var $ = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };
  var root = document.documentElement;
  var doc = $("#doc");
  var cardsBox = $("#cards");
  var cards = $$(".card", cardsBox || document);

  function store(k, v) {
    try { if (v === undefined) return localStorage.getItem(k); localStorage.setItem(k, v); } catch (_) { return null; }
    return null;
  }

  function toast(msg) {
    var t = document.createElement("div");
    t.className = "toast"; t.textContent = msg; document.body.appendChild(t);
    setTimeout(function () { t.remove(); }, 1800);
  }

  /* ── тема ── */
  function currentTheme() {
    if (root.dataset.theme) return root.dataset.theme;
    return window.matchMedia && matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }
  $("#theme").addEventListener("click", function () {
    var next = currentTheme() === "dark" ? "light" : "dark";
    root.dataset.theme = next; store("bccr-theme", next);
  });

  /* ── вкладки ── */
  var tabs = $$(".tab");
  function showTab(name, focus) {
    tabs.forEach(function (t) {
      var on = t.dataset.tab === name;
      t.setAttribute("aria-selected", on ? "true" : "false");
      t.tabIndex = on ? 0 : -1;
      $("#p-" + t.dataset.tab).hidden = !on;
      if (on && focus) t.focus();
    });
  }
  tabs.forEach(function (t, i) {
    t.addEventListener("click", function () {
      showTab(t.dataset.tab);
      history.replaceState(null, "", "#" + t.dataset.tab);
      window.scrollTo({ top: 0 });  /* панель разделов внизу (№41): новый раздел — с начала листа */
    });
    t.addEventListener("keydown", function (ev) {
      var d = ev.key === "ArrowRight" ? 1 : ev.key === "ArrowLeft" ? -1 : 0;
      if (d) { ev.preventDefault(); showTab(tabs[(i + d + tabs.length) % tabs.length].dataset.tab, true); }
    });
  });

  /* ── документ: прокрутка и подсветка ── */
  function lineEl(n) { return doc ? doc.querySelector('.ln[data-n="' + n + '"]') : null; }
  function scrollDocTo(n, n2) {
    if (!doc) return;
    var el = lineEl(n);
    if (!el) return;
    if (doc.classList.contains("onlyhl") && !el.classList.contains("hl")) { $("#onlyhl").checked = false; doc.classList.remove("onlyhl"); }
    if (doc.scrollHeight > doc.clientHeight + 4) {
      doc.scrollTo({ top: Math.max(0, el.offsetTop - doc.clientHeight / 3), behavior: "smooth" });
    } else {  /* лист на столе (№41): прокручивается страница, строка встаёт на треть экрана */
      window.scrollTo({ top: Math.max(0, el.getBoundingClientRect().top + window.scrollY - window.innerHeight / 3), behavior: "smooth" });
    }
    var last = parseInt(n2 || n, 10);
    for (var k = parseInt(n, 10); k <= last; k++) {
      var x = lineEl(k);
      if (x) { x.classList.remove("flash"); void x.offsetWidth; x.classList.add("flash"); }
    }
  }
  function clearSel() {
    $$(".ln.sel, .ln.rqsel, mark.q.on").forEach(function (x) { x.classList.remove("sel", "rqsel", "on"); });
    $$(".card.active").forEach(function (x) { x.classList.remove("active"); });
    if (doc) doc.classList.remove("focus");
  }

  function selectFinding(id, opts) {
    opts = opts || {};
    var card = document.getElementById(id);
    if (!card || !card.classList.contains("card")) return;
    showTab("findings");
    clearSel();
    card.classList.add("active");
    if (doc) doc.classList.add("focus");
    if (card.hidden) { resetFilters(); }
    var lines = (card.dataset.lines || "").split(" ").filter(Boolean);
    if (doc) {
      $$('.ln[data-f]', doc).forEach(function (x) {
        if ((" " + x.dataset.f + " ").indexOf(" " + id + " ") >= 0) x.classList.add("sel");
      });
      $$("mark.q", doc).forEach(function (m) {
        if ((" " + m.dataset.f + " ").indexOf(" " + id + " ") >= 0) m.classList.add("on");
      });
    }
    if (lines.length && !opts.noDocScroll) scrollDocTo(lines[0]);
    if (opts.scrollCard) card.scrollIntoView({ behavior: "smooth", block: "start" });
    history.replaceState(null, "", "#" + id);
  }

  document.addEventListener("click", function (ev) {
    var a = ev.target.closest("[data-goto]");
    if (a) { ev.preventDefault(); selectFinding(a.dataset.goto, { scrollCard: true }); return; }
    var evb = ev.target.closest(".ev");
    if (evb) {
      var c = evb.closest(".card");
      if (c) selectFinding(c.id, { noDocScroll: true });
      scrollDocTo(evb.dataset.ls, evb.dataset.le);
      return;
    }
    var r = ev.target.closest("[data-req]");
    if (r) {
      ev.preventDefault(); showTab("findings"); clearSel();
      for (var k = +r.dataset.ls; k <= +(r.dataset.le || r.dataset.ls); k++) { var x = lineEl(k); if (x) x.classList.add("rqsel"); }
      scrollDocTo(r.dataset.ls, r.dataset.le);
      return;
    }
    var l = ev.target.closest("[data-line]");
    if (l && !l.closest(".card")) {
      ev.preventDefault(); showTab("findings"); clearSel();
      for (var m = +l.dataset.line; m <= +(l.dataset.le || l.dataset.line); m++) { var y = lineEl(m); if (y) y.classList.add("rqsel"); }
      scrollDocTo(l.dataset.line, l.dataset.le);
      return;
    }
    var cp = ev.target.closest("[data-copy]");
    if (cp) {
      var txt = cp.closest(".dl").querySelector(".dd").textContent;
      try { navigator.clipboard.writeText(txt).then(function () { toast("Формулировка скопирована"); }); } catch (_) { toast("Не удалось скопировать"); }
      return;
    }
    var card = ev.target.closest(".card");
    if (card && !ev.target.closest("a, button, summary, input, select, textarea") && !String(window.getSelection())) {
      selectFinding(card.id);
      return;
    }
    var ln = ev.target.closest(".ln.hl");
    if (ln && !ev.target.closest("a")) {
      var ids = ln.dataset.f.split(" ");
      var cur = $(".card.active");
      var i = cur ? ids.indexOf(cur.id) : -1;
      selectFinding(ids[(i + 1) % ids.length], { scrollCard: true, noDocScroll: true });
    }
  });

  if (doc) {
    $("#onlyhl").addEventListener("change", function (ev) { doc.classList.toggle("onlyhl", ev.target.checked); });
    $("#showreq").addEventListener("change", function (ev) { doc.classList.toggle("showreq", ev.target.checked); });
    $$(".ln.ex", doc).forEach(function (x) { x.title = "Не требование — " + x.dataset.ex; });
  }

  /* ── мини-карта: где в документе замечания ── */
  var mm = $("#minimap");
  function drawMap() {
    if (!doc || !mm || !doc.scrollHeight) return;
    mm.innerHTML = "";
    var H = doc.scrollHeight, h = mm.clientHeight;
    $$(".ln.hl", doc).forEach(function (x) {
      if (!x.offsetHeight) return;
      var t = document.createElement("i");
      t.className = (x.className.match(/sev-\w+/) || [""])[0];
      t.style.top = (x.offsetTop / H * h) + "px";
      t.style.height = Math.max(3, x.offsetHeight / H * h) + "px";
      t.title = "Строка " + x.dataset.n + ": " + x.dataset.f;
      t.addEventListener("click", function () { selectFinding(x.dataset.f.split(" ")[0], { scrollCard: true }); });
      mm.appendChild(t);
    });
    var vw = document.createElement("div");
    vw.className = "vw";
    mm.appendChild(vw);
    var upd = function () {
      vw.style.top = (doc.scrollTop / H * h) + "px";
      vw.style.height = Math.max(8, doc.clientHeight / H * h) + "px";
    };
    upd();
    doc.onscroll = upd;
  }
  if (doc && mm) {
    setTimeout(drawMap, 60);
    addEventListener("resize", function () { clearTimeout(drawMap.t); drawMap.t = setTimeout(drawMap, 150); });
    ["onlyhl", "showreq"].forEach(function (k) { $("#" + k).addEventListener("change", function () { setTimeout(drawMap, 30); }); });
  }

  /* ── фильтры ── */
  var chips = $$(".sevchip");
  var q = $("#q"), fkind = $("#fkind"), fsrc = $("#fsrc"), fsort = $("#fsort"), fcount = $("#fcount");
  function applyFilters() {
    if (!cardsBox) return;
    var sev = {};
    chips.forEach(function (c) { sev[c.dataset.sev] = c.getAttribute("aria-pressed") === "true"; });
    var words = (q.value || "").toLowerCase().trim().split(/\s+/).filter(Boolean);
    var shown = 0;
    cards.forEach(function (c) {
      var ok = sev[c.dataset.sev] !== false;
      if (ok && fkind.value) ok = c.dataset.kind === fkind.value;
      if (ok && fsrc.value) ok = (" " + c.dataset.src + " ").indexOf(" " + fsrc.value + " ") >= 0;
      if (ok && words.length) {
        var s = c.dataset.search;
        ok = words.every(function (w) { return s.indexOf(w) >= 0; });
      }
      c.hidden = !ok;
      if (ok) shown++;
    });
    fcount.textContent = "Показано " + shown + " из " + cards.length;
    var empty = $(".empty[hidden], .empty", cardsBox);
    if (empty && cards.length) empty.hidden = shown !== 0;
  }
  function sortCards() {
    var key = fsort.value;
    var sorted = cards.slice().sort(function (a, b) {
      var A = a.dataset, B = b.dataset;
      if (key === "line") return (+A.line - +B.line) || (+B.rank - +A.rank);
      if (key === "sev") return (+B.rank - +A.rank) || (+A.line - +B.line);
      var pa = +A.prio || 999, pb = +B.prio || 999;
      return (pa - pb) || (+B.rank - +A.rank) || (+A.line - +B.line);
    });
    var empty = $(".empty", cardsBox);
    sorted.forEach(function (c) { cardsBox.insertBefore(c, empty); });
  }
  function resetFilters() {
    chips.forEach(function (c) { c.setAttribute("aria-pressed", "true"); });
    q.value = ""; fkind.value = ""; fsrc.value = "";
    applyFilters();
  }
  if (cardsBox) {
    chips.forEach(function (c) {
      c.addEventListener("click", function () {
        c.setAttribute("aria-pressed", c.getAttribute("aria-pressed") === "true" ? "false" : "true");
        applyFilters();
      });
    });
    q.addEventListener("input", applyFilters);
    fkind.addEventListener("change", applyFilters);
    fsrc.addEventListener("change", applyFilters);
    fsort.addEventListener("change", sortCards);
    $$("[data-reset]").forEach(function (b) { b.addEventListener("click", resetFilters); });
    $$("[data-sevonly]").forEach(function (b) {
      b.addEventListener("click", function () {
        var s = b.dataset.sevonly;
        chips.forEach(function (c) { c.setAttribute("aria-pressed", c.dataset.sev === s ? "true" : "false"); });
        showTab("findings"); applyFilters();
        var t = $(".tabs"); window.scrollTo({ top: t.getBoundingClientRect().top + window.scrollY - 60, behavior: "smooth" });
      });
    });
    var allOpen = false;
    $("#toggleall").addEventListener("click", function (ev) {
      allOpen = !allOpen;
      $$(".card .more").forEach(function (d) { d.open = allOpen; });
      ev.target.textContent = allOpen ? "Свернуть все" : "Развернуть все";
    });
    applyFilters();
  }

  /* ── клавиатура: ↑/↓ или j/k по карточкам ── */
  document.addEventListener("keydown", function (ev) {
    if (ev.target.closest("input, textarea, select") || ev.ctrlKey || ev.metaKey || ev.altKey) return;
    if (ev.key === "Escape") { clearSel(); history.replaceState(null, "", location.pathname); return; }
    var d = (ev.key === "ArrowDown" || ev.key === "j") ? 1 : (ev.key === "ArrowUp" || ev.key === "k") ? -1 : 0;
    if (!d || $("#p-findings").hidden || ev.target.closest(".doc")) return;
    var vis = $$(".card", cardsBox).filter(function (c) { return !c.hidden; });
    if (!vis.length) return;
    ev.preventDefault();
    var cur = $(".card.active");
    var i = cur ? vis.indexOf(cur) : -1;
    var next = vis[Math.min(vis.length - 1, Math.max(0, i + d))];
    selectFinding(next.id, { scrollCard: true });
  });

  /* ── печать и скачивание ── */
  var opened = [];
  window.addEventListener("beforeprint", function () {
    opened = $$("details").filter(function (d) { return !d.open; });
    opened.forEach(function (d) { d.open = true; });
  });
  window.addEventListener("afterprint", function () { opened.forEach(function (d) { d.open = false; }); opened = []; });
  $("#print").addEventListener("click", function () { window.print(); });

  function download(name, text, type) {
    var blob = new Blob([text], { type: type });
    var a = document.createElement("a");
    a.href = URL.createObjectURL(blob); a.download = name;
    document.body.appendChild(a); a.click();
    setTimeout(function () { URL.revokeObjectURL(a.href); a.remove(); }, 500);
  }
  var base = document.body.dataset.file || "report";
  $("#dljson").addEventListener("click", function () {
    download(base + ".report.json", $("#report-data").textContent, "application/json");
  });

  var dla = $("#dlanswers");
  if (dla) {
    dla.addEventListener("click", function () {
      var data = JSON.parse($("#report-data").textContent);
      var LET = "ABCDEFGH";
      var md = ["# Ответы владельца на вопросы ревью: «" + ((data.document || {}).title || "") + "»", "",
        "> Формат строки: `Q-01: B` (буква варианта) или `Q-01 [тема]: свой ответ`.",
        "> Передайте файл агенту: python -m bcc_review ДОКУМЕНТ ОТЧЁТ.md --answers этот_файл.md", ""];
      var n = 0;
      (data.questions || []).forEach(function (qq) {
        var pick = $('input[name="' + qq.id + '"]:checked');
        var own = $('textarea[data-own="' + qq.id + '"]');
        var text = own && own.value.trim() ? own.value.trim().replace(/\s*\n\s*/g, " ") : "";
        var val = text || (pick ? (LET.charAt(+pick.value) || String(+pick.value + 1)) : "");
        if (!val) return;
        n++;
        md.push(qq.id + (qq.topic ? " [" + qq.topic + "]" : "") + ": " + val);
      });
      if (!n) { toast("Отметьте хотя бы один ответ"); return; }
      download(base + ".answers.md", md.join("\n") + "\n", "text/markdown");
      toast("Ответов в файле: " + n);
    });
  }

  /* ── адрес страницы: #D-02 или #questions ── */
  function fromHash() {
    var h = decodeURIComponent(location.hash.slice(1));
    if (!h) return;
    if (document.getElementById("p-" + h)) { showTab(h); return; }
    var el = document.getElementById(h);
    if (el && el.classList.contains("card")) selectFinding(h, { scrollCard: true });
    else if (/^L\d+$/.test(h)) { showTab("findings"); scrollDocTo(h.slice(1)); }
  }
  window.addEventListener("hashchange", fromHash);
  fromHash();
})();

/* ── лист с правкой (№41): строка вердикта, заметки на полях с линиями к строкам, карта листа,
 *    исправленная редакция «как у юриста», пометки рисуются по порядку чтения. Содержание отчёта не меняется. ── */
(function () {
  "use strict";
  var $ = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };
  var root = document.documentElement;
  var NS = "http://www.w3.org/2000/svg";
  var data = {};
  try { data = JSON.parse(($("#report-data") || {}).textContent || "{}"); } catch (_) { data = {}; }
  var split = $(".split"), pane = $(".docpane"), doc = $("#doc"), box = $("#cards"), flist = $(".flist");
  var cards = box ? $$(".card", box) : [];
  var LBL = { no: "нельзя", conditional: "с условиями", yes: "можно", undetermined: "не определён" };
  function plural(n, a, b, c) { var m = Math.abs(n) % 100, k = m % 10; return m > 10 && m < 20 ? c : k === 1 ? a : k > 1 && k < 5 ? b : c; }
  function esc(t) { var d = document.createElement("div"); d.textContent = t == null ? "" : String(t); return d.innerHTML; }
  function el(tag, cls, html) { var x = document.createElement(tag); if (cls) x.className = cls; if (html != null) x.innerHTML = html; return x; }
  function resolved(f) { return f.status === "resolved" || f.status_after_answers === "resolved"; }

  /* вердикт — спокойная строка в шапке листа: те же вердикт и блокеры, что в Markdown и в итоге терминала */
  function verdictLine() {
    var head = pane && $(".dochead", pane);
    if (!head || $(".verdict-line", head)) return;
    var run = data.run || {}, v = data.verdict || {}, s = data.summary || {};
    var offline = run.provider === "offline";
    var bl = (data.findings || []).filter(function (f) {
      return !resolved(f) && ["development", "testing", "both"].indexOf(f.blocks) >= 0 &&
        (f.severity === "critical" || (offline && f.rule_conflict));
    });
    var failed = run.status === "failed";
    var dev = failed ? "" : (v.development || ""), test = failed ? "" : (v.testing || "");
    var ok = 0, total = 0;
    if (typeof s.quotes_verified === "number" && typeof s.quotes_total === "number" && s.quotes_verified % 1 === 0) {
      ok = s.quotes_verified; total = s.quotes_total;
    } else {
      (data.findings || []).forEach(function (f) {
        (f.evidence || []).forEach(function (e) { total++; if (["exact", "normalized", "fuzzy"].indexOf(e.verified) >= 0) ok++; });
      });
    }
    var n = bl.length, cls = { no: "v-no", yes: "v-yes" }[dev] || "";
    var parts = ['Разработка: <b class="' + cls + '">' + esc(LBL[dev] || "вердикт не вынесен") + "</b>"];
    if (test && test !== dev) parts.push("тестирование: " + esc(LBL[test] || test));
    parts.push(n ? n + " " + plural(n, "блокер", "блокера", "блокеров") : "блокеров нет");
    if (total) parts.push("цитат сверено " + ok + " из " + total);
    var line = el("div", "verdict-line", parts.map(function (x) { return '<span class="vp">' + x + "</span>"; }).join(' <span class="sep">·</span> '));
    line.setAttribute("role", "status");
    head.appendChild(line);
  }

  /* итог агента — на второй бумаге над заметками */
  function resolution() {
    var ht = $(".hero-text");
    if (!ht || !flist || $(".resolution", flist)) return;
    var r = el("div", "resolution", '<div class="rl">Итог агента</div>');
    r.appendChild(ht);
    flist.insertBefore(r, flist.firstChild);
  }

  /* заметки на полях: каждая — напротив своей строки, тонкая линия к месту; на узком экране — под строкой */
  var wide = window.matchMedia ? window.matchMedia("(min-width: 1001px)") : { matches: true };
  var svg = null, raf = 0, inlined = false;
  function lineOf(c) { return doc ? doc.querySelector('.ln[data-n="' + (c.dataset.line || (c.dataset.lines || "").split(" ")[0]) + '"]') : null; }
  function setInline(on) {
    if (on === inlined || !doc || !box) return;
    inlined = on;
    if (on) {
      var last = {};
      cards.forEach(function (c) {
        var ln = lineOf(c);
        if (!ln) return;
        var after = last[ln.dataset.n] || ln;
        after.parentNode.insertBefore(c, after.nextSibling);
        last[ln.dataset.n] = c;
        c.style.top = "";
      });
    } else {
      var empty = $(".empty", box);
      cards.forEach(function (c) { box.insertBefore(c, empty); });
    }
  }
  function layout() {
    raf = 0;
    if (!split || !doc || !box || !pane || !pane.offsetParent) return;
    if (!wide.matches) { setInline(true); box.style.height = ""; if (svg) svg.innerHTML = ""; return; }
    setInline(false);
    var base = box.getBoundingClientRect().top;
    var items = cards.filter(function (c) { return !c.hidden; }).map(function (c) {
      var ln = lineOf(c);
      return { c: c, ln: ln, y: ln ? ln.getBoundingClientRect().top - base : 0 };
    }).sort(function (a, b) { return a.y - b.y || (+b.c.dataset.rank - +a.c.dataset.rank); });
    var cur = 0, gap = 6;
    var seq = function (list) { list.forEach(function (it) { it.top = Math.max(it.y - 3, cur); cur = it.top + it.c.offsetHeight + gap; }); };
    var ai = -1;
    items.forEach(function (it, i) { if (it.c.classList.contains("active")) ai = i; });
    if (ai < 0) {
      seq(items);
    } else {  /* раскрытая заметка стоит напротив своей строки, соседние расступаются вверх и вниз */
      var A = items[ai], lim;
      A.top = Math.max(0, A.y - 3);
      lim = A.top - gap;
      for (var i = ai - 1; i >= 0; i--) { items[i].top = Math.min(items[i].y - 3, lim - items[i].c.offsetHeight); lim = items[i].top - gap; }
      if (ai > 0 && items[0].top < 0) { cur = 0; seq(items.slice(0, ai)); A.top = Math.max(A.top, cur); }
      cur = A.top + A.c.offsetHeight + gap;
      seq(items.slice(ai + 1));
    }
    items.forEach(function (it) { it.c.style.top = Math.round(it.top) + "px"; });
    box.style.height = Math.max(cur, 0) + "px";
    links(items);
  }
  function links(items) {
    if (!svg) { svg = document.createElementNS(NS, "svg"); svg.setAttribute("class", "links"); svg.setAttribute("aria-hidden", "true"); split.appendChild(svg); }
    var sr = split.getBoundingClientRect(), pr = pane.getBoundingClientRect();
    svg.setAttribute("width", Math.round(sr.width));
    svg.setAttribute("height", Math.round(Math.max(split.scrollHeight, sr.height)));
    var x1 = pr.right - sr.left, out = [], any = false;
    items.forEach(function (it) {
      if (!it.ln) return;
      var lr = it.ln.getBoundingClientRect(), cr = it.c.getBoundingClientRect();
      var y1 = lr.top - sr.top + Math.min(13, lr.height / 2), x2 = cr.left - sr.left + 2, y2 = cr.top - sr.top + 15;
      var on = it.c.classList.contains("active");
      any = any || on;
      var k = Math.max(16, (x2 - x1) / 2);
      out.push('<path class="' + (on ? "on " : "") + "sev-" + it.c.dataset.sev + '" d="M' + x1.toFixed(1) + " " + y1.toFixed(1) +
        " C" + (x1 + k).toFixed(1) + " " + y1.toFixed(1) + " " + (x2 - k).toFixed(1) + " " + y2.toFixed(1) + " " + x2.toFixed(1) + " " + y2.toFixed(1) + '"/>');
    });
    svg.innerHTML = out.join("");
    svg.setAttribute("class", "links" + (any ? " focus" : ""));
  }
  function relayout() { if (!raf) raf = requestAnimationFrame(layout); }

  /* карта листа: рамка видимой части едет вместе со страницей */
  function mapView() {
    var mm = $("#minimap"), vw = mm && $(".vw", mm);
    if (!vw || !doc || !mm.clientHeight) return;
    var r = doc.getBoundingClientRect(), H = r.height || 1, h = mm.clientHeight;
    vw.style.top = (Math.min(H, Math.max(0, -r.top + 60)) / H * h) + "px";
    vw.style.height = Math.max(10, Math.min(H, window.innerHeight) / H * h) + "px";
  }

  /* исправленная редакция: тот же лист, вычеркнутое красным, вставленное зелёным */
  function redline() {
    var p = $("#p-rewrites"), rws = data.rewrites || [];
    if (!p || !rws.length || !doc || $(".redline", p)) return;
    var edits = [];
    rws.forEach(function (r) {
      if (r.edits && r.edits.length) {
        r.edits.forEach(function (e) { edits.push({ line: +e.line, before: e.was || "", after: e.became || "", act: e.action || "" }); });
      } else if (r.after || r.before) {
        edits.push({ line: +(r.line_start || r.line || 0), before: r.before || "", after: r.after || "", act: r.action || "" });
      }
    });
    if (!edits.length) return;
    var clone = el("div", "doc");
    $$(".ln, .pgbreak", doc).forEach(function (ln) {
      var x = ln.cloneNode(true);
      x.removeAttribute("id"); x.removeAttribute("data-f");
      x.className = ln.className.split(" ").filter(function (c) { return c === "ln" || c === "h" || c === "blank" || c === "pgbreak"; }).join(" ");
      $$(".fms, .rtag, .card", x).forEach(function (m) { m.remove(); });
      $$("mark", x).forEach(function (m) { m.replaceWith(document.createTextNode(m.textContent)); });
      clone.appendChild(x);
    });
    var byLine = {};
    edits.forEach(function (e) { (byLine[e.line] = byLine[e.line] || []).push(e); });
    Object.keys(byLine).forEach(function (n) {
      var ln = clone.querySelector('.ln[data-n="' + n + '"]');
      if (!ln) return;
      var tx = $(".tx", ln), text = tx.textContent.replace(/​/g, ""), cuts = [], extra = [];
      byLine[n].forEach(function (e) {
        var at = e.before ? text.indexOf(e.before) : -1;
        var free = at >= 0 && cuts.every(function (c) { return at >= c.b || at + e.before.length <= c.a; });
        if (free) cuts.push({ a: at, b: at + e.before.length, e: e }); else extra.push(e);
      });
      cuts.sort(function (x, y) { return x.a - y.a; });
      var html = "", pos = 0;
      cuts.forEach(function (c) {
        html += esc(text.slice(pos, c.a)) + "<del>" + esc(c.e.before) + "</del>" + (c.e.after ? "<ins>" + esc(c.e.after) + "</ins>" : "");
        pos = c.b;
      });
      if (cuts.length) { tx.innerHTML = html + esc(text.slice(pos)); ln.classList.add("ed"); }
      var at = ln;
      extra.forEach(function (e) {
        if (!e.after) return;
        var add = el("div", "ln add ed", '<span class="no"></span><span class="tx"><ins>' + esc(e.after) + "</ins></span>");
        at.parentNode.insertBefore(add, at.nextSibling);
        at = add;
      });
    });
    var wrap = el("div", "redline");
    var lead = $(".lead", p);
    var head = el("div", "rl-head");
    if (lead) head.appendChild(lead.cloneNode(true));
    wrap.appendChild(head);
    wrap.appendChild(clone);
    p.insertBefore(wrap, p.firstChild);
  }

  /* пометки рисуются по порядку чтения, шаг 30 мс */
  function ink() {
    if (!doc) return;
    $$("mark.q", doc).forEach(function (m, i) { m.style.setProperty("--i", Math.min(i, 70)); });
    requestAnimationFrame(function () { root.classList.add("ink"); });
  }

  if (!split || !doc || !$(".ln", doc)) { redline(); return; }
  verdictLine();
  resolution();
  redline();
  ink();
  layout();
  window.addEventListener("resize", relayout);
  window.addEventListener("scroll", mapView, { passive: true });
  if (window.MutationObserver) {
    var mo = new MutationObserver(relayout);
    if (box) mo.observe(box, { subtree: true, attributes: true, attributeFilter: ["class", "hidden"] });
    var pf = $("#p-findings");
    if (pf) mo.observe(pf, { attributes: true, attributeFilter: ["hidden"] });
    mo.observe(doc, { attributes: true, attributeFilter: ["class"] });
  }
  document.addEventListener("toggle", relayout, true);
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(function () { relayout(); window.dispatchEvent(new Event("resize")); });
  setTimeout(function () { relayout(); mapView(); }, 120);
  /* щелчок по столу — снять фокус с правки */
  document.addEventListener("click", function (ev) {
    var t = ev.target;
    if (t === document.body || t === split || t === flist || t === box || (t.tagName === "MAIN")) {
      if ($(".card.active")) document.body.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    }
  });
})();
