// Экспорт двух ключевых кадров и проверка читаемости.
//
//   node tools/render.mjs            (из папки presentation/first-frame)
//
// Нужны: Node 18+, пакет playwright с Chromium, ffmpeg и ImageMagick (convert).
// Пишет:
//   exports/keyframe-{a,b}-1080p.png   — мастер 1920×1080 для проектора 16:9
//   exports/keyframe-{a,b}-720p.png    — уменьшенная копия 1280×720 (lanczos, как при экспорте видео)
//   exports/check/projector-{a,b}.png  — имитация проектора: поднятый чёрный, просевший белый, мягкий фокус
//   exports/check/sheet-{a,b}.png      — имитация проектора и 720p рядом в одном масштабе
//   exports/checks.json                — замеры: кегли, контраст, безопасные поля, наложения, число слов
import { createRequire } from "node:module";
import { execFileSync } from "node:child_process";
import { mkdirSync, writeFileSync, existsSync } from "node:fs";
import { fileURLToPath, pathToFileURL } from "node:url";
import path from "node:path";

// playwright ищется и в локальном node_modules, и в глобальной установке (NODE_PATH / require)
const { chromium } = createRequire(import.meta.url)("playwright");

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, "..");
const out = path.join(root, "exports");
const chk = path.join(out, "check");
mkdirSync(chk, { recursive: true });

const SAFE = { x: 96, y: 54 };          // 5 % по горизонтали и вертикали — запас под overscan
const MIN_PX_1080 = 26;                 // самый мелкий допустимый текст на 1080p (≈17 px в 720p)
const READ_WPS = 3;                     // слов в секунду при чтении с экрана

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 1 });
const report = { generated_at: new Date().toISOString(), safe_area_px: SAFE, min_text_px_1080: MIN_PX_1080, frames: {} };

for (const id of ["a", "b"]) {
  const url = pathToFileURL(path.join(root, "index.html")).href + `?frame=${id}&export`;
  await page.goto(url);
  await page.evaluate(async () => {
    await document.fonts.ready;
    await Promise.all([...document.images].map((i) => (i.complete ? 0 : new Promise((r) => { i.onload = i.onerror = r; }))));
  });
  await page.waitForTimeout(150);

  const m = await page.evaluate(({ SAFE, MIN_PX_1080, id }) => {
    const stage = document.getElementById(id);
    const rgb = (s) => (s.match(/[\d.]+/g) || []).map(Number);
    const lin = (c) => { c /= 255; return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4; };
    const lum = ([r, g, b]) => 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
    const blend = (fg, bg) => { const a = fg[3] ?? 1; return [0, 1, 2].map((i) => fg[i] * a + bg[i] * (1 - a)); };
    function bgOf(el) {
      const chain = [];
      for (let e = el; e && e !== document.documentElement; e = e.parentElement) chain.push(getComputedStyle(e).backgroundColor);
      let c = [255, 255, 255];
      for (const s of chain.reverse()) { const v = rgb(s); if (v.length >= 3 && (v[3] ?? 1) > 0) c = blend(v, c); }
      return c;
    }
    // проектор: чёрный поднят до 6 % яркости, белый просел до 92 %
    const proj = (L) => 0.06 + 0.86 * L;
    const ratio = (a, b) => { const [h, l] = a > b ? [a, b] : [b, a]; return (h + 0.05) / (l + 0.05); };

    const items = [];
    const walker = document.createTreeWalker(stage, NodeFilter.SHOW_TEXT);
    for (let n; (n = walker.nextNode()); ) {
      const t = n.textContent.replace(/\s+/g, " ").trim();
      if (!t) continue;
      const el = n.parentElement;
      if (el.closest(".logo-slot")) continue; // временное место под официальный логотип, не текст кадра
      const cs = getComputedStyle(el);
      if (cs.display === "none" || cs.visibility === "hidden") continue;
      const r = document.createRange(); r.selectNodeContents(n);
      const rects = [...r.getClientRects()].filter((q) => q.width > 0);
      if (!rects.length) continue;
      const box = rects.reduce((a, q) => ({ l: Math.min(a.l, q.left), t: Math.min(a.t, q.top), r: Math.max(a.r, q.right), b: Math.max(a.b, q.bottom) }), { l: 1e9, t: 1e9, r: -1e9, b: -1e9 });
      const fg = rgb(cs.color); const bg = bgOf(el);
      const fgc = blend(fg, bg);
      const Lf = lum(fgc), Lb = lum(bg);
      const voice = el.closest("[data-voice]")?.getAttribute("data-voice") || "—";
      items.push({
        text: t.slice(0, 60), full: t, voice, el: el.className || el.tagName.toLowerCase(),
        font: cs.fontFamily.split(",")[0].replace(/"/g, ""), px: parseFloat(cs.fontSize), weight: +cs.fontWeight,
        px720: +(parseFloat(cs.fontSize) * 2 / 3).toFixed(1),
        contrast: +ratio(Lf, Lb).toFixed(2), contrast_projector: +ratio(proj(Lf), proj(Lb)).toFixed(2),
        box: { l: Math.round(box.l), t: Math.round(box.t), r: Math.round(box.r), b: Math.round(box.b) },
        lines: new Set(rects.map((q) => Math.round(q.top))).size,
      });
    }

    const large = (i) => i.px >= 32 || (i.px >= 24 && i.weight >= 600);
    const issues = [];
    for (const i of items) {
      if (i.px < MIN_PX_1080) issues.push(`мелкий текст ${i.px}px: «${i.text}»`);
      const need = large(i) ? 3 : 4.5;
      if (i.contrast_projector < need) issues.push(`контраст на проекторе ${i.contrast_projector} < ${need}: «${i.text}»`);
      const b = i.box;
      if (b.l < SAFE.x - 1 || b.r > 1920 - SAFE.x + 1 || b.t < SAFE.y - 1 || b.b > 1080 - SAFE.y + 1) issues.push(`выходит за безопасное поле: «${i.text}» ${JSON.stringify(b)}`);
    }
    // наложения текста разных элементов
    for (let x = 0; x < items.length; x++) for (let y = x + 1; y < items.length; y++) {
      const a = items[x].box, b = items[y].box;
      const ov = Math.min(a.r, b.r) - Math.max(a.l, b.l) > 2 && Math.min(a.b, b.b) - Math.max(a.t, b.t) > 2;
      if (ov && items[x].text !== items[y].text) issues.push(`текст наезжает: «${items[x].text}» × «${items[y].text}»`);
    }
    // текст не помещается в контейнер
    stage.querySelectorAll(".doc, .ask, .meter, .recap, .seg, .badge, .speaker").forEach((e) => {
      if (e.scrollWidth > e.clientWidth + 1 || e.scrollHeight > e.clientHeight + 1) issues.push(`переполнение ${e.className}: ${e.scrollWidth}×${e.scrollHeight} в ${e.clientWidth}×${e.clientHeight}`);
    });

    const used = new Set(items.map((i) => i.font));
    const fonts = {};
    for (const f of used) fonts[f] = document.fonts.check(`40px "${f}"`, "Жж₸");
    for (const [k, v] of Object.entries(fonts)) if (!v) issues.push(`шрифт не загружен: ${k}`);
    const missingLogos = [...stage.querySelectorAll("[data-missing-logo]")].map((e) => e.getAttribute("data-missing-logo"));

    const words = {};
    const wc = (s) => s.split(/\s+/).filter((w) => /[\p{L}\d]/u.test(w)).length;
    for (const i of items) words[i.voice] = (words[i.voice] || 0) + wc(i.full);
    const quotes = [...stage.querySelectorAll('[data-voice="doc"]')].map((q) => ({ line: +q.dataset.tzLine, text: q.textContent }));
    const minPx = Math.min(...items.map((i) => i.px));
    const minC = Math.min(...items.map((i) => i.contrast_projector));
    return { items, issues, fonts, missingLogos, words, quotes, min_px_1080: minPx, min_px_720: +(minPx * 2 / 3).toFixed(1), min_contrast_projector: minC };
  }, { SAFE, MIN_PX_1080, id });

  const totalWords = Object.values(m.words).reduce((a, b) => a + b, 0);
  m.reading_seconds_all_text = +(totalWords / READ_WPS).toFixed(1);
  if (id === "b") {
    const core = (m.words.doc || 0) + m.items.filter((i) => /ask__q/.test(i.el)).reduce((a, i) => a + i.full.split(/\s+/).length, 0);
    m.words_quotes_and_question = core;
    m.reading_seconds_quotes_and_question = +(core / READ_WPS).toFixed(1);
  }
  for (const i of m.items) delete i.full;
  report.frames[id] = m;

  const png1080 = path.join(out, `keyframe-${id}-1080p.png`);
  const png720 = path.join(out, `keyframe-${id}-720p.png`);
  const projector = path.join(chk, `projector-${id}.png`);
  const sheet = path.join(chk, `sheet-${id}.png`);
  await page.screenshot({ path: png1080, clip: { x: 0, y: 0, width: 1920, height: 1080 } });
  execFileSync("ffmpeg", ["-y", "-loglevel", "error", "-i", png1080, "-vf", "scale=1280:720:flags=lanczos", png720]);
  execFileSync("convert", [png1080, "+level", "6%,92%", "-modulate", "100,80", "-blur", "0x0.9", projector]);
  execFileSync("convert", [
    "(", projector, "-resize", "1280x720", "-gravity", "north", "-background", "#0b0d10", "-splice", "0x44", "-fill", "#fff", "-pointsize", "24", "-annotate", "+0+8", "проектор (имитация), уменьшено до 1280", ")",
    "(", png720, "-gravity", "north", "-background", "#0b0d10", "-splice", "0x44", "-fill", "#fff", "-pointsize", "24", "-annotate", "+0+8", "копия 720p", ")",
    "+append", sheet,
  ]);
  console.log(`кадр ${id}: мин. кегль ${m.min_px_1080}px (720p: ${m.min_px_720}px), мин. контраст на проекторе ${m.min_contrast_projector}, слов ${totalWords}, проблем ${m.issues.length}${m.missingLogos.length ? `, нет логотипов: ${m.missingLogos.join(", ")}` : ""}`);
  for (const s of m.issues) console.log("  · " + s);
}

writeFileSync(path.join(out, "checks.json"), JSON.stringify(report, null, 2) + "\n");
await browser.close();
if (!existsSync(path.join(root, "assets/logos/bcc-hub-full.png")) || !existsSync(path.join(root, "assets/logos/mnu-ai-club.webp")))
  console.log("Официальных логотипов нет в assets/logos — в кадрах стоят места под них. Запустите tools/fetch-logos.sh и повторите экспорт.");
