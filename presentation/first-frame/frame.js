// Показ кадров: ?frame=a | b | all, стрелки ← → и клавиши A / B. ?export — окно ровно 1920×1080 без масштаба.
(function () {
  var params = new URLSearchParams(location.search);
  var deck = document.querySelector(".deck");
  var stages = Array.prototype.slice.call(document.querySelectorAll(".stage"));
  var order = ["a", "b"];

  if (params.has("export")) document.documentElement.classList.add("export");

  // Логотип не найден → видимое место под официальный файл, без подделки знака.
  document.querySelectorAll("img[data-logo]").forEach(function (img) {
    function slot() {
      var s = document.createElement("span");
      s.className = "logo-slot";
      s.setAttribute("data-missing-logo", img.getAttribute("src"));
      s.innerHTML = "<b></b><span></span>";
      s.firstChild.textContent = img.getAttribute("data-logo");
      s.lastChild.textContent = img.getAttribute("src").split("/").pop();
      img.replaceWith(s);
    }
    if (img.complete && img.naturalWidth === 0) slot();
    else img.addEventListener("error", slot);
  });

  function show(id) {
    deck.setAttribute("data-frame", id);
    if (id !== "all" && history.replaceState) {
      params.set("frame", id);
      history.replaceState(null, "", "?" + params.toString());
    }
    fit();
  }

  function fit() {
    if (document.documentElement.classList.contains("export")) return;
    var all = deck.getAttribute("data-frame") === "all";
    var w = window.innerWidth, h = window.innerHeight;
    var k = all ? Math.min(w / (1920 * 2 + 80), h / 1080) : Math.min(w / 1920, h / 1080);
    stages.forEach(function (s, i) {
      s.style.setProperty("--fit", k);
      s.style.translate = all ? ((i === 0 ? -1 : 1) * (1920 + 80) / 2 * k) + "px 0" : "";
    });
  }

  document.addEventListener("keydown", function (e) {
    var cur = deck.getAttribute("data-frame");
    var i = order.indexOf(cur);
    if (e.key === "ArrowRight" || e.key === "PageDown" || e.key === " ") show(order[Math.min(i + 1, 1)] || "a");
    else if (e.key === "ArrowLeft" || e.key === "PageUp") show(order[Math.max(i - 1, 0)] || "a");
    else if (e.key === "a" || e.key === "ф") show("a");
    else if (e.key === "b" || e.key === "и") show("b");
  });
  window.addEventListener("resize", fit);

  var f = (params.get("frame") || "a").toLowerCase();
  show(order.indexOf(f) >= 0 || f === "all" ? f : "a");
})();
