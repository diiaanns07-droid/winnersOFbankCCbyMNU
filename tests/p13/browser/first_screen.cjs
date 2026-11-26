#!/usr/bin/env node
/*
 * Первый экран аналитика (№13): проверка двух локальных HTML в Chromium.
 *
 *   NODE_PATH="$(npm root -g)" node tests/p13/browser/first_screen.cjs OUTDIR [SHOTS]
 *
 * OUTDIR — результат `python tests/p13/first_screen.py OUTDIR` (first-screen.json + оба HTML).
 * Входные JSON читаются из путей манифеста. Результат — OUTDIR/first-screen-results.json:
 * [{name, ok, details}]. Страницы открываются по file:// офлайн; сетевой запрос, ошибка JS или
 * диалог — провал.
 */
'use strict';
const fs = require('fs');
const path = require('path');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');

const out = path.resolve(process.argv[2] || '.');
const shots = process.argv[3] ? path.resolve(process.argv[3]) : null;
const manifest = JSON.parse(fs.readFileSync(path.join(out, 'first-screen.json'), 'utf8'));
const root = path.resolve(__dirname, '..', '..', '..');
const load = (rel) => JSON.parse(fs.readFileSync(path.join(root, rel), 'utf8'));
const PDF = manifest.outputs.requirements_pdf;
const EX = manifest.outputs.conflict_same_amount;
const pdfReport = load(PDF.input);
const exReport = load(EX.input);
const SIZES = [{ width: 390, height: 844 }, { width: 1280, height: 800 }];
const READINESS = { ready: 'Можно начинать', not_ready: 'Нельзя начинать', unknown: 'Не определено' };
const results = [];

async function check(name, fn) {
  try {
    results.push({ name, ok: true, details: (await fn()) || '' });
  } catch (err) {
    results.push({ name, ok: false, details: String((err && err.stack) || err) });
  }
}
function assert(c, m) { if (!c) throw new Error(m); }

async function open(browser, html, { viewport, js = true } = {}) {
  const ctx = await browser.newContext({ viewport, javaScriptEnabled: js, offline: true });
  const page = await ctx.newPage();
  const problems = [];
  page.on('pageerror', (e) => problems.push('pageerror: ' + e.message));
  page.on('console', (m) => { if (m.type() === 'error') problems.push('console: ' + m.text()); });
  page.on('dialog', (d) => { problems.push('dialog: ' + d.message()); d.dismiss().catch(() => {}); });
  await page.route('**/*', (r) => (r.request().url().startsWith('file://') ? r.continue() : (problems.push('net: ' + r.request().url()), r.abort())));
  await page.goto('file://' + html, { waitUntil: 'load' });
  return { ctx, page, problems };
}

/* Главная причина: status_reasons «этап: причина», сгруппированные по тексту (как в html.py). */
function primaryReason(run) {
  const groups = new Map();
  for (const raw of run.status_reasons || []) {
    const text = String(raw).split(/\s+/).join(' ');
    const m = text.match(/^([A-Za-z_][\w#.\-]*):\s+(.+)$/s);
    const [stage, reason] = m ? [m[1], m[2]] : ['', text];
    if (!groups.has(reason)) groups.set(reason, []);
    if (stage && !groups.get(reason).includes(stage)) groups.get(reason).push(stage);
  }
  const sorted = [...groups.entries()].sort((a, b) => b[1].length - a[1].length);
  return sorted.length ? sorted[0][0].replace(/\.$/, '') : null;
}

/* Элементы целиком в первом экране (без прокрутки) и видимы. */
const inFirstScreen = (page, sels) => page.evaluate((list) => list.map((sel) => {
  const el = document.querySelector(sel);
  if (!el) return { sel, ok: false, why: 'нет элемента' };
  const r = el.getBoundingClientRect();
  const visible = r.width > 0 && r.height > 0 && getComputedStyle(el).visibility !== 'hidden';
  return { sel, ok: visible && r.top >= 0 && r.bottom <= window.innerHeight, top: Math.round(r.top), bottom: Math.round(r.bottom), text: el.innerText.replace(/\s+/g, ' ').trim() };
}), sels);

const active = (page) => page.evaluate(() => {
  const a = document.activeElement;
  const blk = a && a.closest('[data-block]');
  const card = a && a.closest('.fc');
  const r = a.getBoundingClientRect();
  return {
    cls: a.className, side: a.getAttribute('data-side'), card: card ? card.id : null,
    block: blk ? blk.getAttribute('data-block') : null, cp: a.getAttribute('data-cp'), ev: a.getAttribute('data-ev'),
    inView: r.top >= 0 && r.bottom <= window.innerHeight,
  };
});
const segText = (page, ev) => page.evaluate((id) => Array.from(document.querySelectorAll('#doc-scroll .hl'))
  .filter((el) => el.getAttribute('data-ev').split(' ').includes(id)).map((el) => el.textContent).join(''), ev);

(async () => {
  const browser = await chromium.launch();
  const reason = primaryReason(pdfReport.run);
  const crit = exReport.findings.find((f) => f.severity === 'critical' && f.witness);
  const W = crit.witness;
  const card = '#finding-' + crit.id;

  await check('оба HTML собраны одной версией генератора', async () => {
    const shas = [];
    for (const item of [PDF, EX]) {
      const { ctx, page } = await open(browser, item.html, { viewport: SIZES[1] });
      shas.push(await page.evaluate(() => document.querySelector('meta[name="bcc-review:generator-sha256"]').content));
      await ctx.close();
    }
    assert(shas[0] === shas[1] && shas[0] === manifest.generator_sha256, JSON.stringify(shas));
    return 'generator-sha256 ' + shas[0].slice(0, 16) + '…';
  });

  for (const vp of SIZES) {
    for (const js of [true, false]) {
      await check(`requirements_pdf, ${vp.width} px, JS ${js ? 'вкл' : 'выкл'}: на первом экране статус partial, причина и оба вывода`, async () => {
        const { ctx, page, problems } = await open(browser, PDF.html, { viewport: vp, js });
        const boxes = await inFirstScreen(page, ['#verdict-development', '#verdict-testing', '#run-state']);
        const sw = await page.evaluate(() => document.documentElement.scrollWidth);
        const quotes = await page.evaluate(() => ({
          marks: Array.from(document.querySelectorAll('#doc-scroll mark.hl')).filter((m) => m.textContent.trim()).length,
          buttons: Array.from(document.querySelectorAll('.fc .q-btn q')).filter((q) => q.offsetParent !== null && q.textContent.trim()).length,
        }));
        if (shots) await page.screenshot({ path: path.join(shots, `requirements_pdf-${vp.width}-${js ? 'js' : 'nojs'}.png`) });
        await ctx.close();
        for (const b of boxes) assert(b.ok, 'вне первого экрана: ' + JSON.stringify(b));
        const [dev, test, run] = boxes;
        assert(dev.text.includes(READINESS[pdfReport.verdict.development.status]), 'разработка: ' + dev.text);
        assert(test.text.includes(READINESS[pdfReport.verdict.testing.status]), 'тестирование: ' + test.text);
        assert(run.text.includes('status: ' + pdfReport.run.status) && run.text.includes(reason), 'статус/причина: ' + run.text);
        assert(sw <= vp.width, 'горизонтальная прокрутка ' + sw);
        // Без JS карточки раскрыты и цитаты видны сразу; с JS карточка раскрывается по клику.
        assert(quotes.marks > 0 && (js || quotes.buttons > 0), 'цитаты не читаются: ' + JSON.stringify(quotes));
        assert(problems.length === 0, problems.join('\n'));
        return `низ #run-state ${run.bottom} px из ${vp.height}; подсвеченных цитат ${quotes.marks}, цитат в карточках ${quotes.buttons}`;
      });
    }
  }

  for (const vp of SIZES) {
    await check(`conflict_same_amount, ${vp.width} px, мышь: ${crit.id} → цитата A и B → та же карточка`, async () => {
      const { ctx, page, problems } = await open(browser, EX.html, { viewport: vp });
      const top = await inFirstScreen(page, ['#verdict-development', '#verdict-testing']);
      for (const b of top) assert(b.ok && b.text.includes('Нельзя начинать'), 'вердикт: ' + JSON.stringify(b));
      assert(await page.evaluate((sel) => document.querySelector(sel).classList.contains('sev-critical'), card), 'карточка не критичная');
      await page.click(card + ' .fc-toggle');
      const seen = [];
      for (const side of ['a', 'b']) {
        const ev = W['evidence_' + side];
        await page.click(`${card} .q-btn[data-side="${side}"]`);
        const a = await active(page);
        assert(a.block === ev.block_id && +a.cp.split(':')[0] === ev.start, `сторона ${side}: ${JSON.stringify(a)}`);
        assert(a.inView, `сторона ${side}: цитата вне экрана`);
        const text = await segText(page, a.ev.split(' ')[0]);
        assert(text === ev.quote, `сторона ${side}: текст «${text}»`);
        if (shots) await page.screenshot({ path: path.join(shots, `conflict-${vp.width}-quote-${side}.png`) });
        await page.click('#ret-back');
        await page.waitForFunction(([c, s]) => document.activeElement.closest(c) && document.activeElement.getAttribute('data-side') === s, [card, side]);
        const st = await page.evaluate((c) => ({ ...window.bccReview.state(), expanded: document.querySelector(c + ' .fc-toggle').getAttribute('aria-expanded') }), card);
        const back = await active(page);
        assert(st.selected === crit.id && st.expanded === 'true' && st.hash === card && back.card === card.slice(1) && back.inView, `возврат ${side}: ${JSON.stringify({ st, back })}`);
        seen.push(`${side.toUpperCase()} → ${a.block} [${a.cp}]`);
      }
      await ctx.close();
      assert(problems.length === 0, problems.join('\n'));
      return seen.join('; ') + '; возврат к ' + card;
    });

    await check(`conflict_same_amount, ${vp.width} px, клавиатура: Tab/Enter к обеим цитатам, Escape — назад к карточке`, async () => {
      const { ctx, page, problems } = await open(browser, EX.html, { viewport: vp });
      let tabs = 0;
      while (tabs < 400) {
        await page.keyboard.press('Tab');
        tabs++;
        if (await page.evaluate((c) => document.activeElement.matches(c + ' .fc-toggle'), card)) break;
      }
      assert(tabs < 400, 'не дошли до карточки');
      if ((await page.getAttribute(card + ' .fc-toggle', 'aria-expanded')) !== 'true') await page.keyboard.press('Enter');
      const seen = [];
      for (const side of ['a', 'b']) {
        const ev = W['evidence_' + side];
        let n = 0;
        while (n++ < 40) {
          await page.keyboard.press('Tab');
          const a = await active(page);
          if (a.card === card.slice(1) && a.side === side) break;
        }
        await page.keyboard.press('Enter');
        const a = await active(page);
        assert(a.block === ev.block_id && +a.cp.split(':')[0] === ev.start && a.inView, `клавиатура ${side}: ${JSON.stringify(a)}`);
        await page.keyboard.press('Escape');
        await page.waitForFunction(([c, s]) => document.activeElement.closest(c) && document.activeElement.getAttribute('data-side') === s, [card, side]);
        const back = await active(page);
        assert(back.card === card.slice(1) && back.inView, `клавиатура ${side} назад: ${JSON.stringify(back)}`);
        seen.push(`${side.toUpperCase()} ${a.block} [${a.cp}] за ${n} Tab`);
      }
      const sel = await page.evaluate(() => window.bccReview.state().selected);
      await ctx.close();
      assert(sel === crit.id && problems.length === 0, sel + ' ' + problems.join('\n'));
      return `до карточки ${tabs} Tab; ` + seen.join('; ');
    });
  }

  await check('одинаковые суммы: цитата B не ведёт к первому вхождению того же текста', async () => {
    const prefix = W.evidence_b.quote.split(' | ')[0];
    const firstBlock = exReport.document.blocks.find((b) => b.text.includes(prefix));
    const firstAmount = exReport.document.blocks.find((b) => b.text.includes('50 000 ₸'));
    assert(firstBlock.id !== W.evidence_b.block_id, 'вырожденный пример: первое вхождение и есть сторона B');
    const { ctx, page } = await open(browser, EX.html, { viewport: SIZES[1] });
    await page.click(card + ' .fc-toggle');
    await page.click(`${card} .q-btn[data-side="b"]`);
    const a = await active(page);
    await ctx.close();
    assert(a.block === W.evidence_b.block_id && a.block !== firstBlock.id && a.block !== firstAmount.id, JSON.stringify(a));
    return `«${prefix}» впервые в ${firstBlock.id}, сумма «50 000 ₸» впервые в ${firstAmount.id}; B открыл ${a.block} [${a.cp}]`;
  });

  for (const vp of SIZES) {
    await check(`conflict_same_amount, ${vp.width} px, JS выкл: читаются вердикт и обе цитаты`, async () => {
      const { ctx, page, problems } = await open(browser, EX.html, { viewport: vp, js: false });
      const top = await inFirstScreen(page, ['#verdict-development', '#verdict-testing']);
      const data = await page.evaluate((c) => ({
        quotes: Array.from(document.querySelectorAll(c + ' .q-btn[data-side] q')).map((q) => ({ text: q.textContent, visible: q.offsetParent !== null })),
        marks: Object.fromEntries(Array.from(document.querySelectorAll('#doc-scroll [data-block]')).map((b) => [b.getAttribute('data-block'),
          Array.from(b.querySelectorAll('mark.hl')).map((m) => m.textContent).join('')])),
      }), card);
      if (shots) await page.screenshot({ path: path.join(shots, `conflict-${vp.width}-nojs.png`), fullPage: false });
      await ctx.close();
      for (const b of top) assert(b.ok && b.text.includes('Нельзя начинать'), 'вердикт без JS: ' + JSON.stringify(b));
      const texts = data.quotes.map((q) => q.text);
      assert(texts.includes(W.evidence_a.quote) && texts.includes(W.evidence_b.quote) && data.quotes.every((q) => q.visible), JSON.stringify(data.quotes));
      for (const ev of [W.evidence_a, W.evidence_b]) assert(data.marks[ev.block_id].includes(ev.quote), `${ev.block_id}: ${data.marks[ev.block_id]}`);
      assert(problems.length === 0, problems.join('\n'));
      return 'цитаты: ' + texts.map((t) => '«' + t + '»').join(', ');
    });
  }

  await browser.close();
  fs.writeFileSync(path.join(out, 'first-screen-results.json'), JSON.stringify(results, null, 1));
  for (const r of results) console.log((r.ok ? 'OK   ' : 'FAIL ') + r.name + (r.details ? '\n     ' + r.details.split('\n')[0] : ''));
  process.exit(results.every((r) => r.ok) ? 0 : 1);
})();
