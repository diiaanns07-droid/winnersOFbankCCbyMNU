"""Обратная задача к сверке реестров: критерий приёмки → правило, которое он проверяет.

Вход — ``fixtures/acceptance_links.md`` (PDF собирается из него в тесте), путь движка —
``bcc_review.engine.read_document`` → ``build_inventory``. Четыре критерия приёмки:

* АК-1 — явная ссылка на существующее правило («ДК-2: …»);
* АК-2 — однозначный текст без внешнего ID (выписка по кредитной карте → КК-2);
* АК-3 — похожие правила двух продуктов (ДК-1 и КК-1: три неверных PIN подряд);
* АК-4 — ссылка на отсутствующий пункт («ДК-3: …»);
* строка «Примечание» — пояснение автора, а не критерий.

Реестр не строит связи (это №05 и №06), но обязан донести до них то, из чего связь выводится:
собственный авторский номер критерия (``source_id``) отдельно от присвоенного ID (``R-…``) и
отдельно от номеров, на которые критерий ссылается в тексте. Связь здесь выводится только из
выхода реестра — так видно, что именно реестр способен установить, а что нет.
"""

from __future__ import annotations

import importlib.util
import json
import re

import pytest

from bcc_review.analysis.inventory import build_inventory
from p04_support import (FIXTURES, ScriptedModel, StaticAdapter, assert_invariants, build_pdf_from_md, compare_registries,
                         engine_ask, md_document)

engine = pytest.importorskip("bcc_review.engine", reason="движок bcc/integration не в checkout")

SRC = FIXTURES / "acceptance_links.md"
CRITERIA = ["АК-1", "АК-2", "АК-3", "АК-4"]
# исход для каждого критерия: (как установлена цель, авторские номера целей)
EXPECTED = {
    "АК-1": ("explicit", ["ДК-2"]),
    "АК-2": ("by_text", ["КК-2"]),
    "АК-3": ("ambiguous", ["ДК-1", "КК-1"]),
    "АК-4": ("missing", ["ДК-3"]),
}
_AUTHOR_ID = re.compile(r"(?<![\w-])[A-Za-zА-Яа-яЁё]{1,10}-\d+(?:\.\d+)*(?![\w-])")
_ENGINE_ID = re.compile(r"^(?:R-\d+(?:\.\d+)?|b\d{4,}|F-\d+|AC-\d+)$")


@pytest.fixture(scope="module")
def docs(tmp_path_factory):
    out = {"md": engine.read_document(SRC)}
    if _has_pymupdf():
        out["pdf"] = engine.read_document(build_pdf_from_md(SRC, tmp_path_factory.mktemp("p04acc") / "acceptance.pdf"))
    return out


def _has_pymupdf() -> bool:
    return importlib.util.find_spec("pymupdf") is not None


def _doc(docs, fmt):
    if fmt not in docs:
        pytest.skip("для PDF нужен pymupdf (extra pdf)")
    return docs[fmt]


def _block(doc, start):
    return next(b["id"] for b in doc["blocks"] if b["text"].startswith(start))


def _stems(text: str) -> set[str]:
    return {w[:5] for w in re.findall(r"[\wА-Яа-яЁё-]+", text.lower().replace("ё", "е")) if len(w) >= 4}


def trace(registry: list[dict]) -> dict[str, dict]:
    """Связь «критерий → правило», выведенная только из выхода реестра.

    Явная ссылка — авторский номер в цитате критерия, кроме собственного номера критерия. Нет ссылки —
    кандидаты по общим словам цитат; при равенстве — оба кандидата и слова, которые их различают.
    """
    rules = [r for r in registry if r["kind"] != "acceptance"]
    by_sid = {r["source_id"]: r for r in rules if r["source_id"]}
    out = {}
    for c in (r for r in registry if r["kind"] == "acceptance"):
        quote = " ".join(e["quote"] for e in c["evidence"])
        refs = [m for m in dict.fromkeys(_AUTHOR_ID.findall(quote)) if m != c["source_id"]]
        item = {"req_id": c["id"], "block_id": c["block_ids"][0], "quote": quote, "refs": refs}
        if refs:
            item["targets"] = [(s, by_sid[s]["id"]) for s in refs if s in by_sid]
            item["missing"] = [s for s in refs if s not in by_sid]
            item["how"] = "missing" if item["missing"] else "explicit"
        else:
            words = _stems(quote)
            scored = sorted(((len(words & _stems(" ".join(e["quote"] for e in r["evidence"]))), r) for r in rules),
                            key=lambda x: -x[0])
            best = [r for n, r in scored if n and n == scored[0][0]]
            item["targets"] = [(r["source_id"], r["id"]) for r in best]
            item["how"] = "by_text" if len(best) == 1 else ("ambiguous" if best else "none")
            if len(best) == 2:
                a, b = (_stems(" ".join(e["quote"] for e in r["evidence"])) for r in best)
                item["distinguishing"] = sorted((a ^ b))
                item["distinguishing_in_criterion"] = sorted((a ^ b) & words)
        out[c["source_id"]] = item
    return out


# ---------------------------------------------------------------- 1. что видит следующий этап (без модели)


@pytest.mark.parametrize("fmt", ["md", "pdf"])
def test_registry_keeps_author_ids_apart_from_engine_ids(docs, fmt):
    doc = _doc(docs, fmt)
    inv = build_inventory(doc)
    assert_invariants(doc, inv)
    reqs = inv["requirements"]
    rules = [r for r in reqs if r["kind"] != "acceptance"]
    crit = [r for r in reqs if r["source_id"] in CRITERIA]
    assert [(r["id"], r["source_id"], r["kind"]) for r in rules] == [
        ("R-001", "ДК-1", "functional"), ("R-002", "ДК-2", "functional"),
        ("R-003", "КК-1", "functional"), ("R-004", "КК-2", "functional")]
    assert [(r["id"], r["source_id"], r["kind"]) for r in crit] == [
        ("R-005", "АК-1", "acceptance"), ("R-006", "АК-2", "acceptance"),
        ("R-007", "АК-3", "acceptance"), ("R-008", "АК-4", "acceptance")]
    for r in reqs:  # присвоенные ID и авторские номера не смешиваются
        assert _ENGINE_ID.match(r["id"]) and r["source_id"] != r["id"]
        assert r["source_id"] is None or not _ENGINE_ID.match(r["source_id"]), r
    # ссылки из текста критериев не стали номерами: ДК-3 нигде не зарегистрирован
    assert "ДК-3" not in {r["source_id"] for r in reqs}
    assert [r["source_ref"] for r in crit] == [f"3. Критерии приемки › {s}" for s in CRITERIA]
    # опора критерия — его собственная строка таблицы, а не блок правила
    assert [r["block_ids"] for r in crit] == [[_block(doc, f"{s} |")] for s in CRITERIA]


def test_registry_same_in_md_and_pdf(docs):
    a, b = build_inventory(_doc(docs, "md")), build_inventory(_doc(docs, "pdf"))
    assert compare_registries(a["requirements"], b["requirements"]) == {"pairs": len(a["requirements"]), "issues": []}
    strip = lambda t: {k: {f: v for f, v in x.items() if f != "quote"} for k, x in t.items()}  # noqa: E731
    assert strip(trace(a["requirements"])) == strip(trace(b["requirements"]))


@pytest.mark.parametrize("fmt", ["md", "pdf"])
def test_four_outcomes_from_registry(docs, fmt):
    doc = _doc(docs, fmt)
    t = trace(build_inventory(doc)["requirements"])
    got = {s: (t[s]["how"], [x for x, _ in t[s]["targets"]] or t[s].get("missing")) for s in CRITERIA}
    assert got == EXPECTED
    # 1. явная ссылка: ДК-2 → R-002
    assert t["АК-1"]["refs"] == ["ДК-2"] and t["АК-1"]["targets"] == [("ДК-2", "R-002")]
    assert t["АК-1"]["quote"].startswith("АК-1 | ДК-2: оплата дебетовой картой на 50 000 ₸")
    # 2. без ID, но текст однозначен: «Выписка по кредитной карте» есть только в КК-2
    assert t["АК-2"]["refs"] == [] and t["АК-2"]["targets"] == [("КК-2", "R-004")]
    # 3. две возможные цели: ДК-1 (R-001) и КК-1 (R-003); слова, которые их различают
    #    («дебетовая … на 24 часа» / «кредитная … до обращения в банк»), в критерии отсутствуют
    assert t["АК-3"]["targets"] == [("ДК-1", "R-001"), ("КК-1", "R-003")]
    assert {"дебет", "креди", "обращ"} <= set(t["АК-3"]["distinguishing"])
    assert t["АК-3"]["distinguishing_in_criterion"] == []
    # 4. ссылка на отсутствующий пункт: ДК-3 не зарегистрирован, цель не подставлена
    assert t["АК-4"]["refs"] == ["ДК-3"] and t["АК-4"]["targets"] == [] and t["АК-4"]["missing"] == ["ДК-3"]


# ---------------------------------------------------------------- 2. путь с моделью: ссылка не становится номером


def _answer(doc, criterion_ids):
    """Записанный ответ модели: правила и критерии с дословными цитатами; пояснение — preamble."""
    def it(sid, kind, text, start, quote):
        return {"source_id": sid, "kind": kind, "text": text, "evidence": [{"block_id": _block(doc, start), "quote": quote}]}

    a1, a2, a3, a4 = criterion_ids
    items = [
        it("ДК-1", "functional", "Блокировка дебетовой карты на 24 часа", "ДК-1.", "дебетовая карта блокируется на 24 часа"),
        it("ДК-2", "functional", "SMS по дебетовой карте от 50 000 ₸", "ДК-2.", "на сумму от 50 000 ₸ клиенту отправляется SMS"),
        it("КК-1", "functional", "Блокировка кредитной карты до обращения", "КК-1.", "кредитная карта блокируется до обращения в банк"),
        it("КК-2", "functional", "Выписка 1-го числа", "КК-2.", "Выписка по кредитной карте формируется 1-го числа каждого месяца"),
        it(a1, "acceptance", "Оплата на 50 000 ₸ — SMS", "АК-1 |", "ДК-2: оплата дебетовой картой на 50 000 ₸"),
        it(a2, "acceptance", "1-е число — выписка", "АК-2 |", "Выписка по кредитной карте сформирована"),
        it(a3, "acceptance", "Третий неверный PIN — блокировка", "АК-3 |", "Третий подряд неверный ввод PIN-кода"),
        it(a4, "acceptance", "Снятие сверх лимита отклонено", "АК-4 |", "ДК-3: снятие наличных сверх суточного лимита"),
    ]
    note = {"category": "preamble", "reason": "Пояснение к таблице: валюта и часовой пояс",
            "block_ids": [_block(doc, "Примечание |")]}
    return {"items": items, "excluded": [note], "facts": [], "done": True}


def _registry(inv):
    return [(r["id"], r["source_id"], r["kind"], r["block_ids"], r["origin"]) for r in inv["requirements"]]


@pytest.mark.parametrize("fmt", ["md", "pdf"])
def test_model_reference_in_source_id_is_not_criterion_number(docs, fmt):
    """Модель кладёт в source_id номер правила, на которое ссылается критерий (ДК-2, ДК-3).

    Прежний код (fb5007d): АК-1 отбрасывался («опирается на блоки другого пункта») и шёл повтор,
    АК-4 регистрировался как «ДК-3» — отсутствующий пункт появлялся в реестре, номер АК-4 терялся.
    """
    doc = _doc(docs, fmt)
    good = StaticAdapter(_answer(doc, CRITERIA))
    wrong = StaticAdapter(_answer(doc, ["ДК-2", None, None, "ДК-3"]))
    inv_good = build_inventory(doc, engine_ask(doc, good)[0])
    inv = build_inventory(doc, engine_ask(doc, wrong)[0])
    for x in (inv_good, inv):
        assert_invariants(doc, x)
    assert good.calls == wrong.calls == 1  # ошибочный номер не тратит повтор
    assert _registry(inv) == _registry(inv_good)  # ошибка разметки модели не меняет реестр
    crit = [r for r in inv["requirements"] if r["kind"] == "acceptance"]
    assert [(r["source_id"], r["origin"]) for r in crit] == [(s, "llm") for s in CRITERIA]
    assert "ДК-3" not in {r["source_id"] for r in inv["requirements"]}
    msgs = {w["block_ids"][0]: w["message"] for w in inv["warnings"] if w["code"] == "source_id_reference"}
    assert set(msgs) == {_block(doc, "АК-1 |"), _block(doc, "АК-4 |")}
    assert "«ДК-2»" in msgs[_block(doc, "АК-1 |")] and "«АК-1»" in msgs[_block(doc, "АК-1 |")]
    assert "«ДК-3»" in msgs[_block(doc, "АК-4 |")] and "«АК-4»" in msgs[_block(doc, "АК-4 |")]
    assert not any(w["code"] in ("item_rejected", "rules_fallback") for w in inv["warnings"])
    # пояснение автора не стало критерием: его исключила модель, реестр это принял
    note = _block(doc, "Примечание |")
    assert [(g["category"], g["block_ids"]) for g in inv["excluded"] if note in g["block_ids"]] == [("preamble", [note])]
    # явная ссылка и ссылка на отсутствующий пункт выводятся из реестра так же, как без модели;
    # связь по тексту зависит от длины опор модели (здесь короткие цитаты правил) и тут не проверяется
    t = trace(inv["requirements"])
    assert t["АК-1"]["targets"] == [("ДК-2", "R-002")] and t["АК-4"]["missing"] == ["ДК-3"]
    # модель видела собственный номер критерия: label строки в payload
    blocks = {b["id"]: b for b in build_payload_blocks(doc)}
    assert [blocks[_block(doc, f"{s} |")]["label"] for s in CRITERIA] == CRITERIA


def build_payload_blocks(doc):
    from bcc_review.analysis.inventory import build_payload

    return [b for p in build_payload(doc) for b in p["input"]["blocks"]]


def test_run_review_next_stage_sees_criterion_numbers(tmp_path):
    """Публичный вход движка: run_review, MockAdapter с записанным ответом, где номера критериев перепутаны."""
    doc = engine.read_document(SRC)
    script = tmp_path / "mock.json"
    data = _answer(doc, ["ДК-2", None, None, "ДК-3"])
    script.write_text(json.dumps({"inventory": data}, ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "report.md"
    engine.run_review(SRC, out, options={"provider": "mock", "mock_script": str(script), "use_cache": False})
    report = json.loads(out.with_suffix(".json").read_text(encoding="utf-8"))
    assert report["run"]["modules"]["build_inventory"] == "team:bcc_review.analysis.inventory:build_inventory"
    # движок (normalize_requirements) оставляет id и source_id — то, что получают №05 и №06
    assert [(r["id"], r["source_id"]) for r in report["requirements"]] == [
        ("R-001", "ДК-1"), ("R-002", "ДК-2"), ("R-003", "КК-1"), ("R-004", "КК-2"),
        ("R-005", "АК-1"), ("R-006", "АК-2"), ("R-007", "АК-3"), ("R-008", "АК-4")]
    note = _block(doc, "Примечание |")
    assert any(note in g["block_ids"] and g["category"] == "preamble" for g in report["excluded"])
    from bcc_review import contracts as C

    C.validate(report)
    assert C.evidence_errors(report) == []


# ---------------------------------------------------------------- 3. передача владельцам №05 и №06

EXAMPLE = FIXTURES / "acceptance_links.inventory.json"
OWN_ID_ONLY = FIXTURES / "acceptance_own_id_only.md"
# ожидаемая связь задана автором примера (цитаты из документа), а не выведена эвристикой
LINKS = [
    ("АК-1", "ДК-2: оплата дебетовой картой на 50 000 ₸", "explicit", ["ДК-2"], []),
    ("АК-2", "Выписка по кредитной карте сформирована", "by_text", ["КК-2"], []),
    ("АК-3", "Третий подряд неверный ввод PIN-кода", "ambiguous", ["ДК-1", "КК-1"], []),
    ("АК-4", "ДК-3: снятие наличных сверх суточного лимита", "missing", [], ["ДК-3"]),
]
WHAT_IS_KNOWN = {
    "explicit": "В цитате критерия есть авторский номер ДК-2; в реестре он один (R-002).",
    "by_text": "Номера нет; «Выписка по кредитной карте» есть только в КК-2 (R-004).",
    "ambiguous": "Номера нет; «три неверных ввода PIN-кода подряд» есть и в ДК-1, и в КК-1. Различают их "
                 "«дебетовая … на 24 часа» и «кредитная … до обращения в банк» — в критерии этого нет. "
                 "Ридер даёт строку и ячейки, реестр — АК-3 и обе цели; выбрать цель они не могут: вопрос автору (№08).",
    "missing": "В цитате критерия есть номер ДК-3; в реестре такого пункта нет — ссылка на отсутствующий пункт.",
}


def _example(doc):
    inv = build_inventory(doc, engine_ask(doc, StaticAdapter(_answer(doc, ["ДК-2", None, None, "ДК-3"])))[0])
    by_sid = {r["source_id"]: r for r in inv["requirements"]}
    links = []
    for crit, quote, how, targets, missing in LINKS:
        c = by_sid[crit]
        links.append({"criterion": crit, "req_id": c["id"], "block_id": c["block_ids"][0], "quote": quote,
                      "outcome": how, "targets": [{"source_id": s, "req_id": by_sid[s]["id"]} for s in targets],
                      "missing": missing, "what_registry_knows": WHAT_IS_KNOWN[how]})
    note = _block(doc, "Примечание |")
    return {
        "about": "Критерий приёмки → правило. Номер критерия (source_id) отдельно от присвоенного ID (R-…) и от "
                 "номеров, на которые он ссылается в тексте. Реестр — путь с моделью, где модель поставила в source_id "
                 "АК-1 и АК-4 номера ДК-2 и ДК-3 (после исправления №04 реестр тот же, что при верном ответе).",
        "source": "tests/p04/fixtures/acceptance_links.md",
        "document_id": doc["id"],
        "requirements": [{k: r[k] for k in ("id", "group", "source_id", "source_ref", "kind", "section", "text",
                                             "block_ids", "evidence")} for r in inv["requirements"]],
        "excluded": inv["excluded"],
        "unprocessed_block_ids": inv["unprocessed_block_ids"],
        "expected_links": links,
        "not_a_criterion": [{"block_id": note, "quote": next(b["text"] for b in doc["blocks"] if b["id"] == note),
                             "expected": "не критерий приёмки: пояснение автора (единицы и часовой пояс)"}],
    }


def test_example_for_p05_p06_is_current(docs):
    doc = _doc(docs, "md")
    current = _example(doc)
    text = {b["id"]: b["text"] for b in doc["blocks"]}
    for ln in current["expected_links"]:
        assert ln["quote"] in text[ln["block_id"]]
    assert json.loads(EXAMPLE.read_text(encoding="utf-8")) == current


def test_own_criterion_id_reaches_next_stage_as_acceptance():
    """Минимальный вход для №05: критерий со своим номером и без ссылки на требование.

    Реестр отдаёт АК-1 как acceptance, ДК-1 — как правило; ссылки на ДК-1 в критерии нет.
    """
    doc = engine.read_document(OWN_ID_ONLY)
    inv = build_inventory(doc)
    assert_invariants(doc, inv)
    assert [(r["id"], r["source_id"], r["kind"], r["block_ids"]) for r in inv["requirements"]] == [
        ("R-001", "ДК-1", "functional", [_block(doc, "ДК-1.")]),
        ("R-002", "АК-1", "acceptance", [_block(doc, "АК-1 |")])]
    assert trace(inv["requirements"])["АК-1"]["refs"] == []


# ---------------------------------------------------------------- 4. граница признака «ссылка»


def test_prose_reference_inside_sentence_is_not_item_number():
    doc = md_document("# Т\n\n## Критерии приемки\n\nАК-1. Проверка ДК-2: оплата на 50 000 ₸ — SMS отправлено.\n", "prose.md")
    b = _block(doc, "АК-1.")
    ask = ScriptedModel([{"items": [{"source_id": "ДК-2", "kind": "acceptance", "text": "Оплата — SMS",
                             "evidence": [{"block_id": b, "quote": "оплата на 50 000 ₸ — SMS отправлено"}]}],
                  "excluded": [], "facts": [], "done": True}])
    inv = build_inventory(doc, ask, retry=False)
    assert_invariants(doc, inv)
    assert [(r["source_id"], r["origin"]) for r in inv["requirements"]] == [("АК-1", "llm")]
    assert any(w["code"] == "source_id_reference" for w in inv["warnings"])


def test_prose_merged_item_keeps_its_own_number():
    """Два пункта в одной строке (так бывает после ридера): «У-2.» в начале предложения — свой номер, не ссылка."""
    doc = md_document("# Т\n\n## Условия\n\nУ-1. Снятие без комиссии. У-2. За рубежом комиссия 1 %.\n", "prose.md")
    b = _block(doc, "У-1.")
    ask = ScriptedModel([{"items": [
        {"source_id": "У-1", "kind": "functional", "text": "Без комиссии", "evidence": [{"block_id": b, "quote": "Снятие без комиссии."}]},
        {"source_id": "У-2", "kind": "functional", "text": "За рубежом 1 %", "evidence": [{"block_id": b, "quote": "За рубежом комиссия 1 %."}]},
    ], "excluded": [], "facts": [], "done": True}])
    inv = build_inventory(doc, ask, retry=False)
    assert_invariants(doc, inv)
    assert [(r["source_id"], r["group"]) for r in inv["requirements"]] == [("У-1", "R-001"), ("У-2", "R-002")]
    assert not any(w["code"] in ("source_id_reference", "source_id_cleared") for w in inv["warnings"])
