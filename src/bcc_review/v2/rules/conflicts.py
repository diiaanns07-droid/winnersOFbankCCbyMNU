"""Противоречия кодом (только высокоточные случаи): события и границы.

event_conflict — одно и то же утверждение с противоположным исходом в двух местах:
  * тот же предмет и тот же глагол, в одном месте с «не» («Отменённая операция уменьшает …» ↔ «… не уменьшает …»);
  * то же условие «Если …», а следствия противоположны («… не выполняется» ↔ «… выполняет»);
  * тот же предмет: «без ограничения» ↔ «не чаще / не более N»;
  * то же действие вступает в силу в разное время («действует с …» ↔ «применяется с …»).
boundary_conflict — граница включена в одном месте и исключена в другом:
  * допустимый диапазон «от A до B включительно» ↔ ошибка «меньше A или не меньше B»;
  * «выполняется, если не превысит X» ↔ «отклоняется, если достигнет X или превысит»;
  * правило «величина не выше X → действие» ↔ строка приёмки, где величина равна X, а действия нет;
  * ограничение «величина меньше N» ↔ ожидаемый результат приёмки «величина N».
Сравниваются только утверждения с общим предметом; пара даёт один кандидат с двумя цитатами.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from ._text import Doc, Line, candidate, ev, quoted, tables

ID_PREFIX = re.compile(r"^\s*(?:[A-ZА-ЯЁ]{1,5}-\d+[.)]?|\d{1,2}[.)])\s+")
WORD = re.compile(r"[а-яёa-z]+", re.I)
STOP = {"если", "когда", "после", "перед", "через", "также", "этого", "этой", "который", "которая", "которые",
        "только", "более", "менее", "одного", "одной", "такой", "такая", "всегда", "каждый", "каждая", "клиент",
        "клиента", "система", "банк", "приложение", "метод", "когда", "будет", "может"}


def _norm(w: str) -> str:
    return w.lower().replace("ё", "е")


def _stem(w: str, n: int = 5) -> str:
    return _norm(w)[:n]


def _stems(text: str, n: int = 5) -> set[str]:
    return {_stem(w, n) for w in WORD.findall(text) if len(w) >= 4 and _norm(w) not in STOP}


@dataclass
class Sent:
    line: Line
    text: str      # предложение как в строке (для цитаты)
    body: str      # без ID-префикса


def sentences(doc: Doc) -> list[Sent]:
    res: list[Sent] = []
    for x in doc.lines:
        if not x.text or x.is_code or x.cells is not None or x.is_heading:
            continue
        t = x.joined
        for part in re.split(r"(?<=[.;!?])\s+(?=[А-ЯЁA-Z«\"])", t):
            p = part.strip()
            if len(p.split()) < 3:
                continue
            body = ID_PREFIX.sub("", p).strip()
            res.append(Sent(x, p, body))
    return res


def _words(s: str) -> list[str]:
    return [_norm(w) for w in WORD.findall(s)]


def _emit(out: dict, rule: str, kind: str, a: Sent | Line, qa: str, b: Sent | Line, qb: str, title: str,
          problem: str, scenario: str, recommendation: str, question: str = "") -> None:
    la = a.line if isinstance(a, Sent) else a
    lb = b.line if isinstance(b, Sent) else b
    if isinstance(a, Sent) and qa == a.text:
        qa = a.body
    if isinstance(b, Sent) and qb == b.text:
        qb = b.body
    extra = out.pop("_extra_ev", [])
    # у каждой пары свой source: судья №10 склеивает кандидатов одного правила в один кластер
    rule = f"{rule}.L{min(la.n, lb.n)}-{max(la.n, lb.n)}"
    out["candidates"].append(candidate(
        rule, title=title, kind=kind, criterion="set_consistent", severity="major", blocks="both",
        evidence=[ev(la, qa), ev(lb, qb)] + extra, problem=problem, scenario=scenario,
        impact=("Разработчик реализует одно правило, тестировщик проверяет другое; исход для клиента зависит от "
                "того, какое место документа прочитали."),
        recommendation=recommendation, question=question, conflict=True,
    ))


# --- event_conflict -------------------------------------------------------------------------------

def _subject_verb(body: str) -> tuple[str, str, bool] | None:
    """«Отменённый перевод (не) уменьшает …» → ("отмененный перевод", "уменьшает", negated)."""
    w = _words(body)
    if len(w) < 3:
        return None
    if w[0] in ("если", "при", "когда", "после", "для", "по", "в", "на", "за", "до", "тогда", "дано", "ожидается",
                "ожидаемо", "результат", "шаг", "given", "when", "then", "и", "а", "но"):
        return None
    neg = w[2] == "не"
    verb = w[3] if neg and len(w) > 3 else w[2]
    if not re.search(r"(ет|ит|ут|ют|ат|ят|ется|ится|ются|ятся|ает|яет)$", verb):
        return None
    return f"{w[0]} {w[1]}", verb, neg


COND = re.compile(r"^\s*(?:если|при условии,? что|в случае,? если)\s+(.+?),\s*(.+)$", re.I)
NEG_PHRASE = re.compile(r"\b([а-яё]+)\s+не\s+([а-яё]+)|\bне\s+([а-яё]+)", re.I)
UNLIMITED = re.compile(r"\bбез\s+ограничени\w*", re.I)
LIMITED = re.compile(r"\bне\s+чаще\b|\bне\s+более\b|\bне\s+больше\b|\bмаксимум\b|\bне\s+свыше\b", re.I)
EFFECT = re.compile(r"\b(действует|применяется|вступает\s+в\s+силу|начинает\s+действовать)\b(.*)$", re.I)
EFFECT_TIME = re.compile(r"\b(?:с|со|начиная\s+с|начиная\s+со)\s+((?:момента|первого|следующ|начала|даты|дня|"
                         r"сегодняшн|текущ)\w*(?:\s+[а-яё]+){0,3})|\b(сразу|немедленно)\b", re.I)


TTL_AFTER = re.compile(r"^\s*(?:в\s+течение\s+)?(?:\d+|од(?:ин|ну|ни)|дв[ае]|тр[иё]|четыр\w*|пят\w*|десят\w*|"
                       r"пятнадцат\w*|тридцат\w*)\s+(?:секунд|минут|час|сут|дн|недел|месяц|год|лет)\w*", re.I)


def rule_events(doc: Doc, out: dict) -> None:
    sents = sentences(doc)
    done: set[tuple[int, int]] = set()

    def mark(a: Sent, b: Sent) -> bool:
        key = (min(a.line.n, b.line.n), max(a.line.n, b.line.n))
        if key in done or a.line.n == b.line.n:
            return False
        done.add(key)
        return True

    # 1. тот же предмет и глагол, отрицание в одном месте
    sv = [(s, _subject_verb(s.body)) for s in sents]
    sv = [(s, x) for s, x in sv if x]
    for i, (a, (sa, va, na)) in enumerate(sv):
        for b, (sb, vb, nb) in sv[i + 1:]:
            if sa == sb and va == vb and na != nb and mark(a, b):
                pos, neg = (a, b) if nb else (b, a)
                _emit(out, "conflicts.event_negation", "event_conflict", pos, pos.text, neg, neg.text,
                      title=f"Противоположные исходы одного правила: «{sa} {va}» и «не {va}»",
                      problem=(f"В одном месте {quoted(pos.body)}, в другом — {quoted(neg.body)}. Для одного и того же "
                               "случая документ даёт противоположные исходы."),
                      scenario=(f"Происходит событие «{sa}»: по одному месту документа «{va}» выполняется, по "
                                "другому — нет."),
                      recommendation="Оставить одно правило и удалить или исправить второе; добавить критерий приёмки.",
                      question=f"Какое из двух правил для «{sa}» верное?")
    # 2. то же условие «Если …», противоположные следствия
    conds = []
    for s in sents:
        m = COND.match(s.body)
        if m:
            conds.append((s, _stems(m.group(1)), m.group(2)))
    for i, (a, ca, ra) in enumerate(conds):
        for b, cb, rb in conds[i + 1:]:
            if not ca or len(ca & cb) / len(ca | cb) < 0.75:
                continue
            for neg_txt, pos_txt, na, nb in ((ra, rb, a, b), (rb, ra, b, a)):
                neg_stems = set()
                for m in NEG_PHRASE.finditer(neg_txt):
                    for g in m.groups():
                        if g and len(g) >= 5:
                            neg_stems.add(_stem(g))
                pos_clean = NEG_PHRASE.sub(" ", pos_txt)
                pos_stems = {_stem(w) for w in WORD.findall(pos_clean) if len(w) >= 5}
                common = neg_stems & pos_stems
                if common and mark(na, nb):
                    _emit(out, "conflicts.event_condition", "event_conflict", na, na.text, nb, nb.text,
                          title="Одно и то же условие ведёт к противоположным исходам",
                          problem=(f"Условие одно и то же, а исходы противоположны: {quoted(na.body)} и "
                                   f"{quoted(nb.body)}."),
                          scenario="Условие выполняется: по одному месту действие не происходит, по другому — "
                                   "происходит, причём с другими последствиями для клиента.",
                          recommendation="Выбрать один исход для этого условия, второе правило удалить или "
                                         "сделать отдельным случаем с явным отличающим условием.",
                          question="Какой исход верный при этом условии?")
                    break
    # 3. «без ограничения» ↔ «не чаще / не более»
    for i, a in enumerate(sents):
        if not UNLIMITED.search(a.body):
            continue
        wa = _words(a.body)[:2]
        for b in sents:
            if b is a or not LIMITED.search(b.body) or _words(b.body)[:2] != wa or not mark(a, b):
                continue
            _emit(out, "conflicts.event_quantity", "event_conflict", a, a.text, b, b.text,
                  title=f"«Без ограничения» и ограничение для одного и того же: {quoted(' '.join(wa))}",
                  problem=f"{quoted(a.body)} противоречит {quoted(b.body)}: одно и то же действие и не ограничено, и "
                          "ограничено.",
                  scenario="Клиент выполняет действие второй раз за период: по одному месту можно, по другому — нет.",
                  recommendation="Оставить одно правило; если ограничение нужно — указать число, период и реакцию "
                                 "на превышение.",
                  question="Есть ли ограничение на число повторов и какое?")
    # 4. то же действие вступает в силу в разное время
    effects = []
    for s in sents:
        m = EFFECT.search(s.body)
        if not m:
            continue
        if TTL_AFTER.match(m.group(2)):
            continue  # «код действует 5 минут с момента отправки» — срок действия, а не момент вступления в силу
        tm = EFFECT_TIME.search(m.group(2))
        if not tm:
            continue
        subj = _words(s.body[:m.start()])
        if not subj:
            continue
        effects.append((s, subj, (tm.group(1) or tm.group(2)).lower()))
    for i, (a, sa, ta) in enumerate(effects):
        for b, sb, tb in effects[i + 1:]:
            if ta == tb or _stem(ta, 6) == _stem(tb, 6):
                continue
            # общий предмет: первое слово или общее значимое слово (≥ 4 букв: «код» в «PIN-код» и «SMS-код» — разные)
            if not (sa[0][:3] == sb[0][:3] or (set(x[:5] for x in sa if len(x) >= 4)
                                                & set(x[:5] for x in sb if len(x) >= 4))):
                continue
            if not mark(a, b):
                continue
            _emit(out, "conflicts.event_effective", "event_conflict", a, a.text, b, b.text,
                  title="Одно и то же изменение вступает в силу в разное время",
                  problem=f"{quoted(a.body)} и {quoted(b.body)}: момент, с которого действует изменение, указан по-разному "
                          f"(«{ta}» и «{tb}»).",
                  scenario="Клиент меняет настройку и сразу совершает операцию: по одному месту она уже учитывается "
                           "по-новому, по другому — ещё по-старому.",
                  recommendation="Указать один момент вступления в силу и привести второе место в соответствие.",
                  question="С какого момента изменение начинает действовать?")


# --- boundary_conflict ----------------------------------------------------------------------------

NUM = r"\d{1,3}(?:[   ]\d{3})+|\d+"
OPS = [  # (шаблон, оператор)
    (r"не\s+(?:меньше|менее|ниже)", ">="), (r"не\s+(?:больше|более|выше)", "<="), (r"не\s+превыс\w*", "<="),
    (r"не\s+превыша\w*", "<="), (r"не\s+достиг\w*", "<"),
    (r"(?:меньше|менее|ниже)", "<"), (r"(?:больше|более|выше)", ">"), (r"превыс\w*|превыша\w*", ">"),
    (r"достиг\w*", ">="),
]
_CMP = re.compile(r"\b(" + "|".join(f"(?:{p})" for p, _ in OPS) + r")\s+(" + NUM + r"|[а-яё]+)", re.I)
# «достигла бы X или превысила бы его» — граница внутри
REACH = re.compile(r"\b(достиг\w*(?:\s+бы)?)\s+([а-яё]+)\s+или\s+превыс\w*(?:\s+бы)?(?:\s+(?:его|её|ее|их))?", re.I)


class _M:
    """Совпадение сравнения: group(1) — оператор, group(2) — граница, group(0) — фраза."""

    def __init__(self, op_text: str, bound: str, whole: str, start: int, end: int):
        self._g = (whole, op_text, bound)
        self._s, self._e = start, end

    def group(self, i: int = 0) -> str:
        return self._g[i]

    def start(self) -> int:
        return self._s

    def end(self) -> int:
        return self._e


class CMP:  # noqa: N801 — тот же интерфейс, что у re.Pattern.finditer
    @staticmethod
    def finditer(text: str):
        taken: list[tuple[int, int]] = []
        res = []
        for m in REACH.finditer(text):
            res.append(_M("достигнет или превысит", m.group(2), m.group(0), m.start(), m.end()))
            taken.append((m.start(), m.end()))
        for m in _CMP.finditer(text):
            if any(a <= m.start() < b for a, b in taken):
                continue
            res.append(_M(m.group(1), m.group(2), m.group(0), m.start(), m.end()))
        return sorted(res, key=lambda x: x.start())
# единица после числа («от 100 ₸ до 1 000 000 ₸ включительно», «от 1 до 6 месяцев включительно»)
RANGE_UNIT = r"(?:\s*(?:₸|₽|\$|€|%|тенге|тиын\w*|руб\w*|коп\w*|сум\b))?"
RANGE = re.compile(rf"\bот\s+({NUM}){RANGE_UNIT}\s+до\s+({NUM})[^.;|]{{0,25}}?\bвключительно\b", re.I)
REJECT = re.compile(r"отклон\w*|\bне\s+выполня\w*|запрещ\w*|недопуст\w*|ошибк\w*|\b4\d\d\b|не\s+принима\w*", re.I)
ALLOW = re.compile(r"(?<!не )\b(выполняется|выполняет|разрешается|допускается|проходит|принимается|"
                   r"пополняет|начисляется|списывает|отправляет|зачисляется)\b", re.I)


def _fmt(v: int) -> str:
    return f"{v:,}".replace(",", " ")


def _num(s: str) -> int | None:
    d = re.sub(r"\D", "", s)
    return int(d) if d else None


def _op_of(word: str) -> str:
    w = word.lower()
    if w == "достигнет или превысит":
        return ">="
    for p, op in OPS:
        if re.fullmatch(p, w, re.I):
            return op
    return ""


def _includes(op: str, v: float, b: float) -> bool:
    return {"<": v < b, "<=": v <= b, ">": v > b, ">=": v >= b}[op]


GENERIC = {"сумма", "сумму", "суммы", "значе", "должн", "иначе", "верну", "больш", "меньш", "строг", "включ",
           "менее", "более", "диапа", "поле", "число", "целым", "целое", "клиен", "банк", "задае", "задаё", "указы"}
MUST = re.compile(r"должн\w*\s+(?:быть|составлять)|допуска\w*|разреша\w*", re.I)


def _subj_stems(text: str) -> set[str]:
    st = {w.lower()[:5] for w in re.findall(r"[A-Za-zА-Яа-яЁё_]{4,}", text)}
    return {x.replace("ё", "е") for x in st} - GENERIC


def rule_ranges(doc: Doc, out: dict) -> None:
    """Допустимый диапазон «от A до B включительно» ↔ отказ для A или B («меньше A или не меньше B»)."""
    groups: dict[tuple[int, int], list[tuple[Line, str]]] = {}
    for x in doc.lines:
        if not x.text or x.is_code:
            continue
        for m in RANGE.finditer(x.joined):
            a, b = _num(m.group(1)), _num(m.group(2))
            if a is not None and b is not None and a < b:
                groups.setdefault((a, b), []).append((x, m.group(0)))
    if not groups:
        return
    emitted = 0
    for y in doc.lines:
        if not y.text or y.is_code:
            continue
        rejecting = bool(REJECT.search(y.joined))
        cmps = [(_op_of(m.group(1)), _num(m.group(2)), m.group(0)) for m in CMP.finditer(y.joined)
                if _num(m.group(2)) is not None]
        if not cmps or not (rejecting or (y.cells is not None and len(cmps) >= 2)):
            continue
        # «должна быть не меньше A и меньше B, иначе 400» и ячейка «Logic» параметра («больше A и меньше B»)
        # задают допустимую область; «400 | меньше A или не меньше B» — область отказа
        must = bool(MUST.search(y.joined)) or not rejecting
        for (a, b), members in groups.items():
            members = [(x, rq) for x, rq in members if x is not y]
            if not members:
                continue
            vals = {v for _, v, _ in cmps}
            if not ({a, b} <= vals):
                continue
            ys = _subj_stems(y.joined)
            if not any(ys & _subj_stems(x.joined) for x, _ in members):
                continue  # другая величина с теми же числами
            bad = [(op, v, q) for op, v, q in cmps if v in (a, b) and (_includes(op, v, v) != must)]
            if not bad:
                continue
            op, v, q = bad[0]
            frag = _clause(y.joined, q)
            members.sort(key=lambda m: (m[0].cells is not None, m[0].n))
            x, rq = members[0]
            if len(members) > 1:  # вторая формулировка того же диапазона (например, в таблице API)
                x2, rq2 = members[1]
                out.setdefault("_extra_ev", []).append(ev(x2, rq2))
            _emit(out, "conflicts.boundary_range", "boundary_conflict", y, frag, x, rq,
                  title=f"Граница {_fmt(v)} допустима по одному месту и даёт отказ по другому",
                  problem=(f"{quoted(rq)} — значение {_fmt(v)} допустимо, а по {quoted(frag)} для {_fmt(v)} "
                           "предусмотрен отказ."),
                  scenario=f"Клиент передаёт ровно {_fmt(v)}: по диапазону значение принимается, по правилу ошибки — нет.",
                  recommendation=f"Согласовать границу: если {_fmt(v)} допустимо, ошибка — только за пределами диапазона.",
                  question=f"Допустимо ли значение {_fmt(v)}?")
            emitted += 1
            break
        if emitted >= 3:
            return


def _clause(text: str, needle: str) -> str:
    k = text.find(needle)
    if k < 0:
        return text[:200]
    s0 = max(text.rfind(".", 0, k) + 1, text.rfind("|", 0, k) + 1, 0)
    e = [p for p in (text.find(".", k + len(needle)), text.find("|", k + len(needle))) if p != -1]
    frag = text[s0:min(e) if e else len(text)].strip()
    return frag if len(frag) <= 200 else needle


def rule_noun_bounds(doc: Doc, out: dict) -> None:
    """«выполняется, если не превысит X» ↔ «отклоняется, если достигнет X или превысит»."""
    items = []
    for s in sentences(doc):
        pol = -1 if REJECT.search(s.body) else (1 if ALLOW.search(s.body) else 0)
        if not pol:
            continue
        for m in CMP.finditer(s.body):
            bound = m.group(2)
            if _num(bound) is not None or len(bound) < 4:
                continue
            op = _op_of(m.group(1))
            if not op:
                continue
            subj = _stems(s.body[:m.start()]) - {_stem(bound)}
            items.append((s, op, _stem(bound), pol, subj, m.group(0)))
    for i, (a, opa, ba, pa, sa, qa) in enumerate(items):
        for b, opb, bb, pb, sb, qb in items[i + 1:]:
            if ba != bb or pa == pb or a.line.n == b.line.n or not (sa & sb):
                continue
            allow, reject = ((a, opa), (b, opb)) if pa > 0 else ((b, opb), (a, opa))
            if _includes(allow[1], 0, 0) and _includes(reject[1], 0, 0):  # равенство попадает в оба исхода
                _emit(out, "conflicts.boundary_reach", "boundary_conflict", allow[0], allow[0].text, reject[0],
                      reject[0].text,
                      title="Значение, равное границе, и разрешено, и запрещено",
                      problem=(f"{quoted(allow[0].body)} разрешает случай «ровно на границе», а "
                               f"{quoted(reject[0].body)} его запрещает."),
                      scenario="Операция доводит величину ровно до границы: по одному правилу она проходит, по другому "
                               "отклоняется.",
                      recommendation="Указать явно, допустимо ли значение, равное границе, и привести оба правила к "
                                     "одному знаку сравнения.",
                      question="Операция, после которой величина ровно равна границе, разрешена?")
                return


# --- граница ↔ критерии приёмки -------------------------------------------------------------------

ACC_HEAD = re.compile(r"исходн|предуслов|услови|дано|given", re.I)
ACC_RES = re.compile(r"ожидаем|результат|then", re.I)
NAMED = re.compile(rf"([А-ЯЁа-яё]+(?:\s+[а-яё]+)?)\s+({NUM})\s*(?:₸|тенге|руб\w*|₽|\$|%|сут\w*|дн\w*)?", re.I)
NEG_OUT = re.compile(r"\bне\s+[а-яё]+|отклон\w*|отказ\w*|ошибк\w*", re.I)


def _acceptance_rows(doc: Doc) -> list[tuple[Line, list[str]]]:
    rows = []
    for t in tables(doc):
        cols = t.cols
        if len(cols) >= 3 and ACC_HEAD.search(cols[0]) and any(ACC_RES.search(c) for c in cols):
            rows += [(r, r.cells) for r in t.rows if r.cells and len(r.cells) >= 3]
    return rows


def _values(text: str) -> dict[str, tuple[int, str]]:
    res: dict[str, tuple[int, str]] = {}
    for m in NAMED.finditer(text):
        noun = _words(m.group(1))
        v = _num(m.group(2))
        if not noun or v is None:
            continue
        res.setdefault(_stem(noun[-1] if len(noun[-1]) >= 4 else noun[0]), (v, m.group(0)))
        res.setdefault(_stem(noun[0]), (v, m.group(0)))
    return res


def rule_acceptance_bounds(doc: Doc, out: dict) -> None:
    rows = _acceptance_rows(doc)
    if not rows:
        return
    rules = []
    for s in sentences(doc):
        for m in CMP.finditer(s.body):
            op = _op_of(m.group(1))
            if not op:
                continue
            subj = [w for w in _words(s.body[:m.start()]) if len(w) >= 4 and w not in STOP]
            if not subj:
                continue
            rules.append((s, op, m.group(2), subj, m))
    for s, op, bound, subj, m in rules:
        bnum = _num(bound)
        for r, cells in rows:
            act, res = cells[-2], cells[-1]
            vals_all = _values(" ".join(cells[:-1]))
            vals_res = _values(res)
            subj_key = next((_stem(w) for w in reversed(subj) if _stem(w) in vals_all or _stem(w) in vals_res), None)
            if subj_key is None:
                continue
            if bnum is None:  # «остаток не выше границы → действие»: строка с величиной, равной границе
                bkey = _stem(bound)
                if bkey not in vals_all or subj_key not in vals_all or subj_key == bkey:
                    continue
                v, vq = vals_all[subj_key]
                bv, bq = vals_all[bkey]
                if v != bv:
                    continue
                # величина задана в исходных условиях, а действие добавляет другую сумму — сравнивается уже не она
                if vq not in act and _values(act) and any(x[0] != v for x in _values(act).values()):
                    continue
                pol = -1 if REJECT.search(s.body) else (1 if ALLOW.search(s.body) else 0)
                if not pol:
                    continue
                predicted = pol if _includes(op, v, bv) else -pol
                actual = -1 if NEG_OUT.search(res) else 1
                if predicted == actual:
                    continue
                _emit(out, "conflicts.boundary_acceptance", "boundary_conflict", s, s.text, r,
                      " | ".join(cells[1:]) if len(" | ".join(cells[1:])) <= 200 else res,
                      title="Критерий приёмки на границе противоречит правилу",
                      problem=(f"По правилу {quoted(s.body)} при равенстве ({vq} и {bq}) исход "
                               f"{'наступает' if predicted > 0 else 'не наступает'}, а критерий приёмки ожидает "
                               f"{quoted(res)}."),
                      scenario=f"Значение ровно на границе ({v}): реализация по правилу и тест по критерию дадут разный "
                               "исход.",
                      recommendation="Определить, включается ли граница, и исправить правило или критерий приёмки.",
                      question="Включается ли граница в условие?")
                return
            # «величина меньше N» ↔ ожидаемый результат «величина N»
            if subj_key in vals_res and m.group(1).lower() in ("меньше", "менее", "больше", "более") and \
                    not re.search(r"\bне\s+$", s.body[:m.start()]):
                v, vq = vals_res[subj_key]
                if v == bnum and not _includes(op, v, bnum):
                    _emit(out, "conflicts.boundary_acceptance", "boundary_conflict", s, s.text, r,
                          " | ".join(cells[1:]) if len(" | ".join(cells[1:])) <= 200 else res,
                          title=f"Критерий приёмки ожидает {_fmt(v)}, а правило исключает это значение",
                          problem=(f"Правило {quoted(s.body)} строго исключает {_fmt(v)}, а критерий приёмки ожидает "
                                   f"{quoted(res)}."),
                          scenario=f"Итог ровно {_fmt(v)}: по правилу так быть не может, по критерию приёмки это верный "
                                   "результат.",
                          recommendation="Указать, включается ли граница («не больше» или «меньше»), и согласовать "
                                         "критерий приёмки.",
                          question=f"Допустимо ли значение ровно {_fmt(v)}?")
                    return


BOUND_REASON = re.compile(r"превыша\w*|превышен\w*|максим\w*|минимал\w*|меньше\s+минимал\w*|вне\s+диапазон\w*|"
                          r"больше\s+допустим\w*|за\s+пределами", re.I)


def rule_range_acceptance(doc: Doc, out: dict) -> None:
    """Диапазон «от A до B включительно» ↔ строка приёмки, где значение ровно A или B отклоняется."""
    rows = _acceptance_rows(doc)
    if not rows:
        return
    ranges = []
    for x in doc.lines:
        if not x.text or x.is_code or REJECT.search(x.joined):
            continue
        for m in RANGE.finditer(x.joined):
            a, b = _num(m.group(1)), _num(m.group(2))
            if a is not None and b is not None and a < b:
                ranges.append((x, a, b, m.group(0)))
    for r, cells in rows:
        res = cells[-1]
        if not NEG_OUT.search(res):
            continue
        vals = {_num(m.group(0)) for m in re.finditer(NUM, " ".join(cells[:-1]))}
        for x, a, b, rq in ranges:
            v = b if b in vals else (a if a in vals else None)
            if v is None:
                continue
            if not BOUND_REASON.search(res):
                continue  # отказ объяснён именно границей («превышает максимальную»), а не другим событием
            row_q = " | ".join(cells) if len(" | ".join(cells)) <= 200 else res
            _emit(out, "conflicts.range_acceptance", "boundary_conflict", x, _clause(x.joined, rq), r, row_q,
                  title=f"Критерий приёмки отклоняет {_fmt(v)}, хотя это значение входит в допустимый диапазон",
                  problem=(f"{quoted(rq)} — значение {_fmt(v)} допустимо, а критерий приёмки ожидает отказ: "
                           f"{quoted(res)}."),
                  scenario=f"Операция ровно на {_fmt(v)}: по требованию она проходит, по критерию приёмки — отклоняется.",
                  recommendation="Исправить критерий приёмки или границу диапазона, чтобы они совпадали.",
                  question=f"Значение {_fmt(v)} допустимо?")
            return


def run(doc: Doc, out: dict) -> None:
    rule_events(doc, out)
    rule_ranges(doc, out)
    rule_noun_bounds(doc, out)
    rule_acceptance_bounds(doc, out)
    rule_range_acceptance(doc, out)
