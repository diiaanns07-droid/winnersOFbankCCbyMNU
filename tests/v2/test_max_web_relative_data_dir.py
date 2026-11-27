"""Max (проверка на Windows): веб-демо с относительной папкой данных — значение по умолчанию `--data-dir .bcc_web`.

Анализ идёт дочерним процессом с cwd = папка задания; при относительном корне путь к загруженному файлу там
не находился, и любой прогон из веба падал «Файл не найден: .bcc_web/jobs/…/input/…».
"""

from __future__ import annotations

from pathlib import Path

from bcc_review.v2.web import runner as R

DOC = Path(__file__).resolve().parents[2] / "release" / "input" / "requirements.md"


def test_store_root_is_absolute_for_relative_data_dir(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    store = R.JobStore(Path(".bcc_web"))
    assert store.root.is_absolute()
    job = store.create("requirements.md", b"# T\n", "offline", "")
    assert Path(job.input_path).is_absolute() and Path(job.input_path).exists()


def test_offline_job_runs_with_default_relative_data_dir(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    store = R.JobStore(Path(".bcc_web"))
    job = store.create("requirements.md", DOC.read_bytes(), "offline", "")
    R.PipelineRunner(store).run(job, lambda j: None)
    assert not job.error, job.error
    assert (store.dir(job.id) / "out" / "report.md").exists()
