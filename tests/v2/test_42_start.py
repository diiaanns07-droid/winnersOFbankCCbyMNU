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


def test_banner():
    b = S._banner("http://127.0.0.1:8014/")
    assert "BCC Review работает: http://127.0.0.1:8014 — остановить: Ctrl+C" in b
    lines = [ln for ln in b.splitlines() if ln]
    assert len(lines) == 3 and len({len(ln) for ln in lines}) == 1  # ровная рамка
    ascii_frame = S._banner("http://127.0.0.1:8014/", "cp1251")  # вывод в файл на русской Windows
    ascii_frame.encode("cp1251")
    assert "BCC Review работает: http://127.0.0.1:8014" in ascii_frame and "+===" in ascii_frame


def test_open_browser_only_after_server_answers(tmp_path, monkeypatch, capsys):
    servers: list = []
    real_make = S.make_server
    monkeypatch.setattr(S, "make_server", lambda *a, **k: servers.append(real_make(*a, **k)) or servers[-1])
    answered: list[bytes] = []
    done = threading.Event()

    def fake_open(url, *a, **k):
        with urllib.request.urlopen(url + "healthz", timeout=3) as r:  # сервер уже отвечает
            answered.append(r.read())
        done.set()
        return True

    monkeypatch.setattr(S.webbrowser, "open", fake_open)
    monkeypatch.setattr(S, "_has_gui", lambda: True)
    port = _free_port()
    th = threading.Thread(target=S.main, args=(["--open", "--port", str(port), "--data-dir", str(tmp_path / "w")],),
                          daemon=True)
    th.start()
    try:
        assert done.wait(15), "браузер не открылся"
    finally:
        for s in servers:
            s.shutdown()
        th.join(10)
    assert answered == [b"ok"]
    assert f"BCC Review работает: http://127.0.0.1:{port} — остановить: Ctrl+C" in capsys.readouterr().out


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
