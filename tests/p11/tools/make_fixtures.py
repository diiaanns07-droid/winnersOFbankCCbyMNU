"""Генератор синтетических фикстур ответов Claude API для tests/p11.

Это НЕ записи реальных вызовов: тела и заголовки собраны вручную по формату
Messages API (SDK anthropic==2.14.0, API 2026-10-21). Каждая фикстура
помечена ``"_synthetic": true``. Перегенерация:

    python tests/p11/tools/make_fixtures.py
"""

from __future__ import annotations

import json
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "fixtures"
MODEL = "claude-opus-5-5"

SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "p11-test: черновик семантического этапа (Candidate + hints)",
    "type": "object",
    "properties": {
        "candidates": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "scope": {"type": "string", "enum": ["requirement", "set"]},
                    "kind": {"type": "string", "minLength": 1},
                    "criterion": {"type": "string", "minLength": 1},
                    "severity": {"type": "string", "enum": ["critical", "major", "minor"]},
                    "title": {"type": "string", "minLength": 1},
                    "impact": {"type": "string"},
                    "req_ids": {"type": "array", "items": {"type": "string"}},
                    "hints": {"type": "array", "minItems": 1, "items": {"$ref": "#/$defs/hint"}},
                    "inspected_block_ids": {"type": ["array", "null"], "items": {"type": "string"}},
                },
                "required": [
                    "scope", "kind", "criterion", "severity", "title",
                    "impact", "req_ids", "hints", "inspected_block_ids",
                ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["candidates"],
    "additionalProperties": False,
    "$defs": {
        "hint": {
            "type": "object",
            "properties": {
                "block_id": {"type": "string", "minLength": 1},
                "quote": {"type": "string", "minLength": 1},
            },
            "required": ["block_id", "quote"],
            "additionalProperties": False,
        }
    },
}

GOOD_DATA = {
    "candidates": [
        {
            "scope": "set",
            "kind": "conflict",
            "criterion": "ISO29148-5.2.6-consistency",
            "severity": "critical",
            "title": "Ф-3 и Ф-4 дают разный исход для второго push в месяце",
            "impact": "Разработчик и тестировщик выберут разные правила отправки",
            "req_ids": ["R-003", "R-004"],
            "hints": [
                {"block_id": "blk-039", "quote": "максимум один push за календарный месяц"},
                {"block_id": "blk-040", "quote": "вызывает push независимо от истории"},
            ],
            "inspected_block_ids": None,
        },
        {
            "scope": "requirement",
            "kind": "ambiguity",
            "criterion": "ISO29148-5.2.5-unambiguous",
            "severity": "major",
            "title": "Не указан часовой пояс календарного месяца",
            "impact": "Покупки на стыке месяцев попадут в разные периоды",
            "req_ids": ["R-002"],
            "hints": [{"block_id": "blk-038", "quote": "по дате совершения покупки"}],
            "inspected_block_ids": None,
        },
    ]
}


def usage(inp: int, out: int, *, cache_read: int = 0, cache_write: int = 0, **extra: object) -> dict:
    return {
        "input_tokens": inp,
        "output_tokens": out,
        "cache_creation_input_tokens": cache_write,
        "cache_read_input_tokens": cache_read,
        "cache_creation": {"ephemeral_5m_input_tokens": cache_write, "ephemeral_1h_input_tokens": 0},
        "service_tier": "standard",
        "inference_geo": "global",
        **extra,
    }


def message(text: str, *, stop: str = "end_turn", model: str = MODEL, u: dict | None = None,
            msg_id: str = "msg_synth_01", stop_details: dict | None = None, extra_blocks: list | None = None) -> dict:
    content = [{"type": "thinking", "thinking": "", "signature": "synthetic-signature"}]
    content += extra_blocks or []
    if text is not None:
        content.append({"type": "text", "text": text})
    return {
        "id": msg_id,
        "type": "message",
        "role": "assistant",
        "model": model,
        "content": content,
        "stop_reason": stop,
        "stop_sequence": None,
        "stop_details": stop_details,
        "usage": u or usage(1200, 340),
    }


def ok(name: str, body: dict, request_id: str, note: str) -> dict:
    return {
        "_synthetic": True,
        "_note": note,
        "name": name,
        "response": {"status": 200, "headers": {"request-id": request_id, "content-type": "application/json"},
                     "body": body},
    }


def err(name: str, status: int, etype: str, msg: str, request_id: str, note: str, *,
        headers: dict | None = None, error_code: str | None = None) -> dict:
    error: dict = {"type": etype, "message": msg}
    if error_code:
        error["details"] = {"error_code": error_code}
    return {
        "_synthetic": True,
        "_note": note,
        "name": name,
        "response": {
            "status": status,
            "headers": {"request-id": request_id, "content-type": "application/json", **(headers or {})},
            "body": {"type": "error", "error": error, "request_id": request_id},
        },
    }


def dumps(obj: object) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def build() -> dict[str, dict]:
    bad_schema = {"candidates": [dict(GOOD_DATA["candidates"][0], severity="blocker", hints=[])]}
    empty_quote = {"candidates": [dict(GOOD_DATA["candidates"][1],
                                       hints=[{"block_id": "blk-038", "quote": ""}])]}
    enum_case = {"candidates": [dict(GOOD_DATA["candidates"][0], severity="Critical", scope="Set")]}
    truncated = dumps(GOOD_DATA)[:180]
    return {
        "model_info": {
            "_synthetic": True,
            MODEL: {
                "id": MODEL, "type": "model", "display_name": "Claude Opus 5.5",
                "created_at": "2026-09-22T00:00:00Z", "max_input_tokens": 1000000, "max_tokens": 128000,
            },
            "claude-opus-4-8": {
                "id": "claude-opus-4-8", "type": "model", "display_name": "Claude Opus 4.8",
                "created_at": "2026-05-01T00:00:00Z", "max_input_tokens": 1000000, "max_tokens": 128000,
            },
        },
        "success_candidates": ok(
            "success_candidates",
            message(dumps(GOOD_DATA), u=usage(5210, 612, cache_read=4096, cache_write=1024)),
            "req_synth_success_01",
            "Успешный ответ JSON outputs: thinking (пустой, display=omitted) + text с JSON по схеме.",
        ),
        "rate_limit_429_retry_after": err(
            "rate_limit_429_retry_after", 429, "rate_limit_error",
            "Number of request tokens has exceeded your per-minute rate limit", "req_synth_429",
            "Временный лимит с Retry-After: 7.", headers={"retry-after": "7"},
        ),
        "rate_limit_429_no_retry_after": err(
            "rate_limit_429_no_retry_after", 429, "rate_limit_error", "Rate limited", "req_synth_429_bare",
            "429 без Retry-After и без error_code: неоднозначный случай.",
        ),
        "spend_cap_429": err(
            "spend_cap_429", 429, "rate_limit_error", "You have reached your monthly spend limit",
            "req_synth_429_cap", "429 со spend-limit (error_code enforced_spend_limit_reached).",
            error_code="enforced_spend_limit_reached",
        ),
        "billing_402": err(
            "billing_402", 402, "billing_error", "Your credit balance is too low", "req_synth_402",
            "402 billing_error.",
        ),
        "auth_401": err(
            "auth_401", 401, "authentication_error", "invalid x-api-key", "req_synth_401",
            "Отказ авторизации.",
        ),
        "auth_401_echo_key": err(
            "auth_401_echo_key", 401, "authentication_error",
            "invalid x-api-key: sk-ant-api03-ECHOEDSECRET-0000000000", "req_synth_401_echo",
            "Сервер (или прокси) эхом вернул ключ в сообщении: проверка редактирования.",
        ),
        "overloaded_529": err(
            "overloaded_529", 529, "overloaded_error", "Overloaded", "req_synth_529", "Перегрузка API.",
            headers={"retry-after-ms": "1"},
        ),
        "server_500": err(
            "server_500", 500, "api_error", "Internal server error", "req_synth_500", "Ошибка сервера.",
        ),
        "gateway_504": err(
            "gateway_504", 504, "timeout_error", "Gateway timeout", "req_synth_504", "Тайм-аут шлюза.",
        ),
        "schema_too_complex_400": err(
            "schema_too_complex_400", 400, "invalid_request_error", "Schema is too complex for compilation.",
            "req_synth_400_schema", "Слишком сложная схема.",
        ),
        "max_tokens_stop": ok(
            "max_tokens_stop",
            message(truncated, stop="max_tokens", u=usage(5210, 16000)),
            "req_synth_max_tokens",
            "HTTP 200, stop_reason=max_tokens, JSON оборван.",
        ),
        "wrong_schema_200": ok(
            "wrong_schema_200", message(dumps(bad_schema)), "req_synth_wrong_schema",
            "HTTP 200, валидный JSON, но severity вне enum и hints пуст.",
        ),
        "empty_quote_200": ok(
            "empty_quote_200", message(dumps(empty_quote)), "req_synth_empty_quote",
            "HTTP 200, валидный JSON; minLength у quote не проверяется API, ловится локально.",
        ),
        "invalid_json_200": ok(
            "invalid_json_200", message('{"candidates": [ {"scope": "set",'), "req_synth_invalid_json",
            "HTTP 200, end_turn, но текст не JSON.",
        ),
        "enum_case_200": ok(
            "enum_case_200", message(dumps(enum_case)), "req_synth_enum_case",
            "Регистр enum не гарантирован документацией: Critical/Set вместо critical/set.",
        ),
        "refusal_200": ok(
            "refusal_200",
            message(None, stop="refusal", stop_details={"type": "refusal", "category": "cyber",
                                                        "explanation": "synthetic"}),
            "req_synth_refusal",
            "HTTP 200, stop_reason=refusal.",
        ),
        "fallback_200": ok(
            "fallback_200",
            message(
                dumps(GOOD_DATA), model="claude-opus-4-8",
                u=usage(5210, 600, iterations=[
                    {"type": "message", "input_tokens": 5210, "output_tokens": 3,
                     "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0},
                    {"type": "fallback_message", "model": "claude-opus-4-8", "input_tokens": 5210,
                     "output_tokens": 597, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0},
                ]),
            ),
            "req_synth_fallback",
            "Серверный fallback: ответил другой модельный снимок; фактическая модель в поле model.",
        ),
        "timeout_raise": {"_synthetic": True, "name": "timeout_raise", "raise": "timeout",
                          "_note": "ReadTimeout транспорта."},
        "connect_raise": {"_synthetic": True, "name": "connect_raise", "raise": "connect",
                          "_note": "ConnectError транспорта."},
        "schema_candidates": SCHEMA,
        "expected_candidates": GOOD_DATA,
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, payload in build().items():
        (OUT / f"{name}.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"written {len(build())} fixtures to {OUT}")


if __name__ == "__main__":
    main()
