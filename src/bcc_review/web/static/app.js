// Веб-демо: опрос статуса, одна кнопка загрузки, защита от двойного клика, подстановка ответов.
(function () {
  "use strict";
  var body = document.body;

  // Одна кнопка загрузки: выбор файла сразу отправляет форму.
  var input = document.getElementById("upload-input");
  if (input) {
    input.addEventListener("change", function () {
      if (!input.files || !input.files.length) return;
      var label = document.getElementById("upload-label");
      if (label) { label.classList.add("busy"); label.querySelector("span").textContent = "Загружаю " + input.files[0].name + "…"; }
      input.form.submit();
      input.disabled = true;
    });
  }

  // Повторный клик по форме не отправляет её второй раз (сервер тоже защищён заявкой).
  Array.prototype.forEach.call(document.querySelectorAll("form.once"), function (form) {
    form.addEventListener("submit", function (ev) {
      if (form.dataset.sent) { ev.preventDefault(); return; }
      form.dataset.sent = "1";
      Array.prototype.forEach.call(form.querySelectorAll("button[type=submit]"), function (b) {
        b.classList.add("busy"); b.textContent = "Отправлено…";
      });
    });
  });

  // Подстановка демонстрационного ответа / варианта решения с подписью происхождения.
  function setAnswer(targetId, text, prov) {
    var ta = document.getElementById(targetId);
    var p = document.getElementById("p_" + targetId);
    var label = document.getElementById("prov_" + targetId);
    if (!ta || !p) return;
    ta.value = text;
    ta.dataset.filled = text;
    p.value = prov;
    if (label) label.textContent = "Происхождение ответа: " + prov;
  }
  Array.prototype.forEach.call(document.querySelectorAll(".demo-fill"), function (btn) {
    btn.addEventListener("click", function () {
      setAnswer(btn.dataset.target, btn.dataset.text, btn.dataset.prov);
      if (btn.dataset.editOld) {
        var eo = document.getElementById("eo_" + btn.dataset.target);
        var en = document.getElementById("en_" + btn.dataset.target);
        var box = document.getElementById("ed_" + btn.dataset.target);
        if (eo && en) { eo.value = btn.dataset.editOld; en.value = btn.dataset.editNew || ""; }
        if (box) box.open = true;
      }
    });
  });
  Array.prototype.forEach.call(document.querySelectorAll(".options input[type=radio]"), function (r) {
    r.addEventListener("change", function () { setAnswer(r.dataset.target, r.dataset.text, r.dataset.prov); });
  });
  Array.prototype.forEach.call(document.querySelectorAll(".question textarea"), function (ta) {
    ta.addEventListener("input", function () {
      var p = document.getElementById("p_" + ta.id);
      var label = document.getElementById("prov_" + ta.id);
      if (!p || !ta.dataset.filled) return;
      if (ta.value !== ta.dataset.filled && p.value.indexOf("изменён аналитиком") < 0) {
        p.value = p.value + ", изменён аналитиком";
        if (label) label.textContent = "Происхождение ответа: " + p.value;
      }
    });
  });

  // Опрос статуса, пока запуск не завершён; по завершении — перерисовка страницы сервером.
  var status = body.dataset.runStatus;
  if (status === "started" || status === "running") {
    var api = body.dataset.api;
    var labels = {};
    var tick = function () {
      fetch(api, { headers: { Accept: "application/json" }, cache: "no-store" })
        .then(function (r) { return r.json(); })
        .then(function (s) {
          if (s.final || s.status !== status) { window.location.reload(); return; }
          var el = document.getElementById("elapsed");
          if (el && s.elapsed_s != null) {
            var t = Math.round(s.elapsed_s);
            el.textContent = t >= 60 ? Math.floor(t / 60) + " мин " + ("0" + (t % 60)).slice(-2) + " с" : s.elapsed_s.toFixed(1) + " с";
          }
          var n = (s.events || []).length;
          if (body.dataset.events && Number(body.dataset.events) !== n) { window.location.reload(); return; }
          body.dataset.events = String(n);
          setTimeout(tick, 1500);
        })
        .catch(function () { setTimeout(tick, 3000); });
    };
    setTimeout(tick, 1000);
  }
})();
