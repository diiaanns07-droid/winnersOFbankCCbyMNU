"""Тесты HTML-отчёта v2 (№14): один файл, без сети, подсветка цитат, вкладки, экранирование."""
from __future__ import annotations

import copy
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from bcc_review.v2.render import html as H

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / "release" / "input" / "requirements.md"
SAMPLE = ROOT / "tests" / "v2" / "fixtures" / "14_report_official.json"


@pytest.fixture(scope="module")
def report() -> dict:
    return json.loads(SAMPLE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def view() -> dict:
    return H.load_view(DOC)


@pytest.fixture(scope="module")
def page(report, view) -> str:
    return H.render_html(report, view)


def test_single_file_without_network(page):
    assert page.startswith("<!doctype html>")
    # ни одного внешнего ресурса: ни <script src>, ни <link href=http…>, ни @import/url(http…)
    assert not re.search(r"<script[^>]+src=", page)
    assert not re.search(r"""<link[^>]+href=["']?https?:""", page)
    assert not re.search(r"url\(\s*['\"]?https?:", page)
    assert "@import" not in page
    assert "<style>" in page and "report-data" in page


def test_header_verdict_and_counts(page, report):
    assert "Нельзя" in page
    crit = sum(1 for f in report["findings"] if f["severity"] == "critical")
    assert f'<span class="tnum">{crit}</span><span class="tlab">Критичных' in page
    assert "Исправить первым" in page


def test_every_finding_has_card_and_highlight(page, report):
    for f in report["findings"]:
        assert f'id="{f["id"]}"' in page
        lines = {ev["line_start"] for ev in f["evidence"]}
        for n in lines:
            m = re.search(rf'<div class="[^"]*\bhl\b[^"]*" id="L{n}" data-n="{n}" data-f="([^"]*)"', page)
            assert m, f"строка {n} не подсвечена"
            assert f["id"] in m.group(1).split()


def test_quote_marked_inside_line(page):
    # цитата К1 из строки 64 подсвечена как critical
    assert re.search(r'<mark class="q sev-critical" data-f="[^"]*D-05[^"]*">Февральский счётчик вырос на 4 000 ₸</mark>', page)


def test_tabs_present(page):
    for name in ("Замечания", "Вопросы", "Тест-кейсы", "Чек-лист банка", "Проверки", "Нарезка", "Отклонённые", "Паспорт"):
        assert f">{name}<" in page
    assert page.count('role="tabpanel"') == 8


def test_no_view_still_renders(report):
    page = H.render_html(report, None)
    assert "Текст документа не передан" in page
    assert 'id="D-01"' in page


def test_partial_run_banner(report, view):
    r = copy.deepcopy(report)
    r["run"]["status"] = "partial"
    r["run"]["stages"]["lens:risk"] = "failed"
    page = H.render_html(r, view)
    assert "Прогон неполный" in page and "Линза «Риски»" in page


def test_empty_report_renders(view):
    page = H.render_html({"schema": "bcc-review/2", "run": {"status": "complete"}, "findings": []}, view)
    assert "Замечаний нет" in page


def test_escaping(report, view):
    r = copy.deepcopy(report)
    r["findings"][0]["title"] = '<img src=x onerror=alert(1)>'
    r["findings"][0]["problem"] = "</script><script>alert(2)</script>"
    page = H.render_html(r, view)
    assert "<img src=x" not in page
    assert "&lt;img src=x onerror=alert(1)&gt;" in page
    # в встроенном JSON нет закрывающего тега скрипта
    data = page.split('id="report-data">', 1)[1].split("</script>", 1)[0]
    assert "<" not in data
    assert json.loads(data)["findings"][0]["problem"].startswith("</script>")


def test_find_span_normalizes_quotes_and_spaces():
    text = "Поле «Порог, ₸» и кнопка  «Сохранить»."
    assert H.find_span(text, 'Поле "Порог, ₸" и кнопка "Сохранить"') == (0, len(text) - 1)
    assert H.find_span(text, "нет такого") is None


def test_simple_view_strips_markdown(view):
    assert view["lines"][36]["text"].startswith("Ф-1. Держатель")
    assert view["lines"][62]["text"].startswith("Расходы 48 500 ₸, порог 50 000 ₸ | Провести")
    assert view["lines"][60]["text"] == "" or "|" not in view["lines"][61]["text"].replace(" | ", "")
    assert len(view["lines"]) == 198


def test_cli_writes_file(tmp_path):
    out = tmp_path / "r.html"
    assert H.main([str(SAMPLE), "--doc", str(DOC), "-o", str(out)]) == 0
    assert out.read_text(encoding="utf-8").count('class="card ') == len(json.loads(SAMPLE.read_text("utf-8"))["findings"])


@pytest.mark.skipif(not shutil.which("node"), reason="нет node")
def test_js_syntax():
    js = Path(H.ASSETS / "report.js")
    subprocess.run(["node", "--check", str(js)], check=True)
