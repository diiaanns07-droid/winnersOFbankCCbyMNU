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
    var note = function (html, bad) { pnote.innerHTML = html; pnote.classList.toggle("bad", !!bad); };
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
      if (!sample && !(file.files && file.files.length)) { ev.preventDefault(); note("Выберите файл требований.", true); return; }
      if (!sample) {
        var f0 = file.files[0];
        var ext = (f0.name.split(".").pop() || "").toLowerCase();
        var bad = f0.size > 20 * 1024 * 1024 ? "Файл " + (f0.size / 1048576).toFixed(1) + " МБ — больше 20 МБ. Сожмите PDF или загрузите только раздел требований."
          : !f0.size ? "Файл пустой — в нём нет текста для проверки."
          : ["pdf", "docx", "md", "markdown", "txt", "html", "htm"].indexOf(ext) < 0 ? "Формат ." + ext + " не поддерживается: загрузите PDF, DOCX, MD, TXT или HTML."
          : "";
        if (bad) { ev.preventDefault(); note(bad, true); return; }
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
