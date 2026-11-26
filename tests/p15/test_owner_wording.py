"""Ответ владельца → изменённый пункт: стык с №08 (target + «Формулировка») и надписи сценария.

Малая фикстура: dev-движок, обёрнутый так, как ведёт себя опубликованный №08 в bcc/integration
(вопрос несёт ``target``, варианты начинаются с буквы «A. …», ответ с «Формулировка: …»
заменяет предложение с целью и попадает в ``decisions[].edits``). Сквозной прогон на настоящем
движке — test_demo_path_on_standard_launch (пропускается без №08).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from bcc_review.web import devengine
from bcc_review.web.answers import parse_answers
from bcc_review.web.engine import EngineSpec

from .conftest import CASE, ROOT

WORDING = "В расходы входят проведённые покупки; месяц покупки определяется по дате её совершения (Asia/Almaty, UTC+5)."
TARGET = "В расходы входят проведённые покупки."


def p08_like(input_path, report_md, *, options=None):
    """dev-движок + поведение №08: target у вопроса, буквенные варианты, «Формулировка» → правка."""
    opts = dict(options or {})
    answers_path = opts.pop("answers_path", None)
    wording = {}
    if answers_path:
        wording = {a.qid: a.wording for a in parse_answers(Path(answers_path).read_text(encoding="utf-8")).answers if a.wording}
    src = Path(input_path)
    text = src.read_text(encoding="utf-8")
    edits = []
    for qid, new in wording.items():
        if TARGET in text:
            text = text.replace(TARGET, new, 1)
            edits.append((qid, new))
    reviewed = src
    if edits:
        reviewed = Path(report_md).parent / f"{src.stem}.rev-{opts.get('run_id', 'x')[:16]}{src.suffix}"
        reviewed.write_text(text, encoding="utf-8")
    report = devengine.run_review(reviewed, report_md, options={**opts, "dev_delay": 0})
    blocks = report["document"]["blocks"]
    tb = next(b for b in blocks if TARGET in b["text"] or (edits and edits[0][1] in b["text"]))
    i = tb["text"].find(TARGET)
    for q in report["questions"]:
        q["options"] = [f"{'AB'[n]}. {o}" for n, o in enumerate(q["options"][:2])]
        if i >= 0:
            q["target"] = {"block_id": tb["id"], "start": i, "end": i + len(TARGET), "quote": TARGET}
    report["decisions"] = [{"question_id": qid, "source_sha256": report["run"]["source_sha256"], "answer": "",
                            "edits": [{"block_id": tb["id"], "start": 0, "end": 0, "old": TARGET, "new": new}]} for qid, new in edits]
    Path(report_md).with_suffix(".json").write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
    return report


def test_owner_wording_reaches_engine_and_changed_clause_is_shown(make_server):
    from bcc_review.web.service import Settings

    client = make_server(EngineSpec("shared", "p08-like", p08_like), settings=Settings(provider="mock"))
    r1 = client.wait(client.upload("case_ab.md", CASE.read_bytes())["run_id"])
    page = client.get(f"/runs/{r1['run_id']}")[2].decode()
    # Цель №08 показана, поле — «Новая формулировка», пара «было → стало» не предлагается.
    assert "Движок заменит предложение с выделенным фрагментом (строка 38)" in page
    assert f"<mark>{TARGET}</mark>" in page and 'name="w_Q-01"' in page and 'name="eo_Q-01"' not in page
    # Варианты №08 без второй нумерации («1. A. …»).
    assert re.search(r'value="1"[^>]*> A\. ', page) and " 1. A. " not in page
    code, _, body = client.post_form(f"/runs/{r1['run_id']}/revisions", {"a_Q-01": "По дате совершения", "w_Q-01": WORDING})
    assert code == 201, body
    r2 = client.wait(json.loads(body)["run_id"])
    sent = (client.app.store.input_dir(r2["run_id"]) / "answers.md").read_text(encoding="utf-8")
    assert f"Формулировка: {WORDING}" in sent and "Правка:" not in sent
    page2 = client.get(f"/runs/{r2['run_id']}")[2].decode()
    assert 'id="changes"' in page2 and f"было: «{TARGET}»" in page2 and f"стало: «{WORDING}»" in page2
    assert f"<mark>{WORDING}</mark>" in page2  # пункт целиком, новая часть выделена
    # Прежняя ссылка: сразу видно, что версия не актуальная и данные — её собственные.
    old = client.get(f"/runs/{r1['run_id']}")[2].decode()
    assert 'id="not-latest"' in old and f'href="/runs/{r2["run_id"]}"' in old
    assert old.index('id="not-latest"') < old.index('id="status"')


def test_mode_and_passport_labels_are_accurate(make_server, tmp_path):
    from bcc_review.web.service import Settings

    script = tmp_path / "recorded.json"
    script.write_text("{}", encoding="utf-8")
    client = make_server(EngineSpec("shared", "p08-like", p08_like), settings=Settings(provider="mock", mock_script=script))
    home = client.get("/")[2].decode()
    assert "ответы модели воспроизводятся из записанного сценария recorded.json" in home and "живая модель не вызывается" in home
    st = client.wait(client.upload("case_ab.md", CASE.read_bytes())["run_id"])
    page = client.get(f"/runs/{st['run_id']}")[2].decode()
    assert "не переданы (нет в RunOptions движка): <code>progress, tmp_dir</code>" in page
    assert "не приняты движком" not in page


def _node_env():
    node, npm = shutil.which("node"), shutil.which("npm")
    if not node:
        return None
    env = dict(os.environ)
    if npm:
        env["NODE_PATH"] = os.pathsep.join(filter(None, [env.get("NODE_PATH"), subprocess.run([npm, "root", "-g"], capture_output=True, text=True).stdout.strip()]))
    return env if subprocess.run([node, "-e", "require.resolve('playwright')"], env=env, capture_output=True).returncode == 0 else None


def test_demo_path_on_standard_launch(tmp_path):
    """Сквозной путь аналитика: python -m bcc_review.web + браузер + настоящий run_review (mock-сценарий)."""
    env = _node_env()
    if env is None:
        pytest.skip("нет node + playwright")
    pytest.importorskip("pymupdf", reason="экспорт PDF №14 требует pymupdf")
    import importlib.util

    if importlib.util.find_spec("bcc_review.decisions") is None:
        pytest.skip("движок без №08 (нужен bcc/integration 2821989+)")
    out = Path(os.environ.get("P15_SHOTS") or tmp_path / "demo")
    proc = subprocess.run([sys.executable, str(ROOT / "tests" / "p15" / "demo_run.py"), "--out", str(out), "--port", "8131"],
                          capture_output=True, text=True, timeout=600)
    result = json.loads(proc.stdout[proc.stdout.index("{"):])
    assert proc.returncode == 0, result.get("error")
    assert result["engine_calls"] == 2 and len(result["frames"]) == 6
    assert all(c["status_page"] == c["status_api"] and c["questions_md_sha256"] == c["document_sha256"] for c in result["checks"])
    assert result["revision_file"]["sha256"] == result["checks"][1]["document_sha256"]
