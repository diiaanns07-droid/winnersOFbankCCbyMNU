"""Провайдер ``claude_cli``: Claude Code CLI (``claude -p``) как LLM без API-ключа (№02).

Интерфейс — CONTRACT.md, раздел 3::

    ClaudeCLIProvider().invoke(model=..., messages=[{"role", "content"}], schema=..., timeout_s=...)
        -> {"data", "usage", "model", "request_id", "stop_reason", "cost_usd", "meta"}

Вызов: ``claude -p --output-format json --tools "" --model M --json-schema S --system-prompt-file F``,
текст пользователя — через stdin (без ограничений длины командной строки). Системный промпт — во
временном файле: так не упираемся в лимит 32 КБ командной строки Windows и не ломаем кавычки.

Ошибки — ``bcc_review.contracts.ProviderError`` с ``kind`` из контракта v1; временные
(``rate_limit``, ``overloaded``, ``server``, ``timeout``, ``network``) повторяет ``LLMClient``.
CLI сам повторяет сбои API внутри одного запуска, поэтому провайдер своих повторов не делает.

Переменные окружения:

* ``CLAUDE_CLI_MODEL`` — модель по умолчанию (``opus``, ``sonnet``, ``haiku`` или полный ID), по умолчанию ``opus``;
* ``CLAUDE_CLI_EFFORT`` — ``low|medium|high|xhigh|max``, пусто — по умолчанию CLI;
* ``CLAUDE_CLI_FALLBACK_MODEL`` — запасная модель CLI при перегрузке (``--fallback-model``), ``off`` — без неё;
  по умолчанию ``sonnet`` (для основной ``sonnet`` — ``opus``);
* ``CLAUDE_CLI_BIN`` — путь к исполняемому файлу ``claude`` (по умолчанию ищется в PATH, на Windows — ``claude.exe``/``claude.cmd``);
* ``CLAUDE_CLI_TIMEOUT_S`` — нижняя граница тайм-аута одного вызова, по умолчанию 600 с;
* ``CLAUDE_CLI_LOG`` — файл JSONL для журнала вызовов (необязательно).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from bcc_review.contracts import ProviderError

from . import profiles

__all__ = ["ClaudeCLIProvider", "classify_cli_result", "find_cli", "parse_cli_output"]

PROVIDER = "claude_cli"
DEFAULT_MODEL = "opus"
DEFAULT_TIMEOUT_FLOOR_S = 600.0
_CLI_LIMIT_VAR = "CLAUDE_CODE_MAX_OUTPUT_TOKENS"   # переменная самого claude -p: лимит ответа
MIN_OUTPUT_TOKENS = 64000  # рассуждения входят в лимит: haiku на линзе — 31 тыс. ток., из них 22 тыс. рассуждения
EFFORT_LEVELS = ("low", "medium", "high", "xhigh", "max")
INSTALL_HELP = ("Установите Claude Code (https://claude.com/claude-code): «npm install -g @anthropic-ai/claude-code», "
                "затем один раз выполните «claude» и войдите в аккаунт.")

Runner = Callable[..., "subprocess.CompletedProcess[str]"]


def _is_windows() -> bool:
    return os.name == "nt"


def find_cli(env: Mapping[str, str] | None = None, which: Callable[[str], str | None] | None = None) -> list[str] | None:
    """Команда запуска CLI списком аргументов или ``None``, если CLI не найден.

    На Windows предпочитаем ``claude.exe`` (нативная установка). Для ``claude.cmd`` (установка через npm)
    запускаем ``node cli.js`` напрямую: через cmd.exe пустой аргумент ``--tools ""`` и кавычки в JSON-схеме
    передаются ненадёжно.
    """
    env = os.environ if env is None else env
    which = which or shutil.which  # поиск в момент вызова: подмена shutil.which в тестах действует
    explicit = (env.get("CLAUDE_CLI_BIN") or "").strip()
    if explicit:
        return [explicit]
    if not _is_windows():
        path = which("claude")
        return [path] if path else None
    for name in ("claude.exe", "claude"):
        path = which(name)
        if path and path.lower().endswith(".exe"):
            return [path]
    cmd = which("claude.cmd") or which("claude")
    if not cmd:
        return None
    base = Path(cmd).parent
    script = base / "node_modules" / "@anthropic-ai" / "claude-code" / "cli.js"
    node = which("node") or str(base / "node.exe")
    if script.exists() and node:
        return [node, str(script)]
    return [cmd]


def _strip_fence(text: str) -> str:
    s = (text or "").strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z]*\s*", "", s)
        s = re.sub(r"\s*```$", "", s)
    return s.strip()


def parse_cli_output(stdout: str) -> dict[str, Any] | None:
    """JSON-объект результата из stdout CLI (``--output-format json``); ``None``, если его нет."""
    text = (stdout or "").strip()
    if not text:
        return None
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
        if isinstance(obj, list):  # формат stream/verbose: берём последнее событие result
            for item in reversed(obj):
                if isinstance(item, dict) and item.get("type") == "result":
                    return item
    except json.JSONDecodeError:
        pass
    for line in reversed(text.splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                return obj
    return None


_RESET_RE = re.compile(r"\|(\d{9,13})\b")


def classify_cli_result(out: Mapping[str, Any] | None, *, returncode: int, stderr: str, model: str) -> ProviderError:
    """Ошибка CLI → ProviderError с понятным русским сообщением и советом."""
    out = out or {}
    status = out.get("api_error_status")
    try:
        status = int(status) if status is not None else None
    except (TypeError, ValueError):
        status = None
    etype = str(out.get("api_error_type") or "")
    result = str(out.get("result") or "")
    subtype = str(out.get("subtype") or "")
    text = f"{result}\n{stderr or ''}"
    low = text.lower()
    tail = result.strip()[:300] or (stderr or "").strip()[-300:]

    def err(kind: str, message: str, retry_after: float | None = None) -> ProviderError:
        return ProviderError(kind, f"{message} [claude -p, модель {model}: {tail}]" if tail else message,
                             retry_after_s=retry_after, status=status, request_id=out.get("session_id"), model=model)

    if ("output token maximum" in low or "exceeded the" in low and "output token" in low
            or "max output tokens" in low or out.get("stop_reason") == "max_tokens"):
        return err("truncated", "Ответ модели обрезан по лимиту выходных токенов (claude -p).")
    if ("usage limit" in low or re.search(r"hit your [\w\- ]*limit", low) or "limit reached" in low
            or "out of extra usage" in low or "credit balance is too low" in low):
        retry = None
        m = _RESET_RE.search(result)
        if m:
            ts = int(m.group(1))
            ts = ts / 1000 if ts > 10**11 else ts
            retry = max(0.0, ts - time.time())
        reset = re.search(r"resets? (?:at )?([^\]\n·|]{1,40})", result, flags=re.IGNORECASE)
        when = f" Сброс лимита: {reset.group(1).strip()}." if reset else ""
        return err("quota", f"Исчерпан лимит подписки Claude Code.{when} До сброса выберите другую модель "
                            "(--model haiku) или провайдера (--provider gemini с GEMINI_API_KEY).", retry)
    if status == 401 or status == 403 or etype in ("authentication_error", "permission_error") or any(
            s in low for s in ("invalid api key", "please run /login", "not logged in", "oauth token", "/login")):
        return err("auth", "Claude Code не авторизован. Выполните «claude» в терминале и войдите в аккаунт "
                           "(или задайте ANTHROPIC_API_KEY и используйте --provider anthropic).")
    if status == 404 or etype == "not_found_error" or "issue with the selected model" in low:
        return err("not_found", f"Модель «{model}» недоступна в Claude Code. Укажите opus, sonnet или haiku "
                                "(--model или CLAUDE_CLI_MODEL).")
    if status == 429 or etype == "rate_limit_error" or "rate limit" in low or "rate_limit" in low:
        return err("rate_limit", "Слишком много запросов к Claude (429). Повторите позже.")
    if status == 529 or etype == "overloaded_error" or "overloaded" in low:
        return err("overloaded", "Claude временно перегружен (529). Повтор через несколько секунд.")
    if status in (408, 504) or "timed out" in low or "timeout" in low:
        return err("timeout", "Claude не ответил вовремя (тайм-аут API).")
    if status is not None and status >= 500 or etype == "api_error":
        return err("server", f"Сбой сервера Claude API (HTTP {status}).")
    if "prompt is too long" in low or "context" in low and "too long" in low:
        return err("bad_request", "Запрос слишком длинный для модели: сократите документ или разбейте этап.")
    if status == 400 or etype == "invalid_request_error":
        return err("bad_request", "Claude отклонил запрос (400): проверьте схему ответа и параметры.")
    if "max_tokens" in low or "max output tokens" in low or out.get("stop_reason") == "max_tokens":
        return err("truncated", "Ответ модели обрезан по лимиту выходных токенов.")
    if "structured" in subtype or "max_turns" in subtype or "structured output" in low:
        return err("invalid_output", "Модель не смогла выдать JSON по схеме этапа.")
    if any(s in low for s in ("econnrefused", "enotfound", "network", "fetch failed", "socket hang up", "econnreset")):
        return err("network", "Нет соединения с Claude API. Проверьте сеть и прокси.")
    if not out and returncode != 0:
        return err("unknown", f"claude -p завершился с кодом {returncode} без ответа.")
    return err("unknown", f"claude -p вернул ошибку ({subtype or 'error'}).")


def _usage(out: Mapping[str, Any]) -> dict[str, Any]:
    u = out.get("usage") or {}

    def num(key: str) -> int:
        try:
            return int(u.get(key) or 0)
        except (TypeError, ValueError):
            return 0

    fresh, created, read = num("input_tokens"), num("cache_creation_input_tokens"), num("cache_read_input_tokens")
    details = u.get("output_tokens_details") or {}
    usage: dict[str, Any] = {
        "input_tokens": fresh + created + read,
        "output_tokens": num("output_tokens"),
        "cache_creation_input_tokens": created,
        "cache_read_input_tokens": read,
    }
    if isinstance(details, Mapping) and details.get("thinking_tokens") is not None:
        usage["thinking_tokens"] = int(details.get("thinking_tokens") or 0)
    cost = out.get("total_cost_usd")
    if isinstance(cost, (int, float)):
        usage["cost_usd"] = float(cost)
    return usage


def _models_used(out: Mapping[str, Any], requested: str) -> list[str]:
    mu = out.get("modelUsage") or {}
    if not isinstance(mu, Mapping) or not mu:
        return [requested]

    def weight(item: tuple[str, Any]) -> float:
        v = item[1] if isinstance(item[1], Mapping) else {}
        return float(v.get("outputTokens") or 0) + float(v.get("costUSD") or 0) * 1e6

    return [name for name, _ in sorted(mu.items(), key=weight, reverse=True)]


def _env_float(env: Mapping[str, str], name: str, default: float) -> float:
    raw = (env.get(name) or "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        raise ProviderError("not_configured", f"{name}={raw!r}: ожидается число секунд.") from None


class ClaudeCLIProvider:
    """``claude -p`` как провайдер. ``runner`` и ``which`` подменяются в тестах."""

    name = PROVIDER
    handles_retries = False  # повторы делает LLMClient; CLI сам повторяет сбои API внутри запуска

    def __init__(self, *, model: str | None = None, effort: str | None = None, fallback_model: str | None = None,
                 binary: Sequence[str] | str | None = None, timeout_floor_s: float | None = None,
                 env: Mapping[str, str] | None = None, runner: Runner | None = None,
                 which: Callable[[str], str | None] = shutil.which, log_path: str | None = None) -> None:
        env = os.environ if env is None else env
        self._env = env
        self.default_model = (model or env.get("CLAUDE_CLI_MODEL") or DEFAULT_MODEL).strip()
        effort = (effort if effort is not None else env.get("CLAUDE_CLI_EFFORT") or "").strip().lower()
        if effort and effort not in EFFORT_LEVELS:
            raise ProviderError("not_configured", f"CLAUDE_CLI_EFFORT={effort!r}: допустимо {', '.join(EFFORT_LEVELS)}.")
        self.effort = effort or None
        self.fallback_model = fallback_model if fallback_model is not None else env.get("CLAUDE_CLI_FALLBACK_MODEL")
        self.timeout_floor_s = (float(timeout_floor_s) if timeout_floor_s is not None
                                else _env_float(env, "CLAUDE_CLI_TIMEOUT_S", DEFAULT_TIMEOUT_FLOOR_S))
        if isinstance(binary, str):
            binary = [binary]
        self._binary = list(binary) if binary else None
        self._which = which
        self._runner = runner or subprocess.run
        self.log_path = log_path if log_path is not None else env.get("CLAUDE_CLI_LOG")

    # ------------------------------------------------------------------ helpers

    def command(self) -> list[str]:
        if self._binary is None:
            found = find_cli(self._env, self._which)
            if not found:
                raise ProviderError("not_configured", f"Не найдена программа «claude» (Claude Code CLI). {INSTALL_HELP}")
            self._binary = found
        return list(self._binary)

    def _fallback_for(self, model: str) -> str | None:
        raw = (self.fallback_model or "").strip()
        if raw.lower() in ("off", "none", "no", "0", "false"):
            return None
        if not raw:
            raw = "opus" if "sonnet" in model.lower() else "sonnet"
        return None if raw.lower() == model.lower() else raw

    def effort_for(self, model: str, stage: str = "") -> str | None:
        """``--effort``: явное (аргумент, ``CLAUDE_CLI_EFFORT``) важнее профиля модели и этапа (``profiles.py``)."""
        return self.effort or profiles.claude_effort(model, stage)

    def build_command(self, model: str, schema: Mapping[str, Any], system_file: str | None,
                      stage: str = "") -> list[str]:
        cmd = self.command() + ["-p", "--output-format", "json", "--tools", "", "--model", model,
                                "--json-schema", json.dumps(schema, ensure_ascii=False, separators=(",", ":")),
                                "--no-session-persistence", "--strict-mcp-config"]
        if system_file:
            cmd += ["--system-prompt-file", system_file]
        effort = self.effort_for(model, stage)
        if effort:
            cmd += ["--effort", effort]
        fallback = self._fallback_for(model)
        if fallback:
            cmd += ["--fallback-model", fallback]
        return cmd

    def _log(self, record: Mapping[str, Any]) -> None:
        if not self.log_path:
            return
        try:
            with open(self.log_path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError:
            pass

    # ------------------------------------------------------------------ public

    def invoke(self, *, model: str | None, messages: Sequence[Mapping[str, Any]], schema: Mapping[str, Any],
               timeout_s: float, max_output_tokens: int | None = None, stage: str = "", **_: Any) -> dict[str, Any]:
        model = (model or self.default_model).strip()
        system = "\n\n".join(str(m.get("content") or "") for m in messages if m.get("role") == "system").strip()
        user = "\n\n".join(str(m.get("content") or "") for m in messages if m.get("role") != "system").strip()
        if not user:
            raise ProviderError("bad_request", "Пустой запрос: нет сообщения user.", model=model)
        timeout = max(float(timeout_s or 0), self.timeout_floor_s)

        child_env = dict(self._env)
        # Лимит этапа не опускает лимит CLI: обрезка дороже лишних токенов (рассуждения тоже в лимите).
        # Переменная самого Claude Code CLI: наш код её не читает, только задаёт, если пользователь не задал сам.
        if _CLI_LIMIT_VAR not in child_env or not str(child_env[_CLI_LIMIT_VAR]).strip():
            child_env[_CLI_LIMIT_VAR] = str(max(int(max_output_tokens or 0), MIN_OUTPUT_TOKENS))
        tmp_path = None
        if system:
            fd, tmp_path = tempfile.mkstemp(prefix="bcc_sys_", suffix=".md")
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(system)
        cmd = self.build_command(model, schema, tmp_path, stage)
        started = time.monotonic()
        try:
            proc = self._runner(cmd, input=user, capture_output=True, text=True, encoding="utf-8",
                                errors="replace", timeout=timeout, env=child_env)
        except subprocess.TimeoutExpired:
            raise ProviderError("timeout", f"claude -p не ответил за {timeout:.0f} с (модель {model}). "
                                           "Увеличьте CLAUDE_CLI_TIMEOUT_S или выберите модель быстрее.",
                                model=model) from None
        except FileNotFoundError:
            raise ProviderError("not_configured", f"Не удалось запустить «{cmd[0]}». {INSTALL_HELP}", model=model) from None
        except OSError as exc:
            raise ProviderError("not_configured", f"Не удалось запустить claude -p: {exc}. {INSTALL_HELP}",
                                model=model) from None
        finally:
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
        seconds = time.monotonic() - started
        out = parse_cli_output(proc.stdout)
        if out is None or out.get("is_error") or (proc.returncode != 0 and out.get("structured_output") is None):
            error = classify_cli_result(out, returncode=proc.returncode, stderr=proc.stderr or "", model=model)
            self._log({"model": model, "seconds": round(seconds, 1), "error": error.kind, "message": error.message[:300]})
            raise error

        data = out.get("structured_output")
        if data is None:
            try:
                data = json.loads(_strip_fence(str(out.get("result") or "")))
            except (TypeError, ValueError):
                if out.get("stop_reason") == "max_tokens":
                    raise ProviderError("truncated", "Ответ модели обрезан по лимиту выходных токенов (claude -p).",
                                        model=model) from None
                raise ProviderError("invalid_output", "claude -p не вернул structured_output, а текст ответа — не JSON.",
                                    model=model, request_id=out.get("session_id")) from None
        if out.get("stop_reason") == "max_tokens":
            raise ProviderError("truncated", "Ответ модели обрезан по лимиту выходных токенов (claude -p).", model=model)

        used = _models_used(out, model)
        usage = _usage(out)
        if out.get("num_turns"):
            usage["num_turns"] = int(out.get("num_turns") or 0)   # > 2 — CLI переспрашивал модель (ответ не по схеме)
        self._log({"model": used[0], "requested": model, "seconds": round(seconds, 1), "usage": usage,
                   "system_chars": len(system), "user_chars": len(user)})
        return {
            "data": data,
            "usage": usage,
            "model": used[0],
            "request_id": out.get("session_id") or "",
            "stop_reason": "end_turn",
            "cost_usd": usage.get("cost_usd"),
            "meta": {"provider": PROVIDER, "requested_model": model, "models_used": used,
                     "fallback_used": used[0] != model and model.lower() not in used[0].lower(),
                     "seconds": round(seconds, 2), "num_turns": out.get("num_turns"),
                     "effort": self.effort_for(model, stage)},
        }

    def check(self) -> dict[str, Any]:
        """Версия CLI без вызова модели (для doctor)."""
        cmd = self.command() + ["--version"]
        try:
            proc = self._runner(cmd, capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ProviderError("not_configured", f"claude --version не запустился: {exc}. {INSTALL_HELP}") from None
        return {"command": cmd[:-1], "version": (proc.stdout or proc.stderr or "").strip().splitlines()[0:1]}


def _main(argv: Sequence[str] | None = None) -> int:  # pragma: no cover - ручная проверка
    import argparse
    p = argparse.ArgumentParser(prog="python -m bcc_review.v2.providers.claude_cli",
                                description="Пробный вызов claude -p с маленькой схемой")
    p.add_argument("--model", default=None)
    a = p.parse_args(argv)
    schema = {"type": "object", "additionalProperties": False, "required": ["answer"],
              "properties": {"answer": {"type": "string"}}}
    try:
        r = ClaudeCLIProvider().invoke(model=a.model, schema=schema, timeout_s=120, messages=[
            {"role": "system", "content": "Отвечай только JSON по схеме, по-русски."},
            {"role": "user", "content": "Одним словом: какого цвета небо днём?"}])
    except ProviderError as exc:
        print(f"Ошибка ({exc.kind}): {exc.message}")
        return 1
    print(json.dumps({k: r[k] for k in ("data", "model", "usage", "meta")}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(_main())
