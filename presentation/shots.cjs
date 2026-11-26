// Скриншоты для README и слайдов (№14): node presentation/shots.cjs <report.html> <out_dir> [web_url]
//   report_first.png — первый экран HTML-отчёта; report_card.png — карточка критичного дефекта с подсветкой
//   в документе; report_dark.png — тёмная тема; web_upload.png / web_progress.png / web_report.png — веб-демо
//   (если передан адрес запущенного `python -m bcc_review.v2.web`, загрузка идёт с провайдером mock).
const { chromium } = require("playwright");
const path = require("path");

(async () => {
  const [report, outDir, webUrl, uploadFile] = process.argv.slice(2);
  const out = (n) => path.join(outDir, n);
  const b = await chromium.launch();
  const ctx = await b.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 2, colorScheme: "light" });
  const p = await ctx.newPage();
  await p.goto("file://" + path.resolve(report));
  await p.waitForTimeout(300);
  await p.screenshot({ path: out("report_first.png") });

  // карточка первого критичного дефекта: документ прокручен к цитате, цитаты выделены
  const id = await p.evaluate(() => { const c = document.querySelector('.card[data-sev="critical"]'); return c && c.id; });
  if (id) {
    await p.evaluate(() => { const t = document.querySelector(".tabs"); window.scrollTo(0, t.getBoundingClientRect().top + window.scrollY - 60); });
    await p.waitForTimeout(200);
    await p.evaluate((x) => { const c = document.getElementById(x); c.scrollIntoView({ block: "start" }); c.click(); }, id);
    await p.waitForTimeout(1200);
    await p.screenshot({ path: out("report_card.png") });
  }
  const d = await b.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 2, colorScheme: "dark" });
  const pd = await d.newPage();
  await pd.goto("file://" + path.resolve(report));
  await pd.waitForTimeout(300);
  await pd.screenshot({ path: out("report_dark.png") });

  if (webUrl) {
    const w = await ctx.newPage();
    await w.goto(webUrl);
    if (uploadFile) await w.setInputFiles("#file", uploadFile);
    await w.selectOption("#provider", "mock");
    await w.screenshot({ path: out("web_upload.png") });
    if (uploadFile) await w.click("#go"); else await w.click('button[name="sample"]');
    await w.waitForURL(/\/jobs\//);
    await w.waitForTimeout(1600);
    await w.screenshot({ path: out("web_progress.png") });
    await w.waitForSelector("#result:not([hidden])", { timeout: 600000 });
    await w.waitForTimeout(1500);
    await w.screenshot({ path: out("web_report.png") });
  }
  await b.close();
  console.log("скриншоты →", outDir);
})();
