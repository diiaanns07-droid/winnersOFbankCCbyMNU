"""Модульные тесты HTML-отчёта (№13): без браузера и сети."""

from __future__ import annotations

import base64
import dataclasses
import hashlib
import json
import re
from collections import defaultdict
from html.parser import HTMLParser
from pathlib import Path

import pytest

from bcc_review.exports import html as H
from fixture_builder import (
    EMOJI_TEXT,
    build_empty_report,
    build_partial_empty_report,
    build_partial_report,
    build_report,
)


class Collector(HTMLParser):
    """Восстанавливает текст блоков и подсвеченных опор так, как его видит DOM."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.block: str | None = None
        self.in_text = False
        self.texts: dict[str, str] = {}
        self.cur_ev: list[str] | None = None
        self.ev_text: dict[str, str] = defaultdict(str)
        self.ev_block: dict[str, set[str]] = defaultdict(set)
        self.ev_cp: dict[str, list[tuple[int, int]]] = defaultdict(list)
        self.ids: list[str] = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if a.get("id"):
            self.ids.append(a["id"])
        if "data-block" in a and tag == "div":
            self.block = a["data-block"]
            self.texts[self.block] = ""
        if "data-text" in a:
            self.in_text = True
        if self.in_text and tag == "span" and "data-ev" in a:
            self.cur_ev = a["data-ev"].split()
            s, e = map(int, a["data-cp"].split(":"))
            for ev in self.cur_ev:
                self.ev_cp[ev].append((s, e))
                self.ev_block[ev].add(self.block)

    def handle_endtag(self, tag):
        if tag == "span":
            self.cur_ev = None
        if tag == "div" and self.in_text:
            self.in_text = False

    def handle_data(self, data):
        if self.in_text and self.block is not None:
            self.texts[self.block] += data
            for ev in self.cur_ev or []:
                self.ev_text[ev] += data


def parse(html_text: str) -> Collector:
    c = Collector()
    c.feed(html_text)
    return c


def view_model(html_text: str) -> dict:
    m = re.search(r'<script type="application/json" id="bcc-data">(.*?)</script>', html_text, re.S)
    assert m
    return json.loads(m.group(1))


def card(text: str, fid: str) -> str:
    part = text[text.index(f'id="{H.finding_anchor(fid)}"') :]
    return part[: part.index("</article>")]


def section(text: str, sid: str) -> str:
    part = text[text.index(f'<section id="{sid}"') :]
    return part[: part.index("</section>")]


# --------------------------------------------------------------------------- #


def test_write_html_returns_path_single_file(tmp_path, report):
    out = H.write_html(report, tmp_path / "sub" / "report.html")
    assert isinstance(out, Path) and out.is_file() and out.suffix == ".html"
    assert out == (tmp_path / "sub" / "report.html").resolve()
    text = out.read_text(encoding="utf-8")
    assert text.startswith("<!doctype html>")
    # Нет внешних ресурсов: ни src, ни link, ни url() в стилях, ни @import.
    assert not re.search(r"<(script|img|iframe|link)[^>]+\bsrc=", text)
    assert "<link" not in text
    assert "@import" not in text and "url(" not in text
    assert not re.search(r'href="(https?:)?//', text)
    assert list(tmp_path.joinpath("sub").iterdir()) == [out]


def test_stable_anchors(report):
    text = H.render_html(report)
    c = parse(text)
    ids = set(c.ids)
    for f in report["findings"]:
        assert H.finding_anchor(f["id"]) in ids
    for b in report["document"]["blocks"]:
        assert H.block_anchor(b["id"]) in ids
    for q in report["questions"]:
        assert H.question_anchor(q["id"]) in ids
    for r in report["requirements"]:
        assert H.requirement_anchor(r["id"]) in ids
    for sid in ("summary", "workspace", "requirements", "questions", "checklist", "coverage", "diff", "test-cases", "facts", "run"):
        assert sid in ids
    assert len(ids) == len(c.ids), "дубли id в HTML"
    assert H.finding_anchor("F-001") == "finding-F-001"
    assert H.block_anchor("b0017") == "block-b0017"


@pytest.mark.parametrize(
    "a,b",
    [("A_1", "A 1"), ("a_20_", "a "), ("p/1", "p_2f_1"), ("Ф-1", "_424_-1"), ("x.y", "x_2e_y")],
)
def test_anchor_slug_is_injective(a, b):
    assert H.anchor_slug(a) != H.anchor_slug(b)
    assert re.fullmatch(r"[A-Za-z0-9._\-]+", H.anchor_slug(a))


def test_block_text_in_dom_equals_json(report):
    c = parse(H.render_html(report))
    for b in report["document"]["blocks"]:
        assert c.texts[b["id"]] == b["text"], b["id"]


def test_highlight_text_equals_quotes(report):
    text = H.render_html(report)
    c = parse(text)
    vm = view_model(text)
    assert len(vm["ev"]) >= 30 and all(ev["ok"] for ev in vm["ev"].values())
    for ev_id, ev in vm["ev"].items():
        assert c.ev_text[ev_id] == ev["q"], ev_id
        assert c.ev_block[ev_id] == {ev["b"]}
        spans = c.ev_cp[ev_id]
        assert spans[0][0] == ev["s"] and spans[-1][1] == ev["e"]
        assert all(x[1] == y[0] for x, y in zip(spans, spans[1:])), "опора разорвана"
    # F-009 — подсказка без координат: показана как подсказка, не подсвечена.
    f9 = card(text, "F-009")
    assert "Подсказка без координат" in f9 and 'class="q-btn"' not in f9


def test_bad_evidence_is_not_highlighted(report):
    f = next(x for x in report["findings"] if x["id"] == "F-007")
    f["evidence"][0]["quote"] = "Возврат увеличивает расходы"  # координаты прежние, текст другой
    f["evidence"].append({"block_id": "b9999", "start": 0, "end": 3, "quote": "нет"})
    text = H.render_html(report)
    vm = view_model(text)
    bad = [ev for ev in vm["ev"].values() if not ev["ok"]]
    assert len(bad) == 2 and all(ev["f"] == ["F-007"] for ev in bad)
    c7 = card(text, "F-007")
    assert c7.count("Опора не подтверждена") == 2 and "неподтверждённых опор: 2" in c7
    assert "не подтверждены и не подсвечены: 2" in text
    assert not any(k in parse(text).ev_text for k, ev in vm["ev"].items() if not ev["ok"])


def test_same_quote_second_occurrence_and_other_block(report):
    vm = view_model(H.render_html(report))
    f6 = vm["findings"]["F-006"]
    evs = [vm["ev"][e] for e in f6["ev"]]
    assert evs[0]["q"] == evs[1]["q"] == "Да / Нет"
    assert evs[0]["b"] != evs[1]["b"]
    blocks = {b["id"]: b["text"] for b in report["document"]["blocks"]}
    assert evs[0]["s"] > blocks[evs[0]["b"]].index("Да / Нет"), "должно быть второе вхождение"
    assert len(set(f6["ev"])) == 3


def test_overlapping_ranges_share_segment(report):
    text = H.render_html(report)
    c = parse(text)
    vm = view_model(text)
    owners = {ev_id: set(ev["f"]) for ev_id, ev in vm["ev"].items()}
    shared = [
        ids
        for ids in (seg.split() for seg in re.findall(r'<span class="hl[^"]*" data-ev="([^"]+)"', text))
        if {"F-002", "F-008"} <= set().union(*(owners[e] for e in ids))
    ]
    assert shared, "нет общего сегмента F-002 и F-008"
    assert c.ev_text[vm["findings"]["F-002"]["a"][0]] == report["findings"][1]["witness"]["evidence_a"]["quote"]
    assert c.ev_text[vm["findings"]["F-008"]["ev"][0]] == report["findings"][7]["evidence"][0]["quote"]
    # F-005 и F-010 пересекаются в строке таблицы amount.
    assert c.ev_block[vm["findings"]["F-005"]["ev"][0]] == c.ev_block[vm["findings"]["F-010"]["ev"][0]]


def test_emoji_codepoint_offsets(report):
    vm = view_model(H.render_html(report))
    ev = vm["ev"][vm["findings"]["F-012"]["ev"][0]]
    assert EMOJI_TEXT[ev["s"] : ev["e"]] == ev["q"] == "Порог 50 000 ₸ достигнут"
    utf16_start = len(EMOJI_TEXT[: ev["s"]].encode("utf-16-le")) // 2
    assert utf16_start != ev["s"], "фикстура должна различать кодовые точки и UTF-16"


def test_html_like_source_is_text(report):
    text = H.render_html(report)
    assert text.count("<script") == 2  # JSON-данные и код отчёта
    assert "&lt;script&gt;alert(&quot;xss&quot;)&lt;/script&gt;" in text or '&lt;script&gt;alert("xss")&lt;/script&gt;' in text
    assert "<b>Порог</b>" not in text
    data = re.search(r'id="bcc-data">(.*?)</script>', text, re.S).group(1)
    assert "<" not in data


def test_cr_is_preserved_as_charref(report):
    text = H.render_html(report)
    assert "&#13;" in text and "\r" not in text


def test_csp_hashes_match_inline_code(report):
    text = H.render_html(report)
    csp = re.search(r'http-equiv="Content-Security-Policy" content="([^"]+)"', text).group(1)
    style = re.search(r"<style>(.*?)</style>", text, re.S).group(1)
    script = re.findall(r"<script>(.*?)</script>", text, re.S)[-1]

    def h(s: str) -> str:
        return "'sha256-" + base64.b64encode(hashlib.sha256(s.encode()).digest()).decode() + "'"

    assert f"style-src {h(style)}" in csp
    assert f"script-src {h(script)}" in csp
    assert "default-src 'none'" in csp


def test_nul_and_lone_surrogate_do_not_break_offsets(tmp_path):
    rep = build_empty_report()
    blk = rep["document"]["blocks"][1]
    blk["text"] = "a\x00b\ud800c порог"
    rep["findings"] = [
        {"id": "F-1", "scope": "requirement", "kind": "ambiguity", "criterion": "unambiguous", "severity": "minor",
         "status": "confirmed", "title": "t", "evidence": [{"block_id": blk["id"], "start": 6, "end": 11, "quote": "порог"}]}
    ]
    out = H.write_html(rep, tmp_path / "r.html")
    text = out.read_text(encoding="utf-8")
    c = parse(text)
    assert c.texts[blk["id"]] == "a�b�c порог"
    assert c.ev_text[view_model(text)["findings"]["F-1"]["ev"][0]] == "порог"
    assert "непредставимых" in text


@pytest.mark.parametrize(
    "minimal",
    [{}, {"schema_version": "1.0"}, {"document": {"blocks": []}, "findings": [], "run": {"status": "complete"}}],
)
def test_minimal_reports_render(minimal):
    text = H.render_html(minimal)
    assert "Замечаний нет" in text
    assert 'id="workspace"' in text


def test_empty_and_partial_states():
    assert "Замечаний нет.</strong>" in H.render_html(build_empty_report())
    pe = H.render_html(build_partial_empty_report())
    assert "Замечаний нет, но прогон неполный" in pe and "предварительно" in pe
    assert "Не выполнены этапы: individual, cross" in pe
    p = H.render_html(build_partial_report())
    assert "Прогон неполный" in p and "чтение: partial_read" in p
    assert p.count("Не определено") >= 2
    failed = build_empty_report()
    failed["run"]["status"] = "failed"
    assert "Прогон завершился ошибкой" in H.render_html(failed)


def test_diff_three_statuses_and_new_list(report):
    sec = section(H.render_html(report), "diff")
    for label in ("Исправлено", "Осталось", "Не оценено"):
        assert label in sec
    assert "Новые замечания (2)" in sec
    assert 'href="#finding-F-012"' in sec and 'href="#finding-F-001"' in sec
    assert 'class="q-btn"' in sec  # опора из diff кликабельна
    assert "Затронутые требования" in sec


def test_verdict_and_first_actions_on_top(report):
    text = H.render_html(report)
    top = text[text.index('id="summary"') : text.index('id="workspace"')]
    assert text.index('id="summary"') < text.index('id="workspace"') < text.index('id="questions"')
    assert top.count("Нельзя начинать") == 2
    assert "Что сделать первым" in top
    actions = re.findall(r"<li>([^<]+) <span class=\"refs\">", top)
    assert actions[0].startswith("Решить, допускается ли второй push"), "первые действия упорядочены по order"
    assert "Учтено ответов на вопросы" in top
    assert "блокируют тестирование" in top


def test_severity_not_only_color(report):
    text = H.render_html(report)
    for label, glyph, _ in H.SEVERITY.values():
        assert f'<span aria-hidden="true">{glyph}</span> {label}' in text


def test_conflict_card_has_input_two_outcomes_and_both_quotes(report):
    text = H.render_html(report)
    c1 = card(text, "F-001")
    assert "Вход." in c1 and "Исход A" in c1 and "Исход B" in c1
    assert c1.count('class="q-btn"') == 2
    assert 'data-side="a"' in c1 and 'data-side="b"' in c1
    assert "Блокирует решение" in c1 and "блокирует разработку" in c1
    c4 = card(text, "F-004")
    for h in ("Основание", "Последствие", "Источник", "Как исправить"):
        assert h in c4
    assert "правило без LLM" in c4
    assert "Уточняющий вопрос" in card(text, "F-003")
    assert "Объединено из: C-17, C-23" in card(text, "F-011")


def test_quote_place_uses_loc_map(report):
    text = H.render_html(report)
    c1 = card(text, "F-001")
    assert "строка 39" in c1 and "строка 40" in c1  # Ф-3 и Ф-4 в case_ab.md


def test_source_hash_mismatch_is_flagged(report):
    report["run"]["source_sha256"] = "f" * 64
    assert "Хеш документа не совпадает" in H.render_html(report)


def test_pdf_pages_and_optional_link():
    rep = build_empty_report()
    rep["document"]["format"] = "pdf"
    for i, b in enumerate(rep["document"]["blocks"]):
        b["loc"] = {"page": 1 + i // 60, "fragments": [{"start": 0, "end": len(b["text"]), "rect": [0, 0, 1, 1]}]}
    text = H.render_html(rep)
    assert "Страница 2" in text and "стр. 3" in text
    assert "Оригинальный файл не приложен" in text
    assert 'href="original.pdf#page=2"' in H.render_html(rep, pdf_href="original.pdf")


def test_decisions_shown_as_answered_and_stale_flagged(report):
    text = H.render_html(report)
    q = section(text, "questions")
    q5 = q[q.index('id="question-Q-05"') :]
    assert "Ответ учтён при этом прогоне" in q5 and "в исходный документ не внесены" in q5
    assert "Открытые вопросы (4 из 5)" in q
    report["decisions"][0]["source_sha256"] = "a" * 64
    stale = section(H.render_html(report), "questions")
    assert "Ответ дан к другой версии документа" in stale
    assert "Открытые вопросы (5 из 5)" in stale


def test_answers_markdown_roundtrip(report):
    tricky = "# не заголовок\n\\обратный слэш\n### Ответ\n\n🔔 emoji\nпоследняя"
    md = H.answers_markdown(report, {"Q-01": tricky, "Q-03": "Клиринг", "Q-04": "   "}, exported_at="2026-11-26T00:00:00Z")
    parsed = H.parse_answers_markdown(md)
    assert parsed["meta"]["format"] == H.ANSWERS_FORMAT
    assert parsed["meta"]["source_sha256"] == report["document"]["id"]
    assert parsed["answers"]["Q-01"] == tricky
    assert parsed["answers"]["Q-03"] == "Клиринг"
    assert "Q-04" not in parsed["answers"]  # пустой ответ не выдаётся за ответ
    assert parsed["answers"]["Q-05"].startswith("400 Bad Request")  # ответ, учтённый прогоном
    assert md.count("\n## Q-") == len(report["questions"])
    assert "Варианты: Да, после изменения порога | Нет, не более одного push в месяц" in md


def test_view_model_answers_header_matches_python(report):
    vm = view_model(H.render_html(report))
    header = [("exported_at: X" if h is None else h) for h in vm["answers"]["header"]]
    assert H.answers_markdown(report, {}, exported_at="X").startswith("\n".join(header))
    assert vm["answers"]["storageKey"] == H.answers_storage_key(report["document"]["id"])


def test_input_types_dataclass_path_pydantic(tmp_path, report):
    expected = H.render_html(report)
    p = tmp_path / "report.json"
    p.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
    assert H.render_html(p) == expected

    @dataclasses.dataclass
    class Wrapper:
        data: dict

        def to_dict(self):
            return self.data

    assert H.render_html(Wrapper(report)) == expected
    pydantic = pytest.importorskip("pydantic")

    class Model(pydantic.BaseModel):
        model_config = pydantic.ConfigDict(extra="allow")

    assert H.render_html(Model(**report)) == expected


def test_cli_main(tmp_path, report, capsys):
    src = tmp_path / "report.json"
    src.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
    assert H.main([str(src), str(tmp_path / "out.html")]) == 0
    assert (tmp_path / "out.html").is_file()
    assert capsys.readouterr().out.strip().endswith("out.html")


def test_all_variants_render(any_variant, tmp_path):
    name, rep = any_variant
    out = H.write_html(rep, tmp_path / f"{name}.html")
    c = parse(out.read_text(encoding="utf-8"))
    for b in rep["document"]["blocks"]:
        assert c.texts[b["id"]] == b["text"]
