#!/usr/bin/env node
/*
 * Сценарий «ответ относится к своему вопросу» для HTML-отчёта №13.
 *
 *   NODE_PATH="$(npm root -g)" PYTHONPATH=<src выбранной реализации> \
 *     node tests/p13/browser/answers_scenario.cjs WORKDIR
 *
 * WORKDIR содержит r1.json, r2.json, r3.json — прогоны ОДНОГО документа (один SHA) с разными
 * вопросами под одинаковыми Q-ID. Отчёты по очереди пишутся штатным write_html
 * (`python -m bcc_review.exports.html`) в ОДИН путь WORKDIR/report.html, а Chromium с профилем
 * на диске (launchPersistentContext) перезапускается между шагами. Так область хранения браузера
 * (file://, localStorage) гарантированно общая, как у аналитика, который открыл новый отчёт на месте старого.
 *
 * Скрипт ничего не утверждает: он записывает наблюдения в WORKDIR/answers-scenario.json,
 * а проверки делает pytest (tests/p13/test_answers_binding.py). Поэтому тот же сценарий
 * воспроизводит дефект на прежнем коде.
 */
'use strict';
const fs = require('fs');
const path = require('path');
const { execFileSync } = require('child_process');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');

const work = path.resolve(process.argv[2] || '.');
const PY = process.env.P13_PYTHON || 'python3';
const HTML = path.join(work, 'report.html');
const URL = 'file://' + HTML;
const VIEW = { width: 1366, height: 768 };

const ANS = {
  month: 'Январь: месяц совершения покупки.\nВремя 31.01 23:58 указано по Asia/Almaty.',
  event: 'Авторизация (холд).\nКлиринг только уточняет сумму.',
  push: 'Да: после смены порога разрешён ещё один push в этом месяце.',
  legacy: 'Ответ из черновика старого формата: только Q-ID, без отпечатка вопроса.',
  nostore: 'Отдельный метод GET /alerts/limit возвращает порог и сумму за месяц.',
};

function writeHtml(name) {
  const out = execFileSync(PY, ['-m', 'bcc_review.exports.html', path.join(work, name + '.json'), HTML], { env: process.env });
  return out.toString().trim();
}
function implementation() {
  return execFileSync(PY, ['-c', 'import bcc_review.exports.html as h; print(h.__file__)'], { env: process.env }).toString().trim();
}

async function session(profile, opts, fn) {
  const ctx = await chromium.launchPersistentContext(path.join(work, profile), {
    viewport: VIEW, offline: true, acceptDownloads: true,
  });
  if (opts.init) await ctx.addInitScript(opts.init);
  const page = ctx.pages()[0] || (await ctx.newPage());
  const problems = [];
  const requests = [];
  page.on('pageerror', (e) => problems.push('pageerror: ' + e.message));
  page.on('console', (m) => { if (m.type() === 'error') problems.push('console: ' + m.text()); });
  page.on('dialog', (d) => { problems.push('dialog: ' + d.message()); d.dismiss().catch(() => {}); });
  await page.route('**/*', (route) => {
    const u = route.request().url();
    if (u.startsWith('file://') || u.startsWith('blob:') || u.startsWith('data:')) return route.continue();
    requests.push(u);
    return route.abort();
  });
  try {
    await page.goto(URL, { waitUntil: 'load' });
    const res = await fn(page);
    res.problems = problems;
    res.requests = requests;
    return res;
  } finally {
    await ctx.close();
  }
}

const storage = (page) => page.evaluate(() => {
  try {
    const o = {};
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i);
      if (k.startsWith('bcc-review/')) o[k] = JSON.parse(localStorage.getItem(k));
    }
    return o;
  } catch (e) {
    return { error: String(e && e.name) };
  }
});
const questions = (page) => page.evaluate(() => Array.from(document.querySelectorAll('textarea.ans')).map((t) => ({
  qid: t.getAttribute('data-qid'),
  fp: t.getAttribute('data-qfp'),
  prompt: t.closest('.qa').querySelector('h3').textContent.replace(/\s+/g, ' ').trim(),
  value: t.value,
})));
const panel = (page) => page.evaluate(() => {
  const el = document.getElementById('ans-orphans');
  if (!el || el.hidden) return null;
  return {
    text: el.innerText.replace(/[ \t]+/g, ' ').trim(),
    items: Array.from(el.querySelectorAll('.orphan')).map((li) => ({
      qid: li.getAttribute('data-orphan-qid'),
      kind: li.getAttribute('data-orphan-kind'),
      answer: li.querySelector('textarea').value,
    })),
  };
});
const status = (page) => page.evaluate(() => document.getElementById('ans-status').textContent);
async function waitStored(page, text) {
  const needle = JSON.stringify(text).slice(1, -1);
  await page.waitForFunction((n) => {
    try {
      return Object.keys(localStorage).some((k) => k.startsWith('bcc-review/') && localStorage.getItem(k).includes(n));
    } catch (e) {
      return false;
    }
  }, needle, { timeout: 5000 });
}
async function exportAnswers(page, file) {
  const [dl] = await Promise.all([page.waitForEvent('download'), page.click('#ans-export')]);
  await dl.saveAs(path.join(work, file));
  return { file: path.join(work, file), suggested: dl.suggestedFilename(), text: fs.readFileSync(path.join(work, file), 'utf8') };
}
async function keyboardQuotes(page) {
  const out = { steps: [] };
  const active = () => page.evaluate(() => {
    const a = document.activeElement;
    const blk = a && a.closest('[data-block]');
    return {
      cls: a.className, side: a.getAttribute('data-side'),
      inF1: !!a.closest('#finding-F-001'),
      block: blk ? blk.getAttribute('data-block') : null, cp: a.getAttribute('data-cp'), text: a.textContent,
    };
  });
  let tabs = 0;
  while (tabs < 1500) {
    await page.keyboard.press('Tab');
    tabs++;
    if (await page.evaluate(() => document.activeElement.matches('#finding-F-001 .fc-toggle'))) break;
  }
  out.tabsToF1 = tabs;
  await page.keyboard.press('Enter');
  out.selected = await page.evaluate(() => window.bccReview.state().selected);
  for (const side of ['a', 'b']) {
    let n = 0;
    while (n++ < 30) {
      await page.keyboard.press('Tab');
      const a = await active();
      if (a.inF1 && a.side === side) break;
    }
    await page.keyboard.press('Enter');
    const inDoc = await active();
    await page.keyboard.press('Escape');
    await page.waitForFunction((s) => document.activeElement.getAttribute('data-side') === s, side, { timeout: 3000 }).catch(() => {});
    const back = await active();
    out.steps.push({ side, tabs: n, inDoc, back, selectedAfter: await page.evaluate(() => window.bccReview.state().selected) });
  }
  return out;
}

(async () => {
  const obs = { implementation: implementation(), html_path: HTML };

  // 1. Первый прогон: вводим оба ответа и ждём записи черновика.
  obs.write_r1 = writeHtml('r1');
  obs.step1 = await session('profile-main', {}, async (page) => {
    const qs = await questions(page);
    await page.fill('textarea[data-qid="Q-01"]', ANS.month);
    await page.fill('textarea[data-qid="Q-02"]', ANS.event);
    await waitStored(page, ANS.month);
    await waitStored(page, ANS.event);
    return { questions_loaded: qs, questions_before_close: await questions(page), storage: await storage(page), status: await status(page) };
  });

  // 2. Тот же путь, второй прогон того же документа: перезапуск браузера и загрузка.
  obs.write_r2 = writeHtml('r2');
  obs.step2 = await session('profile-main', {}, async (page) => {
    const loaded = await questions(page);
    const res = { questions_loaded: loaded, panel: await panel(page), status: await status(page), storage_on_load: await storage(page) };
    res.export_as_loaded = await exportAnswers(page, 'answers-r2-as-loaded.md');
    await page.fill('textarea[data-qid="Q-01"]', ANS.push);
    await waitStored(page, ANS.push);
    res.questions_after_push = await questions(page);
    res.storage_after_push = await storage(page);
    res.export = await exportAnswers(page, 'answers-r2.md');
    return res;
  });

  // 3. Третий прогон: тот же вопрос о событии перенумерован в Q-03.
  obs.write_r3 = writeHtml('r3');
  obs.step3 = await session('profile-main', {}, async (page) => ({
    questions_loaded: await questions(page), panel: await panel(page), storage_on_load: await storage(page),
  }));

  // 4. Черновик старого формата (только Q-ID) в чистом профиле.
  obs.write_r2_legacy = writeHtml('r2');
  obs.legacy = await session('profile-legacy', {}, async (page) => {
    const sha = await page.evaluate(() => document.querySelector('meta[name="bcc-review:document-sha256"]').content);
    const legacy = { format: 'bcc-review-answers-draft/1', document_sha256: sha, saved_at: '2026-11-20T10:00:00Z', answers: { 'Q-01': ANS.legacy } };
    await page.evaluate(([k, v]) => localStorage.setItem(k, v), ['bcc-review/answers/v1/' + sha, JSON.stringify(legacy)]);
    await page.reload({ waitUntil: 'load' });
    const res = { injected: legacy, questions_loaded: await questions(page), panel: await panel(page), status: await status(page) };
    await page.fill('textarea[data-qid="Q-02"]', ANS.event);
    await waitStored(page, ANS.event);
    res.storage_after_save = await storage(page);
    return res;
  });

  // 5. Хранилище отключено: загрузка, переход к обеим цитатам с клавиатуры, выгрузка.
  const noStorage = () => {
    Object.defineProperty(window, 'localStorage', { configurable: true, get() { throw new DOMException('denied', 'SecurityError'); } });
  };
  obs.nostore = await session('profile-nostore', { init: noStorage }, async (page) => {
    const res = { status_on_load: await status(page), questions_loaded: await questions(page) };
    res.keyboard = await keyboardQuotes(page);
    await page.fill('textarea[data-qid="Q-01"]', ANS.nostore);
    res.export = await exportAnswers(page, 'answers-r2-nostorage.md');
    res.status_after_export = await status(page);
    return res;
  });

  obs.answers = ANS;
  fs.writeFileSync(path.join(work, 'answers-scenario.json'), JSON.stringify(obs, null, 1));
  console.log('ok ' + path.join(work, 'answers-scenario.json'));
})().catch((err) => {
  console.error(err && err.stack || err);
  process.exit(1);
});
