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

  /* ── страница задания (№41): лист на столе. Проверка — луч сканера и BCC AI над листом; готово — правка на листе ── */
  var wrap = document.querySelector("main.jb[data-job]");
  if (!wrap) return;
  var id = wrap.dataset.job;
  var SCAN = { docview: 1, segment: 1, rules: 1, lens_analyst: 1, lens_qa: 1, lens_architect: 1, lens_risk: 1, consistency: 1, quotes: 1 };
  var SAY = { docview: "читаю документ", segment: "нарезаю требования", rules: "проверяю правилами",
    lenses: "4 ревьюера читают", quotes: "сверяю цитаты", judge: "судья взвешивает", clarify: "готовлю вопросы",
    recheck: "перепроверяю по ответам", revise: "правлю текст", report: "собираю правку" };
  function fmt(s) {
    s = Math.max(0, Math.round(s));
    return s < 60 ? s + " с" : Math.floor(s / 60) + " мин " + String(s % 60).padStart(2, "0") + " с";
  }
  function plural(n, a, b, c) { n = Math.abs(n) % 100; var k = n % 10; return n > 10 && n < 20 ? c : k === 1 ? a : k > 1 && k < 5 ? b : c; }

  /* BCC AI (№40): режим — через экземпляр el.__bccAgent и всегда через data-mood */
  function agentEl() { return document.querySelector(".jb-agent [data-bcc-agent]"); }
  function mood(m, ms) {
    var el = agentEl();
    if (!el || (el.dataset.mood === m && !ms)) return;
    el.dataset.mood = m;
    var a = el.__bccAgent || null;
    if (a && typeof a.mood === "function") { try { a.mood(m, ms); } catch (_) {} }
  }
  function hint(err) {
    err = (err || "").toLowerCase();
    if (/ключ|api|401|403|quota|квот|лимит|модел/.test(err)) return "Что сделать: проверьте ключ модели в файле .env или выберите «Демо без модели» и запустите проверку снова.";
    if (/прочитать|скан|текст|пуст/.test(err)) return "Что сделать: загрузите файл с текстом (не скан страниц) — PDF с текстовым слоем, Word или Markdown.";
    if (/перезапущен/.test(err)) return "Что сделать: запустите проверку ещё раз — документ не потерян.";
    return "Что сделать: запустите проверку ещё раз; подробности — в журнале запуска ниже.";
  }

  /* ── проверка: прогресс — это луч сканера, идущий по листу ── */
  var shown = "", lastY = -1;
  function units(j) {
    var list = [], seen = false;
    j.stage_list.forEach(function (s) {
      if (s.parallel) {
        if (seen) return;
        seen = true;
        var par = j.stage_list.filter(function (x) { return x.parallel; });
        var st = par.every(function (x) { return x.state === "done" || x.state === "skipped"; }) ? "done"
          : par.some(function (x) { return x.state === "running" || x.state === "done"; }) ? "running" : "pending";
        list.push({ id: "lenses", state: st });
        return;
      }
      list.push({ id: s.id, state: s.state });
    });
    return list;
  }
  function render(j) {
    var el = $("#elapsed");
    if (el) el.textContent = fmt(j.elapsed);
    var calls = $("#calls");
    if (calls) calls.textContent = j.calls ? " · " + j.calls + " " + plural(j.calls, "вызов", "вызова", "вызовов") + " модели" : "";
    var u = units(j), done = 0, cur = null;
    u.forEach(function (x) { if (x.state === "done" || x.state === "skipped") done++; else if (!cur && x.state === "running") cur = x; });
    if (!cur) cur = u.filter(function (x) { return x.state === "pending"; })[0] || null;
    var frac = j.state === "done" ? 1 : Math.min(.97, (done + (cur && cur.state === "running" ? .5 : 0)) / Math.max(1, u.length));
    var st = $("#stage");
    if (st && j.state !== "failed") st.textContent = j.state === "queued" ? "жду очереди" : j.state === "done" ? "готово" : SAY[cur ? cur.id : ""] || "читаю документ";
    moveBeam(frac);
    $("#log").textContent = (j.log || []).join("\n");
    if (j.state === "running" || j.state === "queued") mood(cur && !SCAN[cur.id] && cur.id !== "lenses" ? "analyzing" : "scanning");
    if (j.state === "failed" && shown !== "failed") {
      $("#err").hidden = false;
      $("#errtext").textContent = j.error || "Проверка завершилась с ошибкой.";
      $("#todo").textContent = hint(j.error);
      if (st) st.textContent = "не получилось";
      mood("alert");
      wrap.classList.add("finished");
    }
    if (j.state === "done" && shown !== "done") showResult(j);
    shown = j.state;
    return j.state === "done" || j.state === "failed";
  }
  function moveBeam(frac) {
    var sheet = $("#sheet"), beam = $("#beam"), pilot = $("#pilot");
    if (!sheet || !beam) return;
    var top = 40, h = sheet.offsetHeight - 80;
    var y = Math.round(top + frac * Math.max(0, h));
    if (y === lastY) return;
    lastY = y;
    beam.style.top = y + "px";
    if (pilot) pilot.style.top = y + "px";
    document.querySelectorAll("#sheet .ln").forEach(function (ln) { if (ln.offsetTop + ln.offsetHeight < y) ln.classList.add("read"); });
    /* лист длиннее экрана — страница плавно едет за лучом (считаем по месту, куда луч придёт) */
    var at = sheet.getBoundingClientRect().top + y;
    if (at > window.innerHeight * .7 || at < 90) window.scrollTo({ top: Math.max(0, at + window.scrollY - window.innerHeight * .45), behavior: "smooth" });
  }
  function poll() {
    fetch("/api/jobs/" + id, { headers: { Accept: "application/json" } })
      .then(function (r) { return r.json(); })
      .then(function (j) { if (!render(j)) setTimeout(poll, 1000); })
      .catch(function () { setTimeout(poll, 3000); });
  }

  /* прогон закончился при открытой странице: луч доходит до низа, лист сменяется правкой */
  function showResult() {
    wrap.classList.add("finished");
    fetch("/jobs/" + id + "?part=result").then(function (r) { if (!r.ok) throw new Error(r.status); return r.text(); })
      .then(function (html) {
        setTimeout(function () {
          wrap.innerHTML = html;
          wrap.classList.add("done");
          wrap.dataset.state = "done";
          window.scrollTo({ top: 0 });
          initResult();
        }, 700);
      })
      .catch(function () { location.reload(); });
  }

  /* ── готовая правка: лист-отчёт на весь стол и стеклянная панель ── */
  function initResult() {
    var fr = $("#rframe"), dock = $("#dock");
    if (!fr) return;
    var hdr = document.querySelector(".tb-wrap, header");
    var setTop = function () { var t = hdr ? Math.round(hdr.getBoundingClientRect().bottom) : 64; document.documentElement.style.setProperty("--jb-top", Math.max(0, t) + "px"); };
    setTop();
    window.addEventListener("resize", setTop);
    var view = "findings";
    function rdoc() { try { return fr.contentDocument; } catch (_) { return null; } }
    function rtab(name) { var d = rdoc(), t = d && d.getElementById("t-" + name); if (t) { t.click(); return true; } return false; }
    function toast(msg) {
      var t = $("#toast"); if (!t) return;
      t.textContent = msg; t.hidden = false;
      clearTimeout(toast.t); toast.t = setTimeout(function () { t.hidden = true; }, 2600);
    }
    function closeMenus() {
      document.querySelectorAll(".jb-menu").forEach(function (m) { m.hidden = true; });
      document.querySelectorAll("[data-menu]").forEach(function (b) { b.setAttribute("aria-expanded", "false"); });
    }
    function press(v) {
      document.querySelectorAll("#dock [data-view]").forEach(function (b) { b.setAttribute("aria-pressed", b.dataset.view === v ? "true" : "false"); });
      var rc = $("#recheck");
      if (rc) rc.hidden = v !== "questions";
    }
    function setView(v, rt) {
      closeMenus();
      if (v === "revised") {
        var b = $('#dock [data-view="revised"]');
        if (!b || !b.dataset.rt) { toast("Исправленная редакция появится после ответов на вопросы владельца."); v = "questions"; rt = "questions"; }
        else rt = b.dataset.rt;
      }
      view = v;
      press(v);
      rtab(rt || { questions: "questions" }[v] || "findings");
    }
    function answersText() {
      var d = rdoc(); if (!d) return { n: 0, text: "" };
      var data = {}; try { data = JSON.parse(d.getElementById("report-data").textContent); } catch (_) {}
      var LET = "ABCDEFGH", md = ["# Ответы владельца на вопросы ревью: «" + ((data.document || {}).title || "") + "»", "",
        "> Формат строки: `Q-01: B` (буква варианта) или `Q-01 [тема]: свой ответ`.", ""], n = 0;
      (data.questions || []).forEach(function (q) {
        var pick = d.querySelector('input[name="' + q.id + '"]:checked'), own = d.querySelector('textarea[data-own="' + q.id + '"]');
        var text = own && own.value.trim() ? own.value.trim().replace(/\s*\n\s*/g, " ") : "";
        var val = text || (pick ? (LET.charAt(+pick.value) || String(+pick.value + 1)) : "");
        if (!val) return;
        n++; md.push(q.id + (q.topic ? " [" + q.topic + "]" : "") + ": " + val);
      });
      return { n: n, text: md.join("\n") + "\n" };
    }
    function embed() {
      var d = rdoc();
      if (!d || !d.documentElement || d.documentElement.hasAttribute("data-embed")) return;
      var root = d.documentElement;
      root.setAttribute("data-embed", "");
      /* BCC AI садится на край листа и говорит одной строкой (agent.js №40 — в том же окне листа) */
      var pane = d.querySelector(".docpane");
      if (pane && window.BCCAgent) {
        var perch = d.createElement("div");
        perch.className = "perch";
        perch.setAttribute("data-bcc-agent", "");
        perch.setAttribute("data-size", "80");
        perch.setAttribute("data-mood", fr.dataset.mood || "idle");
        pane.appendChild(perch);
        var css = d.createElement("link"); css.rel = "stylesheet"; css.href = "/assets/agent.css"; d.head.appendChild(css);
        var js = d.createElement("script"); js.src = "/assets/agent.js";
        js.onload = function () {
          var a = perch.__bccAgent || (d.defaultView.BCCAgent && d.defaultView.BCCAgent.mount(perch));
          if (!a) return;
          if (fr.dataset.mood === "alert") a.mood("alert", 1500); else a.mood("verified");
          if (fr.dataset.say && a.say) setTimeout(function () { a.say(fr.dataset.say); }, 700);
        };
        d.body.appendChild(js);
      }
      d.addEventListener("change", function () {
        var rc = $("#recheck"); if (rc && !rc.hasAttribute("data-busy")) rc.disabled = !answersText().n;
      });
      d.addEventListener("click", function () { closeMenus(); });
      press(view);
      setTimeout(function () { fr.classList.add("ready"); }, 40);
    }
    fr.addEventListener("load", embed);
    if (!fr.getAttribute("src")) fr.src = fr.dataset.src;
    if (!dock) return;
    dock.querySelectorAll("[data-view]").forEach(function (b) { b.addEventListener("click", function () { setView(b.dataset.view); }); });
    document.querySelectorAll("[data-menu]").forEach(function (b) {
      b.addEventListener("click", function (ev) {
        ev.stopPropagation();
        var m = $("#menu-" + b.dataset.menu), open = m.hidden;
        closeMenus();
        if (open) { m.hidden = false; b.setAttribute("aria-expanded", "true"); var f = m.querySelector("a, button"); if (f) f.focus(); }
      });
    });
    document.querySelectorAll("[data-rtab]").forEach(function (b) {
      b.addEventListener("click", function () { closeMenus(); press(""); rtab(b.dataset.rtab); });
    });
    document.addEventListener("click", function (ev) { if (!ev.target.closest(".jb-menu, [data-menu]")) closeMenus(); });
    document.addEventListener("keydown", function (ev) { if (ev.key === "Escape") closeMenus(); });
    var am = document.querySelector('[data-act="answers-md"]');
    if (am) am.addEventListener("click", function () {
      closeMenus();
      var d = rdoc(), b = d && d.getElementById("dlanswers");
      if (b) { setView("questions"); b.click(); }
    });
    var rc = $("#recheck");
    if (rc) {
      rc.disabled = true;
      rc.addEventListener("click", function () {
        var a = answersText();
        if (!a.n) { toast("Отметьте хотя бы один ответ на стикерах."); return; }
        rc.setAttribute("data-busy", ""); rc.disabled = true; rc.textContent = "Проверяю заново…";
        var fd = new FormData(); fd.append("answers_text", a.text);
        fetch("/api/jobs/" + id + "/answers", { method: "POST", body: fd, headers: { Accept: "application/json" } })
          .then(function (r) { return r.json().then(function (x) { return { ok: r.ok, x: x }; }); })
          .then(function (res) { if (res.ok) location.href = res.x.url; else throw new Error(res.x.error); })
          .catch(function (err) { rc.removeAttribute("data-busy"); rc.disabled = false; rc.textContent = "Проверить заново"; toast(err.message); });
      });
    }
  }

  if (wrap.classList.contains("done")) initResult();
  else poll();
})();
