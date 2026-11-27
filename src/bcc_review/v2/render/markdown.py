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
# своими словами: какой вопрос агент задаёт требованию или набору
CRITERION_WHAT = {
    "necessary": "без требования продукт неполон; это не дубль другого пункта",
    "appropriate": "сказано, что должна делать система, без лишнего решения реализации",
    "unambiguous": "одно толкование: определены термины, единицы, границы, часовые пояса, события",
    "complete": "есть условие, действие, ограничения, реакция на ошибки и граничные случаи",
    "singular": "одно обязательство в одном пункте",
    "feasible": "реализуемо при описанной архитектуре, данных и интеграциях",
    "verifiable": "выполнение можно доказать тестом, анализом или осмотром: есть измеримый результат",
    "correct": "соответствует предметной области и не противоречит критериям приёмки",
    "conforming": "оформлено по шаблону банка: идентификатор, модальность, заполненные поля",
    "language": "нет размытых слов, лазеек «по возможности» и открытых перечней «и т. д.»",
    "set_complete": "набор покрывает цель: обещанные операции описаны, обязательные разделы заполнены",
    "set_consistent": "ни одна пара требований, критериев приёмки или частей документа не даёт разный исход "
                      "для одного входа",
    "set_feasible": "весь набор вместе реализуем в заданных ограничениях",
    "set_comprehensible": "из набора ясно, что ожидается; одно понятие — один термин",
    "set_validatable": "можно показать, что набор достигает бизнес-цели: есть критерии приёмки",
    "ranked": "у требований указаны важность и стабильность",
    "modifiable": "правило записано в одном месте, документ версионируется",
    "traceable": "у требований есть идентификаторы и связи с источником и приёмкой",
    "risk": "нет рисков ИБ и эксплуатации: утечки данных, небезопасные методы, нет отката",
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
PROPOSING = {"rules", "analyst", "qa", "architect", "risk", "consistency"}  # этапы, которые предлагают кандидатов
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


_LREF = re.compile(r"(?:(?<![\w-])([А-Яа-яЁё]{1,20})\s+)?\bL0*(\d{1,5})"
                   r"(?:\s*[–-]\s*L?0*(\d{1,5})\b|\s+(и|или)\s+L0*(\d{1,5})\b(?!\s*[–-]))?\b")
# падеж слова «строка» после предлога: (одна строка, диапазон)
_LCASE = {**dict.fromkeys(("по", "к", "ко"), ("строке", "строкам")),
          **dict.fromkeys(("в", "во", "на", "о", "об", "при"), ("строке", "строках")),
          **dict.fromkeys(("из", "до", "от", "у", "для", "около", "после", "с", "со", "без", "кроме", "вместо",
                           "возле", "вне", "против", "среди", "из-за"), ("строки", "строк")),
          **dict.fromkeys(("между", "над", "под", "перед", "за"), ("строкой", "строками"))}


# после союза или служебного слова — именительный («строка 38 и строка 64»), после прочего слова — родительный
# («к маршруту строки 136», «текст строки 45»)
_LNOM = {"и", "или", "а", "но", "либо", "что", "где", "когда", "как", "также", "тогда", "это", "см", "т", "е", "есть",
         "вот", "здесь", "там", "даже", "только", "ни", "не"}


def _lref(m: re.Match) -> str:
    """«L038» → «строка 38» с падежом по предыдущему слову; «L38–L40» → «строки 38–40»; «L052 и L103» →
    «строки 52 и 103» (в том же падеже). Группы 4–5 есть только у этого модуля (HTML №14 передаёт свои 1–3)."""
    prep = m.group(1) or ""
    low = prep.lower()
    a, rng = m.group(2), m.group(3)
    conj, second = (m.group(4), m.group(5)) if m.re.groups >= 5 else (None, None)
    nums = f"{a}–{rng}" if rng else (f"{a} {conj} {second}" if second else a)
    if low.startswith("строк"):  # «строки L10–L12» → «строки 10–12»: слово модель уже написала
        return f"{prep} {nums}"
    if prep and low not in _LCASE and re.search(r"строк\w*\s+\S+\s*$", m.string[max(0, m.start() - 30):m.start()
                                                                                 + len(prep) + 1], re.I):
        # «строка приёмки L064»: слово «строка» уже стоит рядом в другом смысле — номер в скобках
        return f"{prep} ({'строки' if (rng or second) else 'строка'} {nums})"
    if low in _LCASE:
        one, many = _LCASE[low]
    elif prep and low not in _LNOM and len(low) >= 3:
        one, many = "строки", "строк"
    else:
        one, many = "строка", "строки"
    word = f"{many if (rng or second) else one} {nums}"
    return f"{prep} {word}" if prep else word


_CALL = re.compile(r"(?<![\w`])([A-Za-z_][A-Za-z0-9_.]*\([^()`\n]{0,60}\))")


_IDREF = re.compile(r"(?<![\w\[#/`-])([DRQ]-\d{2,4})(?![\w-])(\s*\(([^()\n]{1,60})\))?")
_KNOWN_IDS: set[str] = set()  # ID дефектов, требований и вопросов текущего отчёта (заполняет render)
_REQ_LABELS: dict[str, tuple[str, str]] = {}  # R-… → (название в документе, source_id) (заполняет render)
# «Ф-3 (R-07)» в тексте модели: название документа уже стоит перед внутренним ID
_LABEL_THEN_ID = re.compile(r"(?<![\w-])([^\s()\[\]]{1,40}(?: [^\s()\[\]]{1,20}){0,4})\s*\(\s*(R-\d{2,4})\s*\)")


def _same_label(inner: str, label: str, sid: str) -> bool:
    a = " ".join(inner.lower().replace("ё", "е").split())
    return any(a == x or (len(a) >= 3 and a in x) or (len(x) >= 2 and x == a) for x in
               (" ".join(label.lower().replace("ё", "е").split()), " ".join(sid.lower().replace("ё", "е").split()))
               if x)


def _plain_ids(text: str) -> str:
    """Как _link_ids, но без ссылок: «R-06 (Ф-1)» → «Ф-1» — чтобы резать текст по видимой длине."""
    if not _REQ_LABELS:
        return text

    def sub(m: re.Match) -> str:
        rid, paren, inner = m.group(1), m.group(2) or "", m.group(3) or ""
        lab, sid = _REQ_LABELS.get(rid, ("", ""))
        if not lab:
            return m.group(0)
        if lab.startswith("критерий приёмки №") and re.search(r"критери\w*\s+(?:приёмки\s+|приемки\s+)?$",
                                                              m.string[max(0, m.start() - 24):m.start()], re.I):
            lab = lab.rsplit(" ", 1)[-1]
        return lab + ("" if paren and _same_label(inner, *_REQ_LABELS[rid]) else paren)

    text = _LABEL_THEN_ID.sub(lambda m: m.group(1) if _REQ_LABELS.get(m.group(2), ("",))[0]
                              and m.group(1).endswith(_REQ_LABELS[m.group(2)][0]) else m.group(0), text)
    return _IDREF.sub(sub, text)


def _link_ids(text: str) -> str:
    """D-…, R-…, Q-… в тексте — ссылки; требование с названием в документе показывается этим названием
    («R-07» → «Ф-3»), повтор названия в скобках после ID убирается."""
    if not _KNOWN_IDS:
        return text

    def label_first(m: re.Match) -> str:
        lab, sid = _REQ_LABELS.get(m.group(2), ("", ""))
        if lab and m.group(1).endswith(lab):
            return f"{m.group(1)[: -len(lab)]}[{lab}](#{m.group(2).lower()})"
        return m.group(0)

    def sub(m: re.Match) -> str:
        rid, paren, inner = m.group(1), m.group(2) or "", m.group(3) or ""
        if rid not in _KNOWN_IDS:
            return m.group(0)
        lab, sid = _REQ_LABELS.get(rid, ("", ""))
        if lab:
            keep = "" if paren and _same_label(inner, lab, sid) else paren
            show = lab
            if lab.startswith("критерий приёмки №") and re.search(r"критери\w*\s+(?:приёмки\s+|приемки\s+)?$",
                                                                  m.string[max(0, m.start() - 24):m.start()], re.I):
                show = lab.rsplit(" ", 1)[-1]  # «критерия R-14» → «критерия №2»
            return f"[{show}](#{rid.lower()}){keep}"
        return f"[{rid}](#{rid.lower()}){paren}"

    text = _LABEL_THEN_ID.sub(label_first, text) if _REQ_LABELS else text
    return _IDREF.sub(sub, text)


_PATH = re.compile(r"(?<![\w`/.])(/[A-Za-z](?:[\w/{}.-]*[\w/}])?(?:\?[\w=&.%{}-]*[\w=}.])?)")
_IDENT = re.compile(r"(?<![\w`$./=?&-])("
                    r"[a-z][a-z0-9]*(?:[A-Z][a-z0-9]*)+"          # camelCase
                    r"|[A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)+"    # snake_case
                    r"|[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+"          # a.b.c
                    r")(?![\w`(])")


def _code_spans(text: str) -> str:
    """Пути API и идентификаторы — как код; уже оформленный код не трогается."""
    parts = re.split(r"(`[^`]*`)", text)
    for i in range(0, len(parts), 2):
        p = _CALL.sub(r"`\1`", parts[i])
        sub = re.split(r"(`[^`]*`)", p)
        for j in range(0, len(sub), 2):
            sub[j] = _IDENT.sub(r"`\1`", _PATH.sub(r"`\1`", sub[j]))
        parts[i] = "".join(sub)
    return "".join(parts)


def prose(text) -> str:
    """Текст модели: «L038» и «L38–L40» из нумерованного документа → «строка 38», «строки 38–40»;
    выражения floor(x/100), пути /a/b?x=1 и идентификаторы monthSpent, limit_kzt, response.result — как код;
    упоминания D-…, R-…, Q-… — ссылки."""
    return _link_ids(_code_spans(_LREF.sub(_lref, esc(text))))


_SEV_WORD = re.compile(r"\b(critical|major|minor)\b")
_STAGE_PREFIX = re.compile(r"^\s*([a-z_:]+):\s+")


_STAGE_WORD = re.compile(r"`?\b(?:lens[_:])?(segment|analyst|qa|architect|risk|consistency|judge|clarify|recheck|"
                         r"revise)\b`?(?!\.)")
_EXC = re.compile(r"\b[A-Z][A-Za-z]*(?:Error|Exceeded|Exception|Timeout)\b:\s*(?:[a-z_]+:\s*)*")


_LENS_CASE = {"линза": "роль", "линзы": "роли", "линзе": "роли", "линзу": "роль", "линзой": "ролью", "линз": "ролей",
              "линзам": "ролям", "линзами": "ролями", "линзах": "ролях"}
_LENS = re.compile(r"\b([Лл])(инз(?:а|ы|е|у|ой|ам|ами|ах)?)\b")


def dejargon(text: str) -> str:
    """Служебное слово конвейера «линза» → «роль» (аналитик, тестировщик, архитектор, риски)."""
    def sub(m: re.Match) -> str:
        w = _LENS_CASE.get("л" + m.group(2), "роль")
        return w.capitalize() if m.group(1) == "Л" else w
    return _LENS.sub(sub, text)


def warn_text(text) -> str:
    """Предупреждение этапа по-русски: «clarify: …» → «Вопросы: …», «lens_risk» → «Риски», critical → критичный;
    служебные префиксы исключений («BudgetExceeded: judge: budget:») убираются."""
    s = dejargon(" ".join(str(text or "").split()))
    m = _STAGE_PREFIX.match(s)
    if m and stage_key(m.group(1)) in STAGES:
        s = f"{STAGES[stage_key(m.group(1))][0]}: " + s[m.end():]
    s = _EXC.sub("", s)
    s = _STAGE_WORD.sub(lambda m: f"«{STAGES[m.group(1)][0]}»", s)
    s = _SEV_WORD.sub(lambda m: SEV_NAME[m.group(1)], s)
    return prose(s)


def _cap(s: str) -> str:
    """Поле карточки начинается с заглавной: «строка 26 не содержит…» → «Строка 26 не содержит…»."""
    return s[0].upper() + s[1:] if s and "а" <= s[0] <= "я" else s  # латиница — возможно имя поля, не трогаем


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
        bits.insert(len(bits) - 1 if ln else len(bits), f"с. {item['page']}")
    return ", ".join(bits) or "место не указано"


def doc_id(req: dict | None) -> str:
    """Собственный ID требования в документе («Ф-3», «НФТ-2»), если он есть; иначе пустая строка."""
    sid = str((req or {}).get("source_id") or "").strip()
    return sid if sid and _DOC_ID.fullmatch(sid) else ""


_ACC_ROW = re.compile(r"^крите\w*\s+при[её]м\w*\D*?(\d+)$", re.I)
_ITEM = re.compile(r"^[^,]{3,40},\s*(?:п\.|пункт|шаг)\s*\d+(?:\.\d+)*$", re.I)


def doc_label(req: dict | None) -> str:
    """Как назвать требование для читателя без внутреннего R-…: «Ф-3», «критерий приёмки №2»,
    «Логика работы метода, п. 5»; пустая строка — подходящего названия в документе нет."""
    if not req:
        return ""
    if doc_id(req):
        return doc_id(req)
    sid = " ".join(str(req.get("source_id") or "").split())
    m = _ACC_ROW.match(sid)
    if m or (req.get("kind") == "acceptance" and re.search(r"(?:№|строка|п\.)\s*(\d+)$", sid)):
        n = m.group(1) if m else re.search(r"(\d+)$", sid).group(1)
        return f"критерий приёмки №{n}"
    if _ITEM.match(sid):
        return sid
    return ""


def _page_line(page, a, b=None) -> str:
    return (f"с. {page}, " if page else "") + lines_word(a, b)


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


RULE_FAMILY = {"api": "контракт API", "conflicts": "противоречия", "injection": "вставки в текст",
               "language": "размытые слова", "placeholder": "заглушки и шаблон", "placeholders": "заглушки и шаблон",
               "promises": "обещанные операции", "units": "единицы измерения", "terms": "термины"}


def source_name(src: str) -> str:
    s = str(src or "")
    if s.startswith("rules:"):
        fam = s.split(":", 1)[1].split(".", 1)[0]
        return f"правило «{RULE_FAMILY[fam]}»" if fam in RULE_FAMILY else "правило без модели"
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
        self.edits = _applied_edits(report)
        self.verdict = report.get("verdict", {}) or {}
        self.offline = self.run.get("provider") == "offline" or (
            not self.run.get("models_used") and self.run.get("provider") not in ("mock",))

    def req_label(self, rid: str, link: bool = True) -> str:
        q = self.req_by_id.get(rid, {})
        sid = str(q.get("source_id") or "").strip()
        label = rid
        if sid and _DOC_ID.fullmatch(sid):
            label = f"{rid} / {sid}"
        elif doc_label(q).startswith("критерий приёмки №"):
            label = f"{rid} / приёмка {doc_label(q).rsplit(' ', 1)[-1]}"
        if not (link and q):
            return label
        tip = shorten(_LREF.sub(_lref, " ".join(str(q.get("summary") or "").split())), 120).replace('"', "'").replace("\\", "/")
        tip = re.sub(r"[\[\]()<>`*|]", "", tip)
        return f'[{label}](#{anchor(rid)} "{tip}")' if tip else f"[{label}](#{anchor(rid)})"

    def req_named(self, rid: str) -> str:
        """Ссылка на требование с кратким названием: «R-07 / Ф-3 (Push при переходе порога…)»."""
        q = self.req_by_id.get(rid, {})
        summ = shorten(q.get("summary") or "", 48)
        return self.req_label(rid) + (f" ({cell(summ)})" if summ else "")

    def req_at(self, line, prefer=()) -> dict | None:
        """Требование, в строки которого попадает line (сначала — из prefer, затем самое узкое)."""
        if not isinstance(line, int):
            return None
        hits = [q for q in self.reqs if isinstance(q.get("line_start"), int)
                and q["line_start"] <= line <= (q.get("line_end") if isinstance(q.get("line_end"), int)
                                                else q["line_start"])]
        if not hits:
            return None
        hits.sort(key=lambda q: (q.get("id") not in prefer, not doc_label(q),
                                 (q.get("line_end") or q["line_start"]) - q["line_start"]))
        return hits[0]

    def ev_label(self, ev: dict, prefer=()) -> str:
        """Чем назвать место цитаты для читателя: ID требования в документе («Ф-3»), иначе раздел."""
        q = self.req_at(ev.get("line_start"), prefer)
        return doc_label(q) or short_section(ev.get("section") or (q or {}).get("section") or "")

    def ev_place(self, ev: dict, prefer=()) -> str:
        """«Ф-3, строка 39» · «Часть B › Логика работы метода, с. 4, строка 121»."""
        label = self.ev_label(ev, prefer)
        pl = _page_line(ev.get("page"), ev.get("line_start"), ev.get("line_end"))
        return ", ".join(x for x in (label, pl) if x) or "место не указано"

    def where_short(self, f: dict, limit: int = 3) -> str:
        """Все места дефекта одной строкой: «Ф-3 (строка 39), Ф-4 (строка 40)»."""
        prefer = f.get("requirement_ids") or []
        groups: dict[str, list[dict]] = {}
        for ev in f.get("evidence") or []:
            if isinstance(ev.get("line_start"), int):
                groups.setdefault(self.ev_label(ev, prefer) or "документ", []).append(ev)
        parts = []
        for label, evs in list(groups.items())[:limit]:
            lns = sorted({e["line_start"] for e in evs})
            pages = sorted({e.get("page") for e in evs if e.get("page")})
            ln = (f"{plural(len(lns), 'строка', 'строки', 'строки')} {', '.join(map(str, lns[:4]))}"
                  + (" и др." if len(lns) > 4 else ""))
            if pages:
                ln = f"с. {', '.join(map(str, pages))}, " + ln
            parts.append(f"{label} ({ln})")
        if len(groups) > limit:
            parts.append(f"ещё {len(groups) - limit} {plural(len(groups) - limit, 'место', 'места', 'мест')}")
        if parts:
            return ", ".join(parts)
        reqs = [doc_id(self.req_by_id.get(r)) or r for r in prefer]
        return ", ".join(reqs) or "документ в целом"

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


def _q_word(c: _Ctx, form: str) -> str:
    """Как назвать «блокирующий» вопрос: при блокирующих дефектах — «блокирующий», иначе — «первоочередной»
    (иначе отчёт с вердиктом «с условиями» противоречил бы себе)."""
    blocked = bool(_blockers(c))
    return {("many", True): "блокирующих", ("many", False): "первоочередных",
            ("mark", True): "⛔ блокирует", ("mark", False): "❗ первоочередной"}[(form, blocked)]


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
                     + ((f", на {blocking} нужен ответ до начала работы" if _blockers(c)
                         else f", на {blocking} — ответить в первую очередь") if blocking else ""))
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
        quotes = (f"все {total} {plural(total, 'цитата найдена', 'цитаты найдены', 'цитат найдены')} в документе "
                  f"{src} программой — по номеру строки каждую можно проверить")
    elif total:
        quotes = f"в документе {src} программой найдено {ok} из {total} цитат, ненайденные помечены ⚠️"
    else:
        quotes = f"документ {src}, цитат в дефектах нет"
    head = esc(c.r.get("title")) if isinstance(c.r.get("title"), str) and c.r.get("title") else "Ревью требований"
    models = ", ".join(f"`{m}`" for m in run.get("models_used") or [])
    st = when(run.get("started_at"))
    how = " ".join(x for x in ((f"{st:%d.%m.%Y в %H:%M} (UTC+5)" if st else ""),
                               (f"за {duration(run.get('duration_s'))}" if run.get("duration_s") is not None else ""))
                   if x)
    model_txt = f"модель {models}" if models else ("без модели" if c.offline else "")
    how = ", ".join(x for x in (how, model_txt) if x)
    del commit, dirty  # коммит и команда проверки — в паспорте
    out = [f"# {head}: «{esc(title)}»", "",
           f"> Отчёт составлен агентом «{esc(run.get('agent') or 'BCC Review')}» без ручных правок"
           + (f" {how}" if how else "") + f"; {quotes}. Версия агента и проверка отчёта — в [паспорте](#s1)."]
    status = run.get("status")
    if status == "partial":
        bad = [stage_name(k) for k, v in (run.get("stages") or {}).items()
               if v in ("partial", "failed")]
        why = _partial_reason(c)
        out += [">", f"> ⚠️ Прогон завершён частично"
                + (f": не полностью выполнены этапы {', '.join(bad)}" if bad else "")
                + (f". Причина: {why}" if why else "")
                + ". Вердикт «можно начинать» по частичной проверке не выносится; недостающие проверки — в "
                  "приложении Д."]
    elif status == "failed":
        out += [">", "> ⛔ Прогон завершился сбоем: вердикт не вынесен, ниже — то, что успели проверить."]
    if c.offline:
        how = ("как подключить модель — в конце раздела «Кратко»"
               if isinstance(c.r.get("offline"), dict) and c.r["offline"].get("how_to_full")
               else "как подключить модель — в инструкции «README», раздел о ключе")
        out += [">", "> Режим без модели: работали только детерминированные правила. Поиск противоречий, "
                     f"проверка критериев приёмки и вопросы владельцу требуют модели ({how})."]
    skip = getattr(c, "skip_nav", set())
    out += ["", "**Содержание:** [Кратко](#s0) · " + " · ".join(f"[{name}](#{a})" for a, name in NAV if a not in skip)]
    return out + [""]


_REASONS = [
    (re.compile(r"исчерпан бюджет вызовов модели(?: \(\d+\))?"), "{0} — повторите с большим `--max-calls`"),
    (re.compile(r"(?:бюджет|лимит) времени[^;,.)]*|превышен[^;,.)]*времени[^;,.)]*|timeout|таймаут[^;,.)]*", re.I),
     "истёк лимит времени — повторите с большим `--max-seconds`"),
    (re.compile(r"\b429\b|квот\w*|quota|rate limit|лимит запросов", re.I),
     "модель отклонила запросы из-за лимита запросов (квоты) — повторите позже или с другой моделью"),
    (re.compile(r"обрез\w*|truncat\w*|output token maximum", re.I), "ответ модели обрезан по длине"),
]


def _partial_reason(c: _Ctx) -> str:
    """Понятная причина частичного прогона по предупреждениям этапов: бюджет вызовов, время, квота, обрезка."""
    found: list[str] = []
    for w in c.run.get("warnings") or []:
        for rx, text in _REASONS:
            m = rx.search(str(w))
            if m:
                msg = text.format(m.group(0))
                if msg not in found:
                    found.append(msg)
                break
    if not found:
        for w in c.run.get("warnings") or []:
            m = re.search(r"не выполнен:\s*(.+)$", str(w))
            if m:
                found.append(warn_text(shorten(m.group(1), 120)))
                break
    return "; ".join(found[:2])


def _brief(c: _Ctx) -> list[str]:
    v = c.verdict
    out = [h2("s0", "Кратко"), ""]
    out += table(["Разработка", "Тестирование"],
                 [[f"**{READINESS.get(v.get('development'), '—')}**", f"**{READINESS.get(v.get('testing'), '—')}**"]],
                 [":---:", ":---:"])
    out += ["", f"**Почему.** {prose(_why(c))}", "", _counts_line(c), ""]
    off = c.r.get("offline") if c.offline and isinstance(c.r.get("offline"), dict) else {}
    out += _before_after(c)
    blockers = _blockers(c)
    if blockers:
        same = len({f.get("blocks") for f in blockers}) == 1
        what = BLOCKS.get(blockers[0].get("blocks"), "—")
        head = "Блокер" if len(blockers) == 1 else f"Блокеры ({len(blockers)})"
        if same:
            verb = "останавливает" if len(blockers) == 1 else "каждый останавливает"
            out += [f"**{head}** — {verb} {what}; что не так и где:", ""]
        else:
            out += [f"**{head}** — что не так, где и что останавливает:", ""]
        for i, f in enumerate(blockers, 1):
            out.append(f"{i}. {SEV_ICON.get(f.get('severity'), '')} [{f['id']}](#{anchor(f['id'])}) "
                       f"**{prose(f.get('title'))}** — {prose(c.where_short(f, limit=5))}"
                       + ("." if same else f"; останавливает {BLOCKS.get(f.get('blocks'), '—')}."))
        out.append("")
    elif c.run.get("status") != "failed" and "блокирующ" not in str(v.get("summary") or "").lower():
        out += ["Блокирующих дефектов не найдено.", ""]
    first = _first_screen_fix(c, blockers)
    if first:
        shown = {f["id"] for f in blockers}
        out += ["**Исправить первым**" + (" — сначала блокеры" if shown and len(first) > len(shown) else ""), ""]
        for i, f in enumerate(first, 1):
            what = "" if f["id"] in shown else f" {prose(shorten(f.get('title'), 90))}"
            act = _action(f)
            out.append(f"{i}. {c.f_link(f['id'], True)}{what}" + (f" → {prose(act)}" if act else ""))
        out.append("")
    if off.get("how_to_full"):
        out += ["**Как получить полную проверку**", ""]
        out += [f"{i}. {prose(step)}" for i, step in enumerate(off["how_to_full"], 1)] + [""]
    out += _how_obtained(c)
    return out


FIRST_SCREEN_FIX = 5


def _first_screen_fix(c: _Ctx, blockers: list[dict], limit: int = FIRST_SCREEN_FIX) -> list[dict]:
    """«Исправить первым»: сначала блокеры (в порядке судьи), затем остальные из «исправить первым»; на первом
    экране — не больше limit пунктов (полный список — в разделе 6, в том же порядке)."""
    order = _fix_first(c)
    rank = {f["id"]: i for i, f in enumerate(order)}
    bl = sorted(blockers, key=lambda f: (rank.get(f["id"], 99), f.get("priority") or 99, _id_num(f.get("id"))))
    rest = [f for f in order if f["id"] not in {b["id"] for b in bl}]
    return (bl + rest)[:max(limit, len(bl))]


_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[А-ЯЁA-Z«])")


_PRIORITY = re.compile(r"^(?:Первым|Первыми|Сначала|В первую очередь|Начать с|Первое)\b", re.I)


def _why(c: _Ctx, limit: int = 420) -> str:
    """Обоснование вердикта для первого экрана. Есть блокеры — фраза кода (сколько, что блокируют и какого рода:
    противоречия, пропуски, неоднозначности) плюс фраза судьи о порядке исправления; перечень блокеров стоит ниже
    списком. Блокеров нет — текст судьи (не длиннее limit)."""
    text = " ".join(str(c.verdict.get("summary") or "").split())
    judge_down = any("судья недоступен" in str(w) or "реестр собран кодом" in str(w) for w in c.run.get("warnings") or [])
    if c.offline:
        lim = ("Смысл требований без модели не проверялся (противоречия правил, критерии приёмки, полнота основной "
               "функции), поэтому отсутствие других дефектов не означает, что их нет.")
        return (_auto_why(c) + " " + lim) if _blockers(c) else ("Без модели вердикт «можно» не выносится. " + lim)
    if not text or judge_down or text.startswith("Итог ревью:"):
        return _auto_why(c)
    sents = _SENT_SPLIT.split(text)
    if not _blockers(c):
        out = ""
        for s in sents:
            if out and len(out) + len(s) + 1 > limit:
                break
            out = f"{out} {s}".strip()
        return out or shorten(text, limit)
    prio = next((s for s in sents if _PRIORITY.match(s)), "")
    first_id = re.search(r"\bD-\d{2,4}\b", prio)
    if first_id and first_id.group(0) not in {f["id"] for f in _blockers(c)}:
        prio = ""  # судья начинает не с блокера — список «Исправить первым» ниже начинается с блокеров
    why = _auto_why(c)
    return why + (f" {shorten(prio, limit)}" if prio else "")


def _auto_why(c: _Ctx) -> str:
    """Обоснование для первого экрана, если судья его не написал: без перечня (блокеры стоят ниже списком)."""
    if c.run.get("status") == "failed":
        return _auto_reason(c)
    bl = _blockers(c)
    partial = c.run.get("status") == "partial"
    tail = (" Проверка неполная, поэтому возможны и другие дефекты." if partial else "")
    if bl:
        what = {b for f in bl for b in ({"both": ("development", "testing")}.get(f.get("blocks")) or (f.get("blocks"),))}
        target = BLOCKS["both"] if what >= {"development", "testing"} else BLOCKS.get(next(iter(what)), "работу")
        n = len(bl)
        noun = (plural(n, "дефект", "дефекта", "дефектов") if c.offline else
                plural(n, "критичный дефект", "критичных дефекта", "критичных дефектов"))
        verb = "блокирует" if plural(n, "1", "2", "5") == "1" else "блокируют"
        kinds = {}
        for f in bl:
            kinds[_category(f)] = kinds.get(_category(f), 0) + 1
        words = {"contradictory": ("противоречие между местами документа", "противоречия между местами документа",
                                   "противоречий между местами документа"),
                 "incomplete": ("пропуск обязательного описания", "пропуска обязательного описания",
                                "пропусков обязательного описания"),
                 "unverifiable": ("неоднозначное ключевое правило", "неоднозначных ключевых правила",
                                  "неоднозначных ключевых правил"),
                 "other": ("другой дефект", "других дефекта", "других дефектов")}
        order = [k for k in ("contradictory", "incomplete", "unverifiable", "other") if kinds.get(k)]
        what_kind = [f"{kinds[k]} {plural(kinds[k], *words[k])}" for k in order]
        kind_txt = (": " + (", ".join(what_kind[:-1]) + " и " + what_kind[-1] if len(what_kind) > 1 else what_kind[0])
                    if what_kind and not (len(order) == 1 and order[0] == "other") else "")
        return f"{n} {noun} {verb} {target}{kind_txt} — список ниже." + tail
    majors = [f for f in c.findings if f.get("severity") == "major"]
    if len(majors) >= 3:
        return (f"Критичных дефектов нет; существенных — {len(majors)}: начинать можно, исправляя их параллельно "
                f"с работой." + tail)
    return "Критичных дефектов нет, существенных меньше трёх." + tail


def _blockers(c: _Ctx) -> list[dict]:
    out = [f for f in c.findings if f.get("blocks") in BLOCKING and (
        f.get("severity") == "critical" or (c.offline and f.get("rule_conflict")))]
    return sorted(out, key=lambda f: (f.get("priority") or 99, _id_num(f.get("id"))))


def _action(f: dict, limit: int = 190) -> str:
    """Что сделать — первое предложение рекомендации, со строчной буквы (после «→»); длинное режется по границе
    части предложения («;», «:»), а не посреди слова."""
    sent = first_sentence(_plain_ids(" ".join(str(f.get("recommendation") or "").split())), 10 ** 4).rstrip(".")
    if len(sent) > limit:
        cut = max(sent.rfind("; ", 0, limit), sent.rfind(": ", 0, limit), sent.rfind(" — ", 0, limit))
        sent = sent[:cut] if cut > limit * 0.5 else shorten(sent, limit)
    rec = sent.rstrip(" ,;:—")
    if len(rec) > 1 and rec[0].isupper() and rec[1].islower():
        rec = rec[0].lower() + rec[1:]
    return rec


def _candidate_counts(c: _Ctx) -> dict:
    """Одни и те же числа «кандидатов» для «Как получено» и приложения Д.

    Предложено = вошли в дефекты + отклонены (судьёй, без цитаты, не рассмотрены). Кандидаты, которые роль сама
    отбросила (`lens_dropped`), в «предложено» не входят и считаются отдельно."""
    rej = c.r.get("rejected") or []
    accepted = sum(len(f.get("candidate_ids") or []) for f in c.r.get("findings") or [])
    code = lambda r: str(r.get("reason_code") or "")  # noqa: E731
    out = {"accepted": accepted,
           "self_dropped": sum(1 for r in rej if code(r) == "lens_dropped"),
           "no_quote": sum(1 for r in rej if code(r) == "no_quote"),
           "not_reviewed": sum(1 for r in rej if code(r) == "not_reviewed")}
    out["judge"] = len(rej) - out["self_dropped"] - out["no_quote"] - out["not_reviewed"]
    out["total"] = accepted + len(rej) - out["self_dropped"]
    return out


def _how_obtained(c: _Ctx) -> list[str]:
    """Строка доверия: откуда взялись дефекты и почему им можно верить."""
    if c.run.get("status") == "failed":
        return []
    roles = [STAGES[stage_key(k)][0].lower() for k in (c.run.get("stages") or {})
             if stage_key(k) in PROPOSING and stage_key(k) != "rules" and c.run["stages"][k] in ("ok", "partial")]
    n = _candidate_counts(c)
    total = n["total"]
    ok, qt = c.summary.get("quotes_verified", 0), c.summary.get("quotes_total", c.summary.get("quotes_verified", 0))
    parts = []
    stages = c.run.get("stages") or {}
    has_rules = any(stage_key(k) == "rules" and v in ("ok", "partial") for k, v in stages.items())
    who = " и ".join(x for x in ((f"проверяющие роли ({', '.join(roles)})" if roles else ""),
                                 ("правила без модели" if has_rules else "")) if x)
    if who:
        who = who[0].upper() + who[1:]
        parts.append(f"{who} нашли {num(total)} {plural(total, 'возможный дефект', 'возможных дефекта', 'возможных дефектов')}"
                     if total else f"{who} проверили документ")
    judge_down = any("судья недоступен" in str(w) or "реестр собран кодом" in str(w)
                     for w in c.run.get("warnings") or [])
    judged = (c.run.get("stages") or {}).get("judge") in ("ok", "partial") and not c.offline and not judge_down
    nf = len(c.findings) + len(c.resolved)
    if total and judged:
        drop = n["judge"] + n["not_reviewed"]
        parts.append(f"судья объединил повторы в {nf} {plural(nf, 'дефект', 'дефекта', 'дефектов')}"
                     + (f" и отклонил {drop} {plural(drop, 'как ложный', 'как ложные', 'как ложные')}" if drop else "")
                     + (f", ещё {n['no_quote']} без найденной цитаты отброшены программой" if n["no_quote"] else "")
                     + (f"; после ответов владельца открыто {len(c.findings)}" if c.resolved else ""))
    elif c.findings:
        parts.append(f"в отчёт вошли {nf} {plural(nf, 'дефект', 'дефекта', 'дефектов')} без отбора судьёй"
                     + (" (судья не ответил, повторы объединены программой)" if judge_down else ""))
    if qt:
        parts.append(f"каждая цитата найдена в документе программой ({ok} из {qt}), номер строки посчитан ею же")
    if not parts:
        return []
    return [f"*Как получено:* {'; '.join(parts)}. Вердикт считает программа по правилу из приложения Е.", ""]


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
    gone = [x for x in cl.get("changes") or [] if isinstance(x, dict) and x.get("status") == "resolved"
            and x.get("severity_before") == "critical"]
    if gone:
        out += ["", f"**Сняты ответами блокеры ({len(gone)}):**", ""]
        for x in gone[:7]:
            reason = str(x.get("reason") or "")
            qids = [q for q in x.get("question_ids") or [] if q not in reason]
            qs = ", ".join(qids) + ": " if qids else ("" if re.search(r"\bQ-\d", reason) else "общее решение: ")
            out.append(f"- 🔴 {c.f_link(x.get('finding_id', ''))} {prose(x.get('title') or '')} — "
                       f"{prose(qs + shorten(reason, 170))}")
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


# ------------------------------------------------------------------ общие подписи MD и HTML (№14 может импортировать)
TERM = {"finding": "дефект", "findings": "дефекты", "requirement": "требование", "question": "вопрос владельцу"}
READINESS_PLAIN = {"no": "нельзя начинать", "conditional": "можно с условиями", "yes": "можно начинать",
                   "undetermined": "не определено", "none": "вердикт не вынесен"}


def run_stamp(run: dict) -> str:
    """Время прогона одинаково в MD и HTML: «27.11.2026 02:50–02:54 (UTC+5)»."""
    st, fn = when((run or {}).get("started_at")), when((run or {}).get("finished_at"))
    if st and fn and f"{st:%d.%m.%Y %H:%M}" == f"{fn:%d.%m.%Y %H:%M}":
        return f"{st:%d.%m.%Y %H:%M} (UTC+5)"
    if st and fn:
        return (f"{st:%d.%m.%Y %H:%M}–{fn:%H:%M} (UTC+5)" if st.date() == fn.date()
                else f"{st:%d.%m.%Y %H:%M} – {fn:%d.%m.%Y %H:%M} (UTC+5)")
    if st or fn:
        return f"{(st or fn):%d.%m.%Y %H:%M} (UTC+5)"
    return "—"


def _passport(c: _Ctx) -> list[str]:
    run, doc = c.run, c.doc
    stamp = run_stamp(run)
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
    ] + ([["Нумерация строк", "строка — фрагмент текста в нумерации агента (сквозная по документу); место на "
                              "странице находится по номеру страницы и цитате"]]
         if doc.get("format") in ("pdf", "docx") else []) + [
        ["Дата и время", stamp],
        ["Модель", model.replace("|", "\\|")],
        ["Провайдер", PROVIDERS.get(run.get("provider")) or f"`{run.get('provider') or '—'}`"],
        ["Агент", f"«{cell(run.get('agent') or 'BCC Review')}» {cell(run.get('version') or '')}, коммит {commit}"],
        ["Обращений к модели", f"{num(calls.get('total', 0))} (из кэша {num(calls.get('cached', 0))}, "
                               f"с ошибкой {num(calls.get('failed', 0))}, делений пакета {num(calls.get('split', 0))})"],
        ["Токены", f"вход {num(tok.get('input', 0))}, выход {num(tok.get('output', 0))}"
                   + (f" · ≈ {cost:.2f} $".replace(".", ",") if isinstance(cost, (int, float)) and cost else "")],
        ["Длительность", duration(run.get("duration_s"))],
        ["Статус прогона", STATUS.get(run.get("status"), run.get("status") or "—")],
        ["Этапы", cell(stage_txt)],
        ["Файлы отчёта", "рядом с этим файлом: `.json` — все данные и полные цитаты (по нему работает `verify`), "
                         "`.html` — интерактивная версия"],
        ["Проверка отчёта", "`python -m bcc_review verify отчёт.json документ` — сверяет каждую цитату с документом, "
                            "числа и вердикт"],
    ]
    cl = c.r.get("clarification") or {}
    if cl:
        rows.append(["Ответы владельца", f"учтены: ответов {len(cl.get('answers') or [])}, общих решений "
                                         f"{len(cl.get('decisions') or [])}, без ответа {len(cl.get('unanswered') or [])}"])
    warns = (run.get("warnings") or []) + (doc.get("warnings") or [])
    if warns:
        rows.append(["Предупреждения", "; ".join(warn_text(w) for w in warns[:5]).replace("|", "\\|")
                     + (f" и ещё {len(warns) - 5}" if len(warns) > 5 else "")])
    return [h2("s1", "1. Паспорт прогона"), ""] + table(["Поле", "Значение"], rows) + [""]


def _segmentation(c: _Ctx) -> list[str]:
    reqs = c.reqs
    out = [h2("s2", "2. Нарезка: как агент нарезал требования"), "",
           f"Выделено {len(reqs)} {plural(len(reqs), 'требование', 'требования', 'требований')}. Идентификаторы "
           f"R-… присвоены агентом в порядке документа; «ID в документе» — номер или пункт документа, если он есть; "
           f"для каждого требования сохранена цитата (полная — в `report.json`).", ""]
    if not reqs:
        why = ("нарезка выполняется моделью, в режиме без модели её нет; замечания правил привязаны к строкам "
               "документа" if c.offline else "этап нарезки не дал результата (приложение Д)")
        return out[:2] + [f"Требования не выделены: {why}.", ""]
    rows = []
    qlen = 70 if c.level < 3 else 45
    for q in reqs:
        rows.append([f"<a id=\"{anchor(q.get('id'))}\"></a>{q.get('id')}", cell(q.get("source_id") or "—"),
                     REQ_KIND.get(q.get("kind"), cell(q.get("kind"))), cell(q.get("summary")),
                     quote_md(q.get("quote"), qlen, in_table=True) if q.get("quote") else "—", cell(place(q))])
    out += table(["ID в отчёте", "ID в документе", "Вид", "Краткая формулировка", "Цитата", "Где"], rows)
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
            + ((f" Без модели по остальным критериям ({', '.join(unused)}) документ не проверялся." if c.offline else
                f" Критерии без нарушений во всём документе: {', '.join(unused)}.") if unused else ""), ""]
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
    if rows and c.level >= 7:
        # очень большой документ: вместо матрицы — требования, сгруппированные по самой серьёзной находке
        for sev in ("critical", "major", "minor"):
            grp = [r for r in rows if r[1] == SEV_ICON[sev]]
            if grp:
                out.append(f"- {SEV_ICON[sev]} {SEV_PLURAL[sev][2].capitalize()} нарушения ({len(grp)}): "
                           + "; ".join(f"{r[0]} — {r[-1]}" for r in grp))
        out += ["", "Критерий каждого дефекта — в его карточке или строке таблицы ниже.", ""]
    elif rows:
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
    as_rows = [f for f in cards if c.level >= 6 and f.get("severity") != "critical"]
    for f in cards:
        if f not in as_rows:
            out += _card(c, f)
    if as_rows:
        out += [f"Существенные ({len(as_rows)}) — по строке на дефект, чтобы отчёт уместился в 900 строк; сценарий, "
                f"последствия и «было → стало» каждого — в `report.json`.", ""]
        out += _finding_rows(c, as_rows) + [""]
    minors = [f for f in c.findings if f.get("severity") not in ("critical", "major")]
    out += ["### 3.3. Незначительные дефекты", ""]
    if minors:
        out += _finding_rows(c, minors) + [""]
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


def _finding_rows(c: _Ctx, fs: list[dict]) -> list[str]:
    """Дефекты таблицей, по строке: суть, место с цитатой, критерий, как исправить."""
    rows = []
    for f in fs:
        ev = (f.get("evidence") or [{}])[0]
        rows.append([f"<a id=\"{anchor(f['id'])}\"></a>{SEV_ICON.get(f.get('severity'), '')} {f['id']}",
                     cell(f.get("title")),
                     cell(c.ev_place(ev, f.get("requirement_ids") or [])) + ": "
                     + quote_md(ev.get("quote"), 90, in_table=True) if ev else "документ в целом",
                     cell(_criterion_name(f.get("criterion"))),
                     pcell(f.get("recommendation"))])
    return table(["Дефект", "Суть", "Где", "Критерий", "Как исправить"], rows)


def _applied_edits(report: dict) -> list[tuple[str, dict]]:
    """Правки режима --revise (№11): [(D-…, {"line", "before", "after", "insert"})], только применённые."""
    out = []
    for rw in report.get("rewrites") or []:
        if not isinstance(rw, dict):
            continue
        for e in rw.get("edits") or []:
            if not isinstance(e, dict) or not e.get("applied") or not isinstance(e.get("line"), int):
                continue
            insert = e.get("action") == "insert"
            out.append((str(rw.get("finding_id") or ""), {
                "line": e["line"], "insert": insert, "before": "" if insert else str(e.get("was") or e.get("old") or ""),
                "after": str(e.get("became") if e.get("became") is not None else e.get("new") or "")}))
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


def _card_compact(c: _Ctx, f: dict) -> list[str]:
    """Карточка существенного дефекта для очень длинных отчётов (уровень сжатия 5): 5 строк вместо 10–12."""
    prefer = f.get("requirement_ids") or []
    where = "; ".join(f"{esc(c.ev_place(ev, prefer))}: {quote_md(ev.get('quote'), 110)}"
                      for ev in (f.get("evidence") or [])[:3]) or "документ в целом"
    story = " ".join(x for x in (str(f.get("problem") or "").strip(), str(f.get("scenario") or "").strip(),
                                 str(f.get("impact") or "").strip()) if x)
    fix = f"**Как исправить.** {prose(f.get('recommendation'))}" if f.get("recommendation") else ""
    if f.get("rewrite"):
        fix += f" **Стало:** «{prose(shorten(f.get('rewrite'), 220))}»"
    qids = c.q_by_finding.get(f.get("id"), [])
    if qids:
        fix += " **Вопрос:** " + ", ".join(f"[{q}](#{anchor(q)})" for q in qids)
    lines = [f"**Где:** {where}", f"**Суть.** {prose(story)}", fix.strip(), _card_footer(c, f)]
    lines = [ln for ln in lines if ln]
    return [f"#### <a id=\"{anchor(f['id'])}\"></a>{SEV_ICON.get(f.get('severity'), '')} {f['id']}. "
            f"{prose(f.get('title'))}", ""] + [ln + "  " if i < len(lines) - 1 else ln
                                               for i, ln in enumerate(lines)] + [""]


CARD_QUOTE = 130  # цитата в карточке: короткая, полная — в report.json


def _card_footer(c: _Ctx, f: dict, badge: str = "") -> str:
    """Справочная строка карточки: серьёзность и что блокирует, критерий со стандартом, требования, кто нашёл."""
    sev = f.get("severity")
    bits = [SEV_NAME.get(sev, "—").capitalize()
            + (f", блокирует {BLOCKS[f['blocks']]}" if f.get("blocks") in BLOCKING else "")]
    bits.append(f"критерий «{esc(_criterion_name(f.get('criterion')))}» ({esc(_criterion_ref(f))})")
    rids = [r for r in f.get("requirement_ids") or [] if r]
    if rids:
        bits.append(f"{plural(len(rids), 'требование', 'требования', 'требования')} "
                    + ", ".join(c.req_label(r) for r in rids[:6]) + (" и др." if len(rids) > 6 else ""))
    srcs = [source_name(s) for s in f.get("sources") or []]
    if srcs:
        bits.append("нашли: " + ", ".join(dict.fromkeys(srcs)))
    return "*" + " · ".join(bits) + badge + "*"


def _card(c: _Ctx, f: dict) -> list[str]:
    """Карточка по рубрике понятности: заголовок → где (место и цитата) → проблема → сценарий → последствия →
    как исправить (было → стало, вопрос владельцу) → справочная строка."""
    sev = f.get("severity")
    if c.level >= 5 and sev != "critical":
        return _card_compact(c, f)
    badge = {"changed": " · уточнён после ответов", "new": " · новый после ответов"}.get(
        f.get("status_after_answers") or f.get("status"), "")
    out = [f"#### <a id=\"{anchor(f['id'])}\"></a>{SEV_ICON.get(sev, '')} {f['id']}. {prose(f.get('title'))}", ""]
    prefer = f.get("requirement_ids") or []
    evs = []
    for ev in f.get("evidence") or []:
        warn = " ⚠️ цитата не найдена в документе" if ev.get("verified") == "missing" else ""
        evs.append(f"{esc(c.ev_place(ev, prefer))}: {quote_md(ev.get('quote'), CARD_QUOTE)}{warn}")
    compact = c.level >= 3 and sev != "critical"
    if compact or len(evs) == 1:
        out += ["**Где:** " + "; ".join(evs) if evs else "**Где:** документ в целом", ""]
    else:
        out += [f"- {e}" for e in evs] + [""]
    if compact and c.level >= 4 and f.get("scenario") and f.get("impact"):
        fields = [("Проблема", f.get("problem")),
                  ("Сценарий и последствия", f"{str(f['scenario']).rstrip('. ')}. {f['impact']}"),
                  ("Как исправить", f.get("recommendation"))]
    else:
        fields = [("Проблема", f.get("problem")), ("Сценарий", f.get("scenario")), ("Последствия", f.get("impact")),
                  ("Как исправить", f.get("recommendation"))]
    body = [f"**{name}.** {_cap(prose(val))}" for name, val in fields if val]
    edits = [e for fid, e in c.edits if fid == f.get("id")]
    src = _rewrite_from(f)
    if edits:
        for e in edits[:2]:
            if e["insert"]:
                body.append(f"**Добавить после строки {e['line']}.** «{prose(e['after'])}»")
            else:
                body.append(f"**Было → стало.** Строка {e['line']}: {quote_md(e['before'])} → "
                            + (f"«{prose(e['after'])}»" if e["after"] else "удалить"))
    elif src is not None:
        label = ("Было → стало (места «<уточнить>» заполнит ответ владельца)"
                 if re.search(r"<\s*уточнить", str(f.get("rewrite") or ""), re.I) else "Было → стало")
        body.append(f"**{label}.** {_cap(_page_line(src.get('page'), src.get('line_start'), src.get('line_end')))}: "
                    f"{quote_md(src.get('quote'), CARD_QUOTE)} → «{prose(f.get('rewrite'))}»")
    qids = c.q_by_finding.get(f["id"], [])
    if f.get("question"):
        link = (" → " + ", ".join(f"[{q}](#{anchor(q)})" for q in qids) + " (варианты ответа)") if qids else ""
        body.append(f"**Вопрос владельцу.** {prose(f['question'])}{link}")
    elif qids:
        body.append("**Вопрос владельцу:** " + ", ".join(f"[{q}](#{anchor(q)})" for q in qids) + " (варианты ответа)")
    body.append(_card_footer(c, f, badge))
    out += [line + "  " if i < len(body) - 1 else line for i, line in enumerate(body)]
    return out + [""]


def _set_check(c: _Ctx) -> list[str]:
    out = [h2("s4", "4. Проверка всего набора требований"), "", "### 4.1. Критерии набора", ""]
    rows = []
    for k in SET_CRITERIA:
        fs = [f for f in c.findings if _set_bucket(f) == k]
        w = _worst(fs)
        verdict = (f"{SEV_ICON[w]} нарушен" if w else ("❔ без модели не проверялся" if c.offline
                                                        else "✅ нарушений не найдено"))
        rows.append([CRITERIA[k][0], CRITERIA[k][1], verdict,
                     c.f_links(sorted({f["id"] for f in fs}, key=_id_num)) if fs else "—"])
    out += table(["Критерий", "Стандарт", "Итог", "Дефекты"], rows) + [""]

    if c.offline and not (c.r.get("pair_checks") or c.r.get("acceptance_checks") or c.r.get("trace")
                          or c.r.get("glossary")):
        return out + ["### 4.2–4.5. Противоречия, критерии приёмки, покрытие, глоссарий", "",
                      "Без модели не выполнялись: попарная сверка требований по сценариям, исполнение критериев "
                      "приёмки, покрытие требований приёмкой и глоссарий разночтений требуют модели. Явные "
                      "противоречия, которые нашли правила, — среди дефектов раздела 3.", ""]
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
                         c.f_links(p.get("finding_ids") or _infer_pair(c, p))])
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
                         cell(a.get("expected_by_rules")), cell(a.get("stated")), mark,
                         c.f_links(a.get("finding_ids") or _infer_acceptance(c, a))])
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
                 cell(g.get("problem")), c.f_links(g.get("finding_ids") or _infer_glossary(c, g))] for g in glossary]
        out += table(["Понятие", "Как названо в документе", "Проблема", "Дефект"], rows) + [""]
    else:
        out += ["Разночтений терминов не найдено.", ""]
    return out


def _ev_lines(f: dict) -> set[int]:
    out = set()
    for e in f.get("evidence") or []:
        a = e.get("line_start")
        if isinstance(a, int):
            b = e.get("line_end") if isinstance(e.get("line_end"), int) else a
            out.update(range(a, b + 1))
    return out


def _infer_pair(c: _Ctx, p: dict) -> list[str]:
    """Дефект для пары, если судья его не указал: оба требования или обе строки в одном дефекте."""
    if p.get("verdict") == "compatible":
        return []
    a, b = p.get("a"), p.get("b")
    la, lb = p.get("line_a"), p.get("line_b")
    hits = []
    for f in c.findings:
        reqs = set(f.get("requirement_ids") or [])
        lines = _ev_lines(f)
        if (a in reqs and b in reqs) or (isinstance(la, int) and isinstance(lb, int) and la in lines and lb in lines):
            hits.append(f)
    hits.sort(key=lambda f: (f.get("kind") not in CONFLICT_KINDS, SEV_ORDER.get(f.get("severity"), 3)))
    return [f["id"] for f in hits[:2]]


def _infer_acceptance(c: _Ctx, a: dict) -> list[str]:
    if a.get("verdict") == "match":
        return []
    row = a.get("row_requirement_id")
    rules = set(a.get("rule_requirement_ids") or [])
    hits = [f for f in c.findings if row in (f.get("requirement_ids") or [])
            and (rules & set(f.get("requirement_ids") or []) or f.get("kind") in CONFLICT_KINDS)]
    hits.sort(key=lambda f: (f.get("kind") not in CONFLICT_KINDS, SEV_ORDER.get(f.get("severity"), 3)))
    return [f["id"] for f in hits[:2]]


def _infer_glossary(c: _Ctx, g: dict) -> list[str]:
    lines = {t.get("line") for t in g.get("terms") or [] if isinstance(t.get("line"), int)}
    hits = [f for f in c.findings if (f.get("kind") == "terminology" or f.get("criterion") == "set_comprehensible")
            and lines & _ev_lines(f)]
    return [f["id"] for f in hits[:2]]


_COVER_CRIT = {"verifiable", "set_validatable"}


def _infer_trace(c: _Ctx, rid: str) -> list[str]:
    """Дефект строки покрытия, если этап набора его не указал: про это требование и про приёмку/проверяемость."""
    hits = [f for f in c.findings if rid in (f.get("requirement_ids") or [])
            and (f.get("criterion") in _COVER_CRIT or f.get("kind") == "unverifiable"
                 or "приёмк" in str(f.get("title") or "").lower() or "приемк" in str(f.get("title") or "").lower())]
    # дефект «на весь документ» (у него десятки требований) — последним: он не про эту строку
    hits = [f for f in hits if len(f.get("requirement_ids") or []) <= 8]
    hits.sort(key=lambda f: (len(f.get("requirement_ids") or []) > 4, SEV_ORDER.get(f.get("severity"), 3),
                             _id_num(f.get("id"))))
    return [f["id"] for f in hits[:2]]


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
    # одинаковая заметка у многих непокрытых требований («трассировка не построена») — одной строкой
    note_count: dict[str, int] = {}
    for rid in rows_ids:
        t = trace.get(rid, {})
        if not (set(t.get("verified_by") or []) | checked.get(rid, set())) and t.get("note"):
            note_count[t["note"]] = note_count.get(t["note"], 0) + 1
    grouped: dict[str, list[str]] = {}
    for rid in rows_ids:
        t = trace.get(rid, {})
        by = set(t.get("verified_by") or []) | checked.get(rid, set())
        if by:
            covered += 1
        elif not t.get("note"):
            bare.append(rid)
            continue
        elif note_count.get(t["note"], 0) >= 3:
            grouped.setdefault(t["note"], []).append(rid)
            continue
        cells = []
        for aid in acc_ids:
            if (aid, rid) in conflict:
                cells.append("⛔")
            elif aid in by:
                cells.append("✓")
            else:
                cells.append("·")
        rows.append([c.req_label(rid)] + cells + [cell(t.get("note") or ("нет критерия приёмки" if not by else "")),
                                                  c.f_links(t.get("finding_ids") or _infer_trace(c, rid))])
    out += [f"Покрыто приёмкой {covered} из {len(rows_ids)} требований, которые должны проверяться. "
            f"✓ — критерий проверяет требование, ⛔ — критерий противоречит требованию, «·» — не проверяет.", ""]
    if rows:
        def head(a: str) -> str:
            lab = doc_label(c.req_by_id.get(a))
            return (f"[{lab.replace('критерий приёмки ', 'Приёмка ')}](#{anchor(a)})"
                    if lab.startswith("критерий приёмки №") else c.req_label(a))
        out += table(["Требование"] + [head(a) for a in acc_ids] + ["Чего не хватает", "Дефект"], rows,
                     [":---"] + [":---:"] * len(acc_ids) + [":---", ":---"])
    for note, ids in grouped.items():
        out += ["", f"Без критерия приёмки — {cell(note)} ({len(ids)}): " + ", ".join(c.req_label(r) for r in ids) + "."]
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
            ["Нарушений (дефектов)", f"{total}: " + " · ".join(f"{SEV_ICON[k]} {fs.get(k, 0)}" for k in SEV_ICON)],
            ["Цитат сверено программой", f"{ok} из {qt}"],
            ["Вопросов владельцу", f"{len(qs)}, из них {_q_word(c, 'many')} {sum(1 for q in qs if q.get('blocking'))}"]]
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
    out += table(["Можно ли по этому документу начинать", "Ответ"],
                 [["разработку", f"**{READINESS.get(v.get('development'), '—')}**"],
                  ["тестирование", f"**{READINESS.get(v.get('testing'), '—')}**"]]) + [""]
    reason = v.get("summary") or _auto_reason(c)
    out += [f"**Обоснование.** {prose(reason)}", ""]
    first = _first_screen_fix(c, _blockers(c), limit=7)
    if first:
        out += ["**Что исправить в первую очередь**", ""]
        for i, f in enumerate(first, 1):
            rec = shorten(f.get("recommendation"), 260)
            if len(rec) > 1 and rec[0].isupper() and rec[1].islower():
                rec = rec[0].lower() + rec[1:]  # после двоеточия — со строчной
            out.append(f"{i}. {c.f_link(f['id'], True)} {prose(f.get('title'))}. Что сделать: {prose(rec)}")
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
    if c.run.get("status") == "failed":
        bad = [stage_name(k) for k, v in (c.run.get("stages") or {}).items() if v == "failed"]
        return ("Проверка не завершена: " + (f"сбой этапов {', '.join(bad)}" if bad else "прогон прерван")
                + ". Отсутствие дефектов здесь не означает готовность документа — повторите прогон; причина — в "
                  "приложении Д.")
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
    out += [f"{len(qs)} {plural(len(qs), 'вопрос', 'вопроса', 'вопросов')}, {_q_word(c, 'many')} — {blocking}. "
            f"Ответ — буква варианта или свой текст, по строке на вопрос (`Q-01: B`); повторный прогон с ответами: "
            f"`python -m bcc_review ВХОД ОТЧЁТ.md --answers ответы.md`.", ""]
    for q in sorted(qs, key=lambda q: (not q.get("blocking"), _id_num(q.get("id")))):
        head = [f"**<a id=\"{anchor(q.get('id'))}\"></a>{q.get('id')}**"
                + (f" {esc(q['topic'])}" if q.get("topic") else ""),
                _q_word(c, "mark") if q.get("blocking") else "можно ответить позже"]
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
    for fid, e in _applied_edits(c.r):
        items.append((fid, e["line"], e["line"], e["before"], e["after"], e["insert"]))
    for rw in c.r.get("rewrites") or []:
        if not rw.get("edits") and (rw.get("after") or rw.get("rewrite")):
            items.append((rw.get("finding_id") or ", ".join(rw.get("finding_ids") or []), rw.get("line_start"),
                          rw.get("line_end"), rw.get("before") or rw.get("quote") or "",
                          rw.get("after") or rw.get("rewrite"), False))
    from_revise = bool(items)
    in_cards = 0
    if not items:
        for f in c.findings:
            src = _rewrite_from(f)
            if src is None:
                continue
            if f.get("severity") in ("critical", "major"):
                in_cards += 1  # «было → стало» уже в карточке раздела 3.2 — здесь не повторяем
                continue
            items.append((f["id"], src.get("line_start"), src.get("line_end"), src.get("quote"), f.get("rewrite"),
                          False))
    cards_note = (f"Для критичных и существенных дефектов ({in_cards}) формулировки «было → стало» — в их карточках "
                  f"(раздел 3.2); здесь — для незначительных." if in_cards else "")
    if not items:
        return out + [(cards_note.replace("; здесь — для незначительных.", ".") if cards_note
                       else "Готовых формулировок нет."), ""]
    st = c.r.get("revise_stats") or {}
    if from_revise and st:
        out += [f"Правки внесены программой в копию документа: заменено фрагментов {num(st.get('replaced', 0))}, "
                f"добавлено строк {num(st.get('inserted', 0))}, не применено {num(st.get('not_applied', 0))}; "
                f"«<уточнить: …>» — место, где нужен ответ владельца ({num(st.get('pending', 0))}).", ""]
    else:
        out += [" ".join(x for x in (cards_note, "«<уточнить: …>» — место, где нужен ответ владельца.") if x), ""]
    rows = [[c.f_link(fid, True) if fid in c.f_by_id else esc(fid),
             (f"после {a}" if ins else lines_word(a, b).replace("строки ", "").replace("строка ", "")),
             "—" if ins else quote_md(before, 120, in_table=True), cell(after) if after else "фрагмент удалён"]
            for fid, a, b, before, after, ins in items]
    out += table(["Дефект", "Строка", "Было", "Стало"], rows)
    if c.r.get("revised_file"):
        from pathlib import PurePath
        out += ["", f"Исправленный текст ТЗ целиком: `{PurePath(str(c.r['revised_file'])).name}` (рядом с отчётом)."]
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
            proposes = stage_key(k) in PROPOSING
            status = STAGE_STATUS.get(v, v) + (" (из прошлого прогона)" if st.get("reused") else "")
            calls = num(st.get("calls")) if "calls" in st else "—"
            if st.get("split"):
                calls += f" (пакет делился: {num(st['split'])})"
            rows.append([name, what, status, calls if "calls" in st else "—",
                         duration(st.get("seconds")) if "seconds" in st else "—",
                         num(st.get("candidates")) if proposes and "candidates" in st else "—"])
        out += table(["Этап", "Что делает", "Итог", "Вызовов", "Время", "Кандидатов"], rows,
                     [":---", ":---", ":---", ":---:", ":---:", ":---:"]) + [""]
    proposed = sum(int((stats.get(k) or {}).get("candidates") or 0) for k in stats if stage_key(k) in PROPOSING)
    n = _candidate_counts(c)
    rej = c.r.get("rejected") or []
    nfind = len(c.findings) + len(c.resolved)
    if n["accepted"] or rej:
        total = n["total"]
        extra = f" (в таблице этапов — {proposed})" if proposed and proposed != total else ""
        bits = [f"вошли в {nfind} {plural(nfind, 'дефект', 'дефекта', 'дефектов')} — {n['accepted']} (повторы "
                f"объединены)"]
        if n["judge"]:
            bits.append(f"отклонены судьёй — {n['judge']}")
        if n["no_quote"]:
            bits.append(f"без найденной в документе цитаты — {n['no_quote']}")
        if n["not_reviewed"]:
            bits.append(f"не рассмотрены судьёй — {n['not_reviewed']}")
        out += [f"Кандидатов в дефекты: {total}{extra}; " + "; ".join(bits) + "."
                + (f" Ещё {n['self_dropped']} {plural(n['self_dropped'], 'кандидат отброшен', 'кандидата отброшены', 'кандидатов отброшены')} самой ролью при проверке." if n["self_dropped"] else "")
                + " Кандидат без найденной в документе цитаты в отчёт не попадает.", ""]
    if rej:
        out += ["**Отклонённые кандидаты**", ""]
        rows = []
        limit = MAX_REJECTED_ROWS if c.level < 1 else 10
        for i, r in enumerate(rej[:limit], 1):
            reason = cell(dejargon(str(r.get("reason") or "")))
            if r.get("duplicate_of"):
                reason += f" → {c.f_link(r['duplicate_of'])}"
            line = r.get("line") if isinstance(r.get("line"), int) and r.get("line") else None
            rows.append([str(i), esc(source_name(r.get("source"))),
                         cell(r.get("title")) + (f" (строка {line})" if line else ""), reason])
        out += table(["№", "Кто предложил", "Что предлагалось", "Почему отклонён"], rows, [":---:", ":---", ":---", ":---"])
        if len(rej) > limit:
            out += ["", f"Ещё {len(rej) - limit} — в `report.json`, поле `rejected`."]
        out.append("")
    warns = run.get("warnings") or []
    if warns:
        out += ["**Предупреждения прогона**", ""] + [f"- {warn_text(w)}" for w in warns[:15]] + [""]
    return out


def _appendix_method(c: _Ctx) -> list[str]:
    out = [h2("pe", "Приложение Е. Методика"), "",
           "Статическое ревью текста до разработки: программа не запускается. Документ нумеруется построчно; "
           "проверяющие роли (аналитик, тестировщик, архитектор, риски, набор целиком) предлагают кандидатов с "
           "дословными цитатами; программа находит каждую цитату в документе и сама определяет строку; судья "
           "объединяет дубли, отклоняет ложные и калибрует серьёзность; вердикт считает программа.", ""]
    if c.level >= 1 or c.offline:
        out += ["**Критерии.** Отдельное требование (ISO/IEC/IEEE 29148:2018 п. 5.2.5, 5.2.7): "
                + ", ".join(CRITERIA[k][0].lower() for k in INDIVIDUAL) + ". Набор (29148 п. 5.2.6, IEEE 830-1998 "
                "п. 4.3): " + ", ".join(CRITERIA[k][0].lower() for k in SET_CRITERIA)
                + ". Плюс ИБ и операционные риски по чек-листу банка.", ""]
    else:
        rows = [[CRITERIA[k][0], CRITERIA[k][1], "требование" if k in INDIVIDUAL else
                 ("набор" if k in SET_CRITERIA else "риски"), CRITERION_WHAT.get(k, "")] for k in CRITERIA]
        out += table(["Критерий", "Стандарт", "Уровень", "Что проверяется"], rows) + [""]
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
            "прогон не даёт «можно»: в лучшем случае «с условиями».", "",
            "**Сверка цитат.** Сравнение без учёта регистра, вида кавычек и тире, лишних пробелов и разметки; "
            "цитата ищется у указанной строки, затем во всём документе, ближе к требованию. Нечёткое совпадение "
            "(не ниже 92 %) допускается только рядом с указанной строкой.", ""]
    return out


# ================================================================== сборка

MAX_LINES = 900
MAX_LEVEL = 7


_LIST_KEYS = ("requirements", "excluded", "findings", "rejected", "acceptance_checks", "pair_checks", "trace",
              "glossary", "test_cases", "questions", "checklist", "rewrites")
_ID_LIST_KEYS = ("requirement_ids", "finding_ids", "candidate_ids", "sources", "rule_requirement_ids", "verified_by",
                 "implemented_by", "options", "standard_refs", "fix_first", "models_used", "warnings",
                 "new_findings", "unanswered", "decisions", "question_ids", "answer_ids")


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
            if k in ("evidence", "terms", "answers", "edits", "changes"):
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
            ("2. Нарезка: как агент нарезал требования", _segmentation),
            ("3. Проверка каждого требования", _per_requirement),
            ("4. Проверка всего набора требований", _set_check), ("5. Сводка", _summary), ("6. Итог", _conclusion),
            ("Приложение А. Вопросы владельцу", _appendix_questions),
            ("Приложение Б. Черновик тест-кейсов", _appendix_tests),
            ("Приложение В. Чек-лист «Ревью требований», заполненный агентом", _appendix_checklist),
            ("Приложение Г. Было → стало", _appendix_rewrites), ("Приложение Д. Как работал агент", _appendix_how),
            ("Приложение Е. Методика", _appendix_method)]


def _render_level(report: dict, level: int) -> str:
    c = _Ctx(_clean_report(report), level)
    _KNOWN_IDS.clear()
    _KNOWN_IDS.update(str(f.get("id")) for f in c.findings)
    _KNOWN_IDS.update(str(q.get("id")) for q in c.reqs)
    _KNOWN_IDS.update(str(q.get("id")) for q in c.r.get("questions") or [])
    _REQ_LABELS.clear()
    _REQ_LABELS.update({str(q.get("id")): (doc_label(q), str(q.get("source_id") or "")) for q in c.reqs
                        if doc_label(q)})
    # офлайн: приложения, которые без модели всегда пусты (вопросы, тест-кейсы, чек-лист), не печатаются (№12)
    c.skip = {fn for fn, key, anchor_id in ((_appendix_questions, "questions", "pa"), (_appendix_tests, "test_cases", "pb"),
                                            (_appendix_checklist, "checklist", "pv"))
              if c.offline and not c.r.get(key)}
    c.skip_nav = {a for fn, key, a in ((_appendix_questions, "questions", "pa"), (_appendix_tests, "test_cases", "pb"),
                                       (_appendix_checklist, "checklist", "pv")) if fn in c.skip}
    parts = []
    for title, fn in _sections():
        if fn in c.skip:
            continue
        try:
            parts.append(fn(c))
        except Exception as exc:  # noqa: BLE001 — один сломанный раздел не должен лишить аналитика отчёта
            head = [f"## {title}", ""] if title else []
            parts.append(head + [f"⚠️ Раздел не построен: в данных прогона ошибка ({esc(type(exc).__name__)}: "
                                 f"{esc(shorten(str(exc), 160))}). Полные данные — в `report.json`.", ""])
    lines = []
    for ln in (ln for part in parts for ln in part):
        if not ln.strip() and lines and not lines[-1].strip():
            continue  # не больше одной пустой строки подряд
        lines.append(ln)
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


_ANCHOR_TAG = re.compile(r'<a id="[^"]*"></a>')
_LINK_TITLE = re.compile(r'(\]\(#[\w-]+) "[^"]*"\)')


def export_text(md: str) -> str:
    """Markdown-отчёт для переноса в Word/PDF (экспорт №03): без HTML-якорей, без экранирования Markdown,
    «|» внутри ячеек заменён на «∣», чтобы простые конвертеры не ломали столбцы таблиц."""
    out = _ANCHOR_TAG.sub("", md)
    out = _LINK_TITLE.sub(r"\1)", out)
    out = out.replace("\\|", "∣")
    out = re.sub(r"\\([\\`*_\[\]<>#])", r"\1", out)
    return out


def write(report: dict, path) -> str:
    from pathlib import Path

    text = render(report)
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return text


# ================================================================== рубрика понятности (WAVE3.md)

RUBRIC = {
    "title": "заголовок до 12 слов",
    "place": "место: строка (и страница для PDF), ID требования или раздел",
    "problem": "проблема в 1–3 предложениях",
    "scenario": "сценарий для противоречия или неполноты",
    "impact": "последствие",
    "fix": "исправление: «было → стало» или вопрос владельцу",
    "codes": "в тексте нет внутренних кодов и латиницы вне имён",
}
_RUBRIC_CODES = re.compile(r"\bC-\d{2,4}\b|\blens[:_]\w+|\bsame_subject\b|\bL\d{2,4}\b|\b(?:critical|major|minor)\b")
_SCENARIO_KINDS = CONFLICT_KINDS | {"missing_element", "incomplete"}


def _sentences(text: str) -> int:
    return len([x for x in _SENT_SPLIT.split(" ".join(str(text or "").split())) if x.strip()])


def rubric(report: dict) -> dict:
    """Проверка каждого критичного и существенного дефекта по рубрике понятности WAVE3.md.

    Возвращает {"checked", "passed", "share", "failed": {D-…: [пункты рубрики]}, "by_item": {пункт: число провалов}}.
    Проверяется то, что видит читатель: карточка отчёта (место — как его пишет рендер, тексты — после «L038» →
    «строка 38»)."""
    rep = _clean_report(report)
    c = _Ctx(rep)
    is_pdf = (rep.get("document") or {}).get("format") in ("pdf", "docx")
    failed: dict[str, list[str]] = {}
    for f in c.findings:
        if f.get("severity") not in ("critical", "major"):
            continue
        bad = []
        if len(str(f.get("title") or "").split()) > 12:
            bad.append("title")
        evs = [e for e in f.get("evidence") or [] if isinstance(e.get("line_start"), int)]
        if not evs or (is_pdf and (rep.get("document") or {}).get("format") == "pdf"
                       and not all(e.get("page") for e in evs)) or any(not c.ev_label(e, f.get("requirement_ids") or [])
                                                                       for e in evs):
            bad.append("place")
        n = _sentences(f.get("problem"))
        if not 1 <= n <= 3:
            bad.append("problem")
        if f.get("kind") in _SCENARIO_KINDS and not str(f.get("scenario") or "").strip():
            bad.append("scenario")
        if not str(f.get("impact") or "").strip():
            bad.append("impact")
        if not (str(f.get("recommendation") or "").strip() and (str(f.get("rewrite") or "").strip()
                                                                or str(f.get("question") or "").strip()
                                                                or c.q_by_finding.get(f.get("id")))):
            bad.append("fix")
        shown = " ".join(_LREF.sub(_lref, str(f.get(k) or "")) for k in
                         ("title", "problem", "scenario", "impact", "recommendation"))
        if _RUBRIC_CODES.search(re.sub(r"`[^`]*`", "", shown)):
            bad.append("codes")
        if bad:
            failed[f["id"]] = bad
    checked = sum(1 for f in c.findings if f.get("severity") in ("critical", "major"))
    by_item = {k: sum(1 for v in failed.values() if k in v) for k in RUBRIC}
    return {"checked": checked, "passed": checked - len(failed),
            "share": round((checked - len(failed)) / checked, 3) if checked else 1.0,
            "failed": failed, "by_item": {k: v for k, v in by_item.items() if v}}
