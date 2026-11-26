"""Сквозной сценарий №01: короткое ТЗ о лимите в LF и в CRLF с BOM через штатный ``read_document``.

Запуск из корня репозитория (после ``pip install -e ".[all,dev]"``)::

    python tests/p01/p01_limit_scenario.py

Для трёх фрагментов печатает block_id, текст блока, исходную строку и обратное чтение этой строки из
байтов файла (своим разбором, без reader). Затем сравнивает варианты LF и CRLF+BOM и показывает
фрагмент официального ТЗ ``release/input/requirements.md``. Если модуль №07 есть в checkout, место
дополнительно считает ``bcc_review.analysis.evidence.locate``. Код выхода 0 — все сверки совпали.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from bcc_review.engine import read_document  # noqa: E402
from bcc_review.readers.text import Block, span_to_source  # noqa: E402
from bcc_review.runtime.modules import Modules  # noqa: E402

try:  # №07, если влит
    from bcc_review.analysis.evidence import locate
except ImportError:  # pragma: no cover
    locate = None

FIX = ROOT / "tests" / "p01" / "fixtures"
VARIANTS = ("limit_spec.lf.md", "limit_spec.crlf_bom.md")
# (строка, цитата, номер вхождения в блоке с 1)
FRAGMENTS = (
    (10, "50 000 ₸", 1),                               # то же число есть в строке 9 таблицы
    (16, "лимит 50 000 ₸ общий для всех каналов", 1),  # сноска [^1]
    (14, "50 000 ₸", 2),                               # второе число в обычном тексте
)
OFFICIAL = (ROOT / "release" / "input" / "requirements.md", 39,
            "максимум один такой push за календарный месяц", 1)


def raw_lines(data: bytes) -> list[str]:
    return re.split(r"\r\n|\r|\n", data.decode("utf-8-sig"))


def line_byte_starts(data: bytes) -> list[int]:
    first = 3 if data.startswith(b"\xef\xbb\xbf") else 0
    return [first] + [m.end() for m in re.finditer(rb"\r\n|\r|\n", data)]


def fragment(path: Path, line: int, quote: str, nth: int) -> dict:
    data = path.read_bytes()
    doc = read_document(path)
    (raw_block,) = [b for b in doc["blocks"] if any(e[0] == line for e in b["loc"]["lines"])]
    block = Block(**raw_block)
    start = -1
    for _ in range(nth):
        start = block.text.index(quote, start + 1)
    end = start + len(quote)
    ((src_line, c0, c1),) = span_to_source(block, start, end)
    lines = raw_lines(data)
    back = lines[src_line - 1][c0:c1]
    b0 = line_byte_starts(data)[src_line - 1] + len(lines[src_line - 1][:c0].encode())
    by_bytes = data[b0:b0 + len(back.encode())].decode("utf-8")
    out = {"block_id": block.id, "text": block.text, "start": start, "end": end, "line": src_line,
           "col": c0, "col_end": c1, "raw_line": lines[src_line - 1], "back_read": back,
           "bytes": by_bytes, "doc_id": doc["id"]}
    if locate is not None:
        place = locate(doc, {"block_id": block.id, "start": start, "end": end, "quote": quote})
        out["p07"] = (place["line"], place["col"], place["col_end"])
    same_p07 = out.get("p07", (line, c0, c1)) == (line, c0, c1)
    out["ok"] = back == quote == by_bytes and src_line == line and same_p07
    return out


def main() -> int:
    print(f"reader: {Modules().get('read_text').label}; №07 locate: {'да' if locate else 'нет в checkout'}")
    ok = True
    results: dict[str, list[dict]] = {}
    for name in VARIANTS:
        path = FIX / name
        print(f"\n== {name} ({len(path.read_bytes())} байт)")
        results[name] = []
        for line, quote, nth in FRAGMENTS:
            r = fragment(path, line, quote, nth)
            results[name].append(r)
            ok &= r["ok"]
            p07 = f"; №07 locate {r['p07']}" if "p07" in r else ""
            print(f"  {r['block_id']}  строка {r['line']}  [{r['col']}:{r['col_end']}]"
                  f"  text[{r['start']}:{r['end']}]  {'OK' if r['ok'] else 'РАСХОЖДЕНИЕ'}{p07}")
            print(f"     text:       {r['text']!r}")
            print(f"     строка {r['line']}:  {r['raw_line']!r}")
            print(f"     обратно:    {r['back_read']!r} (по байтам: {r['bytes']!r})")
    a, b = (results[n] for n in VARIANTS)
    keys = ("block_id", "text", "start", "end", "line", "col", "col_end", "back_read")
    same = all({k: x[k] for k in keys} == {k: y[k] for k in keys} for x, y in zip(a, b, strict=True))
    print(f"\nLF и CRLF+BOM: Document.id {a[0]['doc_id'][:12]} ≠ {b[0]['doc_id'][:12]}; "
          f"block_id/текст/строка/столбцы/обратное чтение {'совпадают' if same else 'РАЗЛИЧАЮТСЯ'}")
    ok &= same and a[0]["doc_id"] != b[0]["doc_id"]

    path, line, quote, nth = OFFICIAL
    if path.exists():
        r = fragment(path, line, quote, nth)
        ok &= r["ok"]
        print(f"\n== release/input/requirements.md: {r['block_id']} строка {r['line']}"
              f" [{r['col']}:{r['col_end']}] {'OK' if r['ok'] else 'РАСХОЖДЕНИЕ'}")
        print(f"     text:    {r['text']!r}")
        print(f"     обратно: {r['back_read']!r}")
    print("\nИТОГ:", "OK" if ok else "РАСХОЖДЕНИЕ")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
