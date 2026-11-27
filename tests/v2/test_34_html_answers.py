"""№34: HTML-отчёт — вкладка ответов, «до и после» (расхождения, отложенное, следующий круг), устойчивость k/N.

Python-часть проверяет разметку; сквозная часть (если есть node и playwright) открывает страницу в Chromium без
сети, заполняет ответы, берёт файл ответов из страницы и разбирает его ``recheck.parse_answers_text`` — тем же
кодом, которым агент читает ``--answers``.
"""
from __future__ import annotations

import copy
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from bcc_review.v2.render import html as H
from bcc_review.v2.stages.recheck import parse_answers_text, render_next_answers

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / "release" / "input" / "requirements.md"
SAMPLE = ROOT / "tests" / "v2" / "fixtures" / "14_report_official.json"
JS = ROOT / "tests" / "v2" / "fixtures" / "34_answers_roundtrip.js"

TOPICS = ["Лимит уведомлений [в месяц] и смена порога", "Дата отнесения покупки", "Код ответа при ошибке суммы",
          "Метод чтения настроек", "Единица хранения сумм"]


def _base() -> dict:
    r = json.loads(SAMPLE.read_text(encoding="utf-8"))
    for q, t in zip(r["questions"], TOPICS):
        q["topic"] = t
        q["if_no_answer"] = f"{q['finding_ids'][0] if q.get('finding_ids') else 'дефект'} остаётся открытым"
    return r


def _with_answers(r: dict) -> dict:
    r = copy.deepcopy(r)
    q = r["questions"]
    r["clarification"] = {
        "answers": [
            {"question_id": "Q-01", "topic": q[0]["topic"], "choice": "A", "answer": q[0]["options"][0],
             "replies": [{"label": "Q-01.1", "choice": "A", "text": q[0]["options"][0]}], "finding_ids": q[0]["finding_ids"]},
            {"question_id": "Q-02", "topic": q[1]["topic"], "choice": "", "answer": "Q-02.1: месяц покупки / Q-02.2: месяц проведения",
             "replies": [{"label": "Q-02.1", "text": "месяц покупки"}, {"label": "Q-02.2", "text": "месяц проведения"}],
             "finding_ids": q[1]["finding_ids"]},
        ],
        "decisions": ["Все суммы в API — в тиынах"], "unanswered": ["Q-04", "Q-05"], "closed_by_decisions": ["Q-05"],
        "postponed": [{"question_id": "Q-03", "text": "Не знаю, решим после встречи команд", "partial": False}],
        "changes": [], "new_findings": [],
        "answer_conflicts": [{"finding_id": q[1]["finding_ids"][0], "answers": ["Q-02.1", "Q-02.2"],
                              "reason": "месяц покупки и месяц проведения дают разные счётчики",
                              "texts": {"Q-02.1": "месяц покупки", "Q-02.2": "месяц проведения"}}],
        "before": {"verdict": {"development": "no", "testing": "no"}, "findings": {"critical": 3, "major": 5, "minor": 2}},
        "after": {"verdict": {"development": "conditional", "testing": "no"}, "findings": {"critical": 1, "major": 5, "minor": 2}},
        "resolved": 2, "changed": 0, "open": 1, "warnings": [], "status": "ok",
        "next_round": [
            {"kind": "conflict", "finding_id": q[1]["finding_ids"][0], "question_id": "Q-02",
             "lines": [f"Q-02 [{q[1]['topic']}]: месяц покупки", f"Q-02 [{q[1]['topic']}]: месяц проведения"]},
            {"kind": "postponed", "finding_id": ", ".join(q[2]["finding_ids"]), "question_id": "Q-03",
             "lines": [f"Q-03 [{q[2]['topic']}]: <решите: Каким кодом отклоняется сумма>"]},
            {"kind": "unanswered", "finding_id": ", ".join(q[3]["finding_ids"]), "question_id": "Q-04", "lines": [],
             "note": "Каким методом читать настройки?", "head": f"Q-04 [{q[3]['topic']}]:"},
        ],
    }
    return r


def _with_stability(r: dict) -> dict:
    r = copy.deepcopy(r)
    for i, f in enumerate(r["findings"]):
        f["stability"] = {"k": 3 if i % 3 else 2, "n": 3, "passes": [1, 2, 3] if i % 3 else [1, 3]}
    unstable = copy.deepcopy(r["findings"][0])
    unstable.update(id="U-01", title="Редкий дефект: только в одном проходе", stability={"k": 1, "n": 3, "passes": [2]})
    r["findings_unstable"] = [unstable]
    r["stability"] = {"runs_requested": 3, "runs_counted": 3, "threshold": 2,
                      "rule": "в реестре — дефекты, найденные не меньше чем в 2 из 3 проходов",
                      "passes": [{"pass": i, "run_id": f"run-{i}", "status": "complete", "findings": 20, "calls": 9}
                                 for i in (1, 2, 3)], "kept": 20, "unstable": 1, "added_from_other_passes": 0}
    return r


@pytest.fixture(scope="module")
def view() -> dict:
    return H.load_view(DOC)


def _tab_names(page: str) -> list[str]:
    return re.findall(r'data-tab="([a-z]+)"', page)


def test_questions_tab_has_if_no_answer_upload_and_decisions(view):
    page = H.render_html(_base(), view)
    assert page.count('class="ifno"') == 5 and "Если ответа не будет:" in page
    assert 'id="ulanswers"' in page and 'id="dlanswers"' in page and 'id="decisions"' in page
    assert 'data-topic="Лимит уведомлений [в месяц] и смена порога"' in page
    # без ответов: ни вкладки «До и после», ни встроенного файла следующего круга
    assert "clarify" not in _tab_names(page) and 'id="next-answers"' not in page


def test_clarify_shows_conflicts_postponed_closed_and_next_round(view):
    r = _with_answers(_base())
    page = H.render_html(r, view)
    assert "clarify" in _tab_names(page)
    panel = page[page.index('id="p-clarify"'):page.index('id="p-tests"')]
    assert "Ответы расходятся — выберите один" in panel and "месяц проведения" in panel
    assert "Решение отложено" in panel and "Не знаю, решим после встречи команд" in panel
    assert "Закрыто общими решениями" in panel and "Q-05" in panel
    assert "Следующий круг" in panel and 'id="dlnext"' in panel and 'id="loadnext"' in panel
    assert "отложено" in panel and "без ответа" in panel and "ответы расходятся" in panel


def test_next_round_file_is_embedded_exactly(view):
    r = _with_answers(_base())
    page = H.render_html(r, view)
    m = re.search(r'<script type="application/json" id="next-answers">(.*?)</script>', page, re.S)
    assert m
    text = json.loads(m.group(1))
    assert text == render_next_answers(r["clarification"], document="requirements.md")
    assert "<решите:" in text and "## Уже согласовано" in text and "## Решения" in text
    # файл следующего круга разбирается тем же кодом, что --answers: расхождение — две строки на Q-02
    parsed = parse_answers_text(text)
    assert [a["id"] for a in parsed["answers"]].count("Q-02") == 2
    assert parsed["decisions"] == ["Все суммы в API — в тиынах"]


def test_embedded_next_round_cannot_break_out_of_script(view):
    r = _with_answers(_base())
    r["clarification"]["decisions"] = ["</script><script>alert(1)</script>"]
    page = H.render_html(r, view)
    m = re.search(r'id="next-answers">(.*?)</script>', page, re.S)
    assert m and "<" not in m.group(1) and "alert(1)" in json.loads(m.group(1))


def test_stability_chip_tab_sort_and_passport(view):
    page = H.render_html(_with_stability(_base()), view)
    assert page.count("устойчивость 3/3") >= 10 and "устойчивость 2/3" in page
    assert 'data-stab="1.000"' in page and 'value="stab"' in page
    assert "unstable" in _tab_names(page)
    panel = page[page.index('id="p-unstable"'):page.index('id="p-rejected"')]
    assert "Редкий дефект: только в одном проходе" in panel and "устойчивость 1/3" in panel
    assert "Устойчивость: 3 независимых прохода" in page and "Проходы устойчивости" in page and "run-2" in page


def test_no_stability_no_chips(view):
    page = H.render_html(_base(), view)
    assert "chip stab" not in page and "Устойчивость:" not in page
    assert 'value="stab"' not in page and "unstable" not in _tab_names(page)


def test_bad_stability_values_are_ignored(view):
    r = _base()
    r["findings"][0]["stability"] = {"k": 5, "n": 3}
    r["findings"][1]["stability"] = {"k": "3", "n": 3}
    r["findings"][2]["stability"] = "3/3"
    page = H.render_html(r, view)
    assert "chip stab" not in page


def test_still_single_file_offline(view):
    page = H.render_html(_with_stability(_with_answers(_base())), view)
    assert not re.search(r"<script[^>]+src=", page)
    assert not re.search(r"""<(?:link|img|iframe)[^>]+(?:href|src)=["']?(?:https?:)?//""", page)
    assert "window.bccReport" in page


# ── сквозной тест в браузере: файл ответов из страницы → parse_answers_text ──

def _playwright_ok() -> bool:
    node = shutil.which("node")
    if not node:
        return False
    r = subprocess.run([node, "-e", "require('playwright')"], capture_output=True, text=True)
    return r.returncode == 0


@pytest.mark.skipif(not _playwright_ok(), reason="нет node или playwright")
def test_browser_roundtrip_answers_file(tmp_path, view):
    r = _with_answers(_base())
    html_path = tmp_path / "report.html"
    html_path.write_text(H.render_html(r, view), encoding="utf-8")
    plan = {
        "fill": [
            {"q": 0, "radio": 1, "text": ""},                       # буква
            {"q": 1, "radio": 0, "text": "с оговоркой:\nпо Алматы"},  # буква + оговорка (перевод строки → пробел)
            {"q": 2, "radio": -1, "text": "B. Свой ответ, похожий на букву"},  # свой текст, не вариант B
            {"q": 3, "radio": -1, "text": "Не знаю"},                # отложенный ответ — остаётся словами
        ],
        "decisions": "Все суммы — в тиынах\n\nПорог — целые тенге",
        "load": render_next_answers(r["clarification"], document="requirements.md"),
    }
    (tmp_path / "plan.json").write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
    out = subprocess.run([shutil.which("node"), str(JS), str(html_path), str(tmp_path / "plan.json")],
                         capture_output=True, text=True, timeout=120, cwd=str(tmp_path))
    assert out.returncode == 0, out.stderr[-2000:]
    res = json.loads(out.stdout)
    assert res["errors"] == [] and res["requests"] == []

    parsed = parse_answers_text(res["text"])
    by_id = {a["id"]: a for a in parsed["answers"]}
    assert set(by_id) == {"Q-01", "Q-02", "Q-03", "Q-04"}
    assert by_id["Q-01"]["choice"] == 1 and not by_id["Q-01"]["text"]
    assert by_id["Q-02"]["choice"] == 0 and by_id["Q-02"]["comment"] == "с оговоркой: по Алматы"
    assert by_id["Q-03"]["choice"] is None and "Свой ответ, похожий на букву" in by_id["Q-03"]["text"]
    assert by_id["Q-04"]["choice"] is None and not by_id["Q-04"]["text"]  # «не знаю» — не ответ, как у агента
    # тема в скобках — та, что у вопроса (вложенные [ ] заменены на круглые, иначе строка не разобралась бы)
    assert by_id["Q-01"]["topic_hint"] == "Лимит уведомлений (в месяц) и смена порога"
    assert parsed["decisions"] == ["Все суммы — в тиынах", "Порог — целые тенге"]
    assert "unparsed" not in parsed
    assert res["count"] == "Отвечено: 4 из 5"

    # загрузка файла следующего круга: согласованное встало, расхождение и «решите» подсвечены
    ld = res["load"]
    assert ld["conflicts"] == 1 and ld["todo"] == 1 and ld["decisions"] == 1 and ld["unmatched"] == []
    assert res["states_after_load"][0] == "есть ответ"
    assert res["states_after_load"][1] == "расхождение" and res["states_after_load"][2] == "нужно решить"
    assert res["checked_after_load"][0] == 0  # Q-01: вариант A из «Уже согласовано»


def test_passport_shows_replay_cost_limit_and_incomplete(view):
    r = _base()
    r["run"]["replay"] = {"from": "runs/abc", "run_id": "abc", "calls_replayed": 9, "calls_live": 0}
    r["run"]["cost_limit"] = {"max_cost_usd": 0.5, "spent_usd": 0.52, "max_tokens": None, "spent_tokens": 1000, "hit": True}
    r["run"]["incomplete_stages"] = ["judge", "lens_qa"]
    page = H.render_html(r, view)
    panel = page[page.index('id="p-passport"'):]
    assert "Повтор прогона" in panel and "живых вызовов 0" in panel
    assert "потолок $0.50, потрачено $0.52" in panel and "потолок достигнут" in panel
    assert "Не завершены этапы" in panel and "Судья" in panel and "Линза «Тестировщик»" in panel
