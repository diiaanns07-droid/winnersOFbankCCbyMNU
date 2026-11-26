"""№03: сверка цитат — эталон К1–К5/С1–С20 на своих строках, повтор фразы, склейка, нечёткий поиск, пакет."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from bcc_review.v2 import docview as dv
from bcc_review.v2 import quotes as Q

ROOT = Path(__file__).resolve().parents[2]
OFFICIAL_MD = ROOT / "release/input/requirements.md"
OFFICIAL_PDF = ROOT / "release/input/requirements.pdf"
REF = json.loads((ROOT / "tests/v2/fixtures/03_reference_quotes.json").read_text(encoding="utf-8"))["quotes"]


def _has(mod: str) -> bool:
    try:
        __import__(mod)
        return True
    except Exception:  # noqa: BLE001
        return False


@pytest.fixture(scope="module")
def md():
    return dv.load(OFFICIAL_MD)


@pytest.fixture(scope="module")
def pdf():
    if not (_has("pymupdf") or _has("fitz")):
        pytest.skip("нет pymupdf")
    return dv.load(OFFICIAL_PDF)


def test_reference_quotes_on_their_lines_md(md):
    wrong = []
    for r in REF:
        m = Q.verify_quote(md, r["quote"], r["line"])
        if not m or not (m["line_start"] <= r["line"] <= m["line_end"]):
            wrong.append((r["ref"], r["line"], r["quote"], m))
    assert not wrong, wrong
    assert len(REF) >= 80
    assert {r["ref"] for r in REF} >= {"К1", "К2", "К3", "К4", "К5"} | {f"С{i}" for i in range(1, 21)}


def test_reference_quotes_without_hint_md(md):
    """Без подсказки находится первое вхождение; для уникальных фраз это и есть верная строка."""
    for r in REF:
        m = Q.verify_quote(md, r["quote"])
        assert m, r
        if r["quote"] in ("Порог в тенге", "Признак включения"):
            continue  # фраза повторяется — без подсказки берётся первое вхождение
        assert m["line_start"] == r["line"], (r, m)


def test_reference_quotes_pdf_same_sections(md, pdf):
    for r in REF:
        mm = Q.verify_quote(md, r["quote"], r["line"])
        loc = Q.verify_quote(pdf, dv.line(md, r["line"])["text"])   # где эта строка MD в PDF
        pm = Q.verify_quote(pdf, r["quote"], loc and loc["line_start"])
        assert pm, r
        assert isinstance(pm["page"], int) and 1 <= pm["page"] <= 6
        a, b = mm["section"].split(" › "), pm["section"].split(" › ")
        # читатель PDF видит «404» заголовком — допускаем лишний уровень глубже
        assert pm["section"] == mm["section"] or a[:2] == b[:2], (r, mm["section"], pm["section"])
    # разумные страницы: Ф-2 на 2-й, Description API на 4-й, пример ERROR на 6-й
    assert Q.verify_quote(pdf, "Месяц определяется по дате совершения покупки")["page"] == 2
    assert Q.verify_quote(pdf, "Сохранение порога. Функциональные требования")["page"] == 4
    assert Q.verify_quote(pdf, '{"result":"ERROR","message":"Проверьте сумму"}')["page"] == 6


def test_repeated_phrase_goes_to_nearest_hint(md):
    # «Уведомление о расходах по карте — REST API» — в интеграции части A (52) и в части B (97)
    q = "Уведомление о расходах по карте — REST API"
    assert Q.verify_quote(md, q, 51)["line_start"] == 52
    assert Q.verify_quote(md, q, 99)["line_start"] == 97
    # «Порог в тенге» — в требованиях к данным (49), в запросе (143) и в ответе (156)
    assert Q.verify_quote(md, "Порог в тенге", 47)["line_start"] == 49
    assert Q.verify_quote(md, "Порог в тенге", 140)["line_start"] == 143
    assert Q.verify_quote(md, "Порог в тенге", 160)["line_start"] == 156
    # подсказка не задана — выручают строки требования (near_lines)
    assert Q.verify_quote(md, "Признак включения", None, [(155, 158)])["line_start"] == 157


def test_repeated_phrase_goals_vs_api_table():
    text = "\n".join([
        "# Сервис",
        "",
        "## Цели",
        "Клиент видит остаток лимита в приложении.",
        "",
        "## Функциональные требования",
        "* **Р-1.** Лимит задаётся в тенге.",
        "",
        "## API",
        "",
        "| Поле | Описание |",
        "| :--- | :--- |",
        "| `limit` | Клиент видит остаток лимита в приложении. |",
    ])
    v = dv.from_text(text)
    q = "Клиент видит остаток лимита в приложении"
    assert Q.verify_quote(v, q, 13)["line_start"] == 13
    assert Q.verify_quote(v, q, 12)["line_start"] == 13
    assert Q.verify_quote(v, q, 4)["line_start"] == 4
    assert Q.verify_quote(v, q, 7)["line_start"] == 4
    assert Q.verify_quote(v, q, None, [(13, 13)])["line_start"] == 13
    assert Q.verify_quote(v, q, 13)["section"] == "API"
    assert Q.verify_quote(v, q, 4)["section"] == "Цели"


def test_normalization_levels(md):
    m = Q.verify_quote(md, "Месяц определяется по дате совершения покупки", 38)
    assert m["verified"] == "exact" and m["text"] == "Месяц определяется по дате совершения покупки"
    m = Q.verify_quote(md, "**Ф-2.** Месяц определяется по дате совершения покупки", 38)
    assert m["verified"] == "normalized" and m["text"].startswith("Ф-2. Месяц")
    m = Q.verify_quote(md, "«месяц определяется по дате совершения покупки в алматы»")
    assert m["line_start"] == 38 and m["text"] == "Месяц определяется по дате совершения покупки в Алматы"
    m = Q.verify_quote(md, "Покупка 31 января в 23:58 на 4000 ₸", 64)          # без пробела в числе
    assert m["line_start"] == 64 and m["text"] == "Покупка 31 января в 23:58 на 4 000 ₸"
    m = Q.verify_quote(md, "учет расходов")                                    # ё → е
    assert m["line_start"] == 26 and m["text"] == "учёт расходов"
    m = Q.verify_quote(md, "Уведомление о расходах по карте - REST API", 52)   # дефис вместо тире
    assert m["line_start"] == 52 and m["verified"] == "normalized"
    m = Q.verify_quote(md, "Prod: —", None)                                    # не «Product» в строке 17
    assert m["line_start"] == 108
    assert Q.verify_quote(md, "200. Ответ в случае успешного выполнения метода.", 162)["text"].startswith("200.")


def test_glue_across_lines(md):
    q = "Ответ в случае успешного выполнения метода. **400.** Ответ в случае, если параметры"
    m = Q.verify_quote(md, q, 162)
    assert (m["line_start"], m["line_end"]) == (162, 163)
    assert m["text"].startswith("Ответ в случае успешного") and m["text"].endswith("если параметры")


def test_ellipsis_inside_quote(md):
    m = Q.verify_quote(md, "Месяц определяется … в Алматы", 38)
    assert m["line_start"] == 38 and m["verified"] == "normalized"
    assert m["text"] == "Месяц определяется … в Алматы"


def test_fuzzy_only_near_hint(md):
    q = "Месяц определяется по дате совершении покупки в Алмате"   # две опечатки
    m = Q.verify_quote(md, q, 37)
    assert m and m["line_start"] == 38 and m["verified"] == "fuzzy"
    assert Q.verify_quote(md, q, 120) is None    # далеко от подсказки — не ищем
    assert Q.verify_quote(md, q) is None         # без подсказки — не ищем


def test_not_found_and_garbage(md):
    assert Q.verify_quote(md, "Кэшбэк начисляется ежедневно", 10) is None
    assert Q.verify_quote(md, "", 10) is None
    assert Q.verify_quote(md, None, 10) is None
    assert Q.verify_quote(md, "ab", 10) is None
    assert Q.verify_quote(md, "Месяц", "L038")["line_start"] == 38   # подсказка строкой «L038»


def test_verify_candidates_batch(md):
    cands = [
        {"id": "C-001", "title": "Конфликт месяца", "requirement_ids": ["R-04", "R-12"],
         "evidence": [{"quote": "Месяц определяется по дате совершения покупки", "line": 30},
                      {"quote": "Февральский счётчик вырос на 4 000", "line": 64},
                      {"quote": "Выдуманная цитата, которой нет", "line": 64}]},
        {"id": "C-002", "title": "Галлюцинация", "requirement_ids": [],
         "evidence": [{"quote": "Кэшбэк начисляется ежедневно", "line": 12}]},
        {"id": "C-003", "title": "Повтор", "requirement_ids": ["R-30"],
         "evidence": [{"quote": "Порог в тенге", "line": 0}, {"quote": "Порог в тенге", "line": 0}]},
    ]
    reqs = [{"id": "R-04", "line_start": 38, "line_end": 38}, {"id": "R-12", "line_start": 64, "line_end": 64},
            {"id": "R-30", "line_start": 156, "line_end": 156}]
    res = Q.verify_candidates(md, copy.deepcopy(cands), reqs)
    kept = {c["id"]: c for c in res["candidates"]}
    assert set(kept) == {"C-001", "C-003"}
    c1 = kept["C-001"]
    assert [e["line_start"] for e in c1["evidence"]] == [38, 64]
    assert all(e["verified"] == "exact" for e in c1["evidence"])
    assert c1["line_start"] == 38 and c1["section"].endswith("Функциональные требования")
    assert [e["line_start"] for e in kept["C-003"]["evidence"]] == [156]      # дубль убран, строка по требованию
    assert res["rejected"][0]["id"] == "C-002" and res["rejected"][0]["reason"] == Q.REASON_MISSING
    assert res["rejected"][0]["evidence"][0]["verified"] == "missing"
    st = res["stats"]
    assert st["quotes"] == 6 and st["missing"] == 2 and st["candidates_kept"] == 2 and st["candidates_rejected"] == 1


def test_verify_requirements(md):
    reqs = [{"id": "R-01", "quote": "Месяц определяется по дате совершения покупки", "line_start": 36, "line_end": 36},
            {"id": "R-02", "quote": "нет такого текста в документе", "line_start": 5, "line_end": 5}]
    res = Q.verify_requirements(md, reqs)
    assert res["missing"] == ["R-02"]
    assert reqs[0]["line_start"] == 38 and reqs[0]["page"] is None and reqs[0]["section"]


def test_official_segment_fixture_quotes_resolve(md):
    """Цитаты нарезки v0 (№04) находятся в документе; номера строк — в пределах требования."""
    seg = json.loads((ROOT / "tests/v2/fixtures/official/segment.json").read_text(encoding="utf-8"))
    reqs = seg["requirements"]
    found = 0
    for r in reqs:
        m = Q.verify_quote(md, r["quote"], r["line_start"])
        if m:
            found += 1
            assert r["line_start"] - 2 <= m["line_start"] <= r["line_end"] + 2, (r["id"], m)
    assert found == len(reqs)
