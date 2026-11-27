"""№34: веб-демо запускается командой из README и не падает трейсбэком на занятом порту."""
from __future__ import annotations

import socket
import threading

from bcc_review.v2.web import server as S


def _app(tmp_path):
    return S.build_app(tmp_path / "web", provider="mock")


def _busy_socket() -> tuple[socket.socket, int]:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    s.listen(1)
    return s, s.getsockname()[1]


def test_port_taken_by_other_program_moves_to_next(tmp_path):
    busy, port = _busy_socket()
    try:
        srv, note = S.bind_server(_app(tmp_path), "127.0.0.1", port)
        assert srv is not None
        try:
            got = srv.server_address[1]
            assert got != port
            assert f"Порт {port} занят" in note and str(got) in note
        finally:
            srv.server_close()
    finally:
        busy.close()


def test_second_start_reports_running_demo(tmp_path):
    app = _app(tmp_path)
    first = S.make_server(app, "127.0.0.1", 0)
    port = first.server_address[1]
    th = threading.Thread(target=first.serve_forever, daemon=True)
    th.start()
    try:
        srv, note = S.bind_server(app, "127.0.0.1", port)
        assert srv is None
        assert note.startswith("Веб-демо уже запущено") and f":{port}/" in note
    finally:
        first.shutdown()
        first.server_close()


def test_main_second_start_exits_cleanly(tmp_path, capsys):
    app = _app(tmp_path)
    first = S.make_server(app, "127.0.0.1", 0)
    port = first.server_address[1]
    th = threading.Thread(target=first.serve_forever, daemon=True)
    th.start()
    try:
        code = S.main(["--port", str(port), "--data-dir", str(tmp_path / "web2")])
    finally:
        first.shutdown()
        first.server_close()
    out = capsys.readouterr()
    assert code == 0
    assert "Веб-демо уже запущено" in out.out
    assert "Traceback" not in out.err and "OSError" not in out.err


def test_bad_host_is_russian_message(tmp_path):
    srv, note = S.bind_server(_app(tmp_path), "host.invalid", 8014)
    assert srv is None
    assert note.startswith("Не удалось запустить веб-демо") and "--port" in note
    assert "такого адреса нет" in note and "Name or service" not in note


def test_no_silent_port_sharing_on_windows():
    # На Windows SO_REUSEADDR даёт второму серверу тот же порт без ошибки — там он должен быть выключен.
    assert S._Server.allow_reuse_address is (S.os.name != "nt")


# ── .env и автовыбор: веб видит то же, что CLI ──

import os  # noqa: E402

from bcc_review.v2.web import runner as R  # noqa: E402

_KEYS = ("GEMINI_API_KEY", "GOOGLE_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_BASE_URL", "CLAUDE_CLI_BIN")


def _clean_env(monkeypatch, tmp_path):
    for k in _KEYS:  # setenv запоминает исходное состояние: ключ из .env не утечёт в следующие тесты
        monkeypatch.setenv(k, "x")
        monkeypatch.delenv(k)
    monkeypatch.chdir(tmp_path)


def test_dotenv_with_bom_from_notepad(monkeypatch, tmp_path):
    _clean_env(monkeypatch, tmp_path)
    (tmp_path / ".env").write_bytes("﻿GEMINI_API_KEY=ключ-из-блокнота\n".encode("utf-8"))
    R.load_dotenv()
    assert os.environ.get("GEMINI_API_KEY") == "ключ-из-блокнота"
    assert {p["id"]: p for p in R.provider_status()}["gemini"]["ok"]


def test_dotenv_utf16_from_powershell_does_not_crash(monkeypatch, tmp_path):
    _clean_env(monkeypatch, tmp_path)
    (tmp_path / ".env").write_bytes("GEMINI_API_KEY=abc123\r\n".encode("utf-16"))
    R.load_dotenv()  # раньше — UnicodeDecodeError и трейсбэк при старте веб-демо
    assert os.environ.get("GEMINI_API_KEY") == "abc123"


def test_dotenv_does_not_override_environment(monkeypatch, tmp_path):
    _clean_env(monkeypatch, tmp_path)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "из-окружения")
    (tmp_path / ".env").write_text("ANTHROPIC_API_KEY=из-файла\n", encoding="utf-8")
    R.load_dotenv()
    assert os.environ["ANTHROPIC_API_KEY"] == "из-окружения"


def test_auto_label_matches_cli_choice(monkeypatch, tmp_path):
    _clean_env(monkeypatch, tmp_path)
    import shutil
    monkeypatch.setattr(shutil, "which", lambda name, *a, **k: "/usr/bin/claude" if name.startswith("claude") else None)
    monkeypatch.setenv("GEMINI_API_KEY", "x")
    auto = R.provider_status()[0]
    # CLI с --provider auto при ключе Gemini берёт Gemini, хотя claude тоже установлен
    assert auto["id"] == "auto" and auto["resolved"] == "gemini" and "Gemini" in auto["label"]
    monkeypatch.delenv("GEMINI_API_KEY")
    auto = R.provider_status()[0]
    assert auto["resolved"] == "claude_cli"


def test_auto_without_anything_is_offline(monkeypatch, tmp_path):
    _clean_env(monkeypatch, tmp_path)
    import shutil
    monkeypatch.setattr(shutil, "which", lambda *a, **k: None)
    auto = R.provider_status()[0]
    assert auto["resolved"] == "offline" and "только правила" in auto["label"]


# ── следующий круг ответов в вебе ──

import json  # noqa: E402
import time  # noqa: E402
import urllib.error  # noqa: E402
import urllib.parse  # noqa: E402
import urllib.request  # noqa: E402
from pathlib import Path  # noqa: E402

import pytest  # noqa: E402

_ROOT = Path(__file__).resolve().parents[2]
_DOC = _ROOT / "release" / "input" / "requirements.md"
_SAMPLE = _ROOT / "tests" / "v2" / "fixtures" / "14_report_official.json"


@pytest.fixture()
def web(tmp_path, monkeypatch):
    for k in _KEYS:
        monkeypatch.setenv(k, "x")
        monkeypatch.delenv(k)
    app = S.build_app(tmp_path / "data", fixture=_SAMPLE, step_s=0.01, sample=_DOC)
    httpd = S.make_server(app, "127.0.0.1", 0)
    th = threading.Thread(target=httpd.serve_forever, daemon=True)
    th.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    httpd.server_close()


def _req(url: str, data: bytes | None = None, ctype: str = "") -> tuple[int, bytes]:
    headers = {"Accept": "application/json"}
    if ctype:
        headers["Content-Type"] = ctype
    req = urllib.request.Request(url, data=data, method="POST" if data is not None else "GET", headers=headers)
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def _form(fields: dict[str, str]) -> tuple[bytes, str]:
    b = "b34" + str(int(time.time() * 1000))
    body = "".join(f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n' for k, v in fields.items())
    return (body + f"--{b}--\r\n").encode("utf-8"), f"multipart/form-data; boundary={b}"


def _done(base: str, jid: str) -> dict:
    for _ in range(300):
        st = json.loads(_req(f"{base}/api/jobs/{jid}")[1])
        if st["state"] in ("done", "failed"):
            return st
        time.sleep(0.05)
    raise AssertionError("задание не завершилось")


def test_recalc_from_report_and_next_round(web):
    body, ctype = _form({"sample": "1", "provider": "mock"})
    code, raw = _req(web + "/api/jobs", body, ctype)
    first = json.loads(raw)["id"]
    assert _done(web, first)["state"] == "done"
    page = _req(f"{web}/jobs/{first}")[1].decode("utf-8")
    assert 'id="recalc"' in page and "Пересчитать с ответами ↻" in page and "Загрузить файл ответов" in page
    # «Пересчитать с ответами» шлёт текст из вкладки «Вопросы» полем answers_text
    text = "Q-01 [Лимит]: A\n\n## Решения\n\n- Все суммы в тиынах\n"
    body, ctype = _form({"answers_text": text})
    code, raw = _req(f"{web}/api/jobs/{first}/answers", body, ctype)
    assert code == 201
    second = json.loads(raw)["id"]
    st = _done(web, second)
    assert st["parent"] == first and st["answers_path"] is True
    # у проверки с ответами — следующий круг: та же кнопка, другой текст
    page2 = _req(f"{web}/jobs/{second}")[1].decode("utf-8")
    assert "Следующий круг ↻" in page2 and 'data-key="answers_next"' in page2
    body, ctype = _form({"answers_text": "Q-02 [Дата]: B\n"})
    code, raw = _req(f"{web}/api/jobs/{second}/answers", body, ctype)
    assert code == 201 and _done(web, json.loads(raw)["id"])["parent"] == second
    # пустые ответы — подсказка, что нажать
    body, ctype = _form({"answers_text": "  "})
    code, raw = _req(f"{web}/api/jobs/{first}/answers", body, ctype)
    assert code == 400 and "Пересчитать с ответами" in json.loads(raw)["error"]


def test_answers_next_file_is_served():
    keys = {k: n for k, n, _, _ in R.FILES}
    assert keys["answers_next"] == "report.answers-next.md"
