"""Public CLI smoke for a clean installation. All provider traffic in these tests is local."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
from bcc_review import contracts
from bcc_review.runtime.core import atomic_write_json

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = "# Квитанция\n\n## Ф-1. Срок\n\nСервис должен выдать квитанцию оперативно после регистрации заявки.\n"
SOURCE_SHA = "e7dae55e5453a250d93e335f5ff9c7f775f4457ccddd333f4a67e47b20d74381"


def run_cli(cwd, *args, expected=0):
    env = {k: v for k, v in os.environ.items() if not k.startswith(("ANTHROPIC_", "GEMINI_", "BCC_"))
           and k not in {"GOOGLE_API_KEY", "PYTHONPATH", "PYTHONHOME"}}
    env.update(PYTHONNOUSERSITE="1", PYTHONIOENCODING="utf8")
    result = subprocess.run([sys.executable, "-m", "bcc_review", *map(str, args)], env=env, cwd=cwd,
                            capture_output=True, text=True, encoding="utf8", timeout=90)
    assert result.returncode == expected, result.stdout + result.stderr
    return result


@pytest.fixture
def source(tmp_path):
    path = tmp_path / "Пример для жюри" / "Условия выдачи.md"
    path.parent.mkdir()
    path.write_text(EXAMPLE, encoding="utf8")
    return path


def report(path):
    assert path.with_suffix(".md").stat().st_size > 0
    data = json.loads(path.with_suffix(".json").read_text("utf8"))
    contracts.validate(data)
    return data


def test_official_markdown_matches_published_release(tmp_path):
    source = ROOT / "release/input/requirements.md"
    out = tmp_path / "готовый отчёт" / "requirements.md"
    run_cli(tmp_path, source, out, "--offline-lint", "--no-cache")
    result = report(out)
    assert hashlib.sha256(source.read_bytes()).hexdigest() == result["document"]["id"] == SOURCE_SHA
    assert result["run"]["mode"] == "rules_only" and result["run"]["model"] is None
    assert result["run"]["status"] == "partial" and result["run"]["calls"]["physical"] == 0
    reference = json.loads((ROOT / "release/reports/offline/requirements.json").read_text("utf8"))
    for key in ("requirements", "findings", "questions", "checklist", "verdict"):
        assert result[key] == reference[key], key
    run_cli(tmp_path, "verify", out.with_suffix(".json"), source)


def test_empty_input_yields_failed_verdict(tmp_path):
    empty = tmp_path / "empty.md"
    empty.write_bytes(b"")
    out = tmp_path / "report.md"
    run_cli(tmp_path, empty, out, "--offline-lint", "--no-cache", "--fail-on", "partial",
            expected=contracts.EXIT_PARTIAL)
    result = report(out)
    assert result["run"]["status"] == "failed" and not result["requirements"]
    assert result["verdict"]["development"]["status"] == result["verdict"]["testing"]["status"] == "unknown"


def test_verify_rejects_another_revision(tmp_path, source):
    out = tmp_path / "отчёт.md"
    run_cli(tmp_path, source, out, "--offline-lint", "--no-cache")
    run_cli(tmp_path, "verify", out.with_suffix(".json"), source)
    source.write_text(EXAMPLE.replace("оперативно", "за две минуты"), encoding="utf8")
    run_cli(tmp_path, "verify", out.with_suffix(".json"), source, expected=contracts.EXIT_VERIFY_FAILED)


def test_anthropic_without_team_key(tmp_path, source):
    out = tmp_path / "no-key.md"
    run_cli(tmp_path, source, out, "--provider", "anthropic", "--no-cache")
    result = report(out)["run"]
    assert result["mode"] == "rules_only" and result["model"] is None
    assert result["status"] == "partial" and result["calls"]["physical"] == 0
    assert "ANTHROPIC_API_KEY" in " ".join(result["status_reasons"])
    run_cli(tmp_path, "verify", out.with_suffix(".json"), source)


def test_mock_cold_and_warm(tmp_path, source):
    cache = tmp_path / "общий кэш"
    counts = []
    for name in ("cold", "warm"):
        out = tmp_path / name / "report.md"
        run_cli(tmp_path, source, out, "--provider", "mock", "--cache-dir", cache)
        result = report(out)["run"]
        assert result["mode"] == "mock"
        run_cli(tmp_path, "verify", out.with_suffix(".json"), source)
        counts.append(result["calls"])
    assert counts[0]["physical"] > 0 and counts[0]["cache_hits"] == 0
    assert counts[1]["physical"] == 0 and counts[1]["cache_hits"] == counts[0]["physical"]


def test_sdk_503_stops_after_one_transport_request():
    from bcc_review.providers.anthropic import AnthropicAdapter
    from bcc_review.contracts import ProviderError

    response = {"status": 503, "headers": {"content-type": "application/json"},
                "body": {"type": "error", "error": {"type": "api_error", "message": "Temporarily unavailable"}}}
    adapter = AnthropicAdapter.replay([{"response": response}])
    with pytest.raises(ProviderError) as failure:
        adapter.invoke(model="claude-opus-5-5", messages=[{"role": "user", "content": "Проверка квитанции"}],
                       schema={"type": "object", "properties": {}, "additionalProperties": False}, timeout_s=5)
    assert failure.value.http_status == 503 and failure.value.retryable
    assert adapter.physical_calls == 1


def test_image_only_pdf_reports_unreadable_input(tmp_path):
    import pymupdf

    source = tmp_path / "Страница без текста.pdf"
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 160, 180), False)
    pix.clear_with(170)
    with pymupdf.open() as document:
        page = document.new_page()
        page.insert_image(page.rect, stream=pix.tobytes("png"))
        document.save(source)

    out = tmp_path / "report.md"
    run_cli(tmp_path, source, out, "--offline-lint", "--no-cache", "--fail-on", "partial",
            expected=contracts.EXIT_PARTIAL)
    result = report(out)
    assert not result["requirements"] and result["run"]["status"] == "failed"
    assert any(w["code"] == "partial_read" for w in result["document"]["warnings"])


def test_interrupted_replacement_keeps_committed_json(tmp_path, monkeypatch):
    path = tmp_path / "report.json"
    atomic_write_json(path, {"run": "previous"})
    before = path.read_bytes()

    def stop_before_replace(src, dest):
        assert dest == path and Path(src).parent == path.parent
        raise InterruptedError("simulated interrupted write")

    monkeypatch.setattr(os, "replace", stop_before_replace)
    with pytest.raises(InterruptedError):
        atomic_write_json(path, {"run": "new"})
    assert path.read_bytes() == before and list(tmp_path.iterdir()) == [path]
