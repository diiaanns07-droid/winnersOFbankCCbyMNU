// Длинный запуск в настоящем Chromium. Запускается из tests/p15/test_long_run.py.
// Одна форма загрузки отправляется дважды (тот же upload_key, тот же файл), страница
// запуска перезагружается во время обработки, после завершения ссылка открывается заново.
// Аргументы: BASE_URL CASE_PATH OUT_DIR. Результат — JSON в stdout, код 0 при успехе.
const { chromium } = require("playwright");
const path = require("path");

const [base, casePath, outDir] = process.argv.slice(2);
const RUN = /\/runs\/(\d{8}-\d{6}-[0-9a-f]{6})/;
const log = [];
function check(cond, msg) {
  if (!cond) throw new Error("ПРОВЕРКА НЕ ПРОШЛА: " + msg);
  log.push("ok: " + msg);
}

(async () => {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 1200, height: 900 } });
  const page = await ctx.newPage();
  const shot = (p, name) => p.screenshot({ path: path.join(outDir, name + ".png"), fullPage: true });
  const posts = [];
  ctx.on("request", (r) => { if (r.method() === "POST") posts.push(r.url()); });
  const result = { log };
  try {
    await page.goto(base + "/");
    // Первая отправка формы — тем же браузером, до обработчика app.js (фаза захвата):
    // FormData той же формы, затем app.js отправляет форму штатно (вторая отправка).
    await page.evaluate(() => {
      document.addEventListener("change", async (ev) => {
        if (ev.target.id !== "upload-input" || window.__replayed) return;
        window.__replayed = true;
        ev.stopImmediatePropagation();
        const input = ev.target;
        const r = await fetch(input.form.action, { method: "POST", body: new FormData(input.form) });
        sessionStorage.setItem("first_submit_url", r.url);
        input.dispatchEvent(new Event("change"));
      }, true);
    });
    await page.setInputFiles("#upload-input", casePath);
    await page.waitForURL(RUN, { timeout: 30000 });
    result.form_submit_url = page.url();
    result.run_id = page.url().match(RUN)[1];
    result.second_submit_url = result.form_submit_url;
    result.first_submit_url = await page.evaluate(() => sessionStorage.getItem("first_submit_url"));
    check(result.first_submit_url && result.first_submit_url.match(RUN)[1] === result.run_id, "обе отправки формы привели к одному run_id");
    check(page.url().endsWith("?dup=1"), "вторая отправка открыла уже созданный запуск (?dup=1)");
    check((await page.locator("#duplicate").count()) === 1, "страница говорит, что второй анализ не запускался");
    await shot(page, "long-01-double-submit");

    // Обновление страницы во время обработки.
    let reloads = 0;
    for (let i = 0; i < 8; i++) {
      await page.reload();
      const st = await page.getAttribute("body", "data-run-status");
      if (st !== "running" && st !== "started") break;
      reloads++;
      if (reloads === 2) await shot(page, "long-02-reload-running");
      await page.waitForTimeout(300);
    }
    result.reloads_while_running = reloads;
    check(reloads >= 2, "страница перезагружена во время обработки: " + reloads);
    await page.waitForSelector('body[data-run-status="complete"]', { timeout: 60000 });

    // Ссылка после завершения — в новой вкладке.
    const again = await ctx.newPage();
    await again.goto(base + "/runs/" + result.run_id);
    result.final_status = await again.getAttribute("body", "data-run-status");
    check(result.final_status === "complete", "по ссылке после завершения — готовый результат");
    check((await again.locator("#verdict").count()) === 1, "вердикт на месте");
    result.job = (await again.locator("#job").innerText()).trim();
    await shot(again, "long-03-link-after");
    result.upload_posts = posts.filter((u) => u.endsWith("/api/runs")).length;
    check(result.upload_posts === 2, "браузер отправил форму загрузки ровно дважды");
    await browser.close();
    console.log(JSON.stringify(result));
  } catch (err) {
    result.error = String(err && err.stack || err);
    try { await shot(page, "long-error"); } catch (_) {}
    await browser.close();
    console.log(JSON.stringify(result));
    process.exit(1);
  }
})();
