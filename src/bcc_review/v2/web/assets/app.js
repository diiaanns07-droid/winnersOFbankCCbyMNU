/* Веб-демо v2 (№14): загрузка с перетаскиванием и опрос прогресса. */
(function () {
  "use strict";
  var $ = function (s) { return document.querySelector(s); };

  /* ── страница загрузки (№39) ── */
  var form = $("#form");
  if (form) {
    var drop = $("#drop"), file = $("#file"), fname = $("#fname");
    var pnote = $("#pnote"), model = $("#model"), models = $("#models"), pmore = $("#pmore");
    var radios = form.querySelectorAll('input[name="provider"]');
    var note = function (html, bad) { pnote.innerHTML = html; pnote.classList.toggle("bad", !!bad); pnote.classList.remove("err"); };
    var fail = function (text) { pnote.textContent = text; pnote.classList.remove("bad"); pnote.classList.add("err"); };
    var showName = function () {
      var f = file.files && file.files[0];
      fname.textContent = f ? f.name : "";
      drop.classList.toggle("has", !!f);
    };
    file.addEventListener("change", showName);
    var depth = 0;
    drop.addEventListener("dragenter", function (ev) { ev.preventDefault(); depth++; drop.classList.add("over"); });
    drop.addEventListener("dragover", function (ev) { ev.preventDefault(); });
    drop.addEventListener("dragleave", function () { if (--depth <= 0) { depth = 0; drop.classList.remove("over"); } });
    drop.addEventListener("drop", function (ev) {
      ev.preventDefault(); depth = 0; drop.classList.remove("over");
      if (ev.dataTransfer && ev.dataTransfer.files.length) { file.files = ev.dataTransfer.files; showName(); }
    });
    var current = function () { return form.querySelector('input[name="provider"]:checked') || radios[0]; };
    var syncProv = function () {
      var o = current();
      if (!o) return;
      note(o.dataset.note || "", o.dataset.ok !== "1");
      models.innerHTML = "";
      (o.dataset.models || "").split(",").filter(Boolean).forEach(function (m) {
        var x = document.createElement("option"); x.value = m; models.appendChild(x);
      });
      var off = !o.dataset.models && o.value !== "openai";
      model.disabled = off;
      if (off) model.value = "";
      pmore.hidden = off;
    };
    radios.forEach(function (r) { r.addEventListener("change", syncProv); });
    syncProv();
    var go = $("#go"), goText = go.textContent;
    form.addEventListener("submit", function (ev) {
      var sample = ev.submitter && ev.submitter.name === "sample";
      if (!sample && !(file.files && file.files.length)) { ev.preventDefault(); fail("Выберите файл требований."); return; }
      if (!sample) {
        var f0 = file.files[0];
        var ext = (f0.name.split(".").pop() || "").toLowerCase();
        var bad = f0.size > 20 * 1024 * 1024 ? "Файл " + (f0.size / 1048576).toFixed(1) + " МБ — больше 20 МБ. Сожмите PDF или загрузите только раздел требований."
          : !f0.size ? "Файл пустой — в нём нет текста для проверки."
          : ["pdf", "docx", "md", "markdown", "txt", "html", "htm"].indexOf(ext) < 0 ? "Формат ." + ext + " не поддерживается: загрузите PDF, DOCX, MD, TXT или HTML."
          : "";
        if (bad) { ev.preventDefault(); fail(bad); return; }
      }
      ev.preventDefault();
      var fd = new FormData(form);
      if (sample) fd.append("sample", "1");
      var btns = form.querySelectorAll("button");
      btns.forEach(function (b) { b.disabled = true; });
      go.textContent = "Загружаем…";
      fetch("/api/jobs", { method: "POST", body: fd, headers: { Accept: "application/json" } })
        .then(function (r) { return r.json().then(function (j) { return { ok: r.ok, j: j }; }); })
        .then(function (res) {
          if (res.ok) { location.href = res.j.url; return; }
          throw new Error(res.j.error || "Не удалось начать проверку");
        })
        .catch(function (err) {
          btns.forEach(function (b) { b.disabled = false; });
          go.textContent = goText;
          var box = form.querySelector(".home-err");
          if (!box) { box = document.createElement("p"); box.className = "home-err"; box.setAttribute("role", "alert"); form.querySelector(".home-act").before(box); }
          box.textContent = err.message;
        });
    });
  }

  /* ── страница задания (№41): прогресс, вердикт, вкладки, боковое окно с документом ── */
  var wrap = document.querySelector("[data-job]");
  if (!wrap) return;
  var id = wrap.dataset.job;
  var STATE = { queued: "в очереди", running: "идёт проверка", done: "готово", failed: "ошибка" };
  var SCAN = { docview: 1, segment: 1, rules: 1, lens_analyst: 1, lens_qa: 1, lens_architect: 1, lens_risk: 1, consistency: 1, quotes: 1 };
  function fmt(s) {
    s = Math.max(0, Math.round(s));
    return s < 60 ? s + " с" : Math.floor(s / 60) + " мин " + String(s % 60).padStart(2, "0") + " с";
  }
  function esc(t) { var d = document.createElement("div"); d.textContent = t == null ? "" : t; return d.innerHTML; }
  function plural(n, a, b, c) { n = Math.abs(n) % 100; var k = n % 10; return n > 10 && n < 20 ? c : k === 1 ? a : k > 1 && k < 5 ? b : c; }

  /* BCC AI (№40): режим меняем через экземпляр, если он есть, и всегда — через data-mood */
  function agentEl() { return document.querySelector(".jb-agent [data-bcc-agent]"); }
  function mood(m, ms) {
    var el = agentEl();
    if (!el || (el.dataset.mood === m && !ms)) return;
    el.dataset.mood = m;
    var a = el.__bccAgent || null;
    if (a && typeof a.mood === "function") { try { a.mood(m, ms); } catch (_) {} }
  }
  /* итог: блокеров нет — verified; есть — alert на 1,5 с, затем idle (bcc-ui.md, раздел 7) */
  function finalMood(alert) {
    mood(alert ? "alert" : "verified", alert ? 1500 : 0);
    if (alert) setTimeout(function () { var el = agentEl(); if (el && !el.__bccAgent) el.dataset.mood = "idle"; }, 1500);
  }

  /* ── прогресс: строки создаём один раз и дальше только меняем классы — точка пульсирует без рывков ── */
  var rows = {};
  function row(key, label) {
    if (rows[key]) return rows[key];
    var x = document.createElement("li");
    x.className = "jb-stg pending";
    x.innerHTML = '<span class="jb-ic" aria-hidden="true"></span><div class="jb-nm">' + esc(label) +
      '<div class="jb-subs"></div></div><span class="jb-tm"></span>';
    $("#stages").appendChild(x);
    rows[key] = x;
    return x;
  }
  function setState(x, st) { var c = "jb-stg " + st; if (x.className !== c) x.className = c; }
  function hint(err) {
    err = (err || "").toLowerCase();
    if (/ключ|api|401|403|quota|квот|лимит|модел/.test(err)) return "Что сделать: проверьте ключ модели в файле .env или выберите «Демо без модели» и запустите проверку снова.";
    if (/прочитать|скан|текст|пуст/.test(err)) return "Что сделать: загрузите файл с текстом (не скан страниц) — PDF с текстовым слоем, Word или Markdown.";
    if (/перезапущен/.test(err)) return "Что сделать: запустите проверку ещё раз — документ не потерян.";
    return "Что сделать: запустите проверку ещё раз; подробности — в журнале запуска ниже.";
  }
  var shownState = "";
  function render(j) {
    $("#elapsed").textContent = fmt(j.elapsed);
    $("#pstate").textContent = STATE[j.state] || j.state;
    $("#calls").textContent = j.calls ? " · " + j.calls + " " + plural(j.calls, "вызов", "вызова", "вызовов") + " модели" : "";
    var par = j.stage_list.filter(function (s) { return s.parallel; });
    var running = null;
    j.stage_list.forEach(function (s) {
      if (s.state === "running" && !running) running = s.id;
      if (s.parallel) {
        if (s !== par[0]) return;
        var x = row("lenses", "Ревьюеры параллельно");
        var st = par.every(function (p) { return p.state === "done" || p.state === "skipped"; }) ? "done"
          : par.some(function (p) { return p.state === "failed"; }) ? "failed"
          : par.some(function (p) { return p.state === "running" || p.state === "done"; }) ? "running" : "pending";
        setState(x, st);
        var subs = x.querySelector(".jb-subs");
        if (!subs.children.length) subs.innerHTML = par.map(function (p) { return '<span class="jb-sub" data-id="' + esc(p.id) + '">' + esc(p.label) + "</span>"; }).join("");
        par.forEach(function (p) { var e2 = subs.querySelector('[data-id="' + p.id + '"]'); if (e2) e2.className = "jb-sub " + p.state; });
        var tl = Math.max.apply(null, par.map(function (p) { return j.stage_times[p.id] || 0; }));
        x.querySelector(".jb-tm").textContent = st === "done" && tl ? fmt(tl) : "";
        return;
      }
      var y = row(s.id, s.label);
      setState(y, s.state);
      var t = j.stage_times[s.id];
      y.querySelector(".jb-tm").textContent = t ? fmt(t) : "";
    });
    $("#log").textContent = (j.log || []).join("\n");
    if (j.state === "running" || j.state === "queued") mood(running && !SCAN[running] ? "analyzing" : "scanning");
    if (j.state === "failed" && shownState !== "failed") {
      $("#err").hidden = false;
      $("#errtext").textContent = j.error || "Проверка завершилась с ошибкой.";
      $("#todo").textContent = hint(j.error);
      mood("alert");
    }
    if (j.state === "done" && shownState !== "done") showResult(j);
    shownState = j.state;
    return j.state === "done" || j.state === "failed";
  }
  function poll() {
    fetch("/api/jobs/" + id, { headers: { Accept: "application/json" } })
      .then(function (r) { return r.json(); })
      .then(function (j) { if (!render(j)) setTimeout(poll, 1000); })
      .catch(function () { setTimeout(poll, 3000); });
  }

  /* ── прогон закончился при открытой странице: подгружаем отчёт и переносим BCC AI к вердикту ── */
  function showResult(j) {
    var res = $("#result");
    if (!res.hidden && res.children.length) return;
    fetch("/jobs/" + id + "?part=result").then(function (r) { if (!r.ok) throw new Error(r.status); return r.text(); })
      .then(function (html) {
        res.innerHTML = html;
        var ag = $("#agent-home > [data-bcc-agent]"), slot = $("#agent-slot");
        if (ag && slot) slot.appendChild(ag);
        $("#prog").hidden = true;
        res.hidden = false;
        initResult();
        var s = j.summary || {};
        finalMood((s.critical || 0) > 0);
        window.scrollTo({ top: 0 });
      })
      .catch(function () { location.reload(); });
  }

  /* ── отчёт: вкладки-капсулы над рамкой с HTML-отчётом ── */
  function initResult() {
    var fr = $("#rframe"), box = $("#framebox");
    if (!fr) return;
    var view = "findings", fdoc = null;
    function rdoc() { try { return fr.contentDocument; } catch (_) { return null; } }
    function rtab(name) { var d = rdoc(), t = d && d.getElementById("t-" + name); if (t) t.click(); return !!t; }
    function closeDrawer() { var d = rdoc(); if (d && d.body) d.body.dispatchEvent(new d.defaultView.KeyboardEvent("keydown", { key: "Escape", bubbles: true })); }
    /* страница встаёт так, чтобы вкладки были сверху, а рамка — сразу под ними (без вложенной прокрутки к ней) */
    function toFrame(force) {
      var prev = $(".jb-block"), res = $("#result"), hdr = $(".tb-wrap");
      if (!prev) return;
      var gap = parseFloat(getComputedStyle(res).rowGap) || 24;
      var top = parseFloat(getComputedStyle($(".jb-tabbar")).top) || (hdr ? hdr.getBoundingClientRect().bottom + 10 : 12);
      var y = prev.getBoundingClientRect().bottom + window.scrollY + gap - top;
      if (force ? Math.abs(window.scrollY - y) > 4 : window.scrollY > y + 4) window.scrollTo({ top: y, behavior: "smooth" });
    }
    function setView(v, rt) {
      view = v;
      document.querySelectorAll("#tabs [data-view]").forEach(function (b) { b.setAttribute("aria-selected", b.dataset.view === v ? "true" : "false"); });
      var revisedReady = $("#revised-empty").hasAttribute("data-ready");
      $("#qbar").hidden = v !== "questions";
      $("#exports").hidden = v !== "exports";
      $("#revised-empty").hidden = !(v === "revised" && !revisedReady);
      box.hidden = v === "exports" || (v === "revised" && !revisedReady);
      var d = rdoc();
      if (d && d.documentElement) {
        d.documentElement.setAttribute("data-view", v);
        if (v === "doc") closeDrawer();
        rtab(rt || { questions: "questions", revised: "rewrites" }[v] || "findings");
      }
    }
    function embed() {
      var d = rdoc();
      if (!d || !d.documentElement || fdoc === d) return;
      fdoc = d;
      var root = d.documentElement;
      root.setAttribute("data-embed", "");
      root.dataset.theme = "light";
      var head = d.querySelector(".dochead");
      if (head && !d.getElementById("jbclose")) {
        var x = d.createElement("button");
        x.type = "button"; x.id = "jbclose"; x.className = "dclose"; x.setAttribute("aria-label", "Закрыть документ"); x.title = "Закрыть (Esc)";
        x.addEventListener("click", closeDrawer);
        head.appendChild(x);
      }
      var sync = function () {
        var open = !!d.querySelector(".card.active, .ln.rqsel");
        if (open !== root.hasAttribute("data-drawer")) { if (open) root.setAttribute("data-drawer", ""); else root.removeAttribute("data-drawer"); }
      };
      var target = d.getElementById("p-findings");
      if (target && window.MutationObserver) new MutationObserver(sync).observe(target, { subtree: true, attributes: true, attributeFilter: ["class"] });
      setView(view);
      setTimeout(function () { fr.classList.add("ready"); root.setAttribute("data-drawer-ready", ""); }, 60);
    }
    fr.addEventListener("load", embed);
    if (!fr.getAttribute("src")) fr.src = fr.dataset.src;
    document.querySelectorAll("[data-view]").forEach(function (b) {
      if (b.closest("#tabs") || b.closest("#revised-empty")) b.addEventListener("click", function () { setView(b.dataset.view); toFrame(); });
    });
    var tabs = Array.prototype.slice.call(document.querySelectorAll("#tabs [data-view]"));
    tabs.forEach(function (b, i) {
      b.addEventListener("keydown", function (ev) {
        var dd = ev.key === "ArrowRight" ? 1 : ev.key === "ArrowLeft" ? -1 : 0;
        if (!dd) return;
        ev.preventDefault();
        var n = tabs[(i + dd + tabs.length) % tabs.length]; n.focus(); setView(n.dataset.view);
      });
    });
    var extra = $(".jb-extra");
    document.querySelectorAll("[data-rtab]").forEach(function (b) {
      b.addEventListener("click", function () { setView("more", b.dataset.rtab); if (extra) extra.open = false; });
    });
    document.addEventListener("click", function (ev) { if (extra && extra.open && !ev.target.closest(".jb-extra")) extra.open = false; });
    /* блокер → замечание в рамке, документ открывается сбоку с подсвеченными строками */
    document.querySelectorAll("[data-goto]").forEach(function (a) {
      a.addEventListener("click", function (ev) {
        var d = rdoc();
        if (!d) return;
        ev.preventDefault();
        setView("findings");
        toFrame(true);
        var c = d.getElementById(a.dataset.goto);
        if (c) {
          c.click();
          setTimeout(function () {  /* после того как окно с документом открылось и колонка карточек сузилась */
            var w = d.defaultView, f = d.querySelector(".filters");
            w.scrollTo({ top: Math.max(0, c.getBoundingClientRect().top + w.scrollY - (f ? f.offsetHeight : 0) - 12), behavior: "smooth" });
          }, 30);
        }
      });
    });
    /* ответы владельца: скачать (из отчёта в рамке) и загрузить → повторная проверка */
    var dl = $("#dlanswers");
    if (dl) dl.addEventListener("click", function () { var d = rdoc(), b = d && d.getElementById("dlanswers"); if (b) b.click(); });
    var qbar = $("#qbar"), inp = qbar && qbar.querySelector("input[type=file]");
    if (inp) inp.addEventListener("change", function () {
      if (!inp.files.length) return;
      var lbl = inp.parentNode.querySelector("span"), note = qbar.querySelector(".b-note");
      lbl.textContent = "Пересчитываем…";
      fetch("/api/jobs/" + id + "/answers", { method: "POST", body: new FormData(qbar), headers: { Accept: "application/json" } })
        .then(function (r) { return r.json().then(function (x) { return { ok: r.ok, x: x }; }); })
        .then(function (res) { if (res.ok) location.href = res.x.url; else throw new Error(res.x.error); })
        .catch(function (err) {
          lbl.textContent = "Загрузить ответы ↻"; inp.value = "";
          note.className = "b-status error"; note.textContent = err.message;
        });
    });
  }

  if (wrap.dataset.state === "done" && !$("#result").hidden) {
    initResult();
    finalMood(!!document.querySelector(".jb-row:not(.ok)"));
  } else {
    poll();
  }
})();
