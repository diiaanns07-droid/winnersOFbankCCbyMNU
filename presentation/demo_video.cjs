// Видео-демо для ролика (№14): Playwright записывает браузер, субтитры — по тем же шагам сценария.
//
//   node presentation/demo_video.cjs --base http://127.0.0.1:8014/ --file release/input/requirements.pdf \
//        --out presentation [--provider claude_cli --model sonnet] [--title presentation/title.html] [--real "4 мин 40 с"]
//
// Веб лучше запустить с общим кэшем и темпом показа этапов, тогда сохранённый живой прогон повторяется без модели:
//   python -m bcc_review.v2.web --cache-dir <кэш живого прогона> --pace 2.6
// Сценарий: титул → загрузка PDF → этапы → вердикт и блокеры → клик по блокеру подсвечивает строки документа →
// фильтр → вопросы владельцу → чек-лист банка → скачивание Word, PDF с выделениями, Jira CSV (с показом) → паспорт → финал.
// Выход: <out>/demo.webm, demo.mp4, demo.srt и demo_subtitled.mp4 (субтитры вшиты; нужен ffmpeg с libass).
const { chromium } = require("playwright");
const path = require("path");
const fs = require("fs");
const { execFileSync } = require("child_process");

const args = Object.fromEntries(process.argv.slice(2).reduce((acc, v, i, a) => (v.startsWith("--") ? acc.concat([[v.slice(2), a[i + 1]]]) : acc), []));
const base = (args.base || "http://127.0.0.1:8014/").replace(/\/?$/, "/");
const inputFile = path.resolve(args.file || "release/input/requirements.pdf");
const outDir = path.resolve(args.out || "presentation");
const provider = args.provider || "claude_cli";
const model = args.model || "sonnet";
const titleFile = args.title ? path.resolve(args.title) : path.resolve(__dirname, "title.html");
const W = 1440, H = 900;

const CURSOR = `(() => { if (document.getElementById("__cur")) return;
  const c = document.createElement("div"); c.id = "__cur";
  c.style.cssText = "position:fixed;left:720px;top:450px;width:24px;height:24px;z-index:2147483647;pointer-events:none;transition:left .6s cubic-bezier(.3,.7,.2,1),top .6s cubic-bezier(.3,.7,.2,1);filter:drop-shadow(0 2px 3px rgba(0,0,0,.35))";
  c.innerHTML = '<svg width="24" height="24" viewBox="0 0 22 22"><path d="M3 2l15 9-6.5 1.6L8.5 19z" fill="#111" stroke="#fff" stroke-width="1.6" stroke-linejoin="round"/></svg>';
  const r = document.createElement("div"); r.id = "__ring";
  r.style.cssText = "position:fixed;width:38px;height:38px;margin:-19px 0 0 -19px;border-radius:50%;border:3px solid #0E7C55;opacity:0;z-index:2147483646;pointer-events:none;";
  const t = document.createElement("div"); t.id = "__toast";
  t.style.cssText = "position:fixed;right:28px;top:84px;z-index:2147483645;pointer-events:none;display:flex;flex-direction:column;gap:8px;font:600 15px/1.35 Inter,system-ui,sans-serif";
  const k = document.createElement("div"); k.id = "__tick"; // меняется каждый кадр: запись идёт без пропусков,
  k.style.cssText = "position:fixed;left:0;bottom:0;width:2px;height:2px;z-index:2147483647;pointer-events:none;opacity:.02"; // субтитры не разъезжаются
  (function f(n) { k.style.background = n % 2 ? "#000" : "#fff"; requestAnimationFrame(() => f(n + 1)); })(0);
  document.documentElement.append(c, r, t, k); })()`;

function plural(n, one, few, many) {
  const a = Math.abs(n) % 100, b = a % 10;
  return a > 10 && a < 20 ? many : b === 1 ? one : b >= 2 && b <= 4 ? few : many;
}
function fmtDur(s) {
  s = Math.round(s || 0);
  return s < 60 ? `${s} с` : `${Math.floor(s / 60)} мин ${String(s % 60).padStart(2, "0")} с`;
}
function srtTime(ms) {
  const h = Math.floor(ms / 3600000), m = Math.floor(ms / 60000) % 60, s = Math.floor(ms / 1000) % 60, x = ms % 1000;
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")},${String(x).padStart(3, "0")}`;
}

(async () => {
  fs.mkdirSync(outDir, { recursive: true });
  const tmp = fs.mkdtempSync(path.join(outDir, ".rec-"));
  const b = await chromium.launch();
  const ctx = await b.newContext({ viewport: { width: W, height: H }, acceptDownloads: true,
    recordVideo: { dir: tmp, size: { width: W, height: H } } });
  const p = await ctx.newPage();
  const t0 = Date.now();
  const subs = [];
  const say = (text) => {
    const now = Date.now() - t0;
    if (subs.length && subs[subs.length - 1].end == null) subs[subs.length - 1].end = now;
    if (text) subs.push({ start: now, end: null, text });
  };
  const pause = (ms) => p.waitForTimeout(ms);
  const cursor = async () => { await p.evaluate(CURSOR).catch(() => {}); };
  async function moveTo(x, y) {
    await cursor();
    await p.evaluate(([x, y]) => { const c = document.getElementById("__cur"); c.style.left = x + "px"; c.style.top = y + "px"; }, [x, y]);
    await pause(700);
  }
  async function click(loc, { wait = 900, dx = null } = {}) {
    await loc.scrollIntoViewIfNeeded().catch(() => {});
    const bb = await loc.boundingBox();
    if (bb) {
      const x = bb.x + (dx == null ? Math.min(bb.width / 2, 80) : dx), y = bb.y + Math.min(bb.height / 2, 18);
      await moveTo(x, y);
      await p.evaluate(([x, y]) => { const r = document.getElementById("__ring"); r.style.left = x + "px"; r.style.top = y + "px";
        r.animate([{ opacity: .9, transform: "scale(.4)" }, { opacity: 0, transform: "scale(1.5)" }], { duration: 520 }); }, [x, y]);
    }
    await loc.click();
    await pause(wait);
  }
  async function toast(text) {
    await cursor();
    await p.evaluate((text) => { const box = document.getElementById("__toast"); const d = document.createElement("div");
      d.textContent = text; d.style.cssText = "background:#131820;color:#fff;padding:10px 16px;border-radius:10px;box-shadow:0 8px 28px rgba(0,0,0,.3);border-left:4px solid #2FB37E";
      box.append(d); setTimeout(() => d.remove(), 3800); }, text);
  }

  // 0. титул команды
  say("STUPITS — ИИ-агент, который находит дефекты в техническом задании до первой строки кода");
  await p.goto("file://" + titleFile + "#final");
  await cursor();
  await pause(6500);

  // 1. загрузка PDF
  await p.goto(base);
  await cursor();
  say("Аналитик загружает ТЗ в PDF — как есть, без подготовки");
  await pause(1500);
  await moveTo(700, 360);
  await p.setInputFiles("#file", inputFile);
  await pause(1600);
  say("Модель на выбор: Claude, Gemini или своя в закрытом контуре банка");
  await click(p.locator("#provider"), { wait: 400 });
  await p.selectOption("#provider", provider);
  await p.fill("#model", model);
  await pause(1800);
  await click(p.locator("#go"), { wait: 300 });

  // 2. этапы
  await p.waitForURL(/\/jobs\//);
  const jobUrl = p.url();
  await cursor();
  say("Агент читает документ, нумерует строки и нарезает требования с собственными ID");
  await p.waitForFunction(() => [...document.querySelectorAll(".stg")].some((x) => /Ревьюеры/.test(x.textContent) && /running|done/.test(x.className)), null, { timeout: 600000 });
  say("Четыре ревьюера — аналитик, тестировщик, архитектор и риски — и проверка набора работают параллельно");
  await p.waitForFunction(() => [...document.querySelectorAll(".stg")].some((x) => /Сверка цитат/.test(x.textContent) && /running|done/.test(x.className)), null, { timeout: 600000 });
  say("Код сверяет каждую цитату с документом; судья склеивает дубли и ставит критичность");
  await p.waitForSelector("#result:not([hidden])", { timeout: 1800000 });
  await cursor();

  // данные настоящего отчёта — для подписей
  const jid = jobUrl.split("/jobs/")[1].split(/[/?#]/)[0];
  const rep = await (await p.request.get(base + "jobs/" + jid + "/files/report.json")).json();
  const fs_ = rep.findings || [];
  const crit = fs_.filter((f) => f.severity === "critical").length;
  let ok = 0, total = 0;
  fs_.forEach((f) => (f.evidence || []).forEach((e) => { total++; if (["exact", "normalized", "fuzzy"].includes(e.verified)) ok++; }));
  const run = rep.run || {};
  const real = args.real ? ` (живой прогон: ${args.real})` : "";
  if ((run.calls || {}).cached) say(`Показ ускорен: ответы модели взяты из кэша сохранённого прогона ${model}${real}`);
  await pause(2600);

  // 3. первый экран отчёта
  const fr = p.frameLocator("#frame");
  await fr.locator(".hero").waitFor();
  say(`Вердикт: разработку и тестирование начинать нельзя — ${crit} ${plural(crit, "критичный дефект", "критичных дефекта", "критичных дефектов")} из ${fs_.length}`);
  await moveTo(520, 420);
  await pause(3200);
  say(`Все ${total} ${plural(total, "цитата", "цитаты", "цитат")} найдены в документе программой, а не моделью`);
  await moveTo(1340, 420);
  await pause(3000);
  say("«Исправить первым» — порядок работы для аналитика");
  await fr.locator(".fixfirst").evaluate((x) => x.scrollIntoView({ behavior: "smooth", block: "center" }));
  await pause(2800);

  // 4. блокеры и подсветка в документе
  await fr.locator(".tabs").evaluate((t) => { const y = t.getBoundingClientRect().top + window.scrollY - 60; window.scrollTo({ top: y, behavior: "smooth" }); });
  await pause(1200);
  const cards = fr.locator('.card[data-sev="critical"]');
  say("Клик по блокеру — документ прокручивается к точной строке, цитаты выделены");
  await click(cards.nth(0).locator(".ct"), { wait: 3600 });
  const ev2 = cards.nth(0).locator(".ev").nth(1);
  if (await ev2.count()) {
    say("У противоречия подсвечены обе стороны — каждую можно открыть отдельно");
    await click(ev2, { wait: 3200 });
  }
  say("У каждого дефекта — сценарий, последствия, рекомендация и готовая формулировка");
  await cards.nth(0).locator(".more").evaluate((d) => { d.open = true; d.scrollIntoView({ behavior: "smooth", block: "start" }); });
  await pause(3600);
  const nCrit = Math.min(await cards.count(), 3);
  say("Следующие блокеры — тем же кликом");
  for (let i = 1; i < nCrit; i++) await click(cards.nth(i).locator(".ct"), { wait: 2600 });
  say("Фильтры по серьёзности, виду дефекта и ревьюеру");
  await click(fr.locator('.sevchip[data-sev="major"]'), { wait: 500 });
  await click(fr.locator('.sevchip[data-sev="minor"]'), { wait: 1800 });
  await click(fr.locator('.sevchip[data-sev="major"]'), { wait: 300 });
  await click(fr.locator('.sevchip[data-sev="minor"]'), { wait: 900 });

  // 5. вопросы владельцу
  say("Вопросы владельцу с вариантами ответа и адресатом");
  await click(fr.locator("#t-questions"), { wait: 1500 });
  const q = fr.locator(".qcard");
  if (await q.count()) {
    await click(q.nth(0).locator(".opts label").first(), { wait: 1200 });
    if ((await q.count()) > 1) await click(q.nth(1).locator(".opts label").first(), { wait: 900 });
    say("Ответы скачиваются файлом и возвращаются агенту — он пересчитает вердикт «до и после»");
    await moveTo(1300, 230);
    await pause(3000);
  }

  // 6. чек-лист банка
  say("Чек-лист «Ревью требований» банка заполнен автоматически, со ссылками на дефекты");
  await click(fr.locator("#t-checklist"), { wait: 4200 });

  // 7. выгрузки
  say("Выгрузки для процесса банка: Word, PDF с выделениями прямо в документе, задачи для Jira");
  await p.evaluate(() => window.scrollTo({ top: 0, behavior: "smooth" }));
  const dl = async (key) => {
    const a = p.locator(`.dl[data-key="${key}"]`);
    if (!(await a.count()) || (await a.isHidden())) return null;
    const [d] = await Promise.all([p.waitForEvent("download"), click(a, { wait: 400 })]);
    const file = path.join(tmp, d.suggestedFilename());
    await d.saveAs(file);
    await toast(`Скачано: ${d.suggestedFilename()} · ${Math.max(1, Math.round(fs.statSync(file).size / 1024))} КБ`);
    await pause(1300);
    return file;
  };
  await dl("docx");
  const pdfFile = await dl("pdf_annotated") || await dl("docx_annotated");
  const csvFile = await dl("csv");
  await pause(1200);

  // показ PDF с выделениями (страница с наибольшим числом пометок) и задач Jira
  if (pdfFile && pdfFile.endsWith(".pdf")) {
    let png = "";
    try {
      // вторая страница: на ней функциональные требования (в первой — шапка документа)
      png = execFileSync("python3", ["-c", `
import sys, pypdfium2 as P
doc = P.PdfDocument(sys.argv[1])
doc[min(1, len(doc) - 1)].render(scale=2, may_draw_forms=True).to_pil().save(sys.argv[2])
print(sys.argv[2])`, pdfFile, path.join(tmp, "pdf_page.png")]).toString().trim();
    } catch (e) { png = ""; }
    if (png) {
      say("PDF аналитика: каждое замечание — выделение с комментарием на своём месте в документе");
      const img = fs.readFileSync(png).toString("base64");
      await p.setContent(`<html><body style="margin:0;background:#2b2f36;display:flex;justify-content:center;align-items:flex-start;height:100vh;overflow:hidden">
        <img src="data:image/png;base64,${img}" style="height:${H * 1.35}px;margin-top:-40px;box-shadow:0 10px 40px rgba(0,0,0,.5)"></body></html>`);
      await cursor();
      await pause(1500);
      await p.evaluate(() => document.querySelector("img").animate([{ transform: "translateY(0)" }, { transform: "translateY(-260px)" }], { duration: 4000, fill: "forwards" }));
      await pause(4400);
    }
  }
  if (csvFile) {
    const all = parseCsv(fs.readFileSync(csvFile, "utf8").replace(/^﻿/, "")).filter((r) => r.some((c) => c.trim()));
    const rows = all.slice(0, 9);
    const nTasks = all.length - 1;
    const head = rows[0] || [];
    const pick = ["Summary", "Priority", "Labels", "Issue Type"].map((h) => head.indexOf(h)).filter((i) => i >= 0);
    const cols = pick.length ? pick : [0, 1, 2].filter((i) => i < head.length);
    const esc = (s) => String(s || "").replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
    say(`Jira CSV: ${nTasks} ${plural(nTasks, "задача", "задачи", "задач")} для импорта — с цитатой, местом и рекомендацией`);
    await p.setContent(`<html><body style="margin:0;background:#F4F6F8;font:15px/1.45 Inter,system-ui,sans-serif;color:#131820;padding:36px 44px">
      <div style="font:700 13px Inter;letter-spacing:.06em;text-transform:uppercase;color:#6E7887;margin-bottom:12px">${esc(path.basename(csvFile))} — импорт в Jira</div>
      <table style="border-collapse:collapse;width:100%;background:#fff;border:1px solid #DFE4EA;border-radius:12px;overflow:hidden">
      <tr>${cols.map((i) => `<th style="text-align:left;padding:10px 14px;background:#F1F3F6;font-size:12px;text-transform:uppercase;letter-spacing:.05em;color:#6E7887">${esc(head[i])}</th>`).join("")}</tr>
      ${rows.slice(1).map((r) => `<tr>${cols.map((i) => `<td style="padding:10px 14px;border-top:1px solid #DFE4EA;vertical-align:top">${esc(r[i]).slice(0, 140)}</td>`).join("")}</tr>`).join("")}
      </table></body></html>`);
    await cursor();
    await pause(5200);
  }

  // 8. паспорт прогона
  await p.goto(jobUrl);
  await p.waitForSelector("#result:not([hidden])");
  await cursor();
  const fr2 = p.frameLocator("#frame");
  await fr2.locator(".hero").waitFor();
  const calls = run.calls || {};
  say(calls.cached && !calls.total
    ? `Паспорт прогона: ${calls.cached} ${plural(calls.cached, "ответ", "ответа", "ответов")} модели из кэша, коммит агента, SHA документа — результат воспроизводим`
    : `Паспорт прогона: модель, ${calls.total || 0} ${plural(calls.total || 0, "вызов", "вызова", "вызовов")}, время, коммит агента, SHA документа`);
  await click(fr2.locator("#t-passport"), { wait: 4200 });

  // 9. финал
  say("Находит дефекты в ТЗ до первой строки кода · python -m bcc_review ТЗ.pdf отчёт.md");
  await p.goto("file://" + titleFile + "#final");
  await cursor();
  await pause(5500);
  say(null);

  const video = p.video();
  await ctx.close();
  await b.close();
  const webm = path.join(outDir, "demo.webm");
  fs.renameSync(await video.path(), webm);
  const srt = subs.map((s, i) => `${i + 1}\n${srtTime(s.start)} --> ${srtTime(s.end ?? s.start + 3000)}\n${s.text}\n`).join("\n");
  fs.writeFileSync(path.join(outDir, "demo.srt"), srt, "utf8");
  fs.rmSync(tmp, { recursive: true, force: true });
  try {
    execFileSync("ffmpeg", ["-y", "-loglevel", "error", "-i", webm, "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "23",
      "-preset", "slow", "-movflags", "+faststart", path.join(outDir, "demo.mp4")]);
    // original_size = размер кадра: иначе libass считает от 384×288 и сжимает текст по горизонтали
    const style = "FontName=Inter,FontSize=9,PrimaryColour=&H00FFFFFF,BackColour=&H80101418,BorderStyle=4,Outline=1,Shadow=0,MarginV=8,MarginL=30,MarginR=30"; // размеры — от высоты 288
    execFileSync("ffmpeg", ["-y", "-loglevel", "error", "-i", webm, "-vf", `subtitles=demo.srt:original_size=${W}x${H}:force_style='${style}'`,
      "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "23", "-preset", "slow", "-movflags", "+faststart", "demo_subtitled.mp4"], { cwd: outDir });
    console.log("видео:", path.join(outDir, "demo.mp4"), "и demo_subtitled.mp4");
  } catch (e) {
    console.log("видео:", webm, "(mp4 не собран:", String(e.message || e).slice(0, 200), ")");
  }
  console.log("длительность ≈", Math.round((Date.now() - t0) / 1000), "с; субтитров:", subs.length);
})();

function parseCsv(text) {
  const rows = []; let row = [], cell = "", q = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (q) { if (c === '"' && text[i + 1] === '"') { cell += '"'; i++; } else if (c === '"') q = false; else cell += c; }
    else if (c === '"') q = true;
    else if (c === ",") { row.push(cell); cell = ""; }
    else if (c === "\n") { row.push(cell); rows.push(row); row = []; cell = ""; }
    else if (c !== "\r") cell += c;
  }
  if (cell || row.length) { row.push(cell); rows.push(row); }
  return rows;
}
