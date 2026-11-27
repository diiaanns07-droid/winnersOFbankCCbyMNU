"""Правила контракта API: тип запроса, тело, коды ответа, типы полей.

Работают на любом ТЗ с описанием REST-методов: распознают таблицы «REST type / Request URL»,
перечни статусов («200. …», строки таблицы «| 404 | …», «Ответ 200»), таблицы параметров
(«Parameter | Format …»). Словари — общие для HTTP, слов конкретного документа здесь нет.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from ._text import Doc, Line, Table, candidate, cell_quote, ev, fmt_list, norm, quoted, signal, tables

HTTP_VERBS = ("GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS")
SAFE_VERBS = ("GET", "HEAD")

VERB_KEYS = ("rest type", "http method", "http-метод", "метод запроса", "тип запроса", "method", "http verb",
             "метод", "тип метода", "http")
URL_KEYS = ("request url", "url", "endpoint", "адрес", "путь", "path")
DESC_KEYS = ("description", "описание", "назначение")

# Первое слово имени метода или сегмента пути, означающее изменение состояния.
MUTATING_TOKENS = {
    "save", "update", "set", "delete", "remove", "create", "add", "edit", "change", "modify", "replace",
    "reset", "enable", "disable", "cancel", "confirm", "activate", "deactivate", "block", "unblock",
    "write", "insert", "upsert", "submit", "register", "assign", "apply", "approve", "reject", "store",
    "put", "post", "patch", "close", "lock", "unlock", "revoke", "transfer", "pay", "send",
}
READ_TOKENS = {"get", "read", "list", "fetch", "find", "search", "check", "load", "view", "show", "query",
               "status", "info", "details", "history", "calc", "calculate", "compute", "estimate", "preview",
               "quote", "lookup"}
# Начало описания метода, означающее изменение состояния.
MUTATING_DESC = re.compile(
    r"^(сохранени|изменени|удалени|создани|обновлени|замен|установк|установлени|отключени|включени|"
    r"блокировк|разблокировк|отмен|добавлени|редактировани|запис|регистраци|подтверждени|перевод|списани)",
    re.I)

REASON_PHRASES = [
    (re.compile(r"\bno content\b", re.I), 204), (re.compile(r"\bcreated\b", re.I), 201),
    (re.compile(r"\baccepted\b", re.I), 202), (re.compile(r"\bbad request\b", re.I), 400),
    (re.compile(r"\bunauthori[sz]ed\b", re.I), 401), (re.compile(r"\bforbidden\b", re.I), 403),
    (re.compile(r"\bnot found\b", re.I), 404), (re.compile(r"\bmethod not allowed\b", re.I), 405),
    (re.compile(r"\bconflict\b", re.I), 409), (re.compile(r"\bunprocessable\b", re.I), 422),
    (re.compile(r"\btoo many requests\b", re.I), 429),
    (re.compile(r"\binternal server error\b", re.I), 500), (re.compile(r"\bbad gateway\b", re.I), 502),
    (re.compile(r"\bservice unavailable\b", re.I), 503), (re.compile(r"\bgateway timeout\b", re.I), 504),
]

CODE = r"[1-5]\d\d"
UNIT_AFTER = re.compile(
    r"^\s*(?:мс|ms|сек\w*|мин\w*|час\w*|₸|тенге|тиын\w*|руб\w*|коп\w*|%|запрос\w*|шт|раз\b|"
    r"символ\w*|знак\w*|бит|bit|байт|kb|кб|мб|mb|гб|gb|rps|tps|дн\w*|сут\w*|₽|\$|usd|eur|kzt)", re.I)
MENTION = re.compile(
    r"(?:возвра\w*|верн\w*|результат\w*|статус\w*|код\w*|ответ\w*|http)\s*:?\s+(?:код\w*\s+|статус\w*\s+)?"
    rf"({CODE}(?:\s*(?:,|или|либо|и|/)\s*{CODE})*)",
    re.I)
DECL_LIST = re.compile(rf"^(?:HTTP\s+)?({CODE})(?:\s*[.:)]\s*\S|\s+[A-Za-z][A-Za-z \-]{{1,30}}?\s*[—–:\-]\s*\S|\s*[—–]\s*\S)")
DECL_OTVET = re.compile(rf"^(?:ответ|response)\s+({CODE})\b", re.I)
BARE_CODE = re.compile(rf"^({CODE})\.?$")
DECL_LIST_INLINE = re.compile(rf"(?<=[.!?»)]\s)({CODE})\.\s+[А-ЯЁA-Z]")
DECL_INLINE = re.compile(rf"\b(?:Ответ|Статус|Код\s+ответа)\s+({CODE})\s*[—–:\-]\s*\S", re.I)
ERROR_JSON = re.compile(
    r'"(?:result|status|state)"\s*:\s*"(error|fail\w*|err|failure|declined|rejected)"|"error"\s*:|'
    r'"success"\s*:\s*false', re.I)
ERROR_WORD = re.compile(r"\b(ERROR|FAIL(?:ED|URE)?)\b|ошибк\w*", re.I)


def _has_error(text: str) -> re.Match | None:
    """Признак ошибки в тексте; «не считается ошибкой» и «без ошибок» — не ошибка."""
    for m in ERROR_WORD.finditer(text):
        before = text[max(0, m.start() - 25):m.start()].lower()
        if m.group(0)[0].islower() and re.search(r"\bне\s+(?:считается|является|будет|приводит\s+к)\s*$|\bбез\s*$",
                                                  before):
            continue
        return m
    return None
NO_BODY = re.compile(
    r"тело\s+(?:запроса\s+)?не\s+(?:используется|передаётся|передается|требуется|предусмотрено)|"
    r"без\s+тела|тело\s+(?:запроса\s+)?отсутствует|тело\s+запроса\s*[:\-—–]\s*(?:нет|отсутствует|не используется)|"
    r"request body\s*[:\-—–]\s*(?:none|no|нет|-)|body is not used", re.I)
CONTENT_TYPE = re.compile(r"content-type", re.I)

TYPE_MAP = [
    (re.compile(r"^(int|integer|int32|int64|long|short|целое|целое число|bigint)\b", re.I), "integer"),
    (re.compile(r"^(number|decimal|float|double|numeric|число|дробное|money|amount)\b", re.I), "number"),
    (re.compile(r"^(string|str|строка|text|текст|varchar|char)\b", re.I), "string"),
    (re.compile(r"^(bool|boolean|логическ\w*|флаг)\b", re.I), "boolean"),
    (re.compile(r"^(date|datetime|timestamp|дата\w*)\b", re.I), "date"),
    (re.compile(r"^(object|объект|json)\b", re.I), "object"),
    (re.compile(r"^(array|list|массив|список)\b", re.I), "array"),
]
NAME_COLS = ("parameter", "параметр", "поле", "field", "name", "имя", "атрибут", "attribute")
TYPE_COLS = ("format", "формат", "type", "тип")
IDENT = re.compile(r"^[A-Za-z_][\w.\[\]]*$")


def _slug(s: str) -> str:
    """Короткий идентификатор предмета для `source` (разные методы — разные кластеры у судьи)."""
    return re.sub(r"[^A-Za-z0-9]+", "_", s).strip("_")[:40] or "x"


def split_camel(name: str) -> list[str]:
    parts = re.split(r"[_\-./]+", name)
    out: list[str] = []
    for p in parts:
        out += [t.lower() for t in re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])|\d+", p)]
    return out


@dataclass
class Method:
    verb: str
    verb_line: Line
    start: int
    end: int = 10 ** 9
    name: str = ""
    name_line: Line | None = None
    url: str = ""
    url_line: Line | None = None
    desc: str = ""
    desc_line: Line | None = None
    curl_line: Line | None = None
    lines: list[Line] = field(default_factory=list)

    @property
    def label(self) -> str:
        return self.name or self.url

    def mutating_reason(self) -> tuple[str, Line | None] | None:
        if self.name:
            toks = split_camel(self.name)
            if toks and toks[0] in MUTATING_TOKENS:
                return (f"имя метода {self.name}", self.name_line or self.url_line)
        if self.url:
            segs = [s for s in re.split(r"[/?]", self.url) if s and not s.startswith("{") and ":" not in s]
            if segs:
                toks = split_camel(segs[-1])
                if toks and toks[0] in MUTATING_TOKENS:
                    return (f"путь {self.url}", self.url_line)
        if self.desc and MUTATING_DESC.match(self.desc.strip()):
            return (f"описание «{self.desc.split('.')[0].strip()}»", self.desc_line)
        return None

    def is_read(self) -> bool:
        if self.verb in SAFE_VERBS and not self.mutating_reason():
            return True
        toks = split_camel(self.name) if self.name else []
        return bool(toks and toks[0] in READ_TOKENS)


def _kv(line: Line) -> tuple[str, str] | None:
    if line.cells and len(line.cells) >= 2:
        return norm(line.cells[0]).rstrip(":"), line.cells[1]
    m = re.match(r"^([A-Za-zА-Яа-яЁё \-]{2,30}):\s*(.+)$", line.text)
    if m:
        return norm(m.group(1)), m.group(2)
    return None


METHOD_HEADING = re.compile(r"^(?:метод|method|операция|endpoint)\s+[«\"]?([A-Za-z_][\w]*)[»\"]?\s*$", re.I)
VERB_PATH = re.compile(r"^(GET|HEAD|POST|PUT|PATCH|DELETE)\s+(/\S*)")
# метод в строке текста: «Эндпоинт сохранения: PUT /cards/{id}/limit», «Метод: GET /x — …»
INLINE_METHOD = re.compile(r"^(?P<lead>[^:|]{0,60}?(?:эндпоинт|endpoint|метод|операци\w*|адрес|запрос)\w*[^:|]{0,40}):\s*"
                           r"(?P<verb>GET|HEAD|POST|PUT|PATCH|DELETE)\s+(?P<url>/[\w\-{}/.]*[\w}])", re.I)


def find_methods(doc: Doc) -> list[Method]:
    L = doc.lines
    methods: list[Method] = []
    row_methods: list[Method] = []
    for idx, x in enumerate(L):
        if not x.text or x.is_code:
            continue
        verb = None
        kv = _kv(x)
        if kv and any(kv[0] == k or kv[0].startswith(k + " ") for k in VERB_KEYS):
            m = re.match(r"^\s*(GET|HEAD|POST|PUT|PATCH|DELETE|OPTIONS)\b", kv[1].strip(), re.I)
            if m:
                verb = m.group(1).upper()
        if verb is None:
            m = VERB_PATH.match(x.text)
            if m and x.cells is None and not x.is_code:
                verb = m.group(1).upper()
        if verb is None and x.cells is None:
            im = INLINE_METHOD.match(x.text)
            if im and not any(mm.verb == im.group("verb").upper() and mm.url == im.group("url") for mm in methods):
                rest = x.text[im.end():].strip(" .—–-")
                meth = Method(verb=im.group("verb").upper(), verb_line=x, start=x.n, url=im.group("url"), url_line=x,
                              desc=(im.group("lead").strip() + (" — " + rest if rest else "")), desc_line=x)
                methods.append(meth)
                continue
        if verb is None and x.cells:
            # сводная таблица методов: «| 3. Данные QR | GET `/qr/{id}` | … |»
            for ci, cell in enumerate(x.cells):
                cm = VERB_PATH.match(cell.strip())
                if cm and ci > 0:
                    meth = Method(verb=cm.group(1).upper(), verb_line=x, start=x.n, end=x.n, url=cm.group(2),
                                  url_line=x, desc=re.sub(r"^\d+[.)]\s*", "", x.cells[0]), desc_line=x)
                    nm = re.search(r"\b([a-z]+[A-Z]\w*)\b", x.cells[0])
                    if nm:
                        meth.name, meth.name_line = nm.group(1), x
                    row_methods.append(meth)
                    break
            continue
        if verb is None:
            continue
        # начало блока: заголовок «Метод X» выше (до 10 строк) или начало таблицы
        start = x.n
        if x.cells is not None:  # тип запроса в таблице общих параметров: блок начинается с её заголовка
            j = idx - 1
            while j >= 0 and idx - j <= 30:
                if L[j].cells is not None:
                    start = L[j].n
                elif not (L[j].is_sep or (not L[j].text and j > 0 and L[j - 1].cells is not None)):
                    break
                j -= 1
        meth = Method(verb=verb, verb_line=x, start=start)
        if x.cells is None:
            vm = VERB_PATH.match(x.text)
            if vm:
                meth.url, meth.url_line = vm.group(2), x
                nm = re.search(r"\(([a-z]+[A-Z]\w*)\)|\b([a-z]+[A-Z]\w*)\b", x.text[vm.end():])
                if nm:
                    meth.name, meth.name_line = nm.group(1) or nm.group(2), x
        for k in range(idx - 1, max(-1, idx - 12), -1):
            hm = METHOD_HEADING.match(L[k].text)
            if hm:
                meth.name, meth.name_line, meth.start = hm.group(1), L[k], L[k].n
                break
            if L[k].text and L[k].cells is None and not L[k].is_sep and k < idx - 1 and \
                    (L[k].is_heading or len(L[k].text) < 60):
                # другой заголовок раньше названия метода — дальше не ищем
                if not METHOD_HEADING.match(L[k].text):
                    pass
        methods.append(meth)
    methods.sort(key=lambda m: m.start)
    for a, b in zip(methods, methods[1:]):
        a.end = b.start - 1
    if row_methods:  # блок метода из текста заканчивается перед сводной таблицей методов
        first_row = min(r.start for r in row_methods)
        for m in methods:
            if m.start < first_row:
                m.end = min(m.end, first_row - 1)
    last = L[-1].n if L else 0
    for m in methods:
        m.end = min(m.end, last)
        m.lines = [y for y in L if m.start <= y.n <= m.end]
        # общие параметры метода — строки «ключ | значение» в таблице с типом запроса
        for y in m.lines:
            kv = _kv(y)
            if not kv:
                if "curl" in y.text.lower() and m.curl_line is None:
                    m.curl_line = y
                continue
            key, val = kv
            if any(key == k or key.startswith(k + " ") for k in URL_KEYS) and not m.url:
                um = re.search(r"https?://[^/\s]+(/[\w\-{}/.]+)", val) or re.search(r"(?<![/\w])(/[\w\-{}/.]+)", val)
                if um:
                    m.url, m.url_line = um.group(1), y
            elif any(key == k for k in DESC_KEYS) and not m.desc:
                m.desc, m.desc_line = val, y
            elif key == "curl" and m.curl_line is None:
                m.curl_line = y
        if not m.name and m.url:
            segs = [s for s in m.url.split("/") if s and not s.startswith("{")]
            if segs and re.match(r"^[a-z]+[A-Z]\w*$", segs[-1]):
                m.name, m.name_line = segs[-1], m.url_line
    for m in row_methods:
        m.lines = [m.verb_line]
    return methods + row_methods


def method_of(methods: list[Method], n: int) -> Method | None:
    for m in methods:
        if m.start <= n <= m.end:
            return m
    return None


# --- 1. Изменение данных безопасным методом ------------------------------------------------------

def rule_get_mutation(doc: Doc, methods: list[Method], out: dict) -> None:
    for m in methods:
        if m.verb not in SAFE_VERBS:
            continue
        why = m.mutating_reason()
        if not why:
            continue
        reason, rline = why
        evidence = [cell_quote(m.verb_line, 0, 1) if m.verb_line.cells else ev(m.verb_line)]
        if m.desc_line is not None and MUTATING_DESC.match(m.desc.strip()):
            evidence.append(ev(m.desc_line, m.desc.split(".")[0].strip()))
        if m.url_line is not None:
            evidence.append(ev(m.url_line, m.url))
        if rline is not None and rline not in (m.verb_line, m.desc_line, m.url_line):
            evidence.append(ev(rline))
        params = _query_params(doc, m)
        leak = (f"параметры {fmt_list(params[:4])} передаются в строке URL и оседают в журналах прокси и "
                f"веб-сервера" if params else "параметры передаются в строке URL и оседают в журналах прокси и "
                "веб-сервера")
        rid = "api.get_mutation" + (f".{_slug(m.label)}" if m.label else "")
        c = candidate(
            rid,
            title=f"Метод {m.label + ' ' if m.label else ''}изменяет данные, но объявлен как {m.verb}",
            kind="api_contract", criterion="correct", severity="major", blocks="development",
            evidence=evidence,
            problem=(f"По документу метод изменяет состояние ({reason}), а тип запроса — {m.verb}. "
                     f"{m.verb} по RFC 9110 — безопасный метод без побочных эффектов: его кэшируют и повторяют "
                     f"прокси и клиенты; {leak}."),
            scenario=(f"Клиент сохраняет новое значение; при обрыве связи библиотека или прокси повторяет {m.verb}, "
                      "кэширующий узел может вернуть прошлый ответ без вызова сервера — клиент видит «успех», "
                      "а значение не изменилось."),
            impact=("Разработка реализует небезопасный контракт; риск ИБ — идентификаторы и значения в журналах; "
                    "автотесты контракта и шлюз API с политикой «GET только на чтение» его отклонят."),
            recommendation=(f"Заменить {m.verb} на POST или PUT (PATCH — для частичного изменения), "
                            "параметры передавать в теле запроса JSON и описать его схему."),
            rewrite="REST type: <уточнить: PUT или POST>. Параметры передаются в теле запроса (application/json).",
        )
        out["candidates"].append(c)
        out["signals"].append(signal(rid, m.verb_line, evidence[0]["quote"],
                                     f"Метод {m.label or m.verb} изменяет данные ({reason}), но объявлен как {m.verb}.",
                                     ("architect",), "api_contract"))
        src = m.curl_line or m.url_line or m.verb_line
        out["signals"].append(signal(
            "api.params_in_url", src, (m.curl_line.joined if m.curl_line else evidence[0]["quote"])[:200],
            f"Значения изменения ({fmt_list(params[:4]) or 'параметры запроса'}) передаются в строке URL метода "
            f"{m.verb}: попадают в журналы прокси, веб-сервера и историю браузера; {m.verb} может повторяться "
            "автоматически.", ("risk",), "security"))


def _query_params(doc: Doc, m: Method) -> list[str]:
    names: list[str] = []
    for t in tables(doc):
        if not (m.start <= t.header.n <= m.end):
            continue
        role = _table_role(doc, t)
        ni = t.col(*NAME_COLS)
        if role != "request" or ni is None:
            continue
        for r in t.rows:
            if r.cells and ni < len(r.cells) and IDENT.match(r.cells[ni]):
                names.append(r.cells[ni])
    return names


# --- 2. Content-Type при запросе без тела --------------------------------------------------------

def rule_content_type_without_body(doc: Doc, methods: list[Method], out: dict) -> None:
    scopes = [(m.start, m.end, m) for m in methods] or [(1, 10 ** 9, None)]
    for a, b, m in scopes:
        block = [x for x in doc.lines if a <= x.n <= b and x.text and not x.is_code]
        ct = next((x for x in block if CONTENT_TYPE.search(x.text)), None)
        nb = next((x for x in block if NO_BODY.search(x.text)), None)
        if not ct or not nb:
            continue
        if abs(ct.n - nb.n) > 40:
            continue
        ct_m = re.search(r"content-type\s*[:|]?\s*([\w.+\-]+/[\w.+\-]+)", ct.joined, re.I)
        ct_frag = ct.joined[ct_m.start():ct_m.end()] if ct_m else ct.joined
        nb_m = NO_BODY.search(nb.joined)
        nb_frag = nb.joined if len(nb.joined) <= 80 else nb.joined[nb_m.start():nb_m.end()]
        label = f" метода {m.label}" if m and m.label else ""
        out["candidates"].append(candidate(
            "api.content_type_without_body",
            title=f"Для запроса{label} указан Content-Type, хотя тело запроса не используется",
            kind="api_contract", criterion="set_consistent", severity="minor", blocks="development",
            evidence=[ev(ct, ct_frag), ev(nb, nb_frag)],
            problem=(f"В описании запроса{label} одновременно указано {quoted(ct_frag)} и {quoted(nb_frag)}. "
                     "Непонятно, передаётся ли тело запроса и в каком формате."),
            scenario=("Клиент отправляет запрос с заголовком Content-Type и пустым телом; строгий шлюз или "
                      "сервер отвечает 400/415, а другая команда реализует запрос без заголовка."),
            impact="Расхождение реализаций клиента и сервера, лишний спор при приёмке контракта.",
            recommendation=("Убрать Content-Type для запроса без тела или описать тело запроса и его поля; "
                            "если параметры переносятся в тело, описать его схему."),
            rewrite="Request body: не используется; заголовок Content-Type не передаётся.",
        ))


# --- 3. Коды ответа ------------------------------------------------------------------------------

@dataclass
class Status:
    code: int
    line: Line
    kind: str  # list | heading | table | otvet | inline
    seg: str = ""  # текст объявления (в PDF/DOCX перечень статусов бывает склеен в одну строку)

    @property
    def text(self) -> str:
        return self.seg or self.line.joined


def _status_tables(doc: Doc) -> list[Table]:
    res = []
    for t in tables(doc):
        cols = t.cols
        if cols and any(c.startswith(k) for c in cols[:1] for k in ("код", "code", "status", "статус", "http")):
            res.append(t)
    return res


def collect_statuses(doc: Doc) -> tuple[list[Status], list[tuple[int, Line, str]]]:
    decls: list[Status] = []
    for t in _status_tables(doc):
        for r in t.rows:
            if r.cells and re.fullmatch(CODE, r.cells[0].strip()):
                decls.append(Status(int(r.cells[0]), r, "table"))
    for x in doc.lines:
        if not x.text or x.is_code or x.cells is not None:
            continue
        m = DECL_LIST.match(x.text)
        if m:
            starts = [0] + [k.start(1) for k in DECL_LIST_INLINE.finditer(x.text)]
            if len(starts) == 1:
                decls.append(Status(int(m.group(1)), x, "list"))
            else:  # «200. Ответ … 401. Ответ … 422. Ответ …» в одной строке
                for i, a in enumerate(starts):
                    seg = x.text[a:starts[i + 1] if i + 1 < len(starts) else len(x.text)].strip()
                    cm = re.match(CODE, seg)
                    if cm:
                        decls.append(Status(int(cm.group(0)), x, "list", seg))
            continue
        if not DECL_LIST.match(x.text):  # PDF: перенос строки — объявления «422. Ответ …» с середины строки
            for k in DECL_LIST_INLINE.finditer(x.text):
                nxt = DECL_LIST_INLINE.search(x.text, k.end())
                seg = x.text[k.start(1):nxt.start(1) if nxt else len(x.text)].strip()
                if re.match(rf"{CODE}\.\s+(?:Ответ|Response|Статус)", seg, re.I):
                    decls.append(Status(int(k.group(1)), x, "list", seg))
        m = DECL_OTVET.match(x.text)
        if m:
            decls.append(Status(int(m.group(1)), x, "otvet"))
        for m in DECL_INLINE.finditer(x.text):  # «… Ответ 400 — поле отсутствует: {…}» внутри строки
            if m.start() > 0:
                decls.append(Status(int(m.group(1)), x, "inline"))
    # PDF/DOCX: объявление переносится на следующую строку («422. Ответ в случае, если клиент не» / «подходит по
    # возрасту.») — условие нужно целиком, иначе тот же случай под другим кодом не сравнить
    idx = {x.n: i for i, x in enumerate(doc.lines)}
    for d in decls:
        if d.kind != "list":
            continue
        t = d.text.rstrip()
        i = idx.get(d.line.n)
        if i is None or i + 1 >= len(doc.lines) or re.search(r"[.!?:;»)]$", t) or len(t) < 12:
            continue
        if not d.line.joined.rstrip().endswith(t[-20:]):
            continue  # объявление не в конце строки — переноса нет
        nx = doc.lines[i + 1]
        if nx.text and nx.cells is None and not nx.is_heading and not nx.is_code and nx.text[:1].islower() \
                and not DECL_LIST.match(nx.text):
            k = DECL_LIST_INLINE.search(nx.text)
            tail = nx.text[:k.start(1)] if k else nx.text
            e = tail.find(". ")
            tail = tail[:e + 1] if e != -1 else tail
            d.seg = f"{t} {tail.strip()}"
    mentions: list[tuple[int, Line, str]] = []
    for x in doc.lines:
        if not x.text or x.is_code:
            continue
        text = x.joined
        for m in MENTION.finditer(text):
            seq = m.group(1)
            base = m.start(1)
            for cm in re.finditer(CODE, seq):
                after = text[base + cm.end():]
                if UNIT_AFTER.match(after):
                    continue
                code = int(cm.group(0))
                # фрагмент цитаты: предложение с упоминанием
                s0 = max(text.rfind(".", 0, m.start()) + 1, text.rfind("|", 0, m.start()) + 1, 0)
                e1 = [p for p in (text.find(".", m.end()), text.find("|", m.end())) if p != -1]
                frag = text[s0:min(e1) + 1 if e1 and text[min(e1)] == "." else (min(e1) if e1 else len(text))]
                mentions.append((code, x, frag.strip()))
    return decls, mentions


def _heading_sections(doc: Doc, decls: list[Status]) -> list[tuple[Status, list[Line]]]:
    """Разделы статусов: строка «NNN. …» и строки до следующего объявления статуса."""
    marks = sorted([d for d in decls if d.kind in ("list", "otvet")], key=lambda d: d.line.n)
    starts = sorted({d.line.n for d in decls} | {x.n for x in doc.lines if x.is_heading})
    res = []
    for d in marks:
        nxt = next((s for s in starts if s > d.line.n), 10 ** 9)
        body = [x for x in doc.lines if d.line.n < x.n < nxt]
        res.append((d, body))
    return res


STOP_STEMS = {"метод", "возвр", "верну", "ответ", "запро", "случа", "резул", "стату", "выпол", "описа", "котор",
              "други", "этого", "также", "тогда", "после", "перед", "данны", "если", "либо", "или", "иначе", "когда",
              "unsuc", "succe", "error", "messa", "body", "тело", "ответа", "код", "кода"}


def _stems(text: str) -> set[str]:
    words = re.findall(r"[а-яёa-z]{4,}", text.lower().replace("ё", "е"))
    return {w[:5] for w in words} - STOP_STEMS


def _same_case_decl(frag: str, decls: list[Status], code: int, method: "Method | None" = None,
                    methods: "list[Method] | None" = None, any_class: bool = False,
                    min_overlap: int = 2) -> Status | None:
    """Объявленный статус с тем же условием, что у упомянутого кода (≥ 2 общих значимых основы).
    Строка перечня, отнесённая к другому методу («createX: …»), — не тот же случай."""
    cond = re.sub(CODE, " ", frag)
    st = _stems(cond)
    best, score = None, 1
    names = {m.name.lower() for m in methods or [] if m.name}
    score = min_overlap - 1
    for d in decls:
        if d.code == code or (not any_class and (d.code // 100) != (code // 100)):
            continue
        named = {w.lower() for w in re.findall(r"\b[a-z]+[A-Z]\w*\b", d.line.joined)} & names
        if named and (method is None or (method.name or "").lower() not in named):
            continue
        k = len(st & _stems(re.sub(CODE, " ", d.text)))
        if k > score:
            best, score = d, k
    return best


COND_MARK = re.compile(r"\b(?:если|при|в\s+случае|иначе|когда)\b", re.I)


def _rule_same_case_declared(doc: Doc, methods: list[Method], decls: list[Status], mentions: list, sections: list,
                             out: dict) -> None:
    """«Если условие C, вернуть X» в логике ↔ строка перечня «Y — условие C» (X ≠ Y, оба объявлены)."""
    declared = {d.code for d in decls}
    decl_lines = {d.line.n for d in decls}
    in_sections = {x.n for _, body in sections for x in body}
    done: set[tuple[int, int]] = set()
    for code, line, frag in mentions:
        if code not in declared or line.n in decl_lines or line.n in in_sections:
            continue
        if not re.search(r"возвра|верн", frag, re.I):
            continue
        if 200 <= code < 300 and _has_error(frag):
            continue  # «200 с ERROR» — это правило api.success_with_error
        # «Если C, вернуть X» — хватит двух общих основ; утверждение без «если» («Повторная операция … возвращает X»)
        # — только при сильном совпадении предмета (≥ 3 основы)
        need = 2 if COND_MARK.search(frag) else 3
        # условие бывает в предыдущем предложении шага («Проверить возраст… Если больше N, вернуть 200»)
        k = line.joined.find(frag)
        prev = line.joined[:k].rstrip() if k > 0 else ""
        prev_sent = re.split(r"(?<=[.;])\s+", prev)[-1] if prev else ""
        context = (prev_sent + " " + frag).strip()
        other = _same_case_decl(context, [d for d in decls if d.code != code and d.kind in ("table", "list")], code,
                                method_of(methods, line.n), methods, any_class=True, min_overlap=need)
        if other is None or (code, other.code) in done:
            continue
        own = [d for d in decls if d.code == code and d.kind in ("table", "list")]
        cst = _stems(re.sub(CODE, " ", context))
        if any(len(cst & _stems(re.sub(CODE, " ", d.text))) >= len(cst & _stems(re.sub(CODE, " ", other.text)))
               for d in own):
            continue  # объявление самого кода X описывает этот случай не хуже — расхождения нет
        done.add((code, other.code))
        out["candidates"].append(candidate(
            f"api.same_case.{code}-{other.code}",
            title=f"Один и тот же случай: код {code} в логике метода и {other.code} в перечне статусов",
            kind="status_conflict", criterion="set_consistent", severity="major", blocks="both",
            evidence=[ev(line, frag), ev(other.line, other.text)],
            problem=(f"В логике сказано {quoted(frag)}, а в перечне статусов тот же случай описан кодом {other.code}: "
                     f"{quoted(other.text)}."),
            scenario=(f"Наступает этот случай: сервер по логике метода отвечает {code}, клиент и автотест по перечню "
                      f"статусов ждут {other.code}."),
            impact="Клиент обработает ответ неверно; тест на этот случай нельзя написать однозначно.",
            recommendation=f"Оставить для случая один код ({code} или {other.code}) и описать его в логике и перечне одинаково.",
            question=f"Какой код возвращать в этом случае — {code} или {other.code}?",
            conflict=True,
        ))


def rule_statuses(doc: Doc, methods: list[Method], out: dict) -> None:
    decls, mentions = collect_statuses(doc)
    declared = sorted({d.code for d in decls})
    if len(declared) < 2:
        return
    sections = _heading_sections(doc, decls)
    problems: dict[int, dict] = {}

    def slot(code: int) -> dict:
        return problems.setdefault(code, {"mentions": [], "foreign": [], "reason": []})

    for code, line, frag in mentions:
        if code not in declared:
            slot(code)["mentions"].append((line, frag))
    # код в разделе другого кода
    for d, body in sections:
        for code, line, frag in mentions:
            if line in body and code != d.code and re.search(r"возвра|верн", frag, re.I):
                slot(code)["foreign"].append((d, line, frag))
    # фраза причины в заголовке не совпадает с кодом
    for d in decls:
        if d.kind not in ("list", "otvet"):
            continue
        for rx, rcode in REASON_PHRASES:
            mm = rx.search(d.line.text)
            if mm and rcode != d.code:
                slot(rcode)["reason"].append((d, mm.group(0)))
    decl_list = fmt_list([str(c) for c in declared])
    for code, p in sorted(problems.items()):
        if not (p["mentions"] or p["foreign"] or p["reason"]):
            continue
        undeclared = code not in declared
        evidence: list[dict] = []
        parts: list[str] = []
        title = ""
        if p["foreign"]:
            d, line, frag = p["foreign"][0]
            evidence += [ev(d.line), ev(line, frag)]
            parts.append(f"В разделе {quoted(d.line.text)} сказано {quoted(frag)} — описан ответ {code}, "
                         f"а не {d.code}.")
            title = f"В разделе ответа {d.code} описан код {code}"
        same_case = None
        if p["mentions"] and undeclared:
            for line, frag in p["mentions"][:2]:
                evidence.append(ev(line, frag))
            if not p["foreign"]:
                same_case = _same_case_decl(p["mentions"][0][1], decls, code,
                                            method_of(methods, p["mentions"][0][0].n), methods)
                parts.append(f"В тексте сказано {quoted(p['mentions'][0][1])}, но кода {code} нет в перечне "
                             f"статусов (описаны {decl_list}).")
                if same_case is not None:
                    evidence.append(ev(same_case.line, same_case.text))
                    parts.append(f"Тот же случай в перечне статусов описан кодом {same_case.code}: "
                                 f"{quoted(same_case.text)}.")
                    title = (f"Один и тот же случай получает код {code} в тексте и {same_case.code} "
                             f"в перечне статусов")
            else:
                parts.append(f"Кода {code} нет в перечне статусов (описаны {decl_list}).")
        if p["reason"]:
            d, phrase = p["reason"][0]
            evidence.append(ev(d.line))
            parts.append(f"Заголовок {quoted(d.line.text)} подписан фразой «{phrase}», которая соответствует "
                         f"коду {code}, а не {d.code}.")
        if not title:
            if undeclared and p["mentions"]:
                title = f"Код {code} упомянут, но не описан в перечне статусов"
                if p["reason"]:
                    title += f"; заголовок ответа {p['reason'][0][0].code} подписан как {p['reason'][0][1]}"
            elif p["reason"]:
                d, phrase = p["reason"][0]
                title = f"Заголовок ответа {d.code} подписан как {phrase} (код {code})"
            else:
                continue
        if undeclared and p["foreign"]:
            title += ", которого нет в перечне статусов"
        conflict = bool(p["foreign"] or p["reason"] or same_case is not None)
        out["candidates"].append(candidate(
            f"api.status_{code}",
            title=title,
            kind="status_conflict" if conflict else "missing_element",
            criterion="set_consistent" if conflict else "set_complete",
            severity="major", blocks="both",
            evidence=evidence,
            problem=" ".join(parts),
            scenario=(f"Сервер возвращает {code}: по перечню статусов такой ответ не предусмотрен "
                      f"или описан под другим кодом; приложение и автотесты ждут другой код и другое тело."
                      if undeclared else
                      f"Разработчик сервера читает заголовок и возвращает один код, тестировщик по тексту ждёт "
                      f"{code}: один и тот же случай получает разные коды."),
            impact=("Клиент обработает ответ как неизвестную ошибку; спор при приёмке о правильном коде; "
                    "автотесты контракта нельзя написать однозначно."),
            recommendation=(f"Описать код {code} в перечне статусов (когда возвращается, тело ответа) или убрать "
                            f"упоминание; привести заголовки разделов в соответствие с кодами."),
            rewrite=f"{code}. <уточнить: когда возвращается>. Тело ответа: <уточнить>.",
            conflict=conflict,
        ))
        out["signals"].append(signal(f"api.status_{code}", doc.get(evidence[0]["line"]),
                                     evidence[0]["quote"], title + ".", ("architect", "qa"), "status_conflict"))
    _rule_same_case_declared(doc, methods, decls, mentions, sections, out)
    # сводка для линз
    first = decls[0].line
    mentioned = sorted({c for c, _, _ in mentions})
    out["signals"].append(signal(
        "api.status_inventory", first, first.joined[:80],
        f"Перечень статусов: {decl_list}; упомянуты в тексте: {fmt_list([str(c) for c in mentioned]) or 'нет'}.",
        ("architect", "qa"), "inventory"))


def rule_success_with_error(doc: Doc, methods: list[Method], out: dict) -> None:
    decls, mentions = collect_statuses(doc)
    client_err = [d for d in decls if 400 <= d.code < 500]
    if not client_err:
        return
    validation = next((d for d in client_err if d.code in (400, 422)), client_err[0])
    hits: list[tuple[int, Line, Line | None]] = []
    for d, body in _heading_sections(doc, decls):
        if not (200 <= d.code < 300):
            continue
        for x in body:
            if x.is_code and ERROR_JSON.search(x.text):
                hits.append((d.code, x, d.line))
                break
    for code, line, frag in mentions:
        if 200 <= code < 300 and _has_error(frag) and re.search(r"возвра|верн", frag, re.I):
            hits.append((code, line, None))
    seen: set[int] = set()
    for code, line, head in hits:
        if line.n in seen:
            continue
        seen.add(line.n)
        evidence = []
        if head is not None:
            evidence.append(ev(head))
        evidence.append(ev(line))
        evidence.append(ev(validation.line))
        err = ERROR_JSON.search(line.text) or _has_error(line.joined)
        err_s = err.group(0) if err else "ошибка"
        out["candidates"].append(candidate(
            "api.success_with_error",
            title=f"Ответ {code} описывает ошибку, хотя для неверного запроса предусмотрен код {validation.code}",
            kind="status_conflict", criterion="set_consistent", severity="major", blocks="both",
            evidence=evidence,
            problem=(f"Для успешного кода {code} приведён результат с ошибкой ({err_s}), а в перечне статусов "
                     f"ошибка входных данных описана кодом {validation.code}: {quoted(validation.line.joined)}. "
                     "Одна и та же ошибка описана двумя способами."),
            scenario=(f"Клиент передаёт недопустимое значение: по одному месту документа сервер отвечает {code} "
                      f"с признаком ошибки в теле, по другому — {validation.code}. Приложение, ждущее "
                      f"{validation.code}, покажет «успех»."),
            impact=("Разработчики сервера и клиента выберут разные варианты; тест на неверный ввод нельзя "
                    "однозначно написать; клиент может увидеть успешное сохранение при ошибке."),
            recommendation=(f"Оставить один способ: ошибки входных данных — только код {validation.code} "
                            f"с описанным телом; ответ {code} — только успех."),
            rewrite=(f"{code} — только успешное выполнение. Неверные параметры — {validation.code} "
                     "с телом <уточнить: поля ответа об ошибке>."),
            conflict=True,
        ))
        out["signals"].append(signal("api.success_with_error", line, evidence[-2]["quote"] if head else
                                     evidence[0]["quote"],
                                     f"Успешный код {code} несёт ошибку в теле; для ошибок ввода есть {validation.code}.",
                                     ("architect", "qa"), "status_conflict"))


# --- 4. Типы одного поля в запросе и ответе ------------------------------------------------------

REQ_WORDS = re.compile(r"запрос|request|query|path|параметр\w* запроса|тело запроса|header|заголов", re.I)
RESP_WORDS = re.compile(r"ответ|response|результат", re.I)


def _table_role(doc: Doc, t: Table) -> str:
    sec = t.header.section or ""
    last = sec.split("›")[-1] if sec else ""
    for s in (last, sec):
        if s:
            r = RESP_WORDS.search(s)
            q = REQ_WORDS.search(s)
            if r and not q:
                return "response"
            if q and not r:
                return "request"
            if q and r:
                return "response" if r.start() > q.start() else "request"
    # запасной путь: ближайшие строки-заголовки выше таблицы
    for k in range(t.header.n - 1, max(0, t.header.n - 8), -1):
        x = doc.get(k)
        if not x or not x.text or x.cells is not None:
            continue
        if len(x.text) > 60 and not x.is_heading:
            continue
        r = RESP_WORDS.search(x.text)
        q = REQ_WORDS.search(x.text)
        if r and not q:
            return "response"
        if q and not r:
            return "request"
    return ""


def _base_type(s: str) -> str:
    s = s.strip().strip("`").strip()
    if not any(rx.match(s) for rx, _ in TYPE_MAP):
        s = s.replace(" ", "")  # PDF: «integ er»
    for rx, t in TYPE_MAP:
        if rx.match(s):
            return t
    return ""


def rule_field_types(doc: Doc, methods: list[Method], out: dict) -> None:
    by_scope: dict[int, dict[str, dict[str, tuple[str, Line, int, int]]]] = {}
    for t in tables(doc):
        ni, ti = t.col(*NAME_COLS), t.col(*TYPE_COLS)
        if ni is None or ti is None:
            continue
        role = _table_role(doc, t)
        if role not in ("request", "response"):
            continue
        m = method_of(methods, t.header.n)
        scope = m.start if m else 0
        for r in t.rows:
            if not r.cells or max(ni, ti) >= len(r.cells):
                continue
            name = r.cells[ni].strip()
            bt = _base_type(r.cells[ti])
            if not IDENT.match(name) or not bt:
                continue
            by_scope.setdefault(scope, {}).setdefault(name, {})
            by_scope[scope][name].setdefault(role, (bt, r, ni, ti))
    for scope, fields in by_scope.items():
        bad = [(nm, d["request"], d["response"]) for nm, d in fields.items()
               if "request" in d and "response" in d and d["request"][0] != d["response"][0]]
        if not bad:
            continue
        m = next((x for x in methods if x.start == scope), None)
        names = [b[0] for b in bad]
        evidence = []
        desc = []
        for nm, (t1, r1, ni1, ti1), (t2, r2, ni2, ti2) in bad[:2]:
            q1 = cell_quote(r1, ni1, ti1) if ti1 == ni1 + 1 else ev(r1, r1.cells[ti1])
            q2 = cell_quote(r2, ni2, ti2) if ti2 == ni2 + 1 else ev(r2, r2.cells[ti2])
            evidence += [q1, q2]
            desc.append(f"{nm}: в запросе {r1.cells[ti1]}, в ответе {r2.cells[ti2]}")
        label = f" метода {m.label}" if m and m.label else ""
        rid = "api.field_types" + (f".{_slug(m.label)}" if m and m.label else "")
        out["candidates"].append(candidate(
            rid,
            title=f"Тип {'поля' if len(names) == 1 else 'полей'} {fmt_list(names)} в запросе и ответе{label} различается",
            kind="api_contract", criterion="set_consistent", severity="major", blocks="development",
            evidence=evidence,
            problem=("Одно и то же поле описано разными типами: " + "; ".join(desc) + ". "
                     "Неясно, какой тип хранится и возвращается."),
            scenario=(f"Клиент отправляет {names[0]} как {bad[0][1][0]} и получает обратно значение типа "
                      f"{bad[0][2][0]}; строгий разбор ответа или сравнение отправленного и сохранённого значения "
                      "не проходит."),
            impact="Разработчики клиента и сервера выберут разные типы; автотесты контракта упадут.",
            recommendation="Выбрать один тип для каждого поля и указать его в таблицах запроса и ответа.",
            rewrite="; ".join(f"{nm} | <уточнить: один тип для запроса и ответа>" for nm in names),
            conflict=True,
        ))
        out["signals"].append(signal(rid, bad[0][1][1], evidence[0]["quote"],
                                     "Разные типы одного поля в запросе и ответе: " + "; ".join(desc) + ".",
                                     ("architect",), "api_contract"))


RESULT_VALUES = re.compile(r"\b(OK|SUCCESS|SUCCEEDED)\b.*\b(ERROR|FAIL\w*|ERR)\b|\b(ERROR|FAIL\w*)\b.*\b(OK|SUCCESS)\b")
JSON_KEY = re.compile(r'"([A-Za-z_][\w]*)"\s*:')


def rule_result_field_missing(doc: Doc, methods: list[Method], out: dict) -> None:
    """Общая таблица ответа задаёт поле-результат («OK / ERROR»), а тела ответов-ошибок его не содержат."""
    decls, _ = collect_statuses(doc)
    sections = _heading_sections(doc, decls)
    for t in tables(doc):
        if _table_role(doc, t) != "response":
            continue
        sec = (t.header.section or "").split("›")[-1]
        if re.search(CODE, sec):
            continue  # таблица описывает ответ конкретного кода, а не все ответы
        near = [doc.get(k) for k in range(t.header.n - 1, max(0, t.header.n - 4), -1)]
        if any(x is not None and x.is_heading and re.search(CODE, x.text) for x in near):
            continue
        ni = t.col(*NAME_COLS)
        if ni is None:
            continue
        result_rows = [r for r in t.rows if r.cells and ni < len(r.cells) and IDENT.match(r.cells[ni])
                       and RESULT_VALUES.search(" | ".join(r.cells[ni + 1:]))]
        if not result_rows:
            continue
        row = result_rows[0]
        field = row.cells[ni]
        missing: list[tuple[int, Line]] = []
        for d, body in sections:
            if d.code < 400:
                continue
            js = [x for x in body if x.is_code and JSON_KEY.search(x.text)]
            if js and not any(f'"{field}"' in x.text for x in js):
                missing.append((d.code, js[0]))
        if len(missing) < 2:
            continue
        codes = fmt_list([str(c) for c, _ in missing])
        evidence = [cell_quote(row, ni, min(len(row.cells) - 1, ni + 2))] + [ev(x) for _, x in missing[:3]]
        out["candidates"].append(candidate(
            f"api.result_field_missing.{_slug(field)}",
            title=f"Ответы {codes} не содержат поля {field}, хотя таблица ответа задаёт его для результата",
            kind="api_contract", criterion="set_consistent", severity="major", blocks="development",
            evidence=evidence,
            problem=(f"В таблице ответа поле {field} — признак результата ({quoted(' | '.join(row.cells[ni + 1:ni + 3]))}), "
                     f"без условия «при успехе» или «при ошибке». В примерах ответов {codes} этого поля нет — "
                     "непонятно, приходит ли признак результата в ошибках."),
            scenario=(f"Клиент разбирает ответ об ошибке и читает {field}, чтобы показать сообщение: поле отсутствует, "
                      "разбор падает или ошибка показывается как неизвестная."),
            impact="Разные реализации обработки ошибок у клиента и сервера; тесты контракта на ошибки не написать.",
            recommendation=(f"Либо добавить {field} во все тела ошибок, либо указать в таблице ответа, при каких кодах "
                            f"поле {field} присутствует."),
            rewrite=f"{field} | <уточнить: тип> | Обязательно во всех ответах | Признак результата",
            conflict=True,
        ))
        out["signals"].append(signal(f"api.result_field_missing.{_slug(field)}", row, evidence[0]["quote"],
                                     f"Поле {field} задано в общей таблице ответа, но отсутствует в ответах {codes}.",
                                     ("architect",), "api_contract"))
        return


DATE_MASKS = [
    (re.compile(r"ДД\.ММ\.ГГГГ|DD\.MM\.YYYY|dd\.MM\.yyyy", re.I), re.compile(r"^\d{2}\.\d{2}\.\d{4}$"), "ДД.ММ.ГГГГ"),
    (re.compile(r"ГГГГ-ММ-ДД|YYYY-MM-DD|yyyy-MM-dd|ISO\s*8601", re.I), re.compile(r"^\d{4}-\d{2}-\d{2}"), "ГГГГ-ММ-ДД (ISO 8601)"),
]
JSON_PAIR = re.compile(r'"([A-Za-z_]\w*)"\s*:\s*"([^"]*)"')


def rule_date_format(doc: Doc, methods: list[Method], out: dict) -> None:
    """Формат даты поля в таблице не совпадает с примером значения этого поля."""
    examples: dict[str, tuple[str, Line]] = {}
    for x in doc.lines:
        for m in JSON_PAIR.finditer(x.joined):
            examples.setdefault(m.group(1), (m.group(2), x))
    for t in tables(doc):
        ni = t.col(*NAME_COLS)
        if ni is None:
            continue
        for r in t.rows:
            if not r.cells or ni >= len(r.cells):
                continue
            name = r.cells[ni].split()[0] if r.cells[ni] else ""
            joined_name = r.cells[ni].replace(" ", "")
            if name not in examples and IDENT.match(joined_name) and joined_name in examples:
                name = joined_name  # PDF: «paymentDueD ate»
            if not IDENT.match(name) or name not in examples:
                continue
            rest = " | ".join(r.cells[ni + 1:])
            for mask_rx, value_rx, mask_name in DATE_MASKS:
                mm = mask_rx.search(rest)
                if not mm:
                    continue
                value, ex_line = examples[name]
                if not re.match(r"^\d", value) or value_rx.match(value):
                    break
                q_row = " | ".join(r.cells[ni:ni + 1 + next(i for i, c in enumerate(r.cells[ni + 1:], 1)
                                                           if mask_rx.search(c))])
                out["candidates"].append(candidate(
                    f"api.date_format.{_slug(name)}",
                    title=f"Формат даты поля {name}: {mask_name} в описании, «{value}» в примере",
                    kind="api_contract", criterion="set_consistent", severity="major", blocks="development",
                    evidence=[ev(r, q_row), ev(ex_line, f'"{name}":"{value}"')],
                    problem=(f"В таблице для {name} указан формат {quoted(mm.group(0))}, а в примере ответа "
                             f"{quoted(value)}. Клиент не знает, какой формат разбирать."),
                    scenario=f"Сервер отдаёт {name} = «{value}», клиент разбирает по маске {mm.group(0)} — дата не читается.",
                    impact="Ошибка разбора даты у клиента; тесты контракта расходятся с примером.",
                    recommendation=f"Указать один формат для {name} (рекомендуется ISO 8601) в таблице и в примерах.",
                    conflict=True,
                ))
                break


def rule_inventory(doc: Doc, methods: list[Method], out: dict) -> None:
    if not methods:
        return
    parts = []
    for m in methods:
        kind = "чтение" if m.is_read() else "изменение"
        parts.append(f"{m.label or 'без имени'} ({m.verb}, {kind})")
    out["signals"].append(signal("api.methods", methods[0].verb_line, methods[0].verb_line.joined[:80],
                                 "Описанные методы API: " + "; ".join(parts) + ".", ("architect",), "inventory"))


def run(doc: Doc, out: dict) -> None:
    methods = find_methods(doc)
    out.setdefault("_methods", methods)
    rule_get_mutation(doc, methods, out)
    rule_content_type_without_body(doc, methods, out)
    rule_statuses(doc, methods, out)
    rule_success_with_error(doc, methods, out)
    rule_field_types(doc, methods, out)
    rule_result_field_missing(doc, methods, out)
    rule_date_format(doc, methods, out)
    rule_inventory(doc, methods, out)
