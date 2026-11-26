#!/usr/bin/env node
/*
 * Браузерная проверка автономного HTML-отчёта (№13).
 *
 * Запуск (pytest делает это сам, см. tests/p13/test_html_browser.py):
 *   NODE_PATH="$(npm root -g)" node tests/p13/browser/check_report.cjs WORKDIR [SCREENSHOT_DIR]
 *
 * WORKDIR содержит пары <variant>.html и <variant>.json (synthetic, empty,
 * partial, partial_empty, long). Результат пишется в WORKDIR/results.json:
 * [{name, ok, details}], а выгруженный файл ответов — в WORKDIR/answers-*.md.
 * Все страницы открываются по file:// в офлайн-контексте. Любой сетевой
 * запрос, диалог, ошибка JS или нарушение CSP считается провалом.
 */
'use strict';
const fs = require('fs');
const path = require('path');
let chromium;
try {
  ({ chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright'));
} catch (err) {
  console.error('playwright not found: ' + err.message);
  process.exit(3);
}

const work = path.resolve(process.argv[2] || '.');
const shots = process.argv[3] ? path.resolve(process.argv[3]) : null;
const url = (name, hash) => 'file://' + path.join(work, name + '.html') + (hash || '');
const report = (name) => JSON.parse(fs.readFileSync(path.join(work, name + '.json'), 'utf8'));
const results = [];
const LAPTOP = { width: 1366, height: 768 };
const NARROW = { width: 375, height: 740 };

async function check(name, fn) {
  try {
    const details = await fn();
    results.push({ name, ok: true, details: details || '' });
  } catch (err) {
    results.push({ name, ok: false, details: String(err && err.stack || err) });
  }
}
function assert(cond, msg) { if (!cond) throw new Error(msg); }

async function open(browser, name, opts) {
  opts = opts || {};
  const ctx = opts.ctx || await browser.newContext({ viewport: opts.viewport || LAPTOP, offline: true, acceptDownloads: true });
  const page = await ctx.newPage();
  const problems = [];
  page.on('pageerror', (e) => problems.push('pageerror: ' + e.message));
  page.on('console', (m) => { if (m.type() === 'error') problems.push('console: ' + m.text()); });
  page.on('dialog', (d) => { problems.push('dialog: ' + d.message()); d.dismiss().catch(() => {}); });
  const requests = [];
  await page.route('**/*', (route) => {
    const u = route.request().url();
    if (u.startsWith('file://') || u.startsWith('blob:') || u.startsWith('data:')) return route.continue();
    requests.push(u);
    return route.abort();
  });
  if (opts.init) await page.addInitScript(opts.init);
  await page.goto(url(name, opts.hash), { waitUntil: 'load' });
  return { ctx, page, problems, requests };
}

const activeInfo = (page) => page.evaluate(() => {
  const a = document.activeElement;
  const blk = a && a.closest && a.closest('[data-block]');
  return {
    cls: a ? a.className : '',
    tag: a ? a.tagName : '',
    block: blk ? blk.getAttribute('data-block') : null,
    cp: a && a.getAttribute ? a.getAttribute('data-cp') : null,
    ev: a && a.getAttribute ? a.getAttribute('data-ev') : null,
    text: a ? a.textContent : '',
    outline: a ? getComputedStyle(a).outlineStyle : '',
  };
});
const stateOf = (page) => page.evaluate(() => window.bccReview.state());
const segText = (page, evId) => page.evaluate((id) => Array.from(document.querySelectorAll('#doc-scroll .hl'))
  .filter((el) => el.getAttribute('data-ev').split(' ').includes(id)).map((el) => el.textContent).join(''), evId);

(async () => {
  const browser = await chromium.launch();
  const syn = report('synthetic');
  const byId = Object.fromEntries(syn.findings.map((f) => [f.id, f]));

  await check('offline: файл открывается без сети, без ошибок JS и CSP', async () => {
    const { page, problems, requests, ctx } = await open(browser, 'synthetic');
    const meta = await page.evaluate(() => ({
      csp: document.querySelector('meta[http-equiv="Content-Security-Policy"]').content,
      external: Array.from(document.querySelectorAll('[src],link[href]')).map((e) => e.getAttribute('src') || e.getAttribute('href')),
    }));
    await ctx.close();
    assert(requests.length === 0, 'сетевые запросы: ' + requests.join(', '));
    assert(problems.length === 0, problems.join('\n'));
    assert(meta.external.length === 0, 'внешние ресурсы: ' + meta.external.join(', '));
    return 'requests=0; ' + meta.csp.slice(0, 60) + '…';
  });

  await check('текст блоков в DOM равен block.text из JSON (кириллица, emoji, HTML-подобный текст, CRLF, таблица)', async () => {
    const { page, ctx } = await open(browser, 'synthetic');
    const dom = await page.evaluate(() => Object.fromEntries(Array.from(document.querySelectorAll('[data-block]'))
      .map((el) => [el.getAttribute('data-block'), el.querySelector('[data-text]').textContent])));
    const injected = await page.evaluate(() => ({
      scripts: document.querySelectorAll('#doc-scroll script, .fc-body script').length,
      bolds: document.querySelectorAll('#doc-scroll b').length,
    }));
    await ctx.close();
    const bad = syn.document.blocks.filter((b) => dom[b.id] !== b.text).map((b) => b.id);
    assert(bad.length === 0, 'расхождение текста в блоках: ' + bad.join(', '));
    assert(injected.scripts === 0 && injected.bolds === 0, 'HTML из исходника стал разметкой: ' + JSON.stringify(injected));
    const emoji = syn.document.blocks.find((b) => b.text.includes('🔔'));
    const crlf = syn.document.blocks.find((b) => b.text.includes('\r\n'));
    assert(dom[emoji.id] === emoji.text && dom[crlf.id].includes('\r\n'), 'emoji/CRLF не сохранились');
    return 'блоков: ' + syn.document.blocks.length + '; <script> в документе: 0';
  });

  await check('самопроверка подсветки: все опоры совпали, подсказка без координат не подсвечена', async () => {
    const { page, ctx } = await open(browser, 'synthetic');
    const r = await page.evaluate(() => ({ check: window.bccReview.domCheck, text: document.getElementById('dom-check').textContent }));
    const f9 = await page.evaluate(() => ({
      hint: document.querySelector('#finding-F-009 .q-hint') !== null,
      buttons: document.querySelectorAll('#finding-F-009 .q-btn').length,
    }));
    await ctx.close();
    assert(r.check.bad.length === 0 && r.check.total > 20, JSON.stringify(r.check));
    assert(f9.hint && f9.buttons === 0, 'F-009: подсказка показана как подтверждённая опора ' + JSON.stringify(f9));
    return r.text;
  });

  await check('одинаковая цитата «Да / Нет»: каждая кнопка ведёт к своему вхождению, возврат сохраняет выбор (F-006)', async () => {
    const { page, ctx } = await open(browser, 'synthetic');
    const evs = byId['F-006'].evidence;
    assert(evs[0].quote === evs[1].quote && evs[0].block_id !== evs[1].block_id, 'фикстура: нужна одинаковая цитата в разных блоках');
    const firstIdx = syn.document.blocks.find((b) => b.id === evs[0].block_id).text.indexOf(evs[0].quote);
    assert(firstIdx !== evs[0].start, 'фикстура: первая опора должна быть вторым вхождением в блоке');
    await page.click('#finding-F-006 .fc-toggle');
    const btns = page.locator('#finding-F-006 .q-btn');
    const seen = [];
    for (const i of [0, 1]) {
      await btns.nth(i).click();
      const a = await activeInfo(page);
      assert(a.block === evs[i].block_id, 'цитата ' + (i + 1) + ': фокус в блоке ' + a.block + ', ожидался ' + evs[i].block_id);
      assert(a.cp && +a.cp.split(':')[0] === evs[i].start, 'цитата ' + (i + 1) + ': начало ' + a.cp + ', ожидалось ' + evs[i].start);
      const visible = await page.evaluate(() => {
        const r = document.activeElement.getBoundingClientRect();
        const c = document.getElementById('doc-scroll').getBoundingClientRect();
        return r.top >= c.top && r.bottom <= c.bottom;
      });
      assert(visible, 'цитата ' + (i + 1) + ' вне видимой области документа');
      seen.push(a.block + ':' + a.cp);
      await page.click('#ret-back');
      await page.waitForFunction(() => document.activeElement && document.activeElement.classList.contains('q-btn'));
      const st = await stateOf(page);
      const back = await page.evaluate(() => ({
        ev: document.activeElement.getAttribute('data-ev'),
        expanded: document.querySelector('#finding-F-006 .fc-toggle').getAttribute('aria-expanded'),
      }));
      assert(st.selected === 'F-006' && back.expanded === 'true', 'выбор потерян: ' + JSON.stringify(st));
      assert(back.ev === (await btns.nth(i).getAttribute('data-ev')), 'фокус вернулся не на цитату ' + (i + 1));
      assert(st.hash === '#finding-F-006', 'якорь ' + st.hash);
    }
    await ctx.close();
    return seen.join(' и ') + ' (первое вхождение в блоке первой цитаты: ' + firstIdx + ')';
  });

  await check('конфликт F-001: обе стороны кликабельны, Escape и «Назад» браузера возвращают к замечанию', async () => {
    const { page, ctx } = await open(browser, 'synthetic');
    const w = byId['F-001'].witness;
    await page.click('#finding-F-001 .fc-toggle');
    await page.click('#finding-F-001 .q-btn[data-side="b"]');
    let a = await activeInfo(page);
    assert(a.block === w.evidence_b.block_id && +a.cp.split(':')[0] === w.evidence_b.start, 'сторона B: ' + JSON.stringify(a));
    const bText = await segText(page, a.ev.split(' ')[0]);
    assert(bText === w.evidence_b.quote, 'текст B: ' + bText);
    await page.keyboard.press('Escape');
    await page.waitForFunction(() => document.activeElement.getAttribute('data-side') === 'b');
    let st = await stateOf(page);
    assert(st.selected === 'F-001' && !st.returnPending, 'после Escape: ' + JSON.stringify(st));
    await page.click('#finding-F-001 .q-btn[data-side="a"]');
    a = await activeInfo(page);
    assert(a.block === w.evidence_a.block_id && +a.cp.split(':')[0] === w.evidence_a.start, 'сторона A: ' + JSON.stringify(a));
    assert((await stateOf(page)).hash.startsWith('#block-'), 'переход к цитате не создал запись истории');
    await page.goBack();
    await page.waitForFunction(() => document.activeElement.getAttribute('data-side') === 'a');
    st = await stateOf(page);
    const labels = await page.evaluate(() => Array.from(document.querySelectorAll('.hl.ev-first[data-side-label]')).map((e) => e.getAttribute('data-side-label')).sort().join(''));
    await ctx.close();
    assert(st.selected === 'F-001' && st.hash === '#finding-F-001', 'после «Назад»: ' + JSON.stringify(st));
    assert(labels === 'AB', 'метки сторон в документе: ' + labels);
    return 'A=' + w.evidence_a.block_id + ', B=' + w.evidence_b.block_id;
  });

  await check('наложенные подсветки: общий сегмент, выбор из документа, точный текст каждой находки', async () => {
    const { page, ctx } = await open(browser, 'synthetic');
    const f2 = byId['F-002'].witness.evidence_a;
    const f8 = byId['F-008'].evidence[0];
    assert(f2.block_id === f8.block_id && f8.start < f2.end && f2.start < f8.end, 'фикстура без пересечения');
    const shared = page.locator('#doc-scroll .hl[data-n="2"]', { hasText: 'покупки в Алматы' }).first();
    await shared.click();
    await page.waitForSelector('#chooser:not([hidden])');
    const options = await page.locator('#chooser-list button').evaluateAll((bs) => bs.map((b) => b.getAttribute('data-fid')).sort());
    assert(options.join(',') === 'F-002,F-008', 'варианты: ' + options);
    await page.click('#chooser-list button[data-fid="F-008"]');
    const st = await stateOf(page);
    const onText = await page.evaluate(() => Array.from(document.querySelectorAll('#doc-scroll .hl.on')).map((e) => e.textContent).join('|'));
    await page.click('#finding-F-002 .fc-toggle');
    const onText2 = await page.evaluate(() => Array.from(document.querySelectorAll('#doc-scroll .hl.on')).map((e) => e.textContent).join(''));
    await ctx.close();
    assert(st.selected === 'F-008', 'выбрано ' + st.selected);
    assert(onText.split('|').join('').includes(f8.quote), 'подсветка F-008: ' + onText);
    assert(onText2.includes(f2.quote), 'подсветка F-002: ' + onText2);
    return 'пересечение ' + Math.max(f2.start, f8.start) + '–' + Math.min(f2.end, f8.end) + ' в ' + f2.block_id;
  });

  await check('emoji до цитаты: подсветка совпадает, cpToUtf16 даёт верный индекс JS', async () => {
    const { page, ctx } = await open(browser, 'synthetic');
    const ev = byId['F-012'].evidence[0];
    const block = syn.document.blocks.find((b) => b.id === ev.block_id);
    await page.click('#finding-F-012 .fc-toggle');
    await page.locator('#finding-F-012 .q-btn').first().click();
    const a = await activeInfo(page);
    const conv = await page.evaluate(([t, s, e]) => {
      const u0 = window.bccReview.cpToUtf16(t, s), u1 = window.bccReview.cpToUtf16(t, e);
      return { u0, u1, slice: t.slice(u0, u1), naive: t.slice(s, e) };
    }, [block.text, ev.start, ev.end]);
    await ctx.close();
    assert(a.text === ev.quote, 'фокус на «' + a.text + '»');
    assert(conv.slice === ev.quote, 'cpToUtf16: ' + JSON.stringify(conv));
    assert(conv.naive !== ev.quote, 'наивный срез случайно совпал — проверка вырождена');
    return 'кодовые точки ' + ev.start + '–' + ev.end + ' → UTF-16 ' + conv.u0 + '–' + conv.u1 + '; наивный срез: «' + conv.naive + '»';
  });

  await check('фильтры: серьёзность, критерий, поиск, пустой результат и сброс', async () => {
    const { page, ctx } = await open(browser, 'synthetic');
    await page.uncheck('input[name=sev][value=critical]');
    await page.uncheck('input[name=sev][value=major]');
    const minorOnly = await page.evaluate(() => Array.from(document.querySelectorAll('.fc')).filter((c) => !c.parentNode.hidden).map((c) => c.dataset.sev));
    assert(minorOnly.length > 0 && minorOnly.every((s) => s === 'minor'), 'после фильтра: ' + minorOnly);
    await page.click('button[type=reset]');
    await page.selectOption('select[name=crit]', 'set_consistent');
    const crit = await page.evaluate(() => Array.from(document.querySelectorAll('.fc')).filter((c) => !c.parentNode.hidden).map((c) => c.dataset.fid));
    assert(crit.join(',') === 'F-001', 'критерий set_consistent: ' + crit);
    await page.selectOption('select[name=crit]', '');
    await page.selectOption('select[name=blocks]', 'testing');
    const blk = await page.evaluate(() => Array.from(document.querySelectorAll('.fc')).filter((c) => !c.parentNode.hidden).map((c) => c.dataset.fid).sort());
    assert(blk.join(',') === 'F-001,F-002,F-008', 'блокирует тестирование: ' + blk);
    await page.selectOption('select[name=blocks]', '');
    await page.fill('input[name=q]', 'нет-такого-текста');
    const empty = await page.isVisible('#f-empty');
    const count = await page.textContent('#f-count');
    await page.click('#f-reset');
    const after = await page.evaluate(() => Array.from(document.querySelectorAll('.fc')).filter((c) => !c.parentNode.hidden).length);
    await ctx.close();
    assert(empty && /Показано 0 из/.test(count), 'пустое состояние: ' + empty + ' ' + count);
    assert(after === syn.findings.length, 'после сброса: ' + after);
    return count;
  });

  await check('клавиатура: стрелки по списку, Enter, Tab к цитате, Escape возвращает фокус', async () => {
    const { page, ctx } = await open(browser, 'synthetic');
    await page.focus('.fc-toggle');
    const first = (await activeInfo(page)).text;
    await page.keyboard.press('ArrowDown');
    const second = await activeInfo(page);
    assert(second.text !== first && second.cls.includes('fc-toggle'), 'ArrowDown не сдвинул фокус');
    await page.keyboard.press('Enter');
    const fid = (await stateOf(page)).selected;
    assert(fid, 'Enter не выбрал замечание');
    let guard = 0;
    while (!(await activeInfo(page)).cls.includes('q-btn') && guard++ < 25) await page.keyboard.press('Tab');
    const q = await activeInfo(page);
    assert(q.cls.includes('q-btn'), 'Tab не дошёл до цитаты');
    assert(q.outline !== 'none', 'нет видимого фокуса на кнопке цитаты');
    await page.keyboard.press('Enter');
    const inDoc = await activeInfo(page);
    assert(inDoc.cls.includes('hl'), 'Enter на цитате не перевёл фокус в документ: ' + inDoc.cls);
    await page.keyboard.press('Escape');
    await page.waitForFunction(() => document.activeElement.classList.contains('q-btn'));
    const st = await stateOf(page);
    const name = await page.evaluate(() => document.activeElement.innerText.replace(/\s+/g, ' ').trim());
    await ctx.close();
    assert(st.selected === fid, 'выбор потерян');
    return 'замечание ' + fid + '; имя кнопки: «' + name.slice(0, 70) + '…»';
  });

  await check('узкое окно 375 px: нет горизонтальной прокрутки страницы, переключение панелей, переход и возврат', async () => {
    const { page, ctx } = await open(browser, 'synthetic', { viewport: NARROW });
    const ov = await page.evaluate(() => ({ sw: document.documentElement.scrollWidth, w: window.innerWidth }));
    assert(ov.sw <= ov.w, 'горизонтальная прокрутка: ' + JSON.stringify(ov));
    assert(await page.isVisible('.ws-switch'), 'нет переключателя панелей');
    assert(!(await page.isVisible('#doc-pane')), 'документ виден в режиме «Замечания»');
    await page.click('#finding-F-001 .fc-toggle');
    if (shots) await page.screenshot({ path: path.join(shots, 'narrow-finding.png') });
    await page.click('#finding-F-001 .q-btn[data-side="b"]');
    const st1 = await stateOf(page);
    const inView = await page.evaluate(() => { const r = document.activeElement.getBoundingClientRect(); return r.top >= 0 && r.bottom <= window.innerHeight; });
    if (shots) await page.screenshot({ path: path.join(shots, 'narrow-quote.png') });
    const table = await page.evaluate(() => {
      const t = Array.from(document.querySelectorAll('.blk-table_row [data-text]')).pop();
      return { sw: t.scrollWidth, cw: t.clientWidth, page: document.documentElement.scrollWidth, w: window.innerWidth };
    });
    await page.click('#ret-back');
    await page.waitForFunction(() => document.activeElement.getAttribute('data-side') === 'b');
    const st2 = await stateOf(page);
    await ctx.close();
    assert(st1.view === 'doc' && inView, 'переход: ' + JSON.stringify(st1) + ' inView=' + inView);
    assert(table.sw > table.cw && table.page <= table.w, 'длинная таблица: ' + JSON.stringify(table));
    assert(st2.view === 'findings' && st2.selected === 'F-001', 'возврат: ' + JSON.stringify(st2));
    return 'scrollWidth=' + ov.sw + ' ≤ ' + ov.w + '; таблица прокручивается внутри блока (' + table.sw + ' > ' + table.cw + ')';
  });

  await check('длинный документ на ноутбуке: загрузка, глубокая ссылка #finding-…, без горизонтальной прокрутки', async () => {
    const rep = report('long');
    const target = rep.findings[rep.findings.length - 3];
    const t0 = Date.now();
    const { page, ctx, problems } = await open(browser, 'long', { hash: '#finding-' + target.id });
    const ms = Date.now() - t0;
    await page.waitForFunction((id) => window.bccReview && window.bccReview.state().selected === id, target.id);
    const vis = await page.evaluate(() => {
      const on = document.querySelector('#doc-scroll .hl.on');
      const c = document.getElementById('doc-scroll').getBoundingClientRect();
      const r = on ? on.getBoundingClientRect() : null;
      return { on: !!on, inView: !!r && r.top >= c.top && r.bottom <= c.bottom, sw: document.documentElement.scrollWidth, w: window.innerWidth, check: window.bccReview.domCheck };
    });
    await ctx.close();
    assert(problems.length === 0, problems.join('\n'));
    assert(vis.on && vis.inView, 'опора глубокой ссылки не видна: ' + JSON.stringify(vis));
    assert(vis.sw <= vis.w, 'горизонтальная прокрутка');
    assert(vis.check.bad.length === 0, 'самопроверка: ' + JSON.stringify(vis.check));
    return 'блоков ' + rep.document.blocks.length + ', замечаний ' + rep.findings.length + ', загрузка ' + ms + ' мс, опор проверено ' + vis.check.total;
  });

  await check('глубокая ссылка #block-…: документ прокручен к блоку', async () => {
    const b = syn.document.blocks[60];
    const { page, ctx } = await open(browser, 'synthetic', { hash: '#block-' + b.id, viewport: NARROW });
    const r = await page.evaluate(() => ({ view: window.bccReview.state().view, focus: document.activeElement.getAttribute('data-block') }));
    await ctx.close();
    assert(r.view === 'doc' && r.focus === b.id, JSON.stringify(r));
    return b.id;
  });

  await check('пустой отчёт и неполный прогон: честные пустые состояния', async () => {
    let o = await open(browser, 'empty');
    const empty = await o.page.evaluate(() => ({
      none: document.getElementById('f-none') && document.getElementById('f-none').textContent,
      disabled: document.querySelector('#filters fieldset').disabled,
      questions: document.getElementById('questions').textContent,
      diff: document.getElementById('diff').textContent,
    }));
    await o.ctx.close();
    o = await open(browser, 'partial_empty');
    const pe = await o.page.evaluate(() => document.getElementById('f-none').textContent + ' | ' + document.querySelector('.banner-run').textContent + ' | ' + document.querySelector('.prelim').textContent);
    await o.ctx.close();
    o = await open(browser, 'partial');
    const part = await o.page.evaluate(() => ({ banner: !!document.querySelector('.banner-run'), flags: document.querySelectorAll('.blk-flag').length }));
    await o.ctx.close();
    assert(/Замечаний нет/.test(empty.none) && empty.disabled, 'пустой: ' + JSON.stringify(empty));
    assert(/не запускалось/.test(empty.diff), 'diff пустого: ' + empty.diff);
    assert(/неполный/.test(pe) && /не подтверждено/.test(pe), 'неполный пустой: ' + pe);
    assert(part.banner && part.flags > 0, 'неполный: ' + JSON.stringify(part));
    return pe.slice(0, 120);
  });

  await check('черновик ответов: localStorage по хешу, восстановление, не выдаётся за исправленный документ, экспорт .md', async () => {
    const ctx = await browser.newContext({ viewport: LAPTOP, offline: true, acceptDownloads: true });
    let o = await open(browser, 'synthetic', { ctx });
    const answer1 = '# Да, повторный push разрешён\n\\путь C:\\x\nпосле смены порога 🔔';
    await o.page.fill('textarea[data-qid="Q-01"]', answer1);
    await o.page.fill('textarea[data-qid="Q-03"]', 'Клиринг');
    await o.page.waitForFunction(() => /сохранён/.test(document.getElementById('ans-status').textContent));
    const key = 'bcc-review/answers/v1/' + syn.document.id;
    const stored = await o.page.evaluate((k) => localStorage.getItem(k), key);
    await o.page.reload();
    const restored = await o.page.evaluate(() => ({
      q1: document.querySelector('textarea[data-qid="Q-01"]').value,
      status: document.getElementById('ans-status').textContent,
      verdict: Array.from(document.querySelectorAll('.tile-v')).map((e) => e.textContent.trim()).join(' / '),
      f1: document.querySelector('#finding-F-001 .st').textContent,
      note: document.getElementById('ans-note').textContent,
    }));
    const [dl] = await Promise.all([o.page.waitForEvent('download'), o.page.click('#ans-export')]);
    const file = path.join(work, dl.suggestedFilename());
    await dl.saveAs(file);
    // Другая версия документа (иной хеш) не подхватывает черновик.
    const other = await ctx.newPage();
    await other.goto(url('partial'));
    const otherQ1 = await other.evaluate(() => document.querySelector('textarea[data-qid="Q-03"]').value);
    await ctx.close();
    assert(stored && JSON.parse(stored).answers['Q-01'] === answer1, 'в хранилище: ' + stored);
    assert(restored.q1 === answer1, 'не восстановлено');
    assert(/не учтён/.test(restored.status) && /не меняют исходный документ/.test(restored.note), 'нет пометки черновика');
    assert(restored.verdict === '✕ Нельзя начинать / ✕ Нельзя начинать' && /Подтверждено/.test(restored.f1), 'черновик изменил вердикт/статус: ' + JSON.stringify(restored));
    assert(otherQ1 === '', 'черновик просочился в документ с другим хешем');
    fs.writeFileSync(path.join(work, 'answers-typed.json'), JSON.stringify({ 'Q-01': answer1, 'Q-03': 'Клиринг', file }));
    return dl.suggestedFilename() + '; ' + restored.status.slice(0, 60) + '…';
  });

  await check('хранилище недоступно: предупреждение, ответы всё равно выгружаются', async () => {
    const init = () => {
      Object.defineProperty(window, 'localStorage', { configurable: true, get() { throw new DOMException('denied', 'SecurityError'); } });
    };
    const o = await open(browser, 'synthetic', { init });
    const status = await o.page.textContent('#ans-status');
    await o.page.fill('textarea[data-qid="Q-04"]', 'Нужен GET /alerts/limit');
    const [dl] = await Promise.all([o.page.waitForEvent('download'), o.page.click('#ans-export')]);
    const file = path.join(work, 'no-storage-' + dl.suggestedFilename());
    await dl.saveAs(file);
    const md = fs.readFileSync(file, 'utf8');
    const problems = o.problems;
    await o.ctx.close();
    assert(/недоступно/.test(status), 'статус: ' + status);
    assert(md.includes('## Q-04') && md.includes('Нужен GET /alerts/limit'), 'ответ не выгружен');
    assert(problems.length === 0, problems.join('\n'));
    return status.slice(0, 80) + '…';
  });

  await check('эталон контракта minimal_report.json: подсветка, конфликт, переход к стороне B', async () => {
    if (!fs.existsSync(path.join(work, 'minimal.json'))) return 'пропущено: нет contracts/examples/minimal_report.json';
    const rep = report('minimal');
    const f = rep.findings.find((x) => x.witness);
    const { page, ctx, problems } = await open(browser, 'minimal');
    const chk = await page.evaluate(() => window.bccReview.domCheck);
    await page.click('#' + 'finding-' + f.id + ' .fc-toggle');
    await page.click('#' + 'finding-' + f.id + ' .q-btn[data-side="b"]');
    const a = await activeInfo(page);
    const dom = await page.evaluate(() => Object.fromEntries(Array.from(document.querySelectorAll('[data-block]'))
      .map((el) => [el.getAttribute('data-block'), el.querySelector('[data-text]').textContent])));
    await ctx.close();
    assert(problems.length === 0, problems.join('\n'));
    assert(chk.bad.length === 0 && chk.total > 0, JSON.stringify(chk));
    assert(a.block === f.witness.evidence_b.block_id && +a.cp.split(':')[0] === f.witness.evidence_b.start, JSON.stringify(a));
    assert(rep.document.blocks.every((b) => dom[b.id] === b.text), 'текст блоков эталона расходится');
    return f.id + ': B → ' + a.block + ' ' + a.cp + '; опор проверено ' + chk.total;
  });

  if (shots) {
    await check('снимки экрана: две связанные цитаты конфликта (ноутбук)', async () => {
      const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 2, offline: true });
      const o = await open(browser, 'synthetic', { ctx });
      await o.page.click('#finding-F-001 .fc-toggle');
      await o.page.click('#finding-F-001 .q-btn[data-side="b"]');
      await o.page.evaluate(() => window.scrollTo(0, document.getElementById('workspace').getBoundingClientRect().top + window.pageYOffset - document.querySelector('.bar').offsetHeight));
      await o.page.screenshot({ path: path.join(shots, 'laptop-two-quotes.png') });
      await o.page.evaluate(() => window.scrollTo(0, 0));
      await o.page.screenshot({ path: path.join(shots, 'laptop-summary.png') });
      await ctx.close();
      return 'laptop-two-quotes.png, laptop-summary.png';
    });
  }

  await browser.close();
  fs.writeFileSync(path.join(work, 'results.json'), JSON.stringify(results, null, 1));
  for (const r of results) console.log((r.ok ? 'OK   ' : 'FAIL ') + r.name + (r.details ? '\n     ' + r.details.split('\n')[0] : ''));
  process.exit(results.every((r) => r.ok) ? 0 : 1);
})();
