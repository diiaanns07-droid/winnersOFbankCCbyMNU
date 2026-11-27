"""№24: claude_cli на Windows — запуск без cmd.exe, кавычки и пустой аргумент, кодировка, предел строки.

Настоящего Windows в облаке нет: проверяем то, что можно проверить честно, — выбор команды по шимам npm/pnpm,
разбор командной строки Windows (``subprocess.list2cmdline`` → правила CommandLineToArgvW) и что схемы этапов
не содержат знаков, которые cmd.exe понял бы по-своему, если запуск всё же пойдёт через ``claude.cmd``.
"""
from __future__ import annotations

import json
import subprocess

import pytest

from bcc_review.v2.providers import claude_cli
from bcc_review.v2.providers.claude_cli import ClaudeCLIProvider, find_cli

NPM_SHIM = r'''@ECHO off
GOTO start
:find_dp0
SET dp0=%~dp0
EXIT /b
:start
SETLOCAL
CALL :find_dp0
IF EXIST "%dp0%\node.exe" (
  SET "_prog=%dp0%\node.exe"
) ELSE (
  SET "_prog=node"
  SET PATHEXT=%PATHEXT:;.JS;=;%
)
endLocal & goto #_undefined_# 2>NUL || title %COMSPEC% & "%_prog%"  "%dp0%\{target}" %*
'''


@pytest.fixture
def windows(monkeypatch):
    monkeypatch.setattr(claude_cli, "_is_windows", lambda: True)


def make(tmp_path, rel):
    path = tmp_path.joinpath(*rel.split("\\"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("//")
    return path


def test_pnpm_style_shim_runs_node_directly(windows, tmp_path):
    bin_dir = tmp_path / "pnpm"
    bin_dir.mkdir()
    target = make(bin_dir, r"global\5\node_modules\@anthropic-ai\claude-code\cli.js")
    (bin_dir / "claude.cmd").write_text(NPM_SHIM.replace("{target}", r"global\5\node_modules\@anthropic-ai"
                                                                     r"\claude-code\cli.js"), encoding="utf-8")
    which = {"claude.cmd": str(bin_dir / "claude.cmd"), "node": r"C:\node\node.exe"}.get
    assert find_cli({}, which=which) == [r"C:\node\node.exe", str(target.resolve())]


def test_shim_pointing_to_native_exe(windows, tmp_path):
    target = make(tmp_path, r"node_modules\@anthropic-ai\claude-code\bin\claude.exe")
    (tmp_path / "claude.cmd").write_text(NPM_SHIM.replace("{target}", r"node_modules\@anthropic-ai\claude-code"
                                                                      r"\bin\claude.exe"), encoding="utf-8")
    which = {"claude.cmd": str(tmp_path / "claude.cmd")}.get
    assert find_cli({}, which=which) == [str(target.resolve())]


def test_missing_node_exe_is_not_invented(windows, tmp_path):
    """Нет node в PATH и рядом — не подставляем несуществующий node.exe (был бы «не удалось запустить»)."""
    make(tmp_path, r"node_modules\@anthropic-ai\claude-code\cli.js")
    cmd = str(tmp_path / "claude.cmd")
    (tmp_path / "claude.cmd").write_text("@echo off", encoding="utf-8")
    assert find_cli({}, which={"claude.cmd": cmd}.get) == [cmd]


def test_unknown_shim_falls_back_to_cmd(windows, tmp_path):
    cmd = tmp_path / "claude.cmd"
    cmd.write_text("@echo off\r\nsomething.exe %*\r\n", encoding="utf-8")
    assert find_cli({}, which={"claude.cmd": str(cmd), "node": "node.exe"}.get) == [str(cmd)]


def _windows_argv(cmdline: str) -> list[str]:
    """Разбор командной строки по правилам MSVCRT/CommandLineToArgvW (как его делают node и claude.exe)."""
    out, cur, i, quoted, has = [], [], 0, False, False
    while i < len(cmdline):
        c = cmdline[i]
        if c == "\\":
            n = 0
            while i < len(cmdline) and cmdline[i] == "\\":
                n += 1
                i += 1
            if i < len(cmdline) and cmdline[i] == '"':
                cur.append("\\" * (n // 2))
                if n % 2:
                    cur.append('"')
                    i += 1
                has = True
                continue
            cur.append("\\" * n)
            has = True
            continue
        if c == '"':
            quoted = not quoted
            has = True
        elif c in " \t" and not quoted:
            if has:
                out.append("".join(cur))
            cur, has = [], False
        else:
            cur.append(c)
            has = True
        i += 1
    if has:
        out.append("".join(cur))
    return out


def _stage_schemas():
    """Схемы всех этапов, как их видит провайдер на mock-прогоне официального ТЗ."""
    from pathlib import Path

    from bcc_review.v2.providers.mock import MockProvider
    seen = {}
    orig = MockProvider.invoke

    def spy(self, **kw):
        seen.setdefault(kw.get("stage"), kw["schema"])
        return orig(self, **kw)

    root = Path(__file__).resolve().parents[2]
    MockProvider.invoke = spy
    try:
        import tempfile

        from bcc_review.v2.__main__ import main
        with tempfile.TemporaryDirectory() as d:
            try:
                main([str(root / "release/input/requirements.md"), f"{d}/r.md", "--provider", "mock", "-q",
                      "--runs-dir", f"{d}/runs", "--no-html"])
            except SystemExit:
                pass
    finally:
        MockProvider.invoke = orig
    return seen


@pytest.fixture(scope="module")
def schemas():
    s = _stage_schemas()
    assert {"segment", "lens_analyst", "judge", "consistency"} <= set(s), sorted(s)
    return s


def test_command_line_survives_windows_quoting(schemas):
    """Пустой ``--tools ""``, JSON-схема с кавычками и кириллицей, путь с пробелом — доходят до CLI без искажений."""
    p = ClaudeCLIProvider(env={"CLAUDE_CLI_BIN": r"C:\Program Files\Claude\claude.exe"})
    for stage, schema in schemas.items():
        cmd = p.build_command("sonnet", schema, r"C:\Users\Иван Петров\AppData\Local\Temp\bcc_sys_1.md", stage)
        line = subprocess.list2cmdline(cmd)
        assert _windows_argv(line) == cmd, stage
        assert json.loads(cmd[cmd.index("--json-schema") + 1]) == schema
        # предел CreateProcess — 32 767 знаков; через cmd.exe — 8 191: держим запас для запуска через claude.cmd
        assert len(line) < 8191, (stage, len(line))


def test_schemas_have_no_cmd_exe_metacharacters(schemas):
    """Если запуск всё же пойдёт через claude.cmd, cmd.exe не должен увидеть % & | < > ^ в аргументе схемы."""
    for stage, schema in schemas.items():
        text = json.dumps(schema, ensure_ascii=False, separators=(",", ":"))
        bad = sorted(set(text) & set('%&|<>^'))
        assert not bad, (stage, bad)


def test_utf8_output_is_decoded_as_utf8(monkeypatch):
    """Ответ CLI читается как UTF-8 при любой кодовой странице консоли (cp866/cp1251 на Windows)."""
    seen = {}

    def runner(cmd, **kw):
        seen.update(kw)
        out = json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": "",
                          "structured_output": {"answer": "Ақпарат — Қазақстан"}, "session_id": "s",
                          "usage": {"input_tokens": 1, "output_tokens": 1}, "modelUsage": {"claude-sonnet": {}}},
                         ensure_ascii=False)
        return subprocess.CompletedProcess(cmd, 0, out, "")

    p = ClaudeCLIProvider(env={"CLAUDE_CLI_BIN": "claude"}, runner=runner)
    schema = {"type": "object", "required": ["answer"], "properties": {"answer": {"type": "string"}}}
    r = p.invoke(model="sonnet", messages=[{"role": "user", "content": "Сұрақ"}], schema=schema, timeout_s=30)
    assert r["data"]["answer"] == "Ақпарат — Қазақстан"
    assert seen["encoding"] == "utf-8" and seen["errors"] == "replace" and seen["text"] is True
    assert seen["input"] == "Сұрақ"
