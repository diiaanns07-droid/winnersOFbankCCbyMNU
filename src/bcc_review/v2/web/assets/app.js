/* Веб-демо v2 (№14): загрузка с перетаскиванием и опрос прогресса. */
(function () {
  "use strict";
  var $ = function (s) { return document.querySelector(s); };

  /* ── стол (№39): своя проверка — выбрать или бросить файл; меню модели ── */
  var form = $("#form");
  if (form && form.classList.contains("b-dock")) {
    var file = $("#file"), veil = $("#veil"), dmsg = $("#dmsg"), pnote = $("#pnote"), pcur = $("#pcur");
    var model = $("#model"), models = $("#models");
    var radios = form.querySelectorAll('input[name="provider"]');
    var say = function (text, bad) {
      if (!dmsg) return;
      dmsg.hidden = !text; dmsg.textContent = text || ""; dmsg.classList.toggle("bad", !!bad);
    };
    var current = function () { return form.querySelector('input[name="provider"]:checked') || radios[0]; };
    var syncProv = function () {
      var o = current();
      if (!o) return;
      pnote.innerHTML = o.dataset.note || "";
      pnote.classList.toggle("bad", o.dataset.ok !== "1");
      pcur.textContent = o.dataset.short || o.value;
      models.innerHTML = "";
      (o.dataset.models || "").split(",").filter(Boolean).forEach(function (m) {
        var x = document.createElement("option"); x.value = m; models.appendChild(x);
      });
      var off = !o.dataset.models && o.value !== "openai";
      model.disabled = off; model.hidden = off;
      if (off) model.value = "";
    };
    radios.forEach(function (r) { r.addEventListener("change", function () { syncProv(); say(""); }); });
    syncProv();
    var check = function (f0) {
      var ext = (f0.name.split(".").pop() || "").toLowerCase();
      return f0.size > 20 * 1024 * 1024 ? "Файл " + (f0.size / 1048576).toFixed(1) + " МБ — больше 20 МБ. Сожмите PDF или загрузите только раздел требований."
        : !f0.size ? "Файл пустой — в нём нет текста для проверки."
        : ["pdf", "docx", "md", "markdown", "txt", "html", "htm"].indexOf(ext) < 0 ? "Формат ." + ext + " не поддерживается: загрузите PDF, DOCX, MD, TXT или HTML."
        : "";
    };
    var send = function (sample) {
      if (!sample) {
        var f0 = file.files && file.files[0];
        if (!f0) { say("Выберите файл требований.", true); return; }
        var bad = check(f0);
        if (bad) { say(bad, true); return; }
      }
      var fd = new FormData(form);
      if (sample) { fd.delete("file"); fd.append("sample", "1"); }
      veil.hidden = false; veil.classList.add("busy");
      veil.querySelector("b").textContent = "Загружаем…";
      fetch("/api/jobs", { method: "POST", body: fd, headers: { Accept: "application/json" } })
        .then(function (r) { return r.json().then(function (j) { return { ok: r.ok, j: j }; }); })
        .then(function (res) {
          if (res.ok) { location.href = res.j.url; return; }
          throw new Error(res.j.error || "Не удалось начать проверку");
        })
        .catch(function (err) {
          veil.hidden = true; veil.classList.remove("busy");
          veil.querySelector("b").textContent = "Отпустите файл";
          file.value = "";
          say(err.message, true);
        });
    };
    file.addEventListener("change", function () { if (file.files && file.files.length) send(false); });
    form.addEventListener("submit", function (ev) {
      ev.preventDefault();
      send(!!(ev.submitter && ev.submitter.name === "sample"));
    });
    var depth = 0;
    var hasFiles = function (ev) { return ev.dataTransfer && Array.prototype.indexOf.call(ev.dataTransfer.types || [], "Files") >= 0; };
    window.addEventListener("dragenter", function (ev) { if (!hasFiles(ev)) return; ev.preventDefault(); depth++; veil.hidden = false; });
    window.addEventListener("dragover", function (ev) { if (hasFiles(ev)) ev.preventDefault(); });
    window.addEventListener("dragleave", function () { if (--depth <= 0) { depth = 0; if (!veil.classList.contains("busy")) veil.hidden = true; } });
    window.addEventListener("drop", function (ev) {
      if (!hasFiles(ev)) return;
      ev.preventDefault(); depth = 0;
      if (ev.dataTransfer.files.length) { file.files = ev.dataTransfer.files; send(false); }
      else veil.hidden = true;
    });
    document.addEventListener("click", function (ev) {
      document.querySelectorAll(".b-menu[open]").forEach(function (m) { if (!m.contains(ev.target)) m.open = false; });
    });
  }

  /* ── лист (№39): заметки на полях, фокус, карта листа ── */
  var sheet = $("#sheet");
  if (sheet) {
    var notes = Array.prototype.slice.call(sheet.querySelectorAll(".b-note"));
    var layout = function () {
      var wide = window.matchMedia("(min-width: 1241px)").matches;
      var head = document.querySelector(".b-margin-q") || document.querySelector(".b-margin-head");
      // заметки начинаются под шапкой полей и вопросами владельцу
      var bottom = head ? head.getBoundingClientRect().bottom - sheet.getBoundingClientRect().top + 6 : -1e9;
      notes.forEach(function (n) {
        n.style.removeProperty("--dy");
        if (!wide) return;
        var line = n.parentElement, top = line.offsetTop;
        var dy = Math.max(0, bottom + 6 - top);
        if (dy) n.style.setProperty("--dy", dy + "px");
        bottom = top + dy + n.offsetHeight;
      });
    };
    var focus = function (fid) {
      var on = sheet.dataset.focus === fid ? "" : fid;
      sheet.dataset.focus = on;
      sheet.classList.toggle("is-focus", !!on);
      sheet.querySelectorAll(".b-line").forEach(function (l) {
        l.classList.toggle("on", !!on && (" " + (l.dataset.f || "") + " ").indexOf(" " + on + " ") >= 0);
      });
      notes.forEach(function (n) { n.classList.toggle("on", n.dataset.f === on); });
      document.querySelectorAll(".b-q").forEach(function (q) { q.classList.toggle("on", !!on && q.dataset.f === on); });
      layout();
      var first = on && sheet.querySelector(".b-line.on");
      if (first) {
        var r = first.getBoundingClientRect();
        if (r.top < 70 || r.bottom > innerHeight - 90) window.scrollTo({ top: scrollY + r.top - innerHeight / 3, behavior: "smooth" });
      }
    };
    sheet.addEventListener("click", function (ev) {
      var t = ev.target.closest(".b-note, .b-hl");
      if (t) focus((t.dataset.f || "").split(" ")[0]);
      else if (sheet.dataset.focus) focus(sheet.dataset.focus);
    });
    document.addEventListener("keydown", function (ev) { if (ev.key === "Escape" && sheet.dataset.focus) focus(sheet.dataset.focus); });
    document.querySelectorAll(".b-q[data-f]").forEach(function (q) {  // вопрос владельцу → его место в листе
      if (!q.dataset.f) return;
      q.addEventListener("click", function () { focus(q.dataset.f); });  // focus() сам прокрутит к строке
    });
    var map = $("#map"), view = $("#mapview");
    var syncView = function () {
      if (!map || !view) return;
      var r = sheet.getBoundingClientRect(), h = Math.max(r.height, 1);
      var a = Math.min(1, Math.max(0, -r.top / h)), b = Math.min(1, Math.max(0, (innerHeight - r.top) / h));
      view.style.top = (a * 100) + "%"; view.style.height = Math.max(2, (b - a) * 100) + "%";
    };
    if (map) {
      map.addEventListener("click", function (ev) {
        var t = ev.target.closest("i[data-line]"), line;
        if (t) line = document.getElementById("L" + t.dataset.line);
        else {
          var r = map.getBoundingClientRect(), y = (ev.clientY - r.top) / r.height;
          line = document.getElementById("L" + Math.max(1, Math.round(y * (+sheet.dataset.lines || 1))));
        }
        if (line) window.scrollTo({ top: scrollY + line.getBoundingClientRect().top - innerHeight / 3, behavior: "smooth" });
        if (t) { var n = line && line.querySelector(".b-note"); if (n && !n.classList.contains("on")) focus(n.dataset.f); }
      });
    }
    var raf = 0;
    window.addEventListener("scroll", function () { if (!raf) raf = requestAnimationFrame(function () { raf = 0; syncView(); }); }, { passive: true });
    window.addEventListener("resize", function () { layout(); syncView(); });
    layout(); syncView();
    if (document.fonts && document.fonts.ready) document.fonts.ready.then(function () { layout(); syncView(); });
  }

  /* ── страница задания (№41): лист на столе. Проверка — луч сканера и BCC AI над листом; готово — правка на листе ── */
  var wrap = document.querySelector("main.jb[data-job]");
  if (!wrap) return;
  var id = wrap.dataset.job;
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
    if (j.state === "running" || j.state === "queued") mood("work");  /* AIshka (№40): за работой, пока идёт проверка */
    if (j.state === "failed" && shown !== "failed") {
      $("#err").hidden = false;
      $("#errtext").textContent = j.error || "Проверка завершилась с ошибкой.";
      $("#todo").textContent = hint(j.error);
      if (st) st.textContent = "не получилось";
      mood("oops");
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
    var setTop = function () {  // панель — под шапкой, лист — под панелью
      var root = document.documentElement.style, t = hdr ? Math.max(0, Math.round(hdr.getBoundingClientRect().bottom)) : 64;
      root.setProperty("--jb-hdr", t + "px");
      if (dock) t = Math.round(dock.getBoundingClientRect().bottom) + 6;
      root.setProperty("--jb-top", t + "px");
    };
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
        perch.setAttribute("data-size", "96");
        perch.setAttribute("data-mood", fr.dataset.mood || "idle");
        pane.appendChild(perch);
        var css = d.createElement("link"); css.rel = "stylesheet"; css.href = "/assets/agent.css"; d.head.appendChild(css);
        var js = d.createElement("script"); js.src = "/assets/agent.js";
        js.onload = function () {
          var a = perch.__bccAgent || (d.defaultView.BCCAgent && d.defaultView.BCCAgent.mount(perch));
          if (!a) return;
          a.mood(fr.dataset.mood || "idle", fr.dataset.mood === "speak" ? 3200 : 0);
          if (fr.dataset.say && a.say) setTimeout(function () { a.say(fr.dataset.say); }, 700);
        };
        d.body.appendChild(js);
      }
      d.addEventListener("change", function () {
        var rc = $("#recheck"); if (rc && !rc.hasAttribute("data-busy")) rc.disabled = !answersText().n;
      });
      d.addEventListener("click", function () { closeMenus(); });
      var h = location.hash.slice(1);  // №54: панель главной ведёт сюда с #questions и #revised (просьба №39 к №41)
      if (h === "questions" || h === "revised") setView(h);
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
