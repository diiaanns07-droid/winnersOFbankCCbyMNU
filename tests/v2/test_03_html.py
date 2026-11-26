"""№03: HTML на входе (readers_html) — заголовки, абзацы, списки, таблицы, pre → строки DocView."""

from __future__ import annotations

from bcc_review.v2 import docview as dv
from bcc_review.v2 import quotes as Q
from bcc_review.v2 import readers_html as H

HTML = """<!doctype html><html><head><meta charset="utf-8"><title>Тест &amp; ТЗ</title>
<style>p{color:red}</style><script>var x = "<p>не текст</p>";</script></head>
<body><nav><a href="#">Меню</a></nav>
<h1>Лимит переводов</h1>
<p>Комплект требований. <b>Важно</b>:&nbsp;читать целиком.</p>
<h2>Часть A</h2>
<h3>Функциональные требования</h3>
<ul>
 <li><p><strong>ЛП-1.</strong> Клиент задаёт лимит от 1&nbsp;000 до 500&nbsp;000 ₸.</p></li>
 <li>ЛП-2. Лимит действует<br>с начала суток.</li>
</ul>
<ol start="3"><li>Третий пункт</li><li>Четвёртый пункт</li></ol>
<table><thead><tr><th>Параметр</th><th>Тип</th></tr></thead>
<tbody><tr><td><code>amount</code></td><td>integer</td></tr><tr><td></td><td></td></tr>
<tr><td>enabled</td><td><p>0 или 1</p></td></tr></tbody></table>
<h2>Часть B</h2>
<pre><code>{"result":"OK",
 "amount":"5000"}</code></pre>
<div>Текст в div без абзаца</div>
<div><div><p>Вложенный абзац</p></div></div>
Хвостовой текст
</body></html>"""


def test_html_blocks_to_lines():
    v = H.view_from_html(HTML, file="t.html")
    texts = [ln["text"] for ln in v["lines"]]
    assert v["title"] == "Лимит переводов" and v["format"] == "html" and v["pages"] is None
    assert texts[0] == "Лимит переводов"
    assert "Комплект требований. Важно: читать целиком." in texts
    assert "ЛП-1. Клиент задаёт лимит от 1 000 до 500 000 ₸." in texts
    assert texts[texts.index("ЛП-2. Лимит действует") + 1] == "с начала суток."
    assert "3. Третий пункт" in texts and "4. Четвёртый пункт" in texts
    assert "Параметр | Тип" in texts and "amount | integer" in texts and "enabled | 0 или 1" in texts
    assert '{"result":"OK",' in texts
    assert "Вложенный абзац" in texts and "Хвостовой текст" in texts and "Текст в div без абзаца" in texts
    joined = "\n".join(texts)
    assert "Меню" not in joined and "не текст" not in joined and "color" not in joined
    assert all(t.strip() for t in texts)   # пустые строки таблиц не попадают
    assert [ln["n"] for ln in v["lines"]] == list(range(1, len(texts) + 1))


def test_html_sections_and_src_lines():
    v = H.view_from_html(HTML, file="t.html")
    by_text = {ln["text"]: ln for ln in v["lines"]}
    assert by_text["ЛП-1. Клиент задаёт лимит от 1 000 до 500 000 ₸."]["section"] == "Часть A › Функциональные требования"
    assert by_text["Вложенный абзац"]["section"] == "Часть B"
    assert by_text["Лимит переводов"]["section"] == ""
    src = HTML.splitlines()
    for t in ("ЛП-2. Лимит действует", "Хвостовой текст", "Параметр | Тип"):
        n = by_text[t]["src_line"]
        assert t.split(" | ")[0].split(".")[0][:6] in src[n - 1], (t, n, src[n - 1])


def test_html_load_file_and_quotes(tmp_path):
    p = tmp_path / "req.html"
    p.write_text(HTML, encoding="utf-8")
    v = dv.load(p)
    assert v["format"] == "html" and v["file"] == "req.html" and len(v["sha256"]) == 64
    m = Q.verify_quote(v, "Клиент задаёт лимит от 1000 до 500000 ₸", 5)
    assert m and m["verified"] == "normalized" and m["section"].endswith("Функциональные требования")
    assert dv.numbered(v, 1, 1) == "L001| Лимит переводов"


def test_html_cp1251_and_empty(tmp_path):
    p = tmp_path / "a.htm"
    p.write_bytes('<html><head><meta charset="windows-1251"></head><body><p>Привет</p></body></html>'
                  .encode("cp1251"))
    v = dv.load(p)
    assert [ln["text"] for ln in v["lines"]] == ["Привет"]
    e = H.view_from_html("<html><body><script>x</script></body></html>")
    assert e["lines"] == [] and e["warnings"]
