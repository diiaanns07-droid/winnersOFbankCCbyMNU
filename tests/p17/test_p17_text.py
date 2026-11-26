"""Русская грамматика чисел, форматы и экранирование Markdown."""

from __future__ import annotations

import pytest

from bcc_review.exports._common import (
    FINDING,
    REQ,
    REQ_GEN,
    count,
    fmt_duration,
    fmt_int,
    fmt_pct,
    of_count,
    plural,
)
from bcc_review.exports.markdown import esc, esc_lead, quote_block

NB = " "


@pytest.mark.parametrize(
    "n, word",
    [
        (0, "требований"),
        (1, "требование"),
        (2, "требования"),
        (4, "требования"),
        (5, "требований"),
        (11, "требований"),
        (12, "требований"),
        (14, "требований"),
        (21, "требование"),
        (22, "требования"),
        (101, "требование"),
        (111, "требований"),
        (1.5, "требования"),
    ],
)
def test_plural_forms(n, word):
    assert plural(n, REQ) == word


def test_genitive_after_iz():
    assert of_count(1, 21, REQ_GEN) == "1 из 21 требования"
    assert of_count(4, 6, REQ_GEN) == "4 из 6 требований"
    assert of_count(0, 1, REQ_GEN) == "0 из 1 требования"
    assert count(21, FINDING) == "21 замечание"
    assert count(3, FINDING) == "3 замечания"


def test_numbers_percent_duration():
    assert fmt_int(999) == "999"
    assert fmt_int(1000) == f"1{NB}000"
    assert fmt_int(1234567) == f"1{NB}234{NB}567"
    assert fmt_pct(2, 3) == f"66,7{NB}%"
    assert fmt_pct(1, 2) == f"50{NB}%"
    assert fmt_pct(1, 8) == f"12,5{NB}%"
    assert fmt_pct(0, 0) == "—"
    assert fmt_duration(None) == "нет данных"
    assert fmt_duration(12.34) == f"12,3{NB}с"
    assert fmt_duration(83.5) == f"1{NB}мин 24{NB}с"
    assert fmt_duration(3725) == f"1{NB}ч 2{NB}мин"


TRICKY = [
    "Если результат 200 или 201 | успешный",
    "**Ф-1.** Держатель `cardId` <b>активной</b> карты [KZT] & т. д.",
    "1. Проверить сессию.\n2. Проверить карту.\n---\n# не заголовок",
    '{"result":"ERROR","message":"Проверьте сумму"}\n    отступ 4 пробела',
    "a\\|b ~~x~~ _y_ 50 000 ₸ «кавычки» \"двойные\"",
    "строка\n\nпосле пустой строки",
]


def _inline_texts(tokens):
    """Текст каждого inline-токена; переносы и <br> — как \\n."""
    out = []
    for t in tokens:
        if t.type != "inline":
            continue
        parts = []
        for c in t.children:
            if c.type in ("text", "code_inline"):
                parts.append(c.content)
            elif c.type in ("softbreak", "hardbreak"):
                parts.append("\n")
            elif c.type == "html_inline" and c.content == "<br>":
                parts.append("\n")
            else:
                parts.append(f"<{c.type}>")
        out.append("".join(parts).replace(NB, " "))
    return out


@pytest.mark.parametrize("text", TRICKY)
def test_escaping_roundtrip_with_commonmark_parser(text):
    markdown_it = pytest.importorskip("markdown_it")
    md = markdown_it.MarkdownIt("commonmark").enable("table").enable("strikethrough")
    # Ячейка таблицы: структура таблицы цела, текст совпадает.
    table = f"| h1 | h2 |\n| --- | --- |\n| x | {esc(text)} |\n"
    tokens = md.parse(table)
    assert sum(1 for t in tokens if t.type == "td_open") == 2
    assert _inline_texts(tokens)[-1] == text
    # Многострочная цитата: ни списков, ни заголовков, ни блока кода.
    tokens = md.parse("\n".join(quote_block(text)) + "\n")
    kinds = {t.type for t in tokens}
    assert kinds <= {"blockquote_open", "blockquote_close", "paragraph_open", "paragraph_close", "inline"}
    assert _inline_texts(tokens) == [text]
    # Пункт списка, начинающийся с пользовательского текста.
    tokens = md.parse(f"- {esc_lead(text)}\n")
    assert sum(1 for t in tokens if t.type == "list_item_open") == 1


def test_escaping_without_parser_keeps_pipes_escaped():
    assert esc("a | b") == "a \\| b"
    assert esc("x\ny") == "x<br>y"
    assert quote_block("1. первая\n2. вторая") == ["> 1\\. первая\\", "> 2\\. вторая"]
