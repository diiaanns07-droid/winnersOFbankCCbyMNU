"""№02: провайдер claude_cli на записанных ответах CLI (без сети и без запуска claude)."""

from __future__ import annotations

import json
import subprocess

import pytest

from bcc_review.contracts import ProviderError
from bcc_review.v2.providers.claude_cli import ClaudeCLIProvider, find_cli, parse_cli_output

SCHEMA = {"type": "object", "required": ["answer"], "properties": {"answer": {"type": "string"}}}
MESSAGES = [{"role": "system", "content": "Системный промпт"}, {"role": "user", "content": "Документ и задание"}]

OK_OUT = {
    "type": "result", "subtype": "success", "is_error": False, "stop_reason": "tool_use", "num_turns": 2,
    "session_id": "sess-1", "total_cost_usd": 0.0123, "result": '{"answer":"да"}',
    "structured_output": {"answer": "да"},
    "usage": {"input_tokens": 10, "cache_creation_input_tokens": 2000, "cache_read_input_tokens": 500,
              "output_tokens": 140, "output_tokens_details": {"thinking_tokens": 80}},
    "modelUsage": {"claude-opus-5-5": {"outputTokens": 140, "costUSD": 0.0123}},
}


def error_out(status, etype, result):
    return {"type": "result", "subtype": "success", "is_error": True, "api_error_status": status,
            "api_error_type": etype, "result": result, "session_id": "sess-e", "modelUsage": {}, "usage": {}}


class FakeRunner:
    def __init__(self, stdout="", returncode=0, stderr="", exc=None):
        self.stdout, self.returncode, self.stderr, self.exc = stdout, returncode, stderr, exc
        self.calls = []

    def __call__(self, cmd, **kw):
        self.calls.append((cmd, kw))
        if self.exc:
            raise self.exc
        return subprocess.CompletedProcess(cmd, self.returncode, self.stdout, self.stderr)


def provider(runner, **kw):
    return ClaudeCLIProvider(binary=["claude"], runner=runner, env={"PATH": "/bin"}, **kw)


def test_success_parses_structured_output_usage_cost_and_model():
    runner = FakeRunner(json.dumps(OK_OUT))
    r = provider(runner).invoke(model="opus", messages=MESSAGES, schema=SCHEMA, timeout_s=30)
    assert r["data"] == {"answer": "да"}
    assert r["model"] == "claude-opus-5-5"
    assert r["stop_reason"] == "end_turn"
    assert r["request_id"] == "sess-1"
    assert r["usage"]["input_tokens"] == 2510 and r["usage"]["output_tokens"] == 140
    assert r["usage"]["cache_read_input_tokens"] == 500
    assert r["cost_usd"] == pytest.approx(0.0123)
    assert r["meta"]["fallback_used"] is False
    cmd, kw = runner.calls[0]
    assert cmd[:2] == ["claude", "-p"]
    assert cmd[cmd.index("--tools") + 1] == ""
    assert cmd[cmd.index("--model") + 1] == "opus"
    assert json.loads(cmd[cmd.index("--json-schema") + 1]) == SCHEMA
    assert "--system-prompt-file" in cmd and "--no-session-persistence" in cmd
    assert kw["input"] == "Документ и задание"          # текст пользователя — через stdin
    assert "Системный промпт" not in " ".join(cmd)      # системный промпт — во временном файле
    assert kw["timeout"] >= 600                         # нижняя граница тайм-аута


def test_system_prompt_file_holds_system_text():
    seen = {}

    def runner(cmd, **kw):
        path = cmd[cmd.index("--system-prompt-file") + 1]
        with open(path, encoding="utf-8") as fh:
            seen["system"] = fh.read()
        return subprocess.CompletedProcess(cmd, 0, json.dumps(OK_OUT), "")

    provider(runner).invoke(model="sonnet", messages=MESSAGES, schema=SCHEMA, timeout_s=30)
    assert seen["system"] == "Системный промпт"


def test_effort_and_fallback_flags():
    runner = FakeRunner(json.dumps(OK_OUT))
    provider(runner, effort="high").invoke(model="opus", messages=MESSAGES, schema=SCHEMA, timeout_s=30)
    cmd = runner.calls[0][0]
    assert cmd[cmd.index("--effort") + 1] == "high"
    assert cmd[cmd.index("--fallback-model") + 1] == "sonnet"
    runner2 = FakeRunner(json.dumps(OK_OUT))
    provider(runner2).invoke(model="sonnet", messages=MESSAGES, schema=SCHEMA, timeout_s=30)
    assert runner2.calls[0][0][runner2.calls[0][0].index("--fallback-model") + 1] == "opus"
    runner3 = FakeRunner(json.dumps(OK_OUT))
    provider(runner3, fallback_model="off").invoke(model="opus", messages=MESSAGES, schema=SCHEMA, timeout_s=30)
    assert "--fallback-model" not in runner3.calls[0][0]


def test_env_model_and_bad_effort():
    p = ClaudeCLIProvider(binary=["claude"], runner=FakeRunner(json.dumps(OK_OUT)),
                          env={"CLAUDE_CLI_MODEL": "haiku", "CLAUDE_CLI_EFFORT": "low"})
    assert p.default_model == "haiku" and p.effort == "low"
    with pytest.raises(ProviderError) as e:
        ClaudeCLIProvider(binary=["claude"], env={"CLAUDE_CLI_EFFORT": "turbo"})
    assert e.value.kind == "not_configured"


def test_fallback_model_detected_from_model_usage():
    out = dict(OK_OUT, modelUsage={"claude-sonnet-5-5": {"outputTokens": 140}})
    r = provider(FakeRunner(json.dumps(out))).invoke(model="opus", messages=MESSAGES, schema=SCHEMA, timeout_s=30)
    assert r["model"] == "claude-sonnet-5-5" and r["meta"]["fallback_used"] is True


def test_result_text_json_when_no_structured_output():
    out = dict(OK_OUT, structured_output=None, result='```json\n{"answer": "нет"}\n```')
    r = provider(FakeRunner(json.dumps(out))).invoke(model="opus", messages=MESSAGES, schema=SCHEMA, timeout_s=30)
    assert r["data"] == {"answer": "нет"}


def test_result_not_json_is_invalid_output():
    out = dict(OK_OUT, structured_output=None, result="Извините, не могу")
    with pytest.raises(ProviderError) as e:
        provider(FakeRunner(json.dumps(out))).invoke(model="opus", messages=MESSAGES, schema=SCHEMA, timeout_s=30)
    assert e.value.kind == "invalid_output"


@pytest.mark.parametrize("out,kind,transient", [
    (error_out(404, "not_found_error", "There's an issue with the selected model (x)."), "not_found", False),
    (error_out(429, "rate_limit_error", "Rate limited"), "rate_limit", True),
    (error_out(529, "overloaded_error", "Overloaded"), "overloaded", True),
    (error_out(500, "api_error", "Internal server error"), "server", True),
    (error_out(401, "authentication_error", "Invalid API key · Please run /login"), "auth", False),
    (error_out(None, "", "Claude AI usage limit reached|1795730000"), "quota", False),
    (error_out(400, "invalid_request_error", "Prompt is too long"), "bad_request", False),
    (error_out(400, "invalid_request_error", "bad schema"), "bad_request", False),
])
def test_error_kinds(out, kind, transient):
    with pytest.raises(ProviderError) as e:
        provider(FakeRunner(json.dumps(out), returncode=1)).invoke(model="opus", messages=MESSAGES, schema=SCHEMA,
                                                                    timeout_s=30)
    assert e.value.kind == kind
    assert e.value.transient is transient
    assert e.value.message  # понятное сообщение
    assert "Traceback" not in e.value.message


def test_quota_retry_after_from_reset_epoch():
    out = error_out(None, "", "Claude AI usage limit reached|9999999999")
    with pytest.raises(ProviderError) as e:
        provider(FakeRunner(json.dumps(out), returncode=1)).invoke(model="opus", messages=MESSAGES, schema=SCHEMA,
                                                                    timeout_s=30)
    assert e.value.retry_after_s and e.value.retry_after_s > 0


def test_nonzero_exit_without_stdout():
    with pytest.raises(ProviderError) as e:
        provider(FakeRunner("", returncode=1, stderr="fetch failed: ECONNREFUSED")).invoke(
            model="opus", messages=MESSAGES, schema=SCHEMA, timeout_s=30)
    assert e.value.kind == "network"


def test_timeout():
    runner = FakeRunner(exc=subprocess.TimeoutExpired("claude", 600))
    with pytest.raises(ProviderError) as e:
        provider(runner).invoke(model="opus", messages=MESSAGES, schema=SCHEMA, timeout_s=30)
    assert e.value.kind == "timeout" and e.value.transient


def test_missing_binary():
    p = ClaudeCLIProvider(env={}, which=lambda name: None)
    with pytest.raises(ProviderError) as e:
        p.invoke(model="opus", messages=MESSAGES, schema=SCHEMA, timeout_s=30)
    assert e.value.kind == "not_configured" and "npm install" in e.value.message
    runner = FakeRunner(exc=FileNotFoundError("claude"))
    with pytest.raises(ProviderError) as e2:
        provider(runner).invoke(model="opus", messages=MESSAGES, schema=SCHEMA, timeout_s=30)
    assert e2.value.kind == "not_configured"


def test_truncated():
    out = dict(OK_OUT, structured_output=None, result='{"answer": "обре', stop_reason="max_tokens")
    with pytest.raises(ProviderError) as e:
        provider(FakeRunner(json.dumps(out))).invoke(model="opus", messages=MESSAGES, schema=SCHEMA, timeout_s=30)
    assert e.value.kind == "truncated"


def test_messages_only_role_and_content_used():
    runner = FakeRunner(json.dumps(OK_OUT))
    msgs = [{"role": "system", "content": "S", "cache": True}, {"role": "user", "content": "U", "extra": 1}]
    provider(runner).invoke(model="opus", messages=msgs, schema=SCHEMA, timeout_s=30)
    assert runner.calls[0][1]["input"] == "U"


def test_parse_cli_output_variants():
    assert parse_cli_output("") is None
    assert parse_cli_output("garbage\n" + json.dumps({"type": "result", "x": 1}))["x"] == 1
    assert parse_cli_output(json.dumps([{"type": "system"}, {"type": "result", "y": 2}]))["y"] == 2


def test_find_cli_env_override_and_path(monkeypatch):
    assert find_cli({"CLAUDE_CLI_BIN": "/opt/claude"}) == ["/opt/claude"]
    monkeypatch.setattr("bcc_review.v2.providers.claude_cli._is_windows", lambda: False)
    assert find_cli({}, which=lambda n: "/usr/bin/claude" if n == "claude" else None) == ["/usr/bin/claude"]
    assert find_cli({}, which=lambda n: None) is None


def test_find_cli_windows_prefers_exe_then_node_script(monkeypatch, tmp_path):
    monkeypatch.setattr("bcc_review.v2.providers.claude_cli._is_windows", lambda: True)
    assert find_cli({}, which=lambda n: r"C:\bin\claude.exe" if n == "claude.exe" else None) == [r"C:\bin\claude.exe"]
    script = tmp_path / "node_modules" / "@anthropic-ai" / "claude-code" / "cli.js"
    script.parent.mkdir(parents=True)
    script.write_text("//")
    cmd = str(tmp_path / "claude.cmd")
    which = {"claude.cmd": cmd, "node": r"C:\node\node.exe"}.get
    assert find_cli({}, which=which) == [r"C:\node\node.exe", str(script)]


# --------------------------------------------------------------------------- записанные ответы настоящего CLI

from pathlib import Path  # noqa: E402

RECORDED = Path(__file__).parent / "fixtures" / "02_providers"


def test_recorded_real_success_haiku():
    raw = (RECORDED / "claude_cli_ok_haiku.json").read_text(encoding="utf-8")
    r = provider(FakeRunner(raw)).invoke(model="haiku", messages=MESSAGES, schema=SCHEMA, timeout_s=30)
    assert r["data"] == {"city": "Астана"}
    assert r["model"] == "claude-haiku-5-5" and r["meta"]["fallback_used"] is False
    assert r["usage"]["input_tokens"] == 2026 and r["usage"]["output_tokens"] == 139
    assert r["cost_usd"] > 0


def test_recorded_real_404_unknown_model():
    raw = (RECORDED / "claude_cli_404_model.json").read_text(encoding="utf-8")
    with pytest.raises(ProviderError) as e:
        provider(FakeRunner(raw, returncode=1, stderr="[claude-code:unrecognized_model]")).invoke(
            model="nonexistent-model-xyz", messages=MESSAGES, schema=SCHEMA, timeout_s=30)
    assert e.value.kind == "not_found" and e.value.status == 404
    assert "opus, sonnet или haiku" in e.value.message
