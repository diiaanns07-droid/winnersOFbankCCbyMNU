"""№34: выгрузка для Confluence — вики-разметка («Вставить → Разметка → Confluence wiki»)."""
from __future__ import annotations

import copy
import json
import re
from pathlib import Path

from bcc_review.v2.render import confluence as C

ROOT = Path(__file__).resolve().parents[2]
SAMPLE = ROOT / "tests" / "v2" / "fixtures" / "14_report_official.json"


def _report() -> dict:
    return json.loads(SAMPLE.read_text(encoding="utf-8"))


def _table_rows(text: str, header_start: str) -> list[str]:
    lines = text.splitlines()
    i = next(k for k, ln in enumerate(lines) if ln.startswith(header_start))
    out = []
    for ln in lines[i + 1:]:
        if not ln.startswith("|"):
            break
        out.append(ln)
    return out


def _cells(row: str) -> list[str]:
    # ячейки: «|» без обратной косой перед ним (экранированные «\|» — текст); «|» внутри {status:…} — параметры макроса
    body = re.sub(r"\{status:[^}]*\}", "STATUS", row)
    return re.split(r"(?<!\\)\|", body)[1:-1]


def test_every_finding_once_in_table_and_details():
    r = _report()
    text = C.render_wiki(r)
    rows = _table_rows(text, "||ID||Серьёзность||")
    assert len(rows) == len(r["findings"])
    for f, row in zip(r["findings"], rows):
        assert f"*{f['id']}*" in row
        assert len(_cells(row)) == 6, row[:200]
    assert text.count("{expand:title=") == len(r["findings"]) == text.count("{expand}")
    assert text.startswith("h1. Ревью требований: ")


def test_verdict_and_severity_status_macros():
    r = _report()
    text = C.render_wiki(r)
    crit = sum(1 for f in r["findings"] if f.get("severity") == "critical")
    assert text.count("{status:colour=Red|title=Критичный}") == crit
    assert "*Разработка:* {status:colour=" in text and "{panel:title=Можно ли начинать}" in text
    assert "h2. Паспорт прогона" in text and r["document"]["sha256"] in text


def test_document_text_cannot_break_markup():
    r = _report()
    f = r["findings"][0]
    f["title"] = "Колонка | разрыв {code} [ссылка] !картинка! *жирный* _курсив_ -зачёркнуто- ?? \\ путь"
    f["problem"] = "Строка 1\nСтрока 2\n\nh1. Заголовок из документа"
    f["evidence"][0]["quote"] = "{status:colour=Green|title=Можно}"
    text = C.render_wiki(r)
    row = _table_rows(text, "||ID||Серьёзность||")[0]
    assert len(_cells(row)) == 6
    assert "\\|" in row and "\\{code\\}" in row and "\\[ссылка\\]" in row and "\\!картинка\\!" in row
    assert "\\*жирный\\*" in row and "\\_курсив\\_" in row and "\\-зачёркнуто\\-" in row and "?\\?" in row
    assert "&#92;" in row and "\\\\ путь" not in row
    assert "Строка 1 \\\\ Строка 2 \\\\ h1. Заголовок" in row  # перевод строки — разрыв в ячейке, не новая строка
    assert not re.search(r"(?<!\\)\{status:colour=Green", text)  # макрос из цитаты экранирован
    assert "\\{status:colour=Green\\|title=Можно\\}" in text
    assert not any(ln.startswith("h1. Заголовок") for ln in text.splitlines())


def test_questions_with_if_no_answer_and_clarification():
    r = _report()
    for q in r["questions"]:
        q["topic"] = "Тема [вложенная]"
        q["if_no_answer"] = "дефект остаётся открытым"
    r["clarification"] = {
        "before": {"verdict": {"development": "no", "testing": "no"}, "findings": {"critical": 2, "major": 1, "minor": 0}},
        "after": {"verdict": {"development": "yes", "testing": "conditional"}, "findings": {"critical": 0, "major": 1, "minor": 0}},
        "answer_conflicts": [{"finding_id": "D-02", "answers": ["Q-02.1", "Q-02.2"], "reason": "разные месяцы",
                              "texts": {"Q-02.1": "месяц покупки", "Q-02.2": "месяц проведения"}}],
        "postponed": [{"question_id": "Q-03", "text": "Не знаю", "partial": False}],
    }
    text = C.render_wiki(r)
    rows = _table_rows(text, "||ID||Кому||Вопрос||")
    assert len(rows) == len(r["questions"]) and all(len(_cells(x)) == 6 for x in rows)
    assert "дефект остаётся открытым" in rows[0] and "Тема \\[вложенная\\]" in rows[0]
    assert "h2. До и после ответов владельца" in text and "{status:colour=Green|title=Можно}" in text
    assert "Q-02.1 «месяц покупки» ↔ Q-02.2 «месяц проведения»" in text and "{status:colour=Yellow|title=Отложено}" in text


def test_no_findings_and_offline_banner():
    r = copy.deepcopy(_report())
    r["findings"] = []
    r["run"]["provider"] = "offline"
    text = C.render_wiki(r)
    assert "Замечаний нет" in text and "{info}Проверка без модели" in text and "{expand" not in text


def test_cli_writes_next_to_report(tmp_path, capsys):
    src = tmp_path / "report.json"
    src.write_text(SAMPLE.read_text(encoding="utf-8"), encoding="utf-8")
    assert C.main([str(src)]) == 0
    out = tmp_path / "report.confluence.txt"
    assert out.is_file() and out.read_text(encoding="utf-8").startswith("h1. ")
    assert "Confluence (вики-разметка)" in capsys.readouterr().out
    assert C.main([str(tmp_path / "нет.json")]) == 2


def test_web_offers_confluence_file():
    from bcc_review.v2.web import runner as R
    assert {k: n for k, n, _, _ in R.FILES}["confluence"] == "report.confluence.txt"
