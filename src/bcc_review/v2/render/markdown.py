"""Отчёт ревью в Markdown (владелец №13) — то, что читает аналитик банка и жюри.

    from bcc_review.v2.render import markdown
    text = markdown.render(report)          # report — dict по contracts/v2.json

Порядок разделов — п. 6 ТЗ: «Кратко» (первый экран), 1. Паспорт, 2. Нарезка, 3. Проверка каждого
требования, 4. Проверка набора, 5. Сводка, 6. Итог; приложения А–Е. Весь текст — по-русски, каждое
замечание ссылается на место в документе (раздел, строка, страница) и дословную цитату.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from . import jsonout

ASTANA = timezone(timedelta(hours=5))
QUOTE_LIMIT = 160
MAX_REJECTED_ROWS = 25

SEV_ICON = {"critical": "🔴", "major": "🟠", "minor": "🟡"}
SEV_NAME = {"critical": "критичный", "major": "существенный", "minor": "незначительный"}
SEV_ORDER = {"critical": 0, "major": 1, "minor": 2}
SEV_PLURAL = {"critical": ("критичный", "критичных", "критичных"),
              "major": ("существенный", "существенных", "существенных"),
              "minor": ("незначительный", "незначительных", "незначительных")}

READINESS = {"no": "⛔ нельзя начинать", "conditional": "⚠️ можно с условиями", "yes": "✅ можно начинать",
             "undetermined": "❔ не определено", "none": "— вердикт не вынесен"}
BLOCKS = {"development": "разработку", "testing": "тестирование", "both": "разработку и тестирование",
          "none": "не блокирует"}
BLOCKING = {"development", "testing", "both"}

# Критерии и стандарты — CONTRACT.md, раздел 4. (название, ссылка, короткая метка столбца матрицы)
CRITERIA: dict[str, tuple[str, str, str]] = {
    "necessary": ("Необходимость", "ISO/IEC/IEEE 29148:2018 п. 5.2.5", "Нб"),
    "appropriate": ("Уместность (что, а не как)", "ISO/IEC/IEEE 29148:2018 п. 5.2.5", "Ум"),
    "unambiguous": ("Однозначность", "ISO/IEC/IEEE 29148:2018 п. 5.2.5; IEEE 830-1998 п. 4.3.2", "Од"),
    "complete": ("Полнота требования", "ISO/IEC/IEEE 29148:2018 п. 5.2.5; IEEE 830-1998 п. 4.3.3", "Пл"),
    "singular": ("Единичность", "ISO/IEC/IEEE 29148:2018 п. 5.2.5", "Ед"),
    "feasible": ("Осуществимость", "ISO/IEC/IEEE 29148:2018 п. 5.2.5", "Ос"),
    "verifiable": ("Проверяемость", "ISO/IEC/IEEE 29148:2018 п. 5.2.5; IEEE 830-1998 п. 4.3.6", "Пр"),
    "correct": ("Корректность", "ISO/IEC/IEEE 29148:2018 п. 5.2.5; IEEE 830-1998 п. 4.3.1", "Кр"),
    "conforming": ("Соответствие шаблону", "ISO/IEC/IEEE 29148:2018 п. 5.2.5", "Ш"),
    "language": ("Язык требований", "ISO/IEC/IEEE 29148:2018 п. 5.2.7", "Яз"),
    "set_complete": ("Полнота набора", "ISO/IEC/IEEE 29148:2018 п. 5.2.6; IEEE 830-1998 п. 4.3.3", "Нб"),
    "set_consistent": ("Согласованность", "ISO/IEC/IEEE 29148:2018 п. 5.2.6; IEEE 830-1998 п. 4.3.4", "Нб"),
    "set_feasible": ("Осуществимость набора", "ISO/IEC/IEEE 29148:2018 п. 5.2.6", "Нб"),
    "set_comprehensible": ("Понятность", "ISO/IEC/IEEE 29148:2018 п. 5.2.6", "Нб"),
    "set_validatable": ("Возможность валидации", "ISO/IEC/IEEE 29148:2018 п. 5.2.6", "Нб"),
    "ranked": ("Ранжирование по важности", "IEEE 830-1998 п. 4.3.5", "Нб"),
    "modifiable": ("Модифицируемость", "IEEE 830-1998 п. 4.3.7", "Нб"),
    "traceable": ("Прослеживаемость", "IEEE 830-1998 п. 4.3.8", "Нб"),
    "risk": ("ИБ и операционные риски", "чек-лист «Ревью требований» банка", "Рс"),
}
INDIVIDUAL = ["necessary", "appropriate", "unambiguous", "complete", "singular", "feasible", "verifiable",
              "correct", "conforming", "language"]
SET_CRITERIA = ["set_consistent", "set_complete", "set_feasible", "set_comprehensible", "set_validatable",
                "ranked", "modifiable", "traceable"]
# виды дефектов, которые относятся к критерию набора, даже если судья поставил критерий требования
KIND_TO_SET = {
    "set_consistent": {"event_conflict", "status_conflict", "unit_mismatch", "boundary_conflict", "contradiction"},
    "set_complete": set(),
    "set_comprehensible": {"terminology"},
    "modifiable": {"duplicate"},
    "traceable": {"traceability"},
}
CONFLICT_KINDS = {"event_conflict", "status_conflict", "unit_mismatch", "boundary_conflict", "contradiction"}

KIND_NAME = {
    "event_conflict": "противоречие по событию", "status_conflict": "противоречие статусов",
    "unit_mismatch": "расхождение единиц", "boundary_conflict": "противоречие границ",
    "contradiction": "противоречие", "missing_element": "отсутствует элемент", "incomplete": "неполнота",
    "ambiguity": "неоднозначность", "unverifiable": "непроверяемость", "non_singular": "неатомарность",
    "design_constraint": "решение реализации в требовании", "terminology": "терминология",
    "api_contract": "контракт API", "placeholder": "незаполненное поле", "traceability": "прослеживаемость",
    "infeasible": "неосуществимость", "incorrect": "некорректность", "duplicate": "дублирование",
    "security": "информационная безопасность", "ops_risk": "операционный риск", "other": "прочее",
}
REQ_KIND = {
    "functional": "функциональное", "nonfunctional": "нефункциональное", "data": "данные",
    "integration": "интеграция", "ui": "интерфейс", "process": "процесс", "architecture": "архитектура",
    "api": "API", "acceptance": "критерий приёмки", "constraint": "ограничение", "goal": "цель",
    "other": "прочее",
}
# требования, которые должны подтверждаться критериями приёмки (матрица покрытия)
VERIFY_KINDS = {"functional", "nonfunctional", "data", "integration", "ui", "process", "constraint"}

STAGES = {
    "docview": ("Чтение документа", "нумерует строки, страницы и разделы"),
    "rules": ("Правила без модели", "точные сигналы: заглушки, единицы, размытые слова"),
    "segment": ("Нарезка", "выделяет требования и исключает шаблоны"),
    "analyst": ("Аналитик", "однозначность, полнота, атомарность, язык"),
    "qa": ("Тестировщик", "проверяемость, исполнение критериев приёмки, тест-кейсы"),
    "architect": ("Архитектор", "контракт API, данные, интеграция, события"),
    "risk": ("Риски", "ИБ, эксплуатация, откат, банковский домен"),
    "consistency": ("Набор целиком", "попарные противоречия, трассировка, глоссарий"),
    "quotes": ("Сверка цитат", "ищет каждую цитату в документе, номер строки считает код"),
    "judge": ("Судья", "объединяет дубли, отклоняет ложные, калибрует серьёзность"),
    "clarify": ("Вопросы", "вопросы владельцу с вариантами ответа"),
    "recheck": ("Пересмотр по ответам", "снимает и уточняет дефекты по ответам владельца"),
    "revise": ("Исправленное ТЗ", "формулировки «было → стало»"),
    "render": ("Запись отчёта", "отчёт в Markdown, JSON и других форматах"),
    "lenses": ("Проверка ролями", "аналитик, тестировщик, архитектор, риски"),
    "export": ("Экспорт", "DOCX, PDF, задачи Jira"),
    "html": ("HTML-отчёт", "интерактивная страница отчёта"),
}


def stage_name(key: str) -> str:
    return STAGES.get(stage_key(key), (f"этап `{key}`",))[0]
STAGE_STATUS = {"ok": "✅ выполнен", "partial": "⚠️ частично", "failed": "⛔ сбой", "skipped": "— пропущен"}
SOURCES = {"analyst": "аналитик", "qa": "тестировщик", "architect": "архитектор", "risk": "риски",
           "consistency": "проверка набора", "rules": "правило", "judge": "судья", "recheck": "пересмотр"}
PROVIDERS = {
    "claude_cli": "«Claude Code», команда `claude -p`", "gemini": "«Google Gemini», API", "anthropic": "«Anthropic», API",
    "openai": "сервер, совместимый с «OpenAI» («Ollama», «vLLM» и др.)", "mock": "тестовый: ответы из файлов",
    "offline": "без модели (только правила)",
}
STATUS = {"complete": "завершён полностью", "partial": "завершён частично", "failed": "завершён со сбоем"}
FORMATS = {"md": "«Markdown»", "txt": "текст", "pdf": "PDF", "docx": "DOCX", "html": "HTML"}
CHECK_ANSWER = {"да": "✅ Да", "нет": "❌ Нет", "частично": "⚠️ Частично", "не требуется": "— Не требуется"}
LETTERS = "ABCDEFGHIJ"  # как в файле ответов --answers (№11 clarify.option_label); кириллицу ответы тоже принимают
# якоря разделов — короткие коды, чтобы в тексте отчёта не было английских слов
NAV = [("s1", "1. Паспорт"), ("s2", "2. Нарезка"), ("s3", "3. Требования"), ("s4", "4. Набор"), ("s5", "5. Сводка"),
       ("s6", "6. Итог"), ("pa", "А. Вопросы"), ("pb", "Б. Тест-кейсы"), ("pv", "В. Чек-лист"),
       ("pg", "Г. Было → стало"), ("pd", "Д. Как работал агент"), ("pe", "Е. Методика")]


def h2(anchor_id: str, title: str) -> str:
    return f"## <a id=\"{anchor_id}\"></a>{title}"


# ================================================================== форматирование

def plural(n: int, one: str, few: str, many: str) -> str:
    n10, n100 = n % 10, n % 100
    if n10 == 1 and n100 != 11:
        return one
    if 2 <= n10 <= 4 and not 12 <= n100 <= 14:
        return few
    return many


def num(n) -> str:
    try:
        return f"{int(n):,}".replace(",", " ")
    except (TypeError, ValueError):
        return "—"


_HTML_START = re.compile(r"<(?=[A-Za-z/!?])")
# собственный ID требования в документе: «Ф-1», «FR-12», «НФТ-3», «4.2.1», «BR.7»
_DOC_ID = re.compile(r"[A-Za-zА-Яа-яЁё]{0,6}[-.]?\d+(?:[.-]\d+)*[a-zа-я]?")


def esc(text) -> str:
    """Текст модели или документа в строку Markdown: без переводов строк и без HTML-тегов."""
    s = " ".join(str(text or "").split())
    return _HTML_START.sub(r"\\<", s)


_LREF = re.compile(r"(?:(?<![\w-])([А-Яа-яЁё]{1,7})\s+)?\bL0*(\d{1,5})(?:\s*[–-]\s*L?0*(\d{1,5}))?\b")
# падеж слова «строка» после предлога: (одна строка, диапазон)
_LCASE = {**dict.fromkeys(("по", "к", "ко"), ("строке", "строкам")),
          **dict.fromkeys(("в", "во", "на", "о", "об", "при"), ("строке", "строках")),
          **dict.fromkeys(("из", "до", "от", "у", "для", "около", "после", "с", "со", "без", "кроме", "вместо",
                           "возле", "вне", "против", "среди", "из-за"), ("строки", "строк")),
          **dict.fromkeys(("между", "над", "под", "перед", "за"), ("строкой", "строками"))}


def _lref(m: re.Match) -> str:
    prep = m.group(1) or ""
    one, many = _LCASE.get(prep.lower(), ("строка", "строки"))
    word = f"{many} {m.group(2)}–{m.group(3)}" if m.group(3) else f"{one} {m.group(2)}"
    return f"{prep} {word}" if prep else word


def prose(text) -> str:
    """Текст модели: «L038» и «L38–L40» из нумерованного документа → «строка 38», «строки 38–40»."""
    return _LREF.sub(_lref, esc(text))


def cell(text) -> str:
    """Ячейка таблицы: текст модели или этапа, «L038» → «строка 38», «|» экранирован."""
    return prose(text).replace("|", "\\|")


pcell = cell


def shorten(text, limit: int = QUOTE_LIMIT) -> str:
    s = " ".join(str(text or "").split())
    if len(s) <= limit:
        return s
    cut = s[:limit]
    sp = cut.rfind(" ")
    if sp > limit * 0.6:
        cut = cut[:sp]
    return cut.rstrip(" ,.;:—-") + "…"


def quote_md(text, limit: int = QUOTE_LIMIT, *, in_table: bool = False) -> str:
    """Цитата документа: «…», не длиннее limit, разметка документа обезврежена."""
    s = shorten(text, limit)
    s = s.replace("\\", "\\\\").replace("*", "\\*").replace("`", "\\`").replace("[", "\\[").replace("]", "\\]")
    s = _HTML_START.sub(r"\\<", s)
    if in_table:
        s = s.replace("|", "\\|")
    return f"«{s}»"


def first_sentence(text, limit: int = 150) -> str:
    """Первое предложение (точка внутри «…» и (…) — не конец предложения)."""
    s = " ".join(str(text or "").split())
    depth = 0
    for i, ch in enumerate(s):
        if ch in "«(":
            depth += 1
        elif ch in "»)":
            depth = max(0, depth - 1)
        elif ch in ".!?" and depth == 0 and i >= 25 and (i + 1 == len(s) or (s[i + 1] == " " and i + 2 < len(s)
                                                                            and s[i + 2].isupper())):
            s = s[: i + 1]
            break
    return shorten(s, limit)


def lines_word(a, b=None) -> str:
    if not a:
        return ""
    if b and b != a:
        return f"строки {a}–{b}"
    return f"строка {a}"


def short_section(section: str) -> str:
    """«Часть A. Новый функционал › Требования к изменениям › Функциональные требования» →
    «Часть A › Функциональные требования»."""
    parts = [p.strip() for p in str(section or "").split("›") if p.strip()]
    if not parts:
        return ""
    head = parts[0]
    m = re.match(r"^(\S+\s+\S{1,4})[.:]\s+\S", head)
    if m and len(m.group(1)) <= 14:
        head = m.group(1)
    if len(parts) == 1:
        return head
    return f"{head} › {parts[-1]}"


def place(item: dict) -> str:
    """Место в документе: «Часть A › Функциональные требования, строка 38, стр. 2»."""
    bits = []
    sec = short_section(item.get("section", ""))
    if sec:
        bits.append(sec)
    ln = lines_word(item.get("line_start"), item.get("line_end"))
    if ln:
        bits.append(ln)
    if item.get("page"):
        bits.append(f"стр. {item['page']}")
    return ", ".join(bits) or "место не указано"


def anchor(id_: str) -> str:
    return str(id_ or "").lower()


def when(iso: str) -> datetime | None:
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(ASTANA)


def duration(seconds) -> str:
    try:
        s = int(round(float(seconds)))
    except (TypeError, ValueError):
        return "—"
    if s < 60:
        return f"{s} с"
    m, s = divmod(s, 60)
    if m < 60:
        return f"{m} мин {s} с" if s else f"{m} мин"
    h, m = divmod(m, 60)
    return f"{h} ч {m} мин"


def stage_key(name: str) -> str:
    n = str(name or "").lower()
    for pref in ("lens:", "lens_", "stage:", "rules:"):
        if n.startswith(pref):
            n = n[len(pref):] if pref != "rules:" else "rules"
    return n


def source_name(src: str) -> str:
    s = str(src or "")
    if s.startswith("rules:"):
        return f"правило «{s.split(':', 1)[1]}»"
    if s in SOURCES or stage_key(s) in SOURCES:
        return SOURCES.get(stage_key(s), SOURCES.get(s))
    if s.startswith("lens"):
        return "проверка ролью"
    return f"этап `{s}`" if s else "—"


def table(header: list[str], rows: list[list[str]], align: list[str] | None = None) -> list[str]:
    align = align or [":---"] * len(header)
    out = ["| " + " | ".join(header) + " |", "| " + " | ".join(align) + " |"]
    out += ["| " + " | ".join(r) + " |" for r in rows]
    return out


# ================================================================== модель отчёта

class _Ctx:
    def __init__(self, report: dict, level: int = 0):
        self.level = level  # 0 — полный отчёт; 1–3 — сжатие, чтобы уложиться в лимит строк
        self.r = report
        self.run = report.get("run", {}) or {}
        self.doc = report.get("document", {}) or {}
        self.reqs = report.get("requirements", []) or []
        self.req_by_id = {q.get("id"): q for q in self.reqs}
        all_f = report.get("findings", []) or []
        self.resolved = [f for f in all_f if jsonout.is_resolved(f)]
        self.findings = sorted((f for f in all_f if not jsonout.is_resolved(f)),
                               key=lambda f: (SEV_ORDER.get(f.get("severity"), 3), _id_num(f.get("id"))))
        self.f_by_id = {f.get("id"): f for f in all_f}
        self.q_by_finding: dict[str, list[str]] = {}
        for q in report.get("questions", []) or []:
            for fid in q.get("finding_ids", []) or []:
                self.q_by_finding.setdefault(fid, []).append(q.get("id"))
        self.summary = report.get("summary") or jsonout.compute_summary(report)
        self.verdict = report.get("verdict", {}) or {}
        self.offline = self.run.get("provider") == "offline" or (
            not self.run.get("models_used") and self.run.get("provider") not in ("mock",))

    def req_label(self, rid: str, link: bool = True) -> str:
        q = self.req_by_id.get(rid, {})
        sid = str(q.get("source_id") or "").strip()
        label = rid
        if sid and _DOC_ID.fullmatch(sid):
            label = f"{rid} / {sid}"
        return f"[{label}](#{anchor(rid)})" if link and q else label

    def f_link(self, fid: str, with_icon: bool = False) -> str:
        f = self.f_by_id.get(fid)
        if not f:
            return esc(fid)
        icon = SEV_ICON.get(f.get("severity"), "") + " " if with_icon else ""
        if jsonout.is_resolved(f):
            return f"{icon}{fid} (снят)"
        return f"{icon}[{fid}](#{anchor(fid)})"

    def f_links(self, ids, with_icon: bool = False) -> str:
        ids = [i for i in ids or [] if i]
        return ", ".join(self.f_link(i, with_icon) for i in ids) if ids else "—"


def _id_num(id_) -> int:
    m = re.search(r"(\d+)$", str(id_ or ""))
    return int(m.group(1)) if m else 10 ** 6


def _worst(findings) -> str | None:
    sevs = sorted((f.get("severity") for f in findings if f.get("severity") in SEV_ORDER), key=SEV_ORDER.get)
    return sevs[0] if sevs else None


def _set_bucket(f: dict) -> str | None:
    c = f.get("criterion")
    if c in SET_CRITERIA:
        return c
    for crit, kinds in KIND_TO_SET.items():
        if f.get("kind") in kinds:
            return crit
    return None


def _category(f: dict) -> str:
    kind, crit = f.get("kind"), f.get("criterion")
    if kind in CONFLICT_KINDS or crit == "set_consistent":
        return "contradictory"
    if kind in ("unverifiable", "ambiguity") or crit in ("verifiable", "unambiguous", "set_validatable"):
        return "unverifiable"
    if kind in ("missing_element", "incomplete", "placeholder") or crit in ("complete", "set_complete"):
        return "incomplete"
    return "other"


CATEGORY = {"contradictory": "Противоречивые", "unverifiable": "Непроверяемые и неоднозначные",
            "incomplete": "Неполные", "other": "Прочие (ИБ, контракт API, термины, оформление)"}


def _criterion_name(code: str) -> str:
    return CRITERIA.get(code, (code or "—", "", ""))[0]


def _criterion_ref(f: dict) -> str:
    refs = f.get("standard_refs") or []
    if refs:
        return "; ".join(refs)
    return CRITERIA.get(f.get("criterion"), ("", "", ""))[1]


def _counts_line(c: _Ctx) -> str:
    s = c.summary
    fs = s.get("findings", {})
    total = sum(fs.get(k, 0) for k in SEV_ICON)
    nreq = s.get("requirements", len(c.reqs)) or 0
    parts = ([f"**{nreq}** {plural(nreq, 'требование', 'требования', 'требований')}"] if nreq or not c.offline
             else ["Требования без модели не выделялись"]) + [
             f"**{total}** {plural(total, 'дефект', 'дефекта', 'дефектов')}: "
             + " · ".join(f"{SEV_ICON[k]} **{fs.get(k, 0)}** {plural(fs.get(k, 0), *SEV_PLURAL[k])}"
                          for k in ("critical", "major", "minor"))]
    qs = c.r.get("questions", []) or []
    if qs:
        blocking = sum(1 for q in qs if q.get("blocking"))
        parts.append(f"**{len(qs)}** {plural(len(qs), 'вопрос', 'вопроса', 'вопросов')} владельцу"
                     + (f" (блокирующих — {blocking})" if blocking else ""))
    return " · ".join(parts)


# ================================================================== разделы

def _header(c: _Ctx) -> list[str]:
    title = c.doc.get("title") or c.doc.get("file") or "документ"
    run = c.run
    commit = f"`{str(run.get('commit'))[:7]}`" if run.get("commit") else "не записан"
    dirty = ", рабочая копия с изменениями" if run.get("dirty") else ""
    ok, total = c.summary.get("quotes_verified", 0), c.summary.get("quotes_total")
    if total is None:
        ok, total = jsonout.count_quotes(c.findings)
    src = f"«{esc(c.doc.get('file') or '')}»"
    if total and ok == total:
        quotes = (f"все {total} {plural(total, 'цитата сверена', 'цитаты сверены', 'цитат сверены')} программой "
                  f"с исходником {src}")
    elif total:
        quotes = f"программой сверено {ok} из {total} цитат с исходником {src}, несверенные помечены ⚠️"
    else:
        quotes = f"исходник {src}, цитат в дефектах нет"
    head = esc(c.r.get("title")) if isinstance(c.r.get("title"), str) and c.r.get("title") else "Ревью требований"
    out = [f"# {head}: «{esc(title)}»", "",
           f"> Сформирован агентом «{esc(run.get('agent') or 'BCC Review')}» {esc(run.get('version') or '')} "
           f"(коммит {commit}{dirty}) без ручных правок; {quotes}. Проверка повторяется командой "
           f"`python -m bcc_review verify отчёт.json исходник`."]
    status = run.get("status")
    if status == "partial":
        bad = [stage_name(k) for k, v in (run.get("stages") or {}).items()
               if v in ("partial", "failed")]
        out += [">", f"> ⚠️ Прогон завершён частично"
                + (f": не полностью выполнены этапы {', '.join(bad)}" if bad else "")
                + ". Вердикт не выше «с условиями»; недостающие проверки — в приложении Д."]
    elif status == "failed":
        out += [">", "> ⛔ Прогон завершился сбоем: вердикт не вынесен, ниже — то, что успели проверить."]
    if c.offline:
        out += [">", "> Режим без модели: работали только детерминированные правила. Поиск противоречий, "
                     "проверка критериев приёмки и вопросы владельцу требуют модели (инструкция «README», раздел о "
                     "ключе)."]
    return out + [""]


def _brief(c: _Ctx) -> list[str]:
    v = c.verdict
    out = ["## Кратко", ""]
    out += table(["Разработка", "Тестирование"],
                 [[f"**{READINESS.get(v.get('development'), '—')}**", f"**{READINESS.get(v.get('testing'), '—')}**"]],
                 [":---:", ":---:"])
    out += ["", _counts_line(c), ""]
    out += [prose(v.get("summary") or _auto_reason(c)), ""]
    blockers = [f for f in c.findings if f.get("blocks") in BLOCKING and (
        f.get("severity") == "critical" or (c.offline and f.get("rule_conflict")))]
    blockers.sort(key=lambda f: (f.get("priority") or 99, _id_num(f.get("id"))))
    if blockers:
        same = len({f.get("blocks") for f in blockers}) == 1
        out += [f"**Блокеры ({len(blockers)})**" + (f" — блокируют {BLOCKS.get(blockers[0].get('blocks'), '—')}"
                                                   if same else ""), ""]
        rows = []
        for f in blockers:
            reqs = ", ".join(c.req_label(r) for r in (f.get("requirement_ids") or [])[:3]) or "документ в целом"
            lns = sorted({e.get("line_start") for e in f.get("evidence", []) if e.get("line_start")})
            where = reqs + (f" · {plural(len(lns), 'строка', 'строки', 'строки')} {', '.join(map(str, lns[:4]))}"
                            if lns else "")
            row = [f"{SEV_ICON.get(f.get('severity'), '')} [{f['id']}](#{anchor(f['id'])}) {cell(f.get('title'))}", where]
            if not same:
                row.append(BLOCKS.get(f.get("blocks"), "—"))
            rows.append(row + [pcell(first_sentence(f.get("impact") or f.get("problem"), 170))])
        out += table(["Дефект", "Где"] + ([] if same else ["Блокирует"]) + ["Почему блокирует"], rows)
        out.append("")
    else:
        out += ["Блокирующих дефектов не найдено.", ""]
    first = _fix_first(c)
    if first:
        out += ["**Исправить первым**", ""]
        out += [f"{i}. {c.f_link(f['id'], True)} {esc(f.get('title'))}" for i, f in enumerate(first, 1)]
        out.append("")
    out += _before_after(c)
    out += ["**Разделы:** " + " · ".join(f"[{name}](#{a})" for a, name in NAV), ""]
    return out


def _fix_first(c: _Ctx) -> list[dict]:
    ids = list(c.verdict.get("fix_first") or [])
    if not ids:
        ids = [f["id"] for f in sorted((f for f in c.findings if f.get("priority")), key=lambda f: f["priority"])]
    if not ids:
        ids = [f["id"] for f in c.findings if f.get("severity") == "critical"][:7]
    return [c.f_by_id[i] for i in ids if i in c.f_by_id and not jsonout.is_resolved(c.f_by_id[i])][:7]


CHANGE_STATUS = {"resolved": "✅ снят", "changed": "✏️ уточнён", "open": "⏳ открыт", "new": "🆕 новый"}


def _before_after(c: _Ctx) -> list[str]:
    """Блок «до/после» на первом экране (режим --answers, №11: report["clarification"])."""
    cl = c.r.get("clarification") or {}
    if not cl:
        return []
    before, after = cl.get("before") or {}, cl.get("after") or {}
    bv, bf = before.get("verdict") or {}, before.get("findings") or {}
    av = after.get("verdict") or c.verdict
    af = after.get("findings") or c.summary.get("findings", {})
    answers = cl.get("answers") or []
    decisions = cl.get("decisions") or []
    out = [f"**До и после ответов владельца** — ответов {len(answers)}, общих решений {len(decisions)}, "
           f"без ответа {len(cl.get('unanswered') or [])}", ""]
    rows = [["Разработка", READINESS.get(bv.get("development"), "—"), READINESS.get(av.get("development"), "—")],
            ["Тестирование", READINESS.get(bv.get("testing"), "—"), READINESS.get(av.get("testing"), "—")]]
    for k in ("critical", "major", "minor"):
        rows.append([f"{SEV_ICON[k]} {SEV_PLURAL[k][2].capitalize()}", num(bf.get(k)) if k in bf else "—",
                     num(af.get(k)) if k in af else "—"])
    out += table(["", "До ответов", "После ответов"], rows, [":---", ":---:", ":---:"])
    out += ["", f"Снято {num(cl.get('resolved', 0))}, уточнено {num(cl.get('changed', 0))}, осталось открытыми "
                f"{num(cl.get('open', 0))}, новых конфликтов из-за ответов {len(cl.get('new_findings') or [])}"
                + (f": {c.f_links(cl['new_findings'])}" if cl.get("new_findings") else "")
                + ". Подробно — [приложение А](#pa).", ""]
    return out


def _clarification_details(c: _Ctx) -> list[str]:
    cl = c.r.get("clarification") or {}
    if not cl:
        return []
    out = ["### Что изменили ответы", ""]
    changes = [x for x in cl.get("changes") or [] if isinstance(x, dict)]
    if changes:
        rows = []
        for x in changes:
            fid = x.get("finding_id") or ""
            before = SEV_ICON.get(x.get("severity_before"), "—")
            after = SEV_ICON.get(x.get("severity_after"), "—") if x.get("status") != "resolved" else "—"
            title = x.get("title_after") or x.get("title") or ""
            rows.append([c.f_link(fid) + " " + cell(title), before, CHANGE_STATUS.get(x.get("status"), "—"), after,
                         cell(x.get("reason")), ", ".join(f"[{q}](#{anchor(q)})" for q in x.get("question_ids") or [])
                         or "общее решение"])
        out += table(["Дефект", "Было", "Итог", "Стало", "Почему", "Ответ"], rows,
                      [":---", ":---:", ":---", ":---:", ":---", ":---"]) + [""]
    else:
        out += ["Ответы не изменили ни одного дефекта.", ""]
    if cl.get("decisions"):
        out += ["**Общие решения владельца:** " + "; ".join(esc(d) for d in cl["decisions"]) + ".", ""]
    if cl.get("unanswered"):
        out += ["**Без ответа:** " + ", ".join(f"[{q}](#{anchor(q)})" for q in cl["unanswered"]) + ".", ""]
    return out


def _passport(c: _Ctx) -> list[str]:
    run, doc = c.run, c.doc
    st, fn = when(run.get("started_at")), when(run.get("finished_at"))
    if st and fn:
        stamp = f"{st:%d.%m.%Y %H:%M}–{fn:%H:%M} (UTC+5)" if st.date() == fn.date() else \
            f"{st:%d.%m.%Y %H:%M} – {fn:%d.%m.%Y %H:%M} (UTC+5)"
    elif st:
        stamp = f"{st:%d.%m.%Y %H:%M} (UTC+5)"
    else:
        stamp = "—"
    models = ", ".join(f"`{m}`" for m in run.get("models_used") or []) or ("не использовалась" if c.offline else "—")
    asked = run.get("model_requested")
    model = models + (f" (запрошена: `{asked}`)" if asked and asked not in (run.get("models_used") or []) else "")
    calls = run.get("calls") or {}
    tok = run.get("tokens") or {}
    fmt = FORMATS.get(doc.get("format"), doc.get("format") or "—")
    size = f"{num(doc.get('lines'))} {plural(int(doc.get('lines') or 0), 'строка', 'строки', 'строк')}"
    if doc.get("pages"):
        size += f", {doc['pages']} {plural(int(doc['pages']), 'страница', 'страницы', 'страниц')}"
    stages = run.get("stages") or {}
    bad = [f"{stage_name(k)} — {STAGE_STATUS.get(v, v).split(' ', 1)[-1]}"
           for k, v in stages.items() if v != "ok"]
    if not stages:
        stage_txt = "—"
    elif not bad:
        stage_txt = f"все {len(stages)} выполнены"
    else:
        stage_txt = f"выполнено {len(stages) - len(bad)} из {len(stages)}; " + "; ".join(bad)
    cost = run.get("cost_usd")
    commit = (f"`{run['commit']}`" if run.get("commit") else "не записан") + \
        (" (рабочая копия с изменениями)" if run.get("dirty") else "")
    rows = [
        ["Документ", f"«{cell(doc.get('title') or '—')}»"],
        ["Файл", f"`{doc.get('file') or '—'}` · {fmt} · {size}"],
        ["Хеш файла (`SHA-256`)", f"`{doc.get('sha256') or '—'}`"],
        ["Дата и время", stamp],
        ["Модель", model.replace("|", "\\|")],
        ["Провайдер", PROVIDERS.get(run.get("provider")) or f"`{run.get('provider') or '—'}`"],
        ["Агент", f"«{cell(run.get('agent') or 'BCC Review')}» {cell(run.get('version') or '')}, коммит {commit}"],
        ["Обращений к модели", f"{num(calls.get('total', 0))} (из кэша {num(calls.get('cached', 0))}, "
                               f"с ошибкой {num(calls.get('failed', 0))}, делений пакета {num(calls.get('split', 0))})"],
        ["Токены", f"вход {num(tok.get('input', 0))}, выход {num(tok.get('output', 0))}"
                   + (f" · ≈ ${cost:.2f}" if isinstance(cost, (int, float)) and cost else "")],
        ["Длительность", duration(run.get("duration_s"))],
        ["Статус прогона", STATUS.get(run.get("status"), run.get("status") or "—")],
        ["Этапы", cell(stage_txt)],
    ]
    cl = c.r.get("clarification") or {}
    if cl:
        rows.append(["Ответы владельца", f"учтены: ответов {len(cl.get('answers') or [])}, общих решений "
                                         f"{len(cl.get('decisions') or [])}, без ответа {len(cl.get('unanswered') or [])}"])
    warns = (run.get("warnings") or []) + (doc.get("warnings") or [])
    if warns:
        rows.append(["Предупреждения", cell("; ".join(warns[:5]) + (f" и ещё {len(warns) - 5}" if len(warns) > 5 else ""))])
    return [h2("s1", "1. Паспорт прогона"), ""] + table(["Поле", "Значение"], rows) + [""]


def _segmentation(c: _Ctx) -> list[str]:
    reqs = c.reqs
    out = [h2("s2", "2. Нарезка требований"), "",
           f"Выделено {len(reqs)} {plural(len(reqs), 'требование', 'требования', 'требований')}. ID R-… присвоены "
           f"агентом в порядке документа; в столбце «ID в документе» — номер или пункт документа, если он есть. "
           f"Дословная цитата каждого требования сохранена в `report.json`.", ""]
    if not reqs:
        why = ("нарезка выполняется моделью, в режиме без модели её нет; замечания правил привязаны к строкам "
               "документа" if c.offline else "этап нарезки не дал результата (приложение Д)")
        return out[:2] + [f"Требования не выделены: {why}.", ""]
    rows = []
    for q in reqs:
        rows.append([f"<a id=\"{anchor(q.get('id'))}\"></a>{q.get('id')}", cell(q.get("source_id") or "—"),
                     REQ_KIND.get(q.get("kind"), cell(q.get("kind"))), cell(q.get("summary")), cell(place(q))])
    out += table(["ID", "ID в документе", "Вид", "Кратко", "Где"], rows)
    exc = c.r.get("excluded") or []
    if exc and c.level >= 2:
        out += ["", f"**Не вошло в нарезку ({len(exc)}):** " + "; ".join(
            f"{esc(e.get('what'))} ({lines_word(e.get('line_start'), e.get('line_end'))}) — {esc(e.get('reason'))}"
            for e in exc) + "."]
    elif exc:
        out += ["", f"**Не вошло в нарезку ({len(exc)})** — не требования: шаблоны, метаданные, служебный текст.", ""]
        out += table(["Фрагмент", "Строки", "Причина"],
                     [[cell(e.get("what")), lines_word(e.get("line_start"), e.get("line_end")).replace("строки ", "")
                       .replace("строка ", ""), cell(e.get("reason"))] for e in exc])
    return out + [""]


def _per_requirement(c: _Ctx) -> list[str]:
    out = [h2("s3", "3. Проверка каждого требования"), ""]
    by_req: dict[str, list[dict]] = {}
    doc_level = []
    for f in c.findings:
        ids = [r for r in f.get("requirement_ids") or [] if r in c.req_by_id]
        if not ids:
            doc_level.append(f)
        for r in ids:
            by_req.setdefault(r, []).append(f)
    used = [k for k in INDIVIDUAL if any(f.get("criterion") == k for f in c.findings)]
    has_set = any(f.get("criterion") in SET_CRITERIA for f in c.findings)
    has_risk = any(f.get("criterion") == "risk" for f in c.findings)
    cols = [(k, CRITERIA[k][2]) for k in used] + ([("set", "Нб")] if has_set else []) + \
           ([("risk", "Рс")] if has_risk else [])
    unused = [CRITERIA[k][0].lower() for k in INDIVIDUAL if k not in used]
    legend = "; ".join(f"{lab} — {CRITERIA[k][0].lower()}" for k, lab in cols if k in CRITERIA and k != "risk")
    if has_set:
        legend += ("; " if legend else "") + "Нб — критерии набора (раздел 4)"
    if has_risk:
        legend += "; Рс — ИБ и операционные риски"
    out += ["### 3.1. Матрица: требование × нарушенный критерий", "",
            f"Столбцы: {legend}. В клетке — самая серьёзная находка: 🔴 критичная, 🟠 существенная, "
            f"🟡 незначительная; «·» — нарушений нет."
            + (f" Критерии без нарушений во всём документе: {', '.join(unused)}." if unused else ""), ""]
    rows, clean = [], []
    for q in c.reqs:
        fs = by_req.get(q.get("id"), [])
        if not fs:
            clean.append(q.get("id"))
            continue
        row = [c.req_label(q.get("id")), SEV_ICON.get(_worst(fs), "")]
        for k, _ in cols:
            if k == "set":
                hit = [f for f in fs if f.get("criterion") in SET_CRITERIA]
            else:
                hit = [f for f in fs if f.get("criterion") == k]
            row.append(SEV_ICON.get(_worst(hit), "·") if hit else "·")
        row.append(c.f_links(sorted({f["id"] for f in fs}, key=_id_num)))
        rows.append(row)
    if doc_level:
        row = ["документ в целом", SEV_ICON.get(_worst(doc_level), "")]
        for k, _ in cols:
            hit = [f for f in doc_level if (f.get("criterion") in SET_CRITERIA if k == "set" else f.get("criterion") == k)]
            row.append(SEV_ICON.get(_worst(hit), "·") if hit else "·")
        row.append(c.f_links([f["id"] for f in doc_level]))
        rows.append(row)
    if rows:
        out += table(["Требование", "Итог"] + [lab for _, lab in cols] + ["Дефекты"], rows,
                     [":---", ":---:"] + [":---:"] * len(cols) + [":---"])
        out.append("")
    if clean:
        out += [f"✅ Без замечаний ({len(clean)}): " + ", ".join(c.req_label(r) for r in clean) + ".", ""]
    if not c.findings:
        out += ["Дефектов не найдено.", ""]

    cards = [f for f in c.findings if f.get("severity") in ("critical", "major")]
    out += ["### 3.2. Критичные и существенные дефекты", ""]
    if not cards:
        out += ["Критичных и существенных дефектов нет.", ""]
    for f in cards:
        out += _card(c, f)
    minors = [f for f in c.findings if f.get("severity") not in ("critical", "major")]
    out += ["### 3.3. Незначительные дефекты", ""]
    if minors:
        rows = []
        for f in minors:
            ev = (f.get("evidence") or [{}])[0]
            rows.append([f"<a id=\"{anchor(f['id'])}\"></a>🟡 {f['id']}",
                         cell(f.get("title")),
                         ", ".join(c.req_label(r) for r in f.get("requirement_ids") or []) or "документ",
                         cell(_criterion_name(f.get("criterion"))),
                         cell(place(ev)) + ": " + quote_md(ev.get("quote"), 90, in_table=True),
                         pcell(f.get("recommendation"))])
        out += table(["Дефект", "Суть", "Требования", "Критерий", "Где", "Что исправить"], rows)
        out.append("")
    else:
        out += ["Незначительных дефектов нет.", ""]
    sig = [g for g in c.r.get("signals") or [] if isinstance(g, dict) and g.get("kind") != "inventory"
           and g.get("quote")]
    if sig and c.offline:
        limit = 20 if c.level < 2 else 10
        out += ["### 3.4. Подсказки для ручной проверки", "",
                "Места, на которые указали правила; это не дефекты, их стоит перечитать.", ""]
        out += [f"- строка {g.get('line') or g.get('line_start') or '—'}: {quote_md(g.get('quote'), 100)} — "
                f"{esc(g.get('message') or g.get('note') or '')}" for g in sig[:limit]]
        if len(sig) > limit:
            out.append(f"- и ещё {len(sig) - limit} — в `report.json`, поле `signals`.")
        out.append("")
    return out


def _rewrite_from(f: dict) -> dict | None:
    """Цитата, которую заменяет «стало»: та, где больше общих слов с новой формулировкой."""
    evs = f.get("evidence") or []
    if not evs or not f.get("rewrite"):
        return None
    target = f.get("rewrite_line")
    for e in evs:
        if target and e.get("line_start") == target:
            return e
    words = set(re.findall(r"\w{3,}", f["rewrite"].lower()))
    return max(evs, key=lambda e: len(words & set(re.findall(r"\w{3,}", str(e.get("quote", "")).lower()))))


def _card(c: _Ctx, f: dict) -> list[str]:
    sev = f.get("severity")
    badge = {"changed": " · уточнён после ответов", "new": " · новый после ответов"}.get(
        f.get("status_after_answers") or f.get("status"), "")
    out = [f"#### <a id=\"{anchor(f['id'])}\"></a>{SEV_ICON.get(sev, '')} {f['id']}. {prose(f.get('title'))}", ""]
    meta = []
    reqs = [c.req_label(r) for r in f.get("requirement_ids") or []]
    meta.append("**Требования:** " + (", ".join(reqs) if reqs else "документ в целом"))
    meta.append(f"**Критерий:** {esc(_criterion_name(f.get('criterion')))} ({esc(_criterion_ref(f))})")
    meta.append(f"**Вид:** {esc(KIND_NAME.get(f.get('kind'), f.get('kind') or '—'))}")
    if f.get("blocks") and f.get("blocks") != "none":
        meta.append(f"**Блокирует:** {BLOCKS.get(f['blocks'])}")
    srcs = [source_name(s) for s in f.get("sources") or []]
    if srcs:
        meta.append("**Нашли:** " + ", ".join(dict.fromkeys(srcs)))
    out += [" · ".join(meta) + badge, ""]
    evs = []
    for ev in f.get("evidence") or []:
        warn = " ⚠️ цитата не сверена" if ev.get("verified") == "missing" else ""
        evs.append(f"{esc(place(ev))}: {quote_md(ev.get('quote'))}{warn}")
    if c.level >= 3 and f.get("severity") != "critical":
        out += ["**Где:** " + "; ".join(evs), ""]
    else:
        out += [f"- {e}" for e in evs] + [""]
    fields = [("Проблема", f.get("problem")), ("Сценарий", f.get("scenario")), ("Последствия", f.get("impact")),
              ("Что исправить", f.get("recommendation"))]
    body = [f"**{name}.** {prose(val)}" for name, val in fields if val]
    src = _rewrite_from(f)
    if src is not None:
        body.append(f"**Было → стало.** {lines_word(src.get('line_start'), src.get('line_end')).capitalize()}: "
                    f"{quote_md(src.get('quote'))} → «{prose(f.get('rewrite'))}»")
    if f.get("question"):
        qids = c.q_by_finding.get(f["id"], [])
        link = (" → " + ", ".join(f"[{q}](#{anchor(q)})" for q in qids)) if qids else ""
        body.append(f"**Вопрос владельцу.** {prose(f['question'])}{link}")
    out += [line + "  " if i < len(body) - 1 else line for i, line in enumerate(body)]
    return out + [""]


def _set_check(c: _Ctx) -> list[str]:
    out = [h2("s4", "4. Проверка набора требований"), "", "### 4.1. Критерии набора", ""]
    rows = []
    for k in SET_CRITERIA:
        fs = [f for f in c.findings if _set_bucket(f) == k]
        w = _worst(fs)
        verdict = (f"{SEV_ICON[w]} нарушен" if w else "✅ нарушений не найдено")
        rows.append([CRITERIA[k][0], CRITERIA[k][1], verdict,
                     c.f_links(sorted({f["id"] for f in fs}, key=_id_num)) if fs else "—"])
    out += table(["Критерий", "Стандарт", "Итог", "Дефекты"], rows) + [""]

    pairs = c.r.get("pair_checks") or []
    out += ["### 4.2. Противоречия по сценариям", ""]
    if pairs:
        cnt = {k: sum(1 for p in pairs if p.get("verdict") == k) for k in ("conflict", "compatible", "undefined")}
        out += [f"Проверено пар: {len(pairs)} — противоречат {cnt['conflict']}, совместимы {cnt['compatible']}, "
                f"не определено {cnt['undefined']}. Пара считается противоречивой, только если оба места говорят "
                f"об одном и том же поле, событии или величине.", ""]
        rows = []
        for p in sorted(pairs, key=lambda p: {"conflict": 0, "undefined": 1}.get(p.get("verdict"), 2)):
            mark = {"conflict": "⛔ противоречат", "compatible": "✅ совместимы",
                    "undefined": "❔ не определено"}.get(p.get("verdict"), "—")
            rows.append([f"{c.req_label(p.get('a'))} ↔ {c.req_label(p.get('b'))}", cell(p.get("subject")),
                         cell(p.get("scenario")), cell(p.get("outcome_a")), cell(p.get("outcome_b")), mark,
                         c.f_links(p.get("finding_ids"))])
        out += table(["Пара", "Общий предмет", "Сценарий", "Исход по первому", "Исход по второму", "Итог", "Дефект"],
                     rows) + [""]
    else:
        out += ["Попарная сверка не выполнялась" + (" (режим без модели)." if c.offline else "."), ""]

    acc = c.r.get("acceptance_checks") or []
    out += ["### 4.3. Исполнение критериев приёмки", "",
            "Для каждого критерия приёмки агент выводит ожидаемый результат из правил документа и сравнивает с "
            "указанным в критерии.", ""]
    if acc:
        rows = []
        for a in acc:
            mark = {"match": "✅ совпадает", "conflict": "⛔ противоречит",
                    "undefined": "❔ правила не определяют"}.get(a.get("verdict"), "—")
            rows.append([c.req_label(a.get("row_requirement_id")), cell(a.get("row_facts")),
                         ", ".join(c.req_label(r) for r in a.get("rule_requirement_ids") or []) or "—",
                         cell(a.get("expected_by_rules")), cell(a.get("stated")), mark, c.f_links(a.get("finding_ids"))])
        out += table(["Критерий", "Исходные данные", "Правила", "Ожидается по правилам", "Указано в критерии",
                      "Итог", "Дефект"], rows) + [""]
    else:
        out += ["Критерии приёмки не исполнялись: в документе их нет или этап не выполнялся.", ""]

    out += _coverage(c)

    glossary = c.r.get("glossary") or []
    out += ["### 4.5. Глоссарий разночтений", ""]
    if glossary:
        rows = [[cell(g.get("concept")),
                 ", ".join(f"«{cell(t.get('term'))}»" + (f" (строка {t['line']})" if t.get("line") else "")
                           for t in g.get("terms") or []),
                 cell(g.get("problem")), c.f_links(g.get("finding_ids"))] for g in glossary]
        out += table(["Понятие", "Как названо в документе", "Проблема", "Дефект"], rows) + [""]
    else:
        out += ["Разночтений терминов не найдено.", ""]
    return out


def _coverage(c: _Ctx) -> list[str]:
    out = ["### 4.4. Покрытие требований критериями приёмки", ""]
    acc_ids = [q["id"] for q in c.reqs if q.get("kind") == "acceptance"]
    trace = {t.get("requirement_id"): t for t in c.r.get("trace") or []}
    conflict = {(a.get("row_requirement_id"), r) for a in c.r.get("acceptance_checks") or []
                if a.get("verdict") == "conflict" for r in a.get("rule_requirement_ids") or []}
    checked = {}
    for a in c.r.get("acceptance_checks") or []:
        for r in a.get("rule_requirement_ids") or []:
            checked.setdefault(r, set()).add(a.get("row_requirement_id"))
    rows_ids = [q["id"] for q in c.reqs if q.get("kind") in VERIFY_KINDS or q.get("id") in trace]
    rows_ids = [r for r in rows_ids if r not in acc_ids]
    if not acc_ids:
        return out + ["В документе нет критериев приёмки: ни одно требование не подтверждается приёмкой.", ""]
    if not trace and not checked:
        return out + ["Трассировка не выполнялась" + (" (режим без модели)." if c.offline else "."), ""]
    covered, rows, bare = 0, [], []
    for rid in rows_ids:
        t = trace.get(rid, {})
        by = set(t.get("verified_by") or []) | checked.get(rid, set())
        if by:
            covered += 1
        elif not t.get("note"):
            bare.append(rid)
            continue
        cells = []
        for aid in acc_ids:
            if (aid, rid) in conflict:
                cells.append("⛔")
            elif aid in by:
                cells.append("✓")
            else:
                cells.append("·")
        rows.append([c.req_label(rid)] + cells + [cell(t.get("note") or ("нет критерия приёмки" if not by else ""))])
    out += [f"Покрыто приёмкой {covered} из {len(rows_ids)} требований, которые должны проверяться. "
            f"✓ — критерий проверяет требование, ⛔ — критерий противоречит требованию, «·» — не проверяет.", ""]
    out += table(["Требование"] + [c.req_label(a) for a in acc_ids] + ["Чего не хватает"], rows,
                 [":---"] + [":---:"] * len(acc_ids) + [":---"])
    if bare:
        out += ["", f"Без критерия приёмки также ({len(bare)}): " + ", ".join(c.req_label(r) for r in bare) + "."]
    return out + [""]


def _summary(c: _Ctx) -> list[str]:
    s = c.summary
    fs = s.get("findings", {})
    total = sum(fs.get(k, 0) for k in SEV_ICON)
    nreq = s.get("requirements", len(c.reqs))
    clean = s.get("requirements_without_findings", 0)
    qs = c.r.get("questions") or []
    ok, qt = s.get("quotes_verified", 0), s.get("quotes_total", s.get("quotes_verified", 0))
    rows = [["Требований выделено", num(nreq)], ["С нарушениями", num(nreq - clean)], ["Без замечаний", num(clean)],
            ["Дефектов всего", f"{total}: " + " · ".join(f"{SEV_ICON[k]} {fs.get(k, 0)}" for k in SEV_ICON)],
            ["Цитат сверено программой", f"{ok} из {qt}"],
            ["Вопросов владельцу", f"{len(qs)}, из них блокирующих {sum(1 for q in qs if q.get('blocking'))}"]]
    out = [h2("s5", "5. Сводка"), ""] + table(["Показатель", "Значение"], rows) + [""]
    out += ["**Критичные дефекты по видам** (п. 6 ТЗ: непроверяемые, противоречивые, неполные)", ""]
    rows = []
    for cat in ("contradictory", "unverifiable", "incomplete", "other"):
        all_cat = [f for f in c.findings if _category(f) == cat]
        crit = [f for f in all_cat if f.get("severity") == "critical"]
        if not all_cat:
            continue
        lst = "; ".join(f"[{f['id']}](#{anchor(f['id'])}) {cell(f.get('title'))}" for f in crit) or "—"
        rows.append([CATEGORY[cat], str(len(crit)), lst, str(len(all_cat))])
    out += (table(["Вид", "Критичных", "Критичные дефекты", "Всего этого вида"], rows, [":---", ":---:", ":---", ":---:"])
            if rows else ["Дефектов нет."]) + [""]
    out += ["**Нарушения по критериям**", ""]
    rows = []
    for k in list(CRITERIA) + sorted({f.get("criterion") for f in c.findings} - set(CRITERIA)):
        fs_k = [f for f in c.findings if f.get("criterion") == k]
        if fs_k:
            rows.append([_criterion_name(k)] + [str(sum(1 for f in fs_k if f.get("severity") == sv) or "·")
                                                 for sv in ("critical", "major", "minor")] + [str(len(fs_k))])
    rows.sort(key=lambda r: -int(r[-1]))
    out += (table(["Критерий", "🔴", "🟠", "🟡", "Всего"], rows, [":---", ":---:", ":---:", ":---:", ":---:"])
            if rows else ["Нарушений нет."]) + [""]
    return out


def _conclusion(c: _Ctx) -> list[str]:
    v = c.verdict
    out = [h2("s6", "6. Итог"), ""]
    out += table(["Работа", "Решение"], [["Разработка", f"**{READINESS.get(v.get('development'), '—')}**"],
                                         ["Тестирование", f"**{READINESS.get(v.get('testing'), '—')}**"]]) + [""]
    reason = v.get("summary") or _auto_reason(c)
    out += [f"**Обоснование.** {prose(reason)}", ""]
    first = _fix_first(c)
    if first:
        out += ["**Что исправить в первую очередь**", ""]
        for i, f in enumerate(first, 1):
            out.append(f"{i}. {c.f_link(f['id'], True)} {prose(f.get('title'))}. Что сделать: "
                       f"{prose(shorten(f.get('recommendation'), 260))}")
        out.append("")
    nc = [x for x in c.r.get("not_checked") or [] if isinstance(x, str)]
    if nc:
        out += ["**Что не проверялось в этом прогоне**", ""] + [f"- {esc(x)}" for x in nc] + [""]
    if c.offline:
        out += ["Без модели программа выносит «нельзя» только при противоречии двух мест документа, найденном "
                "правилом; иначе вердикт «не определено» — для полного ревью нужен прогон с моделью.", ""]
    else:
        out += ["Вердикт считает программа: критичный дефект, блокирующий направление, — «нельзя начинать»; иначе "
                "три и более существенных — «с условиями»; иначе «можно». Подробнее — приложение Е.", ""]
    return out


def _auto_reason(c: _Ctx) -> str:
    crit = [f for f in c.findings if f.get("severity") == "critical" and f.get("blocks") != "none"]
    if crit:
        return (f"Найдено {len(crit)} {plural(len(crit), 'критичный дефект', 'критичных дефекта', 'критичных дефектов')}, "
                f"блокирующих работу: " + "; ".join(f"{f['id']} — {f.get('title')}" for f in crit[:5]) + ".")
    majors = [f for f in c.findings if f.get("severity") == "major"]
    if majors:
        return f"Критичных дефектов нет; существенных — {len(majors)}, их стоит исправить параллельно с работой."
    return "Критичных и существенных дефектов не найдено."


def _appendix_questions(c: _Ctx) -> list[str]:
    qs = c.r.get("questions") or []
    out = [h2("pa", "Приложение А. Вопросы владельцу"), ""]
    if not qs:
        return out + ["Вопросов нет" + (" (режим без модели)." if c.offline else "."), ""]
    blocking = sum(1 for q in qs if q.get("blocking"))
    cl = c.r.get("clarification") or {}
    answered = {a.get("question_id"): a for a in cl.get("answers") or [] if isinstance(a, dict)}
    out += [f"{len(qs)} {plural(len(qs), 'вопрос', 'вопроса', 'вопросов')}, блокирующих — {blocking}. "
            f"Ответ — буква варианта или свой текст, по строке на вопрос (`Q-01: B`); повторный прогон с ответами: "
            f"`python -m bcc_review ВХОД ОТЧЁТ.md --answers ответы.md`.", ""]
    for q in sorted(qs, key=lambda q: (not q.get("blocking"), _id_num(q.get("id")))):
        head = [f"**<a id=\"{anchor(q.get('id'))}\"></a>{q.get('id')}**"
                + (f" {esc(q['topic'])}" if q.get("topic") else ""),
                "⛔ блокирует" if q.get("blocking") else "не блокирует"]
        if q.get("to"):
            head.append(f"кому: {esc(q['to'])}")
        if q.get("finding_ids"):
            head.append(f"к {c.f_links(q['finding_ids'])}")
        lines = [" · ".join(head), prose(q.get("question"))]
        evs = [e for e in q.get("evidence") or [] if isinstance(e, dict) and e.get("quote")]
        if evs:
            lines.append("Где: " + "; ".join(f"{lines_word(e.get('line_start'), e.get('line_end'))} "
                                             f"{quote_md(e.get('quote'), 90)}" for e in evs[:3]))
        opts = [o for o in q.get("options") or [] if str(o).strip()]
        tail = []
        if q.get("why"):
            tail.append(f"Зачем: {prose(q['why'])}")
        a = answered.get(q.get("id"))
        if a:
            choice = f"{a['choice']} — " if a.get("choice") else ""
            tail.append(f"**Ответ владельца:** {prose(choice + str(a.get('answer') or ''))}")
        letter = [LETTERS[i] if i < len(LETTERS) else str(i + 1) for i in range(len(opts))]
        if opts and c.level < 2:
            out += [ln + "  " if i < len(lines) - 1 else ln for i, ln in enumerate(lines)] + [""]
            out += [f"- **{letter[i]}** {prose(o)}" for i, o in enumerate(opts)] + [""]
            lines = tail
        else:
            if opts:
                lines.append("Варианты: " + "; ".join(f"**{letter[i]}** {prose(str(o).rstrip('. '))}"
                                                      for i, o in enumerate(opts)))
            lines += tail
        if lines:
            out += [ln + "  " if i < len(lines) - 1 else ln for i, ln in enumerate(lines)] + [""]
    out += _clarification_details(c)
    return out


def _appendix_tests(c: _Ctx) -> list[str]:
    tc = c.r.get("test_cases") or []
    out = [h2("pb", "Приложение Б. Черновик тест-кейсов"), ""]
    if not tc:
        return out + ["Тест-кейсы не составлялись" + (" (режим без модели)." if c.offline else "."), ""]
    undefined = sum(1 for t in tc if t.get("expected_defined") is False)
    out += [f"{len(tc)} {plural(len(tc), 'тест-кейс', 'тест-кейса', 'тест-кейсов')} для раздела тестирования; "
            f"❔ — ожидаемый результат документ не определяет ({undefined}), сначала нужен ответ владельца.", ""]
    rows = [[t.get("id", ""), ", ".join(c.req_label(r) for r in t.get("requirement_ids") or []) or "—",
             cell(t.get("title")), cell(t.get("given")), cell(t.get("when")),
             ("❔ " if t.get("expected_defined") is False else "") + cell(t.get("then")), cell(t.get("gap"))]
            for t in tc]
    return out + table(["ID", "Требования", "Проверка", "Дано", "Когда", "Тогда", "Чего нет в приёмке"], rows) + [""]


def _appendix_checklist(c: _Ctx) -> list[str]:
    cl = c.r.get("checklist") or []
    out = [h2("pv", "Приложение В. Чек-лист «Ревью требований», заполненный агентом"), ""]
    if not cl:
        return out + ["Чек-лист не заполнялся" + (" (режим без модели)." if c.offline else "."), ""]
    src = c.r.get("checklist_source") or c.run.get("checklist_source")
    origin = {"document": "Пункты — из таблицы «Ревью требований» самого документа",
              "bank": "Пункты — 14 вопросов чек-листа «Ревью требований» банка"}.get(src, "Пункты чек-листа банка")
    out += [f"{origin}; ответ агента обоснован дефектами отчёта. Итоговую отметку ставит ответственный.", ""]
    rows = [[cell(i.get("item")), CHECK_ANSWER.get(str(i.get("answer", "")).strip().lower(), cell(i.get("answer"))),
             cell(i.get("comment")), c.f_links(i.get("finding_ids"))] for i in cl]
    return out + table(["Пункт", "Ответ агента", "Комментарий", "Дефекты"], rows) + [""]


def _appendix_rewrites(c: _Ctx) -> list[str]:
    out = [h2("pg", "Приложение Г. Было → стало"), ""]
    items = []
    for rw in c.r.get("rewrites") or []:
        if rw.get("after") or rw.get("rewrite"):
            items.append((rw.get("finding_id") or ", ".join(rw.get("finding_ids") or []), rw.get("line_start"),
                          rw.get("line_end"), rw.get("before") or rw.get("quote") or "", rw.get("after") or rw.get("rewrite")))
    if not items:
        for f in c.findings:
            if c.level >= 2 and f.get("severity") in ("critical", "major"):
                continue
            src = _rewrite_from(f)
            if src is not None:
                items.append((f["id"], src.get("line_start"), src.get("line_end"), src.get("quote"), f.get("rewrite")))
    if not items and c.level >= 2:
        return out + ["Формулировки «было → стало» приведены в карточках раздела 3.2 и в `report.json`.", ""]
    if not items:
        return out + ["Готовых формулировок нет.", ""]
    out += ["Готовые формулировки для правки ТЗ; «<уточнить: …>» — место, где нужен ответ владельца.", ""]
    rows = [[c.f_link(fid, True) if fid in c.f_by_id else esc(fid), lines_word(a, b).replace("строки ", "")
             .replace("строка ", ""), quote_md(before, 120, in_table=True), cell(after)]
            for fid, a, b, before, after in items]
    out += table(["Дефект", "Строка", "Было", "Стало"], rows)
    if c.r.get("revised_file"):
        out += ["", f"Исправленный текст ТЗ целиком: «{esc(c.r['revised_file'])}»."]
    return out + [""]


def _appendix_how(c: _Ctx) -> list[str]:
    run = c.run
    stages = run.get("stages") or {}
    stats = run.get("stage_stats") or {}
    out = [h2("pd", "Приложение Д. Как работал агент"), ""]
    if stages:
        rows = []
        for k, v in stages.items():
            name, what = STAGES.get(stage_key(k), (stage_name(k), ""))
            st = stats.get(k) or {}
            rows.append([name, what, STAGE_STATUS.get(v, v), num(st.get("calls")) if "calls" in st else "—",
                         duration(st.get("seconds")) if "seconds" in st else "—",
                         num(st.get("candidates")) if "candidates" in st else "—"])
        out += table(["Этап", "Что делает", "Итог", "Вызовов", "Время", "Кандидатов"], rows,
                     [":---", ":---", ":---", ":---:", ":---:", ":---:"]) + [""]
    proposed = sum(int((stats.get(k) or {}).get("candidates") or 0) for k in stats)
    accepted = sum(len(f.get("candidate_ids") or []) for f in c.r.get("findings") or [])
    rej = c.r.get("rejected") or []
    nfind = len(c.findings)
    if accepted or rej:
        total = accepted + len(rej)
        extra = f" (по данным этапов предложено {proposed})" if proposed and proposed != total else ""
        out += [f"Кандидатов в дефекты: {total}{extra}. Вошли в {nfind} "
                f"{plural(nfind, 'дефект', 'дефекта', 'дефектов')} — {accepted} (дубли объединены); отклонено — "
                f"{len(rej)}. Кандидат без найденной в документе цитаты в отчёт не попадает.", ""]
    if rej:
        out += ["**Отклонённые кандидаты**", ""]
        rows = []
        limit = MAX_REJECTED_ROWS if c.level < 1 else 10
        for r in rej[:limit]:
            reason = esc(r.get("reason"))
            if r.get("duplicate_of"):
                reason += f" → {c.f_link(r['duplicate_of'])}"
            line = r.get("line") if isinstance(r.get("line"), int) and r.get("line") else None
            rows.append([esc(r.get("id") or r.get("candidate_id") or "—"), esc(source_name(r.get("source"))),
                         cell(r.get("title")) + (f" (строка {line})" if line else ""), reason.replace("|", "\\|")])
        out += table(["Кандидат", "Источник", "Что предлагалось", "Почему отклонён"], rows)
        if len(rej) > limit:
            out += ["", f"Ещё {len(rej) - limit} — в `report.json`, поле `rejected`."]
        out.append("")
    warns = run.get("warnings") or []
    if warns:
        out += ["**Предупреждения прогона**", ""] + [f"- {esc(w)}" for w in warns[:15]] + [""]
    return out


def _appendix_method(c: _Ctx) -> list[str]:
    out = [h2("pe", "Приложение Е. Методика"), "",
           "Статическое ревью текста до разработки: программа не запускается. Документ нумеруется построчно; "
           "проверяющие роли (аналитик, тестировщик, архитектор, риски, набор целиком) предлагают кандидатов с "
           "дословными цитатами; программа находит каждую цитату в документе и сама определяет строку; судья "
           "объединяет дубли, отклоняет ложные и калибрует серьёзность; вердикт считает программа.", ""]
    if c.level >= 1:
        out += ["**Критерии.** Отдельное требование (ISO/IEC/IEEE 29148:2018 п. 5.2.5, 5.2.7): "
                + ", ".join(CRITERIA[k][0].lower() for k in INDIVIDUAL) + ". Набор (29148 п. 5.2.6, IEEE 830-1998 "
                "п. 4.3): " + ", ".join(CRITERIA[k][0].lower() for k in SET_CRITERIA)
                + ". Плюс ИБ и операционные риски по чек-листу банка.", ""]
    else:
        rows = [[CRITERIA[k][0], CRITERIA[k][1], "требование" if k in INDIVIDUAL else
                 ("набор" if k in SET_CRITERIA else "риски")] for k in CRITERIA]
        out += table(["Критерий", "Стандарт", "Уровень"], rows) + [""]
    out += ["**Шкала серьёзности**", "",
            "- 🔴 **Критичный** — два места документа дают несовместимый результат для одного входа; ключевое "
            "правило нельзя однозначно реализовать или проверить; нет информации, без которой основную функцию не "
            "реализовать.",
            "- 🟠 **Существенный** — неоднозначность или неполнота, ведущая к неверной реализации или спору при "
            "приёмке; непокрытая ветка (ошибки, повторы, отмены, границы); риск ИБ; расхождение типов, единиц, "
            "терминов.",
            "- 🟡 **Незначительный** — оформление, незаполненный шаблон, версия и согласования, отсутствие ID и "
            "приоритетов, стиль.", "",
            "**Вердикт.** Критичный дефект, блокирующий разработку, — разработку начинать нельзя; то же для "
            "тестирования. Иначе при трёх и более существенных дефектах по направлению — «можно с условиями»: "
            "начинать части, не затронутые дефектами, и исправлять их параллельно. Иначе — «можно». Частичный "
            "прогон — не выше «с условиями».", "",
            "**Сверка цитат.** Сравнение без учёта регистра, вида кавычек и тире, лишних пробелов и разметки; "
            "цитата ищется у указанной строки, затем во всём документе, ближе к требованию. Нечёткое совпадение "
            "(не ниже 92 %) допускается только рядом с указанной строкой.", ""]
    return out


# ================================================================== сборка

MAX_LINES = 900
MAX_LEVEL = 3


_LIST_KEYS = ("requirements", "excluded", "findings", "rejected", "acceptance_checks", "pair_checks", "trace",
              "glossary", "test_cases", "questions", "checklist", "rewrites")
_ID_LIST_KEYS = ("requirement_ids", "finding_ids", "candidate_ids", "sources", "rule_requirement_ids", "verified_by",
                 "implemented_by", "options", "standard_refs", "fix_first", "resolved", "changed", "added",
                 "models_used", "warnings")


def _clean_report(report) -> dict:
    """Копия отчёта, в которой у каждого поля ожидаемый тип: рендер не падает на неполных данных этапов."""
    report = report if isinstance(report, dict) else {}
    out = {}
    for k, v in report.items():
        if k in _LIST_KEYS:
            out[k] = [_clean(x) for x in v if isinstance(x, dict)] if isinstance(v, list) else []
        elif k in ("run", "document", "verdict", "summary", "recheck", "clarification"):
            out[k] = _clean(v) if isinstance(v, dict) else {}
        else:
            out[k] = v
    for k in ("run", "document", "verdict", "summary", "recheck", "clarification"):
        out.setdefault(k, {})
    for k in ("signals", "not_checked"):
        v = out.get(k)
        out[k] = [x for x in v if isinstance(x, (dict, str))] if isinstance(v, list) else []
    for key, prefix in (("findings", "D"), ("requirements", "R"), ("questions", "Q"), ("test_cases", "T")):
        for i, item in enumerate(out.get(key, []), 1):
            if not item.get("id"):
                item["id"] = f"{prefix}-{i:02d}"
    if not isinstance(out["summary"].get("findings"), dict):
        out["summary"] = {}
    return out


_STR_KEYS = {"id", "title", "kind", "criterion", "severity", "blocks", "status", "problem", "scenario", "impact",
             "recommendation", "rewrite", "question", "quote", "section", "verified", "source_id", "reason", "source",
             "candidate_id", "duplicate_of", "what", "item", "answer", "comment", "concept", "term", "problem", "to",
             "why", "given", "when", "then", "gap", "agent", "version", "commit", "provider", "model_requested",
             "file", "format", "sha256", "subject", "outcome_a", "outcome_b", "row_facts", "expected_by_rules",
             "stated", "requirement_id", "row_requirement_id", "a", "b", "note", "development", "testing",
             "started_at", "finished_at", "question_id", "status_after_answers", "choice", "message",
             "severity_before", "severity_after", "title_after", "finding_id"}


def _clean(value, key: str = ""):
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if k in _STR_KEYS and not isinstance(v, str):
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    out[k] = str(v)
                continue
            if k in ("evidence", "terms", "answers"):
                out[k] = [_clean(x, k) for x in v if isinstance(x, dict)] if isinstance(v, list) else []
            elif k in _ID_LIST_KEYS:
                out[k] = [str(x) for x in v if isinstance(x, (str, int, float)) and str(x).strip()] \
                    if isinstance(v, list) else ([str(v)] if isinstance(v, str) and v.strip() else [])
            elif v is None and k not in ("page", "pages", "cost_usd", "line", "line_a", "line_b"):
                continue
            else:
                out[k] = _clean(v, k)
        return out
    if isinstance(value, list):
        return [_clean(x) for x in value]
    return value


def _sections():
    return [(None, _header), (None, _brief), ("1. Паспорт прогона", _passport),
            ("2. Нарезка требований", _segmentation), ("3. Проверка каждого требования", _per_requirement),
            ("4. Проверка набора требований", _set_check), ("5. Сводка", _summary), ("6. Итог", _conclusion),
            ("Приложение А. Вопросы владельцу", _appendix_questions),
            ("Приложение Б. Черновик тест-кейсов", _appendix_tests),
            ("Приложение В. Чек-лист «Ревью требований», заполненный агентом", _appendix_checklist),
            ("Приложение Г. Было → стало", _appendix_rewrites), ("Приложение Д. Как работал агент", _appendix_how),
            ("Приложение Е. Методика", _appendix_method)]


def _render_level(report: dict, level: int) -> str:
    c = _Ctx(_clean_report(report), level)
    parts = []
    for title, fn in _sections():
        try:
            parts.append(fn(c))
        except Exception as exc:  # noqa: BLE001 — один сломанный раздел не должен лишить аналитика отчёта
            head = [f"## {title}", ""] if title else []
            parts.append(head + [f"⚠️ Раздел не построен: в данных прогона ошибка ({esc(type(exc).__name__)}: "
                                 f"{esc(shorten(str(exc), 160))}). Полные данные — в `report.json`.", ""])
    lines = [ln for part in parts for ln in part]
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines) + "\n"


def render(report: dict, *, max_lines: int | None = MAX_LINES) -> str:
    """Markdown-отчёт по report.json v2. Если отчёт длиннее max_lines, вспомогательные таблицы сжимаются
    (содержание дефектов не теряется: полные данные — в report.json)."""
    text = ""
    for level in range(MAX_LEVEL + 1):
        text = _render_level(report, level)
        if max_lines is None or text.count("\n") <= max_lines:
            break
    return text


def write(report: dict, path) -> str:
    from pathlib import Path

    text = render(report)
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return text
