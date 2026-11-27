"""Линза «Тестировщик» (№06): исполнение критериев приёмки, проверяемость, покрытие, тест-кейсы.

Модель отвечает тремя списками (схема :data:`SCHEMA`):

* ``acceptance_checks`` — по записи на каждую строку критериев приёмки: факты строки → правила →
  ожидаемый по правилам результат → заявленный результат → ``verdict``;
* ``candidates`` — дефекты проверяемости и покрытия (общая схема кандидатов, CONTRACT 2.3);
* ``test_cases`` — черновик тест-кейсов «Дано / Когда / Тогда».

Код (:func:`postprocess`) превращает ``conflict`` в critical-кандидата с цитатами правила и строки,
``undefined`` — в major, убирает дубли модели по тем же строкам, нумерует тест-кейсы ``T-01…`` и
отмечает строки приёмки, которые модель пропустила. Серьёзность замечаний о покрытии приёмкой и о
проверяемости код уточняет по фактам (доля проверенных функциональных требований; числовой норматив в цитате).
"""
from __future__ import annotations

import re
from typing import Any, Iterable, Mapping

STAGE = "lens_qa"
SOURCE = "lens:qa"
MAX_TEST_CASES = 12
MAX_MODEL_CANDIDATES = 12
# Лимит ответа сразу 32 000: у моделей с рассуждением (haiku через claude -p) 16 000 включают рассуждение,
# и на документе с 4 строками приёмки ответ иногда не помещается — обрезанная попытка стоит целого вызова (3–5 мин).
MAX_OUTPUT_TOKENS = 32000
UNDEFINED_PREFIX = "Не определено требованиями"

KINDS = ["event_conflict", "status_conflict", "unit_mismatch", "boundary_conflict", "contradiction",
         "missing_element", "incomplete", "ambiguity", "unverifiable", "non_singular", "design_constraint",
         "terminology", "api_contract", "placeholder", "traceability", "infeasible", "incorrect", "duplicate",
         "security", "ops_risk", "other"]
CRITERIA = ["necessary", "appropriate", "unambiguous", "complete", "singular", "feasible", "verifiable",
            "correct", "conforming", "language", "set_complete", "set_consistent", "set_feasible",
            "set_comprehensible", "set_validatable", "ranked", "modifiable", "traceable", "risk"]
CONFLICT_KINDS = ["event_conflict", "boundary_conflict", "status_conflict", "unit_mismatch", "contradiction"]
VERDICTS = ["match", "conflict", "undefined"]


def _obj(props: dict, required: list | None = None) -> dict:
    return {"type": "object", "additionalProperties": False, "properties": props,
            "required": required if required is not None else list(props)}


_S = {"type": "string"}
_INT = {"type": "integer"}
_IDS = {"type": "array", "items": _S}
_EVIDENCE = {"type": "array", "items": _obj({"quote": _S, "line": _INT})}

CANDIDATE_SCHEMA = _obj({
    "title": _S, "kind": {"type": "string", "enum": KINDS}, "criterion": {"type": "string", "enum": CRITERIA},
    "severity": {"type": "string", "enum": ["critical", "major", "minor"]},
    "requirement_ids": _IDS, "evidence": _EVIDENCE,
    "problem": _S, "scenario": _S, "impact": _S, "recommendation": _S, "rewrite": _S, "question": _S,
    "blocks": {"type": "string", "enum": ["development", "testing", "both", "none"]},
})

# Порядок полей — порядок рассуждения модели: факты → правила → ожидаемое → заявленное → вердикт.
ACCEPTANCE_CHECK_SCHEMA = _obj({
    "row_requirement_id": _S,
    "row_quote": _S,
    "row_line": _INT,
    "row_facts": _S,
    "assumptions": _S,
    "rule_requirement_ids": _IDS,
    "rule_evidence": _EVIDENCE,
    "derivation": _S,
    "expected_by_rules": _S,
    "stated": _S,
    "stated_line": _INT,
    "verdict": {"type": "string", "enum": VERDICTS},
    "conflict_kind": {"type": "string", "enum": CONFLICT_KINDS + ["none"]},
    "explanation": _S,
    "fix": _S,
})

TEST_CASE_SCHEMA = _obj({
    "requirement_ids": _IDS, "title": _S, "given": _S, "when": _S, "then": _S, "gap": _S,
    "expected_defined": {"type": "boolean"},
})

# Проверка нефункциональных требований по элементам измеримости — по записи на каждое НФТ. Пустая строка —
# элемент в тексте не назван. Кандидата и серьёзность строит код (nfr_candidate): слабая модель без этого
# списка пропускала непроверяемое НФТ, а сильная ставила серьёзность по-разному.
NFR_CHECK_SCHEMA = _obj({
    "requirement_id": _S,
    "quote": _S,
    "line": _INT,
    "metric": _S,
    "start_end": _S,
    "share": _S,
    "load": _S,
    "vague_words": _S,
    "rewrite": _S,
})

SCHEMA = _obj({
    "acceptance_checks": {"type": "array", "items": ACCEPTANCE_CHECK_SCHEMA},
    "nfr_checks": {"type": "array", "items": NFR_CHECK_SCHEMA},
    "candidates": {"type": "array", "items": CANDIDATE_SCHEMA},
    "test_cases": {"type": "array", "items": TEST_CASE_SCHEMA},
})


def schema() -> dict:
    return SCHEMA


# ---------------------------------------------------------------- вспомогательное

def _s(x: Any) -> str:
    return x.strip() if isinstance(x, str) else ""


# Названия полей схемы, которые слабая модель переносит в тексты для пользователя («Acceptance не покрывает…»).
_SCHEMA_WORDS = [(re.compile(r"\bacceptance[_ ]checks?\b|\bacceptance\b", re.I), "критерии приёмки"),
                 (re.compile(r"\btest[_ ]cases?\b", re.I), "тест-кейсы"),
                 (re.compile(r"\bexpected_defined\b", re.I), "признак определённости результата"),
                 (re.compile(r"\bcandidates?\b", re.I), "замечания")]


def _t(x: Any) -> str:
    """Текст для пользователя: как :func:`_s`, плюс названия полей схемы — по-русски."""
    text = _s(x)
    for rx, ru in _SCHEMA_WORDS:
        text = rx.sub(lambda m: ru.capitalize() if m.start() == 0 or text[m.start() - 2:m.start()] in (". ", "\n") else ru,
                      text)
    return text


def _ids(x: Any) -> list[str]:
    out: list[str] = []
    for v in x or []:
        v = _s(v)
        if v and v not in out:
            out.append(v)
    return out


def _int(x: Any) -> int | None:
    try:
        n = int(x)
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


def _norm(s: str) -> str:
    s = re.sub(r"[«»“”„\"']", '"', s or "")
    s = re.sub(r"[—–‑−]", "-", s)
    return re.sub(r"\s+", " ", s).strip().lower()


def _sentence(s: str) -> str:
    s = _s(s)
    return s if not s or s[-1] in ".!?…»\"" else s + "."


def _lower_first(s: str) -> str:
    """«Итог 50» → «итог 50» внутри фразы; аббревиатуры («HTTP 400», «ОК») не трогаем."""
    return s[0].lower() + s[1:] if len(s) > 1 and s[0].isupper() and s[1].islower() else s


def _req_index(requirements: Iterable[Mapping[str, Any]] | None) -> dict[str, Mapping[str, Any]]:
    return {str(r.get("id")): r for r in requirements or [] if r.get("id")}


def _label(rid: str, index: Mapping[str, Mapping[str, Any]]) -> str:
    """«R-06 (Ф-2)» — ID нарезки и исходный номер, если он есть."""
    src = _s((index.get(rid) or {}).get("source_id"))
    return f"{rid} ({src})" if src and src != rid else rid


def _labels(ids: list[str], index: Mapping[str, Mapping[str, Any]]) -> str:
    return ", ".join(_label(i, index) for i in ids) if ids else "правила документа"


def acceptance_rows(requirements: Iterable[Mapping[str, Any]] | None) -> list[str]:
    """ID требований вида acceptance — строки критериев приёмки, которые линза обязана исполнить."""
    return [str(r["id"]) for r in requirements or [] if r.get("id") and r.get("kind") == "acceptance"]


def resolve_row_id(check: Mapping[str, Any], requirements: Iterable[Mapping[str, Any]] | None) -> str:
    """ID строки приёмки: требование acceptance, в которое попадает номер строки; иначе ID модели, если он есть
    в нарезке. Номер строки надёжнее: модель путает соседние ID, а без таблицы даёт всем строкам один «ID»."""
    reqs = list(requirements or [])
    rid = _s(check.get("row_requirement_id"))
    line = _int(check.get("row_line"))
    if line:
        for r in reqs:
            lo = _int(r.get("line_start"))
            hi = _int(r.get("line_end")) or lo
            if r.get("kind") == "acceptance" and lo and lo <= line <= (hi or lo):
                return str(r["id"])
    if any(str(r.get("id")) == rid for r in reqs):
        return rid
    return rid if not reqs else ""


def missing_rows(checks: list[Mapping[str, Any]], requirements: Iterable[Mapping[str, Any]] | None) -> list[str]:
    done = {_s(c.get("row_requirement_id")) for c in checks}
    return [rid for rid in acceptance_rows(requirements) if rid not in done]


# ---------------------------------------------------------------- acceptance_checks

_AMOUNT = re.compile(r"(?<![\d.,])\d{1,3}(?:[   ]\d{3})+(?:[.,]\d+)?(?![\d])|(?<![\d.,])\d+(?:[.,]\d+)?(?![\d])")
_STOP = {"и", "в", "на", "по", "с", "к", "за", "из", "не", "что", "для", "от", "до", "а", "или", "при"}
NEAR_SHARE = 0.01  # расхождение вычисленных сумм до 1 % — способ округления или ошибка счёта модели


def _amounts(text: str) -> list[tuple[float, bool]]:
    """Числа текста: (значение, есть дробная часть). «11 890,36» → (11890.36, True)."""
    out = []
    for m in _AMOUNT.finditer(text or ""):
        raw = re.sub(r"[   ]", "", m.group(0)).replace(",", ".")
        try:
            out.append((float(raw), "." in raw))
        except ValueError:
            continue
    return out


def _words(text: str) -> set[str]:
    text = _AMOUNT.sub(" ", _norm(text))
    return {w[:5] for w in re.findall(r"[а-яёa-z]+", text) if w not in _STOP and len(w) > 1}


def near_amount_only(expected: str, stated: str) -> tuple[float, float] | None:
    """Выведенное и заявленное различаются только вычисленной суммой с дробной частью, и не больше чем на
    :data:`NEAR_SHARE` (11 903,07 против 11 890,36): это способ округления или арифметическая ошибка модели, а не
    противоречие правилу. Целые значения (999 и 1 000, 49 999 и 50 000) сюда не попадают — это границы и счёт.
    Возвращает пару (по правилам, заявлено) или None."""
    e, s = _amounts(expected), _amounts(stated)
    e_only = [x for x in e if all(abs(x[0] - y[0]) > 1e-9 for y in s)]
    s_only = [y for y in s if all(abs(y[0] - x[0]) > 1e-9 for x in e)]
    if not e_only or len(e_only) != len(s_only):
        return None
    pairs = []
    for y in s_only:
        x = min(e_only, key=lambda x: abs(x[0] - y[0]))
        top = max(abs(x[0]), abs(y[0]))
        if not (x[1] or y[1]) or not top or abs(x[0] - y[0]) / top > NEAR_SHARE:
            return None
        pairs.append((x[0], y[0]))
    sw, ew = _words(stated), _words(expected)
    if sw and len(sw - ew) > len(sw) // 4:  # остальной текст заявленного должен совпадать с выведенным
        return None
    return pairs[0]


_HTTP_CODE = re.compile(r"(?<!\d)[1-5]\d\d(?!\d)|(?i:\bкод\w*|\bстатус\w*)|\b[A-Z]{3,}(?:_[A-Z]+)*\b")
_NEG_BEFORE = re.compile(r"(?:\bне|\bнет|\bбез|\bни)\s*$")


def stated_within_expected(expected: str, stated: str) -> bool:
    """Заявленный результат строки дословно входит в выведенный по правилам («Истёк срок: показано «QR-код
    недействителен»; код ответа не определён» ⊃ «Показано «QR-код недействителен»»): строка проверяет часть
    результата, и эта часть выводится. Неопределённость той части, которую строка не проверяет (код ответа),
    — не дефект строки, а тест-кейс. Короткие заявленные (меньше 3 слов) и вхождение после отрицания
    («не отправлен» ⊃ «отправлен») не считаются."""
    e, s = _norm(expected).rstrip("."), _norm(stated).rstrip(".")
    if len(s.split()) < 3 or not e:
        return False
    i = e.find(s)
    return i >= 0 and not _NEG_BEFORE.search(e[:i])


def _fmt_amount(v: float) -> str:
    whole, frac = f"{v:,.2f}".split(".")
    return whole.replace(",", " ") + ("," + frac if frac != "00" else "")


def normalize_check(raw: Mapping[str, Any]) -> dict:
    c = {
        "row_requirement_id": _s(raw.get("row_requirement_id")),
        "row_quote": _s(raw.get("row_quote")),
        "row_line": _int(raw.get("row_line")),
        "row_facts": _t(raw.get("row_facts")),
        "assumptions": _t(raw.get("assumptions")),
        "rule_requirement_ids": _ids(raw.get("rule_requirement_ids")),
        "rule_evidence": [{"quote": _s(e.get("quote")), "line": _int(e.get("line"))}
                          for e in raw.get("rule_evidence") or [] if isinstance(e, Mapping) and _s(e.get("quote"))],
        "derivation": _t(raw.get("derivation")),
        "expected_by_rules": _t(raw.get("expected_by_rules")),
        "stated": _s(raw.get("stated")),
        "stated_line": _int(raw.get("stated_line")) or _int(raw.get("row_line")),
        "verdict": raw.get("verdict") if raw.get("verdict") in VERDICTS else "undefined",
        "conflict_kind": raw.get("conflict_kind") if raw.get("conflict_kind") in CONFLICT_KINDS else "none",
        "explanation": _t(raw.get("explanation")),
        "fix": _t(raw.get("fix")),
    }
    if c["verdict"] == "conflict" and c["stated"] and _norm(c["expected_by_rules"]).rstrip(".") == _norm(
            c["stated"]).rstrip("."):
        # Модель сама вывела ровно заявленный результат — это совпадение, а не противоречие.
        c["verdict"] = "match"
    if c["verdict"] in ("conflict", "undefined") and stated_within_expected(c["expected_by_rules"], c["stated"]):
        # Заявленное выводится, неопределённа или шире только часть, которую строка не проверяет (haiku на qr:
        # «показано «QR-код недействителен»» выводится, код ответа 400/410 — нет; это пункт другого замечания).
        c["verdict"] = "match"
        c["partial_match"] = True
    if c["verdict"] == "conflict" and c["conflict_kind"] == "status_conflict" and not _HTTP_CODE.search(
            re.sub(r"«[^»]*»|\"[^\"]*\"", " ", c["stated"])):  # текст сообщения в кавычках — не код («QR-код …»)
        # Строка не называет код ответа — расхождение кодов или тела ответа интерфейса её не опровергает (haiku на
        # qr сверял «показано «QR-код недействителен»» по Ф-5 с телом ответа 410 «QR-код отменён»). Само
        # расхождение кодов — отдельное замечание о контракте, если оно есть.
        c["verdict"] = "match"
        c["code_not_checked"] = True
    near = near_amount_only(c["expected_by_rules"], c["stated"]) if c["verdict"] == "conflict" else None
    if near:
        # Расхождение только в копейках вычисленной суммы: шаг 1 промпта велит считать это совпадением, а слабая и
        # сильная модель всё же дают conflict (sonnet на чистом ТЗ: 11 903,07 против верных 11 890,36 ₸).
        c["verdict"] = "match"
        c["near_amount"] = [near[0], near[1]]
        note = (f"Выведено {_fmt_amount(near[0])}, заявлено {_fmt_amount(near[1])}: расхождение меньше 1 % — "
                "способ округления или погрешность вычисления, не противоречие правилу.")
        c["assumptions"] = f"{_sentence(c['assumptions'])} {note}".strip()
    if c["verdict"] == "conflict":
        # Конфликт без цитаты правила не доказан: остаётся вопросом к документу, а не противоречием.
        if not c["rule_evidence"]:
            c["verdict"] = "undefined"
            c["conflict_kind"] = "none"
        elif c["conflict_kind"] == "none":
            c["conflict_kind"] = "contradiction"
    else:
        c["conflict_kind"] = "none"
    if c["verdict"] == "match":
        c["fix"] = ""
    return c


def _row_evidence(c: Mapping[str, Any]) -> list[dict]:
    """Цитаты строки приёмки: заявленный результат и вход (без дублей, если одна цитата содержит другую)."""
    stated, row = c["stated"], c["row_quote"]
    if row and stated and _norm(stated) in _norm(row):
        return [{"quote": row, "line": c["row_line"]}]
    ev: list[dict] = []
    if stated:
        ev.append({"quote": stated, "line": c["stated_line"]})
    if row and _norm(row) not in _norm(stated):
        ev.append({"quote": row, "line": c["row_line"]})
    return ev


def _row_forms(c: Mapping[str, Any], row: str, index: Mapping[str, Mapping[str, Any]]) -> dict[str, str]:
    """«критерий приёмки №2» в падежах — номер строки в таблице приёмки (по порядку строк документа), а не ID
    нарезки: читатель отчёта ищет строку в своём документе. Без нарезки — по номеру строки документа."""
    rows = sorted((r for r in index.values() if r.get("kind") == "acceptance"),
                  key=lambda r: (_int(r.get("line_start")) or 0, str(r.get("id"))))
    ids = [str(r.get("id")) for r in rows]
    line = c.get("stated_line") or c.get("row_line")
    tail = f" №{ids.index(row) + 1}" if row and row in ids else (f" в строке {line}" if line else "")
    return {"nom": f"критерий приёмки{tail}", "gen": f"критерия приёмки{tail}", "dat": f"критерию приёмки{tail}"}


_DOC_ID = re.compile(r"[A-Za-zА-Яа-яЁё]{1,6}[-.]?\d+(?:[.-]\d+)*")


def _rule_ident(rid: str, index: Mapping[str, Mapping[str, Any]]) -> str:
    """Собственный номер правила в документе («Ф-2»; длинное имя — в кавычках), иначе «в строке N»,
    иначе ID нарезки."""
    r = index.get(rid) or {}
    src = _s(r.get("source_id"))
    if src and src != rid and len(src) <= 40 and not src.lower().startswith("критери"):
        return src if _DOC_ID.fullmatch(src) else f"«{src}»"
    line = _int(r.get("line_start"))
    return f"в строке {line}" if line else rid


def _rule_forms(rules: list[str], index: Mapping[str, Mapping[str, Any]],
                evidence: list[Mapping[str, Any]]) -> dict[str, str]:
    """«правило Ф-2» / «правила Ф-2, Ф-3» в падежах (именительный, родительный, дательный)."""
    names = list(dict.fromkeys(_rule_ident(r, index) for r in rules))[:3]
    if not names:
        lines = [e.get("line") for e in evidence if e.get("line")]
        names = [f"в строке {lines[0]}"] if lines else []
    if not names:
        return {"nom": "правила документа", "gen": "правил документа", "dat": "правилам документа", "true": "верны",
                "title_dat": "правилам документа"}
    joined = ", ".join(names)
    # для заголовка (до 12 слов): короткие номера документа, длинное имя в кавычках — только если короткого нет
    short = [n for n in names if not n.startswith("«")] or names[:1]
    title = ", ".join(short[:2])
    if len(names) == 1:
        return {"nom": f"правило {joined}", "gen": f"правила {joined}", "dat": f"правилу {joined}",
                "true": "верно", "title_dat": f"правилу {title}"}
    return {"nom": f"правила {joined}", "gen": f"правил {joined}", "dat": f"правилам {joined}", "true": "верны",
            "title_dat": f"правилу {title}" if len(short[:2]) == 1 else f"правилам {title}"}


_CASE_BY_PREP = {"по": "строке", "в": "строке", "на": "строке", "из": "строки", "до": "строки", "от": "строки",
                 "у": "строки", "для": "строки", "с": "строки"}


def _line_refs(text: str) -> str:
    """«L038» (номер строки из нумерованного документа) → «строка 38», после предлога — в нужном падеже."""
    def sub(m: re.Match) -> str:
        prep = m.group(1)
        if prep:
            return f"{prep}{_CASE_BY_PREP.get(prep.lower().strip(), 'строка')} {int(m.group(2))}"
        before = m.string[:m.start()].rstrip(" ")
        if not before or before[-1] in ".!?:;\n":
            return f"Строка {int(m.group(2))}" if before or m.start() == 0 else f"строка {int(m.group(2))}"
        if before[-1] in "(,—–-/…" or re.search(r"(?:^|\s)(?:и|или|либо|а|но)$", before, re.I):
            return f"строка {int(m.group(2))}"  # «(L040)», перечисление, «Ф-1 и L150» — уже отделено
        return f"(строка {int(m.group(2))})"  # «особое правило L131 задаёт» → «особое правило (строка 131) задаёт»
    text = re.sub(r"\b(?:строк[а-я]{0,2}\s+)?L0*(\d{1,4})\s*[–…-]\s*L?0*(\d{1,4})\b",
                  lambda m: f"строки {m.group(1)}–{m.group(2)}", text or "", flags=re.I)
    text = re.sub(r"\b(строк[а-я]{0,2}\s+)L0*(\d{1,4})\b", r"\1\2", text, flags=re.I)  # «строке L012»
    return re.sub(r"\b((?:по|в|на|из|до|от|у|для|с)\s+)?L0*(\d{1,4})\b", sub, text, flags=re.I)


def humanize_ids(text: str, index: Mapping[str, Mapping[str, Any]]) -> str:
    """ID нарезки в тексте модели («R-06») → собственный номер документа («Ф-2»), если он короткий;
    иначе ID остаётся (рендер делает его ссылкой на таблицу требований)."""
    rows = [str(r.get("id")) for r in sorted((r for r in index.values() if r.get("kind") == "acceptance"),
                                              key=lambda r: (_int(r.get("line_start")) or 0, str(r.get("id"))))]
    # строка приёмки: «строка R-14», «критерий R-14» → «критерий приёмки №2»
    text = re.sub(r"\b(?:строк[аеиуой]{1,2}|критери[йяюе]м?)\s+(?:приёмки\s+|приемки\s+)?(R-\d+)\b",
                  lambda m: (("К" if m.group(0)[0].isupper() else "к") + f"ритерий приёмки №{rows.index(m.group(1)) + 1}"
                             if m.group(1) in rows else m.group(0)),
                  text or "", flags=re.I)

    def sub(m: re.Match) -> str:
        if m.group(0) in rows:
            return f"критерий приёмки №{rows.index(m.group(0)) + 1}"
        r = index.get(m.group(0)) or {}
        src = _s(r.get("source_id"))
        if src and _DOC_ID.fullmatch(src):
            return src
        line = _int(r.get("line_start"))
        # у требования нет короткого номера («Особые правила, п. 1», «Статус 409») — строка документа; падеж и
        # скобки расставит _line_refs, как для «L128» модели
        return f"L{line:03d}" if line else m.group(0)
    text = re.sub(r"\bR-\d+\b", sub, text)
    text = _line_refs(text)
    text = re.sub(r"\b([A-Za-zА-Яа-яЁё]{1,6}-\d+) \(\1\)", r"\1", text)  # «Ф-2 (Ф-2)» после замены
    return re.sub(r"\b([А-ЯЁA-Z][А-Яа-яЁёA-Za-z]{0,5}-\d+)(?:, \1\b)+", r"\1", text)  # «Ф-6, Ф-6» → «Ф-6»


_RULE_FIX = re.compile(r"^\s*(?:правило|требование)\s*(?:[^:]{0,40})?:\s*", re.I)
_ALT_SENTENCE = re.compile(r"^(?:либо|или|иначе|если|альтернатив|в противном)", re.I)
_EXPECTED_PREFIX = re.compile(r"^\s*(?:ожидаемый результат|ожидается|стало)\s*:\s*", re.I)


def split_fix(fix: str) -> tuple[str, bool]:
    """Исправление модели → (одна формулировка для «было → стало», это правило?). Модель часто пишет два
    варианта («…. Либо правило: …», «…. Если цель строки…»): в «было → стало» идёт первый, без пояснений."""
    fix = _s(fix)
    if not fix:
        return "", False
    is_rule = bool(_RULE_FIX.match(fix))
    text = _RULE_FIX.sub("", fix, count=1) if is_rule else _EXPECTED_PREFIX.sub("", fix, count=1)
    parts = re.split(r"(?<=[.!?])\s+", text)
    kept = [parts[0]] + [p for p in _takewhile_not_alt(parts[1:])]
    text = " ".join(kept).strip()
    text = re.sub(r"\s*\((?:[^()]*:[^()]*)\)\s*(?=[.!?]?$)", "", text)  # хвост «(Ф-2: месяц по дате …)»
    text = text.strip().strip("«»\"").strip()
    return (text[:1].upper() + text[1:]) if text else "", is_rule


def _takewhile_not_alt(parts: list[str]):
    for p in parts:
        if _ALT_SENTENCE.match(p) or re.search(r"(?i)\b(?:либо|или)\s+правило\b", p):
            return
        yield p


def _row_rewrite(c: Mapping[str, Any], new_result: str) -> str:
    """«Было → стало» для строки приёмки: «было» — цитата всей строки таблицы (условия | действие | результат),
    поэтому «стало» — та же строка с исправленной ячейкой результата, готовая к вставке. Если заявленный результат
    не найден в цитате строки — только новая ячейка."""
    row, stated = _s(c.get("row_quote")), _s(c.get("stated")).rstrip(".")
    if not row or not stated or c.get("row_line") != c.get("stated_line"):
        return new_result
    i = row.find(stated)
    if i < 0:
        return new_result
    return f"{row[:i]}{new_result.rstrip('.')}{row[i + len(stated):]}".strip()


def check_to_candidate(c: Mapping[str, Any], index: Mapping[str, Mapping[str, Any]]) -> dict | None:
    """``conflict`` → critical с цитатами правила и строки; ``undefined`` → major; ``match`` → None.

    Тексты — для аналитика банка (рубрика понятности): критерий называется номером строки таблицы
    приёмки, правило — собственным номером документа («Ф-2»), а не ID нарезки; в сценарии — вход и два
    исхода; «было → стало» — одна готовая формулировка той строки, которую она заменяет (``rewrite_line``).
    """
    verdict = c["verdict"]
    if verdict == "match":
        return None
    row = c["row_requirement_id"]
    if (index and row not in index) or (not index and not _RID.fullmatch(row)):
        row = ""
    rules = [r for r in c["rule_requirement_ids"] if r != row and (not index or r in index)]
    row_f = _row_forms(c, row, index)
    rule_f = _rule_forms(rules, index, c["rule_evidence"])
    facts = _sentence(humanize_ids(c["row_facts"], index))
    assumptions = (f" Как прочитано условие: {_lower_first(_sentence(humanize_ids(c['assumptions'], index)))}"
                   if c["assumptions"] else "")
    expected = humanize_ids(_s(c["expected_by_rules"]), index).rstrip(".")
    stated = _s(c["stated"]).rstrip(".")
    explanation = f" {_sentence(humanize_ids(c['explanation'], index))}" if c["explanation"] else ""
    req_ids = _ids(([row] if row else []) + rules)
    rule_ev = [dict(e) for e in c["rule_evidence"][:3]]  # решающая фраза правила бывает третьей
    rewrite, fix_is_rule = split_fix(humanize_ids(c["fix"], index))
    rule_line = next((e.get("line") for e in rule_ev if e.get("line")), None)
    rewrite_line = (rule_line if fix_is_rule else c["stated_line"]) if rewrite else None
    if rewrite and not fix_is_rule:
        rewrite = _row_rewrite(c, rewrite)
    row_cap = row_f["nom"][:1].upper() + row_f["nom"][1:]

    if verdict == "conflict":
        return {
            "title": f"{row_cap} противоречит {rule_f['title_dat']}",
            "kind": c["conflict_kind"] if c["conflict_kind"] in CONFLICT_KINDS else "contradiction",
            "criterion": "set_consistent",
            "severity": "critical",
            "requirement_ids": req_ids,
            "evidence": rule_ev + _row_evidence(c),
            "problem": (f"По {rule_f['dat']} на входе {row_f['gen']} результат — «{expected or 'другой'}», "
                        f"а критерий ожидает «{stated}».{explanation}"),
            "scenario": f"{facts}{assumptions} По {rule_f['dat']}: {expected}. По {row_f['dat']}: {stated}.",
            "impact": (f"Разработчик, реализовав {rule_f['nom']}, получит «{expected}», и тест по {row_f['dat']} "
                       f"упадёт, хотя код верен; код, подогнанный под критерий, нарушит {rule_f['nom']}. "
                       "Приёмка остановится до решения владельца продукта."),
            "recommendation": (
                f"Исправить ожидаемый результат {row_f['gen']} на «{expected}», если {rule_f['true']} {rule_f['nom']}; "
                f"если верен критерий — изменить {rule_f['nom']}. Решает владелец продукта."
                if not fix_is_rule else
                f"Изменить {rule_f['nom']} так, чтобы оно давало «{stated}» (формулировка ниже), или, если "
                f"{rule_f['nom']} {rule_f['true']}, исправить ожидаемый результат {row_f['gen']} на «{expected}». "
                "Решает владелец продукта."),
            "rewrite": rewrite,
            "rewrite_line": rewrite_line,
            "question": (f"Какой результат верен для этого входа: «{expected}» (по {rule_f['dat']}) "
                         f"или «{stated}» (по {row_f['dat']})?"),
            "blocks": "both",
            "source": SOURCE,
            "origin": "acceptance_check",
            "acceptance_row": c["row_requirement_id"] or f"L{c['row_line']}",
            "derivation": c["derivation"],
        }
    missing = re.sub(r"^\s*не определено\s*:?\s*", "", expected, flags=re.I)
    return {
        "title": f"{row_cap}: ожидаемый результат не следует из требований",
        "kind": "incomplete",
        "criterion": "verifiable",
        "severity": "major",
        "requirement_ids": req_ids,
        "evidence": rule_ev + _row_evidence(c),
        "problem": (f"{row_cap} ожидает «{stated}», но требования не задают результат для этого входа"
                    f"{': ' + _lower_first(missing) if missing else ''}.{explanation}"),
        "scenario": f"{facts}{assumptions} По требованиям исход не определён; по {row_f['dat']}: {stated}.",
        "impact": ("Тестировщик не может обосновать ожидаемый результат требованиями, а разработчик реализует "
                   "своё толкование: при приёмке возникнет спор, чья трактовка верна."),
        "recommendation": (f"Дописать в требования правило, из которого следует «{stated}», или убрать этот "
                           f"исход из {row_f['gen']}."),
        "rewrite": rewrite,
        "rewrite_line": rewrite_line,
        "question": "",
        "blocks": "testing",
        "source": SOURCE,
        "origin": "acceptance_check",
        "acceptance_row": c["row_requirement_id"] or f"L{c['row_line']}",
        "derivation": c["derivation"],
    }


# ---------------------------------------------------------------- кандидаты модели и тест-кейсы

_CONFLICT_FAMILY = set(CONFLICT_KINDS) | {"incorrect"}
_RID = re.compile(r"R-\d+")


def normalize_candidate(raw: Mapping[str, Any]) -> dict:
    c = {k: raw.get(k) for k in CANDIDATE_SCHEMA["properties"]}
    for k in ("title", "problem", "scenario", "impact", "recommendation", "rewrite", "question"):
        c[k] = _t(c[k])
    c["kind"] = c["kind"] if c["kind"] in KINDS else "other"
    c["criterion"] = c["criterion"] if c["criterion"] in CRITERIA else "verifiable"
    c["severity"] = c["severity"] if c["severity"] in ("critical", "major", "minor") else "major"
    c["blocks"] = c["blocks"] if c["blocks"] in ("development", "testing", "both", "none") else "testing"
    c["requirement_ids"] = _ids(c["requirement_ids"])
    c["evidence"] = [{"quote": _s(e.get("quote")), "line": _int(e.get("line"))}
                     for e in c["evidence"] or [] if isinstance(e, Mapping) and _s(e.get("quote"))]
    # Critical у линзы тестировщика — только вычисленный конфликт строки приёмки (check_to_candidate: две
    # сверенные цитаты и вывод по шагам). Кандидат модели — не выше major: противоречия двух правил — зона
    # проверки набора (№09), серьёзность по шкале ставит судья. На новых ТЗ №18 critical-противоречия модели
    # были в основном major эталона (коды ответа, единицы), а на чистых версиях haiku давал ложные critical.
    if c["severity"] == "critical":
        c["severity"] = "major"
        c["severity_hint"] = "critical"  # модель считала critical: подсказка судье, в вердикт не идёт
    if c["kind"] == "placeholder" and c["severity"] != "minor":
        c.setdefault("severity_hint", c["severity"])
        c["severity"] = "minor"  # пустой раздел шаблона не мешает ни разработке, ни тестам по правилам
    if c["blocks"] == "none" and c["kind"] in _CONFLICT_FAMILY:
        c["blocks"] = "testing"
    c["source"] = SOURCE
    return c


def _duplicates_check(cand: Mapping[str, Any], flagged_rows: set[str]) -> bool:
    """Модель всё же написала кандидата о противоречии строки приёмки, уже разобранной в acceptance_checks."""
    if cand["kind"] not in _CONFLICT_FAMILY and cand["criterion"] != "set_consistent":
        return False
    return bool(flagged_rows & set(cand["requirement_ids"]))


def normalize_test_case(raw: Mapping[str, Any]) -> dict:
    t = {"requirement_ids": _ids(raw.get("requirement_ids")), "title": _t(raw.get("title")),
         "given": _t(raw.get("given")), "when": _t(raw.get("when")), "then": _t(raw.get("then")),
         "gap": _t(raw.get("gap")), "expected_defined": raw.get("expected_defined") is not False}
    if UNDEFINED_PREFIX.lower() in t["then"].lower():
        t["expected_defined"] = False
    elif not t["expected_defined"]:
        # Модель сняла признак, но написала вывод без оговорки («Январь 14 000 ₸ по Ф-2. Противоречит строке 64»):
        # приставка «Не определено требованиями:» перед готовым выводом читается как «не определено: январь».
        t["then"] = (f"{UNDEFINED_PREFIX} однозначно. По тексту требований: {_lower_first(t['then'])}"
                     if t["then"] else f"{UNDEFINED_PREFIX}.")
    return t


# ---------------------------------------------------------------- сборка

MAX_OTHER_CANDIDATES = 3  # одно о покрытии приёмкой, одно о проверяемости, одно о пустом разделе тестирования
_OTHER = 3  # ранг «прочее» — снимается


def _other_rank(c: Mapping[str, Any]) -> int:
    """Вид замечания модели вне противоречий: 0 — покрытие приёмкой, 1 — проверяемость, 2 — пустой раздел
    (заглушка раздела тестирования), 3 — прочее."""
    if c.get("kind") == "missing_element" and c.get("criterion") == "set_validatable":
        return 0
    if c.get("kind") == "unverifiable":
        return 1
    if c.get("kind") == "placeholder":
        return 2
    return _OTHER


ZONE_ORIGIN = "out_of_zone"
ZONE_NOTE = "вне зоны тестировщика — тема аналитика или архитектора"
MAX_ZONE_HANDOFF = 2  # кандидатов вне зоны, передаваемых судье с пометкой (на незрелом документе)


def limit_other_candidates(cands: list[dict], handoff: bool = False) -> tuple[list[dict], list[dict]]:
    """Противоречия модели (два места — два исхода) остаются все; вне противоречий линза держит свои виды — не
    больше одного замечания о покрытии приёмкой, одного о проверяемости и одного о пустом разделе (заглушка
    «заполняется тестировщиками» — minor). Прочее (неоднозначность одного места, неполнота, контракт API,
    доставка сообщений) — зона аналитика и архитектора.

    ``handoff=False`` — прочее снимается в ``dropped`` (так на вычитанном документе: там это был основной шум
    линзы на корпусе). ``handoff=True`` — до :data:`MAX_ZONE_HANDOFF` таких кандидатов (сильнейшие, по порядку
    модели) идут судье с пометкой зоны (``origin = out_of_zone``, ``zone``): уровень — ``minor``, прежний — в
    ``severity_hint``. Судья держит их наравне с кандидатами владельцев зоны: на официальном (прогон `bf95`)
    линза сама снимала «логика метода не проверяет активность и валюту карты» (С6), а аналитик и архитектор
    в том прогоне его не дали — до судьи пункт эталона не доходил."""
    sev = {"critical": 0, "major": 1, "minor": 2}
    best: dict[int, dict] = {}
    for c in cands:
        if c.get("kind") in _CONFLICT_FAMILY:
            continue
        r = _other_rank(c)
        if r < _OTHER and (r not in best or sev.get(c.get("severity"), 3) < sev.get(best[r].get("severity"), 3)):
            best[r] = c
    keep = {id(c) for c in best.values()}
    others = [c for c in cands if c.get("kind") not in _CONFLICT_FAMILY and _other_rank(c) == _OTHER]
    passed = ({id(c) for c in sorted(others, key=lambda c: sev.get(c.get("severity"), 3))[:MAX_ZONE_HANDOFF]}
              if handoff else set())
    kept, dropped = [], []
    for c in cands:
        if c.get("kind") in _CONFLICT_FAMILY or id(c) in keep:
            kept.append(c)
        elif id(c) in passed:
            kept.append(mark_out_of_zone(c))
        else:
            why = ("второе замечание того же вида" if _other_rank(c) < _OTHER
                   else "вне зоны линзы тестировщика (неоднозначность, неполнота, контракт — у аналитика и архитектора)"
                   + (f"; судье передано не больше {MAX_ZONE_HANDOFF} таких" if handoff else ""))
            dropped.append({**c, "reason": f"снято линзой тестировщика: {why}; вне противоречий — не больше "
                                          f"{MAX_OTHER_CANDIDATES} замечаний (покрытие приёмкой, проверяемость, "
                                          "пустой раздел)"})
    return kept, dropped


def mark_out_of_zone(c: Mapping[str, Any]) -> dict:
    """Кандидат вне зоны линзы — судье с пометкой: ``origin``, ``zone``; уровень ``minor`` (прежний — подсказка)."""
    c = {**c, "origin": ZONE_ORIGIN, "zone": ZONE_NOTE}
    if c.get("severity") != "minor":
        c.setdefault("severity_hint", c.get("severity"))
        c["severity"] = "minor"
    return c


def coverage_share(checks: list[Mapping[str, Any]], reqs: list[Mapping[str, Any]]) -> tuple[int, int]:
    """Сколько функциональных требований проверяет хотя бы одна строка приёмки: (проверено, всего)."""
    functional = {r.get("id") for r in reqs if r.get("kind") == "functional" and r.get("id")}
    covered: set[str] = set()
    for c in checks:
        covered |= set(c.get("rule_requirement_ids") or [])
        # и по строкам процитированных правил: модель перечисляет ID непостоянно (4 или 5 из 14 от прогона к
        # прогону), а цитата решающей фразы правила — устойчивый след того, что строка приёмки его проверяет
        for e in c.get("rule_evidence") or []:
            n = _int(e.get("line"))
            covered |= {r.get("id") for r in reqs if n and (_int(r.get("line_start")) or 0) <= n
                        <= (_int(r.get("line_end")) or _int(r.get("line_start")) or 0)}
    return len(covered & functional), len(functional)


COVERAGE_SEVERITY = "minor"


def _id_span(ids: list[str]) -> str:
    """«T-02, T-03, T-05» или «T-02–T-07» для подряд идущих номеров."""
    nums = [int(i[2:]) for i in ids]
    if len(nums) > 2 and nums == list(range(nums[0], nums[0] + len(nums))):
        return f"{ids[0]}–{ids[-1]}"
    return ", ".join(ids)


def calibrate_coverage(cands: list[dict], checks: list[Mapping[str, Any]], reqs: list[Mapping[str, Any]],
                       tests: list[Mapping[str, Any]] | None = None) -> None:
    """Замечание о покрытии приёмкой — одно на документ и всегда ``minor``: непокрытые границы и ветки
    закрывают тест-кейсы линзы (черновик раздела тестирования), разработку и проверку правил это не
    останавливает. Модель пишет такое замечание на каждом документе, и на чистом тоже (разбор №18: major
    «приёмка не покрывает ветки» на каждом ТЗ — ложная тревога уровня). Факт для читателя — доля
    функциональных требований, которые проверяют строки приёмки, и номера тест-кейсов, которые закрывают
    пробел. Без нарезки (нет функциональных требований) — только серьёзность.
    """
    done, total = coverage_share(checks, reqs)
    gap_tests = [t["id"] for t in tests or [] if t.get("id") and _s(t.get("gap"))]
    for c in cands:
        if _other_rank(c) != 0 or c.get("kind") in _CONFLICT_FAMILY:
            continue
        if c["severity"] != COVERAGE_SEVERITY:
            c.setdefault("severity_hint", c["severity"])
            c["severity"] = COVERAGE_SEVERITY
        # Место замечания — сама таблица критериев приёмки: первая её строка — первой цитатой (модель цитирует
        # непокрытые правила, и замечание о таблице читалось как замечание о правиле возврата).
        first_row = next((ch for ch in checks if ch.get("row_quote") and ch.get("row_line")), None)
        if first_row and not any(e.get("line") == first_row["row_line"] for e in c["evidence"]):
            c["evidence"] = [{"quote": first_row["row_quote"], "line": first_row["row_line"]}] + c["evidence"][:2]
        if not total:
            continue
        fact = f"Строки приёмки проверяют {done} из {total} функциональных требований."
        if fact not in c["problem"]:  # факт — первым: судья видит problem обрезанным до 420 символов
            c["problem"] = f"{fact} {c['problem']}".strip()
        # заголовок называет объект и меру неполноты (рубрика понятности), а не перечень веток модели
        c.setdefault("model_title", c["title"])
        c["title"] = f"Критерии приёмки проверяют {done} из {total} функциональных требований"
        if gap_tests:
            tail = (f"Непокрытые ветки закрывают тест-кейсы {_id_span(gap_tests)} из черновика тестов отчёта — "
                    "их можно перенести в таблицу критериев приёмки.")
            if tail not in c["recommendation"]:
                # фраза модели о тест-кейсах («закрыв их тест-кейсами ниже») — заменяется номерами кейсов
                own = [p for p in re.split(r"(?<=[.!?])\s+", c["recommendation"]) if p and "тест-кейс" not in p.lower()]
                c["recommendation"] = " ".join([_sentence(p) for p in own] + [tail])


# Норматив задан числом с единицей (время, доля, частота) — требование проверяемо, не хватает только условий
# замера (нагрузка, точка отсчёта, окно выборки): это уточнение, minor. Размытые слова без числа — major.
_NUMERIC_TARGET = re.compile(r"\d[\d\s]*(?:[.,]\d+)?\s*(?:%|мс\b|с\b|сек|минут|мин\b|час|ч\b|сут|дн|раз\b|раза\b|запрос)",
                             re.I)
_VAGUE = re.compile(r"быстр|мгновенн|моментальн|своевременн|оперативн|удобн|понятн|всегда|как можно|по возможности|"
                    r"высок\w* нагрузк|надёжн|надежн|\bточно\b|без ошибок|круглосуточн", re.I)


def calibrate_nfr_contradictions(cands: list[dict], reqs: list[Mapping[str, Any]]) -> list[dict]:
    """Противоречие модели, одна сторона которого — нефункциональное требование (срок, окно отправки, свежесть
    данных, доступность), снимается в ``dropped``: такое требование задаёт качество, а не исход операции, и
    расхождение с функциональным правилом — уточнение условий, а не два ожидаемых результата одного теста. На
    чистых ТЗ №18 haiku давал так major в 5 из 6 прогонов grace_clean («напоминание после 12:00», «платёж за
    последние 5 минут»), а судья поднимал и minor обратно до major; в эталонах официального документа и №18
    таких противоречий нет (строки НФТ — только в пунктах о проверяемости, их даёт ``nfr_checks``)."""
    nfr = [(_int(r.get("line_start")), _int(r.get("line_end")) or _int(r.get("line_start")))
           for r in reqs if r.get("kind") == "nonfunctional" and _int(r.get("line_start"))]
    out: list[tuple[dict, dict]] = []
    for c in cands if nfr else []:
        if c.get("kind") not in _CONFLICT_FAMILY or c.get("origin"):
            continue
        lines = [e.get("line") for e in c["evidence"] if e.get("line")]
        if any(lo <= n <= hi for n in lines for lo, hi in nfr):
            out.append((c, {**c, "reason": "снято линзой тестировщика: одна сторона — нефункциональное требование "
                                          "(качество, а не исход операции); это уточнение условий, а не два "
                                          "ожидаемых результата одного теста"}))
    gone = {id(c) for c, _ in out}
    cands[:] = [c for c in cands if id(c) not in gone]
    return [d for _, d in out]


def calibrate_verifiability(cands: list[dict], reqs: list[Mapping[str, Any]]) -> list[dict]:
    """Модельное замечание о проверяемости остаётся, только если в цитатах есть размытая оценка вместо числа
    («удобный», «быстро») — тогда major. Снимается (возвращается для ``dropped``), если (а) оно только о целях
    продукта (цель не тестируется напрямую — её проверяют через требования), (б) в цитатах есть числовой
    норматив и нет размытых слов — тест написать можно, или (в) нет размытых слов и ни одно процитированное
    требование не нефункциональное: «не определено, что показать» у функции — неполнота (зона аналитика), а не
    непроверяемость. Проверяемость НФТ считает код по ``nfr_checks``. На 4 чистых ТЗ №18 (haiku) все такие
    замечания были ложными (цель без базы, «55 дней без точки отсчёта», «14 дней на границе»), на дефектных
    в эталон не попало ни одно."""
    kinds = {r.get("id"): r.get("kind") for r in reqs}

    def kinds_at(line: int | None) -> set:
        return {r.get("kind") for r in reqs if line and (r.get("line_start") or 0) <= line <= (r.get("line_end") or 0)}

    dropped = []
    for c in cands:
        if c.get("kind") != "unverifiable" or c.get("origin") == "nfr_check":
            continue
        ids = [i for i in c["requirement_ids"] if i in kinds]
        cited = set().union(*(kinds_at(e.get("line")) for e in c["evidence"])) if c["evidence"] else set()
        only_goals = bool(ids) and all(kinds[i] == "goal" for i in ids) and cited <= {"goal"}
        quotes = [e["quote"] for e in c["evidence"]]
        vague = any(_VAGUE.search(q) for q in quotes)
        measured = any(_NUMERIC_TARGET.search(q) for q in quotes) and not vague
        nfr = "nonfunctional" in cited or any(kinds.get(i) == "nonfunctional" for i in ids)
        functional_gap = bool(reqs) and bool(ids or cited) and not vague and not nfr
        why = ("цель продукта не проверяется тестом напрямую" if only_goals else
               "норматив задан числом — тест написать можно" if measured else
               "результат функции не описан — это неполнота (зона аналитика), а не непроверяемость"
               if functional_gap else
               "размытой оценки нет; измеримость нефункциональных требований проверена по каждому из них"
               if not vague else "")
        if why:
            dropped.append((c, {**c, "reason": f"снято линзой тестировщика: {why}"}))
    gone = {id(c) for c, _ in dropped}
    cands[:] = [c for c in cands if id(c) not in gone]
    return [d for _, d in dropped]


# ---------------------------------------------------------------- нефункциональные требования

_PERF = re.compile(r"\d\s*(?:мс|с|сек\w*|минут\w*|мин|час\w*|ч)\b|в течение|не дольше|не позднее|не позже|в срок|"
                   r"доступн|запрос|нагрузк|отклик|время ответа|отвеча|\brps\b|\btps\b|в секунду|перцентил", re.I)
_NFR_FIELDS = [("metric", "числовой норматив"), ("start_end", "точки начала и конца замера"),
               ("share", "доля событий или запросов (перцентиль)"), ("load", "нагрузка")]
_EMPTY = re.compile(r"^(?:-|—|<\s*уточнить|нет|отсутству\w*|не\s+(?:указ|зада|назван|определ|опис)\w*|n/?a)", re.I)


def _given(x: Any) -> str:
    """Элемент НФТ, если он назван; «не указано», «нет», «—» — не назван."""
    v = _s(x)
    return "" if not v or _EMPTY.match(v) else v


def normalize_nfr_check(raw: Mapping[str, Any]) -> dict:
    c = {k: _s(raw.get(k)) for k in ("requirement_id", "quote", "metric", "start_end", "share", "load",
                                      "vague_words", "rewrite")}
    c["line"] = _int(raw.get("line"))
    for k in ("metric", "start_end", "share", "load", "vague_words"):
        c[k] = _given(c[k])
    # слова модель часто даёт уже в кавычках («быстро», «всегда»): кавычки ставит текст замечания
    c["vague_words"] = re.sub(r"[«»“”„\"]", "", c["vague_words"]).strip(" ;,")
    # Размытая оценка — по словарю в цитате; слова модели — только если числа нет совсем (слабая модель пишет
    # сюда обычные уточнения: «без учёта ручной проверки», «выдерживает»).
    m = _VAGUE.search(c["quote"])
    if m:
        a = len(re.match(r"\w*", c["quote"][::-1][len(c["quote"]) - m.start():]).group(0))
        b = len(re.match(r"\w*", c["quote"][m.end():]).group(0))
        c["vague_words"] = c["vague_words"] or c["quote"][m.start() - a:m.end() + b]
    elif c["metric"]:
        c["vague_words"] = ""
    c["missing"] = [k for k, _ in _NFR_FIELDS if not c[k]]
    # Непроверяемо: размытая оценка, нет числового норматива или не названы ни доля событий, ни нагрузка (норматив
    # без условий, при которых он выполняется). Процент в самом нормативе («доступность не ниже 99,9 %») — доля.
    # Точки замера у времени ответа подразумеваются, одно недостающее условие — уточнение, а не дефект: так
    # записаны НФТ аккуратных документов («не дольше 1 с для 95 % запросов»).
    throughput = re.search(r"в\s+(?:секунду|минуту|час)|/\s*с\b|\brps\b|\btps\b", c["metric"], re.I)
    no_conditions = not c["share"] and not c["load"] and "%" not in c["metric"] and not throughput
    # Доля и нагрузка нужны только нормативу времени, скорости, доступности или пропускной способности; правило
    # вычисления («округляются до тиына»), формат или точность хранения проверяются обычным тестом (haiku на
    # чистом ТЗ записал «округление до тиына» в nfr_checks — ложное «нельзя проверить: нет доли и нагрузки»).
    perf = _PERF.search(f"{c['quote']} {c['metric']}")
    c["no_conditions"] = bool(perf) and bool(c["metric"]) and no_conditions
    c["unverifiable"] = bool(c["quote"]) and (bool(c["vague_words"]) or bool(perf) and (not c["metric"] or no_conditions))
    return c


_FUNCTIONAL_SECTION = re.compile(r"(?<![А-Яа-яЁё])функциональн", re.I)  # «Нефункциональные» сюда не попадает


def section_at(view: Any, line: int | None) -> str:
    """Раздел документа у строки — по заголовкам, которые считает код (docview), а не по метке нарезки."""
    lines = view.get("lines") if isinstance(view, Mapping) else None
    if not line or not isinstance(lines, list) or not 0 < line <= len(lines) or not isinstance(lines[line - 1], Mapping):
        return ""
    return _s(lines[line - 1].get("section"))


def calibrate_nfr_checks(checks: list[dict], reqs: list[Mapping[str, Any]], view: Any = None) -> None:
    """Условия замера (доля, нагрузка) спрашиваются только у нефункционального требования и только если они не
    названы в нём же: (а) срок у функционального требования («блокировка вступает в силу не позднее 10 с после
    ответа») — жёсткий предел для каждого события, его проверяет функциональный тест (на чистой базе корпуса
    haiku без НФТ в нарезке взял такую фразу — ложное «нет доли и нагрузки»); (б) доля и нагрузка, названные в
    соседней фразе того же требования («не дольше 1 с для 95 % запросов при нагрузке до 300 запросов в
    секунду. Сведения учитывают платежи не позднее чем за 5 минут»), относятся ко всему требованию. Размытая
    оценка и отсутствие числа — непроверяемость в любом случае. (в) Требование стоит в разделе функциональных
    требований документа (заголовок по docview) — это функциональный предел, даже если нарезка пометила его
    нефункциональным: на корпусе haiku так размечал «блокировка вступает в силу не позднее 10 секунд» (БК-5)."""
    if not reqs and not view:
        return
    index = _req_index(reqs)

    def kind(c: Mapping[str, Any]) -> str | None:
        if _FUNCTIONAL_SECTION.search(section_at(view, c.get("line")).rsplit("›", 1)[-1]):
            return "functional"
        r = index.get(c.get("requirement_id") or "")
        if r:
            return r.get("kind")
        n = c.get("line")
        for r in reqs:
            lo = _int(r.get("line_start"))
            if n and lo and lo <= n <= (_int(r.get("line_end")) or lo):
                return r.get("kind")
        return None

    def key(c: Mapping[str, Any]):
        return c.get("requirement_id") or c.get("line")

    given = {key(c) for c in checks if c.get("share") or c.get("load")}
    for c in checks:
        if not c.get("unverifiable") or c.get("vague_words") or not c.get("no_conditions"):
            continue
        k = kind(c)
        if (k and k != "nonfunctional") or key(c) in given:
            c["unverifiable"] = False
            c["conditions_from"] = "functional" if k and k != "nonfunctional" else "same_requirement"


_METRIC_IN_QUOTE = re.compile(r"(?:в течение|не дольше|не позднее|не позже|не более|не менее|не ниже)\s+[^,.;]{1,25}?"
                              r"(?=\s+(?:после|для|при|с момента|от|до|на)\b|[,.;]|$)", re.I)


def _vague_terms(text: str) -> list[str]:
    """Размытые оценки короткими словами: «мгновенно; Сервис выдерживает высокие нагрузки; в пиковые часы» →
    [«мгновенно», «высокие нагрузки»] (слова словаря целиком). Фразы без слова словаря — только если словарь не
    нашёл ничего, и не длиннее 4 слов."""
    phrases = [p.strip(" .") for p in re.split(r"[;,]\s*|\s+и\s+", text or "") if p.strip(" .")]
    terms: list[str] = []
    for p in phrases:
        if len(p.split()) <= 3 and _VAGUE.search(p):  # короткая фраза документа целиком: «всегда актуальны»
            if p.lower() not in [x.lower() for x in terms]:
                terms.append(p)
            continue
        for m in _VAGUE.finditer(p):
            a = len(re.match(r"\w*", p[:m.start()][::-1]).group(0))
            b = len(re.match(r"\w*", p[m.end():]).group(0))
            t = p[m.start() - a:m.end() + b]
            if t.lower() not in [x.lower() for x in terms]:
                terms.append(t)
    return terms or [p for p in phrases if len(p.split()) <= 4] or phrases[:1]


def _doc_metric(c: Mapping[str, Any]) -> str:
    """Норматив словами документа: метрика модели, если она есть в цитате дословно, иначе фраза срока из цитаты."""
    if _norm(c["metric"]) in _norm(c["quote"]):
        return c["metric"]
    m = _METRIC_IN_QUOTE.search(c["quote"])
    return m.group(0).strip() if m else ""


def nfr_candidate(checks: list[Mapping[str, Any]], index: Mapping[str, Mapping[str, Any]]) -> dict | None:
    """Одно замечание о проверяемости на документ — по НФТ, которые нельзя проверить тестом (major)."""
    bad = [c for c in checks if c.get("unverifiable")]
    if not bad:
        return None
    first = bad[0]
    src = _s((index.get(first["requirement_id"]) or {}).get("source_id"))
    where = f" (строка {first['line']})" if first["line"] else ""
    if src and _DOC_ID.fullmatch(src):
        name = src
    elif first["metric"] and not first["vague_words"] and _doc_metric(first):
        name = f"Норматив «{_doc_metric(first)}»{where}"  # слова документа, а не пересказ модели («не дольше 60 с»)
    else:
        name = f"Нефункциональное требование{where}"
    names = dict(_NFR_FIELDS)
    missing = [names[k] for k in first["missing"]]
    more = f" (и ещё {len(bad) - 1})" if len(bad) > 1 else ""
    if first["vague_words"]:
        words = _vague_terms(first["vague_words"])[:2]
        first = {**first, "vague_words": ", ".join(_vague_terms(first["vague_words"]))}
        title = (f"{name}: " if src and _DOC_ID.fullmatch(src) else "") + \
            f"{', '.join('«' + w + '»' for w in words)}{where if not (src and _DOC_ID.fullmatch(src)) else ''} " \
            f"нельзя проверить тестом{more}"
        what = f"размытая оценка «{first['vague_words']}» вместо числа"
        scenario = (f"Замер показывает 3 с на 95-м перцентиле и 9 с на 99-м: по формулировке «{first['vague_words']}» "
                    "одна сторона считает требование выполненным, другая — нет.")
    else:
        short = {"metric": "норматива", "start_end": "точек замера", "share": "доли событий", "load": "нагрузки"}
        gaps = [short[k] for k in first["missing"] if k in ("share", "load")] or [short[k] for k in first["missing"]]
        title = f"{name.replace(where, '') if name.startswith('Норматив') else name} нельзя проверить: нет " \
                f"{' и '.join(gaps[:2])}{more}"  # место — в цитате; заголовок до 12 слов
        dm = _doc_metric(first) or first["metric"]
        what = f"норматив «{dm}» без условий замера" if dm else "нет числового норматива"
        scenario = (f"Нагрузочный тест: 95 % событий уложились в норматив «{dm or '—'}», 5 % — нет; "
                    "доля и нагрузка в документе не названы — нельзя решить, пройден ли тест.")
    rest = "; ".join(f"«{c['quote']}»" for c in bad[1:3])
    problem = (f"«{first['quote']}» — {what}"
               + (f"; не заданы: {', '.join(missing)}" if missing else "") + ". "
               + "Тест не может дать ответ «пройден» или «не пройден»."
               + (f" То же: {rest}." if rest else ""))
    return {
        "title": title,
        "kind": "unverifiable",
        "criterion": "verifiable",
        "severity": "major",
        "requirement_ids": _ids(c["requirement_id"] for c in bad if not index or c["requirement_id"] in index),
        "evidence": [{"quote": c["quote"], "line": c["line"]} for c in bad[:3]],
        "problem": problem,
        "scenario": scenario,
        "impact": ("Тестировщик не напишет нагрузочный тест с критерием прохождения, приёмка требования превратится "
                   "в спор, а деградацию под нагрузкой банк увидит только в эксплуатации."),
        "recommendation": ("Записать норматив измеримо: значение с единицей, точку начала и конца замера, долю "
                           "событий (перцентиль) и нагрузку, при которой он выполняется."),
        "rewrite": _t(first["rewrite"]),
        "rewrite_line": first["line"],
        "question": "",
        "blocks": "testing",
        "source": SOURCE,
        "origin": "nfr_check",
    }


def _verified_line(view: Any, quote: str, line: int | None) -> int | None:
    """Строка цитаты в документе (сверка кодом, как у этапа quotes); без документа или без находки — строка модели."""
    if not view or not quote:
        return line
    try:
        from .. import quotes
        m = quotes.verify_quote(view, quote, line)
    except Exception:  # noqa: BLE001 — уточнение строки не условие работы линзы
        return line
    return _int(m.get("line_start")) if m else line


def mature_document(view: Any) -> bool:
    """Вычитанный документ (термины, версия, явный пояс, нет заглушек — признаки линзы «Аналитик»)."""
    if not view:
        return False
    from .lens_analyst import maturity
    return bool(maturity(view).get("mature"))


NO_QUOTE_REASON = "снято линзой тестировщика: нет ни одной цитаты документа"
COVERAGE_MATURE_REASON = ("снято линзой тестировщика: документ вычитан (термины, версия, явный часовой пояс, нет "
                          "заглушек) — таблица приёмки в нём сознательная выборка ключевых сценариев; непокрытые "
                          "ветки — в черновике тест-кейсов отчёта, а не дефект требований")


def drop_coverage_on_mature(cands: list[dict]) -> list[dict]:
    """Замечание о покрытии приёмкой на вычитанном документе — в ``dropped``. На корпусе (8 чистых документов, haiku)
    это было 8 из 11 ложных замечаний линзы; на официальном документе и ТЗ №18 (незрелые: заглушки, нет версии
    и терминов) замечание остаётся — там покрытие входит в эталон (С18)."""
    out = [c for c in cands if _other_rank(c) == 0 and c.get("kind") not in _CONFLICT_FAMILY]
    gone = {id(c) for c in out}
    cands[:] = [c for c in cands if id(c) not in gone]
    return [{**c, "reason": COVERAGE_MATURE_REASON} for c in out]


def postprocess(data: Mapping[str, Any] | None, requirements: Iterable[Mapping[str, Any]] | None = None,
                view: Any = None) -> dict:
    """Ответ модели → ``{"candidates", "acceptance_checks", "test_cases", "warnings"}``.

    ``requirements`` — выход нарезки (нужны ``id``, ``source_id``, ``kind``). Без него линза работает,
    но не знает исходных номеров и не может проверить, что исполнены все строки приёмки. ``view`` — документ
    (docview): по нему код уточняет строки цитат НФТ, раздел документа и зрелость; без него — как раньше.
    """
    data = data or {}
    reqs = list(requirements or [])
    index = _req_index(reqs)
    warnings: list[str] = []

    checks: list[dict] = []
    seen_rows: set[tuple] = set()
    for raw in data.get("acceptance_checks") or []:
        if not isinstance(raw, Mapping):
            continue
        c = normalize_check(raw)
        c["row_requirement_id"] = resolve_row_id(c, reqs)
        # Ключ — строка документа: без таблицы требований модель даёт всем строкам одинаковый «ID».
        key = (c["row_line"],) if c["row_line"] else (c["row_requirement_id"], _norm(c["row_quote"]))
        if key in seen_rows:
            warnings.append(f"{STAGE}: строка приёмки {c['row_requirement_id'] or key[0]} исполнена дважды, "
                            "оставлена первая запись")
            continue
        seen_rows.add(key)
        checks.append(c)
    order = {rid: i for i, rid in enumerate(acceptance_rows(reqs))}
    checks.sort(key=lambda c: (order.get(c["row_requirement_id"], len(order)), c["row_line"] or 0))
    for rid in missing_rows(checks, reqs):
        warnings.append(f"{STAGE}: строка критериев приёмки {rid} не исполнена моделью")

    candidates: list[dict] = []
    flagged: set[str] = set()
    for c in checks:
        cand = check_to_candidate(c, index)
        if cand and not any(_s(e.get("quote")) for e in cand["evidence"]):
            warnings.append(f"{STAGE}: строка приёмки {c['row_requirement_id'] or c['row_line'] or '?'} без цитат "
                            "строки и правила — замечание не построено")
            continue
        if cand:
            candidates.append(cand)
            flagged.add(c["row_requirement_id"])

    nfr_checks = [normalize_nfr_check(x) for x in data.get("nfr_checks") or [] if isinstance(x, Mapping)]
    for c in nfr_checks:
        c["line"] = _verified_line(view, c["quote"], c["line"])
    calibrate_nfr_checks(nfr_checks, reqs, view)
    nfr = nfr_candidate(nfr_checks, index)
    model_cands = [normalize_candidate(x) for x in data.get("candidates") or [] if isinstance(x, Mapping)]
    # Без единой цитаты замечание не доказано: в dropped линзы с понятной причиной, а не в «цитата не найдена» сверки.
    no_quote = [c for c in model_cands if not c["evidence"]]
    model_cands = [c for c in model_cands if c["evidence"]]
    for c in model_cands:  # тексты для читателя: «L040» → «строка 40», ID нарезки → номер документа (рубрика, п. 7)
        for k in ("title", "problem", "scenario", "impact", "recommendation", "rewrite", "question"):
            c[k] = humanize_ids(c[k], index)
    if nfr:  # вычисленное замечание о проверяемости — первым: модельное того же вида уйдёт в dropped
        model_cands.insert(0, nfr)
    kept = [c for c in model_cands if not _duplicates_check(c, flagged)]
    tests = [normalize_test_case(x) for x in data.get("test_cases") or [] if isinstance(x, Mapping)]
    # пустой тест-кейс: «Не определено» в then дописывает normalize_test_case, это не содержание модели
    tests = [t for t in tests if t["title"] or t["when"]]
    known = {str(r.get("id")) for r in reqs if isinstance(r, Mapping) and r.get("id")}
    if known:
        for t in tests:
            t["requirement_ids"] = [x for x in t["requirement_ids"] if x in known]
    for t in tests:  # «(R-12: …)», «L064» в тексте кейса → номер документа и строка (рубрика, п. 7)
        for k in ("title", "given", "when", "then", "gap"):
            t[k] = humanize_ids(t[k], index)
    if len(tests) > MAX_TEST_CASES:
        warnings.append(f"{STAGE}: тест-кейсов {len(tests)}, оставлено {MAX_TEST_CASES}")
        tests = tests[:MAX_TEST_CASES]
    for i, t in enumerate(tests, 1):
        t["id"] = f"T-{i:02d}"
    tests = [{"id": t["id"], **{k: v for k, v in t.items() if k != "id"}} for t in tests]

    mature = mature_document(view)
    kept, dropped = limit_other_candidates(kept, handoff=view is not None and not mature)
    dropped = [{**c, "reason": NO_QUOTE_REASON} for c in no_quote] + dropped
    calibrate_coverage(kept, checks, reqs, tests)
    if mature:
        dropped += drop_coverage_on_mature(kept)
    dropped += calibrate_verifiability(kept, reqs)
    dropped += calibrate_nfr_contradictions(kept, reqs)
    if len(kept) > MAX_MODEL_CANDIDATES:
        warnings.append(f"{STAGE}: кандидатов модели {len(kept)}, оставлено {MAX_MODEL_CANDIDATES}")
        rank = {"critical": 0, "major": 1, "minor": 2}
        kept = sorted(kept, key=lambda c: rank[c["severity"]])[:MAX_MODEL_CANDIDATES]
    candidates.extend(kept)

    return {"candidates": candidates, "acceptance_checks": checks, "test_cases": tests, "warnings": warnings,
            "dropped": dropped, "nfr_checks": nfr_checks}


def retry_instruction(missing: list[str]) -> str:
    """Добавка к заданию для повторного вызова, если модель пропустила строки приёмки."""
    return ("\n\n### Дополнительно\nВ прошлом ответе не исполнены строки критериев приёмки: "
            + ", ".join(missing) + ". Сделай acceptance_checks только для них; candidates и test_cases — пустые.")


def focus_instruction(rows: list[str], rest: int) -> str:
    """Добавка к первому вызову, если строк приёмки больше :data:`BATCH_ROWS`: остальные идут отдельными вызовами."""
    return ("\n\n### Дополнительно\nВ этом ответе исполни только строки критериев приёмки "
            + ", ".join(rows) + f". Остальные {rest} строк будут исполнены отдельным запросом. "
            "candidates и test_cases — по всему документу, как обычно.")


BATCH_ROWS = 10
SHORT_INSTRUCTION = ("\n\n### Дополнительно\nПрошлый ответ не поместился в лимит вывода. Пиши короче: candidates — "
                     "не больше 4, test_cases — не больше 6, каждое текстовое поле — одно-два предложения.")
NO_ROWS = " acceptance_checks — пустой список: строки приёмки исполнены отдельным запросом."
EMPTY_INSTRUCTION = ("\n\n### Дополнительно\nВ прошлом ответе списки nfr_checks, candidates и test_cases пустые. "
                     "Заполни их по документу, как сказано в шагах 1б, 2 и 3; acceptance_checks — пустой список: "
                     "строки приёмки уже исполнены.")


def _empty_answer(data: Mapping[str, Any]) -> bool:
    """Слабая модель изредка возвращает только acceptance_checks (haiku: 1 из 16 прогонов, 22 тыс. токенов вывода):
    без тест-кейсов и кандидатов ответ неполон — тест-кейсы есть на любом документе с требованиями."""
    return not data.get("test_cases") and not data.get("candidates") and not data.get("nfr_checks")


_TRUNC_TEXT = re.compile(r"output token|max_tokens|max output|обрез|не поместился", re.I)


def _is_truncation(exc: BaseException) -> bool:
    """Обрезка ответа: ``llm.Truncated`` или ошибка провайдера, текст которой говорит о лимите вывода
    (``claude -p`` сообщает «response exceeded the 16000 output token maximum» как обычную ошибку)."""
    if type(exc).__name__ == "Truncated" or getattr(exc, "kind", "") == "truncated":
        return True
    return bool(_TRUNC_TEXT.search(f"{getattr(exc, 'message', '')} {exc}"))


def _ask_rows(ctx: Any, system: str, user: str, rows: list[str], stage: str, warnings: list[str]) -> list:
    try:
        extra = ctx.llm.ask(stage, system, user + retry_instruction(rows), SCHEMA,
                            max_output_tokens=MAX_OUTPUT_TOKENS) or {}
    except Exception as exc:  # дополнительный вызов — улучшение, а не условие работы линзы
        warnings.append(f"{STAGE}: строки приёмки {', '.join(rows)} не исполнены: {exc}")
        return []
    return [c for c in extra.get("acceptance_checks") or [] if isinstance(c, Mapping)]


def run(ctx: Any) -> dict:
    """Запуск линзы на контексте каркаса v2 (ctx.prompt, ctx.llm, ctx.requirements).

    Вызовы: один основной; если строк приёмки больше BATCH_ROWS — по одному на каждые следующие BATCH_ROWS строк
    (ответ не упирается в лимит вывода); затем не больше одного повтора по строкам, которые модель пропустила.
    Если основной ответ всё же обрезан — строки приёмки запрашиваются пакетами по 5, а кандидаты и тест-кейсы —
    отдельным коротким запросом; этап получает статус partial.
    """
    system, user = ctx.prompt(STAGE)
    reqs = list(getattr(ctx, "requirements", None) or [])
    rows = acceptance_rows(reqs)
    first, later = rows[:BATCH_ROWS], rows[BATCH_ROWS:]
    warnings: list[str] = []
    partial = False
    main_user = user + focus_instruction(first, len(later)) if later else user
    try:
        data = dict(ctx.llm.ask(STAGE, system, main_user, SCHEMA, max_output_tokens=MAX_OUTPUT_TOKENS) or {})
    except Exception as exc:
        if not _is_truncation(exc):
            raise
        partial = True
        warnings.append(f"{STAGE}: ответ обрезан по лимиту вывода — строки приёмки и тест-кейсы запрошены раздельно")
        later = rows  # все строки — пакетами ниже
        short = SHORT_INSTRUCTION + (NO_ROWS if rows else "")
        try:
            data = dict(ctx.llm.ask(f"{STAGE}_short", system, user + short, SCHEMA,
                                        max_output_tokens=MAX_OUTPUT_TOKENS) or {})
        except Exception as exc2:
            if not _is_truncation(exc2):
                raise
            data = {}
            warnings.append(f"{STAGE}: короткий ответ тоже обрезан — кандидаты и тест-кейсы линзы не получены")
        if rows:
            data["acceptance_checks"] = []
    if not partial and reqs and _empty_answer(data):
        warnings.append(f"{STAGE}: в ответе только строки приёмки — кандидаты и тест-кейсы запрошены повторно")
        try:
            extra = dict(ctx.llm.ask(f"{STAGE}_rest", system, user + EMPTY_INSTRUCTION, SCHEMA,
                                     max_output_tokens=MAX_OUTPUT_TOKENS) or {})
            for key in ("nfr_checks", "candidates", "test_cases"):
                data[key] = extra.get(key) or []
        except Exception as exc:  # повтор — улучшение, а не условие работы линзы
            warnings.append(f"{STAGE}: повторный запрос кандидатов не удался: {exc}")
    checks = [c for c in data.get("acceptance_checks") or [] if isinstance(c, Mapping)]
    step = BATCH_ROWS // 2 if partial else BATCH_ROWS
    for i in range(0, len(later), step):
        checks += _ask_rows(ctx, system, user, later[i:i + step], f"{STAGE}_rows", warnings)
    missing = missing_rows([normalize_check(c) for c in checks], reqs)
    if missing:
        checks += _ask_rows(ctx, system, user, missing[:BATCH_ROWS], f"{STAGE}_retry", warnings)
    data["acceptance_checks"] = checks
    out = postprocess(data, reqs, getattr(ctx, "view", None))
    out["warnings"] = warnings + out["warnings"]
    if missing_rows(out["acceptance_checks"], reqs):
        partial = True
    warn = getattr(ctx, "warn", None)
    if callable(warn):  # каркас сам кладёт ctx.warnings в файл этапа и в паспорт — без дубля в out["warnings"]
        for w in out["warnings"]:
            warn(w)
        out["warnings"] = []
    if partial:
        out["_partial"] = True
    return out
