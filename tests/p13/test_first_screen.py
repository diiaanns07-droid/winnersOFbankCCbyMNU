"""Первый экран аналитика: два HTML из одной версии генератора (команда ``tests/p13/first_screen.py``).

* ``requirements_pdf.html`` — реальный офлайн-отчёт релиза (partial): статус, причина и оба вывода
  о готовности на первом экране при 390 и 1280 px, с JavaScript и без;
* ``conflict_same_amount.html`` — записанный прогон движка с критичным конфликтом: переход к обеим
  цитатам и возврат к той же карточке мышью и с клавиатуры; одинаковые суммы не ведут к первому
  вхождению; без JavaScript читаются вердикт и цитаты.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

import first_screen as FS
from bcc_review.exports import html as H
from test_html_browser import _node_env

HERE = Path(__file__).resolve().parent
SCRIPT = HERE / "browser" / "first_screen.cjs"

pytestmark = pytest.mark.skipif(not FS.RELEASE_JSON.is_file(), reason="нет release/reports/offline/requirements_pdf.json")


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    out = tmp_path_factory.mktemp("p13-first-screen")
    return out, FS.build(out)


def _ids(html: str) -> set[str]:
    return set(re.findall(r'\sid="([^"]+)"', html))


def test_one_command_two_html_one_generator(built):
    out, manifest = built
    metas = []
    for item in manifest["outputs"].values():
        html = Path(item["html"]).read_text(encoding="utf-8")
        metas.append(re.search(r'name="bcc-review:generator-sha256" content="([0-9a-f]{64})"', html).group(1))
        ids = _ids(html)
        missing = [a for a in item["anchors"] if a[1:] not in ids]
        assert not missing, missing
    assert metas[0] == metas[1] == manifest["generator_sha256"] == H.generator_fingerprint()
    assert (out / "first-screen.json").is_file()


def test_release_report_first_screen_markup(built):
    _, manifest = built
    html = Path(manifest["outputs"]["requirements_pdf"]["html"]).read_text(encoding="utf-8")
    rep = json.loads(FS.RELEASE_JSON.read_text(encoding="utf-8"))
    assert rep["run"]["status"] == "partial"
    # Порядок в DOM: оба вывода, затем статус прогона — до первых действий и рабочей области.
    pos = [html.index(f'id="{a}"') for a in ("verdict-development", "verdict-testing", "run-state", "first-actions", "workspace")]
    assert pos == sorted(pos)
    state = html[html.index('id="run-state"') : html.index('id="first-actions"')]
    assert "status: partial" in state and "Прогон неполный" in state
    assert "модель не вызывалась: режим --offline-lint (только детерминированные правила) — этапы: individual, cross, verify_meaning" in state
    assert state.count("<li>") == len(rep["run"]["status_reasons"]) + 1 + len(rep["warnings"])  # все причины в <details>
    tiles = html[html.index('id="verdict-development"') : html.index('id="run-state"')]
    assert tiles.count("Не определено") == 2
    assert "Без полной проверки нельзя утверждать, что разработку можно начинать." in tiles


def test_recorded_example_is_valid_and_verified():
    contracts = pytest.importorskip("bcc_review.contracts")
    rep = json.loads(FS.EXAMPLE_JSON.read_text(encoding="utf-8"))
    contracts.validate(rep)
    assert contracts.evidence_errors(rep) == []
    assert rep["document"]["id"] == contracts.sha256_file(FS.EXAMPLE_MD)
    crit = [f for f in rep["findings"] if f["severity"] == "critical"]
    assert len(crit) == 1 and crit[0]["kind"] == "conflict" and crit[0]["status"] == "confirmed"
    w = crit[0]["witness"]
    assert w["evidence_a"]["block_id"] != w["evidence_b"]["block_id"]
    assert w["evidence_a"]["quote"].split(" | ")[0] == w["evidence_b"]["quote"].split(" | ")[0] == "Порог 50 000 ₸, расходы 50 000 ₸"
    assert {k: rep["verdict"][k]["status"] for k in ("development", "testing")} == {"development": "not_ready", "testing": "not_ready"}
    cli = pytest.importorskip("bcc_review.cli")
    assert cli.main(["verify", str(FS.EXAMPLE_JSON), str(FS.EXAMPLE_MD)]) == contracts.EXIT_OK


def test_recorded_example_reproduced_by_engine():
    pytest.importorskip("bcc_review.engine")
    with tempfile.TemporaryDirectory() as tmp:
        env = dict(os.environ, BCC_FORCE_FALLBACK="review_individual,review_set")
        out = Path(tmp) / "x.md"
        subprocess.run([sys.executable, "-m", "bcc_review", str(FS.EXAMPLE_MD), str(out), "--provider", "mock",
                        "--mock-script", str(FS.EXAMPLE_MOCK), "--no-cache", "-q"], env=env, check=True, cwd=str(FS.ROOT))
        fresh = json.loads(out.with_suffix(".json").read_text(encoding="utf-8"))
    rec = json.loads(FS.EXAMPLE_JSON.read_text(encoding="utf-8"))

    def key(r):
        return {
            "doc": r["document"]["id"],
            "status": r["run"]["status"],
            "verdict": {k: (r["verdict"][k]["status"], r["verdict"][k]["finding_ids"]) for k in ("development", "testing")},
            "findings": [(f["id"], f["severity"], f["kind"], f["status"], f["evidence"], f.get("witness")) for f in r["findings"]],
        }

    assert key(fresh) == key(rec)


def test_first_screen_in_browser(built):
    out, _ = built
    env = _node_env()
    if env is None:
        pytest.skip("нет node или пакета playwright для Node")
    proc = subprocess.run(["node", str(SCRIPT), str(out)], env=env, capture_output=True, text=True, timeout=600)
    results_file = out / "first-screen-results.json"
    assert results_file.is_file(), proc.stdout + proc.stderr
    results = json.loads(results_file.read_text(encoding="utf-8"))
    failed = [r for r in results if not r["ok"]]
    assert len(results) == 12, proc.stdout
    assert not failed, "\n\n".join(f"{r['name']}\n{r['details']}" for r in failed)
