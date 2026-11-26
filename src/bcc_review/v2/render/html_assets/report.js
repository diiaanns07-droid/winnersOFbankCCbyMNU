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
      var y = $(".tabs").getBoundingClientRect().top + window.scrollY - parseInt(getComputedStyle(root).getPropertyValue("--top-h"), 10);
      if (window.scrollY > y) window.scrollTo({ top: y });
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
    var top = el.offsetTop - doc.clientHeight / 3;
    doc.scrollTo({ top: Math.max(0, top), behavior: "smooth" });
    var last = parseInt(n2 || n, 10);
    for (var k = parseInt(n, 10); k <= last; k++) {
      var x = lineEl(k);
      if (x) { x.classList.remove("flash"); void x.offsetWidth; x.classList.add("flash"); }
    }
    if (window.matchMedia("(max-width: 960px)").matches) {
      var pane = $(".docpane");
      if (pane) pane.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }
  function clearSel() {
    $$(".ln.sel, .ln.rqsel, mark.q.on").forEach(function (x) { x.classList.remove("sel", "rqsel", "on"); });
    $$(".card.active").forEach(function (x) { x.classList.remove("active"); });
  }

  function selectFinding(id, opts) {
    opts = opts || {};
    var card = document.getElementById(id);
    if (!card || !card.classList.contains("card")) return;
    showTab("findings");
    clearSel();
    card.classList.add("active");
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
