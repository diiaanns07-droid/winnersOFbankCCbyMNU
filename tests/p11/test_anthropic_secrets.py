"""Ключ и приватные заголовки не попадают в сообщения об ошибках и в журнал."""

from __future__ import annotations

import json
import logging
import traceback

import httpx2
import pytest

from bcc_review.providers.anthropic import AnthropicAdapter, ProviderError, RecordedTransport, redact
from conftest import load, models

SECRET = "sk-ant-api03-TESTSECRET-abcdefghijklmnopqrstuvwxyz0123456789"


class _Capture(RecordedTransport):
    """Как RecordedTransport, но запоминает значение Authorization, чтобы тест был содержательным."""

    def handle_request(self, request: httpx2.Request) -> httpx2.Response:
        self.auth_values = getattr(self, "auth_values", []) + [request.headers.get("authorization")]
        return super().handle_request(request)


def _live_like(*records):
    transport = _Capture([load(r) for r in records], models=models())
    return AnthropicAdapter(api_key=SECRET, transport=transport, mode="live", env={}), transport


def _all_text(adapter, errors, caplog):
    parts = [caplog.text, json.dumps(adapter.journal, ensure_ascii=False), repr(adapter),
             json.dumps(adapter.passport(), ensure_ascii=False, default=str)]
    for err in errors:
        parts += [str(err), repr(err), str(getattr(err, "detail", "")),
                  "".join(traceback.format_exception(err))]
    return "\n".join(parts)


def test_no_key_in_errors_journal_or_logs(messages, schema, caplog):
    caplog.set_level(logging.DEBUG)  # включая отладочные логи SDK и httpx2
    adapter, transport = _live_like("auth_401_echo_key", "connect_raise", "rate_limit_429_retry_after",
                                    "success_candidates")
    errors = []
    for _ in range(3):
        with pytest.raises(ProviderError) as info:
            adapter.invoke(model="claude-opus-5-5", messages=messages, schema=schema, timeout_s=10)
        errors.append(info.value)
    adapter.invoke(model="claude-opus-5-5", messages=messages, schema=schema, timeout_s=10)

    # ключ действительно уходил в заголовке Authorization (SDK 2.x)
    assert transport.auth_values and all(v == f"Bearer {SECRET}" for v in transport.auth_values)
    blob = _all_text(adapter, errors, caplog)
    assert SECRET not in blob
    assert "TESTSECRET" not in blob
    assert "ECHOEDSECRET" not in blob  # ключ, который «сервер» вернул эхом в сообщении
    assert "Bearer sk-" not in blob
    assert [e.kind for e in errors] == ["auth", "network", "rate_limit"]
    assert adapter.passport()["credential"] == "argument"
    assert adapter.passport()["run_mode"] == "rules_plus_llm"


def test_redact_patterns():
    text = (f"x-api-key: {SECRET} Authorization: Bearer abcdefghijklmnop "
            "{'authorization': 'Bearer qwertyuiopasdf'} anthropic-api-key=zzzzzzzzzz")
    out = redact(text, secrets=[SECRET])
    for leaked in (SECRET, "abcdefghijklmnop", "qwertyuiopasdf", "zzzzzzzzzz"):
        assert leaked not in out
