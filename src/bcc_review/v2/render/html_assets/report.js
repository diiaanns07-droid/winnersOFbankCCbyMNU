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
      if (key === "stab") return ((+B.stab || 0) - (+A.stab || 0)) || (+B.rank - +A.rank) || (+A.line - +B.line);
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

  /* ── ответы владельца: файл в формате recheck.parse_answers_text, загрузка следующего круга ── */
  var LET = "ABCDEFGH";
  var LETTER = { A: 0, B: 1, C: 2, D: 3, "А": 0, "Б": 1, "В": 1, "С": 2, "Г": 3, "1": 0, "2": 1, "3": 2, "4": 3 };
  var QLINE = /^\s*(?:[-*+]\s+)?(?:\*\*|__)?\s*((?:Q|Вопрос)\s*-?\s*(\d{1,3})(?:\.\d+)?)\s*(?:\*\*|__)?\s*(?:\[((?:[^\[\]\n]|\[[^\[\]\n]*\]){1,200})\]|\(([^()\n]{1,200})\))?\s*(?:\*\*|__)?\s*(?:[:：=—–-]|[.)](?=[\s*_]))\s*(?:\*\*|__)?\s*(.*)$/i;
  var CHOICE = /^\s*(?:\*\*)?([A-DА-ГС1-4])(?:\*\*)?\s*(?:$|[).,;:—–-]\s*([\s\S]*)$|\s+[—–-]\s*([\s\S]*)$)/i;
  var TODO = /<решите:\s*([^>]*)>/g;
  var reportData = null;
  function rdata() { if (!reportData) reportData = JSON.parse($("#report-data").textContent); return reportData; }
  function oneLine(t) { return String(t || "").replace(/\s+/g, " ").trim(); }
  function normTopic(t) { return oneLine(t).toLowerCase().replace(/[«»"'()\[\].,:;!?—–-]/g, "").replace(/ё/g, "е"); }
  function qid(n) { return "Q-" + ("0" + parseInt(n, 10)).slice(-2); }
  var qcards = $$(".qcard");
  function card(id) { return qcards.filter(function (c) { return c.dataset.q === id; })[0] || null; }
  function topicSafe(t) {  // тема в [] разбирается, если в ней нет своих [ ] и она короче 200 символов
    return oneLine(t).replace(/\[/g, "(").replace(/\]/g, ")").slice(0, 200).trim();
  }
  function ownSafe(t) {  // свой текст не должен прочитаться как буква варианта («B. …», «1) …»)
    t = oneLine(t);
    return CHOICE.test(t) ? "«" + t + "»" : t;
  }
  function cardValue(c) {
    var id = c.dataset.q;
    var pick = $('input[name="' + id + '"]:checked', c);
    var own = $('textarea[data-own="' + id + '"]', c);
    var text = own ? oneLine(own.value) : "";
    var letter = pick ? (LET.charAt(+pick.value) || String(+pick.value + 1)) : "";
    if (letter && text) return letter + " — " + text;
    return letter || (text ? ownSafe(text) : "");
  }
  function decisionLines() {
    var d = $("#decisions");
    return d ? d.value.split(/\n/).map(oneLine).filter(Boolean) : [];
  }
  function answersText() {
    var data = rdata(), doc = data.document || {};
    var md = ["# Ответы владельца на вопросы ревью: «" + oneLine(doc.title) + "»", ""];
    if (doc.file || doc.sha256) md.push("> Документ: " + (doc.file || "") + (doc.sha256 ? " · SHA-256: " + doc.sha256 : ""));
    md.push("> Формат строки: `Q-01 [тема]: B` (буква варианта), `Q-01 [тема]: B — оговорка` или `Q-01 [тема]: свой ответ`.",
      "> Запуск: python -m bcc_review ДОКУМЕНТ ОТЧЁТ.md --answers ЭТОТ_ФАЙЛ --revise", "");
    var n = 0;
    (data.questions || []).forEach(function (qq) {
      var c = card(qq.id);
      var val = c ? cardValue(c) : "";
      if (!val) return;
      n++;
      var t = topicSafe(qq.topic);
      md.push(qq.id + (t ? " [" + t + "]" : "") + ": " + val);
    });
    var dec = decisionLines();
    if (dec.length) md.push("", "## Решения", "");
    dec.forEach(function (d) { md.push("- " + d); });
    return { text: md.join("\n") + "\n", answered: n, decisions: dec.length };
  }
  function refreshState() {
    var done = 0;
    qcards.forEach(function (c) {
      var st = $(".qstate", c), v = cardValue(c);
      var note = $(".qnote", c);
      var flag = note && !note.hidden ? note.dataset.kind : "";
      if (v) done++;
      if (st) {
        st.textContent = flag === "conflict" && !v ? "расхождение" : flag === "todo" && !v ? "нужно решить" : v ? "есть ответ" : "";
        st.className = "qstate " + (flag && !v ? "q-" + flag : v ? "q-done" : "");
      }
    });
    var qc = $("#qcount");
    if (qc) qc.textContent = qcards.length ? "Отвечено: " + done + " из " + qcards.length : "";
  }
  qcards.forEach(function (c) {
    c.addEventListener("change", refreshState);
    c.addEventListener("input", refreshState);
  });
  function setNote(c, kind, html) {
    var note = $(".qnote", c);
    if (!note) return;
    note.hidden = !html; note.dataset.kind = kind || ""; note.innerHTML = html || "";
    note.className = "qnote" + (kind ? " qn-" + kind : "");
  }
  function esc(t) { var d = document.createElement("div"); d.textContent = t; return d.innerHTML; }
  function applyValue(c, value) {
    var id = c.dataset.q;
    $$('input[name="' + id + '"]', c).forEach(function (r) { r.checked = false; });
    var own = $('textarea[data-own="' + id + '"]', c);
    if (own) own.value = "";
    value = oneLine(value);
    if (!value) return;
    var m = CHOICE.exec(value);
    if (m) {
      var idx = LETTER[m[1].toUpperCase()];
      var radio = $('input[name="' + id + '"][value="' + idx + '"]', c);
      var rest = oneLine(m[2] || m[3] || "");
      if (radio) {
        radio.checked = true;
        var label = radio.closest("label");
        var optText = label ? oneLine(label.textContent).replace(/^[A-HА-Г]\s*/, "") : "";
        if (rest && own && normTopic(rest) !== normTopic(optText)) own.value = rest;
        return;
      }
    }
    if (own) own.value = value.replace(/^«([\s\S]*)»$/, "$1");
  }
  function loadAnswers(text) {
    var byTopic = {}, byId = {};
    qcards.forEach(function (c) { byId[c.dataset.q] = c; if (c.dataset.topic) byTopic[normTopic(c.dataset.topic)] = c; });
    var got = {}, order = [], unmatched = [], decisions = [], inDec = false;
    String(text || "").replace(/^﻿/, "").split(/\r?\n/).forEach(function (raw) {
      var line = raw.replace(/\s+$/, "");
      if (!line.trim()) return;
      if (/^\s*#/.test(line)) { inDec = /^\s*#{1,6}\s*(решени|общие решени|дополнительн)/i.test(line); return; }
      if (/^\s*(>|<!--)/.test(line)) return;
      var m = QLINE.exec(line);
      if (!m) {
        if (inDec) { var d = oneLine(line.replace(/^\s*[-*+]\s+/, "")); if (d) decisions.push(d); }
        return;
      }
      var topic = m[3] || m[4] || "";
      // номер вопроса между прогонами может смениться — сначала тема, иначе номер
      var c = (topic && byTopic[normTopic(topic)]) || byId[qid(m[2])] || null;
      if (!c) { unmatched.push(oneLine(line).slice(0, 90)); return; }
      var key = c.dataset.q;
      if (!got[key]) { got[key] = []; order.push(key); }
      var v = oneLine(m[5]);
      if (got[key].indexOf(v) < 0) got[key].push(v);
    });
    var filled = 0, conflicts = 0, todos = 0;
    qcards.forEach(function (c) { setNote(c, "", ""); });
    order.forEach(function (key) {
      var c = byId[key], vals = got[key];
      if (vals.length > 1) {
        conflicts++;
        applyValue(c, "");
        setNote(c, "conflict", "<b>Ответы расходятся — оставьте один:</b> " + vals.map(function (v, i) {
          return '<button type="button" class="pickans" data-i="' + i + '">' + esc(v) + "</button>";
        }).join(" "));
        $$(".pickans", c).forEach(function (b) {
          b.addEventListener("click", function () { applyValue(c, vals[+b.dataset.i]); setNote(c, "", ""); refreshState(); });
        });
        return;
      }
      var v = vals[0], todo = [];
      v = v.replace(TODO, function (_, x) { todo.push(oneLine(x)); return ""; }).trim();
      applyValue(c, v);
      if (todo.length) { todos++; setNote(c, "todo", "<b>Нужно решить:</b> " + esc(todo.join("; "))); }
      else if (v) filled++;
    });
    var d = $("#decisions");
    if (d && decisions.length) d.value = decisions.join("\n");
    refreshState();
    showTab("questions");
    var parts = ["Ответов: " + filled];
    if (conflicts) parts.push("расхождений: " + conflicts);
    if (todos) parts.push("нужно решить: " + todos);
    if (decisions.length) parts.push("общих решений: " + decisions.length);
    if (unmatched.length) parts.push("не нашлось вопроса: " + unmatched.length);
    toast(parts.join(", "));
    return { filled: filled, conflicts: conflicts, todo: todos, decisions: decisions.length, unmatched: unmatched };
  }
  function nextText() {
    var el = $("#next-answers");
    try { return el ? JSON.parse(el.textContent) : ""; } catch (_) { return ""; }
  }
  var dla = $("#dlanswers");
  if (dla) {
    dla.addEventListener("click", function () {
      var a = answersText();
      if (!a.answered && !a.decisions) { toast("Отметьте хотя бы один ответ"); return; }
      download(base + ".answers.md", a.text, "text/markdown");
      toast("Ответов в файле: " + a.answered + (a.decisions ? ", общих решений: " + a.decisions : ""));
    });
  }
  var ula = $("#ulanswers");
  if (ula) {
    ula.addEventListener("change", function () {
      var f = ula.files && ula.files[0];
      if (!f) return;
      var rd = new FileReader();
      rd.onload = function () { loadAnswers(String(rd.result || "")); ula.value = ""; };
      rd.onerror = function () { toast("Не удалось прочитать файл"); };
      rd.readAsText(f, "utf-8");
    });
  }
  var clr = $("#clranswers");
  if (clr) clr.addEventListener("click", function () {
    qcards.forEach(function (c) { applyValue(c, ""); setNote(c, "", ""); });
    var d = $("#decisions"); if (d) d.value = "";
    refreshState();
  });
  var dln = $("#dlnext");
  if (dln) dln.addEventListener("click", function () {
    var t = nextText();
    if (!t) { toast("Файла следующего круга в отчёте нет"); return; }
    download(base + ".answers-next.md", t, "text/markdown");
  });
  var ldn = $("#loadnext");
  if (ldn) ldn.addEventListener("click", function () {
    var t = nextText();
    if (t) loadAnswers(t); else toast("Файла следующего круга в отчёте нет");
  });
  refreshState();
  // для веб-демо (та же страница во фрейме): пересчёт с ответами без скачивания файла
  window.bccReport = { answersText: answersText, loadAnswers: loadAnswers, nextText: nextText };

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
