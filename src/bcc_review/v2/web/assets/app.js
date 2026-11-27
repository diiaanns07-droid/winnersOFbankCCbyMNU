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
      var bottom = -1e9;
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

  /* ── страница задания ── */
  var wrap = document.querySelector("[data-job]");
  if (!wrap) return;
  var id = wrap.dataset.job;
  var STATE = { queued: "в очереди", running: "идёт анализ", done: "готово", failed: "ошибка" };
  var VERD = { no: "нельзя", conditional: "с условиями", yes: "можно" };
  function fmt(s) {
    s = Math.max(0, Math.round(s));
    return s < 60 ? s + " с" : Math.floor(s / 60) + " мин " + String(s % 60).padStart(2, "0") + " с";
  }
  function li(cls, inner) { var x = document.createElement("li"); x.className = "stg " + cls; x.innerHTML = inner; return x; }
  function esc(t) { var d = document.createElement("div"); d.textContent = t; return d.innerHTML; }
  function render(j) {
    $("#elapsed").textContent = fmt(j.elapsed);
    $("#pstate").textContent = STATE[j.state] || j.state;
    var box = $("#stages");
    box.innerHTML = "";
    var par = j.stage_list.filter(function (s) { return s.parallel; });
    var parDone = false;
    j.stage_list.forEach(function (s) {
      if (s.parallel) {
        if (parDone) return;
        parDone = true;
        var st = par.every(function (x) { return x.state === "done"; }) ? "done"
          : par.some(function (x) { return x.state === "failed"; }) ? "failed"
          : par.some(function (x) { return x.state === "running" || x.state === "done"; }) ? "running" : "pending";
        var subs = par.map(function (x) { return '<span class="sub ' + x.state + '">' + esc(x.label) + "</span>"; }).join("");
        box.appendChild(li(st, '<span class="ic"></span><span class="nm">Ревьюеры параллельно</span><span class="subs">' + subs + "</span>"));
        return;
      }
      var t = j.stage_times[s.id];
      box.appendChild(li(s.state, '<span class="ic"></span><span class="nm">' + esc(s.label) + '</span><span class="tm">' + (t ? fmt(t) : "") + "</span>"));
    });
    $("#log").textContent = (j.log || []).join("\n");
    var err = $("#err");
    if (j.state === "failed") { err.hidden = false; err.textContent = j.error || "Анализ завершился с ошибкой."; }
    var nt = $("#notice");
    if (nt && j.state === "done" && j.notice) { nt.hidden = false; nt.textContent = j.notice; }
    if (j.state === "done") {
      var af = $("#answers");
      if (af && af.hidden && !j.answers_path) {
        af.hidden = false;
        var inp = af.querySelector("input[type=file]");
        inp.addEventListener("change", function () {
          if (!inp.files.length) return;
          var lbl = af.querySelector("label");
          lbl.firstChild.textContent = "Пересчитываем… ";
          fetch("/api/jobs/" + id + "/answers", { method: "POST", body: new FormData(af), headers: { Accept: "application/json" } })
            .then(function (r) { return r.json().then(function (x) { return { ok: r.ok, x: x }; }); })
            .then(function (res) { if (res.ok) location.href = res.x.url; else throw new Error(res.x.error); })
            .catch(function (err) {
              lbl.firstChild.textContent = "Загрузить ответы ↻";
              inp.value = "";
              var e2 = $("#err"); e2.hidden = false; e2.textContent = err.message;
            });
        });
      }
      $("#prog").classList.add("compact");
      $("#result").hidden = false;
      document.querySelectorAll(".dl[data-key]").forEach(function (a) { a.hidden = !(a.dataset.key in j.files); });
      $("#dll").hidden = false; $("#newtab").hidden = false;
      var s = j.summary || {};
      $("#vsum").innerHTML = " · разработка: <b>" + esc(VERD[s.development] || "—") + "</b> · замечаний: <b>" +
        ((s.critical || 0) + (s.major || 0) + (s.minor || 0)) + "</b>, критичных <b>" + (s.critical || 0) + "</b>";
      var fr = $("#frame");
      if (!fr.src) fr.src = "/jobs/" + id + "/files/report.html?inline=1";
    }
    return j.state === "done" || j.state === "failed";
  }
  function poll() {
    fetch("/api/jobs/" + id, { headers: { Accept: "application/json" } })
      .then(function (r) { return r.json(); })
      .then(function (j) { if (!render(j)) setTimeout(poll, 1000); })
      .catch(function () { setTimeout(poll, 3000); });
  }
  poll();
})();
