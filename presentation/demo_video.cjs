// Запись демо для видео (№14): node presentation/demo_video.cjs <адрес веб-демо> <файл ТЗ> <out_dir> [провайдер] [модель]
// Сценарий: загрузка → этапы → отчёт → клики по блокерам (документ подсвечивает цитаты) → вопросы → чек-лист → паспорт.
// Курсор рисуется оверлеем (в headless-записи его нет). Выход: out_dir/demo.webm и demo.mp4 (если есть ffmpeg).
const { chromium } = require("playwright");
const path = require("path");
const fs = require("fs");
const { execFileSync } = require("child_process");

const [base, inputFile, outDir, provider = "mock", model = ""] = process.argv.slice(2);
const W = 1440, H = 900;

const CURSOR = `(() => { if (document.getElementById("__cur")) return;
  const c = document.createElement("div"); c.id = "__cur";
  c.style.cssText = "position:fixed;left:720px;top:450px;width:22px;height:22px;z-index:2147483647;pointer-events:none;transition:left .55s cubic-bezier(.3,.7,.2,1),top .55s cubic-bezier(.3,.7,.2,1);";
  c.innerHTML = '<svg width="22" height="22" viewBox="0 0 22 22"><path d="M3 2l15 9-6.5 1.6L8.5 19z" fill="#111" stroke="#fff" stroke-width="1.6" stroke-linejoin="round"/></svg>';
  const r = document.createElement("div"); r.id = "__ring";
  r.style.cssText = "position:fixed;width:34px;height:34px;margin:-17px 0 0 -17px;border-radius:50%;border:3px solid #0E7C55;opacity:0;z-index:2147483646;pointer-events:none;";
  document.documentElement.append(c, r); })()`;

(async () => {
  fs.mkdirSync(outDir, { recursive: true });
  const b = await chromium.launch();
  const ctx = await b.newContext({ viewport: { width: W, height: H }, recordVideo: { dir: outDir, size: { width: W, height: H } } });
  const p = await ctx.newPage();
  const pause = (ms) => p.waitForTimeout(ms);
  const cursor = async () => { await p.evaluate(CURSOR); };
  async function moveTo(x, y) {
    await cursor();
    await p.evaluate(([x, y]) => { const c = document.getElementById("__cur"); c.style.left = x + "px"; c.style.top = y + "px"; }, [x, y]);
    await pause(650);
  }
  async function click(loc, { wait = 900 } = {}) {
    await loc.scrollIntoViewIfNeeded().catch(() => {});
    const bb = await loc.boundingBox();
    if (bb) {
      const x = bb.x + Math.min(bb.width / 2, 60), y = bb.y + Math.min(bb.height / 2, 18);
      await moveTo(x, y);
      await p.evaluate(([x, y]) => { const r = document.getElementById("__ring"); r.style.left = x + "px"; r.style.top = y + "px";
        r.animate([{ opacity: .9, transform: "scale(.4)" }, { opacity: 0, transform: "scale(1.4)" }], { duration: 500 }); }, [x, y]);
    }
    await loc.click();
    await pause(wait);
  }

  // 1. загрузка
  await p.goto(base);
  await cursor();
  await pause(1500);
  await moveTo(720, 330);
  await p.setInputFiles("#file", inputFile);
  await pause(700);
  await p.selectOption("#provider", provider);
  if (model) await p.fill("#model", model);
  await pause(600);
  await click(p.locator("#go"), { wait: 300 });

  // 2. этапы
  await p.waitForURL(/\/jobs\//);
  await cursor();
  await p.waitForSelector("#result:not([hidden])", { timeout: 1800000 });
  await cursor();
  await pause(1800);

  // 3. отчёт во фрейме
  const fr = p.frameLocator("#frame");
  await fr.locator(".tabs").waitFor();
  await pause(1200);
  const crit = fr.locator('.card[data-sev="critical"]');
  const n = Math.min(await crit.count(), 3);
  await fr.locator(".tabs").evaluate((t) => { const y = t.getBoundingClientRect().top + window.scrollY - 60; window.scrollTo({ top: y, behavior: "smooth" }); });
  await pause(1200);
  for (let i = 0; i < n; i++) {
    await click(crit.nth(i).locator(".ct"), { wait: 2600 });
  }
  const ev = crit.nth(0).locator(".ev").nth(1);
  if (await ev.count()) { await click(ev, { wait: 2200 }); }
  // фильтр: только критичные
  await click(fr.locator('.sevchip[data-sev="major"]'), { wait: 500 });
  await click(fr.locator('.sevchip[data-sev="minor"]'), { wait: 1500 });
  await click(fr.locator('.sevchip[data-sev="major"]'), { wait: 300 });
  await click(fr.locator('.sevchip[data-sev="minor"]'), { wait: 800 });

  // 4. вопросы, чек-лист, паспорт
  await click(fr.locator("#t-questions"), { wait: 1200 });
  const opt = fr.locator(".qcard").first().locator(".opts label").first();
  if (await opt.count()) await click(opt, { wait: 1500 });
  await click(fr.locator("#t-checklist"), { wait: 2500 });
  await click(fr.locator("#t-tests"), { wait: 2200 });
  await click(fr.locator("#t-passport"), { wait: 2500 });
  await click(fr.locator("#t-findings"), { wait: 1200 });

  const video = p.video();
  await ctx.close();
  await b.close();
  const webm = path.join(outDir, "demo.webm");
  fs.renameSync(await video.path(), webm);
  try {
    execFileSync("ffmpeg", ["-y", "-loglevel", "error", "-i", webm, "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20",
      "-movflags", "+faststart", path.join(outDir, "demo.mp4")]);
    console.log("видео:", path.join(outDir, "demo.mp4"));
  } catch (e) {
    console.log("видео:", webm, "(ffmpeg не найден — mp4 не собран)");
  }
})();
