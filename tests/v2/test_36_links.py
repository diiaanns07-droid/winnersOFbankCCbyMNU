"""№36: ссылки в документах сдачи (README, SUBMISSION, reports/README, presentation/README) ведут на файлы в дереве.

Без сети и без модели. Разбор ссылок — на временных файлах; проверка самого репозитория — в конце.
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "check_links.py"

_spec = importlib.util.spec_from_file_location("check_links", SCRIPT)
check_links = importlib.util.module_from_spec(_spec)
sys.modules["check_links"] = check_links
_spec.loader.exec_module(check_links)

# Слайды делает №37 в своей ветке; их приносит тимлид при слиянии. Пока их нет — не считаются битыми,
# с BCC_RELEASE_CHECK=1 (проверка тега v2.0.0 и ветки release) проверяется всё.
PENDING_FROM_OTHERS = {"presentation/deck.pdf", "presentation/deck.pptx"}


def _write(root: Path, rel: str, text: str = "x") -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _targets(text: str) -> list[str]:
    return [t for _, t in check_links.extract_links(text)]


def test_extracts_inline_images_references_and_html():
    text = ("См. [отчёт](reports/a.md) и ![экран](img/a.png \"подпись\").\n"
            "[метка]: docs/b.md\n"
            '<img src="img/c.png"> <a href=\'d.md\'>d</a>\n'
            "[с пробелом](<my dir/e.md>) и [вложенный [x]](f.md)\n")
    assert _targets(text) == ["reports/a.md", "img/a.png", "docs/b.md", "img/c.png", "d.md", "<my dir/e.md>", "f.md"]


def test_skips_code_blocks_and_inline_code():
    text = ("```bash\n[не ссылка](a.md)\n```\n"
            "~~~~\n```\n[тоже](b.md)\n~~~~\n"
            "`[в строке](c.md)` и [настоящая](d.md)\n"
            "    ```\n")
    assert _targets(text) == ["d.md"]


def test_resolve_external_anchor_relative_root_and_escapes(tmp_path):
    src = _write(tmp_path, "reports/README.md")
    r = check_links.resolve
    assert r("https://github.com/x", src, tmp_path) is None
    assert r("mailto:a@b.c", src, tmp_path) is None
    assert r("#раздел", src, tmp_path) is None
    assert r("requirements.md#кратко", src, tmp_path) == "reports/requirements.md"
    assert r("../docs/task-analysis.md", src, tmp_path) == "docs/task-analysis.md"
    assert r("/SUBMISSION.md", src, tmp_path) == "SUBMISSION.md"
    assert r("<my%20dir/e.md>", src, tmp_path) == "reports/my dir/e.md"
    assert r("../../outside.md", src, tmp_path).startswith("../")


def test_check_reports_missing_and_accepts_existing_files_and_dirs(tmp_path):
    _write(tmp_path, "reports/a.md")
    (tmp_path / "evaluation" / "dev").mkdir(parents=True)
    readme = _write(tmp_path, "README.md", "[a](reports/a.md) [dev](evaluation/dev) [нет](reports/b.md)\n"
                                           "[внешняя](https://example.com/b.md) [якорь](#x)\n")
    links, problems = check_links.check([readme], tmp_path, use_git=False)
    assert [link.path for link in links] == ["reports/a.md", "evaluation/dev", "reports/b.md"]
    assert [(p.link.path, p.link.line) for p in problems] == [("reports/b.md", 1)]


def test_links_are_relative_to_the_file_that_contains_them(tmp_path):
    _write(tmp_path, "reports/requirements.md")
    _write(tmp_path, "docs/task-analysis.md")
    readme = _write(tmp_path, "reports/README.md", "[r](requirements.md) [t](../docs/task-analysis.md) "
                                                   "[корень](requirements.md/../../README.md)\n")
    _, problems = check_links.check([readme], tmp_path, use_git=False)
    assert [p.link.path for p in problems] == ["README.md"]


@pytest.mark.skipif(shutil.which("git") is None, reason="нет git")
def test_untracked_file_is_broken_for_github(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    _write(tmp_path, "reports/committed.md")
    _write(tmp_path, "reports/local_only.md")
    readme = _write(tmp_path, "README.md", "[1](reports/committed.md) [2](reports/local_only.md) [3](reports)\n")
    subprocess.run(["git", "-C", str(tmp_path), "add", "README.md", "reports/committed.md"], check=True)
    _, problems = check_links.check([readme], tmp_path, use_git=True)
    assert [(p.link.path, "не в git" in p.reason) for p in problems] == [("reports/local_only.md", True)]
    _, problems = check_links.check([readme], tmp_path, use_git=False)
    assert problems == []


def test_cli_exit_codes_and_pending(tmp_path):
    _write(tmp_path, "ok.md", "[a](ok.md)\n")
    _write(tmp_path, "bad.md", "[deck](presentation/deck.pdf)\n")
    run = lambda *a: subprocess.run([sys.executable, str(SCRIPT), "--root", str(tmp_path), "--no-git", *a],
                                    capture_output=True, text=True, encoding="utf-8")
    assert run("ok.md").returncode == 0
    bad = run("bad.md")
    assert bad.returncode == 1 and "bad.md:1: presentation/deck.pdf" in bad.stdout and "битых: 1" in bad.stdout
    pending = run("bad.md", "--pending", "presentation/deck.pdf")
    assert pending.returncode == 0 and "ожидается из другой ветки" in pending.stdout
    assert run("missing.md").returncode == 2


def test_default_files_are_the_submission_documents():
    assert set(check_links.DEFAULT_FILES) == {"README.md", "SUBMISSION.md", "reports/README.md", "presentation/README.md"}
    for name in check_links.DEFAULT_FILES:
        assert (ROOT / name).is_file(), name


def test_repository_submission_links_are_not_broken():
    """Главная проверка сдачи: каждая относительная ссылка документов сдачи — на файл в дереве (и в git)."""
    files = [ROOT / name for name in check_links.DEFAULT_FILES]
    use_git = (ROOT / ".git").exists()
    _, problems = check_links.check(files, ROOT, use_git=use_git)
    strict = os.environ.get("BCC_RELEASE_CHECK") == "1"
    broken = [p for p in problems
              if strict or not (p.link.path in PENDING_FROM_OTHERS and not (ROOT / p.link.path).exists())]
    assert not broken, "битые ссылки:\n" + "\n".join(
        f"{p.link.source}:{p.link.line}: {p.link.target} — {p.reason}" for p in broken)


def test_reports_table_shows_source_path_and_verifies(tmp_path):
    """scripts/reports_table.py: вход — путь исходника от корня (как повторить), verify — OK на настоящем отчёте."""
    out = tmp_path / "reports"
    src = "evaluation/dev/corpus/cases/cashback.base/source.md"
    r = subprocess.run([sys.executable, "-m", "bcc_review", src, str(out / "other_topic_cashback.md"),
                        "--provider", "mock", "--no-html", "-q", "--runs-dir", str(tmp_path / "runs")],
                       cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300)
    assert r.returncode == 0, r.stdout + r.stderr
    spec = importlib.util.spec_from_file_location("reports_table", ROOT / "scripts" / "reports_table.py")
    reports_table = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(reports_table)
    rows = reports_table.rows(out, {"other_topic_cashback": str(ROOT / src)})
    assert [(row["report"], row["input"], row["verify"]) for row in rows] == [("other_topic_cashback.md", src, "OK")]
    assert f"`{src}`" in reports_table.table(rows)
