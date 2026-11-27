"""HTML-отчёт v2 одним файлом (№14).

Вход — `report.json` (CONTRACT 2.6) и view документа (CONTRACT 2.1). Выход — один HTML-файл без
внешних зависимостей: стили, скрипт и данные встроены, страница открывается двойным щелчком и
работает без сети.

Что на странице:
* шапка: вердикт для разработки и тестирования, число замечаний по серьёзности, сверка цитат,
  «исправить первым»;
* вкладка «Замечания»: слева документ с номерами строк и подсвеченными цитатами (цвет по
  серьёзности), справа карточки с фильтрами (серьёзность, вид, линза), поиском и сортировкой;
  клик по карточке прокручивает документ к строке, клик по метке в документе — к карточке;
* вкладки «Вопросы», «Тест-кейсы», «Чек-лист банка», «Проверки», «Нарезка», «Отклонённые», «Паспорт»;
* печать в PDF (все вкладки подряд, без документа), светлая и тёмная тема.

Использование из кода::

    from bcc_review.v2.render import html
    html.write(report, view, "reports/requirements.html")

Из командной строки::

    python -m bcc_review.v2.render.html runs/<id>/report.json --doc release/input/requirements.md -o out.html
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import unicodedata
from html import escape
from pathlib import Path
from typing import Any, Iterable

from bcc_review.v2.render import jsonout

ASSETS = Path(__file__).with_name("html_assets")

SEV_ORDER = ("critical", "major", "minor")
SEV_RANK = {"critical": 3, "major": 2, "minor": 1}
SEV_LABEL = {"critical": "Критичный", "major": "Существенный", "minor": "Незначительный"}
SEV_PLURAL = {"critical": "Критичных", "major": "Существенных", "minor": "Незначительных"}
SEV_SHORT = {"critical": "Критичные", "major": "Существенные", "minor": "Незначительные"}

VERDICT_LABEL = {"no": "Нельзя", "conditional": "С условиями", "yes": "Можно", "undetermined": "Не определён"}
VERDICT_HINT = {"no": "есть блокирующие дефекты", "conditional": "можно после исправления замечаний",
                "yes": "блокирующих дефектов нет", "undetermined": "проверка без модели: только формальные правила"}

KIND_LABEL = {
    "event_conflict": "Конфликт исходов события", "status_conflict": "Конфликт статусов и кодов",
    "unit_mismatch": "Расхождение единиц", "boundary_conflict": "Конфликт границ",
    "contradiction": "Противоречие", "missing_element": "Обещанное не описано", "incomplete": "Неполнота",
    "ambiguity": "Неоднозначность", "unverifiable": "Непроверяемость", "non_singular": "Неатомарность",
    "design_constraint": "Решение реализации в требовании", "terminology": "Терминология",
    "api_contract": "Контракт API", "placeholder": "Заглушка", "traceability": "Прослеживаемость",
    "infeasible": "Нереализуемость", "incorrect": "Некорректность", "duplicate": "Дублирование",
    "security": "Информационная безопасность", "ops_risk": "Операционный риск", "other": "Прочее",
}

CRITERION_LABEL = {
    "necessary": "Необходимость", "appropriate": "Уместность", "unambiguous": "Однозначность",
    "complete": "Полнота требования", "singular": "Единичность", "feasible": "Осуществимость",
    "verifiable": "Проверяемость", "correct": "Корректность", "conforming": "Соответствие шаблону",
    "language": "Язык требований", "set_complete": "Полнота набора", "set_consistent": "Согласованность",
    "set_feasible": "Осуществимость набора", "set_comprehensible": "Понятность",
    "set_validatable": "Возможность валидации", "ranked": "Ранжирование", "modifiable": "Модифицируемость",
    "traceable": "Прослеживаемость", "risk": "ИБ и операционные риски",
}

REQ_KIND_LABEL = {
    "functional": "Функциональное", "nonfunctional": "Нефункциональное", "data": "Данные",
    "integration": "Интеграция", "ui": "Интерфейс", "process": "Процесс", "architecture": "Архитектура",
    "api": "API", "acceptance": "Критерий приёмки", "constraint": "Ограничение", "goal": "Цель", "other": "Прочее",
}

SOURCE_LABEL = {
    "lens:analyst": "Аналитик", "lens:qa": "Тестировщик", "lens:architect": "Архитектор", "lens:risk": "Риски",
    "consistency": "Набор целиком", "rules": "Правила", "judge": "Судья", "recheck": "Перепроверка",
}

BLOCKS_LABEL = {"development": "разработку", "testing": "тестирование", "both": "разработку и тестирование"}

VERIFIED = {
    "exact": ("✓", "ok", "Цитата найдена в документе дословно"),
    "normalized": ("✓", "ok", "Цитата найдена после нормализации пробелов, кавычек и тире"),
    "fuzzy": ("≈", "fuzzy", "Нечёткое совпадение (≥ 92 %) рядом с указанной строкой"),
    "missing": ("✗", "miss", "Цитата не найдена в документе"),
}

STAGE_LABEL = {
    "docview": "Чтение документа", "rules": "Правила", "segment": "Нарезка требований",
    "lens:analyst": "Линза «Аналитик»", "lens:qa": "Линза «Тестировщик»", "lens:architect": "Линза «Архитектор»",
    "lens:risk": "Линза «Риски»", "consistency": "Набор целиком", "quotes": "Сверка цитат", "judge": "Судья",
    "clarify": "Вопросы", "revise": "Исправленное ТЗ", "recheck": "Перепроверка", "report": "Отчёт",
    "analyst": "Линза «Аналитик»", "qa": "Линза «Тестировщик»", "architect": "Линза «Архитектор»", "risk": "Линза «Риски»",
    "lens_analyst": "Линза «Аналитик»", "lens_qa": "Линза «Тестировщик»", "lens_architect": "Линза «Архитектор»",
    "lens_risk": "Линза «Риски»", "answers": "Ответы владельца", "offline": "Без модели",
}
STAGE_STATE = {"ok": "готово", "partial": "частично", "failed": "ошибка", "skipped": "пропущен"}

ANSWER_CLASS = {"да": "yes", "нет": "no", "частично": "part", "не требуется": "na"}


# ─────────────────────────────── документ и цитаты ───────────────────────────────

_MD_DECOR = re.compile(r"\*\*|__|`")


def _simple_view(path: Path) -> dict:
    """Запасной view для MD/TXT, если docview №03 недоступен: те же правила, что в CONTRACT 2.1."""
    raw = path.read_bytes()
    text = raw.decode("utf-8-sig", errors="replace")
    lines: list[dict] = []
    stack: list[tuple[int, str]] = []
    in_code = False
    title = ""
    for i, s in enumerate(text.splitlines(), 1):
        heading = 0
        t = s.rstrip()
        if t.strip().startswith("```"):
            in_code = not in_code
            t = ""
        elif not in_code:
            m = re.match(r"^(#{1,6})\s+(.*)$", t)
            if m:
                heading = len(m.group(1))
                t = m.group(2)
            t = _MD_DECOR.sub("", t)
            t = re.sub(r"^\s*[*-]\s+", "", t)
            st = t.strip()
            if st.startswith("|") and st.endswith("|"):
                cells = [c.strip() for c in st.strip("|").split("|")]
                t = "" if all(set(c) <= set(":- ") for c in cells) else " | ".join(cells)
            if t.strip() == "---":
                t = ""
        if heading:
            while stack and stack[-1][0] >= heading:
                stack.pop()
            stack.append((heading, t.strip()))
            if heading == 1 and not title:
                title = t.strip()
        section = " › ".join(h for lvl, h in stack if lvl > 1) or (stack[0][1] if stack else "")
        lines.append({"n": i, "text": t, "page": None, "section": section, "src_line": i,
                      "block_id": "", "heading": heading})
    return {"title": title or path.stem, "file": path.name, "format": path.suffix.lstrip(".").lower() or "txt",
            "sha256": hashlib.sha256(raw).hexdigest(), "lines": lines, "pages": None, "warnings": []}


def load_view(path: str | Path) -> dict:
    """View документа: docview №03, если он есть, иначе запасной разбор MD/TXT."""
    p = Path(path)
    try:
        from bcc_review.v2 import docview  # type: ignore[attr-defined]
        return docview.load(p)
    except Exception:  # noqa: BLE001 — каркас ещё не влит или формат не поддержан
        if p.suffix.lower() in (".md", ".markdown", ".txt", ""):
            return _simple_view(p)
        raise


_QUOTES = dict.fromkeys(map(ord, "«»“”„\"'‘’"), '"')
_DASHES = dict.fromkeys(map(ord, "—–‑−"), "-")
_SPACES = dict.fromkeys(map(ord, "     \t"), " ")


def _norm_char(ch: str) -> str:
    ch = unicodedata.normalize("NFKC", ch)
    ch = ch.translate(_QUOTES).translate(_DASHES).translate(_SPACES)
    return ch.lower()


def _norm_map(s: str) -> tuple[str, list[int]]:
    """Нормализованная строка и индекс исходного символа для каждого её символа."""
    out: list[str] = []
    idx: list[int] = []
    prev_space = True
    for i, ch in enumerate(s):
        n = _norm_char(ch)
        for c in n:
            if c.isspace():
                if prev_space:
                    continue
                c = " "
                prev_space = True
            else:
                prev_space = False
            out.append(c)
            idx.append(i)
    while out and out[-1] == " ":
        out.pop()
        idx.pop()
    return "".join(out), idx


def _norm(s: str) -> str:
    return _norm_map(_MD_DECOR.sub("", s or ""))[0].strip()


def find_span(text: str, quote: str) -> tuple[int, int] | None:
    """Где в строке стоит цитата (с учётом нормализации кавычек, тире и пробелов)."""
    if not text or not quote:
        return None
    i = text.find(quote)
    if i >= 0:
        return i, i + len(quote)
    nt, idx = _norm_map(text)
    nq = _norm(quote)
    if not nq:
        return None
    j = nt.find(nq)
    if j < 0:
        return None
    return idx[j], idx[j + len(nq) - 1] + 1


def locate_quote(view: dict, quote: str, line_hint: int | None = None) -> dict | None:
    """Найти цитату в view: quotes.verify_quote №03, если он есть, иначе упрощённый поиск."""
    try:
        from bcc_review.v2 import quotes  # type: ignore[attr-defined]
        m = quotes.verify_quote(view, quote, line_hint=line_hint)
        if m is not None:
            return dict(m)
    except Exception:  # noqa: BLE001
        pass
    lines = view.get("lines") or []
    nq = _norm(quote)
    if not nq:
        return None
    hits = []
    for ln in lines:
        t = ln.get("text", "")
        if quote in t:
            hits.append((ln["n"], ln["n"], "exact"))
        elif nq in _norm(t):
            hits.append((ln["n"], ln["n"], "normalized"))
    if not hits:
        for k in range(len(lines)):
            for width in (2, 3):
                chunk = lines[k:k + width]
                if len(chunk) == width and nq in _norm(" ".join(x.get("text", "") for x in chunk)):
                    hits.append((chunk[0]["n"], chunk[-1]["n"], "normalized"))
                    break
    if not hits:
        return None
    hint = line_hint or hits[0][0]
    s, e, how = min(hits, key=lambda h: abs(h[0] - hint))
    ln = lines[s - 1] if 0 < s <= len(lines) and lines[s - 1].get("n") == s else next(x for x in lines if x["n"] == s)
    return {"line_start": s, "line_end": e, "page": ln.get("page"), "section": ln.get("section", ""),
            "verified": how, "text": ln.get("text", "")}


# ─────────────────────────────── вспомогательное ───────────────────────────────

def e(v: Any) -> str:
    return escape("" if v is None else str(v), quote=True)


_LREF = re.compile(r"(?:(?<![\w-])([А-Яа-яЁё]{1,7})\s+)?\bL0*(\d{1,5})(?:\s*[–-]\s*L?0*(\d{1,5}))?\b")
_SEV_WORD = re.compile(r"\b(critical|major|minor)\b")
_SEV_RU = {"critical": "критичный", "major": "существенный", "minor": "незначительный"}


def _lref(m: re.Match) -> str:
    try:  # падежи «по строке», «из строки» — как в Markdown-отчёте №13
        from bcc_review.v2.render.markdown import _lref as md_lref
        return md_lref(m)
    except Exception:  # noqa: BLE001
        word = f"строки {m.group(2)}–{m.group(3)}" if m.group(3) else f"строка {m.group(2)}"
        return f"{m.group(1)} {word}" if m.group(1) else word


def tx(v: Any) -> str:
    """Текст модели для показа: «L038» → «строка 38», critical → критичный, затем экранирование."""
    s = "" if v is None else str(v)
    s = _SEV_WORD.sub(lambda m: _SEV_RU[m.group(1)], _LREF.sub(_lref, s))
    if s.startswith("строк"):  # «L035 обещает…» в начале текста
        s = "С" + s[1:]
    return e(s)


def _fmt_int(n: Any) -> str:
    try:
        return f"{int(n):,}".replace(",", " ")
    except (TypeError, ValueError):
        return e(n)


def _fmt_duration(s: Any) -> str:
    try:
        s = float(s)
    except (TypeError, ValueError):
        return "—"
    if s < 60:
        return f"{s:.0f} с"
    m, sec = divmod(int(round(s)), 60)
    if m < 60:
        return f"{m} мин {sec:02d} с"
    h, m = divmod(m, 60)
    return f"{h} ч {m:02d} мин"


def _plural(n: int, one: str, few: str, many: str) -> str:
    n = abs(n)
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def _source_key(src: str) -> str:
    return "rules" if src.startswith("rules") else src


def _source_label(src: str) -> str:
    key = _source_key(src)
    return SOURCE_LABEL.get(key, src)


def _lines_label(ev: dict) -> str:
    a, b = ev.get("line_start") or ev.get("line"), ev.get("line_end") or ev.get("line_start") or ev.get("line")
    if not a:
        return "строка ?"
    page = f"с. {ev['page']}, " if ev.get("page") else ""
    return f"{page}строка {a}" if a == b else f"{page}строки {a}–{b}"


def _first_line(f: dict) -> int:
    nums = [ev.get("line_start") or ev.get("line") or 0 for ev in f.get("evidence") or []]
    nums = [n for n in nums if n]
    return min(nums) if nums else 10 ** 6


def _sev(f: dict) -> str:
    s = f.get("severity", "minor")
    return s if s in SEV_RANK else "minor"


def _quotes_verified(report: dict) -> tuple[int, int]:
    total = ok = 0
    for f in report.get("findings") or []:
        for ev in f.get("evidence") or []:
            total += 1
            if ev.get("verified") in ("exact", "normalized", "fuzzy"):
                ok += 1
    return ok, total


def _finding_link(fid: str, findings_by_id: dict) -> str:
    f = findings_by_id.get(fid)
    if not f:
        return f'<span class="fref">{e(fid)}</span>'
    return (f'<a class="fref sev-{_sev(f)}" href="#{e(fid)}" data-goto="{e(fid)}" '
            f'title="{e(f.get("title", ""))}">{e(fid)}</a>')


def _req_link(rid: str, reqs_by_id: dict) -> str:
    r = reqs_by_id.get(rid)
    if not r:
        return f'<span class="rref">{e(rid)}</span>'
    title = (r.get("source_id") + " · " if r.get("source_id") else "") + r.get("summary", "")
    return (f'<a class="rref" href="#L{e(r.get("line_start"))}" data-req="{e(rid)}" '
            f'data-ls="{e(r.get("line_start"))}" data-le="{e(r.get("line_end"))}" title="{e(title)}">{e(rid)}</a>')


def _asset(name: str) -> str:
    return (ASSETS / name).read_text(encoding="utf-8")


# ─────────────────────────────── блоки страницы ───────────────────────────────

def _hero(report: dict, findings: list[dict], by_id: dict) -> str:
    run = report.get("run") or {}
    verdict = report.get("verdict") or {}
    summary = report.get("summary") or {}
    counts = {s: sum(1 for f in findings if _sev(f) == s) for s in SEV_ORDER}
    reqs = report.get("requirements") or []
    n_req = summary.get("requirements", len(reqs))
    touched = {r for f in findings for r in f.get("requirement_ids") or []}
    no_find = summary.get("requirements_without_findings", len([r for r in reqs if r.get("id") not in touched]))
    ok, total = _quotes_verified(report)
    qv = summary.get("quotes_verified")
    if isinstance(qv, (int, float)) and not isinstance(qv, bool) and 0 <= qv <= 1 and total:
        qv_text = f"{qv * 100:.0f} %"
    elif total:
        qv_text = f"{ok * 100 / total:.0f} %"
    else:
        qv_text = "—"
    qv_sub = f"{ok} из {total} {_plural(total, 'цитаты', 'цитат', 'цитат')}" if total else "цитат нет"

    status = run.get("status", "")
    vcards = []
    for key, label in (("development", "Разработка"), ("testing", "Тестирование")):
        v = verdict.get(key, "") if status != "failed" else ""
        cls = {"no": "no", "conditional": "cond", "yes": "yes"}.get(v, "none")
        word = VERDICT_LABEL.get(v, "Нет вердикта")
        hint = VERDICT_HINT.get(v, "прогон не завершён")
        vcards.append(f'<div class="vcard v-{cls}"><div class="vlabel">{label}</div>'
                      f'<div class="vword">{e(word)}</div><div class="vhint">{e(hint)}</div></div>')

    tiles = []
    for s in SEV_ORDER:
        tiles.append(f'<button class="tile t-{s}" data-sevonly="{s}" title="Показать только: {SEV_SHORT[s].lower()}">'
                     f'<span class="tnum">{counts[s]}</span><span class="tlab">{SEV_PLURAL[s]}</span></button>')
    tiles.append(f'<div class="tile t-neutral"><span class="tnum">{_fmt_int(n_req)}</span>'
                 f'<span class="tlab">{_plural(int(n_req or 0), "требование", "требования", "требований")}'
                 f'<small>{_fmt_int(no_find)} без замечаний</small></span></div>')
    tiles.append(f'<div class="tile t-ok" title="Каждая цитата найдена в документе программой, номер строки посчитан кодом">'
                 f'<span class="tnum">{qv_text}</span><span class="tlab">цитат сверено кодом<small>{e(qv_sub)}</small></span></div>')

    fix = []
    for i, fid in enumerate(verdict.get("fix_first") or [], 1):
        f = by_id.get(fid)
        if not f or jsonout.is_resolved(f):
            continue
        ev0 = (f.get("evidence") or [{}])[0]
        fix.append(f'<li><a href="#{e(fid)}" data-goto="{e(fid)}" class="fix sev-{_sev(f)}">'
                   f'<span class="fixn">{i}</span><span class="dot"></span><span class="fid">{e(fid)}</span>'
                   f'<span class="fixt">{e(f.get("title", ""))}</span><span class="fixl">{e(_lines_label(ev0))}</span></a></li>')
    fix_html = (f'<div class="fixfirst"><h2>Исправить первым</h2><ol>{"".join(fix)}</ol></div>' if fix else "")

    banner = ""
    if status in ("partial", "failed"):
        bad = [STAGE_LABEL.get(k, k) for k, v in (run.get("stages") or {}).items() if v in ("partial", "failed")]
        what = ("Прогон завершился ошибкой — вердикта нет." if status == "failed"
                else "Прогон неполный — вердикт не выше «с условиями».")
        if bad:
            what += " Не завершены этапы: " + ", ".join(bad) + "."
        banner = f'<div class="banner warn" role="status">{e(what)} Подробности — во вкладке «Паспорт».</div>'

    if run.get("provider") == "offline" or verdict.get("development") == "undetermined":
        nc = report.get("not_checked") or []
        nc_txt = (" Не проверялось: " + "; ".join(str(x.get("what", x) if isinstance(x, dict) else x) for x in nc[:6]) + ".") if nc else ""
        banner += (f'<div class="banner info" role="status">Проверка без модели: найдены только формальные дефекты по '
                   f'правилам, смысловые противоречия не искались.{e(nc_txt)}</div>')
    model = ", ".join(run.get("models_used") or []) or run.get("model_requested") or ""
    meta = []
    if model:
        meta.append(f"модель {e(model)}")
    if run.get("duration_s") is not None:
        meta.append(f"время {_fmt_duration(run.get('duration_s'))}")
    calls = (run.get("calls") or {}).get("total")
    if calls:
        meta.append(f"{calls} {_plural(int(calls), 'вызов', 'вызова', 'вызовов')} модели")
    if run.get("finished_at"):
        meta.append(e(str(run["finished_at"]).replace("T", " ")[:16]))

    if report.get("clarification"):
        banner += f'<p class="banner" role="status">{e(jsonout.OWNER_ASSESSMENT)}</p>'
    return f"""
<section class="hero" aria-label="Итог ревью">
  {banner}
  <div class="hero-grid">
    <div class="verdict">
      <h2 class="eyebrow">Можно ли начинать</h2>
      <div class="vcards">{"".join(vcards)}</div>
    </div>
    <div class="stats">
      <h2 class="eyebrow">{"Открытые замечания" if report.get("clarification") else "Замечания"}</h2>
      <div class="tiles">{"".join(tiles)}</div>
    </div>
  </div>
  <div class="hero-text">
    <p class="vsummary">{tx(verdict.get("summary", ""))}</p>
    <p class="runmeta">{" · ".join(meta)}</p>
  </div>
  {fix_html}
</section>"""


def _doc_pane(view: dict | None, findings: list[dict], report: dict) -> str:
    if not view or not view.get("lines"):
        return ('<div class="doc-empty">Текст документа не передан в отчёт, поэтому подсветка недоступна. '
                'Цитаты и номера строк — в карточках справа. Чтобы увидеть документ, соберите отчёт с '
                '<code>--doc ФАЙЛ</code>.</div>')
    lines = view["lines"]
    by_n = {ln["n"]: ln for ln in lines}
    line_f: dict[int, list[str]] = {}
    line_sev: dict[int, int] = {}
    spans: dict[int, list[tuple[int, int, str, int]]] = {}
    for f in findings:
        fid = f.get("id", "")
        rank = SEV_RANK[_sev(f)]
        for ev in f.get("evidence") or []:
            a = ev.get("line_start") or ev.get("line")
            b = ev.get("line_end") or a
            if not a or ev.get("verified") == "missing":
                continue
            for n in range(int(a), int(b) + 1):
                if n not in by_n:
                    continue
                lst = line_f.setdefault(n, [])
                if fid not in lst:
                    lst.append(fid)
                line_sev[n] = max(line_sev.get(n, 0), rank)
                sp = find_span(by_n[n].get("text", ""), ev.get("quote", "")) if a == b else None
                if sp:
                    spans.setdefault(n, []).append((sp[0], sp[1], fid, rank))

    req_start: dict[int, list[str]] = {}
    req_lines: dict[int, list[str]] = {}
    for r in report.get("requirements") or []:
        a, b = r.get("line_start"), r.get("line_end") or r.get("line_start")
        if not a:
            continue
        req_start.setdefault(int(a), []).append(r.get("id", ""))
        for n in range(int(a), int(b) + 1):
            req_lines.setdefault(n, []).append(r.get("id", ""))
    excl: dict[int, str] = {}
    for x in report.get("excluded") or []:
        a, b = x.get("line_start"), x.get("line_end") or x.get("line_start")
        if a:
            for n in range(int(a), int(b) + 1):
                excl[n] = f'{x.get("what", "")}: {x.get("reason", "")}'.strip(": ")

    rank_name = {3: "critical", 2: "major", 1: "minor"}
    fsev = {f.get("id", ""): _sev(f) for f in findings}
    out = []
    prev_page = None
    multi_page = bool(view.get("pages")) or any(ln.get("page") for ln in lines)
    for ln in lines:
        n = ln["n"]
        page = ln.get("page")
        if multi_page and page and page != prev_page:
            out.append(f'<div class="pgbreak" data-page="{e(page)}">страница {e(page)}</div>')
            prev_page = page
        text = ln.get("text", "")
        cls = ["ln"]
        heading = ln.get("heading") or (ln.get("level") or 1 if ln.get("kind") == "heading" else 0)
        if not heading and text.strip() and ln.get("section"):
            last = str(ln["section"]).split("›")[-1].strip()
            heading = 1 if last and text.strip() == last else 0
        if heading:
            cls.append("h")
        if not text.strip():
            cls.append("blank")
        fids = line_f.get(n, [])
        attrs = f' id="L{n}" data-n="{n}"'
        if fids:
            cls.append("hl")
            cls.append("sev-" + rank_name[line_sev[n]])
            attrs += f' data-f="{e(" ".join(fids))}"'
        if n in req_lines:
            cls.append("rq")
            attrs += f' data-r="{e(" ".join(req_lines[n]))}"'
        if n in excl:
            cls.append("ex")
            attrs += f' data-ex="{e(excl[n])}"'
        body = _marked(text, spans.get(n, []), rank_name)
        tags = "".join(f'<span class="rtag">{e(r)}</span>' for r in req_start.get(n, []))
        order = sorted(fids, key=lambda x: -SEV_RANK[fsev[x]])  # сначала самые серьёзные
        marks = "".join(f'<a class="fm sev-{fsev[fid]}" href="#{e(fid)}" data-goto="{e(fid)}">{e(fid)}</a>'
                        for fid in order)
        if len(order) > 3:
            marks += f'<span class="fmore" title="{e(" ".join(order[3:]))}">+{len(order) - 3}</span>'

        out.append(f'<div class="{" ".join(cls)}"{attrs}><span class="no">{n}</span>'
                   f'<span class="tx">{tags}{body or "&#8203;"}</span>'
                   + (f'<span class="fms">{marks}</span>' if marks else "") + "</div>")
    return "\n".join(out)


def _marked(text: str, spans: list[tuple[int, int, str, int]], rank_name: dict) -> str:
    if not spans:
        return e(text)
    cuts = sorted({0, len(text), *[s for s, _, _, _ in spans], *[t for _, t, _, _ in spans]})
    parts = []
    for a, b in zip(cuts, cuts[1:]):
        if a >= b:
            continue
        cover = [(fid, rk) for s, t, fid, rk in spans if s <= a and b <= t]
        seg = e(text[a:b])
        if cover:
            rk = max(r for _, r in cover)
            ids = " ".join(dict.fromkeys(fid for fid, _ in cover))
            parts.append(f'<mark class="q sev-{rank_name[rk]}" data-f="{e(ids)}">{seg}</mark>')
        else:
            parts.append(seg)
    return "".join(parts)


def _card(f: dict, idx: int, reqs_by_id: dict) -> str:
    sev = _sev(f)
    fid = f.get("id", f"D-{idx:02d}")
    kind = f.get("kind", "other")
    crit = f.get("criterion", "")
    sources = f.get("sources") or []
    src_keys = sorted({_source_key(s) for s in sources})
    prio = int(f.get("priority") or 0)
    blocks = f.get("blocks", "none")
    ev_items = []
    ev_lines = []
    for ev in f.get("evidence") or []:
        v = ev.get("verified", "")
        icon, vcls, vtitle = VERIFIED.get(v, ("?", "miss", "Сверка не выполнялась"))
        a = ev.get("line_start") or ev.get("line")
        if a:
            ev_lines.append(str(a))
        b = ev.get("line_end") or a
        ev_items.append(
            f'<li><button type="button" class="ev" data-ls="{e(a)}" data-le="{e(b)}" title="Показать в документе">'
            f'<span class="evl">{e(_lines_label(ev))}</span><q>{e(ev.get("quote", ""))}</q>'
            f'<span class="vf {vcls}" title="{e(vtitle)}">{icon}</span></button></li>')
    reqs = " ".join(_req_link(r, reqs_by_id) for r in f.get("requirement_ids") or [])
    std = "; ".join(f.get("standard_refs") or [])

    details = []
    for key, label, extra in (("scenario", "Сценарий", ""), ("impact", "Последствия", ""),
                              ("recommendation", "Что сделать", ""), ("rewrite", "Предлагаемая формулировка", "rw"),
                              ("question", "Вопрос владельцу", "qq")):
        val = f.get(key)
        if not val:
            continue
        copy = ('<button type="button" class="copy" data-copy title="Скопировать формулировку">Копировать</button>'
                if key == "rewrite" else "")
        details.append(f'<div class="dl {extra}"><div class="dt">{label}{copy}</div><div class="dd">{e(val) if key == "rewrite" else tx(val)}</div></div>')
    more = ""
    if details:
        open_attr = " open" if sev == "critical" else ""
        more = (f'<details class="more"{open_attr}><summary>Сценарий, последствия и исправление</summary>'
                f'{"".join(details)}</details>')

    meta = [f'<span class="chip kind">{e(KIND_LABEL.get(kind, kind))}</span>']
    if crit:
        meta.append(f'<span class="chip crit" title="{e(std)}">{e(CRITERION_LABEL.get(crit, crit))}</span>')
    if blocks in BLOCKS_LABEL:
        meta.append(f'<span class="chip blk">Блокирует {e(BLOCKS_LABEL[blocks])}</span>')

    foot = []
    if reqs:
        foot.append(f'<span class="fl"><b>Требования</b> {reqs}</span>')
    if std:
        foot.append(f'<span class="fl"><b>Стандарт</b> {e(std)}</span>')
    if sources:
        foot.append('<span class="fl"><b>Нашли</b> ' + ", ".join(e(_source_label(s)) for s in dict.fromkeys(sources)) + "</span>")

    search = " ".join(str(x) for x in (fid, f.get("title"), f.get("problem"), f.get("scenario"), f.get("impact"),
                                       f.get("recommendation"), f.get("rewrite"), f.get("question"),
                                       " ".join(ev.get("quote", "") for ev in f.get("evidence") or []),
                                       " ".join(f.get("requirement_ids") or []), KIND_LABEL.get(kind, "")) if x)
    prio_html = f'<span class="prio" title="Порядок исправления">Исправить №{prio}</span>' if prio else ""
    after = f.get("status_after_answers") or (f.get("recheck") or {}).get("status")
    if after in STATUS_AFTER:
        lbl, cls = STATUS_AFTER[after]
        prio_html = f'<span class="ans {cls}" title="После ответов владельца">{lbl}</span>' + prio_html
    return f"""<article class="card sev-{sev}" id="{e(fid)}" tabindex="0" data-idx="{idx}" data-sev="{sev}"
 data-rank="{SEV_RANK[sev]}" data-prio="{prio}" data-line="{_first_line(f)}" data-kind="{e(kind)}"
 data-resolved="{int(jsonout.is_resolved(f))}" data-src="{e(" ".join(src_keys))}" data-blocks="{e(blocks)}" data-lines="{e(" ".join(ev_lines))}" data-search="{e(search.lower())}">
  <header class="ch"><span class="badge sev-{sev}">{SEV_LABEL[sev]}</span><span class="fid">{e(fid)}</span>{prio_html}</header>
  <h3 class="ct">{e(f.get("title", ""))}</h3>
  <div class="meta">{"".join(meta)}</div>
  <ul class="evs">{"".join(ev_items)}</ul>
  <p class="problem">{tx(f.get("problem", ""))}</p>
  {more}
  <footer class="cf">{"".join(foot)}</footer>
</article>"""


def _sort_key(f: dict) -> tuple:
    prio = int(f.get("priority") or 0)
    return (0 if prio else 1, prio, -SEV_RANK[_sev(f)], _first_line(f))


def _findings_panel(findings: list[dict], view: dict | None, report: dict, reqs_by_id: dict) -> str:
    ordered = sorted(findings, key=_sort_key)
    cards = "\n".join(_card(f, i, reqs_by_id) for i, f in enumerate(ordered))
    counts = {s: sum(1 for f in findings if _sev(f) == s) for s in SEV_ORDER}
    chips = "".join(
        f'<button type="button" class="sevchip sev-{s}" aria-pressed="true" data-sev="{s}">'
        f'<span class="dot"></span>{SEV_SHORT[s]} <b>{counts[s]}</b></button>' for s in SEV_ORDER)
    kinds = sorted({f.get("kind", "other") for f in findings}, key=lambda k: KIND_LABEL.get(k, k))
    kind_opts = "".join(f'<option value="{e(k)}">{e(KIND_LABEL.get(k, k))}</option>' for k in kinds)
    srcs = sorted({_source_key(s) for f in findings for s in f.get("sources") or []},
                  key=lambda s: list(SOURCE_LABEL).index(s) if s in SOURCE_LABEL else 99)
    src_opts = "".join(f'<option value="{e(s)}">{e(SOURCE_LABEL.get(s, s))}</option>' for s in srcs)
    doc_title = (view or {}).get("title") or (report.get("document") or {}).get("title", "Документ")
    n_lines = len((view or {}).get("lines") or [])
    empty = ('<div class="empty" hidden>Под фильтр не попало ни одного замечания. '
             '<button type="button" class="linkbtn" data-reset>Сбросить фильтры</button></div>')
    open_filter = ('<label class="tg"><input type="checkbox" id="openonly"> Только открытые</label>'
                   if report.get("clarification") else "")
    no_findings = ('<div class="empty">Замечаний нет: агент не нашёл дефектов, подтверждённых цитатами.</div>'
                   if not findings else "")
    return f"""
<div class="split">
  <aside class="docpane" aria-label="Документ">
    <div class="dochead">
      <div class="doctitle" title="{e(doc_title)}">{e(doc_title)}<small>{n_lines} {_plural(n_lines, "строка", "строки", "строк")}</small></div>
      <div class="doctools">
        <label class="tg"><input type="checkbox" id="onlyhl"> только с замечаниями</label>
        <label class="tg"><input type="checkbox" id="showreq"> нарезка</label>
      </div>
    </div>
    <div class="docbody"><div class="doc" id="doc" tabindex="0">{_doc_pane(view, findings, report)}</div><div class="minimap" id="minimap" aria-hidden="true"></div></div>
    <div class="legend"><span class="lg sev-critical"></span>критичный<span class="lg sev-major"></span>существенный<span class="lg sev-minor"></span>незначительный</div>
  </aside>
  <div class="flist">
    <div class="filters" role="search">
      <div class="frow">{chips}</div>
      <div class="frow">
        <input type="search" id="q" placeholder="Поиск по замечаниям, цитатам, ID…" aria-label="Поиск">
        <select id="fkind" aria-label="Вид дефекта"><option value="">Все виды</option>{kind_opts}</select>
        <select id="fsrc" aria-label="Кто нашёл"><option value="">Все линзы</option>{src_opts}</select>
      </div>
      <div class="frow small">{open_filter}<span id="fcount" aria-live="polite"></span>
        <label class="sortl">Порядок <select id="fsort" class="mini"><option value="prio">по приоритету</option><option value="line">по месту в документе</option><option value="sev">по серьёзности</option></select></label>
        <button type="button" class="linkbtn" id="toggleall">Развернуть все</button><span class="kbd" title="Клавиши">↑ ↓ — по карточкам</span></div>
    </div>
    <div class="cards" id="cards">{cards}{empty}{no_findings}</div>
  </div>
</div>"""


def _table(head: list[str], rows: list[list[str]], cls: str = "") -> str:
    th = "".join(f"<th>{h}</th>" for h in head)
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    return f'<div class="tw"><table class="{cls}"><thead><tr>{th}</tr></thead><tbody>{body}</tbody></table></div>'


OPTION_LETTERS = "ABCDEFGH"


def _ev_list(evs: list) -> str:
    items = []
    for ev in evs or []:
        if not isinstance(ev, dict):
            continue
        a = ev.get("line_start") or ev.get("line")
        b = ev.get("line_end") or a
        icon, vcls, vtitle = VERIFIED.get(ev.get("verified", ""), ("", "", ""))
        items.append(f'<li><button type="button" class="ev" data-ls="{e(a)}" data-le="{e(b)}" title="Показать в документе">'
                     f'<span class="evl">{e(_lines_label(ev))}</span><q>{e(ev.get("quote", ""))}</q>'
                     + (f'<span class="vf {vcls}" title="{e(vtitle)}">{icon}</span>' if icon else "") + "</button></li>")
    return f'<ul class="evs">{"".join(items)}</ul>' if items else ""


def _questions(report: dict, by_id: dict) -> str:
    qs = report.get("questions") or []
    if not qs:
        return '<p class="none">Вопросов к владельцу нет.</p>'
    items = []
    for q in qs:
        qid = q.get("id", "")
        opts = "".join(
            f'<li><label><input type="radio" name="{e(qid)}" value="{i}"><span class="ol">'
            f'{OPTION_LETTERS[i] if i < len(OPTION_LETTERS) else i + 1}</span>{e(o)}</label></li>'
            for i, o in enumerate(q.get("options") or []))
        links = " ".join(_finding_link(fid, by_id) for fid in q.get("finding_ids") or [])
        block = '<span class="badge sev-critical">Блокирует</span>' if q.get("blocking") else ""
        topic = f'<div class="topic">{e(q.get("topic"))}</div>' if q.get("topic") else ""
        items.append(f"""<article class="qcard" data-q="{e(qid)}" data-topic="{e(q.get("topic", ""))}">
  <header class="ch"><span class="fid">{e(qid)}</span>{block}<span class="to">Кому: <b>{e(q.get("to", ""))}</b></span><span class="qlinks">{links}</span></header>
  {topic}<h3 class="ct">{e(q.get("question", ""))}</h3>
  {_ev_list(q.get("evidence") or [])}
  {f'<ol class="opts">{opts}</ol>' if opts else ''}
  <label class="own">Свой ответ<textarea rows="2" data-own="{e(qid)}" placeholder="Если ни один вариант не подходит"></textarea></label>
  {f'<p class="why"><b>Зачем:</b> {tx(q.get("why"))}</p>' if q.get("why") else ''}
</article>""")
    return (f'<div class="qtools"><p>Отметьте варианты или впишите свой ответ и скачайте файл ответов — агент '
            f'перепроверит замечания и покажет вердикт «до и после»: <code>--answers ответы.md</code>.</p>'
            f'<button type="button" class="btn" id="dlanswers">Скачать ответы</button></div>'
            f'<div class="qlist">{"".join(items)}</div>')


STATUS_AFTER = {"resolved": ("закрыт", "a-yes"), "changed": ("изменён", "a-part"), "open": ("открыт", "a-no"),
                "new": ("новый", "a-no")}


def _clarification(report: dict, by_id: dict) -> str:
    c = report.get("clarification") or {}
    if not c:
        return ""
    b, a = c.get("before") or {}, c.get("after") or {}
    vb, va = b.get("verdict") or {}, a.get("verdict") or {}
    fb, fa = b.get("findings") or {}, a.get("findings") or {}
    vcls = {"no": "a-no", "conditional": "a-part", "yes": "a-yes"}

    def vcell(v: str) -> str:
        return f'<span class="ans {vcls.get(v, "a-na")}">{e(VERDICT_LABEL.get(v, "—"))}</span>'

    rows = [["Начинать разработку", vcell(vb.get("development", "")), vcell(va.get("development", ""))],
            ["Начинать тестирование", vcell(vb.get("testing", "")), vcell(va.get("testing", ""))]]
    rows += [[f"Замечания: {SEV_LABEL[s].lower()}", _fmt_int(fb.get(s, 0)), _fmt_int(fa.get(s, 0))] for s in SEV_ORDER]
    out = [f'<p class="lead">Ответов на вопросы: {len(c.get("answers") or [])}, общих решений: '
           f'{len(c.get("decisions") or [])}, без ответа: {len(c.get("unanswered") or [])}. Оценка «после» '
           f'предполагает, что ответы внесены в документ. Закрыто: {_fmt_int(c.get("resolved", 0))}, изменено: '
           f'{_fmt_int(c.get("changed", 0))}, осталось открытыми: {_fmt_int(c.get("open", 0))}, новых: '
           f'{len(c.get("new_findings") or [])}.</p>',
           _table(["Показатель", "До ответов", "После ответов"], rows, "ba")]
    if (c.get("answers_document") or {}).get("match") is False:
        out.append("<p>Владелец отвечал по другой редакции ТЗ. Проверьте привязки к текущим вопросам.</p>")
    pending = c.get("needs_confirmation") or []
    if pending:
        rows = [[e(x.get("question_id", "")), tx(x.get("topic", "")), tx(x.get("text", "")),
                 e(", ".join(x.get("possible_questions") or []) or "уточните текущий вопрос")] for x in pending]
        out += ["<h3>Подтвердить привязку ответов</h3>", _table(["Номер", "Тема", "Ответ", "Вопрос сейчас"], rows)]
    ch = c.get("changes") or []
    if ch:
        crow = []
        for x in ch:
            lbl, cls = STATUS_AFTER.get(x.get("status", ""), (x.get("status", ""), "a-na"))
            sb, sa = x.get("severity_before", ""), x.get("severity_after", "")
            crow.append([_finding_link(x.get("finding_id", ""), by_id) + " " + e(x.get("title_after") or x.get("title", "")),
                         e(SEV_LABEL.get(sb, sb).lower()), f'<span class="ans {cls}">{e(lbl)}</span>',
                         e(SEV_LABEL.get(sa, sa).lower()) if sa else "—", tx(x.get("reason", "")),
                         ", ".join(e(q) for q in x.get("question_ids") or [])])
        out.append('<h3 class="sub">Что изменилось по замечаниям</h3>'
                   + _table(["Замечание", "Было", "Статус", "Стало", "Почему", "Ответ"], crow))
    return "".join(out)


def _rewrites(report: dict, by_id: dict) -> str:
    rws = report.get("rewrites") or []
    if not rws:
        return ""
    rows = []
    for r in rws:
        for ed in r.get("edits") or []:
            act = "заменить" if ed.get("action") == "replace" else "добавить после"
            ok = ('<span class="ans a-yes">внесено</span>' if ed.get("applied")
                  else '<span class="ans a-na">не найдено в тексте</span>')
            rows.append([_finding_link(r.get("finding_id", ""), by_id),
                         f'<a class="lnref" href="#L{e(ed.get("line"))}" data-line="{e(ed.get("line"))}">строка {e(ed.get("line"))}</a>',
                         e(act), f'<div class="was">{e(ed.get("was", ""))}</div>', f'<div class="became">{e(ed.get("became", ""))}</div>', ok])
    return ('<p class="lead">Исправленная редакция ТЗ по критичным и существенным замечаниям: каждая правка '
            'привязана к замечанию и строке. Значения, которые должен выбрать бизнес, помечены «&lt;уточнить: …&gt;».</p>'
            + _table(["Замечание", "Где", "Действие", "Было", "Стало", "Итог"], rows, "rw"))


def _tests(report: dict, reqs_by_id: dict) -> str:
    tcs = report.get("test_cases") or []
    if not tcs:
        return '<p class="none">Черновик тест-кейсов не сформирован.</p>'
    rows = []
    for t in tcs:
        then = e(t.get("then", ""))
        if t.get("expected_defined") is False:
            then = f'<span class="warnmark" title="Ожидаемый результат нельзя вывести из ТЗ">⚠ не определён в ТЗ</span> {then}'
        rows.append([f'<span class="fid">{e(t.get("id", ""))}</span>',
                     " ".join(_req_link(r, reqs_by_id) for r in t.get("requirement_ids") or []),
                     f'<b>{e(t.get("title", ""))}</b>', e(t.get("given", "")), e(t.get("when", "")), then,
                     tx(t.get("gap", ""))])
    return ('<p class="lead">Черновик для раздела «Тестирование требований»: проверки, которых не хватает в '
            'критериях приёмки. Где ожидаемый результат нельзя вывести из текста, это отмечено.</p>'
            + _table(["ID", "Требования", "Проверка", "Дано", "Когда", "Тогда", "Чего нет в приёмке"], rows, "tc"))


def _checklist(report: dict, by_id: dict) -> str:
    items = report.get("checklist") or []
    if not items:
        return '<p class="none">Чек-лист банка не заполнен.</p>'
    rows = []
    for c in items:
        ans = str(c.get("answer", ""))
        cls = ANSWER_CLASS.get(ans.strip().lower(), "na")
        rows.append([e(c.get("item", "")), f'<span class="ans a-{cls}">{e(ans)}</span>', tx(c.get("comment", "")),
                     " ".join(_finding_link(fid, by_id) for fid in c.get("finding_ids") or [])])
    return ('<p class="lead">Чек-лист «Ревью требований» банка, заполненный по результатам проверки.</p>'
            + _table(["Проверка", "Ответ", "Комментарий", "Замечания"], rows, "cl"))


def _checks(report: dict, reqs_by_id: dict) -> str:
    parts = []
    verdict_cls = {"conflict": "a-no", "match": "a-yes", "compatible": "a-yes", "undefined": "a-part"}
    verdict_lbl = {"conflict": "Противоречие", "match": "Совпадает", "compatible": "Совместимы", "undefined": "Не определено"}
    acc = report.get("acceptance_checks") or []
    if acc:
        rows = [[_req_link(a.get("row_requirement_id", ""), reqs_by_id), e(a.get("row_facts", "")),
                 " ".join(_req_link(r, reqs_by_id) for r in a.get("rule_requirement_ids") or []),
                 e(a.get("expected_by_rules", "")) + (f'<div class="deriv">{tx(a["derivation"])}</div>' if a.get("derivation") else ""),
                 e(a.get("stated", "")),
                 f'<span class="ans {verdict_cls.get(a.get("verdict"), "a-na")}">{e(verdict_lbl.get(a.get("verdict"), a.get("verdict", "")))}</span>'
                 + (f'<div class="deriv">{tx(a.get("explanation") or a.get("fix"))}</div>'
                    if a.get("verdict") == "conflict" and (a.get("explanation") or a.get("fix")) else "")]
                for a in acc]
        parts.append('<h3 class="sub">Исполнение критериев приёмки</h3><p class="lead">Ожидаемый результат выведен '
                     'из правил документа и сравнён с тем, что записано в критерии.</p>'
                     + _table(["Критерий", "Условия", "Правила", "По правилам", "В критерии", "Итог"], rows))
    pairs = report.get("pair_checks") or []
    if pairs:
        rows = [[f'{_req_link(p.get("a", ""), reqs_by_id)} ↔ {_req_link(p.get("b", ""), reqs_by_id)}',
                 e(p.get("subject", "")), tx(p.get("scenario", "")), tx(p.get("outcome_a", "")), tx(p.get("outcome_b", "")),
                 f'<span class="ans {verdict_cls.get(p.get("verdict"), "a-na")}">{e(verdict_lbl.get(p.get("verdict"), p.get("verdict", "")))}</span>']
                for p in pairs]
        parts.append('<h3 class="sub">Попарная сверка требований</h3>'
                     + _table(["Пара", "Общий предмет", "Сценарий", "Исход A", "Исход B", "Итог"], rows))
    trace = report.get("trace") or []
    if trace:
        rows = [[_req_link(t.get("requirement_id", ""), reqs_by_id),
                 " ".join(_req_link(r, reqs_by_id) for r in t.get("verified_by") or []) or '<span class="muted">нет</span>',
                 " ".join(_req_link(r, reqs_by_id) for r in t.get("implemented_by") or []) or '<span class="muted">—</span>',
                 tx(t.get("note", ""))] for t in trace]
        parts.append('<h3 class="sub">Трассировка</h3>' + _table(["Требование", "Проверяется", "Реализуется", "Примечание"], rows))
    gl = report.get("glossary") or []
    if gl:
        rows = [[f'<b>{e(g.get("concept", ""))}</b>',
                 ", ".join(f'{e(t.get("term", ""))} <a class="lnref" href="#L{e(t.get("line"))}" data-line="{e(t.get("line"))}">строка {e(t.get("line"))}</a>'
                           for t in g.get("terms") or []), tx(g.get("problem", ""))] for g in gl]
        parts.append('<h3 class="sub">Глоссарий: один смысл — разные слова</h3>' + _table(["Понятие", "Термины в документе", "Проблема"], rows))
    return "".join(parts) or '<p class="none">Дополнительных проверок в отчёте нет.</p>'


def _segmentation(report: dict, findings: list[dict]) -> str:
    reqs = report.get("requirements") or []
    per_req: dict[str, list[dict]] = {}
    for f in findings:
        for r in f.get("requirement_ids") or []:
            per_req.setdefault(r, []).append(f)
    rows = []
    for r in reqs:
        fs = per_req.get(r.get("id", ""), [])
        fl = " ".join(f'<a class="fref sev-{_sev(f)}" href="#{e(f.get("id"))}" data-goto="{e(f.get("id"))}">{e(f.get("id"))}</a>'
                      for f in sorted(fs, key=lambda x: -SEV_RANK[_sev(x)]))
        a, b = r.get("line_start"), r.get("line_end") or r.get("line_start")
        lines = f"{a}" if a == b else f"{a}–{b}"
        rows.append([f'<span class="fid">{e(r.get("id", ""))}</span>', e(r.get("source_id", "")),
                     e(REQ_KIND_LABEL.get(r.get("kind", ""), r.get("kind", ""))), e(r.get("summary", "")),
                     f'<a class="lnref" href="#L{e(a)}" data-line="{e(a)}" data-le="{e(b)}">{e(lines)}</a>',
                     fl or '<span class="muted">—</span>'])
    out = [f'<p class="lead">Агент выделил {len(reqs)} {_plural(len(reqs), "требование", "требования", "требований")} '
           'и присвоил им ID; номер строки — по исходному документу.</p>',
           _table(["ID", "В документе", "Вид", "Кратко", "Строки", "Замечания"], rows, "seg")]
    ex = report.get("excluded") or []
    if ex:
        rows = [[e(x.get("what", "")), f'<a class="lnref" href="#L{e(x.get("line_start"))}" data-line="{e(x.get("line_start"))}" '
                 f'data-le="{e(x.get("line_end"))}">{e(x.get("line_start"))}'
                 + (f'–{e(x.get("line_end"))}' if x.get("line_end") and x.get("line_end") != x.get("line_start") else "")
                 + '</a>', e(x.get("reason", ""))] for x in ex]
        out.append('<h3 class="sub">Не требования (исключено из проверки)</h3>' + _table(["Фрагмент", "Строки", "Почему"], rows))
    return "".join(out)


def _rejected(report: dict, by_id: dict | None = None) -> str:
    rej = report.get("rejected") or []
    if not rej:
        return '<p class="none">Судья не отклонил ни одного кандидата.</p>'
    rows = []
    for r in rej:
        ev = r.get("evidence") or []
        lines = ", ".join(_lines_label(x) for x in ev if isinstance(x, dict))
        rows.append([f'<span class="fid">{e(r.get("candidate_id") or r.get("id", ""))}</span>', e(r.get("title", "")),
                     e(_source_label(r.get("source", ""))) if r.get("source") else "", e(lines),
                     tx(r.get("reason", "")) + (f' <span class="muted">→</span> {_finding_link(r["duplicate_of"], by_id or {})}'
                                              if r.get("duplicate_of") else "")])
    return ('<p class="lead">Кандидаты, которые линзы предложили, а судья не включил в отчёт, — с причиной. '
            'Так видно, что точность важнее количества.</p>'
            + _table(["Кандидат", "Что предлагалось", "Кто", "Где", "Почему отклонено"], rows))


def _passport(report: dict) -> str:
    run = report.get("run") or {}
    doc = report.get("document") or {}
    calls = run.get("calls") or {}
    tokens = run.get("tokens") or {}
    commit = (run.get("commit") or "—") + (" (есть незакоммиченные правки)" if run.get("dirty") else "")
    status = {"complete": "полный", "partial": "неполный", "failed": "ошибка"}.get(run.get("status", ""), run.get("status", "—"))
    cost = run.get("cost_usd")
    rows = [
        ("Агент", f'{e(run.get("agent", "bcc-review"))} {e(run.get("version", ""))}'),
        ("Коммит", e(commit)),
        ("Статус прогона", e(status)),
        ("Начало / конец", f'{e(str(run.get("started_at", "—")).replace("T", " "))} — {e(str(run.get("finished_at", "—")).replace("T", " "))}'),
        ("Длительность", _fmt_duration(run.get("duration_s"))),
        ("Провайдер", e(run.get("provider", "—"))),
        ("Модель (запрошена)", e(run.get("model_requested", "—"))),
        ("Модели (фактически)", e(", ".join(run.get("models_used") or []) or "—")),
        ("Вызовы модели", f'{_fmt_int(calls.get("total", 0))} всего · {_fmt_int(calls.get("cached", 0))} из кэша · '
                          f'{_fmt_int(calls.get("failed", 0))} с ошибкой · {_fmt_int(calls.get("split", 0))} делений пакета'),
        ("Токены", f'{_fmt_int(tokens.get("input", 0))} на входе · {_fmt_int(tokens.get("output", 0))} на выходе'),
        ("Стоимость", f"${cost:.2f}" if isinstance(cost, (int, float)) else "—"),
        ("Документ", f'{e(doc.get("title", ""))} <span class="muted">({e(doc.get("file", ""))}, {e(doc.get("format", ""))})</span>'),
        ("Строк / страниц", f'{_fmt_int(doc.get("lines", "—"))} / {e(doc.get("pages") or "—")}'),
        ("SHA-256 документа", f'<code class="hash">{e(doc.get("sha256", "—"))}</code>'),
        ("Схема отчёта", e(report.get("schema", "—"))),
    ]
    qs = report.get("quote_stats") or {}
    if qs.get("quotes"):
        how = ", ".join(f"{lbl} {qs[k]}" for k, lbl in (("exact", "дословно"), ("normalized", "после нормализации"),
                                                          ("fuzzy", "нечётко"), ("missing", "не найдено")) if qs.get(k))
        rows.insert(10, ("Сверка цитат кодом", f'{_fmt_int(qs.get("verified", 0))} из {_fmt_int(qs["quotes"])} цитат '
                                               f'всех кандидатов найдены в документе <span class="muted">({e(how)})</span>'))
    if qs.get("candidates_in") is not None:
        rows.insert(11, ("Кандидаты", f'{_fmt_int(qs.get("candidates_in", 0))} от ревьюеров → {_fmt_int(qs.get("candidates_kept", 0))} '
                                      f'с найденными цитатами → судье; отклонено {_fmt_int(qs.get("candidates_rejected", 0))}'))
    kv = "".join(f"<tr><th>{k}</th><td>{v}</td></tr>" for k, v in rows)
    stages = dict(run.get("stages") or {})
    stats = run.get("stage_stats") or {}
    for k in stats:
        if k not in stages and f"lens:{k}" not in stages:
            stages[k] = "ok"
    canon = ["docview", "segment", "rules", "lens_analyst", "lens:analyst", "analyst", "lens_qa", "lens:qa", "qa",
             "lens_architect", "lens:architect", "architect", "lens_risk", "lens:risk", "risk", "consistency", "quotes",
             "judge", "clarify", "answers", "recheck", "revise", "report"]
    items = []
    for k, v in sorted(stages.items(), key=lambda kv: canon.index(kv[0]) if kv[0] in canon else 99):
        ss = stats.get(k) or stats.get(k.split(":", 1)[-1]) or {}
        bits = []
        if isinstance(ss, dict):
            if ss.get("seconds") is not None:
                bits.append(_fmt_duration(ss["seconds"]) if ss["seconds"] >= 1 else "< 1 с")
            if ss.get("calls"):
                bits.append(f'{ss["calls"]} {_plural(int(ss["calls"]), "вызов", "вызова", "вызовов")}')
            if ss.get("candidates"):
                bits.append(f'{ss["candidates"]} канд.')
        extra = f'<small>{e(" · ".join(bits))}</small>' if bits else ""
        items.append(f'<li class="st st-{e(v)}"><span>{e(STAGE_LABEL.get(k, k))}{extra}</span><b>{e(STAGE_STATE.get(v, v))}</b></li>')
    st = "".join(items)
    warns = run.get("warnings") or []
    wl = "".join(f"<li>{tx(w)}</li>" for w in warns)
    return (f'<div class="pgrid"><div class="tw"><table class="kv">{kv}</table></div><div>'
            + (f'<h3 class="sub">Этапы</h3><ul class="stages">{st}</ul>' if st else "")
            + (f'<h3 class="sub">Предупреждения</h3><ul class="warns">{wl}</ul>' if wl else "")
            + '<h3 class="sub">Как проверить отчёт</h3><p class="lead">Каждая цитата в замечаниях найдена в документе '
              'программой, номер строки посчитан кодом, а не моделью. Повторная сверка: '
              '<code>python -m bcc_review.v2.verify report.json документ</code>.</p></div></div>')


# ─────────────────────────────── сборка ───────────────────────────────

def render_html(report: dict, view: dict | None = None) -> str:
    """Собрать HTML-отчёт одной строкой (все стили, скрипт и данные внутри)."""
    findings = [f for f in report.get("findings") or [] if isinstance(f, dict)]
    by_id = {f.get("id", ""): f for f in findings}
    reqs_by_id = {r.get("id", ""): r for r in report.get("requirements") or []}
    doc = report.get("document") or {}
    title = doc.get("title") or (view or {}).get("title") or "Документ"
    active = jsonout.open_findings(report)
    counts = {s: sum(1 for f in active if _sev(f) == s) for s in SEV_ORDER}

    tabs = [
        ("findings", "Замечания", len(findings), _findings_panel(findings, view, report, reqs_by_id)),
        ("questions", "Вопросы", len(report.get("questions") or []), _questions(report, by_id)),
        ("clarify", "До и после", None, _clarification(report, by_id)),
        ("rewrites", "Исправленное ТЗ", sum(len(r.get("edits") or []) for r in report.get("rewrites") or []),
         _rewrites(report, by_id)),
        ("tests", "Тест-кейсы", len(report.get("test_cases") or []), _tests(report, reqs_by_id)),
        ("checklist", "Чек-лист банка", len(report.get("checklist") or []), _checklist(report, by_id)),
        ("checks", "Проверки", len(report.get("acceptance_checks") or []) + len(report.get("pair_checks") or []),
         _checks(report, reqs_by_id)),
        ("segment", "Нарезка", len(report.get("requirements") or []), _segmentation(report, findings)),
        ("rejected", "Отклонённые", len(report.get("rejected") or []), _rejected(report, by_id)),
        ("passport", "Паспорт", None, _passport(report)),
    ]
    tabs = [t for t in tabs if t[0] not in ("clarify", "rewrites") or t[3]]
    nav = "".join(
        f'<button type="button" role="tab" class="tab" id="t-{k}" aria-controls="p-{k}" aria-selected="{"true" if i == 0 else "false"}" '
        f'data-tab="{k}">{lbl}{f"<span class=cnt>{n}</span>" if n is not None else ""}</button>'
        for i, (k, lbl, n, _) in enumerate(tabs))
    panels = "".join(
        f'<section class="panel" role="tabpanel" id="p-{k}" aria-labelledby="t-{k}"{"" if i == 0 else " hidden"}>'
        f'<h2 class="ph">{lbl}</h2>{body}</section>' for i, (k, lbl, _, body) in enumerate(tabs))

    data = (json.dumps(report, ensure_ascii=False)
            .replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e"))
    run = report.get("run") or {}
    v = report.get("verdict") or {}
    desc = (f'Разработка: {VERDICT_LABEL.get(v.get("development", ""), "—")}; тестирование: '
            f'{VERDICT_LABEL.get(v.get("testing", ""), "—")}; критичных {counts["critical"]}, '
            f'существенных {counts["major"]}, незначительных {counts["minor"]}.')
    file_name = Path(str(doc.get("file") or "report")).stem or "report"
    gen = f'{e(run.get("agent", "bcc-review"))} {e(run.get("version", ""))}'.strip()
    return f"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="description" content="{e(desc)}">
<meta name="generator" content="{gen}">
<title>Ревью: {e(title)}</title>
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Crect width='32' height='32' rx='8' fill='%230E7C55'/%3E%3Cpath d='M9 16.5l4.5 4.5L23 11' stroke='white' stroke-width='3.2' fill='none' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E">
<script>try{{var t=localStorage.getItem("bccr-theme");if(t)document.documentElement.dataset.theme=t}}catch(_){{}}</script>
<style>
{_asset("report.css")}
</style>
</head>
<body data-file="{e(file_name)}">
<header class="top">
  <div class="brand"><span class="logo" aria-hidden="true"></span><div><div class="bname">Ревью требований</div>
  <h1 class="dname" title="{e(title)}">{e(title)}</h1></div></div>
  <div class="actions">
    <button type="button" class="btn ghost" id="theme" title="Светлая или тёмная тема" aria-label="Сменить тему"><span class="i-theme"></span></button>
    <button type="button" class="btn ghost" id="dljson" title="Скачать report.json">JSON</button>
    <button type="button" class="btn" id="print" title="Печать или сохранение в PDF">PDF / печать</button>
  </div>
</header>
{_hero(report, active, by_id)}
<nav class="tabs" role="tablist" aria-label="Разделы отчёта">{nav}</nav>
<main>{panels}</main>
<footer class="foot">Сформировано агентом {gen} · статическое ревью по ISO/IEC/IEEE 29148:2018 и IEEE 830-1998 ·
цитаты сверены с документом программой</footer>
<script type="application/json" id="report-data">{data}</script>
<script>
{_asset("report.js")}
</script>
</body>
</html>
"""


def write(report: dict, view: dict | None, path: str | Path) -> Path:
    """Записать HTML-отчёт в файл; вернуть путь."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(render_html(report, view), encoding="utf-8")
    return p


export = write  # имя, которое удобно звать из render/exports.py


def _find_doc(report_path: Path, report: dict) -> Path | None:
    f = (report.get("document") or {}).get("file")
    if not f:
        return None
    for base in (Path.cwd(), report_path.parent, *report_path.parents):
        cand = base / f
        if cand.is_file():
            return cand
    return None


def main(argv: Iterable[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m bcc_review.v2.render.html",
                                 description="HTML-отчёт v2 из report.json (один файл, работает без сети)")
    ap.add_argument("report", help="report.json прогона")
    ap.add_argument("--doc", help="исходный документ для подсветки (по умолчанию document.file из отчёта)")
    ap.add_argument("-o", "--out", help="куда записать HTML (по умолчанию рядом с report.json)")
    a = ap.parse_args(list(argv) if argv is not None else None)
    rp = Path(a.report)
    report = json.loads(rp.read_text(encoding="utf-8"))
    doc = Path(a.doc) if a.doc else _find_doc(rp, report)
    view = None
    if doc:
        try:
            view = load_view(doc)
        except Exception as exc:  # noqa: BLE001
            print(f"Документ не прочитан ({exc}); отчёт будет без подсветки.", file=sys.stderr)
    else:
        print("Документ не найден: отчёт будет без подсветки. Укажите --doc ФАЙЛ.", file=sys.stderr)
    out = Path(a.out) if a.out else rp.with_suffix(".html")
    write(report, view, out)
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
