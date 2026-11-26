"""Хранилище: безопасные имена, атомарные заявки, восстановление после перезапуска."""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from bcc_review.web.store import RunStore, StoreError, safe_filename


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("../../etc/passwd", "passwd"),
        ("..\\..\\boot.ini", "boot.ini"),
        ("ТЗ версия 2.PDF", "ТЗ_версия_2.pdf"),
        ("con.md", "_con.md"),
        ("", "document"),
        ("....", "document"),
        ("a\x00b\nc.md", "abc.md"),
        ("отчёт;rm -rf.md", "отчёт_rm_-rf.md"),
    ],
)
def test_safe_filename(raw: str, expected: str) -> None:
    assert safe_filename(raw) == expected


def test_same_name_gets_separate_runs(tmp_path) -> None:
    store = RunStore(tmp_path)
    a = store.create_run(original_name="tz.md", data=b"# A", options={}, engine={})
    b = store.create_run(original_name="tz.md", data=b"# B", options={}, engine={})
    assert a != b
    assert store.input_path(a).read_bytes() == b"# A"
    assert store.input_path(b).read_bytes() == b"# B"
    for rid in (a, b):
        for sub in ("input", "tmp", "artifacts"):
            assert (store.run_dir(rid) / sub).is_dir()


def test_rejects_unknown_extension_and_empty(tmp_path) -> None:
    store = RunStore(tmp_path)
    with pytest.raises(StoreError) as exc:
        store.create_run(original_name="virus.exe", data=b"MZ", options={}, engine={})
    assert exc.value.http_status == 415
    with pytest.raises(StoreError):
        store.create_run(original_name="tz.md", data=b"", options={}, engine={})


def test_concurrent_claims_create_one_run(tmp_path) -> None:
    store = RunStore(tmp_path)
    created: list[str] = []
    lock = threading.Lock()
    barrier = threading.Barrier(40)

    def create() -> str:
        rid = store.create_run(original_name="tz.md", data=b"x", options={}, engine={})
        with lock:
            created.append(rid)
        return rid

    def click(_: int):
        barrier.wait()
        return store.claim(None, "upload-same-key-123", create)

    with ThreadPoolExecutor(40) as pool:
        claims = list(pool.map(click, range(40)))
    assert len(created) == 1
    assert {c.run_id for c in claims} == set(created)
    assert sum(not c.duplicate for c in claims) == 1


def test_artifact_path_only_lists_real_files(tmp_path) -> None:
    store = RunStore(tmp_path)
    rid = store.create_run(original_name="tz.md", data=b"x", options={}, engine={})
    (store.artifacts_dir(rid) / "report.md").write_text("ok", encoding="utf-8")
    assert store.artifact_path(rid, "report.md").read_text() == "ok"
    for bad in ("../run.json", "../input/tz.md", "/etc/passwd", "missing.md"):
        with pytest.raises(StoreError):
            store.artifact_path(rid, bad)
    with pytest.raises(StoreError):
        store.run_dir("../../etc")


def test_recover_interrupted_marks_failed(tmp_path) -> None:
    store = RunStore(tmp_path)
    rid = store.create_run(original_name="tz.md", data=b"x", options={}, engine={})
    store.update(rid, status="running")
    assert RunStore(tmp_path).recover_interrupted() == [rid]
    rec = store.load(rid)
    assert rec["status"] == "failed"
    assert rec["error"]["kind"] == "interrupted"


def test_data_dir_is_self_ignored(tmp_path) -> None:
    RunStore(tmp_path / "d")
    assert (tmp_path / "d" / ".gitignore").read_text(encoding="utf-8").strip().endswith("*")
