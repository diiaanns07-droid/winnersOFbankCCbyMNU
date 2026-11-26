"""Резервный читатель Markdown/TXT: обратимая карта позиций, неполное чтение, таблицы."""

from bcc_review import contracts as C
from bcc_review.runtime.fallback.text_reader import read_text, source_position

from .conftest import BCC


def test_bcc_document_valid_and_hash():
    doc = read_text(BCC)
    C.validate(doc, "Document")
    assert doc["id"] == C.sha256_file(BCC) and doc["warnings"] == []
    assert len({b["id"] for b in doc["blocks"]}) == len(doc["blocks"])


def test_position_map_round_trip():
    doc = read_text(BCC)
    lines = BCC.read_text(encoding="utf-8").split("\n")
    checked = 0
    for b in doc["blocks"]:
        for off, ch in enumerate(b["text"]):
            pos = source_position(b, off)
            if pos is None:  # синтетический разделитель: перевод строки или « | »
                assert ch in "\n |", (b["id"], off, ch)
                continue
            line, col = pos
            assert lines[line - 1][col] == ch, (b["id"], off)
            checked += 1
    assert checked > 5000


def test_markup_stripped_and_lines_one_based():
    doc = read_text(BCC)
    f1 = next(b for b in doc["blocks"] if b["text"].startswith("Ф-1."))
    assert "**" not in f1["text"] and f1["kind"] == "list_item"
    assert f1["loc"]["line_start"] == f1["loc"]["line_end"] == 37
    row = next(b for b in doc["blocks"] if b["kind"] == "table_row" and "amount | integer" in b["text"])
    assert row["loc"]["columns"][0] == "Parameter"


def test_broken_utf8_is_partial_read(tmp_path):
    p = tmp_path / "broken.md"
    p.write_bytes("# Заголовок\n\nТекст требования.\n\n".encode("utf-8") + bytes([0xFF, 0xFE]) + b"\n")
    doc = read_text(p)
    assert any(w["code"] == "decode_error" for w in doc["warnings"])
    assert "Текст требования." in [b["text"] for b in doc["blocks"]]


def test_cp1251_file_read_with_warning(tmp_path):
    p = tmp_path / "legacy.txt"
    p.write_bytes("Система должна хранить порог в тенге.\n\nВторой абзац требований.\n".encode("cp1251"))
    doc = read_text(p)
    assert doc["format"] == "text"
    assert any(w["code"] == "encoding_guess" for w in doc["warnings"])
    assert doc["blocks"][0]["text"].startswith("Система должна")
