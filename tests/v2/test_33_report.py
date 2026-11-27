"""№33: релизные ошибки Markdown-отчёта — таблицы, ссылки, повторяемость (файлы №13)."""

from __future__ import annotations

import copy
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from bcc_review.v2.render import markdown  # noqa: E402

SAMPLE = ROOT / "tests" / "v2" / "fixtures" / "13_report_sample.json"


@pytest.fixture()
def sample() -> dict:
    return json.loads(SAMPLE.read_text(encoding="utf-8"))


def _cells(row: str) -> int:
    """Число ячеек строки таблицы так, как их режет GitHub (cmark-gfm): «\\x» — один символ, «|» — граница."""
    s = row.strip()
    s = s[1:] if s.startswith("|") else s
    n, i, last_bar = 1, 0, False
    while i < len(s):
        last_bar = False
        if s[i] == "\\" and i + 1 < len(s):
            i += 2
            continue
        if s[i] == "|":
            n += 1
            last_bar = True
        i += 1
    return n - 1 if last_bar else n


def broken_rows(md: str) -> list[str]:
    lines = md.splitlines()
    bad, i = [], 0
    while i + 1 < len(lines):
        if lines[i].startswith("|") and re.match(r"^\|\s*:?-{3}", lines[i + 1]):
            n, j = _cells(lines[i]), i + 2
            while j < len(lines) and lines[j].startswith("|"):
                if _cells(lines[j]) != n:
                    bad.append(lines[j])
                j += 1
            i = j
        else:
            i += 1
    return bad


def _anchors_and_links(md: str) -> tuple[set[str], set[str]]:
    """Якоря отчёта и цели ссылок «](#…)» вне `кода` и без экранирования «]\\(»."""
    anchors = set(re.findall(r'<a id="([^"]+)"></a>', md))
    text = re.sub(r"`[^`]*`", "", md)
    links = set(re.findall(r"(?<!\\)\]\(#([^)\s\"]+)", text))
    return anchors, links


def test_table_with_escaped_pipe_from_document_keeps_columns(sample):
    """В Markdown-документе банка «|» в ячейке уже записан как «\\|» (так выгружает pandoc); цитата и формулировка
    модели несут «\\|» дальше. Раньше `cell()` давал «\\\\|» — GitHub резал ячейку, столбцы таблицы ехали."""
    r = copy.deepcopy(sample)
    for req in r["requirements"][:5]:
        req["summary"] = "Поле result: OK \\| ERROR"
        req["quote"] = "result \\| string \\| OK / ERROR"
    for f in r["findings"][:5]:
        f["title"] = "Статус OK \\| ERROR не описан"
        f["recommendation"] = "Описать значения OK \\| ERROR и | разделитель"
    md = markdown.render(r)
    assert broken_rows(md) == []
    assert "OK \\\\\\| ERROR" in md  # «\» документа виден читателю, черта экранирована


def test_newline_and_bare_pipe_in_any_cell_do_not_break_tables(sample):
    r = copy.deepcopy(sample)
    r["document"]["title"] = "ТЗ | версия 2"
    for f in r["findings"]:
        for ev in f.get("evidence") or []:
            ev["section"] = "Часть A | Требования\nк системе"
    md = markdown.render(r)
    assert broken_rows(md) == []


def test_markdown_link_in_model_or_document_text_is_not_a_link(sample):
    """Ссылки на якоря ставит только код: «[Ф-3](#ф-3)» модели или «[АБС](#абс)» заголовка документа не должны
    стать ссылкой в никуда."""
    r = copy.deepcopy(sample)
    r["findings"][0]["problem"] = "См. [Ф-3](#ф-3) и [вики](https://wiki.example/x)."
    r["findings"][0]["evidence"][0]["section"] = "Интеграция с [АБС](#абс)"
    r["document"]["title"] = "Расходы [черновик](#draft)"
    md = markdown.render(r)
    anchors, links = _anchors_and_links(md)
    assert links - anchors == set()
    assert "[Ф-3]\\(#ф-3)" in md
    # в выгрузке для Word экранирование снято
    assert "[Ф-3](#ф-3)" in markdown.export_text(md)


def test_all_internal_links_resolve(sample):
    md = markdown.render(sample)
    anchors, links = _anchors_and_links(md)
    assert links and links - anchors == set()


def test_same_markdown_under_different_hash_seeds():
    """Один и тот же report.json → один и тот же Markdown при любом PYTHONHASHSEED (порядок множеств)."""
    code = ("import json,sys;sys.path.insert(0,'src');from bcc_review.v2.render import markdown;"
            f"sys.stdout.write(markdown.render(json.load(open({str(SAMPLE)!r},encoding='utf-8'))))")
    outs = {subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=ROOT,
                           env=dict(os.environ, PYTHONHASHSEED=seed), check=True).stdout for seed in ("0", "1", "777")}
    assert len(outs) == 1


def test_stage_warnings_read_as_russian_sentences():
    """Паспорт и терминал: судья пишет repr заголовка, обрезанного на 60 знаков, и «понижен до major»."""
    from bcc_review.v2.render import console

    judge = ("судья: 'Событие «проведённые покупки» не выбрано: авторизация или кл' понижен до major "
             "(критичный подтвердил только один ревьюер)")
    clar = "clarify: вопрос «Где клиент заполняет анкету здоровья для страхования, какие » отброшен — повтор"
    for out in (markdown.warn_text(judge), console.plain_warn(judge)):
        assert "«Событие «проведённые покупки» не выбрано: авторизация или…» понижен до существенного" in out
        assert "'" not in out
    for out in (markdown.warn_text(clar), console.plain_warn(clar)):
        assert "«Где клиент заполняет анкету здоровья для страхования, какие…» отброшен" in out
    assert "«Короткий?» отброшен" in markdown.warn_text("clarify: вопрос «Короткий?» отброшен — повтор")


def test_passport_commands_use_paths_from_command_line(sample):
    """Паспорт: команды проверки и повтора можно скопировать и выполнить — пути те, что указали при запуске
    (раньше «verify отчёт.json requirements.md»: такого файла нет, документ лежит в другой папке)."""
    md = markdown.render(sample, out_path="reports/requirements.md", doc_path="release/input/requirements.md")
    assert "`python -m bcc_review verify reports/requirements.json release/input/requirements.md`" in md
    # абсолютные пути машины в отчёт не попадают — только имена файлов
    md = markdown.render(sample, out_path="/home/u/Мои документы/r.md", doc_path="/home/u/ТЗ/requirements.md")
    assert "/home/u" not in md and "verify r.json requirements.md" in md
    # без путей — как раньше
    assert "verify отчёт.json requirements.md" in markdown.render(sample)


def test_written_passport_uses_cli_paths(sample, tmp_path, monkeypatch):
    from bcc_review.v2.pipeline import write_outputs

    monkeypatch.chdir(tmp_path)
    report_path = Path("reports/result.md")
    write_outputs(sample, None, Path("sources/requirements.md"), report_path, {"html": False})
    assert "verify reports/result.json sources/requirements.md" in report_path.read_text(encoding="utf-8")
