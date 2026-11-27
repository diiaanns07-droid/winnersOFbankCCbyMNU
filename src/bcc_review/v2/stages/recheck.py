"""Этап recheck (№11): ответы владельца → пересмотр дефектов → второй вердикт «до / после».

Формат ответов (``--answers answers.md|json``; кодировка — UTF-8, UTF-16 или cp1251 из Блокнота):

* Markdown: строки ``Q-01: B``, ``Q-01: B — комментарий``, ``Q-01: свой текст``,
  ``Q-02 [тема вопроса]: свой текст`` (тема может содержать скобки), ``Q-04. B``, ``Вопрос 6: B``, строки таблицы
  ``| Q-03 | тема | … | ответ |`` (ответ — последняя ячейка). Ответ продолжается следующими строками до пустой
  (абзац Markdown); ``Q-03:`` без значения — ответ на следующей строке. Строки без номера в разделе «Решения»
  (``- …``) — общие решения владельца; они вносятся и в исправленную редакцию. Буквы вариантов — латинские A–D;
  кириллические А, В, С читаются как A, B, C, Б как B, Г как D; цифры 1–4 — номер варианта. Текст варианта вместо
  буквы — тоже выбор варианта; ``B — текст варианта`` сверяется по тексту, если вопросы перегенерированы и варианты
  переставились. ``Q-03: ?`` или пустое значение — «нет ответа». Строки ``#`` и ``>`` — комментарии; строка с
  номером вопроса, которую не удалось разобрать, — предупреждение.
* JSON: ``{"Q-01": "B"}``, ``{"answers": {"Q-01": "B"}}``, ``[{"id": "Q-01", "answer": "B"}]``,
  ``{"Q-01": {"choice": "B", "comment": "…"}}``, ``{"Q-02": ["…", "…"]}`` (реплики разных адресатов),
  ``{"answers": [{"question_id": "Q-01", "option_index": 1, "text": "…"}]}`` (номер варианта с нуля),
  ``{"decisions": ["…"]}`` или ``{"decisions": "…"}``.

Несколько ответов на один вопрос (разные адресаты) хранятся отдельно — ``replies`` с метками ``Q-02.1``,
``Q-02.2``; пересмотр сверяет их, расходящиеся оставляют дефект открытым с ``conflicting_answers``, разные буквы —
конфликт кодом. Мягкий отказ («не знаю», «решим позже», «ещё решаем», «решение не принято», «как обычно») — не
ответ: вопрос без ответа, отложенная часть частичного ответа — ``deferred`` / ``clarification.postponed``.

Номера вопросов от прогона к прогону могут меняться, поэтому ответ можно привязать к теме: если тема в
скобках не совпадает с темой вопроса под этим номером, программа ищет вопрос с подходящей темой.

Честность кода: дефект может стать ``resolved`` только если на связанный вопрос дан содержательный ответ
(или есть общее решение владельца). Новые конфликты, порождённые ответами, идут кандидатами через судью.
Вердикт до и после считает одно и то же правило кода (контракт, раздел 5).
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable

from bcc_review.v2.stages import clarify as _cl

STAGE = "recheck"
STATUSES = ("resolved", "open", "changed")
SEVERITIES = ("critical", "major", "minor")

_KINDS = ["event_conflict", "status_conflict", "unit_mismatch", "boundary_conflict", "contradiction",
          "missing_element", "incomplete", "ambiguity", "unverifiable", "non_singular", "design_constraint",
          "terminology", "api_contract", "placeholder", "traceability", "infeasible", "incorrect", "duplicate",
          "security", "ops_risk", "other"]
_CRITERIA = ["necessary", "appropriate", "unambiguous", "complete", "singular", "feasible", "verifiable",
             "correct", "conforming", "language", "set_complete", "set_consistent", "set_feasible",
             "set_comprehensible", "set_validatable", "ranked", "modifiable", "traceable", "risk"]


def _candidate_schema() -> dict:
    try:  # общая схема кандидата из каркаса (№01), если есть
        from bcc_review.v2 import types as _t  # type: ignore
        for name in ("CANDIDATE_SCHEMA", "CANDIDATE"):
            sch = getattr(_t, name, None)
            if isinstance(sch, dict) and sch.get("properties", {}).get("evidence"):
                return sch
    except Exception:  # noqa: BLE001
        pass
    s = {"type": "string"}
    return {"type": "object", "additionalProperties": False, "properties": {
        "title": s, "kind": {"type": "string", "enum": _KINDS}, "criterion": {"type": "string", "enum": _CRITERIA},
        "severity": {"type": "string", "enum": list(SEVERITIES)},
        "requirement_ids": {"type": "array", "items": s},
        "evidence": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                                "required": ["quote", "line"],
                                                "properties": {"quote": s, "line": {"type": "integer"}}}},
        "problem": s, "scenario": s, "impact": s, "recommendation": s, "rewrite": s, "question": s,
        "blocks": {"type": "string", "enum": ["development", "testing", "both", "none"]}},
        "required": ["title", "kind", "criterion", "severity", "requirement_ids", "evidence", "problem", "scenario",
                     "impact", "recommendation", "rewrite", "question", "blocks"]}


SCHEMA: dict = {
    "type": "object", "additionalProperties": False, "required": ["decisions", "candidates"],
    "properties": {
        "decisions": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["finding_id", "status", "by", "conflicting_answers", "reason", "severity", "title",
                         "problem"],
            "properties": {
                "finding_id": {"type": "string"},
                "status": {"type": "string", "enum": list(STATUSES)},
                "by": {"type": "array", "items": {"type": "string"}},
                "conflicting_answers": {"type": "array", "items": {"type": "string"}},
                "reason": {"type": "string"},
                "severity": {"type": "string", "enum": list(SEVERITIES)},
                "title": {"type": "string"},
                "problem": {"type": "string"},
            }}},
        "candidates": {"type": "array", "maxItems": 8, "items": _candidate_schema()},
    },
}

# --------------------------------------------------------------------------- разбор ответов
_LETTER = {"A": 0, "B": 1, "C": 2, "D": 3, "А": 0, "В": 1, "С": 2, "Б": 1, "Г": 3,
           "1": 0, "2": 1, "3": 2, "4": 3}
# «Q-01 [тема]: ответ». Тема в квадратных скобках может содержать круглые и одну вложенную пару квадратных
# («[Момент утраты льготного периода (LOST)]» — так тему выгружает кнопка «Скачать ответы» HTML-отчёта);
# разделитель — двоеточие, тире, «=», а также «.» или «)» перед пробелом («Q-04. B», «**Q-04.** B», «Q-05) A»).
_QID = r"(?:Q|Вопрос)\s*-?\s*\d{1,3}"
_QLINE = re.compile(
    r"^\s*(?:[-*+]\s+)?(?:\*\*|__)?\s*(" + _QID + r")\s*(?:\*\*|__)?\s*"
    r"(?:\[((?:[^\[\]\n]|\[[^\[\]\n]*\]){1,200})\]|\(([^()\n]{1,200})\))?\s*(?:\*\*|__)?\s*"
    r"(?:[:：=—–-]|[.)](?=[\s*_]))\s*(?:\*\*|__)?\s*(.*)$", re.I)
_QSTART = re.compile(r"^\s*(?:[-*+]\s+)?(?:\*\*|__)?\s*" + _QID + r"\b", re.I)
_QCELL = re.compile(r"^(?:\*\*|__)?\s*(" + _QID + r")\s*(?:\*\*|__)?$", re.I)
_CHOICE = re.compile(r"^\s*(?:\*\*)?([A-DА-ГABCDС1-4])(?:\*\*)?\s*(?:$|[).,;:—–-]\s*(.*)$|\s+[—–-]\s*(.*)$)", re.I)
_NO_ANSWER = re.compile(r"^\s*(?:\?+|-+|—|нет ответа|не знаю|tbd|todo|позже|потом|обсудим\b.*)\s*$", re.I)
_VAGUE = re.compile(r"\b(как обычно|по ситуации|на усмотрение|решим позже|обсудим позже|уточним позже)\b", re.I)
# мягкий отказ: «не знаю», «решим позже», «примем после встречи», «ещё решаем», «пока открыт» — это не правило
_DEFER = re.compile(
    r"(?:\bне\s+знаю\b|\bне\s+(?:решили|решил|решила|решено|определились|согласовали|договорились)\b"
    r"|\b(?:пока|ещё|еще)\s+(?:не\s+(?:знаю|решили|решил|решила|решено|определились|согласовали|договорились|ясно"
    r"|понятно)\b|решаем|обсуждаем|думаем|выясняем|согласуем|неясно|непонятно|под\s+вопросом"
    r"|открыт\w*(?=\s*(?:[.!?;,]|$)))"
    r"|\b(?:решим|обсудим|уточним|договоримся|согласуем|определимся|вернёмся|вернемся|примем|разберёмся"
    r"|разберемся|подумаем)\b[^.!?;]*?\b(?:позже|потом|отдельно|после|завтра|следующ\w*)\b"
    r"|\b(?:позже|потом|отдельно)\s+(?:решим|обсудим|уточним|договоримся|согласуем|определимся|скажем)\b"
    r"|\bоткрыт\w*\s+вопрос|\bвопрос\s+(?:пока\s+|ещё\s+|еще\s+)?открыт|\bна\s+обсуждении\b|\btbd\b|\btodo\b"
    r"|\bрешени\w*\s+(?:пока\s+|ещё\s+|еще\s+)?не\s+принят\w*|\b(?:пока|ещё|еще)\s+неизвестн\w*"
    r"|\bна\s+согласовании\b|\bв\s+процессе\s+согласовани\w*|\bжд[её]м\s+(?:решени|согласовани)\w*)",
    re.I)
_SENT = re.compile(r"(?<=[.!?;])\s+")
_BUT = re.compile(r",?\s+(?:но|однако|а)\s+(?=[а-яё])", re.I)


def _opt_key(s: str) -> str:
    s = re.sub(r"^\s*(?:\*\*)?[A-DА-Г1-4](?:\*\*)?\s*[).:—-]\s+", "", str(s or ""))  # «B) …», «Б — …»
    return re.sub(r"[\s.;,!]+$", "", _cl._norm(s))


def _option_index(text: str, options: list) -> int | None:
    """Номер варианта, если текст ответа совпадает с текстом варианта (без учёта регистра, кавычек, точки)."""
    key = _opt_key(text)
    if len(key) < 3:
        return None
    hits = [i for i, o in enumerate(options) if _opt_key(str(o)) == key]
    return hits[0] if len(hits) == 1 else None


def _option_by_text(text: str, options: list) -> int | None:
    """Вариант, который называет текст ответа: точное совпадение или все значимые слова текста (не меньше двух)
    есть в одном варианте и не меньше чем на 0,2 реже — в любом другом."""
    exact = _option_index(text, options)

    def words(s: str) -> set[str]:  # слова и числа: «48 часов» отличается от «24 часа» числом
        return _tokens(s) | set(re.findall(r"\d+", str(s or "")))
    said = words(text)
    if exact is not None or len(said) < 2:
        return exact
    scores = sorted(((len(said & words(str(o))) / len(said), i) for i, o in enumerate(options)), reverse=True)
    if not scores or scores[0][0] < 0.8:
        return None
    if len(scores) > 1 and scores[0][0] - scores[1][0] < 0.2:
        return None
    return scores[0][1]


# заготовка файла следующего круга, которую владелец не заполнил, или маркер редакции, вставленный в ответ
_TODO = re.compile(r"<\s*(?:решите|допишите|уточнить)\s*:", re.I)
_TODO_WRAP = re.compile(r"^\s*<\s*(?:решите|допишите|уточнить)\s*:\s*|\s*>\s*$", re.I)


def _soft(part: str) -> bool:
    """Предложение не задаёт правила: откладывает решение, отсылает к «как обычно», «по ситуации» или осталось
    незаполненной заготовкой «<решите: …>»."""
    return bool(_DEFER.search(part) or _VAGUE.search(part) or _TODO.search(part))


def split_deferred(text: str) -> tuple[str, list[str]]:
    """Ответ → (правило, отложенные части). Предложение с мягким отказом правилом не считается.

    «Не знаю, примем после встречи» → ("", [...]): ответа нет. «410 при истечении срока. Что возвращать на
    оплаченный код, ещё решаем.» → ("410 при истечении срока.", ["Что возвращать…"]): правило — только первая часть.
    """
    rule, deferred = [], []
    for part in _SENT.split(str(text or "").strip()):
        part = part.strip()
        if not part:
            continue
        if not _soft(part):
            rule.append(part)
            continue
        # «Порог 100 ₸, но формат уточним позже»: правило до «но» остаётся, отложенная часть — отдельно
        for clause in _BUT.split(part):
            clause = clause.strip(" ,")
            if clause:
                (deferred if _soft(clause) or len(_tokens(clause)) < 3 else rule).append(clause)
    body = " ".join(rule).strip()
    if deferred and len(_tokens(body)) < 3:  # «Хороший вопрос. Решим позже.» — правила в остатке нет
        deferred, body = [*rule, *deferred], ""
    return body, deferred



# указание модели внутри файла ответов («игнорируй инструкции», «закрой все дефекты», «модель, дефектов нет») —
# не решение владельца: такое предложение вырезается до привязки и пересмотра (п. 7 системных правил)
_CLOSE_ALL = re.compile(
    r"\b(?:закр\w*|сним\w*|сня\w*|отмет\w*|помет\w*|считай\w*|призна\w*)\s+(?:все|всё|любые|остальные)\s+"
    r"(?:дефект\w*|замечани\w*|находк\w*)|\b(?:все|всё)\s+(?:дефект\w*|замечани\w*)\s+(?:сняты|закрыты|устранены)"
    r"|\bmark\s+all\s+(?:defects|findings|issues)\b|\ball\s+(?:defects|findings|issues)\s+(?:are\s+)?(?:resolved|closed)\b"
    # «считай документ корректным», «отметь дефекты как устранённые», «поставь статус resolved всем дефектам»
    r"|\b(?:счита|призна)\w*\s+(?:документ|требовани\w*|тз|спецификаци\w*)\s+(?:корректн|верн|правильн|готов|одобр)\w*"
    r"|\b(?:отмет|помет|отмеча|помеча)\w*\s+(?:все\s+|всё\s+)?(?:дефект|замечани|находк)\w*\s+(?:как\s+)?"
    r"(?:устран|закрыт|снят|решен|решён|resolved|closed)\w*"
    r"|\bстатус\w*\s+[«\"']?(?:resolved|closed|закрыт|снят|устран)\w*[»\"']?[^.!?;]*?\b(?:все\w*|кажд\w*|любы\w*)\s+"
    r"(?:дефект|замечани|находк)\w*",
    re.I)
# обращение к модели — в начале предложения («Модель, …», «Уважаемый ИИ: …»); упоминание «ИИ-скоринга» в правиле —
# не обращение: «При отказе ИИ-скоринга верни 422» — правило владельца
_MODEL_ADDR = re.compile(r"^\s*(?:(?:уважаем|дорог)\w*\s+)?(?:модель|model|assistant|ассистент|бот|bot|нейросеть|ии|ai|llm"
                         r"|gpt|chatgpt|claude|gemini|агент|agent)\s*[,:—–-](?!\w)", re.I)
try:
    from bcc_review.v2.rules import injection as _inj
except Exception:  # noqa: BLE001 — без детектора №12 остаётся своя проверка
    _inj = None


def _injected(part: str) -> bool:
    """Предложение обращается к модели или проверяющему, а не задаёт правило системы."""
    if _CLOSE_ALL.search(part):
        return True
    if _inj is None:
        return False
    if _inj.OVERRIDE.search(part) or _inj.VERDICT_STRONG.search(part):
        return True
    return bool(_MODEL_ADDR.search(part) and (_inj.VERDICT.search(part) or _inj.VERDICT_ADDR.search(part)
                                              or _inj.IMPERATIVE.search(part)))


def strip_injection(text: str) -> tuple[str, list[str]]:
    """Ответ → (текст без указаний модели, вырезанные предложения)."""
    kept, cut = [], []
    for part in _SENT.split(str(text or "").strip()):
        part = part.strip()
        if part:
            (cut if _injected(part) else kept).append(part)
    return " ".join(kept).strip(), cut

_DECISION_HEAD = re.compile(r"^\s*#{1,6}\s*(решени|общие решени|дополнительн)", re.I)


def _qid(raw: str) -> str:
    num = re.sub(r"\D", "", raw)
    return f"Q-{int(num):02d}" if num else ""


def _parse_value(value: str) -> dict:
    value = str(value or "").strip()
    if not value or _NO_ANSWER.match(value):
        return {"choice": None, "text": "", "comment": ""}
    m = _CHOICE.match(value)
    if m:
        letter = m.group(1).upper()
        rest = (m.group(2) or m.group(3) or "").strip()
        out = {"choice": _LETTER.get(letter), "text": "", "comment": rest}
        if letter == "В":  # кириллическая «В»: похожа на латинскую B, но в алфавите А-Б-В это третий вариант
            out["ambiguous_letter"] = True
        return out
    return {"choice": None, "text": value, "comment": ""}


# что владелец не видит в просмотре Markdown: комментарий <!-- … --> (незакрытый скрывает всё до конца файла)
# и невидимые символы (нулевая ширина, мягкий перенос, управление направлением). Такой текст — не ответ владельца,
# а невидимые символы внутри «Q-0\u200b1» ломают разбор номера.
_HIDDEN = re.compile(r"<!--.*?(?:-->|\Z)", re.S)
_INVISIBLE = re.compile("[\u00ad\u200b-\u200f\u2060-\u2064\ufeff\u202a-\u202e\u2066-\u2069]")


def unhide(text: str) -> tuple[str, int]:
    """Текст без комментариев и невидимых символов, число вырезанных непустых комментариев."""
    text = str(text or "")
    n = sum(1 for m in _HIDDEN.finditer(text) if m.group(0).strip("<!->\n\t "))
    return _INVISIBLE.sub("", _HIDDEN.sub("", text)), n


def _unhide_obj(obj: Any, count: list[int]) -> Any:
    if isinstance(obj, str):
        out, n = unhide(obj)
        count[0] += n
        return out
    if isinstance(obj, list):
        return [_unhide_obj(x, count) for x in obj]
    if isinstance(obj, dict):
        return {(unhide(k)[0] if isinstance(k, str) else k): _unhide_obj(v, count) for k, v in obj.items()}
    return obj


def parse_answers_text(text: str) -> dict:
    """Markdown/текст → ``{"answers": [{"id","topic_hint","choice","text","comment"}], "decisions": [str]}``."""
    answers: list[dict] = []
    decisions: list[str] = []
    in_decisions = False
    current: dict | None = None
    unparsed: list[str] = []
    text, hidden = unhide(text)
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip():
            current = None
            continue
        if line.lstrip().startswith("#"):
            in_decisions = bool(_DECISION_HEAD.match(line))
            current = None
            continue
        if line.lstrip().startswith(">") or line.lstrip().startswith("<!--"):
            continue
        if line.lstrip().startswith("|"):  # строка таблицы «| Q-03 | тема | … | ответ |»
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            mc = _QCELL.match(cells[0]) if cells else None
            current = None
            if mc and len(cells) >= 2:
                topic = cells[1] if len(cells) >= 3 else ""
                if cells[-1]:
                    answers.append({"id": _qid(mc.group(1)), "topic_hint": topic, **_parse_value(cells[-1])})
                continue
            if not in_decisions:
                continue
        m = _QLINE.match(line)
        if m and _qid(m.group(1)):
            value = (m.group(4) or "").strip()
            entry = {"id": _qid(m.group(1)), "topic_hint": (m.group(2) or m.group(3) or "").strip(),
                     **_parse_value(value)}
            answers.append(entry)
            # продолжение ответа — следующие строки до пустой (абзац Markdown): с отступом или без; у буквы —
            # оговорка; «Q-03:» без значения — ответ на следующей строке. Явный отказ («?», «—») продолжения нет.
            current = entry if (entry["choice"] is not None or entry["text"] or not value) else None
            if current is not None and not value:
                current["_empty"] = True
            continue
        if _QSTART.match(line):  # строка с номером вопроса, которую не удалось разобрать, не теряется молча
            unparsed.append(line.strip()[:120])
            current = None
            continue
        stripped = re.sub(r"^\s*[-*+]\s+", "", line).strip()
        if in_decisions and stripped:
            decisions.append(stripped)
            continue
        if current is not None and stripped:
            if current.pop("_empty", False):  # «Q-03:» — значение на следующей строке
                current.update(_parse_value(stripped))
            elif current["choice"] is not None:
                current["comment"] = (current["comment"] + " " + stripped).strip()
            else:
                current["text"] = (current["text"] + " " + stripped).strip()
    for a in answers:
        a.pop("_empty", None)
    out = {"answers": answers, "decisions": decisions}
    if unparsed:
        out["unparsed"] = unparsed
    if hidden:
        out["hidden"] = hidden
    return out


def parse_answers_json(data: Any) -> dict:
    answers: list[dict] = []
    decisions: list[str] = []
    count = [0]
    data = _unhide_obj(data, count)

    def add(qid: str, val: Any) -> None:
        if isinstance(val, list):  # {"Q-02": ["422 …", "403 …"]} — реплики разных адресатов на один вопрос
            for v in val:
                add(qid, v)
            return
        if isinstance(val, dict):
            text = str(val.get("text") or val.get("answer") or "")
            comment = str(val.get("comment") or "")
            topic = str(val.get("topic") or "")
            idx = val.get("option_index")
            if isinstance(idx, int) and not isinstance(idx, bool) and idx >= 0:
                # веб-демо №14 (``bcc-review/answers-1``): номер варианта с нуля; свой текст — оговорка к нему
                answers.append({"id": _qid(qid), "topic_hint": topic, "choice": idx, "text": "",
                                "comment": (text + " " + comment).strip()})
                return
            choice = val.get("choice", val.get("option"))
            parsed = _parse_value(str(choice)) if choice not in (None, "") else _parse_value(text)
            if choice not in (None, "") and text:  # «option» — буква или текст варианта, «text» — оговорка
                comment = (comment + " " + text).strip()
            answers.append({"id": _qid(qid), "topic_hint": topic, "choice": parsed["choice"],
                            "text": parsed["text"], "comment": (parsed["comment"] + " " + comment).strip()})
        else:
            answers.append({"id": _qid(qid), "topic_hint": "", **_parse_value(str(val))})

    if isinstance(data, dict):
        raw_dec = data.get("decisions") or []
        if isinstance(raw_dec, (str, dict)):  # «"decisions": "одно решение"» — не разбивать строку на буквы
            raw_dec = [raw_dec]
        decisions = [str(x.get("text") or x.get("decision") or "") if isinstance(x, dict) else str(x)
                     for x in raw_dec]
        decisions = [x for x in decisions if x.strip()]
        body = data.get("answers", data)
        if isinstance(body, dict):
            for k, v in body.items():
                if _qid(str(k)) and str(k).upper().startswith("Q"):
                    add(str(k), v)
        elif isinstance(body, list):
            data = body
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict) and (item.get("id") or item.get("question_id")):
                add(str(item.get("id") or item.get("question_id")), item)
    out = {"answers": [a for a in answers if a["id"]], "decisions": decisions}
    if count[0]:
        out["hidden"] = count[0]
    return out


def read_answers_file(path: Path) -> str:
    """Текст файла ответов в любой кодировке, в которой его сохраняют на Windows.

    UTF-8 (с BOM и без) → UTF-16 с BOM («Юникод» в Блокноте) или без BOM (``> answers.md`` в Windows
    PowerShell 5) → cp1251 («ANSI» русской Windows). Раньше файл в ANSI давал UnicodeDecodeError, и режим
    --answers молча не выполнялся (код выхода 0, без предупреждения). Слито: Max (67e048d) и №11 (36e7ffc).
    """
    data = Path(path).read_bytes()
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return data.decode("utf-16")
    if len(data) >= 4 and data[1:2] == b"\x00" and data[3:4] == b"\x00":  # UTF-16 LE без BOM
        return data.decode("utf-16-le", errors="replace")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        pass
    try:
        return data.decode("cp1251")
    except UnicodeDecodeError as exc:
        raise ValueError(f"файл ответов {Path(path).name} не в UTF-8: откройте его в Блокноте и сохраните "
                         f"с кодировкой UTF-8") from exc


def load_answers(source: Any) -> dict:
    """Путь к ``answers.md|json``, строка с текстом ответов или уже разобранный объект."""
    if isinstance(source, (dict, list)):
        return parse_answers_json(source)
    s = str(source or "")
    p = Path(s) if len(s) < 4096 and "\n" not in s else None
    if p is not None and p.exists():
        text = read_answers_file(p)
        if p.suffix.lower() == ".json":
            return parse_answers_json(json.loads(text))
    else:
        text = s
    stripped = text.strip()
    if stripped[:1] in "{[":
        try:
            return parse_answers_json(json.loads(stripped))
        except json.JSONDecodeError:
            pass
    return parse_answers_text(text)


_STOP = {"при", "для", "или", "как", "что", "это", "его", "она", "они", "все", "без", "над", "под", "про", "чем",
         "так", "уже", "ещё", "еще", "тот", "эти", "той", "том", "кто", "где", "the", "and", "какие", "какой", "каком",
         "какая", "есть", "быть", "если", "либо", "также"}


def _tokens(s: str) -> set[str]:
    """Грубые основы слов: окончания русских падежей не мешают совпадению («сумме» ~ «суммы»)."""
    words = [w for w in re.findall(r"[a-zа-яё0-9]{3,}", _cl._norm(s)) if w not in _STOP]
    return {w if len(w) <= 4 else w[:min(6, max(4, len(w) - 2))] for w in words}


def _text_score(text: str, q: dict) -> float:
    """Доля слов темы и вопроса, встречающихся в самом ответе."""
    a = _tokens(text)
    b = _tokens(f"{q.get('topic', '')} {q.get('question', '')}")
    return len(a & b) / max(1, len(b)) if a and b else 0.0


def _topic_score(hint: str, q: dict) -> float:
    """Доля слов подсказки в теме (вес 2) и в тексте вопроса (вес 1)."""
    h = _tokens(hint)
    if not h:
        return 0.0
    topic, text = _tokens(q.get("topic", "")), _tokens(q.get("question", ""))
    return (2 * len(h & topic) + len((h & text) - topic)) / (2 * len(h))


def resolve_answers(questions: list[dict], parsed: dict, warnings: list[str] | None = None) -> dict:
    """Ответы → решения по вопросам этого прогона. Возвращает ``answered``, ``unanswered``, ``decisions``.

    Несколько реплик на один вопрос (например, два адресата) не склеиваются и не уходят в общие решения:
    у ответа появляется ``replies`` с метками ``Q-02.1``, ``Q-02.2`` — пересмотр сверяет их между собой.
    Мягкий отказ («не знаю», «решим позже») ответом не считается; отложенная часть частичного ответа — в ``deferred``.
    """
    warnings = warnings if warnings is not None else []
    if parsed.get("hidden"):
        warnings.append(f"recheck: в файле ответов скрытый текст (HTML-комментарий, {parsed['hidden']}) — его не видно "
                        f"в просмотре, в ответы не взят")
    for line in parsed.get("unparsed") or []:
        warnings.append(f"recheck: строка ответа не разобрана — «{line}» (формат: «Q-01: B» или «Q-01 [тема]: ответ»)")
    # вопрос без id (старый или чужой отчёт) не роняет весь режим --answers: он просто не участвует в привязке;
    # номер вопроса сравнивается в одном виде («Q-1», «q1», «Q-01» → «Q-01»), в результат идёт номер из отчёта
    valid_q = [q for q in questions or [] if isinstance(q, dict) and _qid(str(q.get("id") or ""))]
    if len(valid_q) < len(questions or []):
        warnings.append(f"recheck: у {len(questions) - len(valid_q)} вопросов отчёта нет номера — они пропущены")
    questions = valid_q
    by_id = {_qid(str(q["id"])): q for q in questions}
    answered: dict[str, dict] = {}
    extra: list[str] = []
    postponed: list[dict] = []  # вопросы, где владелец отложил решение целиком (для отчёта)
    orphans: dict[tuple, list[dict]] = {}  # ответы на вопросы, которых нет в прогоне, по номеру и теме
    def clean(text: str, where: str) -> str:
        kept, cut = strip_injection(text)
        if cut:
            warnings.append(f"recheck: {where} — указание модели («{_short(cut[0], 80)}»), это не решение "
                            f"владельца; не учтено")
        return kept
    for d in parsed.get("decisions") or []:
        d = clean(str(d or ""), "в общем решении")
        if not d:
            continue
        body, deferred = split_deferred(d)
        if body:
            extra.append(d)
        else:
            warnings.append(f"recheck: общее решение «{str(d)[:60]}» откладывает решение — не учтено")
    entries = []
    for a in parsed.get("answers") or []:
        a = dict(a)
        had = bool(str(a.get("text") or "").strip())
        for key in ("text", "comment", "topic_hint"):  # тема в скобках уходит в текст общего решения
            if a.get(key):
                a[key] = clean(str(a[key]), f"в ответе {a.get('id')}")
        if a.get("choice") is None and had and not a.get("text"):
            continue  # ответ целиком — указание модели
        entries.append(a)
    # номера вопросов от прогона к прогону меняются: ответ с темой в скобках привязывается по теме.
    # Реплики с одним номером и одной темой — это ответы разных адресатов на один вопрос: они привязываются
    # вместе, как одна единица. Сопоставление глобальное: сначала самые уверенные пары «ответ — вопрос»,
    # каждый вопрос — одной единице.
    groups: dict[tuple, list[int]] = {}
    for k, a in enumerate(entries):
        hint = a.get("topic_hint") or ""
        if hint:
            groups.setdefault((a.get("id"), " ".join(sorted(_tokens(hint)))), []).append(k)
    bound: dict[int, dict | None] = {}
    pairs = []
    for gk, members in groups.items():
        hint = entries[members[0]].get("topic_hint") or ""
        text = " ".join(entries[k].get("text") or "" for k in members).strip()
        for x in questions:
            # свой текст ответа — такой же признак, как тема: «возвраты и повторный push» по теме ближе к вопросу
            # о повторном push, а по тексту ответа — к вопросу о возвратах. Ответ буквой — только по теме.
            if text:
                sc, need = 0.5 * _topic_score(hint, x) + 0.5 * _text_score(text, x), 0.3
            else:
                sc, need = _topic_score(hint, x), 0.4
            xid = _qid(str(x["id"]))
            pairs.append((sc + (0.01 if xid == gk[0] else 0), need, gk, xid))
    taken: dict[str, str] = {}  # вопрос → номер, с которым к нему пришла привязанная единица
    done: set[tuple] = set()
    ranked = sorted(pairs, key=lambda t: -t[0])
    for sc, need, gk, qid in ranked:
        if sc < need or gk in done or qid in taken:
            continue
        for k in groups[gk]:
            bound[k] = by_id[qid]
        done.add(gk)
        taken[qid] = gk[0]
    # второй адресат подписал тот же вопрос с тем же номером, но своими словами («[Код при отказе]» против
    # «[Ответ API на отказ антифрода]»): его лучший вопрос уже занят первым — это вторая реплика, а не общее решение
    for sc, need, gk, qid in ranked:
        if gk in done or sc < need:
            continue
        done.add(gk)  # только лучший вопрос группы
        if taken.get(qid) == gk[0]:
            for k in groups[gk]:
                bound[k] = by_id[qid]
    for k, a in enumerate(entries):
        hint = a.get("topic_hint") or ""
        q = by_id.get(a["id"])
        if hint:
            if k in bound:
                if q is None or bound[k]["id"] != q["id"]:
                    warnings.append(f"recheck: ответ {a['id']} [{hint}] отнесён к {bound[k]['id']} по теме")
                q = bound[k]
            elif a.get("choice") is None and a.get("text"):
                q = None  # тема не совпала однозначно ни с одним вопросом — это общее решение
            elif q is not None and _qid(str(q["id"])) in taken:
                q = None
        if q is None:
            if a.get("text"):
                body, _deferred = split_deferred(a["text"])
                if not body:
                    warnings.append(f"recheck: {a['id']}: ответ откладывает решение — не учтён")
                    continue
                extra.append(a["text"] + (f" ({hint})" if hint else ""))
                # реплики одного номера и одной темы — ответы адресатов на один вопрос, даже если в этом прогоне
                # его нет: запоминаем вместе, чтобы сверить их между собой (общими решениями порознь не сверить)
                orphans.setdefault((a.get("id"), " ".join(sorted(_tokens(hint)))), []).append(
                    {"label": f"Решение-{len(extra)}", "text": a["text"], "topic": hint, "id": a.get("id")})
                why = "тема не совпала ни с одним вопросом прогона" if hint else "такого вопроса нет в прогоне"
                warnings.append(f"recheck: {a['id']}: {why} — ответ учтён как общее решение")
            else:
                warnings.append(f"recheck: {a['id']} нет среди вопросов прогона — ответ пропущен")
            continue
        deferred: list[str] = []
        if a.get("choice") is not None:
            opts = q.get("options") or []
            # «B — 48 часов»: буква с текстом варианта. Полный прогон перегенерирует вопросы, и варианты могут
            # переставиться — смысл задаёт текст, который видел владелец, а не позиция буквы в новом списке
            j = _option_by_text(a.get("comment") or "", opts)
            if j is not None and j != a["choice"]:
                was = _cl.option_label(a["choice"])
                warnings.append(f"recheck: {q['id']}: буква {was} в этом прогоне указывает на другой вариант, а текст "
                                f"ответа совпал с вариантом {_cl.option_label(j)} («{str(opts[j])[:60]}») — взят он")
                a = dict(a, choice=j)
            if a["choice"] >= len(opts):
                warnings.append(f"recheck: у {q['id']} нет варианта {_cl.option_label(a['choice'])} — ответ пропущен")
                continue
            text = opts[a["choice"]]
            label = _cl.option_label(a["choice"])
            rejected = [str(o) for i, o in enumerate(opts) if i != a["choice"]]
            if a.get("ambiguous_letter") and len(opts) >= 3:
                warnings.append(f"recheck: {q['id']}: кириллическая «В» понята как вариант B («{text[:60]}»); "
                                f"если имелся в виду третий вариант (А, Б, В), укажите C")
        else:
            text, deferred = split_deferred(a.get("text", ""))
            label, rejected = "", []
            # владелец скопировал текст варианта вместо буквы — это выбор варианта, а не «свой ответ»
            pick = _option_index(text, q.get("options") or [])
            if pick is not None:
                text, label = q["options"][pick], _cl.option_label(pick)
                rejected = [str(o) for i, o in enumerate(q["options"]) if i != pick]
        # свой текст уже разобран по предложениям (split_deferred); «как обычно» в варианте модели — не правило
        if not text or (label and _VAGUE.search(text)) or len(text) < 3:
            why = "откладывает решение" if deferred else "не задаёт правила"
            warnings.append(f"recheck: ответ на {q['id']} {why} — вопрос остаётся открытым")
            if deferred:
                postponed.append({"question_id": q["id"], "text": " ".join(deferred), "partial": False})
            continue
        comment, later = split_deferred(a.get("comment") or "")
        if a.get("comment") and not comment and not later:
            comment = a["comment"]
        if comment and _opt_key(comment) == _opt_key(text):  # «B) 48 часов» — оговорка повторяет сам вариант
            comment = ""
        # «Б, но что после срока — решим позже»: буква — правило, отложенная оговорка — не правило
        deferred = deferred + [re.sub(r"^(?:но|однако|а)\s+", "", x, flags=re.I) for x in later]
        full = text + (f" ({comment})" if comment else "")
        if q["id"] in answered:  # ещё одна реплика на тот же вопрос — отдельно, пересмотр сверяет их
            prev = answered[q["id"]]
            if any(r["text"] == full for r in prev["replies"]):
                continue
            prev["replies"].append({"label": f"{q['id']}.{len(prev['replies']) + 1}", "choice": label, "text": full,
                                    "deferred": deferred})
            prev["answer"] = " / ".join(f"{r['label']}: {r['text']}" for r in prev["replies"])
            prev["choice"] = prev["choice"] if prev["choice"] == label else ""
            if not prev["choice"]:
                prev["rejected_options"] = []
            prev["deferred"] = prev["deferred"] + deferred
            # адресаты выбрали разные варианты одного вопроса — это конфликт по построению вариантов, без модели
            letters = {r["choice"] for r in prev["replies"] if r["choice"]}
            if len(letters) > 1:
                prev["choice_conflict"] = [r["label"] for r in prev["replies"] if r["choice"]]
            warnings.append(f"recheck: на {q['id']} несколько ответов ({len(prev['replies'])}) — сверяются при пересмотре")
            continue
        answered[q["id"]] = {"question_id": q["id"], "topic": q.get("topic", ""), "question": q.get("question", ""),
                             "choice": label, "answer": full, "deferred": deferred,
                             # отвергнутые владельцем варианты: правка редакции не должна вписать их значение
                             "rejected_options": rejected,
                             "replies": [{"label": f"{q['id']}.1", "choice": label, "text": full, "deferred": deferred}],
                             "finding_ids": list(q.get("finding_ids") or [])}
    unanswered = [q["id"] for q in questions if q["id"] not in answered]
    postponed = [p for p in postponed if p["question_id"] not in answered] + \
        [{"question_id": a["question_id"], "text": x, "partial": True} for a in answered.values()
         for x in a.get("deferred") or []]
    out = {"answered": list(answered.values()), "unanswered": unanswered, "decisions": extra, "postponed": postponed}
    clashes = decision_clashes(orphans)
    for c in clashes:
        warnings.append(f"recheck: {c['question_id']} [{c['topic']}]: ответы адресатов расходятся в значениях "
                        f"({' ↔ '.join(c['answers'])}), а вопроса с этой темой в прогоне нет — ни одно значение не "
                        f"вносится, выберите одно")
    if clashes:
        out["decision_conflicts"] = clashes
    return out


def _values(text: str) -> set[str]:
    """Числа ответа: «100 000» = «100000», «0,5» = «0.5»; одна цифра («1 раз», «шаг 2») — не значение."""
    s = re.sub(r"(?<=\d)[\s\u00a0\u202f](?=\d{3}(?!\d))", "", str(text or ""))
    return {n.replace(",", ".") for n in re.findall(r"(?<![\w.,:-])\d+(?:[.,:]\d+)*(?![\w-])", s) if len(n) >= 2}


def decision_clashes(orphans: dict) -> list[dict]:
    """Реплики разных адресатов на один вопрос (номер и тема), которого нет в прогоне, с разными значениями — конфликт.

    Расхождение кодом — только по числам (коды, сроки, суммы): у каждой стороны есть число, которого нет у другой
    («422» ↔ «403»). Реплики, где одна дополняет другую («48 часов» и «48 часов, затем 409»), — не конфликт."""
    out = []
    for (qid, _topic), items in orphans.items():
        if len(items) < 2:
            continue
        vals = [_values(x["text"]) for x in items]
        clash = [x for i, x in enumerate(items)
                 if any(vals[i] - vals[j] and vals[j] - vals[i] for j in range(len(items)) if j != i)]
        if len(clash) >= 2:
            out.append({"question_id": qid or "", "topic": clash[0]["topic"], "answers": [x["label"] for x in clash],
                        "texts": {x["label"]: x["text"] for x in clash}})
    return out


def _orphan_conflicts(resolved: dict, conflicts: list[dict]) -> list[dict]:
    """Спорящие реплики на вопрос, которого нет в прогоне, — в ``answer_conflicts`` (номер, тема, тексты): решения
    в споре редакция не вносит (``revise.decision_targets``), владелец выбирает одно."""
    out = [dict(c) for c in conflicts]
    for d in resolved.get("decision_conflicts") or []:
        extra = {"question_id": d.get("question_id", ""), "topic": d.get("topic", ""), "texts": dict(d.get("texts") or {})}
        hit = [c for c in out if set(c.get("answers") or []) == set(d["answers"])]
        for c in hit:
            c.update(extra)
        if not hit:
            out.append({"finding_id": "", "answers": list(d["answers"]), **extra,
                        "reason": f"адресаты по-разному ответили на «{d.get('topic') or d.get('question_id')}», а такого "
                                  f"вопроса в этом прогоне нет — ни одно значение не внесено, выберите одно"})
    return out


def severity_counts(findings: Iterable[dict]) -> dict:
    out = {"critical": 0, "major": 0, "minor": 0}
    for f in findings:
        if f.get("severity") in out:
            out[f["severity"]] += 1
    return out


def verdict_rule(findings: list[dict], run_status: str = "complete") -> dict:
    """Правило вердикта из контракта (раздел 5). Используется и для «до», и для «после»."""
    if run_status == "failed":
        return {"development": "", "testing": "", "fix_first": []}

    def direction(d: str) -> str:
        crit = [f for f in findings if f.get("severity") == "critical" and f.get("blocks") in (d, "both")]
        if crit:
            return "no"
        majors = [f for f in findings if f.get("severity") == "major" and f.get("blocks") in (d, "both")]
        res = "conditional" if len(majors) >= 3 else "yes"
        if run_status == "partial" and res == "yes":
            res = "conditional"
        return res

    order = sorted((f for f in findings if f.get("severity") in ("critical", "major")),
                   key=lambda f: (int(f.get("priority") or 0) or 99, SEVERITIES.index(f.get("severity", "minor"))))
    return {"development": direction("development"), "testing": direction("testing"),
            "fix_first": [f["id"] for f in order[:7] if f.get("id")]}


def shared_verdict(findings: list[dict], run_status: str = "complete") -> dict:
    """Вердикт по общему правилу каркаса, если оно есть; иначе по ``verdict_rule``."""
    for mod_name, fn_name in (("bcc_review.v2.verdict", "compute"), ("bcc_review.v2.pipeline", "compute_verdict"),
                              ("bcc_review.v2.pipeline", "verdict_rule")):
        try:
            mod = __import__(mod_name, fromlist=[fn_name])
            fn = getattr(mod, fn_name, None)
            if callable(fn):
                v = fn(findings, run_status)
                if isinstance(v, dict) and "development" in v:
                    return v
        except Exception:  # noqa: BLE001
            continue
    return verdict_rule(findings, run_status)


# --------------------------------------------------------------------------- этап
def _format_answers(resolved: dict) -> str:
    rows = []
    for a in resolved["answered"]:
        head = f"{a['question_id']} ({a['topic']}) → дефекты {', '.join(a['finding_ids'])}\n  вопрос: {a['question']}"
        replies = a.get("replies") or []
        if len(replies) > 1:
            rows.append(head + f"\n  ответов несколько ({len(replies)}, разные адресаты) — сверь их между собой; "
                               f"если на одном входе исходы разные, перечисли их ID в conflicting_answers:")
            for r in replies:
                label = f"вариант {r['choice']}: " if r["choice"] else "свой ответ: "
                rows.append(f"  {r['label']}, {label}{r['text']}")
        else:
            label = f"вариант {a['choice']}: " if a["choice"] else "свой ответ: "
            rows.append(head + f"\n  ответ, {label}{a['answer']}")
        for part in a.get("deferred") or []:
            rows.append(f"  владелец не решил (это не правило, дефект по этой части не снимает): {part}")
    for i, d in enumerate(resolved["decisions"], 1):
        rows.append(f"Решение-{i} (общее решение владельца, без номера вопроса): {d}")
    return "\n".join(rows) or "—"


def answer_labels(resolved: dict) -> set[str]:
    """ID ответов, на которые модель может сослаться в ``by``: Q-… с ответом и Решение-1…N."""
    return {a["question_id"] for a in resolved["answered"]} | \
        {r["label"] for a in resolved["answered"] if len(a.get("replies") or []) > 1 for r in a["replies"]} | \
        {f"Решение-{i}" for i in range(1, len(resolved["decisions"]) + 1)}


def _expand(labels: list[str], resolved: dict) -> list[str]:
    """«Q-02» с несколькими репликами → «Q-02.1», «Q-02.2»: каждая реплика — отдельный ответ."""
    multi = {a["question_id"]: [r["label"] for r in a["replies"]]
             for a in resolved["answered"] if len(a.get("replies") or []) > 1}
    out: list[str] = []
    for lab in labels:
        for x in multi.get(lab, [lab]):
            if x not in out:
                out.append(x)
    return out


def answer_text_map(resolved: dict) -> dict[str, str]:
    """ID ответа → текст решения владельца (для судьи новых конфликтов: вторая сторона — сам ответ).
    У вопроса с несколькими репликами есть и метки реплик ``Q-02.1``, ``Q-02.2``."""
    out = {a["question_id"]: str(a.get("answer") or "") for a in resolved["answered"]}
    out.update({r["label"]: str(r.get("text") or "") for a in resolved["answered"]
                if len(a.get("replies") or []) > 1 for r in a["replies"]})
    out.update({f"Решение-{i}": str(d or "") for i, d in enumerate(resolved["decisions"], 1)})
    return out


_CLASH = re.compile(r"противореч|расходятся|несовместим|взаимоисключ|разн\w* исход", re.I)
_LABEL = re.compile(r"(Q\s*-?\s*\d{1,3}(?:\.\d{1,2})?)|(Решени\w*\s*-?\s*\d{1,3})", re.I)


def norm_labels(items: Iterable[str], valid: set[str]) -> list[str]:
    """«q-3», «Q-03», «решение 2» → «Q-03», «Решение-2»; только существующие ответы."""
    # канонический вид → метка как в отчёте: вопрос «Q-1» в старом отчёте и ссылка модели «Q-01» — один ответ
    canon: dict[str, str] = {}
    for v in valid:
        base, _, sub = str(v).partition(".")
        canon[(_qid(base) + (f".{int(sub)}" if sub.isdigit() else "")) if base.upper().startswith("Q") else v] = v
    out: list[str] = []
    for raw in items or []:
        for m in _LABEL.finditer(str(raw)):
            num = re.sub(r"\D", "", m.group(2) or "")
            if m.group(1):
                base, _, sub = m.group(1).partition(".")
                lab = _qid(base) + (f".{int(sub)}" if sub else "")
                if lab not in canon and sub:
                    lab = _qid(base)
            else:
                lab = "Решение-" + str(int(num)) if num else ""
            lab = canon.get(lab, "")
            if lab and lab not in out:
                out.append(lab)
    return out


def _next_candidate_number(report: dict | None, findings: list[dict]) -> int:
    nums = [0]
    pools = list(findings) + list((report or {}).get("rejected") or [])
    for item in pools:
        for cid in list(item.get("candidate_ids") or []) + [item.get("candidate_id") or "", item.get("id") or ""]:
            m = re.match(r"C-(\d+)$", str(cid))
            if m:
                nums.append(int(m.group(1)))
    return max(nums) + 1


def run(ctx: Any, findings: list[dict], answers: Any, questions: list[dict] | None = None,
        report: dict | None = None) -> dict:
    """Пересмотр дефектов по ответам (контракт: ``{"findings": [...], "new_candidates": [...]}``).

    ``findings`` в ответе — все дефекты «до» с полем ``recheck`` (status, reason, severity_after…);
    ``new_candidates`` — сверенные кодом кандидаты новых конфликтов (их судит ``judge``).
    """
    questions = list(questions if questions is not None else (report or {}).get("questions") or [])
    warnings: list[str] = []
    parsed = answers if isinstance(answers, dict) and "answers" in answers and isinstance(answers.get("answers"), list) \
        else load_answers(answers)
    resolved = resolve_answers(questions, parsed, warnings)
    q_by_finding: dict[str, list[str]] = {}
    for a in resolved["answered"]:
        for fid in a["finding_ids"]:
            q_by_finding.setdefault(fid, []).append(a["question_id"])
    # затронутые — дефекты вопросов, на которые дан ответ: по каждому модель решает и объясняет.
    # Остальные модель видит кратко и называет только те, что ответ или общее решение прямо закрывает или
    # меняет (раньше общее решение отправляло на разбор все critical и major — до 23 тыс. токенов ответа).
    affected_ids = set(q_by_finding)
    affected = [f for f in findings if f.get("id") in affected_ids]
    others = [f for f in findings if f.get("id") not in affected_ids]
    open_to_decisions = {f["id"] for f in others if f.get("severity") in ("critical", "major")} \
        if (resolved["decisions"] or resolved["answered"]) else set()

    out_findings = []
    for f in findings:
        g = dict(f)
        g["recheck"] = {"status": "open", "reason": "", "question_ids": q_by_finding.get(f.get("id"), []),
                        "severity_before": f.get("severity"), "severity_after": f.get("severity"),
                        "affected": f.get("id") in affected_ids}
        out_findings.append(g)
    result = {"findings": out_findings, "new_candidates": [], "rejected": [], "answers": resolved, "warnings": warnings}
    if not affected and not resolved["decisions"]:
        for g in out_findings:
            g["recheck"]["reason"] = "ответа на связанный вопрос нет" if not resolved["answered"] else ""
        return _finish(ctx, result)

    block = _format_answers(resolved)
    others_block = _cl.format_findings([f for f in others if f["id"] in open_to_decisions], full=False) or "—"

    def build(items: list) -> tuple[str, str]:
        fb = _cl.format_findings(items)
        system, user = ctx.prompt(STAGE, answers=block, findings=fb, others=others_block)
        if block[:200] not in user:  # шаблон не подставил переменные — вставляем блоки сами
            extra = (f"<ответы>\n{block}\n</ответы>\n\n<затронутые_дефекты>\n{fb}\n</затронутые_дефекты>\n\n"
                     f"<остальные_дефекты>\n{others_block}\n</остальные_дефекты>")
            idx = user.find("Задание: пересмотр")
            user = (user[:idx] + extra + "\n\n" + user[idx:]) if idx >= 0 else (user + "\n\n" + extra)
        return system, user

    try:
        raw = _cl.ask_items(ctx, STAGE, affected, build, SCHEMA, max_output_tokens=32000)
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"recheck: модель не ответила ({type(exc).__name__}: {str(exc)[:200]}); дефекты оставлены открытыми")
        for g in out_findings:
            if g["recheck"]["affected"]:
                g["recheck"]["reason"] = "пересмотр не выполнен: модель не ответила"
        result["status"] = "failed"
        return _finish(ctx, result)

    by_id = {g.get("id"): g for g in out_findings if g.get("id")}
    valid = answer_labels(resolved)
    keep = _cl.doc_codes(getattr(ctx, "view", None))
    for d in _one_decision_per_finding(raw.get("decisions") or []):
        g = by_id.get(str(d.get("finding_id", "")).strip())
        if g is None:
            continue
        status = d.get("status") if d.get("status") in STATUSES else "open"
        cross = None
        if not g["recheck"]["affected"]:
            # дефект вне вопросов с ответом: учитываем, только если ответ его прямо закрывает или меняет
            if g["id"] not in open_to_decisions or status == "open":
                continue
            cross = dict(g["recheck"])
            g["recheck"]["affected"] = True
        rc = g["recheck"]
        # причина — для владельца: без номеров строк L… и ID требований (ID дефектов и ответов остаются ссылками)
        rc["status"], rc["reason"] = status, _plain_reason(str(d.get("reason", "")).strip(), keep)
        # два ответа противоречат друг другу — дефект остаётся открытым, владелец выбирает один ответ
        clash = _expand(norm_labels(list(d.get("conflicting_answers") or []), valid), resolved)
        if len(clash) < 2 and _CLASH.search(rc["reason"]):  # модель описала противоречие ответов только в причине
            clash = _expand(norm_labels([rc["reason"]], valid), resolved)
        if len(clash) >= 2:
            rc["answer_conflict"] = clash
            if status != "open":
                rc["status"], status = "open", "open"
                rc["reason"] = (f"ответы {' и '.join(clash)} противоречат друг другу: " + rc["reason"]).strip(": ")
        # дефект снимает только ответ, который модель назвала прямо (в by или в тексте причины)
        by = norm_labels(list(d.get("by") or []), valid) if status != "open" else []
        if status != "open" and not by:
            by = norm_labels([rc["reason"]], valid)
        if status != "open" and not by:
            rc["status"], status = "open", "open"
            rc["reason"] = ("не назван ответ, который снимает дефект: " + rc["reason"]).strip(": ")
        by = _expand(by, resolved)
        # дефект снимает одна реплика, а другая реплика на тот же вопрос не учтена — исход не согласован
        skipped = [r["label"] for a in resolved["answered"] if len(a.get("replies") or []) > 1
                   and any(r["label"] in by for r in a["replies"]) for r in a["replies"] if r["label"] not in by]
        if status != "open" and skipped:
            rc["status"], status = "open", "open"
            rc["reason"] = (f"не учтён другой ответ на тот же вопрос ({', '.join(skipped)}): " + rc["reason"]).strip(": ")
            by = []
        # дефект не своего вопроса снимается ответом, только если ответ говорит о том же: общие слова у текста
        # ответа (с темой его вопроса) и дефекта. Иначе это перенос решения на чужой дефект — дефект не меняется
        if cross is not None and status != "open" and not _related(by, g, resolved):
            rc.clear()
            rc.update(cross)
            warnings.append(f"recheck: {g['id']}: модель сняла дефект ответом {', '.join(by)}, но ответ говорит "
                            f"о другом — дефект оставлен без изменений")
            continue
        if by:
            rc["answer_ids"] = by
            closing = list(dict.fromkeys(x.split(".")[0] for x in by if x.startswith("Q-")))
            rc["linked_question_ids"] = list(rc["question_ids"])
            rc["question_ids"] = closing
        # ответ своего вопроса с отложенной частью («…, остальное ещё решаем») снимает дефект только частично:
        # нерешённая часть остаётся дефектом прежней серьёзности
        pending = [p for a in resolved["answered"] if a["question_id"] in rc["question_ids"]
                   and g["id"] in a["finding_ids"] for p in a.get("deferred") or []]
        if status == "resolved" and pending:
            rc["status"], status = "changed", "changed"
            d = dict(d, severity=g.get("severity"), title=d.get("title") or g.get("title", ""),
                     problem="Владелец не решил: " + " ".join(pending))
            rc["reason"] = (rc["reason"] + " Часть решения владелец отложил — дефект снят не полностью.").strip()
        if status == "changed":
            sev = d.get("severity") if d.get("severity") in SEVERITIES else g.get("severity")
            # частичный ответ на противоречие снимает его не для всех входов: critical остаётся critical
            if g.get("severity") == "critical" and g.get("kind") in _cl.CONFLICT_KINDS:
                sev = "critical"
            rc["severity_after"] = sev
            if str(d.get("title", "")).strip():
                rc["title_after"] = _cl.plain_text(str(d["title"]).strip(), keep)
            if str(d.get("problem", "")).strip():
                rc["problem_after"] = _cl.plain_text(str(d["problem"]).strip(), keep)
        elif status == "resolved":
            rc["severity_after"] = ""
    for g in out_findings:
        rc = g["recheck"]
        if not rc["affected"] or rc["reason"]:
            continue
        names = ", ".join(rc.get("answer_ids") or [])
        if rc["status"] == "resolved" and names:
            rc["reason"] = f"снят ответом {names}"
        elif rc["status"] == "changed" and names:
            rc["reason"] = f"частично снят ответом {names}"
        else:
            rc["status"], rc["reason"] = "open", "модель не оценила дефект — оставлен открытым"

    n = _next_candidate_number(report, findings)
    answer_texts = answer_text_map(resolved)
    for c in raw.get("candidates") or []:
        lines = [x for f in affected for x in _cl.finding_lines(f)]
        ev = _cl.verified_evidence(ctx.view, c.get("evidence") or [], lines)
        cand = dict(c)
        cand["id"] = f"C-{n:03d}"
        cand["source"] = "recheck"
        n += 1
        if not ev:
            result["rejected"].append({"candidate_id": cand["id"], "title": cand.get("title", ""),
                                       "reason": "цитата не найдена", "source": "recheck"})
            continue
        twin = duplicate_of(ev, findings, str(cand.get("title", "")))
        if twin:  # прежний дефект модель описала заново — это не новый конфликт от ответа
            result["rejected"].append({"candidate_id": cand["id"], "title": cand.get("title", ""),
                                       "reason": f"повторяет дефект {twin}", "source": "recheck"})
            continue
        # новый конфликт — это ответ против места документа: без названного ответа проверить его нельзя
        refs = norm_labels([str(cand.get(k) or "") for k in ("problem", "scenario", "title", "impact")], valid)
        if not refs:
            result["rejected"].append({"candidate_id": cand["id"], "title": cand.get("title", ""),
                                       "reason": "не назван ответ, с которым расходится документ", "source": "recheck"})
            continue
        cand["answer_refs"] = [{"id": r, "text": answer_texts.get(r, "")} for r in refs]
        cand["evidence"] = ev
        cand["line_start"], cand["line_end"] = ev[0]["line_start"], ev[0]["line_end"]
        result["new_candidates"].append(cand)
    return _finish(ctx, result)


def _plain_reason(text: str, keep: set[str]) -> str:
    """Причина решения: номера строк «L064» → «стр. 64»; «Q-03», «D-05», «R-12» и «Решение-1»
    остаются — это ссылки на вопросы и дефекты отчёта, по ним видно, какой ответ снял дефект."""
    protected: dict[str, str] = {}

    def hide(m: re.Match) -> str:
        key = f"\x00{len(protected)}\x00"
        protected[key] = m.group(0)
        return key
    s = re.sub(r"\b(?:Q|D|R)-\d{1,3}\b", hide, text)
    s = _cl.plain_text(s, keep)
    for key, val in protected.items():
        s = s.replace(key, val)
    return s


def duplicate_of(evidence: list[dict], findings: list[dict], title: str = "", slack: int = 1) -> str:
    """ID прежнего дефекта, который новый кандидат описывает заново, иначе пустая строка.

    Новый конфликт от ответа цитирует место, которое теперь противоречит ответу. Если все его цитаты —
    строки одного прежнего дефекта (±``slack``), это тот же дефект (закрытый ответом или оставшийся открытым):
    для двух и более строк хватает совпадения строк, для одной строки нужна ещё та же суть в заголовке."""
    cand = {int(e["line_start"]) for e in evidence if e.get("line_start")}
    if not cand:
        return ""
    words = _tokens(_cl.plain_text(title))
    for f in findings:
        own = {int(x) for x in _cl.finding_lines(f)}
        if not own or not all(any(abs(c - o) <= slack for o in own) for c in cand):
            continue
        if len(cand) >= 2:
            return str(f.get("id", ""))
        theirs = _tokens(f"{f.get('title', '')} {f.get('problem', '')}")
        if words and len(words & theirs) / len(words) >= 0.4:
            return str(f.get("id", ""))
    return ""


def _related(labels: list[str], finding: dict, resolved: dict) -> bool:
    """У ответов и дефекта не меньше двух общих основ слов (ответ на вопрос — вместе с темой вопроса)."""
    texts = answer_text_map(resolved)
    topics = {a["question_id"]: f"{a.get('topic', '')} {a.get('question', '')}" for a in resolved["answered"]}
    said: set[str] = set()
    for x in labels:
        said |= _tokens(texts.get(x, "")) | _tokens(topics.get(x.split(".")[0], ""))
    quotes = " ".join(str(e.get("quote", "")) for e in finding.get("evidence") or [] if isinstance(e, dict))
    about = _tokens(" ".join(str(finding.get(k) or "") for k in
                             ("title", "problem", "scenario", "impact", "recommendation", "rewrite")) + " " + quotes)
    return len(said & about) >= 2


def _one_decision_per_finding(decisions: list) -> list[dict]:
    """Модель (или два пакета ``ask_items``) дала по дефекту несколько решений — берём самое осторожное:
    с конфликтом ответов, затем open, changed, resolved. Порядок дефектов сохраняется."""
    rank = {"resolved": 0, "changed": 1, "open": 2}
    best: dict[str, dict] = {}
    for d in decisions:
        if not isinstance(d, dict):
            continue
        fid = str(d.get("finding_id", "")).strip()
        key = (len(d.get("conflicting_answers") or []) >= 2, rank.get(d.get("status"), 2))
        prev = best.get(fid)
        if prev is None or key > (len(prev.get("conflicting_answers") or []) >= 2, rank.get(prev.get("status"), 2)):
            best[fid] = d
    return list(best.values())


def _force_choice_conflicts(result: dict) -> None:
    """Разные буквы вариантов на один вопрос — дефекты вопроса остаются open с ``answer_conflict``,
    что бы ни решила модель: варианты вопроса взаимоисключающие, владелец должен выбрать один."""
    for a in result["answers"]["answered"]:
        clash = a.get("choice_conflict") or []
        if len(clash) < 2:
            continue
        for g in result["findings"]:
            if g.get("id") not in a["finding_ids"]:
                continue
            rc = g["recheck"]
            rc["affected"] = True
            rc["answer_conflict"] = list(dict.fromkeys(list(rc.get("answer_conflict") or []) + clash))
            if rc["status"] != "open" or "противореч" not in rc["reason"]:
                rc["status"], rc["severity_after"] = "open", g.get("severity")
                rc.pop("answer_ids", None)
                rc.pop("title_after", None)
                rc.pop("problem_after", None)
                rc["reason"] = f"ответы {' и '.join(clash)} выбирают разные варианты одного вопроса — выберите один"
    # общее решение из спорящих реплик (вопроса в прогоне нет) не снимает дефект: значение не согласовано
    for c in result["answers"].get("decision_conflicts") or []:
        labels = set(c["answers"])
        for g in result["findings"]:
            rc = g["recheck"]
            if rc["status"] == "open" or not labels & set(rc.get("answer_ids") or []):
                continue
            rc["status"], rc["severity_after"] = "open", g.get("severity")
            rc["answer_conflict"] = list(dict.fromkeys(list(rc.get("answer_conflict") or []) + c["answers"]))
            for k in ("answer_ids", "title_after", "problem_after"):
                rc.pop(k, None)
            rc["reason"] = (f"ответы адресатов на «{c['topic']}» расходятся ({' и '.join(c['answers'])}) — "
                            f"выберите одно значение")


def _finish(ctx: Any, result: dict) -> dict:
    _force_choice_conflicts(result)
    for w in result.get("warnings", []):
        _cl._warn(ctx, w)
    return result


def findings_after(rechecked: list[dict]) -> list[dict]:
    """Дефекты, которые остаются после ответов: без resolved, changed — с новой серьёзностью и текстом."""
    out = []
    for g in rechecked:
        rc = g.get("recheck") or {}
        if rc.get("status") == "resolved":
            continue
        h = {k: v for k, v in g.items() if k != "recheck"}
        if rc.get("status") == "changed":
            h["severity"] = rc.get("severity_after") or h.get("severity")
            h["title"] = rc.get("title_after") or h.get("title")
            h["problem"] = rc.get("problem_after") or h.get("problem")
        h["status_after_answers"] = rc.get("status", "open")
        out.append(h)
    return out


def _judge_new(ctx: Any, candidates: list[dict], start_n: int, warnings: list[str],
               old: Iterable[dict] = ()) -> tuple[list[dict], list[dict]]:
    """Новые кандидаты → судья (№10). Без судьи — кандидат становится дефектом как есть.

    Судья может переписать кандидата в прежний дефект (на официальном haiku: «ключ повторной доставки не
    задан» — его как раз закрыло общее решение): такой «новый» дефект — дубль, он отклоняется."""
    if not candidates:
        return [], []
    try:
        from bcc_review.v2.stages import judge  # type: ignore
        res = judge.run(ctx, [for_judge(c) for c in candidates]) or {}
        found, rejected = list(res.get("findings") or []), list(res.get("rejected") or [])
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"recheck: судья недоступен для новых кандидатов ({type(exc).__name__}); приняты как есть")
        found = [{"id": "", "candidate_ids": [c["id"]], "title": c.get("title", ""), "kind": c.get("kind", "other"),
                  "criterion": c.get("criterion", "set_consistent"), "standard_refs": [],
                  "severity": c.get("severity", "major"), "requirement_ids": c.get("requirement_ids", []),
                  "evidence": c.get("evidence", []), "problem": c.get("problem", ""), "scenario": c.get("scenario", ""),
                  "impact": c.get("impact", ""), "recommendation": c.get("recommendation", ""),
                  "rewrite": c.get("rewrite", ""), "question": c.get("question", ""), "blocks": c.get("blocks", "both"),
                  "priority": 0, "sources": ["recheck"]} for c in candidates]
        rejected = []
    keep = _cl.doc_codes(getattr(ctx, "view", None))
    by_cand = {c["id"]: c for c in candidates}
    old = list(old)
    if old:
        fresh = []
        for f in found:
            twin = duplicate_of(f.get("evidence") or [], old, str(f.get("title") or ""))
            if twin:
                rejected.append({"candidate_id": ", ".join(f.get("candidate_ids") or []), "title": f.get("title", ""),
                                 "reason": f"повторяет дефект {twin}", "source": "recheck"})
            else:
                fresh.append(f)
        found = fresh
    for i, f in enumerate(found):
        refs = [r["id"] for cid in f.get("candidate_ids") or [] for r in by_cand.get(cid, {}).get("answer_refs") or []]
        refs = list(dict.fromkeys(refs))
        if HINT in str(f.get("problem") or ""):  # судья повторил подсказку — владельцу нужен исходный текст
            orig = next((by_cand[c] for c in f.get("candidate_ids") or [] if c in by_cand), {})
            f["problem"] = str(orig.get("problem") or "")
        for key in ("title", "problem", "scenario", "impact", "recommendation", "question"):
            if isinstance(f.get(key), str):  # ссылки на ответы (Q-…) — не внутренние коды, их владелец видит
                f[key] = _cl.plain_text(f[key], keep | set(refs))
        # служебные хвосты судьи о ненайденной ссылке («Ссылка «» в документе не найдена») владельцу не нужны
        if isinstance(f.get("problem"), str) and "«»" in f["problem"]:
            f["problem"] = " ".join(x for x in re.split(r"(?<=[.!?])\s+(?=[А-ЯЁA-Z])", f["problem"]) if "«»" not in x).strip()
        if refs:
            # владелец видит, какой его ответ породил конфликт
            f["answer_ids"] = refs
            if not any(r in str(f.get("problem") or "") for r in refs):
                f["problem"] = f"После ответа {', '.join(refs)}: {f.get('problem') or ''}".strip()
        f["id"] = f"D-{start_n + i:02d}"
        f.setdefault("sources", ["recheck"])
        if "recheck" not in f["sources"]:
            f["sources"] = list(f["sources"]) + ["recheck"]
        f["status_after_answers"] = "new"
    return found, rejected


ANSWER_QUOTE_CHARS = 240
HINT = "Решение владельца, которое будет вписано в документ"


def for_judge(c: dict) -> dict:
    """Кандидат нового конфликта для судьи: одна сторона — цитата документа, вторая — решение владельца.
    Судья видит только документ, поэтому без текста ответа отклонял настоящий конфликт как «не подтверждён»;
    текст ответа идёт первым в ``problem`` (судья показывает его первые 420 знаков)."""
    refs = c.get("answer_refs") or []
    if not refs:
        return c
    said = "; ".join(f"{r['id']} — «{_cut(r.get('text', ''), ANSWER_QUOTE_CHARS)}»" for r in refs if r.get("text"))
    if not said:
        return c
    out = dict(c)
    out["problem"] = (f"{HINT}: {said}. С ним расходится место документа в цитате, которое ответ не меняет. "
                      f"{c.get('problem') or ''}").strip()
    return out


def _cut(text: str, n: int) -> str:
    t = re.sub(r"\s+", " ", str(text or "")).strip()
    return t if len(t) <= n else t[: n - 1].rstrip() + "…"


def apply_answers(ctx: Any, report: dict, answers: Any) -> dict:
    """Весь режим ``--answers`` одним вызовом для pipeline (№01).

    Принимает собранный отчёт (``findings``, ``questions``, ``verdict``, ``run.status``) и ответы.
    Возвращает ``{"clarification": {...}, "findings_after": [...], "rejected_after": [...]}``;
    ``clarification`` кладётся в ``report.json`` как есть и рендерится таблицей «до / после».
    """
    findings = list(report.get("findings") or [])
    status = (report.get("run") or {}).get("status", "complete")
    rc = run(ctx, findings, answers, report.get("questions") or [], report)
    warnings = rc.get("warnings", [])
    remaining = findings_after(rc["findings"])
    max_d = max([int(m.group(1)) for f in findings for m in [re.match(r"D-(\d+)$", str(f.get("id", "")))] if m] or [0])
    new_found, new_rejected = _judge_new(ctx, rc["new_candidates"], max_d + 1, warnings, findings)
    after = remaining + new_found
    before_v = report.get("verdict") or {}
    before_rule = shared_verdict(findings, status)
    v_before = {"development": before_v.get("development") or before_rule["development"],
                "testing": before_v.get("testing") or before_rule["testing"]}
    after_rule = shared_verdict(after, "partial" if rc.get("status") == "failed" and status == "complete" else status)
    changes = []
    for g in rc["findings"]:
        r = g["recheck"]
        if not r.get("affected"):
            continue
        changes.append({"finding_id": g["id"], "title": g.get("title", ""), "severity_before": r["severity_before"],
                        "status": r["status"], "severity_after": r["severity_after"], "reason": r["reason"],
                        "question_ids": r["question_ids"], "answer_ids": r.get("answer_ids", []),
                        "answer_conflict": r.get("answer_conflict", []),
                        "title_after": r.get("title_after", "")})
    order = {"resolved": 0, "changed": 1, "open": 2}
    changes.sort(key=lambda c: (order.get(c["status"], 3), SEVERITIES.index(c["severity_before"] or "minor")))
    # вопрос без прямого ответа, все дефекты которого сняты общими решениями, — не «без ответа»
    status_by_id = {c["finding_id"]: c["status"] for c in changes}
    q_by_id = {q.get("id"): q for q in report.get("questions") or []}
    closed = [qid for qid in rc["answers"]["unanswered"]
              if rc["answers"]["decisions"] and q_by_id.get(qid, {}).get("finding_ids")
              and all(status_by_id.get(fid) == "resolved" for fid in q_by_id[qid]["finding_ids"])]
    texts = answer_text_map(rc["answers"])
    clar = {
        "answers": rc["answers"]["answered"],
        "decisions": rc["answers"]["decisions"],
        "unanswered": [q for q in rc["answers"]["unanswered"] if q not in closed],
        "closed_by_decisions": closed,
        "postponed": list(rc["answers"].get("postponed") or []),
        "changes": changes,
        "new_findings": [f["id"] for f in new_found],
        # тексты спорящих ответов — чтобы владелец видел, из чего выбирать, а не только метки «Q-02.1 ↔ Q-02.2»
        "answer_conflicts": [{"finding_id": c["finding_id"], "answers": c["answer_conflict"], "reason": c["reason"],
                              "texts": {x: texts.get(x, "") for x in c["answer_conflict"]}}
                             for c in changes if c.get("answer_conflict")],
        "before": {"verdict": v_before, "findings": severity_counts(findings)},
        "after": {"verdict": {"development": after_rule["development"], "testing": after_rule["testing"],
                              "fix_first": after_rule.get("fix_first", [])},
                  "findings": severity_counts(after)},
        "resolved": sum(1 for c in changes if c["status"] == "resolved"),
        "changed": sum(1 for c in changes if c["status"] == "changed"),
        "open": sum(1 for c in changes if c["status"] == "open"),
        "warnings": warnings,
        "status": rc.get("status", "ok"),
    }
    clar["answer_conflicts"] = _orphan_conflicts(rc["answers"], clar["answer_conflicts"])
    clar["next_round"] = next_round(clar, report.get("questions") or [])
    return {"clarification": clar, "findings_after": after,
            "rejected_after": list(rc.get("rejected") or []) + new_rejected}


# --------------------------------------------------------------------------- следующий круг ответов
def _one_line(text: Any) -> str:
    return " ".join(str(text or "").split())


def _head(qid: str, topic: str) -> str:
    return f"{qid} [{_one_line(topic).replace('[', '(').replace(']', ')')}]: " if topic else f"{qid}: "


def next_round(clar: dict, questions: list[dict]) -> list[dict]:
    """Что осталось решить после ответов — готовыми строками файла ответов (идея: уточняющий вопрос на дефект,
    который ответ не закрыл). ``kind``: ``conflict`` — ответы расходятся, оставить одну строку; ``partial`` —
    решена часть, вписать решение вместо «<решите: …>»; ``postponed`` — решение отложено целиком. Строки с темой в скобках: номер вопроса в следующем
    прогоне может смениться, привязка идёт по теме."""
    topic = {q.get("id"): q.get("topic", "") for q in questions if isinstance(q, dict)}
    answered = {a["question_id"]: a for a in clar.get("answers") or []}
    for qid, a in answered.items():
        topic[qid] = a.get("topic") or topic.get(qid, "")
    status = {c["finding_id"]: c["status"] for c in clar.get("changes") or []}
    out: list[dict] = []
    for c in clar.get("answer_conflicts") or []:
        texts = c.get("texts") or {}
        qids = list(dict.fromkeys(x.split(".")[0] for x in c["answers"] if str(x).startswith("Q-")))
        sides = [_one_line(texts.get(x)) for x in c["answers"] if _one_line(texts.get(x))]
        if qids:
            lines = list(dict.fromkeys(_head(qids[0], topic.get(qids[0], "")) + t for t in sides))
        else:  # спорят общие решения: в разделе «## Решения» остаётся одно
            lines = list(dict.fromkeys(f"- {t}" for t in sides))
        if len(lines) >= 2:
            out.append({"kind": "conflict", "finding_id": c["finding_id"], "question_id": qids[0] if qids else "",
                        "lines": lines})
    asked = {q.get("id"): _one_line(q.get("question")) for q in questions if isinstance(q, dict)}
    by_q: dict[str, list[str]] = {}
    for p in clar.get("postponed") or []:
        # весь ответ отложен — решить нужно сам вопрос; отложена часть — эту часть словами владельца
        part = _one_line(p.get("text")) if p.get("partial") or not asked.get(p["question_id"]) \
            else asked[p["question_id"]]
        by_q.setdefault(p["question_id"], []).append(_TODO_WRAP.sub("", part))
    for qid, parts in by_q.items():
        a = answered.get(qid)
        fids = list((a or {}).get("finding_ids") or next((q.get("finding_ids") or [] for q in questions
                                                           if isinstance(q, dict) and q.get("id") == qid), []))
        if fids and all(status.get(f) == "resolved" for f in fids):
            continue
        todo = " ".join("<решите: " + re.sub(r"[.!?;<>]+", ",", x).strip(" ,") + ">" for x in parts if x)
        rule = ""
        if a and len(a.get("replies") or []) <= 1:
            rule = _one_line(a.get("answer"))
            rule = rule if not rule or rule.endswith((".", "!", "?")) else rule + "."
        out.append({"kind": "partial" if a else "postponed", "finding_id": ", ".join(fids), "question_id": qid,
                    "lines": [_head(qid, topic.get(qid, "")) + (rule + " " if rule else "") + todo]})
    # без ответа: вопрос, варианты и что будет без ответа — пояснением (строку ответа владелец пишет сам)
    for q in questions:
        qid = q.get("id") if isinstance(q, dict) else None
        if not qid or qid not in (clar.get("unanswered") or []) or qid in by_q:
            continue
        opts = "; ".join(f"{_cl.option_label(i)} — {_one_line(o)}" for i, o in enumerate(q.get("options") or []))
        note = f"{_one_line(q.get('question'))}" + (f" Варианты: {opts}." if opts else "")
        if q.get("if_no_answer"):
            note += f" Если ответа не будет: {q['if_no_answer']}."
        out.append({"kind": "unanswered", "finding_id": ", ".join(q.get("finding_ids") or []), "question_id": qid,
                    "lines": [], "note": note, "head": _head(qid, q.get("topic", "")).rstrip()})
    return out


def render_next_answers(clar: dict, document: str = "", report: str = "") -> str:
    """Файл ответов для следующего круга: что решить (расхождения, отложенное) и всё уже согласованное — чтобы
    повторный ``--answers`` не потерял прежние ответы. Пояснения — строками «>»: разбор ответов их пропускает."""
    todo = clar.get("next_round") or []
    busy = {n["question_id"] for n in todo if n.get("question_id")}
    lines = ["# Ответы владельца: следующий круг", "",
             "> При расхождении оставьте одну строку на вопрос; вместо «<решите: …>» впишите решение.",
             "> Строки «Уже согласовано» не меняйте, если решение то же: без них повторный прогон их потеряет."]
    if document or report:
        lines.append(f"> Запуск: python -m bcc_review.v2 review {document or 'ДОКУМЕНТ'} {report or 'ОТЧЁТ.md'} "
                     f"--answers ЭТОТ_ФАЙЛ")
    lines.append("")
    if todo:
        lines += ["## Что решить", ""]
        for n in todo:
            if n["kind"] == "unanswered":
                lines += [f"> {n['question_id']} ({n['finding_id']}): без ответа. {n.get('note', '')}",
                          f"> Ответ — строкой «{n.get('head') or n['question_id'] + ':'} буква или свой текст».", ""]
                continue
            what = {"conflict": "ответы расходятся, оставьте одну строку",
                    "partial": "решена только часть, допишите решение"}.get(n["kind"], "решение отложено, впишите его")
            lines += [f"> {n.get('question_id') or 'Общие решения'} ({n['finding_id']}): {what}", *n["lines"], ""]
    agreed = []
    for a in clar.get("answers") or []:
        if a["question_id"] in busy:
            continue
        head = _head(a["question_id"], a.get("topic", ""))
        replies = a.get("replies") or []
        if len(replies) > 1:
            agreed += [head + _one_line(r.get("text")) for r in replies]
        elif a.get("choice"):
            agreed.append(head + f"{a['choice']} — " + _one_line(a.get("answer")))
        else:
            agreed.append(head + _one_line(a.get("answer")))
    if agreed:
        lines += ["## Уже согласовано", "", *agreed, ""]
    decided = [d for d in clar.get("decisions") or [] if _one_line(d)]
    if decided:
        lines += ["## Решения", "", *[f"- {_one_line(d)}" for d in decided], ""]
    rest = [q for q in clar.get("unanswered") or [] if q not in busy
            and not any(n.get("question_id") == q for n in todo)]
    if rest:
        lines += [f"> Без ответа остаются: {', '.join(rest)}. Ответ можно дописать строкой «{rest[0]} [тема]: ответ» "
                  f"в раздел выше.", ""]
    return "\n".join(lines).rstrip() + "\n"


def next_answers_path(report_path: str | Path) -> Path:
    p = Path(report_path)
    return p.with_name(p.stem + ".answers-next.md") if p.suffix else p.with_name(p.name + ".answers-next.md")


# --------------------------------------------------------------------------- Markdown-раздел (для №13)
_V = {"no": "нельзя", "conditional": "можно с условиями", "yes": "можно", "": "—"}
_S = {"critical": "критичный", "major": "существенный", "minor": "незначительный", "": "—"}
_ST = {"resolved": "закрыт", "changed": "изменён", "open": "открыт", "new": "новый"}


def _short(text: str, limit: int = 160) -> str:
    text = " ".join(str(text or "").split()).replace("|", "/")
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def render_markdown(clar: dict, findings_after: list[dict] | None = None) -> str:
    """Раздел отчёта «Уточнение: до и после» (№13 может вставить как есть или нарисовать сам)."""
    b, a = clar["before"], clar["after"]
    lines = ["## Уточнение: до и после ответов владельца", "",
             f"Ответов на вопросы: {len(clar['answers'])}, общих решений: {len(clar['decisions'])}, "
             f"закрыто общими решениями: {len(clar.get('closed_by_decisions') or [])}, "
             f"без ответа: {len(clar['unanswered'])}. Оценка «после» предполагает, что ответы внесены в документ "
             f"(см. исправленную редакцию).", "",
             "| Показатель | До уточнения | После уточнения |", "| :--- | :--- | :--- |",
             f"| Начинать разработку | {_V.get(b['verdict'].get('development', ''), '—')} | "
             f"{_V.get(a['verdict'].get('development', ''), '—')} |",
             f"| Начинать тестирование | {_V.get(b['verdict'].get('testing', ''), '—')} | "
             f"{_V.get(a['verdict'].get('testing', ''), '—')} |"]
    for sev in SEVERITIES:
        lines.append(f"| Дефекты: {_S[sev]} | {b['findings'][sev]} | {a['findings'][sev]} |")
    lines += ["", f"Закрыто: {clar['resolved']}, изменено: {clar['changed']}, осталось открытыми: {clar['open']}, "
                  f"новых конфликтов из-за ответов: {len(clar['new_findings'])}.", ""]
    if clar["changes"]:
        lines += ["| Дефект | Было | Статус | Стало | Почему | Ответ |", "| :--- | :--- | :--- | :--- | :--- | :--- |"]
        for c in clar["changes"]:
            reason = c["reason"].replace("|", "/").replace("\n", " ")
            lines.append(f"| {c['finding_id']} {c['title'].replace('|', '/')} | {_S.get(c['severity_before'], '—')} | "
                         f"{_ST.get(c['status'], c['status'])} | {_S.get(c['severity_after'] or '', '—')} | {reason} | "
                         f"{', '.join(c['question_ids']) or 'общее решение'} |")
        lines.append("")
    if clar.get("answer_conflicts"):
        lines.append("Ответы, которые противоречат друг другу (выберите один):")
        for c in clar["answer_conflicts"]:
            texts = c.get("texts") or {}
            sides = " ↔ ".join(f"{x} «{_short(texts[x])}»" if texts.get(x) else x for x in c["answers"])
            where = c.get("finding_id") or (f"{c['question_id']} [{c.get('topic', '')}]" if c.get("question_id") else "")
            lines.append(f"* {sides} — {where}: {c['reason']}" if where else f"* {sides} — {c['reason']}")
        lines.append("")
    if clar.get("postponed"):
        lines.append("Владелец отложил решение — это не ответ, дефект по этой части остаётся открытым:")
        for p in clar["postponed"]:
            how = "часть ответа" if p.get("partial") else "весь ответ"
            lines.append(f"* {p['question_id']} ({how}): «{p['text']}»")
        lines.append("")
    if clar["new_findings"] and findings_after:
        by_id = {f["id"]: f for f in findings_after}
        lines.append("Новые конфликты, которые порождают ответы:")
        for fid in clar["new_findings"]:
            f = by_id.get(fid, {})
            ev = "; ".join(f"строка {e['line_start']}: «{e['quote']}»" for e in f.get("evidence", []))
            lines.append(f"* **{fid}** ({_S.get(f.get('severity', ''), '—')}) {f.get('title', '')}. {ev}")
        lines.append("")
    return "\n".join(lines)
