"""resolve_hint: точная позиция цитаты, причины missing/ambiguous, регрессии ложного совпадения."""

from __future__ import annotations

import random

import pytest
from p07_helpers import NB, make_doc

from bcc_review.analysis.evidence import (
    DocumentIndex,
    EvidenceAudit,
    RepairBudget,
    normalize,
    resolve_hint,
)


def assert_literal(doc: dict, res: dict) -> None:
    """Главный инвариант контракта: block.text[start:end] == quote."""
    assert res["status"] == "matched", res
    ev = res["evidence"]
    block = next(b for b in doc["blocks"] if b["id"] == ev["block_id"])
    assert block["text"][ev["start"]:ev["end"]] == ev["quote"]
    assert 0 <= ev["start"] < ev["end"] <= len(block["text"])


# --- Готовность 1: повтор в блоке и в соседнем блоке -------------------------------

REPEAT = make_doc(
    "Клиент получает push. Сумма в push не более 10 ₸. Клиент получает push.",
    "Клиент получает push при достижении порога.",
)


def test_repeat_in_block_is_ambiguous_without_context() -> None:
    res = resolve_hint(REPEAT, {"block_id": "b1", "quote": "Клиент получает push"})
    assert res["status"] == "ambiguous"
    assert res["reason"] == "multiple_occurrences"
    assert res["evidence"] is None
    assert [(o["start"], o["end"]) for o in res["occurrences"]] == [(0, 20), (50, 70)]


def test_repeat_across_blocks_is_ambiguous_without_block() -> None:
    res = resolve_hint(REPEAT, {"block_id": None, "quote": "Клиент получает push"})
    assert res["status"] == "ambiguous"
    assert {o["block_id"] for o in res["occurrences"]} == {"b1", "b2"}
    assert len(res["occurrences"]) == 3


@pytest.mark.parametrize(
    ("hint", "expected"),
    [
        ({"block_id": "b1", "after": ". Сумма в push"}, ("b1", 0, 20)),
        ({"block_id": "b1", "before": "не более 10 ₸."}, ("b1", 50, 70)),
        ({"block_id": "b1", "context": "не более 10 ₸. Клиент получает push."}, ("b1", 50, 70)),
        ({"block_id": None, "after": "при достижении порога"}, ("b2", 0, 20)),
        ({"block_id": "b2"}, ("b2", 0, 20)),
    ],
)
def test_context_picks_the_right_occurrence(hint: dict, expected: tuple) -> None:
    res = resolve_hint(REPEAT, {"quote": "Клиент получает push", **hint})
    assert_literal(REPEAT, res)
    ev = res["evidence"]
    assert (ev["block_id"], ev["start"], ev["end"]) == expected


def test_equal_context_stays_ambiguous() -> None:
    doc = make_doc("Лимит: да. Лимит: да.")
    res = resolve_hint(doc, {"block_id": "b1", "quote": "да", "before": "Лимит:"})
    assert res["status"] == "ambiguous"
    assert res["reason"] == "context_not_unique"


def test_wrong_context_is_not_guessed() -> None:
    res = resolve_hint(REPEAT, {"block_id": "b1", "quote": "Клиент получает push", "before": "Иначе"})
    assert res["status"] == "ambiguous"
    assert res["reason"] == "context_mismatch"


def test_context_word_boundary() -> None:
    # «ее» не должно совпасть с хвостом слова «более»
    doc = make_doc("более 10 ₸ и ее 10 ₸")
    res = resolve_hint(doc, {"block_id": "b1", "quote": "10 ₸", "before": "ее"})
    assert_literal(doc, res)
    assert res["evidence"]["start"] == 16


# --- Готовность 2: сумма, отрицание, валюта, знак сравнения --------------------------

AMOUNTS = make_doc(
    f"Комиссия за SMS составляет не более 10{NB}₸.",
    "Комиссия составляет более 100 ₸ за операцию.",
    "Лимит SMS — не более 100 ₸ в сутки.",
)


@pytest.mark.parametrize(
    ("block_id", "quote", "reason"),
    [
        ("b1", "не более 1000 ₸", "number_mismatch"),        # не та сумма
        ("b2", "более 1000 ₸", "number_mismatch"),
        ("b1", "более 100 ₸", "found_in_other_block"),       # «более 100 ₸» есть только в b2
        ("b1", "не более 100 ₸", "found_in_other_block"),    # есть только в b3
        ("b2", "не более 100 ₸", "found_in_other_block"),    # отрицание добавлено моделью
        ("b2", "не более 10 ₸", "found_in_other_block"),
        ("b1", "более 10 ₸", "negation_outside_quote"),      # литерал есть, но отрицание отрезано
        ("b3", "более 100 ₸", "negation_outside_quote"),
        ("b3", "не более 10", "number_boundary"),            # литерал есть, но режет 100 → 10
        ("b1", "не более 10 $", "currency_mismatch"),        # другая валюта
        ("b1", "не более 10 тенге", "currency_mismatch"),
        ("b2", "менее 100 ₸", "comparison_mismatch"),        # другой знак сравнения
    ],
)
def test_amount_negation_currency_are_not_confirmed(block_id: str, quote: str, reason: str) -> None:
    res = resolve_hint(AMOUNTS, {"block_id": block_id, "quote": quote})
    assert res["status"] == "missing", res
    assert res["evidence"] is None
    assert res["reason"] == reason
    # кандидат — только подсказка места, а не опора
    for cand in res["candidates"]:
        assert set(cand) >= {"block_id", "start", "end", "text", "score", "differences"}


@pytest.mark.parametrize(
    ("block_id", "quote"),
    [("b1", "не более 10 ₸"), ("b2", "более 100 ₸"), ("b3", "не более 100 ₸")],
)
def test_exact_amounts_are_confirmed(block_id: str, quote: str) -> None:
    res = resolve_hint(AMOUNTS, {"block_id": block_id, "quote": quote})
    assert_literal(AMOUNTS, res)
    assert res["evidence"]["block_id"] == block_id


def test_wrong_digit_is_not_replaced_by_similar_paragraph() -> None:
    res = resolve_hint(AMOUNTS, {"block_id": "b1", "quote": "Комиссия за SMS составляет не более 100 ₸."})
    assert res["status"] == "missing"
    assert res["evidence"] is None
    assert res["reason"] == "number_mismatch"
    best = res["candidates"][0]
    assert best["block_id"] == "b1"
    assert "10" in best["text"] and "100" not in best["text"]


@pytest.mark.parametrize(
    ("text", "quote", "reason"),
    [
        ("Операция невозможна при блокировке.", "возможна при блокировке", "partial_word"),
        ("Порога не существует.", "Порог", "partial_word"),
        ("Сумма 10,5 ₸.", "10", "number_boundary"),
        ("Сумма 1 000 000 ₸.", "000 000 ₸", "number_boundary"),
        ("Температура -5 градусов.", "5 градусов", "sign_outside_quote"),
        ("Отправлять без подтверждения клиента.", "подтверждения клиента", "negation_outside_quote"),
        ("Учитываются все операции, кроме переводов.", "переводов", "negation_outside_quote"),
    ],
)
def test_boundary_guard_rejects_literal_substrings(text: str, quote: str, reason: str) -> None:
    doc = make_doc(text)
    assert quote in text or normalize(quote).text in normalize(text).text
    res = resolve_hint(doc, {"block_id": "b1", "quote": quote})
    assert res["status"] == "missing"
    assert res["reason"] == reason


def test_comparison_and_unit_outside_quote_are_warnings() -> None:
    doc = make_doc("Порог не более 100 ₸.")
    res = resolve_hint(doc, {"block_id": "b1", "quote": "100"})
    assert_literal(doc, res)
    assert {"comparison_outside_quote", "unit_outside_quote"} <= set(res["warnings"])


# --- Готовность 3: NBSP, кириллица, символ вне BMP, переносы --------------------------


def test_nbsp_cyrillic_astral_codepoints() -> None:
    text = f"Знак 𝟙 обозначает лимит 50{NB}000{NB}₸ для клиента."
    doc = make_doc(text)
    res = resolve_hint(doc, {"block_id": "b1", "quote": "𝟙 обозначает лимит 50 000 ₸"})
    assert_literal(doc, res)
    ev = res["evidence"]
    assert ev["quote"] == f"𝟙 обозначает лимит 50{NB}000{NB}₸"  # буквально, с NBSP
    assert (ev["start"], ev["end"]) == (5, 32)  # кодовые точки: 𝟙 — одна позиция
    assert len(text[:ev["end"]].encode("utf-16-le")) // 2 == ev["end"] + 1  # в UTF-16 было бы 33
    assert "normalized_match" in res["warnings"]


@pytest.mark.parametrize(
    ("text", "quote", "literal"),
    [
        ("Система выполняет про-\nверку порога.", "проверку порога", "про-\nверку порога"),
        ("Система выполняет про­\nверку порога.", "проверку порога", "про­\nверку порога"),
        ("Система выполняет про­верку порога.", "проверку порога", "про­верку порога"),
        ("Это что-\nто важное.", "что-то важное", "что-\nто важное"),
        ("Это что‑то важное.", "что-то важное", "что‑то важное"),
        ("Поле\t«Порог, ₸»\n видно.", "Поле «Порог, ₸» видно", "Поле\t«Порог, ₸»\n видно"),
        ("Ключ​евой лимит.", "Ключевой лимит", "Ключ​евой лимит"),
        ("Йод и ёж.", "Йод и ёж", "Йод и ёж"),  # NFD в тексте, NFC в цитате
    ],
)
def test_tolerated_differences_return_literal(text: str, quote: str, literal: str) -> None:
    doc = make_doc(text)
    res = resolve_hint(doc, {"block_id": "b1", "quote": quote})
    assert_literal(doc, res)
    assert res["evidence"]["quote"] == literal


def test_grapheme_is_never_split() -> None:
    doc = make_doc("Нӗ и Не")  # «е» + бреве в начале и обычное «Не» в конце
    res = resolve_hint(doc, {"block_id": "b1", "quote": "Не"})
    assert_literal(doc, res)
    assert res["evidence"]["start"] == 5


def test_cluster_expanding_under_nfc_is_not_split() -> None:
    # U+0958 (исключение из композиции) при NFC → «क» + нукта: часть графемы не находится вовсе
    doc = make_doc("\u0958 и \u0915 отдельно")
    idx = DocumentIndex(doc)
    clean, rejected = idx.find("\u0915", ["b1"])
    assert [o["start"] for o in clean] == [4] and rejected == []
    assert resolve_hint(doc, {"block_id": "b1", "quote": "\u0915"})["evidence"]["start"] == 4


def test_markdown_markup_is_tolerated_only_for_md() -> None:
    text = "* **Ф-1.** Держатель задаёт `порог`."
    md = make_doc(text, fmt="md")
    res = resolve_hint(md, {"block_id": "b1", "quote": "Ф-1. Держатель задаёт порог"})
    assert_literal(md, res)
    assert res["evidence"]["quote"] == "Ф-1.** Держатель задаёт `порог"
    txt = make_doc(text, fmt="txt")
    assert resolve_hint(txt, {"block_id": "b1", "quote": "Ф-1. Держатель задаёт порог"})["status"] == "missing"


def test_case_and_dashes_are_not_folded() -> None:
    doc = make_doc("Сумма 10–20 ₸.")
    assert resolve_hint(doc, {"block_id": "b1", "quote": "сумма 10–20 ₸"})["status"] == "missing"
    assert resolve_hint(doc, {"block_id": "b1", "quote": "Сумма 10-20 ₸"})["status"] == "missing"


# --- Блок, кавычки, бюджет, учёт --------------------------------------------------


def test_unknown_block_relocates_only_unique_quote() -> None:
    res = resolve_hint(REPEAT, {"block_id": "zzz", "quote": "при достижении порога"})
    assert_literal(REPEAT, res)
    assert "unknown_block_id" in res["warnings"]
    res = resolve_hint(REPEAT, {"block_id": "zzz", "quote": "Клиент получает push"})
    assert res["status"] == "ambiguous"


def test_relocation_is_explicit_opt_in() -> None:
    res = resolve_hint(AMOUNTS, {"block_id": "b2", "quote": "не более 100 ₸"})
    assert res["status"] == "missing" and res["reason"] == "found_in_other_block"
    assert [(c["block_id"], c["text"]) for c in res["candidates"]] == [("b3", "не более 100 ₸")]
    moved = resolve_hint(AMOUNTS, {"block_id": "b2", "quote": "не более 100 ₸"}, relocate=True)
    assert_literal(AMOUNTS, moved)
    assert moved["evidence"]["block_id"] == "b3"
    assert "block_relocated" in moved["warnings"]


def test_outer_quotes_are_stripped() -> None:
    res = resolve_hint(AMOUNTS, {"block_id": "b2", "quote": "«более 100 ₸»"})
    assert_literal(AMOUNTS, res)
    assert "outer_quotes_stripped" in res["warnings"]


def test_empty_quote() -> None:
    assert resolve_hint(AMOUNTS, {"block_id": "b1", "quote": "  "})["reason"] == "empty_quote"


def test_duplicate_block_ids_are_ambiguous() -> None:
    doc = make_doc("Один текст.", "Другой текст.", ids=["x", "x"])
    assert resolve_hint(doc, {"block_id": "x", "quote": "текст"})["reason"] == "duplicate_block_id"


def test_repair_budget_is_shared_and_bounded() -> None:
    budget = RepairBudget(limit=2)
    results = [resolve_hint(AMOUNTS, {"block_id": "b1", "quote": f"не более {n} ₸"}, budget=budget)
               for n in (11, 12, 13)]
    assert [bool(r["candidates"]) for r in results] == [True, True, False]
    assert "repair_budget_exhausted" in results[2]["warnings"]
    assert budget.used == 2 and budget.remaining == 0
    assert all(r["status"] == "missing" and r["evidence"] is None for r in results)


def test_audit_counts_hints() -> None:
    audit = EvidenceAudit()
    resolve_hint(REPEAT, {"block_id": "b2", "quote": "Клиент получает push"}, audit=audit)
    resolve_hint(REPEAT, {"block_id": "b1", "quote": "Клиент получает push"}, audit=audit)
    resolve_hint(AMOUNTS, {"block_id": "b1", "quote": "более 10 ₸"}, audit=audit)
    data = audit.to_dict()
    assert (data["checked"], data["confirmed"], data["ambiguous"], data["rejected"]) == (3, 1, 1, 1)
    assert data["unit"] == "hint" and "Единица учёта" in data["note"]
    assert data["by_reason"] == {"multiple_occurrences": 1, "negation_outside_quote": 1}


def test_objects_with_attributes_are_accepted() -> None:
    class Obj:
        def __init__(self, **kw: object) -> None:
            self.__dict__.update(kw)

    doc = Obj(id="x", format="txt", blocks=[Obj(id="b1", text="Порог 10 ₸.", section=[], loc={})])
    res = resolve_hint(doc, Obj(block_id="b1", quote="Порог 10 ₸"))
    assert res["evidence"] == {"block_id": "b1", "start": 0, "end": 10, "quote": "Порог 10 ₸"}


# --- Свойство: для каждого matched строго block.text[start:end] == quote -------------


def test_random_quotes_keep_literal_invariant(md_doc: dict, bcc_doc: dict) -> None:
    rng = random.Random(20261127)
    checked = 0
    for doc in (md_doc, bcc_doc):
        idx = DocumentIndex(doc)
        for _ in range(400):
            bid = rng.choice(idx.order)
            text = idx.text(bid)
            words = [(m.start(), m.end()) for m in __import__("re").finditer(r"\S+", text)]
            if len(words) < 2:
                continue
            i = rng.randrange(len(words))
            j = min(len(words), i + rng.randint(1, 6))
            quote = text[words[i][0]:words[j - 1][1]]
            # модель «портит» пробелы: NBSP/перевод строки → обычный пробел
            noisy = " ".join(quote.split())
            res = resolve_hint(doc, {"block_id": bid, "quote": noisy}, index=idx)
            if res["status"] == "matched":
                assert_literal(doc, res)
                checked += 1
            else:
                assert res["evidence"] is None
                assert res["reason"]
    assert checked > 300
