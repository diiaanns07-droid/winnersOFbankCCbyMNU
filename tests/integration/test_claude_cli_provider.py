"""План Б: движок v1 с провайдером claude_cli (Claude Code CLI без API-ключа).

В bcc/integration адаптера v2 нет — провайдер честно недоступен (rules_only с причиной). В bcc/v2 после
слияния bcc/integration адаптер v2/02 есть, и движок v1 проходит через его настоящий код: сборку команды
`claude -p`, разбор JSON-результата и учёт модели. Запуск CLI подменяется, сети нет.
"""

import importlib.util
import json
import subprocess

import pytest

from bcc_review import contracts as C
from bcc_review.runtime.mock import synth

from .conftest import BCC, run

HAS_ADAPTER = importlib.util.find_spec("bcc_review.v2") is not None and \
    importlib.util.find_spec("bcc_review.v2.providers.claude_cli") is not None


def test_claude_cli_without_adapter_is_honest_rules_only(tmp_path, monkeypatch):
    from bcc_review.runtime import modules

    monkeypatch.setitem(modules.SLOTS, "claude_cli", ("bcc_review.nonexistent_cli:X", None))
    rep = run(tmp_path, BCC, provider="claude_cli")
    C.validate(rep)
    assert rep["run"]["provider"] == "claude_cli" and rep["run"]["requested_model"] == "opus"
    assert rep["run"]["mode"] == "rules_only" and rep["run"]["calls"]["physical"] == 0
    assert any("claude_cli" in r for r in rep["run"]["status_reasons"])


def _fake_cli(cmd, input=None, **kw):
    schema = json.loads(cmd[cmd.index("--json-schema") + 1])
    model = cmd[cmd.index("--model") + 1]
    out = {"type": "result", "subtype": "success", "is_error": False, "result": "", "session_id": "sess-1",
           "structured_output": synth(schema), "num_turns": 1,
           "usage": {"input_tokens": 1200, "output_tokens": 300},
           "modelUsage": {f"claude-{model}-5-5": {"inputTokens": 1200, "outputTokens": 300, "costUSD": 0.01}}}
    return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(out), stderr="")


class FakeRunnerCLI:
    """Настоящий ClaudeCLIProvider v2/02 с подменённым запуском процесса."""

    def __new__(cls, *a, **k):
        from bcc_review.v2.providers.claude_cli import ClaudeCLIProvider

        return ClaudeCLIProvider(binary="claude", runner=_fake_cli)


@pytest.mark.skipif(not HAS_ADAPTER, reason="адаптер claude_cli (v2/02) есть только после слияния в bcc/v2")
def test_v1_engine_through_real_claude_cli_adapter(tmp_path, monkeypatch):
    from bcc_review.runtime import modules

    monkeypatch.setitem(modules.SLOTS, "claude_cli", ("tests.integration.test_claude_cli_provider:FakeRunnerCLI", None))
    rep = run(tmp_path, BCC, provider="claude_cli", use_cache=False)
    C.validate(rep)
    assert C.evidence_errors(rep) == []
    assert rep["run"]["mode"] == "rules_plus_llm" and rep["run"]["calls"]["physical"] > 0
    assert rep["run"]["model"] and "opus" in rep["run"]["model"]
    assert rep["run"]["calls"]["failed"] == 0
