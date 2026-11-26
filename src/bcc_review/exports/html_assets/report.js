/* bcc_review: автономный HTML-отчёт. Без зависимостей и сетевых запросов. */
(function () {
  'use strict';
  var D;
  try {
    D = JSON.parse(document.getElementById('bcc-data').textContent);
  } catch (err) {
    return;
  }
  var doc = document;
  doc.documentElement.classList.add('js');

  function $(sel, root) { return (root || doc).querySelector(sel); }
  function $$(sel, root) { return Array.prototype.slice.call((root || doc).querySelectorAll(sel)); }

  var live = $('#live');
  var liveTimer = 0;
  function say(msg) {
    if (!live) return;
    clearTimeout(liveTimer);
    live.textContent = '';
    liveTimer = setTimeout(function () { live.textContent = msg; }, 40);
  }

  /* Кодовые точки Unicode → индекс UTF-16. Нужен живому приложению (№15),
     если оно строит подсветку само. Отчёт режет текст заранее в Python. */
  function cpToUtf16(text, cp) {
    var u = 0, i = 0;
    for (var it = text[Symbol.iterator](), step = it.next(); !step.done; step = it.next()) {
      if (i === cp) return u;
      u += step.value.length;
      i++;
    }
    return u;
  }

  var ws = $('#workspace');
  var bar = $('.bar');
  var docScroll = $('#doc-scroll');
  var fScroll = $('#f-scroll');
  var docPane = $('#doc-pane');
  var mq = window.matchMedia ? window.matchMedia('(max-width: 999px)') : { matches: false };
  function isNarrow() { return !!mq.matches; }

  /* ---------------------------------------------------------- индекс сегментов */
  var segs = {};
  $$('.hl', docScroll).forEach(function (el) {
    el.getAttribute('data-ev').split(' ').forEach(function (id) {
      (segs[id] = segs[id] || []).push(el);
    });
  });

  function fidsOfSeg(el) {
    var out = [];
    el.getAttribute('data-ev').split(' ').forEach(function (id) {
      var ev = D.ev[id];
      if (ev) ev.f.forEach(function (f) { if (out.indexOf(f) < 0) out.push(f); });
    });
    return out;
  }

  /* Самопроверка: склеенный текст сегментов опоры равен цитате из JSON,
     а срез textContent блока по кодовым точкам даёт ту же цитату. */
  function domCheck() {
    var total = 0, ok = 0, bad = [];
    Object.keys(D.ev).forEach(function (id) {
      var ev = D.ev[id];
      if (!ev.ok) return;
      total++;
      var list = segs[id] || [];
      var text = '', pos = ev.s, contiguous = true, sameBlock = list.length > 0;
      list.forEach(function (el) {
        var cp = el.getAttribute('data-cp').split(':');
        if (+cp[0] !== pos) contiguous = false;
        pos = +cp[1];
        text += el.textContent;
        var blk = el.closest('[data-block]');
        if (!blk || blk.getAttribute('data-block') !== ev.b) sameBlock = false;
      });
      var bt = list.length ? list[0].closest('[data-text]').textContent : '';
      var bySlice = Array.from(bt).slice(ev.s, ev.e).join('');
      if (text === ev.q && bySlice === ev.q && contiguous && pos === ev.e && sameBlock) ok++;
      else bad.push(id);
    });
    return { total: total, ok: ok, bad: bad };
  }
  var check = domCheck();
  var checkEl = $('#dom-check');
  if (checkEl) {
    checkEl.textContent = check.bad.length
      ? 'Проверка подсветки в браузере: расхождения у ' + check.bad.length + ' из ' + check.total + ' опор (' + check.bad.join(', ') + ').'
      : 'Проверка подсветки в браузере: все ' + check.total + ' подсвеченные цитаты совпадают с JSON по кодовым точкам Unicode.';
    if (check.bad.length) checkEl.classList.add('warn');
  }

  /* ---------------------------------------------------------- карточки */
  var cards = {};
  $$('.fc').forEach(function (c) {
    cards[c.getAttribute('data-fid')] = c;
    collapse(c);
  });
  function toggleOf(c) { return $('.fc-toggle', c); }
  function collapse(c) {
    if (!c) return;
    toggleOf(c).setAttribute('aria-expanded', 'false');
    $('.fc-body', c).hidden = true;
    c.classList.remove('is-sel');
  }
  function expand(c) {
    toggleOf(c).setAttribute('aria-expanded', 'true');
    $('.fc-body', c).hidden = false;
    c.classList.add('is-sel');
  }

  var state = { sel: null, ret: null, retList: [], retIdx: 0, retFid: null };
  var marked = [];
  var lastHash = location.hash;
  var pendingReturn = false;

  function clearMarks() {
    marked.forEach(function (el) {
      el.classList.remove('on', 'side-a', 'side-b', 'ev-first', 'pulse');
      el.removeAttribute('data-side-label');
      el.removeAttribute('tabindex');
    });
    marked = [];
    $$('.blk.has-on', docScroll).forEach(function (b) { b.classList.remove('has-on'); });
  }
  function markEvs(groups) {
    clearMarks();
    groups.forEach(function (g) {
      g.ids.forEach(function (id) {
        (segs[id] || []).forEach(function (el, i) {
          el.classList.add('on');
          if (g.side) el.classList.add('side-' + g.side);
          if (i === 0) {
            el.classList.add('ev-first');
            if (g.side) el.setAttribute('data-side-label', g.side.toUpperCase());
          }
          marked.push(el);
          var b = el.closest('.blk');
          if (b) b.classList.add('has-on');
        });
      });
    });
  }
  function orderedEvs(fid) {
    var f = D.findings[fid];
    return f ? f.a.concat(f.b, f.ev) : [];
  }
  function firstOkEv(fid) {
    var list = orderedEvs(fid);
    for (var i = 0; i < list.length; i++) if (D.ev[list[i]] && D.ev[list[i]].ok) return list[i];
    return null;
  }

  function setHash(anchor, st, push) {
    var url = anchor ? '#' + anchor : location.pathname + location.search;
    try {
      if (push) history.pushState(st, '', url);
      else history.replaceState(st, '', url);
    } catch (err) { /* file:// в отдельных браузерах */ }
    lastHash = location.hash;
  }

  function reveal(el, container) {
    if (!el) return;
    if (!isNarrow() && container && container.scrollHeight > container.clientHeight + 1) {
      var cr = container.getBoundingClientRect();
      var er = el.getBoundingClientRect();
      container.scrollTop += (er.top - cr.top) - Math.max(24, container.clientHeight / 3);
    } else {
      el.scrollIntoView({ block: 'center' });
    }
  }
  function revealCard(c) {
    if (!c) return;
    if (!isNarrow() && fScroll && fScroll.scrollHeight > fScroll.clientHeight + 1) {
      var cr = fScroll.getBoundingClientRect();
      var er = c.getBoundingClientRect();
      if (er.top < cr.top || er.top > cr.bottom - 80) fScroll.scrollTop += er.top - cr.top - 8;
    } else {
      c.scrollIntoView({ block: 'start' });
    }
  }
  function ensureWorkspace() {
    if (isNarrow() || !ws) return;
    var barH = bar ? bar.offsetHeight : 0;
    var top = ws.getBoundingClientRect().top;
    if (Math.abs(top - barH) > 1) window.scrollTo(0, window.pageYOffset + top - barH);
  }
  function flash(el) {
    el.classList.remove('pulse');
    void el.offsetWidth;
    el.classList.add('pulse');
  }

  function select(fid, opt) {
    opt = opt || {};
    var c = cards[fid];
    if (!c) return false;
    if (state.sel && state.sel !== fid) {
      collapse(cards[state.sel]);
      hideRet();
    }
    if (c.parentNode.hidden) resetFilters();
    state.sel = fid;
    expand(c);
    var f = D.findings[fid];
    markEvs([{ ids: f.a, side: 'a' }, { ids: f.b, side: 'b' }, { ids: f.ev, side: '' }]);
    if (opt.hash !== false) setHash(f.anchor, { kind: 'finding', fid: fid }, !!opt.push);
    var first = firstOkEv(fid);
    if (opt.scrollDoc !== false && first && !isNarrow()) reveal(segs[first][0], docScroll);
    if (opt.scrollCard) revealCard(c);
    if (opt.focusCard) toggleOf(c).focus({ preventScroll: true });
    var n = orderedEvs(fid).filter(function (id) { return D.ev[id] && D.ev[id].ok; }).length;
    say('Выбрано замечание ' + fid + ': ' + f.title + '. Подсвечено цитат: ' + n + '.');
    return true;
  }
  function deselect() {
    if (!state.sel) return;
    collapse(cards[state.sel]);
    clearMarks();
    hideRet();
    say('Замечание ' + state.sel + ' свёрнуто.');
    state.sel = null;
    setHash('', null, false);
  }

  /* ---------------------------------------------------------- переход к цитате */
  var ret = $('#ret'), retLabel = $('#ret-label');
  var retPrev = $('#ret-prev'), retNext = $('#ret-next'), retBack = $('#ret-back');

  function sideOf(fid, evId) {
    var f = D.findings[fid];
    if (!f) return '';
    if (f.a.indexOf(evId) >= 0) return 'A';
    if (f.b.indexOf(evId) >= 0) return 'B';
    return '';
  }
  function showRet(fid, evId) {
    var ev = D.ev[evId];
    var side = fid ? sideOf(fid, evId) : '';
    var loc = ev.place ? ' · ' + ev.place : '';
    var pos = state.retList.length > 1 ? ' (' + (state.retIdx + 1) + ' из ' + state.retList.length + ')' : '';
    retLabel.textContent = 'Цитата' + (side ? ' ' + side : '') + (fid ? ' · ' + fid : '') + ' · блок ' + ev.b + loc + pos;
    retPrev.hidden = retNext.hidden = state.retList.length < 2;
    retPrev.disabled = state.retIdx <= 0;
    retNext.disabled = state.retIdx >= state.retList.length - 1;
    retBack.textContent = fid ? 'Вернуться к замечанию ' + fid : 'Вернуться';
    ret.hidden = false;
  }
  function hideRet() {
    if (ret) ret.hidden = true;
    state.ret = null;
    state.retFid = null;
  }

  function jump(evId, fromBtn) {
    var ev = D.ev[evId];
    if (!ev) return;
    var card = fromBtn ? fromBtn.closest('.fc') : null;
    var fid = card ? card.getAttribute('data-fid') : null;
    if (fid && state.sel !== fid) select(fid, { scrollDoc: false });
    if (!fid) markEvs([{ ids: [evId], side: '' }]);
    setView('doc');
    ensureWorkspace();
    var list = segs[evId];
    var target = list && list.length ? list[0] : doc.getElementById(ev.anchor);
    if (!target) return;
    target.setAttribute('tabindex', '-1');
    reveal(target, docScroll);
    (list || [target]).forEach(flash);
    target.focus({ preventScroll: true });
    state.ret = fromBtn || null;
    state.retFid = fid;
    var okList = fid ? orderedEvs(fid).filter(function (id) { return D.ev[id] && D.ev[id].ok; }) : [evId];
    state.retList = okList.length ? okList : [evId];
    state.retIdx = Math.max(0, state.retList.indexOf(evId));
    showRet(fid, evId);
    var cur = history.state;
    setHash(ev.anchor, { kind: 'quote', fid: fid, ev: evId }, !(cur && cur.kind === 'quote'));
    say('Показана цитата' + (fid ? ' ' + (sideOf(fid, evId) || '') + ' замечания ' + fid : '') + ' в блоке ' + ev.b + '. Escape — вернуться.');
  }

  function finishReturn() {
    var btn = state.ret;
    var fid = state.retFid || state.sel;
    hideRet();
    setView('findings');
    var c = fid ? cards[fid] : null;
    if (c && state.sel === fid) revealCard(c);
    var target = btn && doc.contains(btn) && !btn.closest('[hidden]') ? btn : c ? toggleOf(c) : null;
    if (target) {
      if (!c || !c.contains(target)) target.scrollIntoView({ block: 'center' });
      target.focus({ preventScroll: true });
    }
    if (state.sel) setHash(D.findings[state.sel].anchor, { kind: 'finding', fid: state.sel }, false);
    say(state.sel ? 'Возврат к замечанию ' + state.sel + '. Выбор сохранён.' : 'Возврат.');
  }
  function goBack() {
    if (history.state && history.state.kind === 'quote') {
      pendingReturn = true;
      history.back();
      // Если браузер не вернулся (нет записи), завершаем возврат сами.
      setTimeout(function () { if (pendingReturn) { pendingReturn = false; finishReturn(); } }, 300);
    } else {
      finishReturn();
    }
  }
  function stepRet(delta) {
    var i = state.retIdx + delta;
    if (i < 0 || i >= state.retList.length) return;
    var id = state.retList[i];
    var c = state.retFid ? cards[state.retFid] : null;
    var btn = c ? $('.q-btn[data-ev="' + id + '"]', c) : state.ret;
    jump(id, btn || state.ret);
  }
  if (retBack) retBack.addEventListener('click', goBack);
  if (retPrev) retPrev.addEventListener('click', function () { stepRet(-1); });
  if (retNext) retNext.addEventListener('click', function () { stepRet(1); });

  /* ---------------------------------------------------------- выбор фрагмента в документе */
  var chooser = $('#chooser'), chooserList = $('#chooser-list');
  var chooserReturn = null;
  function visibleFid(fid) { return cards[fid] && !cards[fid].parentNode.hidden; }
  function openChooser(fids, from) {
    chooserList.textContent = '';
    fids.forEach(function (fid) {
      var f = D.findings[fid];
      var li = doc.createElement('li');
      var b = doc.createElement('button');
      b.type = 'button';
      b.className = 'btn chooser-item sev-' + f.sev;
      b.setAttribute('data-fid', fid);
      var badge = $('.sev', cards[fid]);
      b.textContent = (badge ? badge.textContent.trim() + ' · ' : '') + fid + ' · ' + f.title;
      li.appendChild(b);
      chooserList.appendChild(li);
    });
    chooser.hidden = false;
    chooserReturn = from;
    var first = $('button', chooserList);
    if (first) first.focus();
  }
  function closeChooser(restore) {
    if (!chooser || chooser.hidden) return;
    chooser.hidden = true;
    if (restore && chooserReturn && chooserReturn.focus) chooserReturn.focus();
    chooserReturn = null;
  }
  function pickFromDoc(fid) {
    closeChooser(false);
    select(fid, { scrollDoc: false });
    setView('findings');
    revealCard(cards[fid]);
    toggleOf(cards[fid]).focus({ preventScroll: true });
  }
  if (chooser) {
    $('#chooser-close').addEventListener('click', function () { closeChooser(true); });
    chooserList.addEventListener('click', function (e) {
      var b = e.target.closest('button[data-fid]');
      if (b) pickFromDoc(b.getAttribute('data-fid'));
    });
  }
  if (docScroll) docScroll.addEventListener('click', function (e) {
    var blkBtn = e.target.closest('.blk-f');
    if (blkBtn) {
      var fl = blkBtn.getAttribute('data-fids').split(' ').filter(visibleFid);
      if (fl.length === 1) pickFromDoc(fl[0]);
      else if (fl.length) openChooser(fl, blkBtn);
      else say('Замечания этого блока скрыты фильтрами.');
      return;
    }
    if (e.target.closest('a,button')) return;
    var seg = e.target.closest('.hl');
    if (!seg) return;
    var sel = window.getSelection ? String(window.getSelection()) : '';
    if (sel.length) return;
    var fids = fidsOfSeg(seg).filter(visibleFid);
    if (fids.length === 1) pickFromDoc(fids[0]);
    else if (fids.length > 1) openChooser(fids, seg);
  });

  /* ---------------------------------------------------------- клики в карточках */
  doc.addEventListener('click', function (e) {
    var t = e.target;
    var toggle = t.closest('.fc-toggle');
    if (toggle) {
      var fid = toggle.closest('.fc').getAttribute('data-fid');
      if (state.sel === fid) deselect();
      else select(fid, {});
      return;
    }
    var q = t.closest('.q-btn');
    if (q) {
      jump(q.getAttribute('data-ev'), q);
      return;
    }
    var sw = t.closest('.ws-switch [data-view]');
    if (sw) {
      setView(sw.getAttribute('data-view'));
      return;
    }
    var opt = t.closest('.opt[data-qid]');
    if (opt) {
      var ta = $('textarea.ans[data-qid="' + opt.getAttribute('data-qid') + '"]');
      if (ta) {
        var v = opt.getAttribute('data-opt');
        ta.value = ta.value.trim() ? ta.value.replace(/\s+$/, '') + '\n' + v : v;
        ta.dispatchEvent(new Event('input', { bubbles: true }));
        ta.focus();
      }
      return;
    }
    var fl = t.closest('[data-filter-sev],[data-filter-status],[data-filter-blocks]');
    if (fl && form) {
      resetFilters();
      var sev = fl.getAttribute('data-filter-sev');
      var st = fl.getAttribute('data-filter-status');
      var fb = fl.getAttribute('data-filter-blocks');
      if (sev) $$('input[name=sev]', form).forEach(function (i) { i.checked = i.value === sev; });
      if (st) form.elements.status.value = st;
      if (fb) form.elements.blocks.value = fb;
      applyFilters();
      setView('findings');
    }
    var a = t.closest('a[href^="#"]');
    if (a) {
      var h = a.getAttribute('href');
      if (/^#(finding|block)-/.test(h) && doc.getElementById(h.slice(1))) {
        e.preventDefault();
        setHash(h.slice(1), { kind: h.indexOf('#finding-') === 0 ? 'finding' : 'block' }, true);
        route(h);
      }
    }
  });

  /* ---------------------------------------------------------- клавиатура */
  doc.addEventListener('keydown', function (e) {
    var t = e.target;
    if (e.key === 'Escape') {
      if (chooser && !chooser.hidden) { closeChooser(true); e.preventDefault(); return; }
      if (state.ret || (ret && !ret.hidden)) {
        if (docPane.contains(t) || t === doc.body || t === doc.documentElement) { goBack(); e.preventDefault(); }
      }
      return;
    }
    if (t.classList && t.classList.contains('fc-toggle')) {
      var keys = { ArrowDown: 1, ArrowUp: -1, Home: 'first', End: 'last' };
      if (!(e.key in keys)) return;
      var list = $$('.fc-toggle').filter(function (b) { return !b.closest('li').hidden; });
      var i = list.indexOf(t);
      var k = keys[e.key];
      var n = k === 'first' ? 0 : k === 'last' ? list.length - 1 : i + k;
      if (list[n]) { list[n].focus(); e.preventDefault(); }
    }
  });

  /* ---------------------------------------------------------- фильтры */
  var form = $('#filters');
  var countEl = $('#f-count'), emptyEl = $('#f-empty');
  function applyFilters() {
    if (!form || !countEl) return;
    var sev = $$('input[name=sev]:checked', form).map(function (i) { return i.value; });
    var crit = form.elements.crit.value, st = form.elements.status.value, blk = form.elements.blocks.value;
    var q = form.elements.q.value.trim().toLowerCase();
    var shown = 0, total = 0, vis = {};
    Object.keys(cards).forEach(function (fid) {
      var c = cards[fid];
      total++;
      var ok = sev.indexOf(c.getAttribute('data-sev')) >= 0 &&
        (!crit || c.getAttribute('data-crit') === crit) &&
        (!st || c.getAttribute('data-status') === st) &&
        (!blk || (' ' + c.getAttribute('data-blocks') + ' ').indexOf(' ' + blk + ' ') >= 0) &&
        (!q || c.getAttribute('data-search').indexOf(q) >= 0);
      c.parentNode.hidden = !ok;
      if (ok) { shown++; vis[fid] = 1; }
    });
    var hiddenSel = state.sel && !vis[state.sel] ? ' Выбранное ' + state.sel + ' скрыто фильтром.' : '';
    countEl.textContent = 'Показано ' + shown + ' из ' + total + '.' + hiddenSel;
    emptyEl.hidden = shown !== 0;
    $$('.hl', docScroll).forEach(function (el) {
      var f = fidsOfSeg(el);
      el.classList.toggle('off', f.length > 0 && !f.some(function (x) { return vis[x]; }));
    });
  }
  function resetFilters() {
    if (!form) return;
    form.reset();
    $$('input[name=sev]', form).forEach(function (i) { i.checked = true; });
    applyFilters();
  }
  if (form) {
    form.addEventListener('input', applyFilters);
    form.addEventListener('change', applyFilters);
    form.addEventListener('reset', function () { setTimeout(applyFilters, 0); });
    form.addEventListener('submit', function (e) { e.preventDefault(); });
    var fr = $('#f-reset');
    if (fr) fr.addEventListener('click', function () { resetFilters(); var first = $('.fc-toggle'); if (first) first.focus(); });
  }

  /* ---------------------------------------------------------- панели на узком экране */
  function setView(v) {
    if (!ws) return;
    ws.setAttribute('data-view', v);
    $$('.ws-switch [data-view]').forEach(function (b) {
      b.setAttribute('aria-pressed', b.getAttribute('data-view') === v ? 'true' : 'false');
    });
  }

  /* ---------------------------------------------------------- якоря */
  function route(hash) {
    var id = '';
    try { id = decodeURIComponent((hash || '').replace(/^#/, '')); } catch (err) { id = (hash || '').slice(1); }
    if (!id) return false;
    var el = doc.getElementById(id);
    if (!el) return false;
    if (el.classList.contains('fc')) {
      var fid = el.getAttribute('data-fid');
      ensureWorkspace();
      setView('findings');
      select(fid, { hash: false, scrollCard: true });
      lastHash = location.hash;
      return true;
    }
    if (el.classList.contains('blk')) {
      setView('doc');
      ensureWorkspace();
      el.setAttribute('tabindex', '-1');
      reveal(el, docScroll);
      flash(el);
      el.focus({ preventScroll: true });
      lastHash = location.hash;
      return true;
    }
    return false;
  }
  /* При переходе по истории браузер после popstate прокручивает к якорю и
     выполняет шаги фокусировки, сбрасывая фокус на body. Поэтому возврат
     завершается следующей задачей, уже после навигации к фрагменту. */
  window.addEventListener('popstate', function () {
    var returning = pendingReturn || !!state.ret;
    pendingReturn = false;
    lastHash = location.hash;
    setTimeout(function () {
      if (returning) finishReturn();
      else route(location.hash);
      lastHash = location.hash;
    }, 0);
  });
  window.addEventListener('hashchange', function () {
    if (location.hash === lastHash) return;
    lastHash = location.hash;
    route(location.hash);
  });

  /* ---------------------------------------------------------- черновик ответов */
  var A = D.answers;
  var ansStatus = $('#ans-status');
  var areas = $$('textarea.ans');
  var mdBox = $('#ans-md');
  var store = null;
  try {
    store = window.localStorage;
    store.setItem('bcc-review/probe', '1');
    store.removeItem('bcc-review/probe');
  } catch (err) {
    store = null;
  }
  function setAnsStatus(msg, warn) {
    if (!ansStatus) return;
    ansStatus.textContent = msg;
    ansStatus.classList.toggle('warn', !!warn);
  }
  /* Q-ID живёт только в своём прогоне: в другом отчёте того же документа Q-01 может
     означать другой вопрос. Поэтому запись черновика хранится по отпечатку вопроса
     (data-qfp: текст вопроса + опоры его замечаний), а Q-ID — лишь подпись. Записи к
     вопросам, которых нет в этом отчёте, не подставляются и не затираются. */
  var qByFp = {};
  A.questions.forEach(function (q) { qByFp[q.fp] = q; });
  var orphansBox = $('#ans-orphans'), orphansList = $('#ans-orphans-list');
  function collect() {
    var out = {};
    areas.forEach(function (ta) { if (ta.value.trim()) out[ta.getAttribute('data-qid')] = ta.value; });
    return out;
  }
  function readJSON(key) {
    if (!store || !D.doc.id) return null;
    try {
      var raw = store.getItem(key);
      return raw ? JSON.parse(raw) : null;
    } catch (err) {
      return null;
    }
  }
  function loadDraft() {
    var d = readJSON(A.storageKey);
    if (!d || d.format !== A.draftFormat || d.document_sha256 !== D.doc.id || !d.entries || typeof d.entries !== 'object') return null;
    return d;
  }
  function loadLegacy() {
    var d = readJSON(A.legacyKey);
    if (!d || d.format !== A.legacyFormat || d.document_sha256 !== D.doc.id || !d.answers || typeof d.answers !== 'object') return null;
    return d;
  }
  var saveTimer = 0;
  function saveDraft() {
    if (!store) {
      setAnsStatus('Локальное хранилище недоступно: черновик живёт только в этой вкладке. Выгрузите ответы в Markdown перед закрытием.', true);
      return;
    }
    try {
      // Перечитываем запись: черновики других прогонов этого документа сохраняются как есть.
      var obj = loadDraft() || { format: A.draftFormat, document_sha256: D.doc.id, entries: {} };
      var now = new Date().toISOString();
      areas.forEach(function (ta) {
        var fp = ta.getAttribute('data-qfp');
        if (ta.value.trim()) {
          obj.entries[fp] = { qid: ta.getAttribute('data-qid'), prompt: (qByFp[fp] || {}).prompt || '', answer: ta.value, saved_at: now, run_id: A.runId };
        } else {
          delete obj.entries[fp];
        }
      });
      obj.saved_at = now;
      if (Object.keys(obj.entries).length) store.setItem(A.storageKey, JSON.stringify(obj));
      else store.removeItem(A.storageKey);
      setAnsStatus('Черновик сохранён в этом браузере (' + new Date().toLocaleTimeString('ru-RU') + ') по тексту вопроса. Документ и вердикт не изменены.');
    } catch (err) {
      setAnsStatus('Не удалось сохранить черновик (' + (err && err.name) + '). Выгрузите ответы в Markdown.', true);
    }
  }
  function markDraft(ta) {
    var art = ta.closest('.qa');
    if (art) art.classList.toggle('has-draft', !!ta.value.trim());
  }
  function el(tag, cls, text) {
    var e = doc.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  }
  function insertInto(qid, text) {
    var ta = $('textarea.ans[data-qid="' + qid + '"]');
    if (!ta) return;
    ta.value = ta.value.trim() ? ta.value.replace(/\s+$/, '') + '\n' + text : text;
    ta.dispatchEvent(new Event('input', { bubbles: true }));
    ta.focus();
  }
  function removeStored(item) {
    try {
      if (item.legacy) {
        var lg = loadLegacy();
        if (lg) {
          delete lg.answers[item.qid];
          if (Object.keys(lg.answers).length) store.setItem(A.legacyKey, JSON.stringify(lg));
          else store.removeItem(A.legacyKey);
        }
      } else {
        var d = loadDraft();
        if (d) {
          delete d.entries[item.fp];
          if (Object.keys(d.entries).length) store.setItem(A.storageKey, JSON.stringify(d));
          else store.removeItem(A.storageKey);
        }
      }
    } catch (err) { /* хранилище недоступно */ }
  }
  function renderOrphans(items) {
    if (!orphansBox || !orphansList) return;
    orphansList.textContent = '';
    items.forEach(function (item, i) {
      var li = el('li', 'orphan' + (item.legacy ? ' orphan-legacy' : ''));
      li.setAttribute('data-orphan-qid', item.qid);
      li.setAttribute('data-orphan-kind', item.legacy ? 'legacy' : 'other-question');
      li.appendChild(el('p', null, (item.legacy
        ? 'Старый формат черновика (только Q-ID) · ' + item.qid + ' · сохранён ' + (item.saved_at || '—')
        : item.qid + ' прогона ' + (item.run_id || '—') + ' · сохранён ' + (item.saved_at || '—'))));
      li.appendChild(el('p', 'small', item.legacy
        ? 'Вопрос неизвестен: старый формат хранил только номер, а в этом отчёте ' + item.qid + ' может означать другое. Ответ не подставлен.'
        : 'Вопрос: «' + (item.prompt || '—') + '». В этом отчёте такого вопроса нет.'));
      var id = 'orph-' + i;
      var lab = el('label', 'small', 'Текст сохранённого ответа');
      lab.setAttribute('for', id);
      var ta = el('textarea', 'orphan-text');
      ta.id = id;
      ta.readOnly = true;
      ta.rows = 2;
      ta.value = item.answer;
      var sel = el('select');
      sel.setAttribute('aria-label', 'Вопрос этого отчёта для переноса ответа ' + item.qid);
      A.questions.forEach(function (q) { var o = el('option', null, q.id + ' — ' + q.prompt.slice(0, 70)); o.value = q.id; sel.appendChild(o); });
      var put = el('button', 'btn', 'Перенести в черновик');
      put.type = 'button';
      put.addEventListener('click', function () { insertInto(sel.value, item.answer); });
      var del = el('button', 'btn', 'Удалить сохранённый ответ');
      del.type = 'button';
      del.addEventListener('click', function () {
        removeStored(item);
        li.remove();
        if (!orphansList.children.length) orphansBox.hidden = true;
        setAnsStatus('Сохранённый ответ ' + item.qid + ' удалён из браузера.');
      });
      var row = el('div', 'btns');
      row.appendChild(sel);
      row.appendChild(put);
      row.appendChild(del);
      li.appendChild(lab);
      li.appendChild(ta);
      li.appendChild(row);
      orphansList.appendChild(li);
    });
    orphansBox.hidden = items.length === 0;
  }
  if (areas.length) {
    var draft = loadDraft();
    var legacy = loadLegacy();
    var restored = 0, moved = [], orphans = [];
    if (draft) {
      areas.forEach(function (ta) {
        var e = draft.entries[ta.getAttribute('data-qfp')];
        if (e && typeof e.answer === 'string') {
          ta.value = e.answer;
          markDraft(ta);
          restored++;
          if (e.qid && e.qid !== ta.getAttribute('data-qid')) moved.push(e.qid + ' → ' + ta.getAttribute('data-qid'));
        }
      });
      Object.keys(draft.entries).forEach(function (fp) {
        var e = draft.entries[fp];
        if (!qByFp[fp] && e && typeof e.answer === 'string' && e.answer.trim()) {
          orphans.push({ fp: fp, qid: e.qid, prompt: e.prompt, answer: e.answer, saved_at: e.saved_at, run_id: e.run_id });
        }
      });
    }
    if (legacy) {
      Object.keys(legacy.answers).forEach(function (qid) {
        var v = legacy.answers[qid];
        if (typeof v === 'string' && v.trim()) orphans.push({ legacy: true, qid: qid, answer: v, saved_at: legacy.saved_at });
      });
    }
    renderOrphans(orphans);
    var msg = [];
    var warn = false;
    if (restored) msg.push('Восстановлено черновиков для этой версии документа: ' + restored + ' (сопоставлены по тексту вопроса, в отчёте не учтены).');
    if (moved.length) msg.push('Номер вопроса изменился: ' + moved.join(', ') + '.');
    var nOther = orphans.filter(function (o) { return !o.legacy; }).length;
    var nLegacy = orphans.length - nOther;
    if (nOther) { msg.push('Черновиков к вопросам, которых нет в этом отчёте: ' + nOther + ' — они не подставлены, см. список ниже.'); warn = true; }
    if (nLegacy) { msg.push('Найден черновик старого формата, где ответ привязан только к номеру вопроса (ответов: ' + nLegacy + '). Он не подставлен: под тем же номером теперь может быть другой вопрос.'); warn = true; }
    if (!store) {
      msg.push('Локальное хранилище недоступно (приватный режим или запрет сайта). Ответы можно ввести и выгрузить в Markdown, но после закрытия вкладки они пропадут.');
      warn = true;
    }
    if (msg.length) setAnsStatus(msg.join(' '), warn);
    areas.forEach(function (ta) {
      ta.addEventListener('input', function () {
        markDraft(ta);
        clearTimeout(saveTimer);
        saveTimer = setTimeout(saveDraft, 300);
      });
    });
  }
  /* Формат совпадает с answers_markdown() в html.py: «Ответ: …» одной строкой, только вопросы с ответом. */
  function oneLine(s) {
    return String(s || '').split(/\r\n|\r|\n/).map(function (x) { return x.replace(/^[ \t]+|[ \t]+$/g, ''); })
      .filter(function (x) { return x; }).join(' ');
  }
  function buildMarkdown(exportedAt) {
    var answers = collect();
    var lines = [], missing = [], blocks = [];
    A.header.forEach(function (h) { lines.push(h === null ? 'exported_at: ' + exportedAt : h); });
    A.questions.forEach(function (q) {
      var one = oneLine(answers[q.id] || '') || oneLine(q.reportAnswer || '');
      if (one) blocks.push(q.head.concat(['Ответ: ' + one, '']));
      else missing.push(q.id);
    });
    if (missing.length) lines.push('Без ответа: ' + missing.join(', '), '');
    blocks.forEach(function (b) { lines.push.apply(lines, b); });
    return lines.join('\n').replace(/\n+$/, '') + '\n';
  }
  function fileName() { return 'answers-' + (D.doc.id || 'document').slice(0, 12) + '.md'; }
  var exp = $('#ans-export');
  if (exp) exp.addEventListener('click', function () {
    var md = buildMarkdown(new Date().toISOString());
    if (mdBox) mdBox.value = md;
    try {
      var url = URL.createObjectURL(new Blob([md], { type: 'text/markdown;charset=utf-8' }));
      var a = doc.createElement('a');
      a.href = url;
      a.download = fileName();
      a.hidden = true;
      doc.body.appendChild(a);
      a.click();
      setTimeout(function () { URL.revokeObjectURL(url); a.remove(); }, 1500);
      setAnsStatus('Сформирован файл ' + a.download + '. Передайте его в повторную проверку через --answers.');
    } catch (err) {
      var box = $('#ans-md-box');
      if (box) box.open = true;
      setAnsStatus('Скачивание недоступно: скопируйте Markdown из поля ниже.', true);
    }
  });
  var cp = $('#ans-copy');
  if (cp) cp.addEventListener('click', function () {
    var md = buildMarkdown(new Date().toISOString());
    if (mdBox) mdBox.value = md;
    function fallback() {
      var box = $('#ans-md-box');
      if (box) box.open = true;
      if (mdBox) { mdBox.focus(); mdBox.select(); }
      var ok = false;
      try { ok = doc.execCommand('copy'); } catch (err) { ok = false; }
      setAnsStatus(ok ? 'Markdown скопирован.' : 'Выделите текст в поле ниже и скопируйте вручную.', !ok);
    }
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(md).then(function () { setAnsStatus('Markdown скопирован в буфер обмена.'); }, fallback);
    } else {
      fallback();
    }
  });
  var clr = $('#ans-clear');
  if (clr) clr.addEventListener('click', function () {
    if (!window.confirm('Удалить черновики ответов на вопросы этого отчёта? Сохранённые ответы к другим вопросам останутся.')) return;
    areas.forEach(function (ta) { ta.value = ''; markDraft(ta); });
    saveDraft();
    setAnsStatus('Черновики ответов на вопросы этого отчёта удалены.');
  });

  /* ---------------------------------------------------------- старт */
  if (location.hash) {
    var h0 = location.hash;
    route(h0);
    if (history.state === null && state.sel) setHash(D.findings[state.sel].anchor, { kind: 'finding', fid: state.sel }, false);
  }

  window.bccReview = {
    version: D.generator,
    domCheck: check,
    cpToUtf16: cpToUtf16,
    select: function (fid) { return select(fid, {}); },
    state: function () {
      return {
        selected: state.sel,
        view: ws ? ws.getAttribute('data-view') : null,
        returnPending: !!state.ret,
        hash: location.hash,
        storage: !!store
      };
    }
  };
})();
