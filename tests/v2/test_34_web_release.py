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
