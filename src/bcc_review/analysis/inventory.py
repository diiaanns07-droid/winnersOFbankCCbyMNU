"""Нарезка документа на атомарные требования и реестр судьбы каждого блока (направление №04).

Публичный интерфейс::

    build_inventory(document, ask=None, **options) -> {
        "requirements": [...],          # атомарные обязательства
        "fact_hints": [...],            # наблюдаемые факты для сверки кодом (№06)
        "excluded": [...],              # группы не-обязательств: категория, причина, ID блоков
        "unprocessed_block_ids": [...], # явный остаток
        "warnings": [...],
        "block_coverage": {...},        # объяснимый уровень покрытия и судьба каждого блока
        "mode": "rules_only" | "rules_plus_llm",
        "version": VERSION,
    }

Требование (проходит ``contracts.validate(r, "Requirement")``): ``{id, group, source_id, source_ref, kind,
text, block_ids, hints, evidence, section, origin, review_status, review_reason}``; ``group`` — общий
внутренний ID исходного пункта, ``source_id`` — номер пункта в документе или ``None``.
Hint: ``{block_id, quote[, context]}``; ``quote`` — дословная подстрока ``block.text`` (проверено кодом),
``context`` (строка) добавляется, если цитата встречается в блоке не один раз. ``evidence`` — те же
опоры с координатами: ``block.text[start:end] == quote``.
FactHint: ``{id, subject, field, direction, type, value, unit, range, condition, required, size,
values, db_field, hints, evidence, req_ids, origin}``; неизвестное значение = ``None``.
Предупреждение: ``{code, message, stage: "inventory", block_ids}``.

При ``ask=None`` работают только правила: явные нумерованные пункты, строки таблиц и абзацы
разделов требований. С ``ask`` модель получает окна блоков по схеме :data:`RESPONSE_SCHEMA`,
ответ проверяется программно, необработанные блоки повторно предъявляются один раз в рамках
бюджета вызовов, остаток показывается явно.

Payload вызова — ``{task, input, context}`` по contracts/HANDOFF.md; короткий документ идёт целиком
(``context.mode = full``), окна большого — ``mode = blocks``. Модуль не импортирует остальной пакет:
Document и Block принимаются как dict или как объект с атрибутами по контракту v1.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Mapping

__all__ = [
    "build_inventory",
    "build_payload",
    "RESPONSE_SCHEMA",
    "PROMPT",
    "STAGE",
    "VERSION",
    "KINDS",
    "EXCLUSION_CATEGORIES",
]

STAGE = "inventory"
VERSION = "p04-inventory/1.0"

KINDS: tuple[str, ...] = (
    "functional",
    "nonfunctional",
    "data",
    "integration",
    "ui",
    "contract",
    "acceptance",
)

# категория -> (причина по умолчанию, нужна ли группе сквозная сверка набора)
EXCLUSION_CATEGORIES: dict[str, tuple[str, bool]] = {
    "structure": ("Заголовок, разделитель или шапка таблицы: задаёт структуру, обязательства не содержит.", False),
    "empty": ("Пустой блок или пустая строка таблицы.", False),
    "goal": ("Цель или ожидаемая польза: обоснование для трассировки, а не проверяемое обязательство.", True),
    "metadata": ("Метаданные: паспорт задачи, роли, проект, автор, описательные строки контракта.", True),
    "preamble": ("Вводный или описательный текст раздела без собственного обязательства.", True),
    "placeholder": ("Заглушка: раздел или значение не заполнены.", True),
    "example": ("Пример запроса, ответа или команды: остаётся опорой для сверки с контрактом.", True),
    "design": ("Описание архитектуры или схемы без самостоятельного обязательства: нужно для сверки согласованности.", True),
    "glossary": ("Глоссарий: определения терминов, а не обязательства.", True),
    "review_checklist": ("Шаблон чек-листа ревью: варианты отметок, а не требования к продукту.", True),
    "approval": ("Блок согласования: подразделение, ФИО и подпись не являются функциональными требованиями.", True),
    "fragment": ("Служебная связка или обрывок без самостоятельного утверждения.", False),
    "other": ("Не обязательство (причину указала модель).", True),
}

# Эти группы определяются кодом и не отдаются модели как обрабатываемые.
HARD_CATEGORIES = frozenset({"structure", "empty", "review_checklist", "approval"})

PROMPT = """Ты — аналитик требований. Задача: инвентаризация. Разложи блоки документа на атомарные проверяемые обязательства и укажи судьбу каждого блока. Отвечай строго JSON по схеме, по-русски.

Вход: текст документа приложен в контексте, каждый блок помечен своим id в квадратных скобках. В input.blocks перечислены блоки окна в исходном порядке: id, section (путь заголовков), kind, label (номер пункта, найденный кодом, или null), process и иногда text. Обрабатывай блоки с process=true (их id также в input.window.process_block_ids). Блоки с process=false даны только для контекста.

1. Обязательство (items) — утверждение о поведении, свойстве, ограничении, данных, интерфейсе или интеграции, выполнение которого можно проверить, даже если оно написано без «должен». kind:
- functional — поведение и бизнес-правила системы;
- nonfunctional — время, нагрузка, доступность, безопасность;
- data — что хранить и в каком виде;
- integration — обмен между системами, в том числе шаг схемы, если он задаёт, что и когда передаётся;
- ui — экран и реакция интерфейса;
- contract — обязательство API: метод, адрес, авторизация, параметр, код ответа и его смысл;
- acceptance — строка или сценарий критерия приёмки (исходные условия, действие, ожидаемый результат).
Критерии приёмки и обязательства контракта API выдавай как items (acceptance и contract): по ним идёт сквозная сверка набора.
Строка таблицы параметров API — один item contract на параметр. Тип, размер, обязательность и допустимые значения выпиши в facts. Не делай item из каждой ячейки.

2. Не обязательство (excluded: category, reason, block_ids; у каждой группы своя причина):
- goal — цель, ожидаемая польза;
- metadata — паспорт задачи, роли, автор, проект, фреймворк, версия; строка контракта, которая только описывает (контроллер, проект), а не обязывает;
- preamble — вводный и описательный текст без собственного обязательства;
- placeholder — заглушка («заполняется», «—», TBD);
- example — пример запроса или ответа, команда curl;
- design — описание архитектуры, BPMN или sequence без самостоятельного обязательства;
- glossary — определения терминов;
- review_checklist — чек-лист ревью и варианты отметок «Да / Нет»;
- approval — согласование: подразделение, ФИО, подпись, дата. Подпись никогда не является функциональным требованием;
- fragment — служебная связка («или») или обрывок;
- other — иное, причину напиши.

3. Атомарность:
- один item — одно проверяемое обязательство. Если пункт задаёт нижнюю границу, верхнюю границу и значение по умолчанию, это три items;
- у всех частей одного пункта один и тот же source_id — номер пункта из документа (например «П-3», «2.1», «404»). Если номера нет, ставь null. Бери номер только из text или label, не выдумывай;
- одинаковый номер в разных разделах означает разные пункты, не объединяй их;
- text — короткая формулировка обязательства, пересказ допустим;
- evidence — 1–3 опоры {block_id, quote}. quote — дословная непрерывная подстрока text указанного блока, без изменений, многоточий и пересказа; самая короткая, по которой обязательство видно. Первая опора — из блока с process=true.

4. Учёт: каждый блок с process=true попадает либо в evidence хотя бы одного item, либо в block_ids ровно одной группы excluded. Не пропускай блоки.

5. facts — наблюдаемые факты из тех же блоков: subject (сущность), field (поле или величина), direction (request — параметр запроса API, response — поле ответа API, business — бизнес-правило), type (integer, string, boolean, date, money, duration и т. п.), value (строкой), unit, range {min, max, min_inclusive, max_inclusive}, condition, required (обязательность), values (перечень допустимых значений, иначе []), evidence. Пиши только сказанное явно, неизвестное — null. Включённость границы ставь true или false, только если она сказана («включительно», «обе границы включены», «не более»), иначе null. Числа в range пиши числом без пробелов.

6. Последним полем верни "done": true."""

def _strict(props: dict[str, Any]) -> dict[str, Any]:
    """Объект для structured outputs: все поля обязательны, лишних полей нет (contracts/HANDOFF.md)."""
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


_NSTR: dict[str, Any] = {"type": ["string", "null"]}
_EVIDENCE_SCHEMA = _strict({"block_id": {"type": "string"}, "quote": {"type": "string"}})

RESPONSE_SCHEMA: dict[str, Any] = _strict({
    "items": {"type": "array", "items": _strict({
        "source_id": _NSTR,
        "kind": {"type": "string", "enum": list(KINDS)},
        "text": {"type": "string"},
        "evidence": {"type": "array", "items": _EVIDENCE_SCHEMA},
    })},
    "excluded": {"type": "array", "items": _strict({
        "category": {"type": "string", "enum": list(EXCLUSION_CATEGORIES)},
        "reason": {"type": "string"},
        "block_ids": {"type": "array", "items": {"type": "string"}},
    })},
    "facts": {"type": "array", "items": _strict({
        "subject": _NSTR,
        "field": _NSTR,
        "direction": {"anyOf": [{"type": "string", "enum": ["request", "response", "business"]}, {"type": "null"}]},
        "type": _NSTR,
        "value": _NSTR,
        "unit": _NSTR,
        "range": {"anyOf": [{"type": "null"}, _strict({
            "min": {"type": ["number", "null"]},
            "max": {"type": ["number", "null"]},
            "min_inclusive": {"type": ["boolean", "null"]},
            "max_inclusive": {"type": ["boolean", "null"]},
        })]},
        "condition": _NSTR,
        "required": {"type": ["boolean", "null"]},
        "values": {"type": "array", "items": {"type": "string"}},
        "evidence": {"type": "array", "items": _EVIDENCE_SCHEMA},
    })},
    "done": {"type": "boolean"},
})

# ---------------------------------------------------------------------------- регулярные выражения

_WS_RE = re.compile(r"\s+")
_MARKUP_RE = re.compile(r"\*\*|__|`")
_HR_RE = re.compile(r"^\s*(?:-{3,}|\*{3,}|_{3,}|={3,})\s*$")
_PIPE_ROW_RE = re.compile(r"^\s*\|.*\|\s*$")
_SEP_CELL_RE = re.compile(r"^:?-{2,}:?$")
_LETTER_RE = re.compile(r"[A-Za-zА-Яа-яЁё]")
_MODAL_RE = re.compile(
    r"(?<![\w-])(?:долж(?:ен|на|но|ны)|обязан\w*|необходимо|требуется|следует|shall|must|is required to)(?![\w-])",
    re.I,
)
_PLACEHOLDER_RE = re.compile(
    r"^\s*(?:—|–|-|tbd|tba|todo|n/?a|нет данных|не заполнен\w*|заполня\w*(?:\s+\w+)?|"
    r"будет\s+\w+\s+позже|to be (?:defined|determined|done))\s*\.?\s*$",
    re.I,
)
_PLACEHOLDER_VALUE_RE = re.compile(r"^(?:—|–|-|tbd|tba|todo|n/?a|нет|не определен\w*|не указан\w*|)$", re.I)
_CONNECTOR_RE = re.compile(
    r"^\s*(?:или|либо|или же|а также|or|and|далее|см\. (?:выше|ниже)|пример|например|example)\s*[.:]?\s*$",
    re.I,
)
_ARROW_RE = re.compile(r"→|->|=>")

_LABEL_RE = re.compile(
    r"""^[ \t]*(?:[*+•\-][ \t]+)?               # маркер списка
    (?:\*\*|__)?[ \t]*
    (?P<label>
        (?P<alpha>[A-Za-zА-Яа-яЁё]{1,10}(?:[-_.][A-Za-zА-Яа-яЁё]{1,10})*[-_.]?\d+(?:[.\-]\d+)*)
      | (?P<multi>\d+(?:\.\d+)+)
      | (?P<num>\d{1,4})
      | (?P<letter>\(?[a-zа-я])
    )
    (?P<punct>[.:)]|[ \t]+[—–-])?
    [ \t]*(?:\*\*|__)?
    (?=[ \t]|$)""",
    re.X,
)
# Префиксы, которые считаются номером даже без точки/двоеточия и без выделения.
_LABEL_PREFIXES = frozenset(
    "REQ FR NFR BR UR SR TR UC US AC R RQ Ф ФТ НФТ БТ ТТ Т ТР П ПТ ИТ ДТ КП СТ КТ ТЗ БП".split()
)

# Роли разделов: порядок важен, первым совпадением по самому глубокому заголовку.
_ROLE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("approval", re.compile(r"согласующ|лист согласован|блок согласован|утвержд|подпис|sign-?off|approval")),
    ("review_checklist", re.compile(r"\bревью\b|\breview\b|чек-?лист|check-?list")),
    ("metadata", re.compile(
        r"общие сведения|сведения о документ|паспорт|метаданн|metadata|истори\w* изменени|лист изменени|"
        r"revision|document info|general information|общая информаци")),
    ("goal", re.compile(r"\bцел[ьи]\b|назначени|\bgoals?\b|purpose|objectives?|ценност|мотиваци|бизнес-?эффект")),
    ("glossary", re.compile(r"глоссари|термины|определения|glossary|definitions|сокращени")),
    ("acceptance", re.compile(r"критери\w* при[её]мк|при[её]мочн|acceptance|сценари\w* при[её]мк")),
    ("testing", re.compile(r"тестировани|\btesting\b|\bqa\b|тест-?кейс|test cases?")),
    ("design", re.compile(r"архитектур|architecture|\bbpmn\b|sequence|диаграмм|diagram|\bсхема\b|scheme|блок-?схем")),
    ("contract", re.compile(r"\bapi\b|\brest\b|endpoint|эндпоинт|swagger|\bhttp\b|\bsoap\b|\bgrpc\b|graphql")),
    ("nonfunctional", re.compile(
        r"нефункциональн|\bнфт\b|non-?functional|производительн|надёжн|надежн|performance|"
        r"безопасност|security|качеств|quality|доступност")),
    ("data", re.compile(r"\bданн\w*|\bdata\b")),
    ("integration", re.compile(r"интеграц|integration|взаимодейств")),
    ("ui", re.compile(r"\bui\b|\bux\b|\bgui\b|интерфейс|экран|макет|дизайн|mockup|wireframe")),
    ("requirements", re.compile(
        r"требовани|requirement|правил|\brules?\b|логика|\blogic\b|ограничени|constraint|функционал|"
        r"function|возможност|features?")),
]
# Слабые слова контракта: считаются контрактом только внутри части про API.
_WEAK_CONTRACT_RE = re.compile(
    r"параметр|parameter|\bответ\w*|response|\bзапрос\w*|request|статус|status|\bметод\w*|header|\bbody\b")
_REQ_ROLES = frozenset({"requirements", "nonfunctional", "data", "integration", "ui", "contract", "acceptance"})
_ROLE_KIND = {
    "nonfunctional": "nonfunctional",
    "data": "data",
    "integration": "integration",
    "ui": "ui",
    "contract": "contract",
    "acceptance": "acceptance",
}

# Таблицы.
_OPTION_RE = re.compile(
    r"^(?:да|нет|yes|no|не требуется|n/?a)(?:\s*/\s*(?:да|нет|yes|no|не требуется|n/?a))+$")
_APPROVAL_HEAD_RE = re.compile(r"подпис|signature|\bsign\b|sign-?off|\bфио\b|согласующ|утвержд")
_CHECK_HEAD_RE = re.compile(r"провер|check")
_META_HEAD_RE = re.compile(
    r"^(?:верси\w*|version|дата|date|автор|author|изменени\w*|changes?|revision|редакци\w*|статус документа)$")
_GLOSS_HEAD_RE = re.compile(r"термин|\bterm\b|определени|definition|сокращени|abbreviation|глоссари|понятие")
_ACC_GIVEN_RE = re.compile(r"исходн|предуслов|\bдано\b|given|precondition")
_ACC_THEN_RE = re.compile(r"ожидаем|результат|тогда|\bthen\b|expected")
_NAME_COL_RE = re.compile(r"^(?:parameter|param|параметр|поле|field|name|имя|атрибут|attribute|свойство|property)\b")
_TYPE_COL_RE = re.compile(r"^(?:format|формат|type|тип|data type|тип данных)\b")
_SIZE_COL_RE = re.compile(r"^(?:size|размер|длина|length|max length)")
_REQ_COL_RE = re.compile(r"^(?:mandatory|обязат|required|req\b|optional|опционал)")
_LOGIC_COL_RE = re.compile(r"^(?:logic|логика|значени|values|допустим|ограничен|constraint|range|диапазон|правил)")
_DESC_COL_RE = re.compile(r"^(?:description|описание|назначение|комментар|comment)")
_DB_COL_RE = re.compile(r"\bdb\b|\bбд\b|column|колонк")
_ID_COL_RE = re.compile(r"^(?:id|№|#|код|номер|n|no\.?|ид)$")
_KV_KEY_HEAD_RE = re.compile(r"^(?:поле|field|параметр|атрибут|ключ|key|свойство|наименование|характеристика|property)")
_CONTRACT_KEY_RE = re.compile(
    r"\b(?:rest|http)\b|method|метод|authori[sz]|авториз|аутентиф|authentication|request url|endpoint|"
    r"эндпоинт|^url$|адрес|content-type|тип содержимого|протокол|protocol|timeout|тайм-?аут|rate limit|"
    r"лимит запрос|идемпотент")
_EXAMPLE_KEY_RE = re.compile(r"curl|пример|example|sample")

# Факты.
_NUM = r"\d{1,3}(?:[   ]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?"
_UNIT = (
    r"₸|тенге|тг\b|kzt\b|тиын\w*|руб\w*|₽|usd\b|eur\b|€|\$|%|процент\w*|мс\b|миллисекунд\w*|"
    r"секунд\w*|сек\b|минут\w*|мин\b|час\w*|сут\w*|дн(?:я|ей)\b|день\b|бит\w*|bit\b|байт\w*|"
    r"символ\w*|знак\w*"
)
_RANGE_TEXT_RE = re.compile(
    rf"\bот\s+(?P<min>{_NUM})\s*(?P<u1>{_UNIT})?\s+до\s+(?P<max>{_NUM})(?:\s*(?P<u2>{_UNIT}))?(?P<incl>\s+включительно)?",
    re.I)
_RANGE_DASH_RE = re.compile(rf"^(?P<min>{_NUM})\s*[–—-]\s*(?P<max>{_NUM})\s*(?P<u>{_UNIT})?$", re.I)
_BOUND_RE = re.compile(
    rf"(?P<op>не более|не больше|не превыша\w*|максимум|не позднее|не менее|не меньше|минимум|не ранее)"
    rf"\s+(?:чем\s+)?(?:за\s+)?(?P<num>{_NUM})\s*(?P<u>{_UNIT})?",
    re.I)
_WITHIN_RE = re.compile(rf"\bв течение\s+(?P<num>{_NUM})\s*(?P<u>{_UNIT})", re.I)
_INCL_RE = re.compile(r"обе границы включ\w*|границы включ\w*|включая границы", re.I)
_INTEGER_RE = re.compile(r"\bцел(?:ое|ый|ым|ого|ую|ые|ых|ыми)\s+(?P<w1>[А-Яа-яЁё]+)(?:\s+(?P<w2>[А-Яа-яЁё₸]+))?", re.I)
_UNIT_PHRASE_RE = re.compile(
    r"(?P<field>[А-Яа-яЁёA-Za-z][\w-]*(?:[ \t]+[А-Яа-яЁёA-Za-z][\w-]*){0,2})[ \t]+в[ \t]+"
    r"(?P<u>тиынах|тенге|копейках|рублях|долларах|центах|секундах|миллисекундах|минутах|часах|днях|"
    r"байтах|битах|процентах|символах)\b",
    re.I)
_DEFAULT_RE = re.compile(
    r"\bпо умолчанию[ \t,]+(?P<field>[А-Яа-яЁёA-Za-z][\w-]*(?:[ \t]+[А-Яа-яЁёA-Za-z][\w-]*)?)[ \t]+"
    r"(?P<value>включен\w*|выключен\w*|отключен\w*|активн\w*|неактивн\w*|разреш\w*|запрещ\w*|пуст\w*|"
    r"скрыт\w*|отображ\w*)",
    re.I)
_UNIT_CANON: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"^(?:₸|тенге|тг\.?|kzt)$", re.I), "тенге"),
    (re.compile(r"^тиын", re.I), "тиын"),
    (re.compile(r"^(?:руб|₽|rub)", re.I), "рубль"),
    (re.compile(r"^(?:usd|\$)$", re.I), "USD"),
    (re.compile(r"^(?:eur|€)$", re.I), "EUR"),
    (re.compile(r"^(?:%|процент)", re.I), "процент"),
    (re.compile(r"^(?:мс|миллисекунд)", re.I), "миллисекунда"),
    (re.compile(r"^(?:сек|секунд)", re.I), "секунда"),
    (re.compile(r"^(?:мин|минут)", re.I), "минута"),
    (re.compile(r"^час", re.I), "час"),
    (re.compile(r"^(?:сут|дн|день|дней)", re.I), "день"),
    (re.compile(r"^(?:бит|bit)", re.I), "бит"),
    (re.compile(r"^(?:байт|byte)", re.I), "байт"),
    (re.compile(r"^(?:символ|знак)", re.I), "символ"),
]
_DIR_RESPONSE_RE = re.compile(r"\bответ\w*|response|выходн|output")
_DIR_REQUEST_RE = re.compile(r"\bзапрос\w*|request|query|\bpath\b|header|\bbody\b|входн|input")

_ABBREVIATIONS = frozenset(
    "т д п е г гг др пр см ср рис табл стр ст ул им напр тыс млн млрд руб коп вкл искл макс прим "
    "т.д т.п т.е т.ч e.g i.e etc vs no".split()
)
_QUOTE_FOLD = {
    "«": '"', "»": '"', "“": '"', "”": '"', "„": '"', "‘": "'", "’": "'", "‚": "'",
    "–": "-", "—": "-", "‑": "-", "−": "-", "ё": "е", "Ё": "е",
}

# ---------------------------------------------------------------------------- служебные функции


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, Mapping):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _kw(text: Any) -> str:
    """Текст для сопоставления ключевых слов: без разметки, нижний регистр, ё→е."""
    return _WS_RE.sub(" ", re.sub(r"[*`]", "", str(text or ""))).strip().lower().replace("ё", "е")


def _clean(text: str) -> str:
    """Короткая формулировка из дословного фрагмента: без разметки Markdown и лишних пробелов."""
    s = _MARKUP_RE.sub("", text or "")
    s = _WS_RE.sub(" ", s).strip()
    return re.sub(r"\s+([.,;:!?])", r"\1", s)


def _none_if_empty(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str):
        v = value.strip()
        if not v or v.lower() in {"null", "none", "unknown", "неизвестно", "n/a"}:
            return None
        return v
    return value


def _norm_map(text: str) -> tuple[str, list[int]]:
    """Нормализованный текст и отображение его символов на позиции исходника."""
    out: list[str] = []
    idx: list[int] = []
    prev_space = True
    for i, ch in enumerate(text):
        if ch in "*`":
            continue
        if ch.isspace():
            if not prev_space:
                out.append(" ")
                idx.append(i)
                prev_space = True
            continue
        c = _QUOTE_FOLD.get(ch, ch)
        low = c.lower()
        out.append(low if len(low) == 1 else c)
        idx.append(i)
        prev_space = False
    if out and out[-1] == " ":
        out.pop()
        idx.pop()
    return "".join(out), idx


def _locate(quote: Any, text: str) -> tuple[int, int, str] | None:
    """Находит цитату в тексте блока: дословно, затем с нормализацией пробелов, кавычек, тире и разметки."""
    if not isinstance(quote, str):
        return None
    q = quote.strip()
    if not q:
        return None
    i = text.find(q)
    if i >= 0:
        return i, i + len(q), "exact"
    nt, idx = _norm_map(text)
    nq, _ = _norm_map(q)
    if not nq:
        return None
    j = nt.find(nq)
    if j < 0:
        return None
    start, end = idx[j], idx[j + len(nq) - 1] + 1
    # разметку на краях нормализация отбросила: возвращаем ту, что была в цитате модели
    lead = len(q) - len(q.lstrip("*`"))
    trail = len(q) - len(q.rstrip("*`"))
    while lead and start > 0 and text[start - 1] in "*`":
        start, lead = start - 1, lead - 1
    while trail and end < len(text) and text[end] in "*`":
        end, trail = end + 1, trail - 1
    # непарный бэктик или ** внутри фрагмента выравниваем по соседнему символу источника
    for mark in ("`", "**"):
        if text[start:end].count(mark) % 2:
            if text[max(0, start - len(mark)):start] == mark:
                start -= len(mark)
            elif text[end:end + len(mark)] == mark:
                end += len(mark)
    return start, end, "normalized"


def _norm_label(label: Any) -> str:
    s = _kw(label)
    s = re.sub(r"^(?:п\.|пункт|№|#|item|req\.)\s*", "", s)
    s = re.sub(r"[\s ]", "", s)
    s = s.translate(str.maketrans({"–": "-", "—": "-", "‑": "-", "_": "-"}))
    return s.strip(".:)(")


def _parse_num(text: str | None) -> int | float | None:
    if text is None:
        return None
    s = re.sub(r"[\s  ]", "", str(text)).replace(",", ".")
    try:
        f = float(s)
    except ValueError:
        return None
    return int(f) if f.is_integer() and "." not in s else f


def _canon_unit(text: str | None) -> str | None:
    if not text:
        return None
    t = text.strip().lower()
    for pat, name in _UNIT_CANON:
        if pat.search(t):
            return name
    return None


def _lines(text: str) -> list[tuple[int, int]]:
    spans = []
    pos = 0
    for line in text.split("\n"):
        spans.append((pos, pos + len(line)))
        pos += len(line) + 1
    return spans


def _label_ok(m: re.Match[str], line: str) -> bool:
    punct = (m.group("punct") or "").strip()
    bold = "**" in line[: m.end()] or "__" in line[: m.end()]
    if m.group("num"):
        return bool(punct)
    if m.group("letter"):
        return punct == ")"
    if m.group("multi"):
        return True
    prefix = re.match(r"[A-Za-zА-Яа-яЁё]+", m.group("label"))
    return bool(punct) or bold or bool(prefix and prefix.group().upper() in _LABEL_PREFIXES)


def _match_label(line: str) -> tuple[str, int] | None:
    """Номер пункта в начале строки и позиция начала содержательной части."""
    m = _LABEL_RE.match(line)
    if not m or not _label_ok(m, line):
        return None
    end = m.end()
    while end < len(line) and line[end] in " \t":
        end += 1
    return m.group("label").lstrip("("), end


def _heading_label(heading: str) -> str | None:
    found = _match_label(heading)
    return found[0] if found else None


@dataclass
class _Segment:
    label: str | None
    start: int
    end: int


def _segments(text: str) -> list[_Segment]:
    """Делит блок на сегменты по строкам, начинающимся с номера пункта."""
    segs: list[_Segment] = []
    cur: _Segment | None = None
    for s, e in _lines(text):
        line = text[s:e]
        found = _match_label(line)
        if found:
            if cur:
                segs.append(cur)
            cur = _Segment(found[0], s + found[1], e)
        elif cur is None:
            cur = _Segment(None, s, e)
        else:
            cur.end = e
    if cur:
        segs.append(cur)
    return segs


def _trim(text: str, a: int, b: int) -> tuple[int, int]:
    while a < b and text[a].isspace():
        a += 1
    while b > a and text[b - 1].isspace():
        b -= 1
    return a, b


_SENT_END_RE = re.compile(r"[.!?…]+[\"»”)\]]*(?=\s)")


def _sentences(text: str, start: int, end: int) -> list[tuple[int, int]]:
    """Разбиение на предложения с учётом сокращений, инициалов и чисел."""
    spans: list[tuple[int, int]] = []
    cur = start
    for m in _SENT_END_RE.finditer(text, start, end):
        j = m.end()
        while j < end and text[j].isspace():
            j += 1
        if j >= end:
            break
        nxt = text[j]
        if not (nxt.isupper() or nxt.isdigit() or nxt in "«\"*(`["):
            continue
        w = m.start()
        while w > cur and (text[w - 1].isalpha() or text[w - 1] == "."):
            w -= 1
        token = text[w : m.start()].lower().rstrip(".")
        if token in _ABBREVIATIONS or (len(token) == 1 and token.isalpha()):
            continue
        spans.append(_trim(text, cur, m.end()))
        cur = j
    spans.append(_trim(text, cur, end))
    return [(a, b) for a, b in spans if b > a]


# ---------------------------------------------------------------------------- модель данных


@dataclass
class _Block:
    idx: int
    id: str
    kind: str
    section: tuple[str, ...]
    text: str
    marker: str | None
    loc: Any = None


@dataclass
class _Hint:
    block_id: str
    start: int
    end: int
    quote: str


@dataclass
class _Atom:
    kind: str
    text: str
    source_id: str | None
    hints: list[_Hint]
    origin: str
    sid_src: str | None = None  # label | heading | text | None
    context_anchor: bool = False


@dataclass
class _Fact:
    hints: list[_Hint]
    origin: str
    subject: str | None = None
    field: str | None = None
    direction: str | None = None
    type: str | None = None
    value: Any = None
    unit: str | None = None
    range: dict[str, Any] | None = None
    condition: str | None = None
    required: bool | None = None
    size: str | None = None
    values: list[str] | None = None
    db_field: str | None = None


class _Warning(dict):
    """Контрактный ``Warning``-объект, который при ``str()`` читается как «код: сообщение»."""

    def __str__(self) -> str:
        return f"{self['code']}: {self['message']}"


@dataclass
class _Fate:
    atoms: list[_Atom] = field(default_factory=list)
    excl: tuple[str, str] | None = None
    unprocessed: str | None = None
    facts: list[_Fact] = field(default_factory=list)


@dataclass
class _Cell:
    block_id: str
    start: int
    end: int
    text: str


@dataclass
class _Row:
    cells: list[_Cell]
    block_id: str
    line: int
    separator: bool = False

    @property
    def values(self) -> list[str]:
        return [c.text for c in self.cells]

    @property
    def empty(self) -> bool:
        return not any(_clean(c.text) for c in self.cells)


@dataclass
class _Table:
    section: tuple[str, ...]
    rows: list[_Row] = field(default_factory=list)

    @property
    def header(self) -> _Row | None:
        body = [r for r in self.rows if not r.separator]
        return body[0] if len(body) >= 2 else None

    @property
    def data(self) -> list[_Row]:
        head = self.header
        return [r for r in self.rows if not r.separator and r is not head]


@dataclass
class _Stats:
    hints_checked: int = 0
    hints_exact: int = 0
    hints_repaired: int = 0
    hints_rejected: int = 0
    hints_empty: int = 0
    items_rejected: int = 0
    source_ids_cleared: int = 0
    source_ids_filled: int = 0
    duplicates_merged: int = 0
    context_linked: int = 0
    excluded_unknown_ids: int = 0
    conflicts_resolved: int = 0
    facts_rejected: int = 0
    hints_ambiguous: int = 0


def _split_pipe_row(text: str, base: int, block_id: str) -> list[_Cell]:
    pipes: list[int] = []
    in_code = False
    for i, ch in enumerate(text):
        if ch == "`":
            in_code = not in_code
        elif ch == "|" and not in_code and (i == 0 or text[i - 1] != "\\"):
            pipes.append(i)
    a, b = _trim(text, 0, len(text))
    if not pipes:
        return [_Cell(block_id, base + a, base + b, text[a:b])]
    edges = list(pipes)
    if text[a] != "|":
        edges.insert(0, a - 1)
    if text[b - 1] != "|":
        edges.append(b)
    cells = []
    for left, right in zip(edges, edges[1:]):
        s, e = _trim(text, left + 1, right)
        cells.append(_Cell(block_id, base + s, base + e, text[s:e]))
    return cells


# ---------------------------------------------------------------------------- инвентарь


class _Inventory:
    def __init__(self, document: Any) -> None:
        self.warnings: list[dict[str, Any]] = []
        self.stats = _Stats()
        self.doc_id = _get(document, "id")
        self.title = _get(document, "title")
        self.blocks = self._load_blocks(document)
        self.by_id = {b.id: b for b in self.blocks}
        self.section_set = {b.section for b in self.blocks}
        self._role_cache: dict[tuple[str, ...], str | None] = {}
        self.labels: dict[str, list[tuple[int, int, str]]] = {}
        self.tables: list[_Table] = []
        self.row_of: dict[str, list[_Row]] = {}
        self.header_block: dict[str, str] = {}
        self._group_tables()
        self._collect_labels()
        self.parent_label = self._continuations()
        self.fates: dict[str, _Fate] = {}
        self._rule_fates()

    def _warn(self, code: str, message: str, block_ids: Iterable[str] = ()) -> None:
        """Предупреждение по контракту v1: ``{code, message, stage, block_ids}``; повтор не дублируется."""
        item = _Warning(code=code, message=message, stage=STAGE, block_ids=list(dict.fromkeys(block_ids)))
        if item not in self.warnings:
            self.warnings.append(item)

    # ------------------------------------------------------------ загрузка

    def _load_blocks(self, document: Any) -> list[_Block]:
        raw_blocks = _get(document, "blocks") or []
        blocks: list[_Block] = []
        seen: set[str] = set()
        for raw in raw_blocks:
            bid = _get(raw, "id")
            if bid is None or str(bid) == "":
                self._warn("block_without_id", "блок без id пропущен")
                continue
            bid = str(bid)
            if bid in seen:
                self._warn("duplicate_block_id", f"повтор id блока {bid}, учтён первый", [bid])
                continue
            seen.add(bid)
            sec = _get(raw, "section") or []
            if isinstance(sec, str):
                sec = [sec]
            loc = _get(raw, "loc") or {}
            marker = _get(raw, "marker") or _get(raw, "number") or _get(loc, "marker") or _get(loc, "number")
            lst = _get(loc, "list")
            if marker in (None, "") and lst is not None and _get(lst, "ordered") and _get(lst, "number") is not None:
                marker = str(_get(lst, "number"))  # №01 выносит «1.» из текста в loc.list
            blocks.append(
                _Block(
                    idx=len(blocks),
                    id=bid,
                    kind=str(_get(raw, "kind") or "").lower(),
                    section=tuple(str(s) for s in sec),
                    text=str(_get(raw, "text") or ""),
                    marker=str(marker) if marker not in (None, "") else None,
                    loc=loc,
                )
            )
        if not blocks:
            self._warn("empty_document", "в документе нет блоков")
        return blocks

    # ------------------------------------------------------------ разделы

    def role(self, section: tuple[str, ...]) -> str | None:
        if section in self._role_cache:
            return self._role_cache[section]
        api = any(pat.search(_kw(h)) for h in section for name, pat in _ROLE_PATTERNS if name == "contract")
        found: str | None = None
        for heading in reversed(section):
            h = _kw(heading)
            for name, pat in _ROLE_PATTERNS:
                if pat.search(h):
                    found = name
                    break
            if found is None and api and _WEAK_CONTRACT_RE.search(h):
                found = "contract"
            if found:
                break
        self._role_cache[section] = found
        return found

    def kind_for(self, section: tuple[str, ...]) -> str:
        for i in range(len(section), 0, -1):
            r = self.role(section[:i])
            if r in _ROLE_KIND:
                return _ROLE_KIND[r]
            if r not in (None, "requirements"):
                break
        return "functional"

    def has_children(self, section: tuple[str, ...]) -> bool:
        n = len(section)
        return any(len(s) > n and s[:n] == section for s in self.section_set)

    def heading_label(self, section: tuple[str, ...]) -> str | None:
        return _heading_label(section[-1]) if section else None

    @staticmethod
    def is_heading(b: _Block) -> bool:
        return b.kind.startswith(("heading", "title", "header", "h1", "h2", "h3", "h4", "h5", "h6")) and (
            "table" not in b.kind
        )

    @staticmethod
    def is_code(b: _Block) -> bool:
        return b.kind in ("code", "pre", "code_block", "listing", "fence") or b.text.lstrip().startswith("```")

    # ------------------------------------------------------------ таблицы

    def _table_rows(self, b: _Block) -> list[_Row] | None:
        kind = b.kind
        if "cell" in kind or kind in ("td", "th"):
            a, e = _trim(b.text, 0, len(b.text))
            return [_Row([_Cell(b.id, a, e, b.text[a:e])], b.id, 0)]
        spans = [(s, e) for s, e in _lines(b.text) if b.text[s:e].strip()]
        if not spans:
            return None
        piped = all(_PIPE_ROW_RE.match(b.text[s:e]) for s, e in spans)
        tableish = "table" in kind or kind in ("row", "tr")
        if not piped and not tableish:
            return None
        rows = []
        for n, (s, e) in enumerate(spans):
            line = b.text[s:e]
            if "|" in line:
                cells = _split_pipe_row(line, s, b.id)
            elif "\t" in line:
                cells = []
                pos = 0
                for part in line.split("\t"):
                    a, z = _trim(line, pos, pos + len(part))
                    cells.append(_Cell(b.id, s + a, s + z, line[a:z]))
                    pos += len(part) + 1
            else:
                a, z = _trim(line, 0, len(line))
                cells = [_Cell(b.id, s + a, s + z, line[a:z])]
            sep = bool(cells) and all(_SEP_CELL_RE.match(c.text.replace(" ", "")) for c in cells if c.text) and any(
                c.text for c in cells
            )
            rows.append(_Row(cells, b.id, n, separator=sep))
        return rows

    def _group_tables(self) -> None:
        cur: _Table | None = None
        cur_table_key: Any = None
        prev_idx = -2
        cell_key: tuple[Any, Any] | None = None
        for b in self.blocks:
            rows = self._table_rows(b)
            if rows is None:
                cur = None
                continue
            is_cell = "cell" in b.kind or b.kind in ("td", "th")
            row_key = self._cell_row_key(b) if is_cell else None
            table_key = row_key[0] if row_key else None
            if (cur is None or b.idx != prev_idx + 1 or b.section != cur.section
                    or (is_cell and table_key is not None and table_key != cur_table_key)):
                cur = _Table(section=b.section)
                self.tables.append(cur)
                cell_key = None
                cur_table_key = table_key
            if is_cell and cur.rows and row_key is not None and row_key == cell_key:
                # ячейки DOCX одной строки (loc.row) собираются в одну строку таблицы
                cur.rows[-1].cells.extend(rows[0].cells)
                rows = [cur.rows[-1]]
            else:
                cur.rows.extend(rows)
            cell_key = row_key
            self.row_of.setdefault(b.id, []).extend(rows)
            prev_idx = b.idx
        for t in self.tables:
            head = t.header
            if head is not None and len({c.block_id for c in head.cells}) == 1:
                hb = head.cells[0].block_id if head.cells else head.block_id
                for r in t.data:
                    for c in r.cells:
                        if c.block_id != hb:
                            self.header_block.setdefault(c.block_id, hb)

    @staticmethod
    def _cell_row_key(b: _Block) -> tuple[Any, Any] | None:
        loc = b.loc or {}
        row = _get(loc, "row", _get(loc, "r"))
        if row is None:
            return None
        return (_get(loc, "table", _get(loc, "t")), row)

    def table_of(self, block_id: str) -> _Table | None:
        for t in self.tables:
            for r in t.rows:
                if any(c.block_id == block_id for c in r.cells) or r.block_id == block_id:
                    return t
        return None

    def segments_of(self, b: _Block) -> list[_Segment]:
        """Сегменты блока; номер списка из loc (``marker``) достаётся первому сегменту без своего номера."""
        segs = _segments(b.text)
        if b.marker and segs and segs[0].label is None:
            segs[0] = _Segment(b.marker, segs[0].start, segs[0].end)
        return segs

    def _collect_labels(self) -> None:
        for b in self.blocks:
            if self.is_heading(b) or b.id in self.row_of:
                continue
            for seg in self.segments_of(b):
                if seg.label:
                    self.labels.setdefault(b.id, []).append((seg.start, seg.end, seg.label))
        for t in self.tables:
            head = t.header
            id_col = self._col([c.text for c in head.cells], _ID_COL_RE) if head else None
            for r in t.data:
                lab = None
                if id_col is not None and id_col < len(r.cells):
                    lab = _clean(r.cells[id_col].text) or None
                elif r.cells:
                    first = _clean(r.cells[0].text)
                    if re.fullmatch(r"[A-Za-zА-Яа-яЁё]{1,10}(?:[-_.][A-Za-zА-Яа-яЁё]{1,10})*[-_.]?\d+(?:[.\-]\d+)*", first):
                        lab = first
                if lab:
                    for c in r.cells:
                        self.labels.setdefault(c.block_id, []).append((c.start, c.end, lab))

    def _continuations(self) -> dict[str, tuple[str, str]]:
        """Блок без номера сразу за пронумерованным абзацем того же раздела — продолжение этого пункта.

        Только прямое соседство (без цепочек): так «следующей строкой» уточнение или исключение остаётся
        при своём пункте, даже если стык окон прошёл между ними, а заключительный абзац раздела
        не прилипает к последнему пункту. Код, таблицы и заголовки не наследуют номер.
        """
        out: dict[str, tuple[str, str]] = {}
        for prev, b in zip(self.blocks, self.blocks[1:]):
            if b.section != prev.section or b.id in self.labels or not b.text.strip():
                continue
            if any(self.is_heading(x) or self.is_code(x) or x.id in self.row_of for x in (prev, b)):
                continue
            labels = self.labels.get(prev.id)
            if labels:
                out[b.id] = (labels[-1][2], prev.id)
        return out

    @staticmethod
    def _col(header: list[str], pat: re.Pattern[str]) -> int | None:
        for i, h in enumerate(header):
            if pat.search(_kw(h)):
                return i
        return None

    def row_index(self, block_id: str, offset: int) -> int:
        rows = self.row_of.get(block_id)
        if not rows:
            return 0
        for r in rows:
            if r.cells and r.cells[0].start <= offset <= r.cells[-1].end:
                return r.line
        return 0

    # ------------------------------------------------------------ правила

    def _excl(self, category: str, reason: str | None = None) -> _Fate:
        return _Fate(excl=(category, reason or EXCLUSION_CATEGORIES[category][0]))

    def _hint(self, block_id: str, start: int, end: int) -> _Hint:
        text = self.by_id[block_id].text
        return _Hint(block_id, start, end, text[start:end])

    def _rule_fates(self) -> None:
        for t in self.tables:
            self._rule_table(t)
        for b in self.blocks:
            if b.id in self.fates:
                continue
            self.fates[b.id] = self._rule_prose(b)

    def _section_name(self, section: tuple[str, ...]) -> str:
        return section[-1] if section else "без раздела"

    def _rule_prose(self, b: _Block) -> _Fate:
        text = b.text
        if self.is_heading(b):
            return self._excl("structure", "Заголовок раздела: задаёт путь section для вложенных блоков.")
        if not text.strip():
            return self._excl("empty")
        if _HR_RE.match(text):
            return self._excl("structure", "Горизонтальный разделитель.")
        role = self.role(b.section)
        name = self._section_name(b.section)
        if role == "approval":
            return self._excl("approval", f"Раздел «{name}»: блок согласования, а не требование к продукту.")
        if role == "review_checklist":
            return self._excl("review_checklist", f"Раздел «{name}»: служебная часть шаблона ревью, а не требование к продукту.")
        if _PLACEHOLDER_RE.match(_clean(text)):
            return self._excl("placeholder", f"Раздел «{name}»: заглушка вместо содержания.")
        if self.is_code(b):
            body = text.strip().strip("`").strip()
            if body[:1] in "{[" or re.search(r"\bcurl\b|^(?:GET|POST|PUT|PATCH|DELETE)\s+/", body, re.M):
                return self._excl("example", f"Раздел «{name}»: пример запроса или ответа, опора для сверки с контрактом.")
            if role == "design" or _ARROW_RE.search(body):
                return _Fate(unprocessed=f"Раздел «{name}»: схема в блоке кода; обязательства выделяет семантический этап.")
            return _Fate(unprocessed=f"Раздел «{name}»: блок кода без явного назначения.")
        if role in ("metadata", "goal", "glossary"):
            return self._excl(role)
        if role in ("design", "testing"):
            return _Fate(
                unprocessed=f"Раздел «{name}» ({role}): описание без явного номера; обязательства выделяет семантический этап."
            )
        if _CONNECTOR_RE.match(_clean(text)):
            return self._excl("fragment", f"Раздел «{name}»: служебная связка «{_clean(text)}».")
        segs = self.segments_of(b)
        labeled = any(s.label for s in segs)
        modal = bool(_MODAL_RE.search(text))
        parent = self.parent_label.get(b.id)
        if parent and not labeled and self.fates.get(parent[1]) and self.fates[parent[1]].atoms:
            atoms = self._prose_atoms(b, segs, role, inherited=parent[0])
            if atoms:
                return _Fate(atoms=atoms, facts=self._text_facts_for(atoms))
        if labeled or role in _REQ_ROLES or modal:
            if not labeled and role != "acceptance" and not modal and self.has_children(b.section):
                return self._excl("preamble", f"Раздел «{name}»: вводный текст перед подразделами.")
            atoms = self._prose_atoms(b, segs, role)
            if atoms:
                return _Fate(atoms=atoms, facts=self._text_facts_for(atoms))
            return self._excl("fragment", f"Раздел «{name}»: номер без содержательного текста.")
        if self.has_children(b.section):
            return self._excl("preamble", f"Раздел «{name}»: вводный или описательный текст без обязательства.")
        return _Fate(unprocessed=f"Раздел «{name}»: нет номера, модальности и признаков раздела требований; "
                                 "решение за семантическим этапом.")

    def _prose_atoms(self, b: _Block, segs: list[_Segment], role: str | None,
                     inherited: str | None = None) -> list[_Atom]:
        kind = self.kind_for(b.section)
        no_split = role == "acceptance"
        heading = self._section_name(b.section)
        head_label = self.heading_label(b.section)
        atoms = []
        for seg in segs:
            spans = [_trim(b.text, seg.start, seg.end)] if no_split else _sentences(b.text, seg.start, seg.end)
            for a, z in spans:
                cleaned = _clean(b.text[a:z])
                if not _LETTER_RE.search(cleaned):
                    continue
                if len(cleaned.split()) < 4 and not seg.label:
                    cleaned = f"{_clean(heading)}: {cleaned}"
                if seg.label or inherited:
                    sid, src = seg.label or inherited, "label"
                else:
                    sid, src = (head_label, "heading") if head_label else (None, None)
                atoms.append(_Atom(kind, cleaned, sid, [self._hint(b.id, a, z)], "rules", src))
        return atoms

    def _classify_table(self, t: _Table) -> str:
        head = t.header
        H = [_kw(c.text) for c in head.cells] if head else []
        Hj = " | ".join(H)
        role = self.role(t.section)
        data_vals = [[_kw(c.text) for c in r.cells] for r in t.data]
        options = sum(1 for r in data_vals for v in r if _OPTION_RE.match(v))
        if role == "approval" or (H and _APPROVAL_HEAD_RE.search(Hj)):
            return "approval"
        if role == "review_checklist" or (data_vals and options >= max(1, len(data_vals) // 2)):
            return "review_checklist"
        if role in ("metadata", "goal", "glossary"):
            return role
        if H and sum(1 for h in H if _META_HEAD_RE.match(h)) >= max(2, (len(H) + 1) // 2):
            return "metadata"
        if H and _GLOSS_HEAD_RE.search(Hj):
            return "glossary"
        if role == "acceptance" or (H and _ACC_GIVEN_RE.search(Hj) and _ACC_THEN_RE.search(Hj)):
            return "acceptance"
        if H and self._col(H, _NAME_COL_RE) is not None and self._col(H, _TYPE_COL_RE) is not None:
            return "params"
        if len(H) == 2 and _KV_KEY_HEAD_RE.match(H[0]):
            return "keyvalue"
        if role in ("design", "testing"):
            return role
        return "generic"

    def _row_hints(self, row: _Row) -> list[_Hint]:
        cells = [c for c in row.cells if c.text.strip()]
        if not cells:
            return []
        if len({c.block_id for c in cells}) == 1:
            return [self._hint(cells[0].block_id, cells[0].start, cells[-1].end)]
        return [self._hint(c.block_id, c.start, c.end) for c in cells]

    def _row_text(self, header: list[str], row: _Row, skip: set[int] | None = None) -> str:
        parts = []
        for i, c in enumerate(row.cells):
            if skip and i in skip:
                continue
            v = _clean(c.text)
            if not v:
                continue
            h = _clean(header[i]) if i < len(header) else ""
            parts.append(f"{h}: {v}" if h else v)
        return "; ".join(parts)

    def _set_row_fate(self, row: _Row, fate: _Fate) -> None:
        for bid in {c.block_id for c in row.cells} | {row.block_id}:
            cur = self.fates.get(bid)
            if cur is None:
                self.fates[bid] = _Fate(atoms=list(fate.atoms), excl=fate.excl, unprocessed=fate.unprocessed,
                                        facts=list(fate.facts))
                continue
            cur.atoms.extend(a for a in fate.atoms if a not in cur.atoms)
            cur.facts.extend(f for f in fate.facts if f not in cur.facts)
            if cur.excl is None or (cur.excl[0] == "structure" and fate.excl):
                cur.excl = fate.excl or cur.excl
            if cur.unprocessed is None:
                cur.unprocessed = fate.unprocessed

    def _rule_table(self, t: _Table) -> None:
        ttype = self._classify_table(t)
        head = t.header
        H = [c.text for c in head.cells] if head else []
        name = self._section_name(t.section)
        whole = {
            "approval": ("approval", f"Таблица «{name}»: поля подразделения, ФИО и подписи не заполнены и не являются требованиями."),
            "review_checklist": ("review_checklist", f"Таблица «{name}»: чек-лист ревью, варианты отметок не выбраны."),
            "metadata": ("metadata", f"Таблица «{name}»: метаданные документа или задачи."),
            "goal": ("goal", f"Таблица «{name}»: цели, а не обязательства."),
            "glossary": ("glossary", f"Таблица «{name}»: определения терминов."),
        }
        if ttype in whole:
            cat, reason = whole[ttype]
            if ttype == "review_checklist":
                filled = any(not _OPTION_RE.match(_kw(c.text)) and _kw(c.text) in ("да", "нет", "yes", "no", "не требуется")
                             for r in t.data for c in r.cells)
                if filled:
                    reason = f"Таблица «{name}»: заполненный чек-лист ревью — запись проверки, а не требование."
            for r in t.rows:
                if (r.separator or r is head) and ttype not in ("approval", "review_checklist"):
                    self._set_row_fate(r, self._excl("structure", f"Шапка таблицы «{name}»: названия колонок."))
                else:
                    self._set_row_fate(r, self._excl(cat, reason))
            return
        for r in t.rows:
            if r.separator:
                self._set_row_fate(r, self._excl("structure", "Разделитель шапки таблицы."))
            elif r is head:
                self._set_row_fate(r, self._excl("structure", f"Шапка таблицы «{name}»: названия колонок."))
        kind = self.kind_for(t.section)
        id_col = self._col(H, _ID_COL_RE) if H else None
        for n, r in enumerate(t.data, start=1):
            if r.empty:
                self._set_row_fate(r, self._excl("empty", f"Таблица «{name}»: пустая строка."))
                continue
            hints = self._row_hints(r)
            if ttype in ("design", "testing"):
                self._set_row_fate(r, _Fate(unprocessed=f"Таблица «{name}» ({ttype}): обязательства выделяет семантический этап."))
                continue
            sid = None
            if id_col is not None and id_col < len(r.cells):
                sid = _clean(r.cells[id_col].text) or None
            else:
                labs = self.labels.get(r.cells[0].block_id, []) if r.cells else []
                for s, e, lab in labs:
                    if r.cells and s == r.cells[0].start:
                        sid = lab
            src = "label" if sid else None
            if ttype == "acceptance":
                text = self._row_text(H, r, {id_col} if id_col is not None else None)
                self._set_row_fate(r, _Fate(atoms=[_Atom("acceptance", text, sid, hints, "rules", src)]))
            elif ttype == "params":
                fact = self._param_fact(t, H, r)
                akind = "contract" if kind == "functional" else kind
                self._set_row_fate(r, _Fate(atoms=[_Atom(akind, self._row_text(H, r), sid, hints, "rules", src)],
                                            facts=[fact] if fact else []))
            elif ttype == "keyvalue":
                key = _kw(r.cells[0].text) if r.cells else ""
                value = _kw(r.cells[1].text) if len(r.cells) > 1 else ""
                if _PLACEHOLDER_VALUE_RE.match(value):
                    fate = self._excl("placeholder", f"Таблица «{name}»: значение «{_clean(r.cells[0].text)}» не заполнено.")
                elif _EXAMPLE_KEY_RE.search(key):
                    fate = self._excl("example", f"Таблица «{name}»: пример вызова, опора для сверки с контрактом.")
                elif _CONTRACT_KEY_RE.search(key):
                    ckind = "contract" if kind in ("functional", "contract") else kind
                    fate = _Fate(atoms=[_Atom(ckind, self._row_text([], r).replace("; ", ": ", 1), sid, hints, "rules", src)])
                else:
                    fate = self._excl("metadata", f"Таблица «{name}»: описательные атрибуты (проект, роли, авторы, сводка).")
                self._set_row_fate(r, fate)
            else:
                text = self._row_text(H, r, {id_col} if id_col is not None else None)
                atom = _Atom(kind, text, sid, hints, "rules", src)
                self._set_row_fate(r, _Fate(atoms=[atom], facts=self._text_facts_for([atom])))

    # ------------------------------------------------------------ факты по правилам

    def _direction(self, section: tuple[str, ...]) -> str | None:
        for h in reversed(section):
            k = _kw(h)
            if _DIR_RESPONSE_RE.search(k):
                return "response"
            if _DIR_REQUEST_RE.search(k):
                return "request"
        return None if self.kind_for(section) == "contract" else "business"

    def _param_fact(self, t: _Table, H: list[str], r: _Row) -> _Fact | None:
        def cell(pat: re.Pattern[str]) -> _Cell | None:
            i = self._col(H, pat)
            return r.cells[i] if i is not None and i < len(r.cells) else None

        name_c, type_c, size_c = cell(_NAME_COL_RE), cell(_TYPE_COL_RE), cell(_SIZE_COL_RE)
        req_c, logic_c, desc_c, db_c = cell(_REQ_COL_RE), cell(_LOGIC_COL_RE), cell(_DESC_COL_RE), cell(_DB_COL_RE)
        if name_c is None or not _clean(name_c.text):
            return None
        req = None
        if req_c is not None:
            v = _kw(req_c.text)
            if re.match(r"^(?:да|yes|y|\+|обязат\w*|required|mandatory|true|m)$", v):
                req = True
            elif re.match(r"^(?:нет|no|n|-|опционал\w*|optional|false|o)$", v):
                req = False
        rng, values, condition, unit = self._parse_logic(_clean(logic_c.text) if logic_c else "")
        if desc_c is not None:
            m = _UNIT_PHRASE_RE.search(desc_c.text)
            if m:
                unit = _canon_unit(m.group("u")) or unit
        db = _clean(db_c.text) if db_c else None
        hints = [self._hint(c.block_id, c.start, c.end) for c in (name_c, type_c, logic_c, desc_c) if c and c.text.strip()]
        return _Fact(
            hints=hints,
            origin="rules",
            field=_clean(name_c.text),
            direction=self._direction(t.section),
            type=(_clean(type_c.text).lower() or None) if type_c else None,
            unit=unit,
            range=rng,
            condition=condition,
            required=req,
            size=(_clean(size_c.text) or None) if size_c else None,
            values=values,
            db_field=None if db is None or _PLACEHOLDER_VALUE_RE.match(db) else db,
        )

    @staticmethod
    def _parse_logic(logic: str) -> tuple[dict[str, Any] | None, list[str] | None, str | None, str | None]:
        """Колонка Logic: диапазон, перечень допустимых значений или условие (что не распознано)."""
        if not logic:
            return None, None, None, None
        m = _RANGE_DASH_RE.match(logic) or _RANGE_TEXT_RE.search(logic)
        if m:
            gd = m.groupdict()
            incl = True if gd.get("incl") else None
            unit = _canon_unit(gd.get("u") or gd.get("u2") or gd.get("u1"))
            return ({"min": _parse_num(m.group("min")), "max": _parse_num(m.group("max")),
                     "min_inclusive": incl, "max_inclusive": incl}, None, None, unit)
        parts = [p.strip(" «»\"'") for p in re.split(r"\s*(?:/|,|\bили\b|\bor\b|\|)\s*", logic) if p.strip(" «»\"'")]
        if 2 <= len(parts) <= 8 and all(len(p) <= 16 for p in parts):
            return None, parts, None, None
        return None, None, logic, None

    def _text_facts_for(self, atoms: Iterable[_Atom]) -> list[_Fact]:
        facts: list[_Fact] = []
        for a in atoms:
            for h in a.hints:
                b = self.by_id[h.block_id]
                facts.extend(self._text_facts(b, h.start, h.end))
        return facts

    def _text_facts(self, b: _Block, start: int, end: int) -> list[_Fact]:
        text = b.text
        seg = text[start:end]
        direction = self._direction(b.section)
        out: list[_Fact] = []

        def hint(m: re.Match[str]) -> list[_Hint]:
            return [self._hint(b.id, start + m.start(), start + m.end())]

        for m in _RANGE_TEXT_RE.finditer(seg):
            incl = True if m.group("incl") else None
            out.append(_Fact(hint(m), "rules", direction=direction, unit=_canon_unit(m.group("u2") or m.group("u1")),
                             range={"min": _parse_num(m.group("min")), "max": _parse_num(m.group("max")),
                                    "min_inclusive": incl, "max_inclusive": incl}))
        for m in _BOUND_RE.finditer(seg):
            op = m.group("op").lower()
            is_max = op.startswith(("не более", "не больше", "не превыш", "максимум", "не позднее"))
            rng = {"min": None, "max": None, "min_inclusive": None, "max_inclusive": None}
            rng["max" if is_max else "min"] = _parse_num(m.group("num"))
            rng["max_inclusive" if is_max else "min_inclusive"] = True
            out.append(_Fact(hint(m), "rules", direction=direction, unit=_canon_unit(m.group("u")), range=rng))
        for m in _WITHIN_RE.finditer(seg):
            out.append(_Fact(hint(m), "rules", direction=direction, type="duration", unit=_canon_unit(m.group("u")),
                             range={"min": None, "max": _parse_num(m.group("num")), "min_inclusive": None,
                                    "max_inclusive": None}))
        for m in _INCL_RE.finditer(seg):
            out.append(_Fact(hint(m), "rules", direction=direction,
                             range={"min": None, "max": None, "min_inclusive": True, "max_inclusive": True}))
        for m in _INTEGER_RE.finditer(seg):
            w1, w2 = m.group("w1"), m.group("w2")
            if w1.lower() in ("число", "числом", "числа"):
                out.append(_Fact(hint(m), "rules", direction=direction, type="integer", unit=_canon_unit(w2)))
            elif _canon_unit(w1):
                out.append(_Fact(hint(m), "rules", direction=direction, type="integer", unit=_canon_unit(w1)))
            else:
                out.append(_Fact(hint(m), "rules", direction=direction, type="integer", field=w1.lower()))
        for m in _UNIT_PHRASE_RE.finditer(seg):
            fld = re.split(r"\s+(?:и|или|а|либо)\s+", m.group("field"))[-1].strip().lower()
            out.append(_Fact(hint(m), "rules", direction=direction, field=fld, unit=_canon_unit(m.group("u"))))
        for m in _DEFAULT_RE.finditer(seg):
            out.append(_Fact(hint(m), "rules", direction=direction, field=m.group("field").lower(),
                             value=m.group("value").lower(), condition="по умолчанию"))
        return out

    # ------------------------------------------------------------ проверка ответа модели

    def _resolve_hint(self, ev: Any, window: list[str], forbidden: set[str]) -> _Hint | None:
        hint = self._resolve_hint_inner(ev, window, forbidden)
        if hint is not None and self.by_id[hint.block_id].text.count(hint.quote) > 1:
            self.stats.hints_ambiguous += 1
        return hint

    def _resolve_hint_inner(self, ev: Any, window: list[str], forbidden: set[str]) -> _Hint | None:
        st = self.stats
        st.hints_checked += 1
        if not isinstance(ev, Mapping):
            st.hints_rejected += 1
            return None
        bid = str(ev.get("block_id") or "")
        quote = ev.get("quote")
        if not isinstance(quote, str) or not quote.strip():
            st.hints_empty += 1
            st.hints_rejected += 1
            self._warn("empty_quote", f"пустая цитата у блока {bid or '?'} отклонена", [bid] if bid in self.by_id else [])
            return None
        if bid in self.by_id and bid not in forbidden:
            found = _locate(quote, self.by_id[bid].text)
            if found:
                s, e, how = found
                if how == "exact":
                    st.hints_exact += 1
                else:
                    st.hints_repaired += 1
                    self._warn("quote_normalized", f"цитата в {bid} заменена дословным фрагментом источника", [bid])
                return self._hint(bid, s, e)
        # поиск в других блоках окна: сначала обрабатываемые, затем контекст
        for other in window:
            if other == bid or other in forbidden:
                continue
            found = _locate(quote, self.by_id[other].text)
            if found:
                st.hints_repaired += 1
                why = "неизвестный блок" if bid not in self.by_id else (
                    "блок шаблона/структуры" if bid in forbidden else "цитата не из этого блока")
                self._warn("hint_relocated", f"{why} «{bid}» → цитата найдена в {other}", [other])
                return self._hint(other, found[0], found[1])
        st.hints_rejected += 1
        if bid in forbidden:
            self._warn("hint_rejected", f"опора в блоке {bid} (структура или шаблон согласования/ревью) не подтверждает требование", [bid])
        elif bid not in self.by_id:
            self._warn("hint_rejected", f"неизвестный блок «{bid}», цитата не найдена в документе")
        else:
            self._warn("hint_rejected", f"цитата не найдена в блоке {bid}: «{quote.strip()[:60]}»", [bid])
        return None

    def _check_source_id(self, sid: Any, hints: list[_Hint]) -> tuple[str | None, str | None]:
        """Номер пункта принимается, только если он виден в опорах; иначе берётся из ярлыка или заголовка."""
        anchor = hints[0]
        b = self.by_id[anchor.block_id]
        given = _none_if_empty(sid)
        if given is not None:
            s = _norm_label(sid)
            for h in hints:
                hb = self.by_id[h.block_id]
                for _, _, lab in self.labels.get(hb.id, []):
                    if _norm_label(lab) == s:
                        return lab, "label"
                if hb.marker and _norm_label(hb.marker) == s:
                    return hb.marker, "label"
                parent = self.parent_label.get(hb.id)
                if parent and _norm_label(parent[0]) == s:
                    return parent[0], "label"  # продолжение пункта: номер стоит в предыдущем блоке
                hl = self.heading_label(hb.section)
                if hl and _norm_label(hl) == s:
                    return hl, "heading"
                if not s.isdigit() and s and re.search(rf"(?<![\w]){re.escape(s)}(?![\w])", _norm_label_text(hb.text)):
                    return str(sid).strip(), "text"
            self.stats.source_ids_cleared += 1
        # номер из ярлыка сегмента, в котором лежит первая опора, иначе из ближайшего заголовка
        filled: tuple[str | None, str | None] = (None, None)
        for s, e, lab in self.labels.get(b.id, []):
            if s <= anchor.start <= max(e, s):
                filled = (lab, "label")
                break
        else:
            if b.marker:
                filled = (b.marker, "label")
            elif b.id in self.parent_label:
                filled = (self.parent_label[b.id][0], "label")
            elif self.heading_label(b.section):
                filled = (self.heading_label(b.section), "heading")
        if filled[0] is not None:
            self.stats.source_ids_filled += 1
        if given is not None:
            self._warn("source_id_cleared",
                       f"номер «{given}» не найден в опорах ({anchor.block_id}); "
                       + (f"взят номер из текста «{filled[0]}»" if filled[0] else "оставлен null"),
                       [anchor.block_id])
        return filled

    def _accept(self, resp: Any, core: list[str], context: list[str], origin: str) -> tuple[
        list[_Atom], list[tuple[str, str, list[str]]], list[_Fact], set[str], bool]:
        """Проверяет ответ модели. Возвращает атомы, группы исключений, факты, покрытые блоки, признак обрезки."""
        truncated = _is_truncated(resp)
        if not isinstance(resp, Mapping):
            self._warn("bad_response", f"ответ модели не объект JSON ({type(resp).__name__})")
            return [], [], [], set(), True
        window = list(core) + [c for c in context if c not in core]
        core_set = set(core)
        forbidden = {bid for bid, f in self.fates.items() if self._is_hard(f)}
        atoms: list[_Atom] = []
        items = resp.get("items")
        for n, it in enumerate(items if isinstance(items, list) else []):
            if not isinstance(it, Mapping):
                self.stats.items_rejected += 1
                continue
            evs = it.get("evidence")
            if evs is None:
                evs = it.get("hints")
            hints: list[_Hint] = []
            for ev in evs if isinstance(evs, list) else []:
                h = self._resolve_hint(ev, window, forbidden)
                if h and not any(x.block_id == h.block_id and x.start == h.start and x.end == h.end for x in hints):
                    hints.append(h)
            if not hints:
                self.stats.items_rejected += 1
                claimed = [str(ev.get("block_id")) for ev in (evs if isinstance(evs, list) else [])
                           if isinstance(ev, Mapping) and str(ev.get("block_id")) in self.by_id]
                self._warn("item_rejected",
                           f"пункт без подтверждённой цитаты отброшен: «{_clean(str(it.get('text') or ''))[:60]}»", claimed)
                continue
            hints.sort(key=lambda h: (self.by_id[h.block_id].idx, h.start, h.end))
            anchor_core = [h for h in hints if h.block_id in core_set]
            if anchor_core:
                first = anchor_core[0]
                hints.remove(first)
                hints.insert(0, first)
            kind = it.get("kind")
            if kind not in KINDS:
                kind = self.kind_for(self.by_id[hints[0].block_id].section)
                self._warn("kind_fixed", f"неизвестный вид «{it.get('kind')}» заменён на {kind}", [hints[0].block_id])
            text = _clean(str(it.get("text") or "")) or _clean(hints[0].quote)
            sid, src = self._check_source_id(it.get("source_id"), hints)
            atoms.append(_Atom(kind, text, sid, hints, origin, src, context_anchor=not anchor_core))
        groups: list[tuple[str, str, list[str]]] = []
        excluded = resp.get("excluded")
        for g in excluded if isinstance(excluded, list) else []:
            if not isinstance(g, Mapping):
                continue
            cat = g.get("category") if g.get("category") in EXCLUSION_CATEGORIES else "other"
            reason = _clean(str(g.get("reason") or "")) or EXCLUSION_CATEGORIES[cat][0]
            ids = []
            for bid in g.get("block_ids") or []:
                bid = str(bid)
                if bid not in self.by_id:
                    self.stats.excluded_unknown_ids += 1
                    self._warn("excluded_unknown_block", f"группа «{cat}» ссылается на неизвестный блок «{bid}»")
                elif bid in core_set and bid not in ids:
                    ids.append(bid)
            if ids:
                groups.append((cat, reason, ids))
        facts: list[_Fact] = []
        raw_facts = resp.get("facts")
        for f in raw_facts if isinstance(raw_facts, list) else []:
            fact = self._accept_fact(f, window, forbidden, origin)
            if fact:
                facts.append(fact)
        covered = {h.block_id for a in atoms for h in a.hints if not a.context_anchor} | {
            bid for _, _, ids in groups for bid in ids}
        return atoms, groups, facts, covered & core_set, truncated

    def _accept_fact(self, f: Any, window: list[str], forbidden: set[str], origin: str) -> _Fact | None:
        if not isinstance(f, Mapping):
            self.stats.facts_rejected += 1
            return None
        evs = f.get("evidence") if f.get("evidence") is not None else f.get("hints")
        hints = [h for h in (self._resolve_hint(ev, window, forbidden) for ev in (evs if isinstance(evs, list) else []))
                 if h]
        if not hints:
            self.stats.facts_rejected += 1
            return None
        rng = f.get("range")
        rng_out = None
        if isinstance(rng, Mapping):
            rng_out = {
                "min": _num_or_none(rng.get("min")),
                "max": _num_or_none(rng.get("max")),
                "min_inclusive": rng.get("min_inclusive") if isinstance(rng.get("min_inclusive"), bool) else None,
                "max_inclusive": rng.get("max_inclusive") if isinstance(rng.get("max_inclusive"), bool) else None,
            }
            if all(v is None for v in rng_out.values()):
                rng_out = None
        direction = _none_if_empty(f.get("direction"))
        values = f.get("values")
        return _Fact(
            hints=hints,
            origin=origin,
            subject=_none_if_empty(f.get("subject")),
            field=_none_if_empty(f.get("field")),
            direction=direction if direction in ("request", "response", "business") else None,
            type=_none_if_empty(f.get("type")),
            value=_none_if_empty(f.get("value")),
            unit=_canon_unit(_none_if_empty(f.get("unit"))) or _none_if_empty(f.get("unit")),
            range=rng_out,
            condition=_none_if_empty(f.get("condition")),
            required=f.get("required") if isinstance(f.get("required"), bool) else None,
            values=[str(v) for v in values if _none_if_empty(v) is not None] or None if isinstance(values, list) else None,
        )

    @staticmethod
    def _is_hard(f: _Fate) -> bool:
        return not f.atoms and f.excl is not None and f.excl[0] in HARD_CATEGORIES

    # ------------------------------------------------------------ окна и вызовы модели

    def _block_payload(self, b: _Block, process: bool, attach_text: bool) -> dict[str, Any]:
        labels = self.labels.get(b.id, [])
        item: dict[str, Any] = {
            "id": b.id,
            "section": " › ".join(b.section),
            "kind": b.kind or None,
            "label": labels[0][2] if labels else b.marker,
            "process": process,
        }
        if attach_text:
            item["text"] = b.text
        return item

    def _plan(self, blocks: list[_Block], limit: int, overlap: int) -> list[tuple[list[str], list[str]]]:
        sizes = [len(b.text) + sum(len(s) for s in b.section) + 48 for b in blocks]
        chunks: list[list[_Block]] = []
        cur: list[_Block] = []
        size = 0
        for b, sz in zip(blocks, sizes):
            if cur and size + sz > limit:
                chunks.append(cur)
                cur, size = [], 0
            cur.append(b)
            size += sz
        if cur:
            chunks.append(cur)
        plan = []
        for i, chunk in enumerate(chunks):
            core = [b.id for b in chunk]
            ctx: list[str] = []
            if overlap > 0 and len(chunks) > 1:
                before = chunks[i - 1][-overlap:] if i > 0 else []
                after = chunks[i + 1][:overlap] if i + 1 < len(chunks) else []
                ctx = [b.id for b in before + after]
            for bid in core:
                hb = self.header_block.get(bid)
                if hb and hb not in core and hb not in ctx:
                    ctx.append(hb)
            plan.append((core, ctx))
        return plan

    def payload(self, core: list[str], context: list[str], index: int, count: int, mode: str, *,
                full: bool, attach_text: bool) -> dict[str, Any]:
        """Payload ``{task, input, context}`` по contracts/HANDOFF.md.

        Текст прикладывает движок: короткий документ целиком (``full`` — обе части спецификации),
        окно большого — по ``block_ids``. С ``attach_text`` текст блоков кладётся в input, а контекст
        движка не нужен (``mode: none``): так payload самодостаточен для ручного прогона промпта.
        """
        ids = set(core) | set(context)
        core_set = set(core)
        listed = [b for b in self.blocks if b.id in ids]
        if attach_text:
            ctx: dict[str, Any] = {"mode": "none"}
        elif full:
            ctx = {"mode": "full"}
        else:
            ctx = {"mode": "blocks", "block_ids": [b.id for b in listed]}
        return {
            "task": PROMPT,
            "input": {
                "document": {"id": self.doc_id, "title": self.title},
                "window": {"index": index, "count": count, "mode": mode, "process_block_ids": list(core)},
                "blocks": [self._block_payload(b, b.id in core_set, attach_text) for b in listed],
            },
            "context": ctx,
        }

    # ------------------------------------------------------------ сборка результата

    def run(self, ask: Callable[..., Any] | None, *, window_chars: int, overlap_blocks: int,
            max_calls: int | None, retry: bool, fallback: bool, attach_text: bool) -> dict[str, Any]:
        calls = {"used": 0, "budget": 0, "windows": 0, "retry_calls": 0, "failed": 0, "truncated": 0}
        model_missed: list[str] = []
        fallback_blocks: list[str] = []
        if ask is None:
            atoms = [a for b in self.blocks for a in self.fates[b.id].atoms]
            atoms = _unique(atoms)
            groups = [(f.excl[0], f.excl[1], [bid]) for bid, f in self._ordered_fates() if f.excl and not f.atoms]
            unproc = {bid: f.unprocessed for bid, f in self._ordered_fates() if f.unprocessed and not f.atoms
                      and not f.excl}
            facts = _unique([x for b in self.blocks for x in self.fates[b.id].facts])
            mode, llm_status = "rules_only", "not_used"
        else:
            (atoms, groups, unproc, facts, llm_status, model_missed, fallback_blocks) = self._run_llm(
                ask, calls, window_chars, overlap_blocks, max_calls, retry, fallback, attach_text)
            mode = "rules_plus_llm" if calls["used"] > calls["failed"] else "rules_only"
        return self._finalize(atoms, groups, unproc, facts, mode, llm_status, calls, model_missed, fallback_blocks)

    def _ordered_fates(self) -> list[tuple[str, _Fate]]:
        return [(b.id, self.fates[b.id]) for b in self.blocks]

    def _run_llm(self, ask: Callable[..., Any], calls: dict[str, int], window_chars: int, overlap: int,
                 max_calls: int | None, retry: bool, fallback: bool, attach_text: bool):
        hard = [(bid, f) for bid, f in self._ordered_fates() if self._is_hard(f)]
        hard_ids = {bid for bid, _ in hard}
        groups: list[tuple[str, str, list[str]]] = [(f.excl[0], f.excl[1], [bid]) for bid, f in hard]
        process = [b for b in self.blocks if b.id not in hard_ids]
        plan = self._plan(process, max(1, window_chars), overlap)
        full = len(plan) == 1  # короткий вход: обе части спецификации в контексте, и в повторе тоже
        stop = {"budget": False}
        calls["windows"] = len(plan)
        budget = max_calls if max_calls is not None else max(2, 2 * len(plan))
        calls["budget"] = budget
        atoms: list[_Atom] = []
        facts: list[_Fact] = []
        covered: set[str] = set()

        def call(core: list[str], ctx: list[str], index: int, count: int, mode: str, origin: str) -> None:
            if calls["used"] >= budget or stop["budget"]:
                return
            calls["used"] += 1
            payload = self.payload(core, ctx, index, count, mode, full=full, attach_text=attach_text)
            try:
                resp = ask(STAGE, payload, RESPONSE_SCHEMA)
            except Exception as exc:  # noqa: BLE001 - AskError, ProviderError и прочее фиксируются и учитываются
                calls["failed"] += 1
                if type(exc).__name__ == "BudgetExhausted" or getattr(exc, "kind", None) == "budget_exhausted":
                    stop["budget"] = True
                if getattr(exc, "kind", None) == "truncated":
                    calls["truncated"] += 1
                self._warn("llm_call_failed", f"окно {index + 1}/{count} ({mode}): {type(exc).__name__}: {str(exc)[:200]}", core)
                return
            a, g, f, cov, truncated = self._accept(resp, core, ctx, origin)
            if truncated:
                calls["truncated"] += 1
                self._warn("llm_truncated",
                           f"ответ по окну {index + 1}/{count} ({mode}) обрезан или без done=true; "
                           f"принято {len(a)} пунктов, непокрытые блоки уйдут в повтор",
                           [bid for bid in core if bid not in cov])
            atoms.extend(a)
            facts.extend(f)
            groups.extend(g)
            covered.update(cov)

        for i, (core, ctx) in enumerate(plan):
            if calls["used"] >= budget or stop["budget"]:
                self._warn("llm_budget", f"бюджет {budget} вызовов исчерпан до окна {i + 1}/{len(plan)}")
                break
            call(core, ctx, i, len(plan), "full", "llm")
        atoms[:] = self._link_windows(atoms)
        process_ids = {b.id for b in process}
        covered.update(h.block_id for a in atoms for h in a.hints[:1] if h.block_id in process_ids)
        pending = [b for b in process if b.id not in covered]
        if pending and retry and calls["used"] < budget and not stop["budget"]:
            rplan = self._plan(pending, max(1, window_chars // 2), 0)
            for i, (core, ctx) in enumerate(rplan):
                if calls["used"] >= budget or stop["budget"]:
                    self._warn("llm_budget", f"на повтор не хватило бюджета ({budget}) для части {i + 1}/{len(rplan)}")
                    break
                calls["retry_calls"] += 1
                call(core, ctx, i, len(rplan), "retry", "llm_retry")
        elif pending and retry:
            why = ("движок сообщил BudgetExhausted" if stop["budget"]
                   else f"бюджет модуля исчерпан ({calls['used']} из {budget})")
            self._warn("llm_budget", f"повтор не выполнен — {why}", [b.id for b in pending])
        atoms = self._link_windows(atoms)
        missed = [b.id for b in process if b.id not in covered]
        unproc: dict[str, str] = {}
        fallback_blocks: list[str] = []
        copied: set[int] = set()
        for bid in missed:
            f = self.fates[bid]
            if fallback and (f.atoms or f.excl):
                fallback_blocks.append(bid)
                for a in f.atoms:
                    if id(a) in copied:
                        continue
                    copied.add(id(a))
                    atoms.append(_Atom(a.kind, a.text, a.source_id, list(a.hints), "rules_fallback", a.sid_src))
                if f.excl and not f.atoms:
                    groups.append((f.excl[0], f.excl[1] + " (по правилам: модель блок не учла)", [bid]))
            else:
                unproc[bid] = f.unprocessed or "Модель не учла блок, правила не дают решения."
        if fallback_blocks:
            self._warn("rules_fallback",
                       "модель не учла блоки " + ", ".join(fallback_blocks) + "; применена нарезка по правилам",
                       fallback_blocks)
        # факты правил добавляются там, где модель факта не дала
        for bid, f in self._ordered_fates():
            for rf in f.facts:
                if not any(_overlap(rf.hints, mf.hints) for mf in facts):
                    facts.append(rf)
        if calls["used"] == 0:
            status = "failed"
        elif calls["failed"] == calls["used"]:
            status = "failed"
        elif missed or calls["failed"] or calls["truncated"]:
            status = "partial"
        else:
            status = "complete"
        return atoms, groups, unproc, facts, status, missed, fallback_blocks

    def _link_windows(self, atoms: list[_Atom]) -> list[_Atom]:
        """Связывает пересекающиеся окна по координатам: дубль из контекста соседнего окна отбрасывается."""
        core_atoms = [a for a in atoms if not a.context_anchor]
        out = list(core_atoms)
        for a in atoms:
            if not a.context_anchor:
                continue
            if any(_overlap(a.hints[:1], c.hints) for c in core_atoms):
                self.stats.context_linked += 1
                continue
            a.context_anchor = False
            out.append(a)
        return out

    def _dedupe(self, atoms: list[_Atom]) -> list[_Atom]:
        out: list[_Atom] = []
        for a in atoms:
            key = _kw(a.text)
            dup = next((o for o in out if _kw(o.text) == key and o.kind == a.kind and _overlap(o.hints, a.hints)), None)
            if dup is None:
                out.append(a)
                continue
            self.stats.duplicates_merged += 1
            for h in a.hints:
                if not any(_same(h, x) for x in dup.hints):
                    dup.hints.append(h)
        return out

    def _finalize(self, atoms: list[_Atom], groups: list[tuple[str, str, list[str]]], unproc: dict[str, str],
                  facts: list[_Fact], mode: str, llm_status: str, calls: dict[str, int], model_missed: list[str],
                  fallback_blocks: list[str]) -> dict[str, Any]:
        atoms = self._dedupe(atoms)
        if self.stats.duplicates_merged:
            self._warn("duplicates_merged", f"объединено дублей пунктов: {self.stats.duplicates_merged}")
        # единицы (исходные пункты) и устойчивые ID
        units: dict[tuple[Any, ...], list[_Atom]] = {}
        for a in atoms:
            units.setdefault(self._unit_key(a), []).append(a)
        ordered_units = sorted(units.items(), key=lambda kv: min(self._pos(x) for x in kv[1]))
        by_number: dict[tuple[Any, ...], list[str]] = {}
        for key, _ in ordered_units:
            if key[0] == "L":
                by_number.setdefault(key[1:3], []).append(key[3])
        for (section, number), label_blocks in by_number.items():
            if len(label_blocks) > 1:
                self._warn("duplicate_source_id",
                           f"номер «{number}» повторяется в разделе «{self._section_name(section)}» "
                           f"(блоки {', '.join(label_blocks)}); пункты учтены раздельно", label_blocks)
        requirements: list[dict[str, Any]] = []
        req_blocks: dict[str, list[str]] = {}
        spans_by_req: list[tuple[str, list[_Hint]]] = []
        width = max(3, len(str(len(ordered_units))))
        for n, (_, members) in enumerate(ordered_units, start=1):
            members.sort(key=lambda x: (self._pos(x), x.hints[0].end, _kw(x.text)))
            group = f"R-{n:0{width}d}"
            for k, a in enumerate(members, start=1):
                rid = group if len(members) == 1 else f"{group}.{k}"
                anchor_block = self.by_id[a.hints[0].block_id]
                block_ids = _ordered_unique([h.block_id for h in a.hints], self.by_id)
                requirements.append({
                    "id": rid,
                    "group": group,
                    "source_id": a.source_id,
                    "source_ref": self._source_ref(a, anchor_block),
                    "kind": a.kind,
                    "text": a.text,
                    "block_ids": block_ids,
                    "hints": [self._hint_out(h) for h in a.hints],
                    "evidence": [_evidence_out(h) for h in a.hints],
                    "section": list(anchor_block.section),
                    "origin": a.origin,
                    "review_status": "not_reviewed",
                    "review_reason": None,
                })
                spans_by_req.append((rid, a.hints))
                for bid in block_ids:
                    req_blocks.setdefault(bid, []).append(rid)
        # исключения: требование побеждает конфликтующую отметку
        excl_by_block: dict[str, tuple[str, str]] = {}
        conflict_blocks: list[str] = []
        for cat, reason, ids in groups:
            for bid in ids:
                if bid in req_blocks:
                    self.stats.conflicts_resolved += 1
                    if bid not in conflict_blocks:
                        conflict_blocks.append(bid)
                    continue
                excl_by_block.setdefault(bid, (cat, reason))
        if self.stats.conflicts_resolved:
            self._warn("exclusion_conflict",
                       f"{self.stats.conflicts_resolved} отметок исключения сняты — блок содержит требование",
                       conflict_blocks)
        grouped: dict[tuple[str, str], list[str]] = {}
        for b in self.blocks:
            if b.id in excl_by_block:
                grouped.setdefault(excl_by_block[b.id], []).append(b.id)
        excluded = []
        for (cat, reason), ids in sorted(grouped.items(), key=lambda kv: self.by_id[kv[1][0]].idx):
            excluded.append({
                "category": cat,
                "reason": reason,
                "block_ids": ids,
                "cross_check": EXCLUSION_CATEGORIES.get(cat, EXCLUSION_CATEGORIES["other"])[1],
                "sections": _ordered_unique([" › ".join(self.by_id[i].section) for i in ids], None),
            })
        accounted = set(req_blocks) | set(excl_by_block)
        unprocessed = [b.id for b in self.blocks if b.id not in accounted]
        reasons = {bid: unproc.get(bid) or self.fates[bid].unprocessed or "Блок не получил судьбу." for bid in unprocessed}
        # остаток показан в unprocessed_block_ids и block_coverage; предупреждение о нём выдаёт движок
        fact_out = self._facts_out(_unique_facts(facts), spans_by_req)
        coverage = self._coverage(requirements, ordered_units, req_blocks, excl_by_block, unprocessed, reasons,
                                  mode, llm_status, calls, model_missed, fallback_blocks)
        return {
            "requirements": requirements,
            "fact_hints": fact_out,
            "excluded": excluded,
            "unprocessed_block_ids": unprocessed,
            "warnings": list(self.warnings),
            "block_coverage": coverage,
            "mode": mode,
            "version": VERSION,
        }

    def _pos(self, a: _Atom) -> tuple[int, int]:
        h = a.hints[0]
        return self.by_id[h.block_id].idx, h.start

    def _unit_key(self, a: _Atom) -> tuple[Any, ...]:
        anchor = a.hints[0]
        b = self.by_id[anchor.block_id]
        if a.source_id and a.sid_src in ("label", "text"):
            label_block = b.id
            if not any(_norm_label(lab) == _norm_label(a.source_id) for _, _, lab in self.labels.get(b.id, [])):
                for prev in reversed(self.blocks[: b.idx]):
                    if prev.section != b.section:
                        break
                    if any(_norm_label(lab) == _norm_label(a.source_id) for _, _, lab in self.labels.get(prev.id, [])):
                        label_block = prev.id
                        break
            return ("L", b.section, _norm_label(a.source_id), label_block)
        return ("B", b.id, self.row_index(b.id, anchor.start))

    def _source_ref(self, a: _Atom, b: _Block) -> str:
        head = _clean(b.section[-1]) if b.section else "без раздела"
        if a.source_id and a.sid_src in ("label", "text"):
            return f"{head} › {a.source_id}"
        rows = self.row_of.get(b.id)
        if rows:
            t = self.table_of(b.id)
            if t is not None:
                data = t.data
                pos = a.hints[0].start
                for n, r in enumerate(data, start=1):
                    if any(c.block_id == b.id and c.start <= pos <= c.end for c in r.cells) or (
                            r.block_id == b.id and r.cells and r.cells[0].start <= pos <= r.cells[-1].end):
                        return f"{head} › строка {n}"
        return head

    def _hint_out(self, h: _Hint) -> dict[str, Any]:
        """Hint по контракту: при неоднозначной цитате ``context`` — фрагмент блока, где она встречается один раз."""
        out: dict[str, Any] = {"block_id": h.block_id, "quote": h.quote}
        text = self.by_id[h.block_id].text
        if text.count(h.quote) > 1:
            pad = 12
            while True:
                a, b = max(0, h.start - pad), min(len(text), h.end + pad)
                ctx = text[a:b]
                if text.count(ctx) == 1 or (a == 0 and b == len(text)):
                    break
                pad *= 2
            out["context"] = ctx
        return out

    def _facts_out(self, facts: list[_Fact], spans_by_req: list[tuple[str, list[_Hint]]]) -> list[dict[str, Any]]:
        facts = sorted(facts, key=lambda f: (self.by_id[f.hints[0].block_id].idx, f.hints[0].start, f.field or ""))
        out = []
        for n, f in enumerate(facts, start=1):
            out.append({
                "id": f"F-{n:03d}",
                "subject": f.subject,
                "field": f.field,
                "direction": f.direction,
                "type": f.type,
                "value": f.value,
                "unit": f.unit,
                "range": f.range,
                "condition": f.condition,
                "required": f.required,
                "size": f.size,
                "values": f.values,
                "db_field": f.db_field,
                "hints": [self._hint_out(h) for h in f.hints],
                "evidence": [_evidence_out(h) for h in f.hints],
                "req_ids": [rid for rid, hs in spans_by_req if _overlap(f.hints, hs)],
                "origin": f.origin,
            })
        return out

    def _coverage(self, requirements, units, req_blocks, excl_by_block, unprocessed, reasons, mode, llm_status,
                  calls, model_missed, fallback_blocks) -> dict[str, Any]:
        total = len(self.blocks)
        by_kind: dict[str, int] = {}
        by_origin: dict[str, int] = {}
        for r in requirements:
            by_kind[r["kind"]] = by_kind.get(r["kind"], 0) + 1
            by_origin[r["origin"]] = by_origin.get(r["origin"], 0) + 1
        by_cat: dict[str, int] = {}
        for cat, _ in excl_by_block.values():
            by_cat[cat] = by_cat.get(cat, 0) + 1
        blocks = []
        for b in self.blocks:
            if b.id in req_blocks:
                blocks.append({"block_id": b.id, "fate": "requirement", "ref": req_blocks[b.id]})
            elif b.id in excl_by_block:
                blocks.append({"block_id": b.id, "fate": "excluded", "ref": excl_by_block[b.id][0],
                               "reason": excl_by_block[b.id][1]})
            else:
                blocks.append({"block_id": b.id, "fate": "unprocessed", "ref": None, "reason": reasons[b.id]})
        accounted = total - len(unprocessed)
        ratio = round(accounted / total, 4) if total else 1.0
        st = self.stats
        cat_txt = ", ".join(f"{k} {v}" for k, v in sorted(by_cat.items(), key=lambda kv: (-kv[1], kv[0])))
        parts = [
            f"Учтено {accounted} из {_blocks_word(total)} ({ratio * 100:.1f}%).",
            f"Требования: {len(requirements)} атомарных из {len(units)} исходных пунктов; опорных блоков: {len(req_blocks)}.",
            f"Исключено {_blocks_word(len(excl_by_block))} с причинами" + (f" ({cat_txt})." if cat_txt else "."),
        ]
        if unprocessed:
            parts.append(f"Не обработано {_blocks_word(len(unprocessed))}: " + "; ".join(
                f"{bid} — {reasons[bid].rstrip('.')}" for bid in unprocessed) + ".")
        else:
            parts.append("Необработанных блоков нет.")
        if mode == "rules_only" and llm_status == "not_used":
            parts.append("Режим rules_only: нарезка по явным номерам, строкам таблиц и абзацам разделов требований; "
                         "модель не вызывалась, атомарность — до предложения.")
        else:
            parts.append(
                f"Обращений к ask: {calls['used']} при пределе модуля {calls['budget']} (окон {calls['windows']}, "
                f"повторов {calls['retry_calls']}, сбоев {calls['failed']}, обрезанных ответов {calls['truncated']}); "
                f"цитат проверено {st.hints_checked}: дословно {st.hints_exact}, исправлено {st.hints_repaired}, "
                f"отклонено {st.hints_rejected}; пунктов отброшено {st.items_rejected}.")
            if model_missed:
                parts.append(f"Модель не учла {_blocks_word(len(model_missed))}; правилами закрыто {len(fallback_blocks)}.")
        return {
            "mode": mode,
            "llm_status": llm_status,
            "level": "complete" if not unprocessed else "partial",
            "total_blocks": total,
            "requirement_blocks": len(req_blocks),
            "excluded_blocks": len(excl_by_block),
            "unprocessed_blocks": len(unprocessed),
            "accounted_ratio": ratio,
            "requirements": len(requirements),
            "source_units": len(units),
            "by_kind": by_kind,
            "by_origin": by_origin,
            "excluded_by_category": by_cat,
            "calls": dict(calls),
            "model_missed_block_ids": list(model_missed),
            "fallback_block_ids": list(fallback_blocks),
            "evidence": {
                "checked": st.hints_checked,
                "exact": st.hints_exact,
                "repaired": st.hints_repaired,
                "rejected": st.hints_rejected,
                "empty": st.hints_empty,
                "items_rejected": st.items_rejected,
                "facts_rejected": st.facts_rejected,
                "source_ids_cleared": st.source_ids_cleared,
                "source_ids_filled": st.source_ids_filled,
                "duplicates_merged": st.duplicates_merged,
                "context_linked": st.context_linked,
                "excluded_unknown_ids": st.excluded_unknown_ids,
                "conflicts_resolved": st.conflicts_resolved,
            },
            "evidence_audit": {
                "checked": st.hints_checked,
                "confirmed": st.hints_exact + st.hints_repaired,
                "ambiguous": st.hints_ambiguous,
                "rejected": st.hints_rejected,
                "note": ("Опоры этапа inventory: цитата модели принята, если она дословная или после нормализации "
                         "пробелов, кавычек, тире и разметки найдена в блоке; тогда она заменена фрагментом источника "
                         f"(исправлено {st.hints_repaired}). Неоднозначные — цитата встречается в блоке не один раз "
                         "и снабжена context. Правила дают опоры из текста напрямую и здесь не считаются."),
            },
            "blocks": blocks,
            "explanation": " ".join(parts),
        }


# ---------------------------------------------------------------------------- вспомогательные


def _blocks_word(n: int) -> str:
    tail = n % 100
    if 11 <= tail <= 14:
        word = "блоков"
    elif n % 10 == 1:
        word = "блок"
    elif 2 <= n % 10 <= 4:
        word = "блока"
    else:
        word = "блоков"
    return f"{n} {word}"


def _times_word(n: int) -> str:
    tail = n % 100
    return f"{n} раза" if 2 <= n % 10 <= 4 and not 12 <= tail <= 14 else f"{n} раз"


def _norm_label_text(text: str) -> str:
    s = _kw(text)
    return s.translate(str.maketrans({"–": "-", "—": "-", "‑": "-", "_": "-"}))


def _num_or_none(v: Any) -> Any:
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return v
    parsed = _parse_num(str(v))
    return parsed if parsed is not None else _none_if_empty(v)


def _evidence_out(h: _Hint) -> dict[str, Any]:
    """Evidence по контракту: ``block.text[start:end] == quote`` проверено при разборе."""
    return {"block_id": h.block_id, "start": h.start, "end": h.end, "quote": h.quote}


def _same(a: _Hint, b: _Hint) -> bool:
    return a.block_id == b.block_id and a.start == b.start and a.end == b.end


def _overlap(xs: Iterable[_Hint], ys: Iterable[_Hint]) -> bool:
    ys = list(ys)
    return any(x.block_id == y.block_id and x.start < y.end and y.start < x.end for x in xs for y in ys)


def _unique(items: list[Any]) -> list[Any]:
    seen: list[int] = []
    out = []
    for it in items:
        if id(it) in seen:
            continue
        seen.append(id(it))
        out.append(it)
    return out


def _unique_facts(facts: list[_Fact]) -> list[_Fact]:
    out: list[_Fact] = []
    for f in _unique(facts):
        key = (f.field, f.direction, f.type, f.unit, str(f.value), json.dumps(f.range, sort_keys=True), f.condition)
        if any((o.field, o.direction, o.type, o.unit, str(o.value), json.dumps(o.range, sort_keys=True), o.condition)
               == key and _overlap(o.hints, f.hints) for o in out):
            continue
        out.append(f)
    return out


def _ordered_unique(items: Iterable[str], by_id: Mapping[str, _Block] | None) -> list[str]:
    seen: set[str] = set()
    out = [x for x in items if not (x in seen or seen.add(x))]
    if by_id is not None:
        out.sort(key=lambda x: by_id[x].idx)
    return out


def _is_truncated(resp: Any) -> bool:
    if not isinstance(resp, Mapping):
        return True
    meta = resp.get("_meta") if isinstance(resp.get("_meta"), Mapping) else {}
    if resp.get("_truncated") or meta.get("truncated"):
        return True
    stop = str(meta.get("stop_reason") or meta.get("finish_reason") or "").lower()
    if stop in ("max_tokens", "length", "max_output_tokens"):
        return True
    return resp.get("done") is not True


# ---------------------------------------------------------------------------- публичные функции


def build_inventory(
    document: Any,
    ask: Callable[[str, dict[str, Any], dict[str, Any]], Any] | None = None,
    *,
    window_chars: int = 40_000,
    overlap_blocks: int = 2,
    max_calls: int | None = None,
    retry: bool = True,
    fallback: bool = True,
    attach_text: bool = False,
) -> dict[str, Any]:
    """Строит инвентарь требований по Document (контракт v1).

    :param document: Document как dict или объект: ``{id, title, format, blocks, warnings}``.
    :param ask: ``ask(stage, payload, schema) -> dict``; ``None`` — только правила.
    :param window_chars: размер окна в символах; короткий документ идёт одним окном целиком.
    :param overlap_blocks: число блоков соседнего окна, передаваемых как контекст.
    :param max_calls: бюджет физических вызовов; по умолчанию ``max(2, 2 * окна)``.
    :param retry: повторно предъявить модели необработанные блоки (один раз в рамках бюджета).
    :param fallback: закрыть пропущенные моделью блоки нарезкой по правилам (с пометкой origin).
    :param attach_text: класть текст блоков в payload (``context.mode = none``) вместо контекста движка.
    """
    inv = _Inventory(document)
    return inv.run(ask, window_chars=window_chars, overlap_blocks=overlap_blocks, max_calls=max_calls, retry=retry,
                   fallback=fallback, attach_text=attach_text)


def build_payload(document: Any, *, window_chars: int = 40_000, overlap_blocks: int = 2,
                  attach_text: bool = True) -> list[dict[str, Any]]:
    """Payload-ы первого прохода без вызова модели: для журнала, кэша и ручного прогона промпта.

    По умолчанию текст блоков вложен в payload, чтобы его можно было отдать модели как есть.
    """
    inv = _Inventory(document)
    hard = {bid for bid, f in inv._ordered_fates() if inv._is_hard(f)}
    plan = inv._plan([b for b in inv.blocks if b.id not in hard], max(1, window_chars), overlap_blocks)
    return [inv.payload(core, ctx, i, len(plan), "full", full=len(plan) == 1, attach_text=attach_text)
            for i, (core, ctx) in enumerate(plan)]


def _main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        prog="python -m bcc_review.analysis.inventory",
        description="Инвентарь требований по Document JSON (режим rules_only, без модели).",
    )
    parser.add_argument("document_json", help="Document по контракту v1 в JSON")
    parser.add_argument("-o", "--output", help="куда записать инвентарь JSON (по умолчанию stdout)")
    parser.add_argument("--payload", action="store_true", help="вывести payload-ы для модели вместо инвентаря")
    args = parser.parse_args(argv)
    with open(args.document_json, encoding="utf-8") as fh:
        doc = json.load(fh)
    result: Any = build_payload(doc) if args.payload else build_inventory(doc)
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
    else:
        sys.stdout.write(text + "\n")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main())
