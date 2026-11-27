// №34: сквозной тест вкладки «Вопросы» HTML-отчёта (вызывает tests/v2/test_34_html_answers.py).
// node 34_answers_roundtrip.js report.html plan.json → JSON: текст файла ответов, итог загрузки следующего круга.
const { chromium } = require('playwright');
const fs = require('fs');
(async () => {
  const [file, planPath] = process.argv.slice(2);
  const plan = JSON.parse(fs.readFileSync(planPath, 'utf8'));
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ offline: true });
  const page = await ctx.newPage();
  const errors = [], requests = [];
  page.on('pageerror', e => errors.push('pageerror: ' + e.message));
  page.on('console', m => { if (m.type() === 'error') errors.push('console: ' + m.text()); });
  page.on('request', r => { const u = r.url(); if (!u.startsWith('file:') && !u.startsWith('data:')) requests.push(u); });
  await page.goto('file://' + file);
  await page.click('.tab[data-tab="questions"]');
  for (const f of plan.fill) {
    const c = page.locator('.qcard').nth(f.q);
    if (f.radio >= 0) await c.locator('input[type=radio]').nth(f.radio).check();
    if (f.text) await c.locator('textarea').fill(f.text);
  }
  await page.fill('#decisions', plan.decisions);
  const a = await page.evaluate(() => window.bccReport.answersText());
  const count = await page.textContent('#qcount');
  const load = await page.evaluate(t => window.bccReport.loadAnswers(t), plan.load);
  const states = await page.locator('.qcard .qstate').allTextContents();
  const checked = await page.$$eval('.qcard', cs => cs.map(c => {
    const r = c.querySelector('input[type=radio]:checked');
    return r ? +r.value : -1;
  }));
  console.log(JSON.stringify({ text: a.text, answered: a.answered, count, load, states_after_load: states,
    checked_after_load: checked, errors, requests }));
  await browser.close();
})();
