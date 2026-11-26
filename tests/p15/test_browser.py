"""Сквозной путь в настоящем браузере (Chromium через Node Playwright).

Пропускается, если на машине нет node или пакета playwright. Скриншоты шагов
сохраняются в ``$P15_SHOTS`` (по умолчанию — во временный каталог теста).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from bcc_review.web.service import Settings

from .conftest import CASE, CountingEngine

HERE = Path(__file__).parent


def _node_env() -> dict[str, str] | None:
    node = shutil.which("node")
    npm = shutil.which("npm")
    if not node:
        return None
    env = dict(os.environ)
    if npm:
        root = subprocess.run([npm, "root", "-g"], capture_output=True, text=True).stdout.strip()
        if root:
            env["NODE_PATH"] = os.pathsep.join(filter(None, [env.get("NODE_PATH"), root]))
    probe = subprocess.run([node, "-e", "require.resolve('playwright')"], env=env, capture_output=True)
    return env if probe.returncode == 0 else None


def test_analyst_path_in_browser(make_server, tmp_path):
    env = _node_env()
    if env is None:
        pytest.skip("нет node + playwright")
    demo = tmp_path / "demo_answers.md"
    demo.write_text(
        "# Демонстрационные ответы команды\n\n## Ф-3, Ф-4\n"
        "Источник ответа: демонстрационный ответ команды (подготовлен для показа жюри 26.11.2026; не решение банка)\n"
        "Ответ:\nПриоритет Ф-4: смена порога открывает право на новый push в том же месяце; Ф-3 дополнить исключением.\n",
        encoding="utf-8",
    )
    engine = CountingEngine(delay=0.1)
    client = make_server(engine, settings=Settings(demo_answers=demo))
    out = Path(os.environ.get("P15_SHOTS") or tmp_path / "shots")
    out.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        ["node", str(HERE / "e2e_browser.js"), client.base, str(CASE), str(out)],
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )
    last = (proc.stdout.strip().splitlines() or ["{}"])[-1]
    result = json.loads(last)
    assert proc.returncode == 0, result.get("error") or proc.stderr
    # Двойной клик по «Подтвердить» дал ровно один дочерний запуск.
    store = client.app.store
    children = store.children(result["parent"])
    assert [c["run_id"] for c in children] == [result["child"]]
    revision_calls = [c for c in engine.calls if c["options"].get("compare_path")]
    assert len(revision_calls) == 1
    # Скачанный в браузере файл совпадает с файлом, который записал движок.
    assert Path(result["downloaded"]).read_bytes() == store.report_md(result["child"]).read_bytes()
    assert len(result["log"]) >= 20
