/* BCC AI — маскот веб-интерфейса (№40). Пиксельный персонаж AIshka с титульного слайда команды
 * (docs/design/source/stupits-title-slide.html: makePixelBot, палитра PAL, основа PBASE, сетка 96×96):
 * светлый треугольный корпус BCC с золотом, значок с зелёной точкой, циановое лицо, румянец. Стоит прямо на светлом
 * фоне, под ним мягкая тень; плитки нет. Без зависимостей и внешних ссылок.
 *
 * Значок или персонаж (размер кратен сетке: 192 — знакомство, 96 — над листом, 48 — шапка, на 2× это 96 точек):
 *   const a = BCCAgent.mount(el, {size: 96, mood: 'idle'});
 *   a.mood('idle'|'happy'|'work'|'ready'|'oops'|'speak'[, мс_до_idle]);
 *     прежние имена тоже понимает: scanning, analyzing → work; verified → happy; alert → oops
 *   a.say('Одна строка');   // печать ~10 мс на символ (пока печатает — говорит), щелчок показывает сразу; → Promise
 *   a.stage('читаю');       // мелкая подпись рядом
 *   a.destroy();
 *   Автоподключение: [data-bcc-agent] с data-size, data-mood, data-say. Смена data-mood / data-say сразу меняет его.
 *
 * Над листом (прогресс проверки = тонкий бледно-зелёный луч по строкам, AIshka в настроении work плывёт вдоль него):
 *   const p = BCCAgent.fly(sheetEl, {size: 96});
 *   p.progress(0.4, 'правила');   // 0…1 (или элемент листа) и подпись этапа
 *   p.say('Читаю раздел 3');
 *   p.land();                     // встаёт на верхний край листа; на листе — событие 'bcc-agent:landed'
 *   p.takeoff(); p.mood(...); p.destroy();
 *   Без JS: <div class="sheet" data-bcc-scan data-progress="0.4" data-stage="правила">, data-bcc-scan="land" — встать
 *   на край; data-land="left" — слева (по умолчанию справа).
 *
 * Анимация — только пока элемент виден и вкладка открыта; prefers-reduced-motion — статичные кадры. */
(function () {
  'use strict';
  if (window.BCCAgent) return;

  var LITE = !!(window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches);
  var MOODS = ['idle', 'happy', 'work', 'ready', 'oops', 'speak'];
  var ALIAS = { scanning: 'work', analyzing: 'work', verified: 'happy', alert: 'oops' };
  var real = function (m) { m = ALIAS[m] || m; return MOODS.indexOf(m) < 0 ? 'idle' : m; };
  var R = function (a, b) { return a + Math.random() * (b - a); };
  var clamp = function (v, a, b) { return Math.max(a, Math.min(b, v)); };
  var ease = function (k) { return k < .5 ? 4 * k * k * k : 1 - Math.pow(-2 * k + 2, 3) / 2; };

  function sdRoundBox(px, py, cx, cy, bx, by, r) {
    const dx = Math.abs(px - cx) - (bx - r), dy = Math.abs(py - cy) - (by - r);
    return Math.hypot(Math.max(dx, 0), Math.max(dy, 0)) + Math.min(Math.max(dx, dy), 0) - r;
  }
  function sdTri(px, py, ax, ay, bx, by, cx, cy) {
    const e0x = bx - ax, e0y = by - ay, e1x = cx - bx, e1y = cy - by, e2x = ax - cx, e2y = ay - cy;
    const v0x = px - ax, v0y = py - ay, v1x = px - bx, v1y = py - by, v2x = px - cx, v2y = py - cy;
    const t0 = clamp((v0x * e0x + v0y * e0y) / (e0x * e0x + e0y * e0y), 0, 1);
    const t1 = clamp((v1x * e1x + v1y * e1y) / (e1x * e1x + e1y * e1y), 0, 1);
    const t2 = clamp((v2x * e2x + v2y * e2y) / (e2x * e2x + e2y * e2y), 0, 1);
    const q0x = v0x - e0x * t0, q0y = v0y - e0y * t0, q1x = v1x - e1x * t1, q1y = v1y - e1y * t1, q2x = v2x - e2x * t2, q2y = v2y - e2y * t2;
    const s = Math.sign(e0x * e2y - e0y * e2x);
    return -Math.sqrt(Math.min(q0x * q0x + q0y * q0y, q1x * q1x + q1y * q1y, q2x * q2x + q2y * q2y)) *
      Math.sign(Math.min(s * (v0x * e0y - v0y * e0x), s * (v1x * e1y - v1y * e1x), s * (v2x * e2y - v2y * e2x)));
  }

  // ── AIshka: 96×96, палитра и основа — как на слайде ──
  const PAL = {
    INK: '#161E31', GLASS: '#1F2E4A', WHITE: '#FFFFFF', SHELL_SH: '#DCE7F2', SHELL_DP: '#B9CBE0',
    GOLD: '#CAA166', GOLD_LT: '#E6BD74', GOLD_HI: '#FFF3C4', GOLD_SH: '#9C7136',
    GREEN: '#21A049', GREEN_BR: '#34D36A', GREEN_HI: '#E4FDE9',
    CORE: '#F2FEFF', HALO: '#5ED6FF', GLINT: '#9EEBFF', BLUSH: '#F58DA8'
  };
  const PG = 96, PCX = 48, PBY = 56, PEAR = 27, PEARY = PBY + 9;
  const CROP = { x: 14, y: 4, w: 68, h: 80 };   // персонаж без пустых полей — для значков меньше 48 px
  const FOOT = 82 / PG;                          // низ корпуса: здесь он стоит на краю листа
  const PBASE = (() => {
    const buf = new Array(PG * PG).fill(null), cx = PCX, by = PBY;
    const set = (x, y, c) => { x = Math.round(x); y = Math.round(y); if (x >= 0 && x < PG && y >= 0 && y < PG) buf[y * PG + x] = c; };
    const stamp = (w, h, ox, oy, test, sh) => {
      const m = new Uint8Array(w * h);
      for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) if (test(x, y)) m[y * w + x] = 1;
      for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) if (!m[y * w + x] && ((x > 0 && m[y * w + x - 1]) || (x < w - 1 && m[y * w + x + 1]) || (y > 0 && m[(y - 1) * w + x]) || (y < h - 1 && m[(y + 1) * w + x]))) set(ox + x, oy + y, PAL.INK);
      for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) if (m[y * w + x]) set(ox + x, oy + y, sh(x, y, { isTop: y === 0 || !m[(y - 1) * w + x], isLeft: x === 0 || !m[y * w + x - 1], isBottom: y === h - 1 || !m[(y + 1) * w + x], isRight: x === w - 1 || !m[y * w + x + 1] }));
    };
    const layer = (sd, col) => {
      const m = new Uint8Array(PG * PG), D = new Float32Array(PG * PG);
      for (let y = 0; y < PG; y++) for (let x = 0; x < PG; x++) { const i = y * PG + x; D[i] = sd(x, y); if (D[i] <= 0) m[i] = 1; }
      for (let y = 1; y < PG - 1; y++) for (let x = 1; x < PG - 1; x++) { const i = y * PG + x; if (!m[i] && (m[i - 1] || m[i + 1] || m[i - PG] || m[i + PG])) set(x, y, PAL.INK); }
      for (let y = 0; y < PG; y++) for (let x = 0; x < PG; x++) { const i = y * PG + x; if (m[i]) set(x, y, col(x, y, D[i])); }
      return m;
    };
    const crest = by - 29;
    for (let dy = -3; dy <= 1; dy++) { set(cx - 2, crest + dy, PAL.INK); set(cx - 1, crest + dy, PAL.WHITE); set(cx, crest + dy, PAL.WHITE); set(cx + 1, crest + dy, PAL.SHELL_SH); set(cx + 2, crest + dy, PAL.INK); }
    stamp(23, 20, Math.round(cx - 11.5), crest - 19, (x, y) => {
      const o = sdTri(x, y, 11, 4.5, 4.2, 15.2, 17.8, 15.2) - 2.3, i = sdTri(x, y, 12.2, 9.2, 9.2, 13.8, 15.2, 13.8) - 1.25;
      return (o <= 0 && o >= -2.15) || (i <= 0 && i >= -1.65);
    }, (x, y, e) => e.isTop && y < 12 ? PAL.GOLD_HI : (e.isBottom || (e.isRight && y > 10)) ? PAL.GOLD_SH : (y < 9 || e.isLeft) ? PAL.GOLD_LT : PAL.GOLD);
    set(cx, crest - 1, PAL.GREEN_BR);
    for (const side of [-1, 1]) stamp(11, 21, Math.round(cx + side * PEAR - 5), PEARY - 10, (x, y) => sdRoundBox(x, y, 5, 10, 3.6, 7.6, 3.2) <= 0, (x, y, e) => y <= 5 ? PAL.GOLD_HI : y <= 9 ? PAL.GOLD_LT : (y >= 14 || e.isBottom) ? PAL.GOLD_SH : PAL.GOLD);
    layer((x, y) => sdTri(x, y, cx, by - 15.5, cx - 18.2, by + 11.2, cx + 18.2, by + 11.2) - 13, (x, y, d) => ((x > cx + 12 && d > -2.2) || (y > by + 18 && d > -1.7)) ? PAL.SHELL_DP : ((x > cx + 6 && d > -4.2) || (y > by + 14 && d > -2.8)) ? PAL.SHELL_SH : PAL.WHITE);
    [PAL.SHELL_DP, PAL.GREEN, PAL.GREEN_BR, PAL.GREEN, PAL.SHELL_DP].forEach((c, i) => set(cx - 2 + i, by + 23, c));
    layer((x, y) => sdTri(x, y, cx, by - 11.2, cx - 16, by + 11.2, cx + 16, by + 11.2) - 10.2, (x, y, d) => {
      const ry = y - by, rx = x - cx;
      if (rx < -4 && ry < -5 && d > -2) return PAL.GOLD_HI;
      return ry < -11 && d > -2.5 ? PAL.GOLD_HI : ry < 2 && rx < 10 ? PAL.GOLD_LT : (ry > 14 || (rx > 14 && ry > 4)) ? PAL.GOLD_SH : PAL.GOLD;
    });
    const scr = layer((x, y) => sdTri(x, y, cx, by - 9.2, cx - 15.2, by + 11.2, cx + 15.2, by + 11.2) - 7.2, (x, y, d) => d < -3.2 && y < by + 13 ? PAL.GLASS : PAL.INK);
    [[cx - 3, by - 12], [cx - 4, by - 11], [cx - 5, by - 10], [cx - 6, by - 9], [cx - 7, by - 7], [cx - 8, by - 6], [cx - 10, by - 3], [cx - 11, by - 1]].forEach(([x, y], i) => {
      if (!scr[y * PG + x]) return;
      set(x, y, i < 3 ? PAL.WHITE : PAL.GLINT); if (i > 0 && i < 5) set(x + 1, y, PAL.GLINT);
    });
    return { buf, scr };
  })();

  function makePixelBot() {
    const canvas = document.createElement('canvas'); canvas.width = canvas.height = PG;
    const ctx = canvas.getContext('2d'), buf = new Array(PG * PG).fill(null), face = new Uint8Array(PG * PG), now0 = performance.now();
    const b = { canvas, cur: '', since: now0, gx: 0, gy: 0, cx: 0, cy: 0, bob: 0, blinkUntil: 0, nextBlink: now0 + 2600, wink: true, nextWink: now0 + 4200, bounceStart: -9999, parts: [] };
    let off = 0;
    const set = (x, y, c) => { x = Math.round(x); y = Math.round(y); if (x >= 0 && x < PG && y >= 0 && y < PG) buf[y * PG + x] = c; };
    const onScr = (x, y) => { const sy = y - off; return x >= 0 && x < PG && sy >= 0 && sy < PG && PBASE.scr[sy * PG + x]; };
    const fp = (x, y) => { x = Math.round(x); y = Math.round(y); if (onScr(x, y)) face[y * PG + x] = 1; };
    const eyeZero = (ex, ey, big) => { const h = big ? 5 : 4; for (let dy = -h; dy <= h; dy++) for (let dx = -3; dx <= 3; dx++) if (!(Math.abs(dx) === 3 && Math.abs(dy) === h) && !(Math.abs(dx) <= 1 && Math.abs(dy) <= h - 2)) fp(ex + dx, ey + dy); };
    const eyeWink = (ex, ey) => [[-3, -4], [-2, -4], [-2, -3], [-1, -3], [-1, -2], [0, -2], [0, -1], [1, -1], [1, 0], [2, 0], [0, 1], [1, 1], [-1, 2], [0, 2], [-2, 3], [-1, 3], [-3, 4], [-2, 4]].forEach(([dx, dy]) => fp(ex + dx, ey + dy));
    const eyeHappy = (ex, ey) => [[-3, 1], [-3, 2], [-2, 0], [-2, 1], [-1, -1], [-1, 0], [0, -2], [0, -1], [1, -1], [1, 0], [2, 0], [2, 1], [3, 1], [3, 2]].forEach(([dx, dy]) => fp(ex + dx, ey + dy));
    const eyeClosed = (ex, ey) => { for (let dx = -3; dx <= 3; dx++) { fp(ex + dx, ey); if (Math.abs(dx) <= 2) fp(ex + dx, ey + 1); } };
    const eyeFocus = (ex, ey, side) => { for (let dy = -2; dy <= 3; dy++) for (let dx = -3; dx <= 3; dx++) if (!(dy === -2 && side * dx > 0) && !(Math.abs(dx) === 3 && dy === 3) && !(Math.abs(dx) <= 1 && dy >= 0 && dy <= 1)) fp(ex + dx, ey + dy); };
    const eyeTenge = (ex, ey) => { for (let dx = -3; dx <= 3; dx++) { fp(ex + dx, ey - 3); fp(ex + dx, ey - 1); } for (let dy = -1; dy <= 4; dy++) { fp(ex, ey + dy); fp(ex + 1, ey + dy); } };
    const smile = (mx, my, wide) => { const w = wide ? 4 : 3; fp(mx - w, my - 1); fp(mx + w, my - 1); for (let dx = 1 - w; dx <= w - 1; dx++) { fp(mx + dx, my); if (Math.abs(dx) <= w - 2) fp(mx + dx, my + 1); } };
    const oMouth = (mx, my) => { for (let dx = -1; dx <= 1; dx++) { fp(mx + dx, my - 1); fp(mx + dx, my + 2); } fp(mx - 2, my); fp(mx - 2, my + 1); fp(mx + 2, my); fp(mx + 2, my + 1); };
    const talk = (mx, my, t) => {
      const ph = Math.floor(t * 9) % 4;
      if (ph === 0) smile(mx, my, false);
      else if (ph % 2) { for (let dx = -2; dx <= 2; dx++) fp(mx + dx, my - 1); fp(mx - 2, my); fp(mx + 2, my); for (let dx = -1; dx <= 1; dx++) fp(mx + dx, my + 1); }
      else { for (let dx = -3; dx <= 3; dx++) fp(mx + dx, my - 1); fp(mx - 3, my); fp(mx + 3, my); fp(mx - 2, my + 1); fp(mx + 2, my + 1); for (let dx = -1; dx <= 1; dx++) fp(mx + dx, my + 2); }
    };
    const burst = n => {
      const kinds = ['tenge', 'coin', 'sparkle', 'coin'];
      for (let i = 0; i < n; i++) { const a = -Math.PI * .1 - Math.random() * Math.PI * .8, v = 26 + Math.random() * 34; b.parts.push({ k: kinds[i % 4], x: 48 + R(-12, 12), y: 40 + R(-6, 6), vx: Math.cos(a) * v, vy: Math.sin(a) * v - 12, life: R(.9, 1.35), age: 0 }); }
    };
    b.mood = m => { if (m === b.cur) return; b.cur = m; b.since = performance.now(); b.parts.length = 0; if (m === 'happy' && !LITE) burst(6); };
    b.look = (x, y) => { b.gx = clamp(x, -1, 1); b.gy = clamp(y, -1, 1); };
    b.render = (now, dt, still) => {
      const t = now / 1000, m = b.cur, age = (now - b.since) / 1000, bAge = (now - b.bounceStart) / 1000, lite = LITE || !!still;
      b.cx += (b.gx - b.cx) * .14; b.cy += (b.gy - b.cy) * .14;
      if (now >= b.nextBlink) { b.blinkUntil = now + 130; b.nextBlink = now + R(2400, 5200); }
      if (now >= b.nextWink) { b.wink = !b.wink; b.nextWink = now + (b.wink ? 4600 : 2100); }
      const blink = now < b.blinkUntil;
      b.bob = (bAge >= 0 && bAge < .45) ? -Math.round(Math.sin((bAge / .45) * Math.PI) * 7) : lite ? 0 : (m === 'happy' && age < 2.6) ? -Math.round(Math.abs(Math.sin(t * 5.2)) * 4) : m === 'speak' ? Math.round(Math.sin(t * 6.5) * 1.6) : Math.round(Math.sin(t * 2.5) * 2);
      off = b.bob; buf.fill(null); face.fill(0);
      for (let y = 0; y < PG; y++) { const sy = y - off; if (sy >= 0 && sy < PG) for (let x = 0; x < PG; x++) buf[y * PG + x] = PBASE.buf[sy * PG + x]; }
      const busy = m === 'work' || m === 'speak', ey = PEARY + off;
      for (const side of [-1, 1]) {
        const ex = PCX + side * PEAR, lx = side < 0 ? ex - 2 : ex + 2, gl = busy ? (Math.sin(t * 10) > 0 ? PAL.GREEN_HI : PAL.GREEN_BR) : PAL.GREEN_BR;
        set(lx, ey - 1, gl); set(lx, ey, PAL.GREEN); set(lx, ey + 1, gl);
        if (m === 'work') for (let i = 0; i < 3; i++) { const bx = ex + side * (6 + i * 3), h = 1 + Math.round((Math.sin(t * 9 - i * 1.1) + 1) * 2.2); for (let dy = -h; dy <= h; dy++) set(bx, ey + dy, Math.abs(dy) === h ? PAL.GREEN_HI : i === 0 ? PAL.GREEN_BR : PAL.GREEN); }
      }
      const lx = Math.round(b.cx * 2), ly = Math.round(b.cy * 1.5);
      const fx = PCX + lx, fy = PBY + 5 + off + ly, L = fx - 8, Rx = fx + 8, eY = fy - 1, mY = fy + 6;
      if (bAge >= 0 && bAge < .75) { eyeTenge(L, eY); eyeTenge(Rx, eY); smile(fx, mY, true); }
      else if (m === 'happy') { if (Math.floor(t * 1.4) % 3 === 2) { eyeTenge(L, eY); eyeTenge(Rx, eY); } else { eyeHappy(L, eY); eyeHappy(Rx, eY); } smile(fx, mY, true); }
      else if (m === 'work' || m === 'ready') { eyeFocus(L, eY, -1); eyeFocus(Rx, eY, 1); for (let dx = -3; dx <= 3; dx++) fp(fx + dx, mY); fp(fx + 4, mY - 1); }
      else if (m === 'oops') { eyeZero(L, eY, true); eyeZero(Rx, eY, true); oMouth(fx, mY); }
      else if (m === 'speak') { if (blink) { eyeClosed(L, eY); eyeClosed(Rx, eY); } else { eyeZero(L, eY, false); eyeZero(Rx, eY, false); } talk(fx, mY, t); }
      else { if (blink) { eyeClosed(L, eY); eyeClosed(Rx, eY); } else if (b.wink) { eyeWink(L, eY); eyeZero(Rx, eY, false); } else { eyeZero(L, eY, false); eyeZero(Rx, eY, false); } smile(fx, mY, false); }
      for (let y = 1; y < PG - 1; y++) for (let x = 1; x < PG - 1; x++) { const i = y * PG + x; if (!face[i] && onScr(x, y) && (face[i - 1] || face[i + 1] || face[i - PG] || face[i + PG])) buf[i] = PAL.HALO; }
      for (let i = 0; i < PG * PG; i++) if (face[i]) buf[i] = PAL.CORE;
      if (m !== 'work' && m !== 'ready') for (const bx of [fx - 12, fx + 12]) { if (onScr(bx, mY)) set(bx, mY, PAL.BLUSH); if (onScr(bx - 1, mY)) set(bx - 1, mY, PAL.BLUSH); }
      for (let i = b.parts.length - 1; i >= 0; i--) {
        const p = b.parts[i]; p.age += dt; if (p.age >= p.life) { b.parts.splice(i, 1); continue; }
        p.vy += 62 * dt; p.x += p.vx * dt; p.y += p.vy * dt; const px = Math.round(p.x), py = Math.round(p.y);
        if (p.k === 'coin') { for (let dy = -2; dy <= 2; dy++) for (let dx = -2; dx <= 2; dx++) if (!(Math.abs(dx) === 2 && Math.abs(dy) === 2)) set(px + dx, py + dy, Math.abs(dx) === 2 || Math.abs(dy) === 2 ? PAL.INK : dx < 0 && dy < 0 ? PAL.GOLD_HI : PAL.GOLD_LT); }
        else if (p.k === 'tenge') { for (let dx = -2; dx <= 2; dx++) { set(px + dx, py - 2, PAL.GOLD_HI); set(px + dx, py, PAL.GOLD_LT); } set(px, py + 1, PAL.GOLD); set(px, py + 2, PAL.GOLD); }
        else { const c = p.k === 'sparkle' ? PAL.GREEN_BR : PAL.GOLD_HI; set(px, py, PAL.WHITE); set(px - 1, py, c); set(px + 1, py, c); set(px, py - 1, c); set(px, py + 1, c); }
      }
      ctx.clearRect(0, 0, PG, PG);
      for (let y = 0; y < PG; y++) for (let x = 0; x < PG;) { const c = buf[y * PG + x]; if (!c) { x++; continue; } let n = 1; while (x + n < PG && buf[y * PG + x + n] === c) n++; ctx.fillStyle = c; ctx.fillRect(x, y, n, 1); x += n; }
      return buf;
    };
    b.mood('idle'); return b;
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

  function paint(cv, g, bot, now, dt, b, still) {
    bot.render(now, dt, still);
    g.clearRect(0, 0, cv.width, cv.height);
    g.imageSmoothingEnabled = !!b.smooth;
    if (b.smooth) g.imageSmoothingQuality = 'high';
    if (b.crop) {
      var s = Math.min(cv.width / CROP.w, cv.height / CROP.h), w = CROP.w * s, h = CROP.h * s;
      g.drawImage(bot.canvas, CROP.x, CROP.y, CROP.w, CROP.h, (cv.width - w) / 2, (cv.height - h) / 2, w, h);
    } else g.drawImage(bot.canvas, 0, 0, cv.width, cv.height);
  }

  // Размер холста: целое число пикселей сетки на точку экрана (192, 96 и 48 на 2× — чётко); меньше сетки — сглаженно
  function backing(size, crop) {
    var dpr = window.devicePixelRatio || 1, want = size * dpr;
    if (crop || want < PG * .75) return { px: Math.max(16, Math.round(want)), css: size, smooth: true, crop: !!crop };
    var k = Math.max(1, Math.round(want / PG));
    return { px: PG * k, css: PG * k / dpr, smooth: false, crop: false };
  }

  function active(list) { return document.hidden ? [] : list.filter(function (a) { return a._visible; }); }

  function tick(now) {
    raf = 0;
    var dt = last ? Math.min(.05, (now - last) / 1000) : .016; last = now;
    var la = active(agents), lp = active(pilots);
    la.forEach(function (a) { if (a._real === 'idle') lookAt(a._drone, a._box.getBoundingClientRect()); a._draw(now, dt); });
    lp.forEach(function (p) { p._step(now, dt); });
    if ((la.length || lp.length) && !LITE) raf = requestAnimationFrame(tick);
    else last = 0;
  }
  function kick() { if (!raf && !LITE) raf = requestAnimationFrame(tick); }

  document.addEventListener('visibilitychange', function () { if (!document.hidden) kick(); });
  window.addEventListener('pointermove', function (ev) { mouse = { x: ev.clientX, y: ev.clientY }; }, { passive: true });

  // Пока печатает реплику, спокойный AIshka говорит (рот двигается), потом возвращается к своему настроению
  function talking(bot, moodNow, typing, text) {
    if (!text || LITE || moodNow() !== 'idle') return typing;
    bot.mood('speak'); kick();
    return typing.then(function () { if (bot.cur === 'speak') bot.mood(moodNow()); });
  }

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
    var b = backing(size, size < 40);
    el.classList.add('bcc-agent');
    if (b.smooth) el.classList.add('bcc-agent--small');
    if (size < 40) el.classList.add('bcc-agent--icon');   // значок в строке: без тени
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
      el: el, size: b.css, _box: box, _drone: makePixelBot(), _visible: !io, _mood: '', _real: 'idle', _said: null, _moodT: 0,
      _draw: function (now, dt, still) { paint(cv, cv.getContext('2d'), a._drone, now, dt, b, still); },
      mood: function (name, ms) {
        if (MOODS.indexOf(name) < 0 && !ALIAS[name]) name = 'idle';
        clearTimeout(a._moodT);
        a._mood = name; a._real = real(name);
        a._drone.mood(a._real);
        if (el.getAttribute('data-mood') !== name) el.setAttribute('data-mood', name);
        if (ms > 0) a._moodT = setTimeout(function () { a.mood('idle'); }, ms);
        if (LITE) a._draw(1200, 0, true); else kick();
        return a;
      },
      say: function (text) {
        ensureTalk(); a._said = text == null ? '' : String(text);
        return talking(a._drone, function () { return a._real; }, typeSay(a._said), a._said);
      },
      stage: function (text) { ensureTalk(); stageEl.textContent = text || ''; stageEl.hidden = !text; return a; },
      destroy: function () {
        clearTimeout(a._moodT);
        if (io) io.unobserve(el);
        agents = agents.filter(function (x) { return x !== a; });
        if (box.parentNode) box.parentNode.removeChild(box);
        if (talk && talk.parentNode) talk.parentNode.removeChild(talk);
        el.classList.remove('bcc-agent', 'bcc-agent--small', 'bcc-agent--icon');
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
    sheet.style.isolation = 'isolate';   // луч идёт под текстом, как линейка на бумаге, а не зачёркивает строку
    var b = backing(+(opts.size || sheet.getAttribute('data-size') || 96), false), S = b.css;
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
      sheet: sheet, size: S, _drone: makePixelBot(), _visible: !io, state: 'scan', prog: 0, target: 0, focusEl: null, _real: 'work',
      x: null, y: null, ly: null, x0: 0, y0: 0, t0: 0, dur: 900, _said: null,
      bottomInset: opts.bottomInset != null ? +opts.bottomInset : 96,
      _spot: function (W) { var m = Math.min(40, Math.round(W * .05)); return { x: side === 'left' ? m : W - S - m, y: -Math.round(S * FOOT) }; },
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
          p.x = cx - S / 2; p.y = ly - S * FOOT - Math.round(S * .06);   // плывёт чуть выше луча
          line.style.transform = 'translate3d(0,' + ly.toFixed(1) + 'px,0)';
          wash.style.transform = 'translate3d(0,' + (ly - 40).toFixed(1) + 'px,0)';
        } else if (p.state === 'landing') {
          var s = p._spot(W), k = still ? 1 : clamp((now - p.t0) / p.dur, 0, 1), e = ease(k);
          p.x = p.x0 + (s.x - p.x0) * e; p.y = p.y0 + (s.y - p.y0) * e - Math.sin(k * Math.PI) * 28;
          if (k >= 1) {
            p.state = 'landed';
            layer.classList.add('is-landed');
            sheet.setAttribute('data-bcc-landed', '');
            try { sheet.dispatchEvent(new CustomEvent('bcc-agent:landed', { bubbles: true })); } catch (e2) { /* старый браузер */ }
          }
        } else {
          var s2 = p._spot(W); p.x = s2.x; p.y = s2.y;
        }
        var left = p.x + S + 300 > W && p.x > 160, out = p.state === 'scan' ? 0 : 1;   // севший — говорит над столом
        var room = left ? p.x - 8 + out * Math.max(0, r.left - 8) : W - p.x - S - 8 + out * Math.max(0, window.innerWidth - r.right - 8);
        talk.classList.toggle('is-left', left);
        talk.style.maxWidth = Math.max(140, Math.min(560, room)) + 'px';
        craft.style.transform = 'translate3d(' + p.x.toFixed(1) + 'px,' + p.y.toFixed(1) + 'px,0)';
        if (p.state === 'landed' && p._drone.cur === 'idle') lookAt(p._drone, cv.getBoundingClientRect());
        paint(cv, g, p._drone, now, dt, b, still);
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
      say: function (text) {
        p._said = text == null ? '' : String(text);
        return talking(p._drone, function () { return p._real; }, typeSay(p._said), p._said);
      },
      mood: function (m) { p._real = real(m); p._drone.mood(p._real); p._refresh(); return p; },
      land: function () {
        if (p.state !== 'scan') return p;
        p.state = 'landing'; p.t0 = performance.now(); p.x0 = p.x || 0; p.y0 = p.y || 0;
        p._real = 'idle'; p._drone.mood('idle'); p.stage('');
        p._refresh();
        return p;
      },
      takeoff: function () {
        p.state = 'scan'; p._real = 'work'; p._drone.mood('work');
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
    p._real = real(opts.mood || 'work'); p._drone.mood(p._real);
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
      var landing = v === 'land' || v === 'done';
      if (el.hasAttribute('data-progress') && !landing) p.progress(parseFloat(el.getAttribute('data-progress')) || 0);
      if (st != null && !landing) p.stage(st);
      if (sy != null && sy !== p._said) p.say(sy);
      if (el.hasAttribute('data-mood') && p.state === 'scan') p.mood(el.getAttribute('data-mood'));
      if (landing) p.land();
    }
  }
  function mountAll(root) {
    (root || document).querySelectorAll('[data-bcc-agent],[data-bcc-scan]').forEach(sync);
  }

  window.addEventListener('resize', function () { agents.forEach(function (a) { a._draw(1200, 0, true); }); pilots.forEach(function (p) { p._refresh(); }); });
  window.addEventListener('scroll', function () { if (LITE) pilots.forEach(function (p) { p._refresh(); }); }, { passive: true });

  // Статичный кадр для терминала и тестов: массив 96×96 цветов (null — прозрачно)
  function pixels(mood, o) {
    o = o || {};
    var d = makePixelBot(); d.mood(real(mood)); d.parts.length = 0;
    d.cx = d.gx = o.gx || 0; d.cy = d.gy = o.gy || 0; d.nextBlink = d.nextWink = Infinity;
    d.blinkUntil = o.blink ? Infinity : 0; d.wink = !!o.wink;
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
