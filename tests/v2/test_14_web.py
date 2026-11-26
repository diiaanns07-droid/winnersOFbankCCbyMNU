"""Тесты веб-демо v2 (№14): загрузка → этапы → отчёт и выгрузки; понятные ошибки без ключа."""
from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

import pytest

from bcc_review.v2.web import runner as R
from bcc_review.v2.web import server as S

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / "release" / "input" / "requirements.md"
SAMPLE = ROOT / "tests" / "v2" / "fixtures" / "14_report_official.json"


@pytest.fixture()
def srv(tmp_path, monkeypatch):
    for k in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_BASE_URL"):
        monkeypatch.delenv(k, raising=False)
    app = S.build_app(tmp_path / "data", fixture=SAMPLE, step_s=0.01, sample=DOC)
    httpd = S.make_server(app, "127.0.0.1", 0)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    httpd.server_close()


def _multipart(fields: dict, file: tuple[str, bytes] | None) -> tuple[bytes, str]:
    b = uuid.uuid4().hex
    out = []
    for k, v in fields.items():
        out.append(f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
    if file:
        out.append(f'--{b}\r\nContent-Disposition: form-data; name="file"; filename="{file[0]}"\r\n'
                   f"Content-Type: application/octet-stream\r\n\r\n".encode() + file[1] + b"\r\n")
    out.append(f"--{b}--\r\n".encode())
    return b"".join(out), f"multipart/form-data; boundary={b}"


def _post(base: str, fields: dict, file=None) -> tuple[int, dict]:
    body, ctype = _multipart(fields, file)
    req = urllib.request.Request(base + "/api/jobs", data=body, method="POST",
                                 headers={"Content-Type": ctype, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def _get(url: str) -> tuple[int, bytes, dict]:
    try:
        with urllib.request.urlopen(url) as r:
            return r.status, r.read(), dict(r.headers)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(), dict(exc.headers)


def _wait(base: str, jid: str, timeout: float = 15) -> dict:
    t0 = time.time()
    while time.time() - t0 < timeout:
        st = json.loads(_get(f"{base}/api/jobs/{jid}")[1])
        if st["state"] in ("done", "failed"):
            return st
        time.sleep(0.05)
    raise AssertionError("задание не завершилось")


def test_index_page(srv):
    code, body, _ = _get(srv + "/")
    text = body.decode()
    assert code == 200 and "Проверка требований" in text and 'name="provider"' in text
    assert "Проверить пример" in text


def test_upload_to_report(srv):
    code, j = _post(srv, {"provider": "mock"}, ("Моё ТЗ.md", DOC.read_bytes()))
    assert code == 201, j
    st = _wait(srv, j["id"])
    assert st["state"] == "done", st
    assert all(s["state"] == "done" for s in st["stage_list"])
    assert {"html", "json"} <= set(st["files"])
    assert st["summary"]["critical"] == 5
    code, html, hdr = _get(f"{srv}/jobs/{j['id']}/files/report.html?inline=1")
    assert code == 200 and b"<!doctype html>" in html and hdr["Content-Disposition"].startswith("inline")
    code, _, hdr = _get(f"{srv}/jobs/{j['id']}/files/report.json")
    assert code == 200 and hdr["Content-Disposition"].startswith("attachment")
    code, page, _ = _get(f"{srv}/jobs/{j['id']}")
    assert code == 200 and "data-job" in page.decode()


def test_sample_button(srv):
    code, j = _post(srv, {"provider": "mock", "sample": "1"})
    assert code == 201
    assert _wait(srv, j["id"])["state"] == "done"


def test_missing_key_message(srv):
    code, j = _post(srv, {"provider": "gemini"}, ("t.md", b"# x\n"))
    assert code == 400
    assert "GEMINI_API_KEY" in j["error"] and "Демо без модели" in j["error"]


def test_bad_extension_and_no_file(srv):
    code, j = _post(srv, {"provider": "mock"}, ("virus.exe", b"MZ"))
    assert code == 400 and "не поддерживается" in j["error"]
    code, j = _post(srv, {"provider": "mock"})
    assert code == 400 and "Выберите файл" in j["error"]


def test_unknown_file_and_job(srv):
    assert _get(srv + "/jobs/20990101-000000-abcdef")[0] == 404
    code, j = _post(srv, {"provider": "mock"}, ("a.md", DOC.read_bytes()))
    _wait(srv, j["id"])
    assert _get(f"{srv}/jobs/{j['id']}/files/../../job.json")[0] == 404
    assert _get(f"{srv}/jobs/{j['id']}/files/secret.txt")[0] == 404


def test_safe_filename():
    assert R.safe_filename("../../etc/passwd") == "passwd.txt"
    assert R.safe_filename("C:\\docs\\ТЗ v2 (финал).PDF") == "ТЗ v2 _финал.pdf"
    assert R.safe_filename(".md") == "document.md"


def test_provider_status_has_mock_and_auto(monkeypatch):
    for k in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_BASE_URL"):
        monkeypatch.delenv(k, raising=False)
    ids = {p["id"]: p for p in R.provider_status()}
    assert ids["mock"]["ok"] and ids["auto"]["ok"] and not ids["gemini"]["ok"]
    assert R.check_provider("mock") == ""


def test_answers_rerun(srv):
    code, j = _post(srv, {"provider": "mock"}, ("tz.md", DOC.read_bytes()))
    assert _wait(srv, j["id"])["state"] == "done"
    body, ctype = _multipart({}, None)
    b = ctype.split("boundary=")[1]
    body = (f'--{b}\r\nContent-Disposition: form-data; name="answers"; filename="a.md"\r\n\r\n'
            "Q-01 [лимит]: A\r\n"
            f"--{b}--\r\n").encode()
    req = urllib.request.Request(f"{srv}/api/jobs/{j['id']}/answers", data=body, method="POST",
                                 headers={"Content-Type": ctype, "Accept": "application/json"})
    with urllib.request.urlopen(req) as r:
        child = json.loads(r.read())
    st = _wait(srv, child["id"])
    assert st["parent"] == j["id"] and st["answers_path"] is True and st["state"] == "done"
    # пустые ответы — понятная ошибка
    req = urllib.request.Request(f"{srv}/api/jobs/{j['id']}/answers", data=f"--{b}--\r\n".encode(), method="POST",
                                 headers={"Content-Type": ctype, "Accept": "application/json"})
    try:
        urllib.request.urlopen(req)
        raise AssertionError("ожидалась ошибка")
    except urllib.error.HTTPError as exc:
        assert exc.code == 400 and "Скачать ответы" in json.loads(exc.read())["error"]


def test_pipeline_command_has_answers(tmp_path):
    store = R.JobStore(tmp_path)
    job = store.create("a.md", b"# x\n", "claude_cli", "sonnet", answers=b"Q-01: A\n")
    cmd = R.PipelineRunner(store, extra_args=["--engine", "v1"]).command(job, tmp_path / "o.md", tmp_path / "runs")
    assert cmd[1:3] == ["-m", "bcc_review"] and "--answers" in cmd and "--revise" in cmd
    assert cmd[cmd.index("--model") + 1] == "sonnet" and cmd[-2:] == ["--engine", "v1"]
