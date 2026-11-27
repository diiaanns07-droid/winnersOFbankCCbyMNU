"""№16: выпуск — README по п. 7 ТЗ, .env.example без ключей, зафиксированные зависимости, CI, секреты.

Тесты без сети и без модели. Проверки, которым нужен CLI v2, пропускаются, пока каркаса v2 нет.
"""

from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
README = ROOT / "README.md"
ENV_EXAMPLE = ROOT / ".env.example"
REQUIREMENTS = ROOT / "requirements.txt"
WORKFLOWS = ROOT / ".github" / "workflows"
V2_SRC = ROOT / "src" / "bcc_review" / "v2"

# Похожие на настоящие ключи строки. Шаблоны «AIza…» в тексте README сюда не попадают: нужна полная длина.
SECRET_PATTERNS = {
    "Google API key": re.compile(r"AIza[0-9A-Za-z_\-]{35}"),
    "Anthropic key": re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}"),
    "OpenAI key": re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9]{32,}"),
    "GitHub token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}"),
}

# Заведомо поддельные ключи в тестах (проверка маскирования секретов): в них есть слово-маркер.
FAKE_MARKERS = re.compile(r"TEST|ECHOED|FAKE|DUMMY|EXAMPLE|PLACEHOLDER|SECRET|XXXX|0{8}", re.IGNORECASE)

# Переменные, которые код читает, но пользователю задавать не нужно (служебные, для CI и тестов).
INTERNAL_ENV = {
    "BCC_AGENT_COMMIT",  # коммит для паспорта в Docker и CI, задаётся при сборке
    "CLAUDE_CLI_LOG",  # отладочный журнал адаптера claude_cli
    "PYTHONUTF8",
    "PYTHONIOENCODING",
    "HOME",
    "PATH",
    "APPDATA",
    "LOCALAPPDATA",
    "USERPROFILE",
    "GITHUB_ACTIONS",
    "CI",
}


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _v2_cli_ready() -> bool:
    if not (V2_SRC / "pipeline.py").exists():
        return False
    try:
        return importlib.util.find_spec("bcc_review.v2") is not None
    except ImportError:  # пакет не установлен (`pip install -e .` не выполнен)
        return False


def _cli_help(*args: str) -> str:
    r = subprocess.run([sys.executable, "-m", "bcc_review", *args, "--help"], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", cwd=ROOT, timeout=120)
    return r.stdout + r.stderr


# --------------------------------------------------------------------------- README по п. 7 ТЗ


def test_readme_covers_tz_item_7():
    text = _read(README)
    # как получить ключ, куда его положить, какой командой запустить, куда ляжет отчёт
    assert "aistudio.google.com/apikey" in text
    assert "GEMINI_API_KEY" in text and ".env" in text and ".env.example" in text
    assert "python -m bcc_review <файл требований> <файл отчёта.md>" in text
    assert "## Куда ложится отчёт" in text
    for ext in (".md", ".json", ".html"):
        assert ext in text
    # модель указана в инструкции
    assert "gemini-3.8-flash" in text
    # быстрый старт для Windows и macOS/Linux
    assert "```powershell" in text and "```bash" in text
    assert "python -m pip install -r requirements.txt -e ." in text


def test_readme_has_required_sections():
    text = _read(README)
    for heading in ("## Быстрый старт", "## Что в отчёте", "## Модели и провайдеры", "## Параметры командной строки",
                    "## Режим ответов и исправленное ТЗ", "## Как устроен агент", "## Как мы проверяем качество",
                    "## Ограничения"):
        assert heading in text, heading


def test_readme_local_links_exist():
    text = _read(README)
    missing = []
    for target in re.findall(r"\]\(([^)#\s]+)(?:#[^)]*)?\)", text):
        if re.match(r"^[a-z]+://", target) or target.startswith("mailto:"):
            continue
        # каталоги и файлы, которые появляются на поздних этапах выпуска, проверяются после тега v2.0.0
        if target.startswith(("reports/", "evaluation/v2/", "examples/v2/")) and not (ROOT / target).exists():
            continue
        if not (ROOT / target).exists():
            missing.append(target)
    assert not missing, f"битые ссылки в README: {missing}"


@pytest.mark.skipif(not _v2_cli_ready(), reason="каркаса v2 ещё нет")
def test_readme_cli_flags_exist():
    """Каждый флаг из таблицы параметров README есть в --help (README не обещает того, чего нет)."""
    text = _read(README)
    section = text.split("## Параметры командной строки", 1)[1].split("\n## ", 1)[0]
    flags = sorted(set(re.findall(r"`(--[a-z][a-z0-9-]*)", section)))
    assert flags, "в разделе параметров нет флагов"
    help_text = _cli_help()
    missing = [f for f in flags if f not in help_text]
    assert not missing, f"флаги из README отсутствуют в `python -m bcc_review --help`: {missing}"


@pytest.mark.skipif(not _v2_cli_ready(), reason="каркаса v2 ещё нет")
def test_readme_providers_match_cli():
    help_text = _cli_help()
    for provider in ("gemini", "claude_cli", "anthropic", "openai", "offline", "mock"):
        assert provider in help_text, provider


# --------------------------------------------------------------------------- .env.example


def _env_documented() -> set[str]:
    """Имена переменных из .env.example, включая закомментированные необязательные строки «# NAME=…»."""
    return set(re.findall(r"^#?\s?([A-Z][A-Z0-9_]{2,})=", _read(ENV_EXAMPLE), flags=re.MULTILINE))


def _env_example() -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in _read(ENV_EXAMPLE).splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        assert "=" in line, f"строка .env.example без '=': {raw!r}"
        name, value = line.split("=", 1)
        assert re.fullmatch(r"[A-Z][A-Z0-9_]*", name), name
        values[name] = value
    return values


def test_env_example_has_no_secrets():
    values = _env_example()
    for name, value in values.items():
        if re.search(r"(KEY|TOKEN|SECRET|PASSWORD)$", name):
            assert value == "", f"{name} в .env.example должен быть пустым"
    text = _read(ENV_EXAMPLE)
    for label, pattern in SECRET_PATTERNS.items():
        assert not pattern.search(text), label
    for line in text.splitlines():  # закомментированные ключи тоже пустые
        m = re.match(r"^#\s?([A-Z][A-Z0-9_]*(?:KEY|TOKEN|SECRET|PASSWORD))=(.*)$", line)
        if m:
            assert m.group(2).strip() == "", f"{m.group(1)} в .env.example должен быть пустым"


def test_env_example_lists_provider_variables():
    values = _env_example()
    for name in ("GEMINI_API_KEY", "GEMINI_MODEL", "GEMINI_FALLBACK_MODELS", "ANTHROPIC_API_KEY", "ANTHROPIC_MODEL",
                 "CLAUDE_CLI_MODEL", "OPENAI_BASE_URL", "OPENAI_MODEL", "OPENAI_API_KEY"):
        assert name in values, name


@pytest.mark.skipif(not V2_SRC.exists(), reason="каркаса v2 ещё нет")
def test_env_example_covers_variables_read_by_v2():
    """Каждая переменная окружения, которую читает ядро v2, описана в .env.example."""
    pattern = re.compile(r"""(?:environ\.get|getenv|environ\[|_env\(|env\.get)\(?\s*["']([A-Z][A-Z0-9_]{2,})["']""")
    used: set[str] = set()
    for path in V2_SRC.rglob("*.py"):
        used |= set(pattern.findall(path.read_text(encoding="utf-8")))
    missing = sorted(used - _env_documented() - INTERNAL_ENV)
    assert not missing, f"переменные v2 не описаны в .env.example: {missing}"


# --------------------------------------------------------------------------- зависимости


def test_requirements_are_pinned():
    lines = [ln.split("#", 1)[0].strip() for ln in _read(REQUIREMENTS).splitlines()]
    reqs = [ln for ln in lines if ln]
    assert reqs
    for req in reqs:
        assert re.fullmatch(r"[A-Za-z0-9_.\-\[\],]+==[0-9][A-Za-z0-9.\-]*", req), f"версия не зафиксирована: {req}"
    names = {re.split(r"[\[=]", r, maxsplit=1)[0].lower() for r in reqs}
    for needed in ("jsonschema", "google-genai", "pymupdf", "python-docx", "pytest"):
        assert needed in names, needed


def test_pyproject_dependencies_are_in_requirements():
    try:
        import tomllib
    except ModuleNotFoundError:  # pragma: no cover - Python < 3.11
        pytest.skip("нет tomllib")
    data = tomllib.loads(_read(ROOT / "pyproject.toml"))
    pinned = {re.split(r"[\[=<>!~ ]", ln.split("#", 1)[0].strip(), maxsplit=1)[0].lower()
              for ln in _read(REQUIREMENTS).splitlines() if ln.split("#", 1)[0].strip()}
    for dep in data["project"].get("dependencies", []):
        name = re.split(r"[\[=<>!~ ;]", dep, maxsplit=1)[0].lower()
        assert name in pinned, f"зависимость pyproject не зафиксирована в requirements.txt: {dep}"


# --------------------------------------------------------------------------- CI и Docker


def test_ci_matrix_covers_three_os_and_two_pythons():
    text = _read(WORKFLOWS / "tests.yml")
    for os_name in ("ubuntu-latest", "windows-latest", "macos-latest"):
        assert os_name in text
    assert '"3.11"' in text and '"3.12"' in text
    assert "python -m pytest tests/v2 -q" in text
    assert "--provider mock" in text
    assert "python -m pip install -r requirements.txt -e ." in text


def test_report_workflow_uses_secret_and_uploads_artifacts():
    text = _read(WORKFLOWS / "report.yml")
    assert "workflow_dispatch" in text
    assert "secrets.GEMINI_API_KEY" in text
    assert "actions/upload-artifact" in text
    # входы workflow не подставляются прямо в shell (защита от внедрения команд)
    for line in text.splitlines():
        if line.strip().startswith(("run:", "python", "if [", "out=", "stem=")):
            assert "${{ inputs." not in line, line


def test_dockerfile_runs_the_agent():
    text = _read(ROOT / "Dockerfile")
    assert "requirements.txt" in text
    assert "exec python -m bcc_review" in text and "ENTRYPOINT" in text
    assert "AGENT_COMMIT" in text  # коммит в паспорте и без .git в образе
    ignore = _read(ROOT / ".dockerignore").splitlines()
    for entry in (".env", ".git/*", ".bcc_cache", "runs"):
        assert entry in ignore, entry
    allowed = {"!tests/v2/fixtures/official"}  # записанные ответы для --provider mock в контейнере
    assert not any(ln.startswith("!") and ".git/" not in ln and ln not in allowed for ln in ignore), \
        "исключения .dockerignore только для .git и фикстур mock"
    assert "COPY tests/v2/fixtures/official" in text


def test_git_commit_script_resolves_head(tmp_path):
    import importlib.util as iu
    spec = iu.spec_from_file_location("git_commit", ROOT / "scripts" / "git_commit.py")
    mod = iu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    sha = "0123456789abcdef0123456789abcdef01234567"
    (tmp_path / "HEAD").write_text(sha + "\n", encoding="utf-8")
    assert mod.resolve(tmp_path) == sha
    (tmp_path / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    (tmp_path / "packed-refs").write_text(f"# pack-refs\n{sha} refs/heads/main\n", encoding="utf-8")
    assert mod.resolve(tmp_path) == sha
    (tmp_path / "refs" / "heads").mkdir(parents=True)
    other = "f" * 40
    (tmp_path / "refs" / "heads" / "main").write_text(other, encoding="utf-8")
    assert mod.resolve(tmp_path) == other
    assert mod.resolve(tmp_path / "нет") == ""


# --------------------------------------------------------------------------- секреты в репозитории


def test_gitignore_protects_secrets_and_runs():
    lines = {ln.strip() for ln in _read(ROOT / ".gitignore").splitlines()}
    assert ".env" in lines
    assert any(ln.rstrip("/") in {".bcc_cache", "/.bcc_cache"} for ln in lines)


def test_no_secrets_in_tracked_files():
    try:
        out = subprocess.run(["git", "ls-files", "-z"], capture_output=True, cwd=ROOT, timeout=60, check=True).stdout
    except (OSError, subprocess.SubprocessError):
        pytest.skip("git недоступен")
    found = []
    for rel in filter(None, out.decode("utf-8", "replace").split("\0")):
        path = ROOT / rel
        if rel == ".env" or rel.endswith("/.env"):
            found.append(f"{rel}: файл .env в git")
            continue
        try:
            if not path.is_file() or path.stat().st_size > 5_000_000:
                continue
            text = path.read_bytes().decode("utf-8", "ignore")
        except OSError:
            continue
        for label, pattern in SECRET_PATTERNS.items():
            for m in pattern.finditer(text):
                if not FAKE_MARKERS.search(m.group(0)):
                    found.append(f"{rel}: {label}")
    assert not found, found


# --------------------------------------------------------------------------- скрипты для жюри и оператора

SCRIPTS = ROOT / "scripts"


def test_powershell_scripts_have_utf8_bom():
    """Windows PowerShell 5.1 читает .ps1 без BOM в кодировке ANSI: байты «Д» (D0 94) становятся кавычкой «”»."""
    ps1 = sorted(SCRIPTS.glob("*.ps1"))
    assert {p.name for p in ps1} >= {"run_official.ps1", "jury_check.ps1", "_env.ps1"}
    for path in ps1:
        assert path.read_bytes().startswith(b"\xef\xbb\xbf"), f"{path.name}: нужен UTF-8 с BOM"


def test_shell_scripts_parse_and_are_executable():
    import os
    import shutil

    bash = shutil.which("bash")
    for name in ("run_official.sh", "jury_check.sh", "final_reports.sh", "check_clean_install.sh"):
        path = SCRIPTS / name
        assert path.read_bytes().startswith(b"#!/usr/bin/env bash"), name
        assert b"\r\n" not in path.read_bytes(), f"{name}: окончания строк CRLF"
        if os.name != "nt":
            assert os.access(path, os.X_OK), f"{name}: нет права на запуск (chmod +x)"
        if bash and os.name != "nt":
            r = subprocess.run([bash, "-n", str(path)], capture_output=True, text=True, timeout=30)
            assert r.returncode == 0, r.stderr
    assert b"\r\n" not in (SCRIPTS / "_env.sh").read_bytes()


def _summary_report(tmp_path: Path, status: str, *, verified: int = 10, seconds: float = 120.0) -> Path:
    import json

    rep = {"run": {"status": status, "provider": "gemini", "models_used": ["gemini-3.8-flash"],
                   "calls": {"total": 9, "cached": 0, "failed": 0, "split": 0}, "duration_s": seconds,
                   "tokens": {"input": 1000, "output": 500}, "warnings": []},
           "summary": {"requirements": 40, "findings": {"critical": 4, "major": 10, "minor": 8},
                       "quotes_verified": verified, "quotes_total": 10},
           "verdict": {"development": "no", "testing": "no"}}
    path = tmp_path / f"r_{status}.json"
    path.write_text(json.dumps(rep, ensure_ascii=False), encoding="utf-8")
    return path


def _run_summary(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPTS / "run_summary.py"), *args], capture_output=True,
                          text=True, encoding="utf-8", errors="replace", timeout=60)


def test_run_summary_gates(tmp_path):
    ok = _summary_report(tmp_path, "complete")
    r = _run_summary(str(ok), "--check", "--max-minutes", "6", "--max-calls", "12", "--verify-code", "0")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "gemini-3.8-flash" in r.stdout and "Все проверки пройдены" in r.stdout

    partial = _summary_report(tmp_path, "partial")
    r = _run_summary(str(partial), "--check")
    assert r.returncode == 1 and "статус прогона" in r.stdout.split("Не пройдено:", 1)[1]

    slow = _summary_report(tmp_path, "complete", seconds=500)
    assert _run_summary(str(slow), "--check", "--max-minutes", "6").returncode == 1
    assert _run_summary(str(ok), "--check", "--verify-code", "4").returncode == 1
    # без --check сводка только печатается
    assert _run_summary(str(partial)).returncode == 0
    assert _run_summary(str(tmp_path / "нет.json")).returncode == 1
