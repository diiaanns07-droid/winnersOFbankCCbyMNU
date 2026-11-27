/* BCC AI — маскот веб-интерфейса (№40). Пиксельный дрон «Review Agent» с титульного слайда команды
 * (docs/design/source/stupits-title-slide.html: makeDrone, палитра DSK). Без зависимостей, без внешних ссылок.
 *
 * Значок или персонаж:
 *   const a = BCCAgent.mount(el, {size: 24, mood: 'idle', tile: false});
 *   a.mood('idle'|'scanning'|'analyzing'|'verified'|'alert'[, мс_до_idle]);
 *   a.say('Одна строка');   // печать ~10 мс на символ, щелчок показывает сразу; → Promise
 *   a.stage('читаю');       // мелкая подпись у дрона
 *   a.destroy();
 *   Автоподключение: [data-bcc-agent] с data-size, data-mood, data-say, data-tile="1" (плитка, как раньше).
 *   Смена атрибутов data-mood / data-say на элементе сразу меняет дрона.
 *
 * Дрон над листом (прогресс проверки = луч сканера сверху вниз по строкам):
 *   const p = BCCAgent.fly(sheetEl, {size: 80});
 *   p.progress(0.4, 'правила');   // 0…1 и подпись этапа
 *   p.say('Читаю раздел 3');
 *   p.land();                     // садится на верхний край листа; на листе — событие 'bcc-agent:landed'
 *   p.takeoff(); p.mood(...); p.destroy();
 *   Без JS-вызовов: <div class="sheet" data-bcc-scan data-progress="0.4" data-stage="правила">,
 *   data-bcc-scan="land" — посадка. data-land="left" — сесть слева (по умолчанию справа, над печатью).
 *
 * Анимация — только пока элемент виден и вкладка открыта; prefers-reduced-motion — статичные кадры. */
(function () {
  'use strict';
  if (window.BCCAgent) return;

  var LITE = !!(window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches);
  var MOODS = ['idle', 'scanning', 'analyzing', 'verified', 'alert'];
  var R = function (a, b) { return a + Math.random() * (b - a); };
  var clamp = function (v, a, b) { return Math.max(a, Math.min(b, v)); };
  var ease = function (k) { return k < .5 ? 4 * k * k * k : 1 - Math.pow(-2 * k + 2, 3) / 2; };

  function sdRoundBox(px, py, cx, cy, bx, by, r) {
    var dx = Math.abs(px - cx) - (bx - r), dy = Math.abs(py - cy) - (by - r);
    return Math.hypot(Math.max(dx, 0), Math.max(dy, 0)) + Math.min(Math.max(dx, dy), 0) - r;
  }
  function sdSeg(px, py, ax, ay, bx, by) {
    var pax = px - ax, pay = py - ay, bax = bx - ax, bay = by - ay;
    var h = clamp((pax * bax + pay * bay) / (bax * bax + bay * bay || 1), 0, 1);
    return Math.hypot(pax - bax * h, pay - bay * h);
  }

  // ── Review Agent: 80×80, палитра DSK — как на слайде ──
  var DSK = {
    shellHi: '#64748B', shellLt: '#475569', shellMid: '#334155', shellSh: '#1E293B', shellDp: '#151E2E',
    bezelHi: '#FFF3C4', bezelLt: '#F2C94C', bezelMid: '#CAA166', bezelSh: '#8F652A',
    armLt: '#94A3B8', armMid: '#64748B', armSh: '#334155', visorBg: '#0E1525', visorInner: '#162138', glint: '#7DD3FC',
    scanCore: '#E4FDE9', scanMid: '#34D36A', scanDim: '#1A6E3B', beamMain: '#34D36A', beamHi: '#A7F3C5',
    eyeCore: '#EEFFF4', eyeHalo: '#34D36A', cheekL: '#34D36A', cheekR: '#F2C94C', lensRing: '#CAA166'
  };
  var DG = 80, DINK = '#121826';
  var CROP = { x: 6, y: 16, w: 68, h: 48 };   // дрон без луча — для значков меньше 48 px

  function makeDrone() {
    var canvas = document.createElement('canvas'); canvas.width = canvas.height = DG;
    var ctx = canvas.getContext('2d'), buf = new Array(DG * DG).fill(null), glow = new Uint8Array(DG * DG), now0 = performance.now();
    var d = { canvas: canvas, cur: '', since: now0, gx: 0, gy: 0, cx: 0, cy: 0, blinkUntil: 0, nextBlink: now0 + 2400, parts: [] };
    var set = function (x, y, c) { x = Math.round(x); y = Math.round(y); if (x >= 0 && x < DG && y >= 0 && y < DG) buf[y * DG + x] = c; };
    var paint = function (m, w, h, ox, oy, col) {
      var x, y;
      for (y = 0; y < h; y++) for (x = 0; x < w; x++) if (!m[y * w + x] && ((x > 0 && m[y * w + x - 1]) || (x < w - 1 && m[y * w + x + 1]) || (y > 0 && m[(y - 1) * w + x]) || (y < h - 1 && m[(y + 1) * w + x]))) set(ox + x, oy + y, DINK);
      for (y = 0; y < h; y++) for (x = 0; x < w; x++) if (m[y * w + x]) set(ox + x, oy + y, col(x, y));
    };
    var layer = function (x0, x1, y0, y1, sd, col) {
      var m = new Uint8Array(DG * DG), x, y, i;
      for (y = y0; y < y1; y++) for (x = x0; x < x1; x++) if (sd(x, y) <= 0) m[y * DG + x] = 1;
      for (y = y0 - 1; y <= y1; y++) for (x = x0 - 1; x <= x1; x++) { i = y * DG + x; if (!m[i] && (m[i - 1] || m[i + 1] || m[i - DG] || m[i + DG])) set(x, y, DINK); }
      for (y = y0; y < y1; y++) for (x = x0; x < x1; x++) if (m[y * DG + x]) set(x, y, col(x, y));
      return m;
    };
    d.sparkles = function (n) {
      var kinds = ['check', 'sparkle', 'gold', 'sparkle'];
      for (var i = 0; i < n; i++) { var a = -Math.PI * .15 - Math.random() * Math.PI * .7, v = 22 + Math.random() * 28; d.parts.push({ k: kinds[i % 4], x: 40 + R(-13, 13), y: 38 + R(-7, 7), vx: Math.cos(a) * v, vy: Math.sin(a) * v - 8, life: R(.75, 1.15), age: 0 }); }
    };
    d.mood = function (m) {
      if (m === d.cur) return;
      d.cur = m; d.since = performance.now(); d.parts.length = 0;
      if (m === 'verified' && !LITE) d.sparkles(7);   // искры один раз
    };
    d.look = function (x, y) { d.gx = clamp(x, -1, 1); d.gy = clamp(y, -1, 1); };
    d.render = function (now, dt, still) {
      var t = now / 1000, st = d.cur, age = (now - d.since) / 1000, x, y, dx, dy, i, lite = LITE || !!still;
      d.cx += (d.gx - d.cx) * .14; d.cy += (d.gy - d.cy) * .14;
      if (now >= d.nextBlink) { d.blinkUntil = now + 130; d.nextBlink = now + R(2300, 4900); }
      var bob = 0, jit = 0;
      if (d.landed) { var sa = now - d.settleT; bob = (!lite && sa >= 0 && sa < 260) ? -Math.round(Math.sin(sa / 260 * Math.PI) * 2) : 0; }
      else if (!lite) {
        if (st === 'scanning') bob = Math.round(Math.sin(t * 4.2) * 1.8);
        else if (st === 'verified' && age < 2.5) bob = -Math.round(Math.abs(Math.sin(t * 4.8)) * 3);
        else if (st === 'alert') { bob = Math.round(Math.sin(t * 14) * 1.4); jit = Math.round(Math.sin(t * 28) * 1.3); }
        else bob = Math.round(Math.sin(t * 2.5) * 1.6);   // дыхание ±2 px, период 2.5 с
      }
      var cx = 40 + jit + Math.round(d.cx * 1.2), by = 40 + bob;
      buf.fill(null);

      // Дизеринг-луч сканера вниз из камеры
      if (st === 'scanning' || st === 'analyzing') {
        var an = st === 'analyzing', bc = an ? '#5ED6FF' : DSK.beamMain, bh = an ? '#E0F7FF' : DSK.beamHi;
        var sway = an ? Math.sin(t * 4.4) * 7.5 : Math.sin(t * 2.5) * 4.5, y0 = by + 19, y1 = 78, sweep = y0 + Math.floor((t * 22) % (y1 - y0));
        for (y = y0; y <= y1; y++) {
          var p = (y - y0) / (y1 - y0), hw = an ? 1.5 + p * 4.5 : 2.2 + p * 13.5, c = cx + sway * p;
          for (x = Math.max(2, Math.floor(c - hw)); x <= Math.min(DG - 3, Math.ceil(c + hw)); x++) {
            var e = Math.abs(x - c) / (hw || 1);
            if (y === sweep && e < .9) { set(x, y, bh); continue; }
            if (p < .28 ? ((x + y) % 2 === 0 || e < .45) : p < .68 ? (x + y) % 2 === 0 : (x % 2 === 0 && y % 2 === 0)) set(x, y, e < .35 && p < .55 ? bh : bc);
          }
        }
      }
      // 4-кадровые двойные верхние роторы
      var frame = (lite || d.landed) ? 0 : Math.floor(t * (st === 'alert' ? 30 : 22)) % 4;
      [-1, 1].forEach(function (side) {
        var ax = cx + side * 15, ay = by - 10, hx = cx + side * 22, hy = by - 19, ox = Math.min(ax, hx) - 4, oy = hy - 3, xx, yy, ddx;
        var am = new Uint8Array(256); for (yy = 0; yy < 16; yy++) for (xx = 0; xx < 16; xx++) if (sdSeg(ox + xx, oy + yy, ax, ay, hx, hy + 2) <= 1.55) am[yy * 16 + xx] = 1;
        paint(am, 16, 16, ox, oy, function (x, y) { return oy + y < hy + 5 ? DSK.armLt : DSK.armMid; });
        var mm = new Uint8Array(72); for (yy = 0; yy < 8; yy++) for (xx = 0; xx < 9; xx++) if (sdRoundBox(xx, yy, 4, 4, 2.4, 2.2, 1.5) <= 0) mm[yy * 9 + xx] = 1;
        paint(mm, 9, 8, hx - 4, hy - 3, function (x, y) { return y <= 2 ? DSK.bezelHi : y === 3 ? DSK.bezelLt : y === 4 ? DSK.bezelMid : DSK.armSh; });
        var bY = hy - 2, f = side < 0 ? frame : (frame + 2) % 4, span = [11, 8, 11, 6][f];
        for (ddx = -span; ddx <= span; ddx++) { var a = Math.abs(ddx); if (a <= 1) continue; if (a % 2 === f % 2) set(hx + ddx, bY - 1, '#334155'); set(hx + ddx, bY, a >= span - 2 ? '#FFFFFF' : a <= 4 ? '#94A3B8' : (ddx + f) % 3 === 0 ? '#E2E8F0' : '#CBD5E1'); }
        if (f % 2) { set(hx - 11, bY, '#94A3B8'); set(hx - 10, bY, '#E2E8F0'); set(hx + 10, bY, '#E2E8F0'); set(hx + 11, bY, '#94A3B8'); }
        else { set(hx - 7, bY + 2, '#64748B'); set(hx + 7, bY + 2, '#64748B'); }
        set(hx - 1, bY - 1, DINK); set(hx, bY - 1, DINK); set(hx + 1, bY - 1, DINK); set(hx - 1, bY, DSK.bezelLt); set(hx, bY, DSK.bezelHi); set(hx + 1, bY, DSK.bezelMid);
      });
      // Корпус, золотая рамка, визор, диоды и нижняя камера
      var lx = cx, ly = by + 15;
      for (dy = -3; dy <= 0; dy++) [DINK, DSK.armSh, DSK.armMid, DSK.armMid, DSK.armLt, DSK.armMid, DSK.armSh, DINK].forEach(function (c, i) { set(lx - 4 + i, ly + dy - 2, c); });
      layer(10, 70, 20, 62, function (x, y) { return sdRoundBox(x, y, cx, by, 21.6, 11.8, 9.6); }, function (x, y) {
        var ry = y - by, rx = x - cx;
        if (ry >= -10.5 && ry <= -9.2 && Math.abs(rx) <= 10.5) return DSK.shellHi;
        return ry <= -8 ? DSK.shellLt : ry >= 9.6 ? DSK.shellDp : (ry >= 6.5 || (rx > 15 && ry > 1)) ? DSK.shellSh : DSK.shellMid;
      });
      [-15, -13, 13, 15].forEach(function (dx) { set(cx + dx, by + 8, DSK.shellDp); set(cx + dx, by + 9, DSK.shellDp); });
      var eY = by - 10;
      set(cx, eY - 1, DSK.bezelHi); set(cx - 1, eY, DSK.bezelLt); set(cx, eY, '#34D36A'); set(cx + 1, eY, DSK.bezelMid);
      set(cx - 2, eY + 1, DSK.bezelMid); set(cx - 1, eY + 1, DSK.bezelLt); set(cx, eY + 1, '#21A049'); set(cx + 1, eY + 1, DSK.bezelMid); set(cx + 2, eY + 1, DSK.bezelSh);
      layer(18, 62, 28, 56, function (x, y) { return sdRoundBox(x, y, cx, by + .5, 16.4, 7.6, 5.2); }, function (x, y) { var ry = y - by, rx = x - cx; return ry <= -5.5 && rx <= 6 ? DSK.bezelHi : ry <= -2 ? DSK.bezelLt : (ry >= 5.5 || rx >= 13) ? DSK.bezelSh : DSK.bezelMid; });
      var vis = layer(20, 60, 30, 54, function (x, y) { return sdRoundBox(x, y, cx, by + .5, 14.3, 5.6, 3.6); }, function (x, y) { return sdRoundBox(x, y, cx, by + .8, 12.2, 3.8, 2.4) <= 0 ? DSK.visorInner : DSK.visorBg; });
      [[cx - 12, by - 2], [cx - 12, by - 3], [cx - 11, by - 4], [cx - 10, by - 4], [cx - 9, by - 4], [cx - 7, by - 4]].forEach(function (q, i) { if (vis[q[1] * DG + q[0]]) set(q[0], q[1], i === 2 || i === 3 ? '#FFFFFF' : DSK.glint); });
      var fast = Math.floor(t * 7) % 2 === 0, slow = Math.floor(t * 2.2) % 2 === 0;
      var cL = DSK.cheekL, cR = DSK.cheekR;
      if (st === 'alert') { cL = fast ? '#FF4D5E' : '#6B1825'; cR = fast ? '#6B1825' : '#FF4D5E'; }
      else if (st === 'verified') cL = cR = '#34D36A';
      else if (st === 'scanning' || st === 'analyzing') { cL = slow ? DSK.cheekL : '#1E293B'; cR = slow ? '#1E293B' : DSK.cheekR; }
      var led = function (x, y, c) { for (var dy = -1; dy <= 2; dy++) for (var dx = -1; dx <= 2; dx++) if (!((dx === -1 || dx === 2) && (dy === -1 || dy === 2))) set(x + dx, y + dy, DINK); set(x, y, c); set(x + 1, y, c); set(x, y + 1, c); set(x + 1, y + 1, c); if (c !== '#1E293B' && c !== '#6B1825') set(x, y, '#FFFFFF'); };
      led(cx - 20, by, cL); led(cx + 19, by, cR);
      var cm = new Uint8Array(169); for (y = 0; y < 13; y++) for (x = 0; x < 13; x++) if (Math.hypot(x - 6, y - 6) <= 4.7) cm[y * 13 + x] = 1;
      paint(cm, 13, 13, lx - 6, ly - 6, function (x, y) { var r = Math.hypot(x - 6, y - 6); return r >= 3.5 ? (y < 5 ? DSK.bezelLt : y > 7 ? DSK.armSh : DSK.lensRing) : r >= 2.6 ? '#1E293B' : '#090E1A'; });
      var px = Math.round(d.cx * 1.6), py = Math.round(d.cy * 1.1);
      if (st === 'scanning') { px = Math.round(Math.sin(t * 2.5) * 1.6); py = 1; } else if (st === 'analyzing') { px = Math.round(Math.sin(t * 4.4) * 1.8); py = 1; }
      set(lx + px, ly + py, st === 'alert' ? '#FF4D5E' : st === 'analyzing' ? '#5ED6FF' : DSK.scanMid); set(lx + px - 1, ly + py - 1, '#FFFFFF');

      // Выражение внутри визора
      var vy = by + 1; glow.fill(0);
      var vp = function (x, y, c) { x = Math.round(x); y = Math.round(y); if (x >= 0 && x < DG && y >= 0 && y < DG && vis[y * DG + x]) set(x, y, c); };
      var gp = function (x, y) { x = Math.round(x); y = Math.round(y); if (x >= 0 && x < DG && y >= 0 && y < DG && vis[y * DG + x]) glow[y * DG + x] = 1; };
      var flush = function (core, halo) {
        var x, y, i;
        for (y = 30; y < 54; y++) for (x = 20; x < 60; x++) { i = y * DG + x; if (vis[i] && !glow[i] && (glow[i - 1] || glow[i + 1] || glow[i - DG] || glow[i + DG])) set(x, y, halo); }
        for (y = 30; y < 54; y++) for (x = 20; x < 60; x++) if (glow[y * DG + x]) set(x, y, core);
      };
      if (st === 'scanning') {
        var pos = Math.sin(t * 2.75), dir = Math.cos(t * 2.75) >= 0 ? 1 : -1, hx = Math.round(cx + pos * 10);
        for (x = cx - 11; x <= cx + 11; x += 2) vp(x, vy, '#1E2D4A');
        for (var s = 3; s >= 1; s--) { var tx = hx - dir * s * 3, sc = s === 1 ? DSK.scanMid : s === 2 ? DSK.scanDim : '#241E36', hh = s === 1 ? 2 : 1; for (dy = -hh; dy <= hh; dy++) for (dx = -1; dx <= 1; dx++) vp(tx + dx, vy + dy, sc); }
        for (dy = -2; dy <= 2; dy++) for (dx = -2; dx <= 2; dx++) if (!(Math.abs(dx) === 2 && Math.abs(dy) === 2)) vp(hx + dx, vy + dy, Math.abs(dx) <= 1 && Math.abs(dy) <= 1 ? DSK.scanCore : DSK.scanMid);
        var on = Math.floor(t * 6) % 2 === 0; vp(cx - 12, vy + 3, on ? DSK.scanMid : '#1E2D4A'); vp(cx + 12, vy + 3, on ? '#1E2D4A' : DSK.scanMid);
        var pp = Math.floor(t * 4) % 2, rc2 = pp ? '#475569' : DSK.scanMid, o = 25 + pp;
        [-1, 1].forEach(function (s) { set(cx + s * o, by - 2, rc2); set(cx + s * (o + 1), by - 1, rc2); set(cx + s * (o + 1), by, rc2); set(cx + s * (o + 1), by + 1, rc2); set(cx + s * o, by + 2, rc2); });
      } else if (st === 'verified') {
        if (lite || Math.floor(t * .9) % 2 === 1) [[-5, 0], [-4, 1], [-3, 2], [-2, 3], [-1, 2], [0, 1], [1, 0], [2, -1], [3, -2], [4, -3], [5, -3]].forEach(function (q) { gp(cx + q[0], vy + q[1]); gp(cx + q[0], vy + q[1] + 1); });
        else { [[-3, 1], [-2, 0], [-1, -1], [0, -1], [1, -1], [2, 0], [3, 1]].forEach(function (q) { gp(cx - 7 + q[0], vy - 1 + q[1]); gp(cx - 7 + q[0], vy + q[1]); gp(cx + 7 + q[0], vy - 1 + q[1]); gp(cx + 7 + q[0], vy + q[1]); }); gp(cx - 2, vy + 2); gp(cx + 2, vy + 2); gp(cx - 1, vy + 3); gp(cx, vy + 3); gp(cx + 1, vy + 3); }
        flush('#EEFFF4', '#34D36A');
      } else if (st === 'analyzing') {
        var lk = Math.round(Math.sin(t * 3.2) * 1.5);
        for (dy = -1; dy <= 1; dy++) for (dx = -1; dx <= 1; dx++) { gp(cx - 9 + lk + dx, vy - 1 + dy); gp(cx - 3 + lk + dx, vy - 1 + dy); }
        for (dx = -2; dx <= 2; dx++) gp(cx - 6 + lk + dx, vy + 3);
        for (i = 0; i < 5; i++) { var bx = cx + 3 + i * 2, h = 1 + Math.round((Math.sin(t * 8 + i * 1.3) + 1) * 1.8); for (dy = 0; dy < h; dy++) vp(bx, vy + 2 - dy, dy === h - 1 ? '#F2C94C' : '#5ED6FF'); }
        flush('#F2FEFF', '#38BDF8');
      } else if (st === 'alert') {
        if (Math.floor(t * 2.2) % 2 === 1) { for (dy = -3; dy <= 0; dy++) { gp(cx, vy + dy); gp(cx - 1, vy + dy); } gp(cx, vy + 2); gp(cx - 1, vy + 2); gp(cx, vy + 3); gp(cx - 1, vy + 3); [-7, 6].forEach(function (o) { for (var dy = -2; dy <= 2; dy++) gp(cx + o, vy + dy); }); }
        else { [[-2, -2], [-1, -1], [0, 0], [-1, 1], [-2, 2]].forEach(function (q) { gp(cx - 6 + q[0], vy + q[1]); gp(cx - 5 + q[0], vy + q[1]); gp(cx + 6 - q[0], vy + q[1]); gp(cx + 5 - q[0], vy + q[1]); }); gp(cx - 1, vy + 2); gp(cx, vy + 2); gp(cx + 1, vy + 2); }
        flush('#FFF1F2', '#FF4D5E');
      } else {
        var dlx = Math.round(d.cx * 2.4), dly = Math.round(d.cy * 1.2), m0 = Math.min(0, dly);
        if ((!LITE || still) && now < d.blinkUntil) { for (dx = -2; dx <= 2; dx++) { gp(cx - 6 + dlx + dx, vy + dly); gp(cx + 6 + dlx + dx, vy + dly); } }
        else { [cx - 6 + dlx, cx + 6 + dlx].forEach(function (ex) { for (var dy = -3; dy <= 3; dy++) for (var dx = -2; dx <= 2; dx++) if (!(Math.abs(dx) === 2 && Math.abs(dy) === 3) && !(dx === 0 && Math.abs(dy) <= 1)) gp(ex + dx, vy - 1 + dly + dy); }); }
        gp(cx + dlx - 2, vy + 2 + m0); gp(cx + dlx + 2, vy + 2 + m0); gp(cx + dlx - 1, vy + 3 + m0); gp(cx + dlx, vy + 3 + m0); gp(cx + dlx + 1, vy + 3 + m0);
        flush(DSK.eyeCore, DSK.eyeHalo);
      }
      for (i = d.parts.length - 1; i >= 0; i--) {
        var q = d.parts[i]; q.age += dt; if (q.age >= q.life) { d.parts.splice(i, 1); continue; }
        q.vy += 46 * dt; q.x += q.vx * dt; q.y += q.vy * dt; x = Math.round(q.x); y = Math.round(q.y);
        if (q.k === 'check') { set(x - 1, y, '#34D36A'); set(x, y + 1, '#E4FDE9'); set(x + 1, y, '#34D36A'); set(x + 2, y - 1, '#34D36A'); }
        else { var pc = q.k === 'gold' ? '#F2C94C' : '#34D36A'; set(x, y, '#FFFFFF'); set(x - 1, y, pc); set(x + 1, y, pc); set(x, y - 1, pc); set(x, y + 1, pc); }
      }
      ctx.clearRect(0, 0, DG, DG);
      for (y = 0; y < DG; y++) for (x = 0; x < DG;) { var col = buf[y * DG + x]; if (!col) { x++; continue; } var n = 1; while (x + n < DG && buf[y * DG + x + n] === col) n++; ctx.fillStyle = col; ctx.fillRect(x, y, n, 1); x += n; }
      return buf;
    };
    d.mood('idle');
    return d;
  }


  // ── Общий цикл: один requestAnimationFrame на все видимые экземпляры ──
  var agents = [], pilots = [], raf = 0, last = 0, mouse = null;
  var io = 'IntersectionObserver' in window ? new IntersectionObserver(function (es) {
    es.forEach(function (en) { var a = en.target.__bccAgent, p = en.target.__bccPilot; if (a) a._visible = en.isIntersecting; if (p) p._visible = en.isIntersecting; });
    kick();
  }) : null;

  function node(tag, cls) { var n = document.createElement(tag); if (cls) n.className = cls; return n; }

  function lookAt(drone, rect) {
    if (!mouse) return;
    var k = Math.max(240, rect.width * 2.5);
    drone.look((mouse.x - (rect.left + rect.width / 2)) / k, (mouse.y - (rect.top + rect.height / 2)) / k);
  }

  function paint(cv, g, drone, now, dt, crop, still) {
    drone.render(now, dt, still);
    g.clearRect(0, 0, cv.width, cv.height);
    if (crop) {
      g.imageSmoothingEnabled = true; g.imageSmoothingQuality = 'high';
      var s = Math.min(cv.width / CROP.w, cv.height / CROP.h), w = CROP.w * s, h = CROP.h * s;
      g.drawImage(drone.canvas, CROP.x, CROP.y, CROP.w, CROP.h, (cv.width - w) / 2, (cv.height - h) / 2, w, h);
    } else {
      g.imageSmoothingEnabled = false;
      g.drawImage(drone.canvas, 0, 0, cv.width, cv.height);
    }
  }

  // Размер холста: крупный дрон — целое число пикселей сетки на экранный пиксель (чётко на 1× и 2×)
  function backing(size, crop, tile) {
    var dpr = window.devicePixelRatio || 1;
    if (crop || tile) return { px: Math.max(16, Math.round(size * dpr)), css: size };
    var k = Math.max(1, Math.round(size * dpr / DG));
    return { px: DG * k, css: DG * k / dpr };
  }

  function active(list) { return document.hidden ? [] : list.filter(function (a) { return a._visible; }); }

  function tick(now) {
    raf = 0;
    var dt = last ? Math.min(.05, (now - last) / 1000) : .016; last = now;
    var la = active(agents), lp = active(pilots);
    la.forEach(function (a) { if (a._mood === 'idle') lookAt(a._drone, a._box.getBoundingClientRect()); a._draw(now, dt); });
    lp.forEach(function (p) { p._step(now, dt); });
    if ((la.length || lp.length) && !LITE) raf = requestAnimationFrame(tick);
    else last = 0;
  }
  function kick() { if (!raf && !LITE) raf = requestAnimationFrame(tick); }

  document.addEventListener('visibilitychange', function () { if (!document.hidden) kick(); });
  window.addEventListener('pointermove', function (ev) { mouse = { x: ev.clientX, y: ev.clientY }; }, { passive: true });

  // Реплика одной строкой: печать ~10 мс на символ, щелчок — сразу целиком
  function typer(el) {
    var timer = 0, finish = null;
    el.addEventListener('click', function () { if (finish) finish(); });
    return function (text) {
      text = String(text == null ? '' : text);
      if (finish) finish();
      clearInterval(timer);
      el.hidden = !text;
      return new Promise(function (resolve) {
        var shown = 0, t0 = performance.now();
        finish = function () { clearInterval(timer); el.textContent = text; el.classList.remove('is-typing'); finish = null; resolve(); };
        if (LITE || !text) return finish();
        el.textContent = ''; el.classList.add('is-typing');
        timer = setInterval(function () {
          var n = Math.min(text.length, Math.floor((performance.now() - t0) / 10) + 1);
          if (n !== shown) { shown = n; el.textContent = text.slice(0, n); }
          if (n >= text.length) finish();
        }, 16);
      });
    };
  }

  // ── Значок / персонаж ──
  function mount(el, opts) {
    if (!el) return null;
    if (el.__bccAgent) return el.__bccAgent;
    opts = opts || {};
    var size = +(opts.size || el.getAttribute('data-size') || 96);
    var tile = opts.tile != null ? !!opts.tile : el.getAttribute('data-tile') === '1';
    var crop = !tile && size < 48;
    var b = backing(size, crop, tile);
    el.classList.add('bcc-agent');
    if (tile) el.classList.add('bcc-agent--tile');
    if (size < 48) el.classList.add('bcc-agent--small');
    el.style.setProperty('--bcc-agent-size', b.css + 'px');
    var box = node('span', 'bcc-agent__box'), cv = node('canvas', 'bcc-agent__cv');
    cv.width = cv.height = b.px;
    cv.setAttribute('role', 'img');
    cv.setAttribute('aria-label', 'BCC AI');
    box.appendChild(cv);
    el.appendChild(box);
    var talk = null, sayEl = null, stageEl = null, typeSay = null;
    function ensureTalk() {
      if (talk) return;
      talk = node('span', 'bcc-agent__talk');
      sayEl = node('span', 'bcc-agent__say'); sayEl.setAttribute('aria-live', 'polite'); sayEl.hidden = true;
      stageEl = node('span', 'bcc-agent__stage'); stageEl.hidden = true;
      talk.appendChild(stageEl); talk.appendChild(sayEl);
      el.appendChild(talk);
      typeSay = typer(sayEl);
    }
    var a = {
      el: el, size: b.css, _box: box, _drone: makeDrone(), _visible: !io, _mood: '', _said: null, _moodT: 0,
      _draw: function (now, dt, still) { paint(cv, cv.getContext('2d'), a._drone, now, dt, crop, still); },
      mood: function (name, ms) {
        if (MOODS.indexOf(name) < 0) name = 'idle';
        clearTimeout(a._moodT);
        a._mood = name;
        a._drone.mood(name);
        if (el.getAttribute('data-mood') !== name) el.setAttribute('data-mood', name);
        if (ms > 0) a._moodT = setTimeout(function () { a.mood('idle'); }, ms);
        if (LITE) a._draw(1200, 0, true); else kick();
        return a;
      },
      say: function (text) { ensureTalk(); a._said = text == null ? '' : String(text); return typeSay(a._said); },
      stage: function (text) { ensureTalk(); stageEl.textContent = text || ''; stageEl.hidden = !text; return a; },
      destroy: function () {
        clearTimeout(a._moodT);
        if (io) io.unobserve(el);
        agents = agents.filter(function (x) { return x !== a; });
        if (box.parentNode) box.parentNode.removeChild(box);
        if (talk && talk.parentNode) talk.parentNode.removeChild(talk);
        el.classList.remove('bcc-agent', 'bcc-agent--tile', 'bcc-agent--small');
        delete el.__bccAgent;
      }
    };
    el.__bccAgent = a;
    agents.push(a);
    if (io) io.observe(el);
    a.mood(opts.mood || el.getAttribute('data-mood') || 'idle');
    a._draw(1200, 0, true);
    var say0 = opts.say || el.getAttribute('data-say');
    if (say0) a.say(say0);
    return a;
  }

  // ── Дрон над листом: луч сканера по строкам, посадка на край ──
  function fly(sheet, opts) {
    if (!sheet) return null;
    if (sheet.__bccPilot) return sheet.__bccPilot;
    opts = opts || {};
    if (getComputedStyle(sheet).position === 'static') sheet.style.position = 'relative';
    var b = backing(+(opts.size || sheet.getAttribute('data-size') || 80), false, false), S = b.css;
    var layer = node('div', 'bcc-pilot'), wash = node('div', 'bcc-pilot__wash'), line = node('div', 'bcc-pilot__line');
    var craft = node('div', 'bcc-pilot__craft'), cv = node('canvas', 'bcc-pilot__cv');
    var talk = node('div', 'bcc-pilot__talk'), sayEl = node('span', 'bcc-agent__say'), stageEl = node('span', 'bcc-agent__stage');
    cv.width = cv.height = b.px;
    cv.setAttribute('role', 'img'); cv.setAttribute('aria-label', 'BCC AI');
    sayEl.setAttribute('aria-live', 'polite'); sayEl.hidden = true; stageEl.hidden = true;
    craft.style.width = craft.style.height = S + 'px';
    talk.appendChild(stageEl); talk.appendChild(sayEl);
    craft.appendChild(cv); craft.appendChild(talk);
    layer.appendChild(wash); layer.appendChild(line); layer.appendChild(craft);
    sheet.appendChild(layer);
    var g = cv.getContext('2d'), typeSay = typer(sayEl);
    var side = opts.land || sheet.getAttribute('data-land') || 'right';
    var p = {
      sheet: sheet, size: S, _drone: makeDrone(), _visible: !io, state: 'scan', prog: 0, target: 0, focusEl: null,
      x: null, y: null, ly: null, x0: 0, y0: 0, t0: 0, dur: 900, _said: null,
      bottomInset: opts.bottomInset != null ? +opts.bottomInset : 96,
      _spot: function (W) { return { x: side === 'left' ? 28 : W - S - 40, y: -Math.round(S * 61 / 80) }; },
      _step: function (now, dt, still) {
        var r = sheet.getBoundingClientRect(), W = r.width, H = r.height, tt = now / 1000;
        var vt = clamp(-r.top + 12, 0, H), vb = clamp(window.innerHeight - r.top - p.bottomInset, 0, H);
        if (vb - vt < 180) { vt = 0; vb = H; }
        if (p.state === 'scan') {
          var ty;
          if (p.focusEl && p.focusEl.isConnected) ty = p.focusEl.getBoundingClientRect().bottom - r.top + 4;
          else ty = vt + 36 + p.target * Math.max(0, vb - vt - 72);
          p.ly = (still || p.ly == null) ? ty : p.ly + (ty - p.ly) * Math.min(1, dt * 3);
          var ly = p.ly;
          var padL = Math.min(72, W * .12), padR = Math.min(48, W * .08), span = Math.max(0, W - padL - padR - S);
          var cx = padL + S / 2 + (still ? .5 : .5 + .5 * Math.sin(tt * .7)) * span;
          p.x = cx - S / 2; p.y = ly - S * 78 / 80;
          line.style.transform = 'translate3d(0,' + ly.toFixed(1) + 'px,0)';
          wash.style.transform = 'translate3d(0,' + (ly - 40).toFixed(1) + 'px,0)';
        } else if (p.state === 'landing') {
          var s = p._spot(W), k = still ? 1 : clamp((now - p.t0) / p.dur, 0, 1), e = ease(k);
          p.x = p.x0 + (s.x - p.x0) * e; p.y = p.y0 + (s.y - p.y0) * e - Math.sin(k * Math.PI) * 28;
          if (k >= 1) {
            p.state = 'landed'; p._drone.landed = true; p._drone.settleT = now;
            layer.classList.add('is-landed');
            sheet.setAttribute('data-bcc-landed', '');
            try { sheet.dispatchEvent(new CustomEvent('bcc-agent:landed', { bubbles: true })); } catch (e2) { /* старый браузер */ }
          }
        } else {
          var s2 = p._spot(W); p.x = s2.x; p.y = s2.y;
        }
        var left = p.x + S + 300 > W && p.x > 160;
        talk.classList.toggle('is-left', left);
        talk.style.maxWidth = Math.max(140, Math.min(460, left ? p.x - 8 : W - p.x - S - 8)) + 'px';
        craft.style.transform = 'translate3d(' + p.x.toFixed(1) + 'px,' + p.y.toFixed(1) + 'px,0)';
        if (p.state === 'landed' && p._drone.cur === 'idle') lookAt(p._drone, cv.getBoundingClientRect());
        paint(cv, g, p._drone, now, dt, false, still);
      },
      _refresh: function () { if (LITE) p._step(1200, 0, true); else kick(); },
      progress: function (v, stage) {
        if (v && v.nodeType === 1) { p.focusEl = v; } else { p.focusEl = null; p.target = clamp(+v || 0, 0, 1); }
        if (stage != null) p.stage(stage);
        if (p.state !== 'scan') p.takeoff();
        p._refresh();
        return p;
      },
      stage: function (text) { stageEl.textContent = text || ''; stageEl.hidden = !text; return p; },
      say: function (text) { p._said = text == null ? '' : String(text); return typeSay(p._said); },
      mood: function (m) { p._drone.mood(MOODS.indexOf(m) < 0 ? 'idle' : m); p._refresh(); return p; },
      land: function () {
        if (p.state !== 'scan') return p;
        p.state = 'landing'; p.t0 = performance.now(); p.x0 = p.x || 0; p.y0 = p.y || 0;
        p._drone.mood('idle'); p.stage('');
        p._refresh();
        return p;
      },
      takeoff: function () {
        p.state = 'scan'; p._drone.landed = false; p._drone.mood('scanning');
        layer.classList.remove('is-landed'); sheet.removeAttribute('data-bcc-landed');
        p._refresh();
        return p;
      },
      destroy: function () {
        if (io) io.unobserve(sheet);
        pilots = pilots.filter(function (x) { return x !== p; });
        if (layer.parentNode) layer.parentNode.removeChild(layer);
        delete sheet.__bccPilot;
      }
    };
    sheet.__bccPilot = p;
    pilots.push(p);
    if (io) io.observe(sheet);
    p._drone.mood(opts.mood || 'scanning');
    p._step(1200, 0, true);
    p._refresh();
    return p;
  }

  // ── Декларативно: атрибуты на странице управляют дроном ──
  function sync(el) {
    if (el.hasAttribute('data-bcc-agent')) {
      var a = mount(el), m = el.getAttribute('data-mood'), s = el.getAttribute('data-say');
      if (m && m !== a._mood) a.mood(m);
      if (s != null && s !== a._said) a.say(s);
    }
    if (el.hasAttribute('data-bcc-scan')) {
      var p = fly(el), v = el.getAttribute('data-bcc-scan'), st = el.getAttribute('data-stage'), sy = el.getAttribute('data-say');
      if (el.hasAttribute('data-progress') && v !== 'land' && v !== 'done') p.progress(parseFloat(el.getAttribute('data-progress')) || 0);
      if (st != null) p.stage(st);
      if (sy != null && sy !== p._said) p.say(sy);
      if (el.hasAttribute('data-mood') && p.state === 'scan') p.mood(el.getAttribute('data-mood'));
      if (v === 'land' || v === 'done') p.land();
    }
  }
  function mountAll(root) {
    (root || document).querySelectorAll('[data-bcc-agent],[data-bcc-scan]').forEach(sync);
  }

  window.addEventListener('resize', function () { agents.forEach(function (a) { a._draw(1200, 0, true); }); pilots.forEach(function (p) { p._refresh(); }); });
  window.addEventListener('scroll', function () { if (LITE) pilots.forEach(function (p) { p._refresh(); }); }, { passive: true });

  // Статичный кадр для терминала и тестов: массив 80×80 цветов (null — прозрачно)
  function pixels(mood, o) {
    o = o || {};
    var d = makeDrone(); d.mood(mood || 'idle'); d.parts.length = 0;
    d.cx = d.gx = o.gx || 0; d.cy = d.gy = o.gy || 0; d.nextBlink = Infinity; d.blinkUntil = o.blink ? Infinity : 0;
    return d.render((o.t == null ? 1.2 : o.t) * 1000, 0, true).slice();
  }

  window.BCCAgent = { mount: mount, fly: fly, mountAll: mountAll, moods: MOODS.slice(), reducedMotion: LITE, _pixels: pixels };

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', function () { mountAll(); });
  else mountAll();
  if ('MutationObserver' in window) {
    new MutationObserver(function (ms) {
      ms.forEach(function (m) {
        if (m.type === 'attributes') { if (m.target.nodeType === 1) sync(m.target); return; }
        m.addedNodes.forEach(function (n) {
          if (n.nodeType !== 1 || (n.classList && (n.classList.contains('bcc-pilot') || n.classList.contains('bcc-agent__box')))) return;
          if (n.hasAttribute('data-bcc-agent') || n.hasAttribute('data-bcc-scan')) sync(n);
          if (n.querySelectorAll) mountAll(n);
        });
      });
    }).observe(document.documentElement, { childList: true, subtree: true, attributes: true,
      attributeFilter: ['data-mood', 'data-say', 'data-progress', 'data-stage', 'data-bcc-scan'] });
  }
})();
