"""№42: одна команда — скачал, запустил, открылось (start.sh, start.command, START.cmd + start.ps1, Docker, --check).

Без сети: pip и сервер в проверках start.sh подменены, сервер в проверках main() — настоящий, на 127.0.0.1.
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import socket
import stat
import subprocess
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from bcc_review.v2.web import server as S

ROOT = Path(__file__).resolve().parents[2]
UNIX = ("start.sh", "start.command", "scripts/check_start.sh")
WINDOWS = ("START.cmd", "start.ps1")
IS_GIT = (ROOT / ".git").exists() and shutil.which("git") is not None


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout


# ── файлы, окончания строк, биты ──

def test_start_files_exist():
    for name in UNIX + WINDOWS + ("docker-compose.yml",):
        assert (ROOT / name).is_file(), name


@pytest.mark.skipif(not IS_GIT, reason="нет git (архив ZIP)")
def test_gitattributes_line_endings():
    want = {"START.cmd": "crlf", "start.ps1": "crlf", "start.sh": "lf", "start.command": "lf",
            "scripts/check_start.sh": "lf"}
    for name, eol in want.items():
        out = _git("check-attr", "eol", "--", name)
        assert out.strip().endswith(f"eol: {eol}"), out


def test_unix_scripts_have_lf_and_shebang():
    for name in UNIX:
        data = (ROOT / name).read_bytes()
        assert data.startswith(b"#!"), name
        assert b"\r" not in data, f"{name}: CRLF — bash не запустит"


@pytest.mark.skipif(not IS_GIT, reason="нет git (архив ZIP)")
def test_unix_scripts_executable_in_git():
    for line in _git("ls-files", "-s", "--", *UNIX).splitlines():
        mode, _sha, _stage, path = line.split(maxsplit=3)
        assert mode == "100755", f"{path}: в git без бита исполнения (git update-index --chmod=+x)"
    assert len(_git("ls-files", "--", *UNIX).split()) == len(UNIX)


@pytest.mark.skipif(os.name == "nt", reason="бит исполнения — только unix")
def test_unix_scripts_executable_on_disk():
    for name in UNIX:
        assert os.access(ROOT / name, os.X_OK), name


@pytest.mark.skipif(shutil.which("bash") is None or os.name == "nt", reason="нет bash")
def test_unix_scripts_parse():
    for name in UNIX:
        r = subprocess.run(["bash", "-n", str(ROOT / name)], capture_output=True, text=True, timeout=30)
        assert r.returncode == 0, f"{name}: {r.stderr}"


def test_start_cmd_is_ascii_and_calls_start_ps1():
    data = (ROOT / "START.cmd").read_bytes()
    data.decode("ascii")  # cmd.exe читает .cmd в кодировке консоли: только ASCII
    text = data.decode("ascii").replace("\r\n", "\n")
    assert "chcp 65001" in text
    assert 'cd /d "%~dp0"' in text
    assert 'powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1" %*' in text
    assert re.search(r"if errorlevel 1 pause", text)


def test_start_ps1_bom_and_powershell51_syntax():
    data = (ROOT / "start.ps1").read_bytes()
    assert data.startswith(b"\xef\xbb\xbf"), "start.ps1: нужен UTF-8 с BOM (PowerShell 5.1 читает кириллицу как cp1251)"
    text = data[3:].decode("utf-8")
    code = "\n".join(ln.split("#", 1)[0] if not ln.lstrip().startswith("#") else "" for ln in text.splitlines())
    assert "&&" not in code and "||" not in code, "&& и || — только PowerShell 7"
    assert not re.search(r"\w\?\.\w|\?\?", code), "?. и ?? — только PowerShell 7"
    assert code.count("{") == code.count("}") and code.count("(") == code.count(")")
    for must in ('"-3.12"', '"-3.11"', 'Test-Python @("python")', "winget install -e --id Python.Python.3.12",
                 "Read-Host", "https://www.python.org/downloads/", "-LiteralPath", ".bcc-req",
                 "-m pip install -q -r requirements.txt", "-m bcc_review.v2.web --open @args"):
        assert must in text, must


# ── start.sh: поиск Python, установка только при изменении requirements ──

def _sandbox(tmp_path: Path) -> Path:
    d = tmp_path / "bcc review"  # пробел в пути
    d.mkdir()
    for name in ("start.sh", "requirements.txt", "constraints.txt"):
        shutil.copy2(ROOT / name, d / name)
    return d


def _fake_venv(d: Path, log: Path) -> None:
    """.venv/bin/python: `-m …` только записывается в журнал (ни pip, ни сервера), остальное — настоящий Python."""
    b = d / ".venv" / "bin"
    b.mkdir(parents=True)
    py = b / "python"
    py.write_text(f'#!/bin/sh\necho "$*" >> "{log}"\ncase "$1" in -m) exit 0;; esac\nexec "{sys.executable}" "$@"\n')
    py.chmod(py.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _run_start(d: Path, *args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    return subprocess.run([shutil.which("bash") or "bash", str(d / "start.sh"), *args], cwd=d, capture_output=True, text=True, timeout=60,
                          env=env or dict(os.environ))


needs_bash = pytest.mark.skipif(shutil.which("bash") is None or os.name == "nt", reason="нет bash")


@needs_bash
def test_start_sh_installs_once_then_skips_pip(tmp_path):
    d = _sandbox(tmp_path)
    log = tmp_path / "calls.log"
    _fake_venv(d, log)
    r = _run_start(d, "--check")
    assert r.returncode == 0, r.stderr
    calls = log.read_text().splitlines()
    assert any(c.startswith("-m pip install -q -r requirements.txt") for c in calls), calls
    assert calls[-1] == "-m bcc_review.v2.web --open --check"
    want = hashlib.sha256((d / "requirements.txt").read_bytes() + (d / "constraints.txt").read_bytes()).hexdigest()
    assert (d / ".venv" / ".bcc-req").read_text() == want

    log.write_text("")
    r = _run_start(d, "--check")
    assert r.returncode == 0, r.stderr
    calls = log.read_text().splitlines()
    assert not any("pip" in c for c in calls), f"повторный запуск снова звал pip: {calls}"
    assert "Устанавливаю зависимости" not in r.stdout

    with open(d / "constraints.txt", "a", encoding="utf-8") as f:  # изменились версии — ставим заново
        f.write("\n# new\n")
    log.write_text("")
    assert _run_start(d).returncode == 0
    assert any("pip install" in c for c in log.read_text().splitlines())


@needs_bash
def test_start_sh_without_python_prints_one_line_hint(tmp_path):
    d = _sandbox(tmp_path)
    bin_dir = tmp_path / "bin"  # в PATH только то, что нужно до проверки Python, и «старый» python3
    bin_dir.mkdir()
    for tool in ("dirname", "uname", "cat", "rm"):
        p = shutil.which(tool)
        if p:
            (bin_dir / tool).symlink_to(p)
    old = bin_dir / "python3"
    old.write_text("#!/bin/sh\nexit 1\n")  # как Python 3.9: проверка версии не проходит
    old.chmod(0o755)
    r = _run_start(d, env={"PATH": str(bin_dir), "HOME": str(tmp_path)})
    assert r.returncode == 1
    err = r.stderr.strip().splitlines()
    assert len(err) == 1 and "Нужен Python 3.11" in err[0], r.stderr
    assert "sudo apt install python3 python3-venv" in err[0] or "brew install python@3.12" in err[0]
    assert not (d / ".venv").exists()


def test_start_command_calls_start_sh():
    text = (ROOT / "start.command").read_text(encoding="utf-8")
    assert '"$(dirname "$0")/start.sh"' in text


# ── main(): --check, баннер, порты, браузер после ответа сервера ──

@pytest.fixture
def no_browser(monkeypatch):
    opened: list[str] = []
    monkeypatch.setattr(S.webbrowser, "open", lambda url, *a, **k: opened.append(url) or True)
    monkeypatch.setattr(S, "_CHECK_MODULES", ("json",))  # зависимости проверяет start.sh --check; тут — сервер
    return opened


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_check_starts_server_and_exits_zero(tmp_path, capsys, no_browser):
    port = _free_port()
    code = S.main(["--check", "--open", "--port", str(port), "--data-dir", str(tmp_path / "web")])
    out = capsys.readouterr().out
    assert code == 0
    assert f"http://127.0.0.1:{port}/healthz — ok" in out and "— 200" in out
    assert no_browser == [], "--check не открывает браузер"
    with pytest.raises(OSError), socket.create_connection(("127.0.0.1", port), timeout=2):
        pass  # сервер остановлен


def test_check_fails_when_dependency_missing(tmp_path, capsys, no_browser, monkeypatch):
    monkeypatch.setattr(S, "_CHECK_MODULES", ("json", "no_such_module_42"))
    code = S.main(["--check", "--port", str(_free_port()), "--data-dir", str(tmp_path / "web")])
    assert code == 1
    assert "no_such_module_42" in capsys.readouterr().err


def test_busy_port_moves_to_next(tmp_path, capsys, no_browser):
    busy = socket.socket()
    busy.bind(("127.0.0.1", 0))
    busy.listen(1)
    port = busy.getsockname()[1]
    try:
        code = S.main(["--check", "--port", str(port), "--data-dir", str(tmp_path / "web")])
    finally:
        busy.close()
    out = capsys.readouterr().out
    assert code == 0
    m = re.search(rf"Порт {port} занят другой программой — веб-демо запущено на порту (\d+)", out)
    assert m and int(m.group(1)) != port
    assert f"http://127.0.0.1:{m.group(1)}/healthz — ok" in out


def test_check_with_demo_already_running_checks_fresh_server(tmp_path, capsys, no_browser):
    app = S.build_app(tmp_path / "first", provider="mock")
    first = S.make_server(app, "127.0.0.1", 0)
    port = first.server_address[1]
    threading.Thread(target=first.serve_forever, daemon=True).start()
    try:
        code = S.main(["--check", "--port", str(port), "--data-dir", str(tmp_path / "web")])
    finally:
        first.shutdown()
        first.server_close()
    out = capsys.readouterr().out
    assert code == 0 and "healthz — ok" in out and f":{port}/healthz" not in out


def test_default_ports_8014_to_8030(tmp_path, monkeypatch):
    seen: dict[str, object] = {}

    def fake_bind(app, host, port, *, tries=20):
        seen.update(host=host, port=port, tries=tries)
        return None, "Не удалось запустить веб-демо (тест)"

    monkeypatch.setattr(S, "bind_server", fake_bind)
    assert S.main(["--data-dir", str(tmp_path / "web")]) == 2
    assert seen == {"host": "127.0.0.1", "port": 8014, "tries": 16}  # 8014…8030, только этот компьютер


def test_ready_line():
    plain = S._ready_line("http://127.0.0.1:8014/")
    assert plain == "Система открыта: http://127.0.0.1:8014 · остановить — Ctrl+C"
    busy = S._ready_line("http://127.0.0.1:8015/", "порт 8014 занят другой программой")
    assert busy == "Система открыта: http://127.0.0.1:8015 · порт 8014 занят другой программой · остановить — Ctrl+C"
    colored = S._ready_line("http://127.0.0.1:8014/", "", 24)
    assert "\x1b[1;38;2;0;185;117mhttp://127.0.0.1:8014\x1b[0m" in colored  # адрес — BCC Green
    assert re.sub(r"\x1b\[[0-9;]*m", "", colored) == plain
    assert "38;5;36m" in S._ready_line("http://127.0.0.1:8014/", "", 256)


def test_no_color_when_not_a_terminal(monkeypatch):
    class Pipe:
        def isatty(self):
            return False

    class Tty:
        def isatty(self):
            return True

    assert S._color_depth(Pipe()) == 0
    if os.name != "nt":
        monkeypatch.setenv("TERM", "xterm-256color")
        monkeypatch.delenv("NO_COLOR", raising=False)
        monkeypatch.delenv("COLORTERM", raising=False)
        monkeypatch.delenv("WT_SESSION", raising=False)
        monkeypatch.delenv("TERM_PROGRAM", raising=False)
        assert S._color_depth(Tty()) == 256
        monkeypatch.setenv("COLORTERM", "truecolor")
        assert S._color_depth(Tty()) == 24
        monkeypatch.setenv("NO_COLOR", "1")
        assert S._color_depth(Tty()) == 0


class _Run:
    """main() в потоке, как из start.sh: ждём строку «Система открыта» (браузер), потом останавливаем сервер."""

    def __init__(self, monkeypatch, tmp_path, *extra: str):
        self.servers: list = []
        self.opened = threading.Event()
        self.apps: list = []
        real_make, real_build = S.make_server, S.build_app
        monkeypatch.setattr(S, "make_server", lambda *a, **k: self.servers.append(real_make(*a, **k)) or self.servers[-1])
        monkeypatch.setattr(S, "build_app", lambda *a, **k: self.apps.append(real_build(*a, **k)) or self.apps[-1])
        monkeypatch.setattr(S, "_has_gui", lambda: True)
        monkeypatch.setattr(S.webbrowser, "open", lambda url, *a, **k: self.opened.set() or True)
        self.port = _free_port()
        self.data = tmp_path / "web"
        self.result: list = []
        args = ["--open", "--port", str(self.port), "--data-dir", str(self.data), *extra]
        self.thread = threading.Thread(target=lambda: self.result.append(S.main(args)), daemon=True)

    def __enter__(self):
        self.thread.start()
        assert self.opened.wait(15), "браузер не открылся"
        return self

    def get(self, path: str) -> int:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}", timeout=5) as r:
                r.read()
                return r.status
        except urllib.error.HTTPError as exc:
            return exc.code

    def __exit__(self, *exc):
        for s in self.servers:
            s.shutdown()
        self.thread.join(10)
        assert not self.thread.is_alive()


def test_console_has_no_request_log(tmp_path, monkeypatch, capsys):
    with _Run(monkeypatch, tmp_path, "--no-tty") as run:
        assert run.get("/") == 200 and run.get("/assets/app.css") == 200 and run.get("/nope") == 404
    out = capsys.readouterr()
    assert "GET /" not in out.out + out.err, "журнал запросов — не в консоль"
    assert out.out.strip().splitlines()[-1] == f"Система открыта: http://127.0.0.1:{run.port} · остановить — Ctrl+C"
    assert out.err == ""
    log = (run.data / "web.log").read_text(encoding="utf-8")
    assert '"GET / HTTP/1.1" 200' in log and '"GET /assets/app.css HTTP/1.1" 200' in log
    assert run.result == [0]


def test_server_error_one_line_in_console_traceback_in_log(tmp_path, monkeypatch, capsys):
    def boom(*a, **k):
        raise RuntimeError("сломалось")

    with _Run(monkeypatch, tmp_path, "--no-tty") as run:
        monkeypatch.setattr(S, "index_page", boom)
        try:
            run.get("/")
        except Exception:  # noqa: BLE001 — соединение закрыто без ответа
            pass
    err = capsys.readouterr().err
    assert "Ошибка при обработке запроса: RuntimeError: сломалось" in err and "Traceback" not in err
    assert "Traceback" in (run.data / "web.log").read_text(encoding="utf-8")


def test_broken_connection_is_silent(tmp_path, capsys):
    app = S.build_app(tmp_path / "web", provider="mock")
    srv = S.make_server(app, "127.0.0.1", 0)
    try:
        try:
            raise ConnectionResetError("браузер закрыл вкладку")
        except ConnectionResetError:
            srv.handle_error(None, ("127.0.0.1", 1))
    finally:
        srv.server_close()
    assert capsys.readouterr().err == ""


def _fake_tty_agent(monkeypatch, greet):
    import types

    mod = types.ModuleType("bcc_review.v2.web.tty_agent")
    mod.greet = greet
    monkeypatch.setitem(sys.modules, "bcc_review.v2.web.tty_agent", mod)
    import bcc_review.v2.web as web_pkg

    monkeypatch.setattr(web_pkg, "tty_agent", mod, raising=False)


def test_greet_runs_before_browser_and_sets_provider(tmp_path, monkeypatch, capsys):
    calls: list = []

    def greet(port, env_path):
        calls.append((port, Path(env_path).name))
        print("Здравствуйте! Я BCC AI.")
        return "gemini"

    _fake_tty_agent(monkeypatch, greet)
    with _Run(monkeypatch, tmp_path) as run:
        pass
    assert calls == [(run.port, ".env")]
    assert run.apps[0].default_provider == "gemini"  # браузер — сразу на главную, не на веб-знакомство
    out = capsys.readouterr().out.strip().splitlines()
    assert out[-2:] == ["Здравствуйте! Я BCC AI.", f"Система открыта: http://127.0.0.1:{run.port} · остановить — Ctrl+C"]


def test_greet_failure_does_not_block_system(tmp_path, monkeypatch, capsys):
    def greet(port, env_path):
        raise RuntimeError("терминал странный")

    _fake_tty_agent(monkeypatch, greet)
    with _Run(monkeypatch, tmp_path) as run:
        assert run.get("/healthz") == 200
    assert run.apps[0].default_provider == "auto"
    assert "Система открыта" in capsys.readouterr().out
    assert "терминал странный" in (run.data / "web.log").read_text(encoding="utf-8")


def test_greet_skipped_with_no_tty_and_check(tmp_path, monkeypatch, capsys):
    calls: list = []
    _fake_tty_agent(monkeypatch, lambda port, env_path: calls.append(port) or "gemini")
    with _Run(monkeypatch, tmp_path, "--no-tty") as run:
        pass
    monkeypatch.setattr(S, "_CHECK_MODULES", ("json",))
    assert S.main(["--check", "--port", str(_free_port()), "--data-dir", str(tmp_path / "c")]) == 0
    assert calls == [] and run.apps[0].default_provider == "auto"


def test_ctrl_c_during_greet_stops_cleanly(tmp_path, monkeypatch, capsys):
    def greet(port, env_path):
        raise KeyboardInterrupt

    _fake_tty_agent(monkeypatch, greet)
    monkeypatch.setattr(S, "_has_gui", lambda: True)
    opened: list = []
    monkeypatch.setattr(S.webbrowser, "open", lambda url, *a, **k: opened.append(url))
    port = _free_port()
    assert S.main(["--open", "--port", str(port), "--data-dir", str(tmp_path / "w")]) == 0
    assert opened == [] and "BCC Review остановлен." in capsys.readouterr().out
    with pytest.raises(OSError), socket.create_connection(("127.0.0.1", port), timeout=2):
        pass


def test_no_text_browser_on_headless_linux(monkeypatch):
    monkeypatch.setattr(S.sys, "platform", "linux")
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    assert S._has_gui() is False
    monkeypatch.setenv("DISPLAY", ":0")
    assert S._has_gui() is True


def test_start_sh_empty_args_safe_for_bash32():
    text = (ROOT / "start.sh").read_text(encoding="utf-8")
    assert 'exec "$PY" -m bcc_review.v2.web --open ${1+"$@"}' in text  # bash 3.2 + set -u: пустой "$@" — ошибка


def test_host_0000_prints_local_address():
    assert S._shown_host("0.0.0.0") == "127.0.0.1" and S._shown_host("127.0.0.1") == "127.0.0.1"


# ── Docker и README ──

def test_docker_compose():
    text = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    yaml = pytest.importorskip("yaml")
    svc = yaml.safe_load(text)["services"]["web"]
    assert svc["ports"] == ["127.0.0.1:8014:8014"]
    assert svc["command"][:2] == ["--host", "0.0.0.0"] and "8014" in svc["command"]
    assert "python -m bcc_review.v2.web" in " ".join(svc["entrypoint"])
    assert svc["env_file"] == [{"path": ".env", "required": False}], "без .env compose не должен падать"


@pytest.mark.skipif(shutil.which("docker") is None, reason="нет docker")
def test_docker_compose_config_valid():
    r = subprocess.run(["docker", "compose", "config", "-q"], cwd=ROOT, capture_output=True, text=True, timeout=60)
    if r.returncode != 0 and "compose" in r.stderr and "not a docker command" in r.stderr:
        pytest.skip("нет docker compose")
    assert r.returncode == 0, r.stderr


def test_readme_quickstart_block():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    head, _, rest = text.partition("\n")
    assert head.startswith("# ")
    assert rest.lstrip().startswith("<!-- quickstart -->"), "блок «Быстрый старт» — сразу под заголовком"
    block = rest.split("<!-- quickstart -->", 1)[1].split("<!-- /quickstart -->", 1)[0]
    url = "git clone -b release https://github.com/diiaanns07-droid/winnersOFbankCCbyMNU bcc-review"
    assert f"{url} && cd bcc-review && ./start.sh" in block
    assert f"{url}; cd bcc-review; .\\START.cmd" in block
    assert "docker compose up" in block and "http://localhost:8014" in block
    assert "Download ZIP" in block and "START.cmd" in block and "start.command" in block


def test_web_data_dir_ignored():
    assert "/.bcc_web/" in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
