"""№01: короткое ТЗ о лимите — таблица под пунктом, сноска, повтор числа; LF и CRLF с BOM.

Фикстуры ``limit_spec.lf.md`` и ``limit_spec.crlf_bom.md`` — один текст в двух кодировках переносов.
Сквозной вывод тех же фрагментов через ``read_document`` и CLI — ``tests/p01/p01_limit_scenario.py``.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from bcc_review.readers.text import Block, read_text, span_to_source

FIX = Path(__file__).parent / "fixtures"
LF, CRLF_BOM = FIX / "limit_spec.lf.md", FIX / "limit_spec.crlf_bom.md"
# (строка, цитата, номер вхождения в блоке) → (block_id, столбцы в строке файла)
FRAGMENTS = {
    (10, "50 000 ₸", 1): ("b0006", 21, 29),                               # то же число и в строке 9
    (16, "лимит 50 000 ₸ общий для всех каналов", 1): ("b0009", 41, 78),  # сноска: снят «^»
    (14, "50 000 ₸", 2): ("b0008", 52, 60),                               # второе число в абзаце
}


def _lines_and_starts(data: bytes) -> tuple[list[str], list[int]]:
    first = 3 if data.startswith(b"\xef\xbb\xbf") else 0
    starts = [first] + [m.end() for m in re.finditer(rb"\r\n|\r|\n", data)]
    return re.split(r"\r\n|\r|\n", data.decode("utf-8-sig")), starts


def _at(doc, line: int) -> Block:
    (b,) = [b for b in doc.blocks if any(e[0] == line for e in b.loc["lines"])]
    return b


def test_limit_fragments_back_read_identically_in_lf_and_crlf_bom():
    lf_bytes, crlf_bytes = LF.read_bytes(), CRLF_BOM.read_bytes()
    assert crlf_bytes == b"\xef\xbb\xbf" + lf_bytes.replace(b"\n", b"\r\n")
    docs = {LF: read_text(LF), CRLF_BOM: read_text(CRLF_BOM)}
    shape = {p: [(b.id, b.kind, b.section, b.text, b.loc["lines"], b.loc["map"]) for b in d.blocks]
             for p, d in docs.items()}
    assert shape[LF] == shape[CRLF_BOM]
    assert docs[LF].id == hashlib.sha256(lf_bytes).hexdigest() != docs[CRLF_BOM].id

    for path, doc in docs.items():
        data = path.read_bytes()
        lines, starts = _lines_and_starts(data)
        for (line, quote, nth), (bid, c0_exp, c1_exp) in FRAGMENTS.items():
            block = _at(doc, line)
            start = -1
            for _ in range(nth):
                start = block.text.index(quote, start + 1)
            (src_line, c0, c1), = span_to_source(block, start, start + len(quote))
            assert (block.id, src_line, c0, c1) == (bid, line, c0_exp, c1_exp), (path.name, quote)
            assert lines[line - 1][c0:c1] == quote  # обратное чтение строки файла
            b0 = starts[line - 1] + len(lines[line - 1][:c0].encode())
            assert data[b0:b0 + len(quote.encode())].decode("utf-8") == quote  # и по байтам

        # одно и то же число в двух строках таблицы — разные блоки и строки
        assert [(b.id, b.loc["line_start"]) for b in doc.blocks if b.kind == "table_row"] == [
            ("b0005", 9), ("b0006", 10)]
        # сноска читается как [1], разметка ^ снята, ссылка и определение связаны
        ref, note = _at(doc, 5), _at(doc, 16)
        assert ref.text == "Лимит переводов в сутки[1]"
        assert ref.loc["footnotes"] == [{"label": "1", "start": 23, "end": 26, "definition": note.id}]
        assert note.text.startswith("[1]: Сутки") and note.loc["footnote"] == {"label": "1", "refs": [ref.id]}
        (ln, c0, c1), = span_to_source(ref, 23, 26)
        assert (ln, lines[ln - 1][c0:c1]) == (5, "[^1]")
        assert not any("[^" in b.text for b in doc.blocks)
