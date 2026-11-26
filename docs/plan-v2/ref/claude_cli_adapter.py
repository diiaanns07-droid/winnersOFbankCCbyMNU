"""Experimental adapter: Claude Code CLI (`claude -p`) as LLM provider.

Drop-in replacement for bcc_review.providers.anthropic:AnthropicAdapter (scratch experiment only).
"""
from __future__ import annotations

import json
import os
import subprocess
import time
from typing import Any, Mapping, Sequence

from bcc_review.contracts import ProviderError

PROVIDER = "anthropic"


class AnthropicAdapter:
    provider = PROVIDER

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.default_model = os.environ.get("CLAUDE_CLI_MODEL", "opus")
        self.log_path = os.environ.get("CLAUDE_CLI_LOG")

    def invoke(self, *, model: str | None, messages: Sequence[Mapping[str, Any]], schema: Mapping[str, Any],
               timeout_s: float) -> dict[str, Any]:
        model = (model or self.default_model).strip()
        system = "\n\n".join(str(m["content"]) for m in messages if m.get("role") == "system")
        user = "\n\n".join(str(m["content"]) for m in messages if m.get("role") != "system")
        cmd = ["claude", "-p", "--output-format", "json", "--tools", "", "--model", model,
               "--json-schema", json.dumps(schema, ensure_ascii=False)]
        if system:
            cmd += ["--system-prompt", system]
        t0 = time.monotonic()
        try:
            r = subprocess.run(cmd, input=user, capture_output=True, text=True, timeout=max(timeout_s, 900))
        except subprocess.TimeoutExpired as exc:
            raise ProviderError("timeout", f"claude -p timeout: {exc}")
        dt = time.monotonic() - t0
        if r.returncode != 0 and not r.stdout.strip():
            raise ProviderError("server", f"claude -p rc={r.returncode}: {r.stderr[-500:]}")
        try:
            out = json.loads(r.stdout)
        except json.JSONDecodeError:
            raise ProviderError("invalid_output", f"claude -p non-json: {r.stdout[-500:]}")
        if out.get("is_error"):
            raise ProviderError("server", f"claude -p error: {str(out.get('result'))[:500]}")
        data = out.get("structured_output")
        if data is None:
            try:
                data = json.loads(out.get("result") or "")
            except Exception:
                raise ProviderError("invalid_output", "no structured_output")
        mu = out.get("modelUsage") or {}
        actual = next(iter(mu.keys()), model)
        u = out.get("usage") or {}
        usage = {"input_tokens": int(u.get("input_tokens", 0)) + int(u.get("cache_creation_input_tokens", 0)),
                 "output_tokens": int(u.get("output_tokens", 0)),
                 "cache_read_input_tokens": int(u.get("cache_read_input_tokens", 0))}
        if self.log_path:
            with open(self.log_path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps({"model": actual, "seconds": round(dt, 1), "usage": usage,
                                     "cost_usd": out.get("total_cost_usd"), "system_chars": len(system),
                                     "user_chars": len(user)}, ensure_ascii=False) + "\n")
        return {"data": data, "usage": usage, "model": actual, "request_id": out.get("session_id"),
                "stop_reason": "end_turn"}
