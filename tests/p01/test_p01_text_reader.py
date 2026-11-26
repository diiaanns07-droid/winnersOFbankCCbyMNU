"""№01: reader Markdown/TXT → Document. Точная обратная привязка цитат к строкам источника."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest

from bcc_review.readers.text import (
    Block,
    Document,
    block_at_line,
    dumps_document,
    from_source,
    parse_bytes,
    read_text,
    source_lines,
    span_to_source,
    table_records,
    to_source,
    verify_document,
)

FIX = Path(__file__).parent / "fixtures"
# BCC-HUB/ai-requirements-validator-task@928c1aa364265426105b69ba7a3444eac11b22db docs/requirements.md
OFFICIAL = FIX / "official_requirements.md"
OFFICIAL_SHA256 = "e7dae55e5453a250d93e335f5ff9c7f775f4457ccddd333f4a67e47b20d74381"
SPEC = FIX / "spec_ab.md"
NOTES = FIX / "notes.txt"
SAMPLE = FIX / "sample_document.json"


def independent_lines(data: bytes) -> list[str]:
    """Строки так, как их восстанавливает соседний модуль своим кодом, без reader."""
    return re.split(r"\r\n|\r|\n", data.decode("utf-8-sig"))


def restore(block: Block, start: int, end: int, lines: list[str]) -> list[tuple[int, str]]:
    return [(ln, lines[ln - 1][a:b]) for ln, a, b in span_to_source(block, start, end)]


def at(doc: Document, line: int) -> Block:
    """Блок, который начинается на строке ``line``."""
    (b,) = [b for b in doc.blocks if b.loc["line_start"] == line]
    return b


def codes(doc: Document) -> list[str]:
    return [w["code"] for w in doc.warnings]


def from_json(doc_dict: dict, block_id: str) -> Block:
    """Соседний модуль получает Document как JSON и собирает Block обратно."""
    (raw,) = [b for b in doc_dict["blocks"] if b["id"] == block_id]
    return Block(**raw)


# --------------------------------------------------------------------------- официальный документ


def test_official_document_hash_title_and_structure():
    data = OFFICIAL.read_bytes()
    doc = read_text(OFFICIAL)
    assert doc.id == OFFICIAL_SHA256 == hashlib.sha256(data).hexdigest()
    assert (doc.title, doc.format, doc.source_name, doc.warnings) == (
        "Уведомление о расходах по карте", "markdown", "official_requirements.md", [])
    assert verify_document(doc, data) == []
    assert [b.id for b in doc.blocks] == [f"b{k:04d}" for k in range(1, len(doc.blocks) + 1)]

    f1 = at(doc, 37)
    assert f1.kind == "list_item" and "checklist" not in f1.loc
    assert f1.text.startswith("Ф-1. Держатель активной карты KZT")
    assert f1.section == [
        "Уведомление о расходах по карте",
        "Часть A. Новый функционал",
        "Требования к изменениям",
        "Функциональные требования",
    ]
    assert f1.loc["section_ids"] == [at(doc, n).id for n in (1, 8, 31, 36)]
    assert f1.loc["map"] == [[0, 37, 4], [4, 37, 10]]  # «* **» и «**» сняты
    assert [at(doc, n).text[:4] for n in (37, 38, 39, 40)] == ["Ф-1.", "Ф-2.", "Ф-3.", "Ф-4."]
    assert at(doc, 36).section == f1.section[:-1]  # путь заголовка — его родители

    logic = [b for b in doc.blocks if b.section[-1:] == ["Логика работы метода"] and b.kind == "list_item"]
    assert [b.loc["list"]["number"] for b in logic] == [1, 2, 3, 4, 5]
    assert {b.section[1] for b in logic} == {"Часть B. REST API"}

    code = [b for b in doc.blocks if b.kind == "code"]
    assert [(b.loc["line_start"], b.loc["fence"]["info"]) for b in code] == [
        (129, "text"), (166, "json"), (170, "json"), (179, "json"),
        (184, "json"), (191, "json"), (196, "json"),
    ]
    for b in code[1:]:
        json.loads(b.text)  # тело кода дословно, без снятия разметки
    assert at(doc, 170).section[-1] == "200. Successful — Created"

    approvers = at(doc, 91)
    assert approvers.loc["empty"] is True
    assert [c["column"] for c in approvers.loc["cells"]] == ["Подразделение", "ФИО ответственного", "Подпись"]


def test_official_hard_break_paragraph_keeps_both_lines():
    doc = read_text(OFFICIAL)
    b = at(doc, 162)
    assert b.text.split("\n") == [
        "200. Ответ в случае успешного выполнения метода.",
        "400. Ответ в случае, если параметры запроса заполнены неверно.",
    ]
    assert b.loc["lines"] == [[162, 0, 48], [163, 49, 111]]
    # два хвостовых пробела жёсткого переноса заменены синтетическим "\n"
    assert [s for s in b.loc["spans"] if s[5] == "s"] == [[48, 49, 162, 52, 54, "s"]]
    assert block_at_line(doc, 163) is b


def test_block_at_line_resolves_markup_and_continuation_lines():
    doc = read_text(OFFICIAL)
    assert block_at_line(doc, 4) is at(doc, 3)  # вторая строка абзаца
    assert block_at_line(doc, 13) is at(doc, 12)  # строка-разделитель таблицы
    assert block_at_line(doc, 130) is at(doc, 129)  # содержимое кода
    assert block_at_line(doc, 131) is at(doc, 129)  # закрывающее ограждение
    assert block_at_line(doc, 5) is None  # пустая строка


# --------------------------------------------------------------------------- доказательство 1


def test_quote_from_middle_of_second_table_row_restores_its_line_and_exact_text():
    data = OFFICIAL.read_bytes()
    doc = read_text(OFFICIAL)
    header = next(b for b in doc.blocks if b.kind == "table_header" and b.section[-1] == "Критерии приемки")
    row2 = next(b for b in doc.blocks
                if b.kind == "table_row" and b.loc["table"]["header_id"] == header.id and b.loc["row"] == 2)

    quote = "23:58 на 4 000 ₸ | Провести 1 февраля в 00:03"
    start = row2.text.index(quote)
    end = start + len(quote)
    assert 0 < start and end < len(row2.text) and row2.text.count(quote) == 1  # середина, не края
    evidence = {"block_id": row2.id, "start": start, "end": end, "quote": quote}

    # соседний модуль: JSON документа + исходные байты, свой разбор строк
    block = from_json(json.loads(json.dumps(doc.to_dict(), ensure_ascii=False)), evidence["block_id"])
    assert block.text[evidence["start"]:evidence["end"]] == evidence["quote"]
    assert restore(block, evidence["start"], evidence["end"], independent_lines(data)) == [(64, quote)]
    cols = [c["column"] for c in block.loc["cells"] if c["start"] < end and c["end"] > start]
    assert cols == ["Исходные условия", "Действие"]

    # то же только по контрактному loc.map (без spans), как сделает модуль другого автора
    bare = Block(block.id, block.kind, block.section, block.text,
                 {k: v for k, v in block.loc.items() if k != "spans"})
    assert restore(bare, start, end, independent_lines(data)) == [(64, quote)]


def test_quote_inside_second_api_row_and_in_padded_table():
    doc = read_text(OFFICIAL)
    lines = independent_lines(OFFICIAL.read_bytes())
    amount = at(doc, 143)
    assert amount.loc["row"] == 2
    quote = "integer | 32 bit | Да"
    s = amount.text.index(quote)
    assert restore(amount, s, s + len(quote), lines) == [(143, quote)]

    # таблица без канонических отступов: цитата внутри ячейки точна,
    # цитата через границу ячеек показывает реальный исходник со своими пробелами
    spec = read_text(SPEC)
    spec_lines = independent_lines(SPEC.read_bytes())
    padded = at(spec, 35)
    assert padded.text == "Бронь на  4 часа | Продлить на 1 час | Отказ: больше 4 часов"
    q = "на  4 часа"
    s = padded.text.index(q)
    assert restore(padded, s, s + len(q), spec_lines) == [(35, q)]
    q = "4 часа | Продлить"
    s = padded.text.index(q)
    assert restore(padded, s, s + len(q), spec_lines) == [(35, "4 часа  |Продлить")]


# --------------------------------------------------------------------------- доказательство 2


def test_repeated_heading_and_sentence_in_parts_a_and_b_have_distinct_ids_and_paths():
    doc = read_text(SPEC)
    lines = independent_lines(SPEC.read_bytes())
    title = "Бронирование переговорных"
    part_a, part_b = at(doc, 8), at(doc, 44)
    heads = [b for b in doc.blocks if b.kind == "heading" and b.text == "Общие сведения"]
    sentence = "Время указывается по UTC+5."
    same = [b for b in doc.blocks if b.text == sentence]

    assert [b.loc["line_start"] for b in heads] == [10, 46]
    assert [b.loc["line_start"] for b in same] == [12, 48]
    assert len({b.id for b in heads + same}) == 4
    assert heads[0].section == [title, "Часть A. Бизнес-требования"]
    assert heads[1].section == [title, "Часть B. REST API"]
    assert same[0].section == [title, "Часть A. Бизнес-требования", "Общие сведения"]
    assert same[1].section == [title, "Часть B. REST API", "Общие сведения"]
    assert same[0].loc["section_ids"] == [doc.blocks[0].id, part_a.id, heads[0].id]
    assert same[1].loc["section_ids"] == [doc.blocks[0].id, part_b.id, heads[1].id]
    for b, line in zip(same, (12, 48), strict=True):
        assert restore(b, 0, len(sentence), lines) == [(line, sentence)]
    # поиск фразы по всему тексту нашёл бы только первое место
    assert "\n".join(lines).count(sentence) == 2


# --------------------------------------------------------------------------- доказательство 3

VARIANTS = {
    "lf": lambda d: d,
    "crlf": lambda d: d.replace(b"\n", b"\r\n"),
    "cr": lambda d: d.replace(b"\n", b"\r"),
    "bom": lambda d: b"\xef\xbb\xbf" + d,
    "bom_crlf": lambda d: b"\xef\xbb\xbf" + d.replace(b"\n", b"\r\n"),
}


def _shape(doc):
    return [(b.id, b.kind, b.section, b.text, b.loc["lines"], b.loc["map"], b.loc["spans"])
            for b in doc.blocks]


@pytest.mark.parametrize("fixture", [SPEC, NOTES, OFFICIAL], ids=lambda p: p.name)
@pytest.mark.parametrize("variant", list(VARIANTS))
def test_bom_and_line_endings_keep_ids_texts_and_coordinates(variant, fixture, tmp_path):
    base = fixture.read_bytes()
    data = VARIANTS[variant](base)
    path = tmp_path / fixture.name
    path.write_bytes(data)
    doc, ref = read_text(path), read_text(fixture)

    assert doc.id == hashlib.sha256(data).hexdigest()
    assert (doc.id == ref.id) is (variant == "lf")
    assert _shape(doc) == _shape(ref)
    assert doc.warnings == ref.warnings
    assert verify_document(doc, data) == []

    eol = "\r\n" if "crlf" in variant else "\r" if variant == "cr" else "\n"
    lines = independent_lines(data)
    for b in doc.blocks:
        chunk = data[b.loc["byte_start"]:b.loc["byte_end"]].decode("utf-8")
        assert chunk == eol.join(lines[b.loc["line_start"] - 1:b.loc["line_end"]])


def test_same_bytes_give_same_ids_and_identical_json(tmp_path):
    first = dumps_document(read_text(SPEC))
    copy = tmp_path / "spec_ab.md"
    copy.write_bytes(SPEC.read_bytes())
    again = dumps_document(parse_bytes(SPEC.read_bytes(), "md", "spec_ab.md"))
    assert first == dumps_document(read_text(copy)) == again


def test_sample_document_json_is_current():
    """Образец для №04/№07/№13. Пересборка: см. tests/p01/README.md."""
    assert SAMPLE.read_text(encoding="utf-8") == dumps_document(read_text(SPEC))
    assert json.loads(SAMPLE.read_text(encoding="utf-8")) == read_text(SPEC).to_dict()


def test_mixed_line_endings_are_reported():
    doc = parse_bytes(b"# T\r\n\r\na\nb\r\n", "md")
    assert doc.blocks[1].text == "a\nb"
    assert doc.warnings == [{"code": "mixed_line_endings", "message": "смешанные окончания строк: LF, CRLF",
                             "stage": "read"}]


# --------------------------------------------------------------------------- fenced-блоки, пустые секции


def test_fenced_json_with_vertical_bars_is_inert():
    doc = read_text(SPEC)
    code = [b for b in doc.blocks if b.kind == "code"]
    assert json.loads(code[0].text)["filter"] == "status|owner"
    assert code[0].loc["fence"] == {"marker": "```", "info": "json", "open_line": 80,
                                    "close_line": 82, "closed": True}
    assert code[1].text == "| это | не таблица |\n# и не заголовок"
    inside = {n for c in code for n in range(c.loc["line_start"], c.loc["line_end"] + 1)}
    assert all(b.loc["line_start"] not in inside for b in doc.blocks if b.kind != "code")


def test_unclosed_fence_runs_to_end_with_warning():
    data = b'# T\n\n```json\n{"a": "x | y"}\n| a | b |\n'
    doc = parse_bytes(data, "md")
    code = doc.blocks[-1]
    assert (code.kind, code.text, code.loc["fence"]["closed"], code.loc["line_end"]) == (
        "code", '{"a": "x | y"}\n| a | b |', False, 5)
    assert doc.warnings == [{"code": "unclosed_fence", "stage": "read", "block_ids": [code.id],
                             "message": "строка 3: блок кода ``` не закрыт; строки 4–5 прочитаны как код"}]


def test_empty_section_is_marked_and_reported():
    doc = read_text(SPEC)
    empty = at(doc, 27)
    assert (empty.text, empty.loc["empty"], empty.loc["section_end"]) == ("Ограничения", True, 28)
    assert doc.warnings == [{"code": "empty_section", "stage": "read", "block_ids": [empty.id],
                             "message": "строка 27: раздел «Ограничения» без содержимого"}]
    assert [b for b in doc.blocks if b.kind == "heading" and b.loc["empty"]] == [empty]
    assert at(doc, 62).loc["empty"] is False  # только подраздел с таблицей

    nested = parse_bytes("# T\n\n## A\n### A1\n## B\nтекст\n".encode(), "md")
    flags = {b.text: b.loc["empty"] for b in nested.blocks if b.kind == "heading"}
    assert flags == {"T": False, "A": True, "A1": True, "B": False}
    assert codes(nested) == ["empty_section", "empty_section"]


# --------------------------------------------------------------------------- TXT


def test_txt_without_numbering_has_paragraph_coordinates():
    doc = read_text(NOTES)
    lines = independent_lines(NOTES.read_bytes())
    assert (doc.format, doc.title, doc.warnings) == ("text", "Заметки к ревью требований", [])
    assert [(b.id, b.kind, b.loc["line_start"], b.loc["line_end"]) for b in doc.blocks] == [
        ("b0001", "paragraph", 1, 1), ("b0002", "paragraph", 3, 4),
        ("b0003", "paragraph", 6, 6), ("b0004", "paragraph", 8, 9),
    ]
    assert all(b.section == [] and b.loc["section_ids"] == [] for b in doc.blocks)
    sentence = "Время указывается по UTC+5."
    hits = [(b, b.text.index(sentence)) for b in doc.blocks if sentence in b.text]
    assert [(b.id, restore(b, s, s + len(sentence), lines)) for b, s in hits] == [
        ("b0003", [(6, sentence)]), ("b0004", [(9, sentence)]),
    ]


def test_txt_bullets_trailing_spaces_and_wrapped_lines():
    data = "Система должна:\n- принимать заявки;   \n- отклонять дубли\n  без потери порядка.\n".encode()
    doc = parse_bytes(data, "txt")
    assert [(b.kind, b.text) for b in doc.blocks] == [
        ("paragraph", "Система должна:"),
        ("list_item", "принимать заявки;"),
        ("list_item", "отклонять дубли\nбез потери порядка."),
    ]
    assert doc.blocks[2].loc["lines"] == [[3, 0, 15], [4, 16, 35]]
    assert verify_document(doc, data) == []


def test_cp1251_txt_is_decoded_with_warning(tmp_path):
    data = "Требование: статус хранится.\n".encode("cp1251")
    path = tmp_path / "legacy.txt"
    path.write_bytes(data)
    doc = read_text(path)
    assert doc.blocks[0].text == "Требование: статус хранится."
    assert doc.blocks[0].loc["byte_end"] == len(data) - 1
    assert doc.warnings == [{"code": "encoding_fallback", "stage": "read",
                             "message": "файл не в UTF-8 (байт 0); прочитан как cp1251"}]


def test_utf8_with_a_few_broken_bytes_stays_utf8_and_is_a_partial_read():
    """HANDOFF: UTF-8 с единичным битым байтом не перечитывается целиком как cp1251."""
    good = NOTES.read_bytes()
    k = good.index("сотрудник".encode())
    doc = parse_bytes(good[:k] + b"\xff" + good[k:], "txt", "notes.txt")
    assert codes(doc) == ["decode_error"]
    assert doc.blocks[1].text.startswith("Сервис хранит заявки \ufffdсотрудников")
    assert [b.loc["line_start"] for b in doc.blocks] == [1, 3, 6, 8]  # номера строк не сдвинулись
    assert doc.blocks[1].loc["byte_start"] is None


def test_undecodable_bytes_are_a_partial_read():
    doc = parse_bytes(b"\xef\xbb\xbf\xd0\x9f\xff\xfe text\n", "txt")
    assert codes(doc) == ["decode_error"]
    assert doc.blocks[0].loc["byte_start"] is None


# --------------------------------------------------------------------------- чек-лист, таблицы, факты


def test_checklist_items_are_distinguished_from_requirements():
    doc = read_text(SPEC)
    items = [b for b in doc.blocks if b.kind == "list_item"]
    reqs = [b for b in items if b.text.startswith("R-")]
    assert [b.loc["line_start"] for b in reqs] == [21, 23, 25]
    assert all("checklist" not in b.loc for b in reqs)
    assert reqs[0].text == "R-1. Сотрудник бронирует комнату на 1–20 мест\nне дольше чем на 4 часа."
    nested = at(doc, 24)
    assert (nested.loc["list"]["depth"], nested.loc["list"]["ordered"]) == (1, True)
    checks = [(b.text, b.loc["checked"]) for b in items if b.loc.get("checklist")]
    assert checks == [("Сценарии согласованы с владельцем.", True), ("Тексты ошибок утверждены.", False)]

    official = read_text(OFFICIAL)
    rows = [b for b in official.blocks if b.kind == "table_row"]
    review = [b for b in rows if b.section[-1] == "Ревью требований"]
    assert len(review) == 14 and all(b.loc["template_choices"] == [1, 2] for b in review)
    assert all("template_choices" not in b.loc for b in rows if b.section[-1] == "Критерии приемки")


def test_acceptance_rows_keep_given_when_then_and_own_ids():
    doc = read_text(OFFICIAL)
    recs = [r for r in table_records(doc) if r["section"][-1] == "Критерии приемки"]
    assert [(r["block_id"], r["row"], r["header_id"], r["line"]) for r in recs] == [
        (at(doc, n).id, k, at(doc, 61).id, n) for k, n in ((1, 63), (2, 64), (3, 65))]
    for r in recs:
        assert [c["column"] for c in r["cells"]] == ["Исходные условия", "Действие", "Ожидаемый результат"]
    given, when, then = recs[1]["cells"]
    assert (given["value"], when["value"], then["value"]) == (
        "Покупка 31 января в 23:58 на 4 000 ₸",
        "Провести 1 февраля в 00:03 по Алматы",
        "Февральский счётчик вырос на 4 000 ₸",
    )
    assert [n["value"] for n in recs[0]["cells"][0]["numbers"]] == [48500, 50000]


def test_number_from_neighbouring_row_does_not_join_the_fact():
    doc = read_text(SPEC)
    lines = independent_lines(SPEC.read_bytes())
    recs = {r["line"]: r for r in table_records(doc)}
    row1, row2 = recs[33], recs[34]
    assert row1["cells"][-1]["value"] == "Свободно 8, остаток 1 000"
    assert row2["cells"][0]["value"] == "500 минут в журнале за день"

    # ловушка: наивная склейка ячеек и «пробел как разделитель тысяч» даёт 1 000 500
    naive = "\n".join(c["value"] for r in (row1, row2) for c in r["cells"])
    assert 1000500 in [int(re.sub(r"\s", "", m)) for m in re.findall(r"\d{1,3}(?:\s\d{3})+|\d+", naive)]

    assert [n["value"] for n in row1["cells"][-1]["numbers"]] == [8, 1000]
    assert [n["value"] for n in row2["cells"][0]["numbers"]] == [500]
    row1_numbers = {n["value"] for c in row1["cells"] for n in c["numbers"]}
    assert row1_numbers == {20, 0, 12, 8, 1000}
    block = at(doc, 33)
    for n in row1["cells"][-1]["numbers"]:
        line, col = to_source(block, n["start"])
        assert line == 33 and lines[32][col:col + len(n["text"])] == n["text"]


def test_api_table_rows_keep_column_direction_type_value_and_place():
    doc = read_text(OFFICIAL)
    lines = independent_lines(OFFICIAL.read_bytes())
    recs = table_records(doc)
    req = {r["key"]: r for r in recs if r["direction"] == "request"}
    resp = {r["key"]: r for r in recs if r["direction"] == "response"}
    assert list(req) == ["cardId", "amount", "enabled"]
    assert list(resp) == ["result", "amount", "enabled", "message"]
    plain = ("Общие параметры", "Критерии приемки")
    assert {r["direction"] for r in recs if r["section"][-1] in plain} == {None}

    for rec, line, fmt in ((req["amount"], 143, "integer"), (resp["amount"], 156, "string")):
        cells = {c["column"]: c for c in rec["cells"]}
        f = cells["Format"]
        assert (rec["line"], f["line"], f["value"]) == (line, line, fmt)
        assert lines[line - 1][f["col_start"]:f["col_end"]] == fmt
        assert cells["Parameter"]["value"] == "amount"
        assert cells["DB field"]["value"] == "limit_kzt"
    logic = {c["column"]: c for c in req["amount"]["cells"]}["Logic"]
    assert [n["value"] for n in logic["numbers"]] == [1000, 1000000]


def test_escaped_pipe_and_link_inside_cells():
    doc = read_text(SPEC)
    row = at(doc, 54)
    assert row.text == "Фильтр | status | owner"
    assert [row.text[c["start"]:c["end"]] for c in row.loc["cells"]] == ["Фильтр", "status | owner"]
    task = at(doc, 17)
    assert task.text == "Задача | ROOM-7"
    assert task.loc["links"] == [{"start": 9, "end": 15, "url": "https://tracker.example.test/ROOM-7"}]


def test_short_and_long_table_rows_are_kept_with_warnings():
    data = b"| a | b |\n| - | - |\n| 1 |\n| 1 | 2 | 3 |\n"
    doc = parse_bytes(data, "md")
    short, long_ = doc.blocks[1], doc.blocks[2]
    assert [c["column"] for c in short.loc["cells"]] == ["a", "b"]
    assert short.text == "1 | "
    assert [c["column"] for c in long_.loc["cells"]] == ["a", "b", None]
    assert long_.text == "1 | 2 | 3"
    assert [(w["code"], w["block_ids"]) for w in doc.warnings] == [
        ("table_cells_mismatch", [short.id]), ("table_cells_mismatch", [long_.id])]
    assert verify_document(doc, data) == []


# ------------------------------------------------------------------ обратимость и ложные срабатывания


@pytest.mark.parametrize("path", [OFFICIAL, SPEC, NOTES], ids=lambda p: p.name)
def test_every_visible_character_maps_back_to_its_source_character(path):
    data = path.read_bytes()
    doc = read_text(path)
    lines = independent_lines(data)
    assert source_lines(data) == lines[:len(source_lines(data))]
    for b in doc.blocks:
        assert b.loc["map"] == [[t0, line, c0] for t0, _t1, line, c0, _c1, _k in b.loc["spans"]]
        for t0, t1, _line, _c0, _c1, kind in b.loc["spans"]:
            if kind == "s":
                assert b.text[t0:t1] in ("\n", " | ")
                continue
            for off in range(t0, t1):
                ln, col = to_source(b, off)
                assert lines[ln - 1][col] == b.text[off]
                assert from_source(b, ln, col) == off
        for line, t0, t1 in b.loc["lines"]:
            if t1 > t0:
                assert {ln for ln, _, _ in span_to_source(b, t0, t1)} == {line}


def test_inline_markup_removed_code_and_intraword_underscores_kept():
    src = ("# T\n\nПоле `limit_kzt` и card_id, 2 * 3, **жирный** и *курсив*, \\*звёздочка\\*, "
           "[ссылка](https://x.test/a_b), <https://y.test>, A&amp;B, a<br>b.\n")
    data = src.encode()
    doc = parse_bytes(data, "md")
    b = doc.blocks[1]
    assert b.text == ("Поле limit_kzt и card_id, 2 * 3, жирный и курсив, *звёздочка*, "
                      "ссылка, https://y.test, A&B, a\nb.")
    assert [link["url"] for link in b.loc["links"]] == ["https://x.test/a_b", "https://y.test"]
    assert {b.text[s[0]:s[1]] for s in b.loc["spans"] if s[5] == "s"} == {"&", "\n"}
    assert verify_document(doc, data) == []
    start = b.text.index("жирный")
    col = src.split("\n")[2].index("жирный")
    assert span_to_source(b, start, start + 6) == [(3, col, col + 6)]


def test_setext_thematic_break_and_false_positives():
    src = ("Заголовок\n---------\n\nтекст\n\n---\n\n#хештег не заголовок\n* * *\n"
           "абзац\n2024. год не пункт\n| a | b | без разделителя\n")
    doc = parse_bytes(src.encode(), "md")
    assert [(b.loc["line_start"], b.kind, b.text) for b in doc.blocks] == [
        (1, "heading", "Заголовок"),
        (4, "paragraph", "текст"),
        (8, "paragraph", "#хештег не заголовок"),
        (10, "paragraph", "абзац\n2024. год не пункт\n| a | b | без разделителя"),
    ]
    assert (doc.blocks[0].loc["style"], doc.blocks[0].loc["line_end"]) == ("setext", 2)
    assert doc.warnings == []


def test_other_markdown_blocks_keep_all_lines():
    src = ("---\ntitle: x\n---\n\n<!-- скрыто\nв рендере -->\n\n    отступ 4\n    код\n\n"
           "> цитата\n> вторая\n>\n> третья\n\n* пункт\n\n  продолжение пункта\n")
    data = src.encode()
    doc = parse_bytes(data, "md")
    assert [(b.loc["line_start"], b.kind, b.text) for b in doc.blocks] == [
        (1, "other", "title: x"),
        (5, "other", "<!-- скрыто\nв рендере -->"),
        (8, "code", "отступ 4\nкод"),
        (11, "quote", "цитата\nвторая"),
        (14, "quote", "третья"),
        (16, "list_item", "пункт"),
        (18, "paragraph", "продолжение пункта"),
    ]
    assert [doc.blocks[0].loc["subtype"], doc.blocks[1].loc["subtype"]] == ["front_matter", "html_comment"]
    assert doc.blocks[6].loc["parent"] == at(doc, 16).id
    assert doc.warnings == [] and verify_document(doc, data) == []


def test_columns_are_code_points_and_u2028_does_not_break_lines():
    src = "# 𝄞 Ноты\n\nа б 😀 текст\n"
    data = src.encode()
    doc = parse_bytes(data, "md")
    head, para = doc.blocks
    assert span_to_source(head, 0, 1) == [(1, 2, 3)]  # 𝄞 — одна кодовая точка (4 байта UTF-8)
    assert (para.loc["line_start"], para.text) == (3, "а б 😀 текст")
    off = para.text.index("текст")
    assert to_source(para, off) == (3, off)
    assert data[para.loc["byte_start"]:para.loc["byte_end"]].decode() == para.text
    assert codes(doc) == ["line_separator_char"]


def test_entry_point_edges(tmp_path):
    empty = tmp_path / "empty.md"
    empty.write_bytes(b"")
    doc = read_text(empty)
    assert (doc.blocks, doc.title, codes(doc)) == ([], "empty", ["empty_document"])
    bom_only = tmp_path / "bom.txt"
    bom_only.write_bytes(b"\xef\xbb\xbf")
    assert read_text(bom_only).blocks == []
    no_eol = tmp_path / "no_eol.markdown"
    no_eol.write_bytes("# Т\nпоследняя".encode())
    assert [b.loc["line_start"] for b in read_text(no_eol).blocks] == [1, 2]
    with pytest.raises(ValueError):
        read_text(tmp_path / "spec.pdf")
    with pytest.raises(ValueError):
        parse_bytes(b"x", "pdf")
