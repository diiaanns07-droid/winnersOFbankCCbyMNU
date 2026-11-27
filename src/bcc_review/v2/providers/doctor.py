"""Выбор провайдера, понятные ошибки и диагностика ``doctor`` (№02).

* :func:`make_provider` — провайдер по имени (``auto | claude_cli | gemini | anthropic | openai | mock | offline``);
* :func:`resolve_auto` — правило ``auto`` (CONTRACT.md, раздел 3): ``GEMINI_API_KEY`` → gemini;
  ``ANTHROPIC_API_KEY`` → anthropic; ``OPENAI_BASE_URL`` → openai; есть программа ``claude`` → claude_cli;
  иначе offline (только правила, без модели);
* :func:`explain` — русское сообщение об ошибке провайдера с советом, что сделать (без трейсбэка);
* :func:`main` — ``python -m bcc_review doctor [--live] [--provider P] [--model M]``
  (также ``python -m bcc_review.v2.providers.doctor``).

Значения ключей doctor не печатает никогда — только «задан» / «не задан».
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
from importlib import metadata
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from bcc_review.contracts import PROVIDER_ERROR_KINDS, ProviderError

__all__ = ["FATAL_KINDS", "PROVIDER_NAMES", "explain", "headline", "is_fatal", "load_dotenv", "main", "make_provider",
           "resolve_auto", "run_doctor"]

PROVIDER_NAMES = ("auto", "claude_cli", "gemini", "anthropic", "openai", "mock", "offline")
ALIASES = {"claude": "claude_cli", "claude-cli": "claude_cli", "cli": "claude_cli", "google": "gemini",
           "claude_api": "anthropic", "anthropic_api": "anthropic", "openai_compat": "openai", "ollama": "openai",
           "vllm": "openai", "none": "offline", "rules": "offline"}
TITLES = {"gemini": "Google Gemini", "anthropic": "Claude API", "openai": "OpenAI-совместимый сервер",
          "claude_cli": "Claude Code CLI (claude -p)", "mock": "mock (записанные ответы)",
          "offline": "без модели (только правила)"}

GEMINI_KEY_HELP = "Получите бесплатный ключ: https://aistudio.google.com/apikey и добавьте в файл .env строку GEMINI_API_KEY=<ключ>."
ANTHROPIC_KEY_HELP = "Ключ Claude API: https://console.anthropic.com/settings/keys — строка ANTHROPIC_API_KEY=<ключ> в .env."
OPENAI_HELP = ("Для своего сервера задайте OPENAI_BASE_URL (Ollama: http://localhost:11434/v1) и OPENAI_MODEL "
               "(например qwen3:32b); OPENAI_API_KEY — если сервер требует ключ.")
CLI_HELP = ("Установите Claude Code: npm install -g @anthropic-ai/claude-code, затем выполните «claude» и войдите "
            "в аккаунт.")
DOCTOR_HINT = "Проверка настроек: python -m bcc_review doctor (с пробным вызовом модели: doctor --live)."


# --------------------------------------------------------------------------- окружение


def read_env_text(path: str | Path) -> str:
    """Текст .env в любой кодировке, в которой его пишет Windows.

    Windows PowerShell 5.1 (``echo GEMINI_API_KEY=… > .env``, ``Out-File``) пишет UTF-16 с BOM — раньше такой
    файл ронял doctor трейсбэком, а прогон молча уходил в режим без модели. Блокнот — UTF-8 с BOM; старые
    редакторы — cp1251 (ключ — латиница, читается и так).
    """
    raw = Path(path).read_bytes()
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16")
    if len(raw) >= 4 and raw[1:2] == b"\x00" and raw[3:4] == b"\x00":   # UTF-16 LE без BOM
        return raw.decode("utf-16-le", "replace")
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("cp1251", "replace")


def load_dotenv(path: str | Path = ".env", environ: dict[str, str] | None = None) -> bool:
    """Тот же минимальный загрузчик .env, что в v1: окружение важнее файла. True — файл найден."""
    env = os.environ if environ is None else environ
    p = Path(path)
    if not p.is_file():
        return False
    for line in read_env_text(p).splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip().lstrip("\ufeff").removeprefix("export ").strip()
        value = value.strip().strip('"').strip("'").strip()
        if key and value and key not in env:
            env[key] = value
    return True


def _has(env: Mapping[str, str], *names: str) -> bool:
    return any((env.get(n) or "").strip() for n in names)


def resolve_auto(env: Mapping[str, str] | None = None,
                 which: Callable[[str], str | None] | None = None) -> tuple[str, str]:
    """(имя провайдера, причина выбора) по правилу ``auto``."""
    env = os.environ if env is None else env
    which = which or shutil.which  # в момент вызова, а не объявления: иначе подмена в тестах не действует
    if _has(env, "GEMINI_API_KEY", "GOOGLE_API_KEY"):
        return "gemini", "задан GEMINI_API_KEY" if _has(env, "GEMINI_API_KEY") else "задан GOOGLE_API_KEY"
    if _has(env, "ANTHROPIC_API_KEY"):
        return "anthropic", "задан ANTHROPIC_API_KEY"
    if _has(env, "OPENAI_BASE_URL"):
        return "openai", "задан OPENAI_BASE_URL"
    from bcc_review.v2.providers.claude_cli import find_cli
    if find_cli(env, which):
        return "claude_cli", "найдена программа claude (Claude Code CLI)"
    return "offline", "нет ни ключа модели, ни программы claude — отчёт будет построен только правилами"


def normalize_name(name: str | None) -> str:
    raw = (name or "auto").strip().lower().replace("-", "_")
    raw = ALIASES.get(raw, raw)
    if raw not in PROVIDER_NAMES:
        raise ProviderError("not_configured", f"Неизвестный провайдер «{name}». Допустимо: {', '.join(PROVIDER_NAMES)}.")
    return raw


def make_provider(name: str | None = "auto", *, env: Mapping[str, str] | None = None, **options: Any) -> Any:
    """Экземпляр провайдера или ``None`` для ``offline``. Ошибки настройки — ``ProviderError(not_configured)``."""
    env = os.environ if env is None else env
    name = normalize_name(name)
    if name == "auto":
        name, _ = resolve_auto(env)
    if name == "offline":
        return None
    if name == "claude_cli":
        from bcc_review.v2.providers.claude_cli import ClaudeCLIProvider
        return ClaudeCLIProvider(env=env, **options)
    if name == "gemini":
        from bcc_review.v2.providers.gemini import GeminiProvider
        return GeminiProvider(env=env, **options)
    if name == "anthropic":
        from bcc_review.v2.providers.anthropic_api import AnthropicProvider
        return AnthropicProvider(env=env, **options)
    if name == "openai":
        from bcc_review.v2.providers.openai_compat import OpenAICompatProvider
        return OpenAICompatProvider(env=env, **options)
    module = importlib.import_module("bcc_review.v2.providers.mock")
    for attr in ("MockProvider", "Provider"):
        if hasattr(module, attr):
            return getattr(module, attr)(**options)
    raise ProviderError("not_configured", "Провайдер mock не найден в bcc_review.v2.providers.mock.")


# --------------------------------------------------------------------------- ошибки

_ADVICE: dict[tuple[str, str], str] = {
    ("gemini", "not_configured"): GEMINI_KEY_HELP,
    ("gemini", "auth"): ("Google не принял ключ: проверьте, что GEMINI_API_KEY скопирован целиком, без кавычек и пробелов, "
                         "или создайте новый ключ на https://aistudio.google.com/apikey. Если ключ верный — бесплатный "
                         "тариф может быть недоступен в вашем регионе или проекте."),
    ("gemini", "quota"): ("Квота ключа исчерпана. Минутный лимит сбрасывается через минуту, дневной — в полночь по "
                          "тихоокеанскому времени. Можно задать другую модель (GEMINI_MODEL) или другой ключ."),
    ("gemini", "rate_limit"): ("Слишком много запросов в минуту для бесплатного ключа. Подождите минуту и повторите; "
                               "если у ключа меньше 5 запросов в минуту — задайте темп GEMINI_RPM=3 в .env."),
    ("gemini", "not_found"): ("Модель недоступна этому ключу. Список доступных моделей покажет "
                              "«python -m bcc_review doctor»; затем задайте GEMINI_MODEL=<модель>."),
    ("anthropic", "not_configured"): ANTHROPIC_KEY_HELP,
    ("anthropic", "auth"): "Claude API не принял ключ: проверьте ANTHROPIC_API_KEY (начинается с sk-ant-).",
    ("anthropic", "quota"): "Закончился кредит или лимит расходов Claude API: пополните баланс в console.anthropic.com.",
    ("anthropic", "not_found"): "Модель недоступна ключу: задайте ANTHROPIC_MODEL (например claude-sonnet-5-5).",
    ("openai", "not_configured"): OPENAI_HELP,
    ("openai", "network"): "Сервер модели не отвечает: запущен ли он (Ollama: «ollama serve»)? Верен ли OPENAI_BASE_URL?",
    ("openai", "not_found"): "Модель не найдена на сервере: проверьте OPENAI_MODEL (Ollama: «ollama list», «ollama pull <модель>»).",
    ("claude_cli", "not_configured"): CLI_HELP,
    ("claude_cli", "auth"): "Выполните «claude» в терминале и войдите в аккаунт Claude.",
    ("claude_cli", "quota"): "Лимит подписки Claude исчерпан: дождитесь сброса или используйте --provider gemini.",
}
_GENERIC: dict[str, str] = {
    "not_configured": "Проверьте настройки в файле .env (образец — .env.example). " + DOCTOR_HINT,
    "auth": "Проверьте ключ API в файле .env. " + DOCTOR_HINT,
    "quota": "Квота исчерпана: подождите, смените ключ или модель.",
    "rate_limit": "Превышен лимит запросов: подождите минуту и повторите.",
    "overloaded": "Сервис модели перегружен: агент уже повторял запрос и пробовал запасные модели. Повторите через несколько минут.",
    "server": "Сбой на стороне сервиса модели. Повторите через несколько минут.",
    "timeout": "Модель не ответила вовремя. Повторите; для больших документов увеличьте тайм-аут.",
    "network": "Нет соединения с сервисом модели: проверьте интернет, прокси (HTTPS_PROXY) и брандмауэр.",
    "not_found": "Модель недоступна. " + DOCTOR_HINT,
    "bad_request": "Сервис отклонил запрос. Приложите к сообщению об ошибке файл runs/<id>/trace.jsonl.",
    "refusal": "Модель отказалась отвечать (фильтр безопасности). Попробуйте другую модель или провайдера.",
    "truncated": "Ответ модели не поместился в лимит токенов: агент делит пакет пополам; если ошибка повторяется — "
                 "увеличьте лимит ответа или выберите модель с большим лимитом.",
    "invalid_output": "Модель вернула ответ не по схеме. Повторите или выберите модель сильнее.",
    "unknown": "Неожиданная ошибка провайдера. " + DOCTOR_HINT,
}


#: Ошибки, после которых звать модель в этом прогоне бессмысленно: следующие этапы получат то же самое.
FATAL_KINDS = frozenset({"auth", "not_configured", "quota"})


def is_fatal(exc: BaseException) -> bool:
    """True — модель недоступна до конца прогона (ключ, настройка, квота): остальные этапы — без модели."""
    return isinstance(exc, ProviderError) and exc.kind in FATAL_KINDS or getattr(exc, "kind", None) in FATAL_KINDS


_WRAP_PREFIXES = ("модель недоступна в этом прогоне:",)


def _kind_message(exc: BaseException) -> tuple[str | None, str]:
    """(kind, текст) для ProviderError и обёрток вроде LLMError (у них есть ``kind`` и ``message``)."""
    kind = getattr(exc, "kind", None)
    kind = kind if kind in PROVIDER_ERROR_KINDS else None
    message = str(getattr(exc, "message", None) or exc or "").strip()
    stage = getattr(exc, "stage", None)
    if stage and message.startswith(f"{stage}:"):
        message = message[len(stage) + 1:].strip()
    if kind and message.startswith(f"{kind}:"):
        message = message[len(kind) + 1:].strip()
    for prefix in _WRAP_PREFIXES:
        if message.lower().startswith(prefix):
            message = message[len(prefix):].strip()
    return kind, message or (kind or "")


def headline(exc: BaseException, provider: str | None = None) -> str:
    """Одна строка для первой строки консоли и отчёта: что случилось и что сделать (без подробностей сервера)."""
    kind, message = _kind_message(exc)
    name = ALIASES.get(str(provider or getattr(exc, "provider", "") or ""), str(provider or getattr(exc, "provider", "") or ""))
    low = message.lower()
    if kind is None:
        return f"Ошибка: {message}. {DOCTOR_HINT}"
    if kind == "not_configured" and "pip install" in low:
        pkg = re.search(r"pip install ([\w.=<>,\-\[\]]+)", message)
        return (f"Не установлен нужный пакет{(' ' + pkg.group(1)) if pkg else ''}: выполните "
                "«pip install -r requirements.txt» и повторите.")
    if name == "gemini":
        if kind == "not_configured":
            return ("Не задан ключ Gemini. Получите бесплатный ключ на https://aistudio.google.com/apikey и добавьте "
                    "в файл .env строку GEMINI_API_KEY=<ключ>.")
        if kind in ("auth", "bad_request") and _proxy_refusal(message):
            return ("Запрос к Google Gemini отклонил прокси или брандмауэр сети, а не Google (ключ тут ни при чём): "
                    "разрешите доступ к generativelanguage.googleapis.com, проверьте HTTPS_PROXY или подключитесь "
                    "к другой сети (например, раздайте интернет с телефона).")
        if kind == "auth" and ("location" in low or "регион" in low or "failed_precondition" in low):
            return ("Gemini недоступен для этого ключа из текущего региона или без подключённой оплаты в Google Cloud: "
                    "попробуйте другую сеть или другой ключ AI Studio.")
        if kind == "auth":
            return ("Google не принял ключ Gemini (GEMINI_API_KEY): проверьте, что он скопирован целиком, без кавычек и "
                    "пробелов, или создайте новый на https://aistudio.google.com/apikey.")
        if kind == "quota":
            reset = re.search(r"восстановится около ([^.]+)", message)
            if reset:
                return (f"Дневная квота бесплатного ключа Gemini исчерпана на всех моделях цепочки. Квота восстановится "
                        f"около {reset.group(1)}; сейчас можно взять другой ключ.")
            if "нулевая квота" in low or "limit_zero" in low or "limit: 0" in low:
                return ("Модели Gemini из цепочки недоступны этому ключу на бесплатном тарифе (квота 0). Список доступных "
                        "моделей: python -m bcc_review doctor; затем GEMINI_MODEL=<модель> в .env.")
            return "Квота ключа Gemini исчерпана. Подождите, возьмите другой ключ или задайте другую модель (GEMINI_MODEL)."
        if kind == "rate_limit":
            wait = getattr(exc, "retry_after_s", None)
            when = f" через {int(wait) + 1} с" if isinstance(wait, (int, float)) and wait > 0 else " через минуту"
            return (f"Превышен лимит запросов в минуту бесплатного ключа Gemini (агент уже ждал и повторял). Повторите"
                    f"{when}; если у ключа меньше 5 запросов в минуту — задайте темп GEMINI_RPM=3 в .env.")
        if kind == "not_found":
            return ("Модели Gemini из цепочки недоступны этому ключу. Список доступных моделей: python -m bcc_review "
                    "doctor; затем GEMINI_MODEL=<модель> в .env.")
        if kind == "network":
            return ("Нет соединения с Google Gemini (generativelanguage.googleapis.com): проверьте интернет, прокси "
                    "(HTTPS_PROXY) и брандмауэр.")
        if kind in ("overloaded", "server"):
            return ("Gemini перегружен: все модели цепочки не ответили после повторов. Повторите через несколько минут "
                    "или задайте GEMINI_MODEL=<другая модель>.")
        if kind == "timeout" and "брандмауэр" in low:
            return message
        if kind == "timeout":
            return "Gemini не ответил вовремя даже после повторов. Повторите через несколько минут."
    if name == "claude_cli" and kind == "quota":
        # «Исчерпан лимит подписки… Что сделать: Лимит подписки исчерпан…» — одно и то же дважды, а время сброса
        # (главное для пользователя) терялось в «Подробностях»
        reset = re.search(r"Сброс лимита: ([^\]\n]+?)\.(?:\s|$)", message)
        when = f" Сброс лимита: {reset.group(1).strip()}." if reset else ""
        wait = getattr(exc, "retry_after_s", None)
        if not when and isinstance(wait, (int, float)) and 0 < wait < 7 * 86400:
            import datetime as dt
            at = dt.datetime.now().astimezone() + dt.timedelta(seconds=float(wait))
            when = f" Сброс лимита около {at:%H:%M} по местному времени."
        return (f"Исчерпан лимит подписки Claude Code.{when} До сброса — другая модель (--model haiku) или "
                "--provider gemini с ключом GEMINI_API_KEY.")
    title = TITLES.get(name, name or "модели")
    advice = _ADVICE.get((name, kind)) or _GENERIC.get(kind, _GENERIC["unknown"])
    return f"{title}: {_first_sentence(message)} Что сделать: {advice}"


_GOOGLE_STATUSES = ("PERMISSION_DENIED", "UNAUTHENTICATED", "INVALID_ARGUMENT", "FAILED_PRECONDITION",
                    "API_KEY_INVALID")


def _proxy_refusal(message: str) -> bool:
    """403/407 не от Google: у Google в ответе статус вида PERMISSION_DENIED, у прокси — «Forbidden» или пусто.

    Корпоративный или университетский прокси, запрещающий googleapis.com, иначе выглядел как «ключ не принят».
    """
    m = re.search(r"\((40[37])\b([^)]*)\)", message or "")
    if not m:
        return False
    return m.group(1) == "407" or not any(st in m.group(2).upper() for st in _GOOGLE_STATUSES)


def _first_sentence(text: str, limit: int = 160) -> str:
    text = " ".join(text.split())
    m = re.match(r"(.+?[.!?])(\s|$)", text)
    out = m.group(1) if m else text
    return out if len(out) <= limit else out[: limit - 1].rstrip() + "…"


def explain(exc: BaseException, provider: str | None = None) -> str:
    """Первая строка — :func:`headline` (что случилось и что сделать), вторая — подробности провайдера."""
    kind, message = _kind_message(exc)
    head = headline(exc, provider)
    if kind is None or not message or message in head:
        return head
    return f"{head}\nПодробности: {message}"


# --------------------------------------------------------------------------- doctor

PROBE_SCHEMA: dict[str, Any] = {
    "type": "object", "additionalProperties": False, "required": ["ok", "requirement", "problem"],
    "properties": {"ok": {"type": "boolean"}, "requirement": {"type": "string"}, "problem": {"type": "string"}},
}
PROBE_MESSAGES = [
    {"role": "system", "content": "Ты проверяешь требования. Ответ — только JSON по схеме, тексты по-русски, коротко."},
    {"role": "user", "content": "Требование: «Система должна быстро обрабатывать заявки». Верни ok=false, "
                                "requirement — цитату требования, problem — одно предложение, почему его нельзя проверить."},
]

PACKAGES = (
    ("jsonschema", "jsonschema", "обязателен", True),
    ("google-genai", "google.genai", "для Gemini", False),
    ("anthropic", "anthropic", "для Claude API", False),
    ("pymupdf", "fitz", "для PDF", False),
    ("python-docx", "docx", "для DOCX", False),
)
OK, NO, WARN = "[ок] ", "[нет]", "[!]  "


def _pkg_version(dist: str, module: str) -> str | None:
    try:
        return metadata.version(dist)
    except metadata.PackageNotFoundError:
        try:
            importlib.import_module(module)
            return "установлен"
        except Exception:  # noqa: BLE001
            return None


def _cli_version(cmd: list[str]) -> str:
    try:
        r = subprocess.run(cmd + ["--version"], capture_output=True, text=True, timeout=30)
        return ((r.stdout or r.stderr or "").strip().splitlines() or ["?"])[0]
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"не запускается: {exc}"


FREE_TIER_NOTE = ("Бесплатный ключ: 20 запросов в сутки на каждую модель Flash и 500 на Flash-Lite (квота на проект "
                  "Google, не на ключ); прогон — 9–10 запросов, поэтому цепочка идёт по всем Flash, затем Flash-Lite.")


def _attempt_lines(attempts: Sequence[Mapping[str, Any]]) -> list[str]:
    """Неудачные попытки пробного вызова Gemini по-русски: почему ответила не основная модель."""
    from bcc_review.v2.providers.gemini import daily_reset_local
    lines: list[str] = []
    seen: set[str] = set()
    for a in attempts:
        model, kind = str(a.get("model") or "?"), str(a.get("kind") or a.get("skipped") or "")
        if not kind or model in seen:
            continue
        seen.add(model)
        if kind == "quota" and a.get("subkind") == "limit_zero":
            why = "на бесплатном тарифе квота модели нулевая"
        elif kind == "quota":
            limit = a.get("quota_limit")
            why = ("исчерпана дневная квота" + (f" ({limit} запросов в сутки на модель)" if limit else "")
                   + f"; восстановится около {daily_reset_local()}")
        elif kind == "not_found":
            why = "модель недоступна этому ключу (404)"
        elif kind == "rate_limit":
            why = "лимит запросов в минуту (429), агент подождал"
        elif kind in ("overloaded", "server", "timeout"):
            why = "модель перегружена (503) или не ответила вовремя"
        else:
            why = kind
        lines.append(f"  {WARN} {model}: {why}")
    return lines


LIVE_BUDGET_S = {"gemini": 9.0}   # doctor --live у Gemini: диагноз за ≤ 10 с (быстрые повторы, без долгих ожиданий 429)
LIVE_BUDGET_DEFAULT_S = 120.0      # claude -p стартует 10–30 с — ему прежний запас
NET_HEADLINE = ("Google Gemini не ответил за {s:.0f} с: похоже, соединение блокирует прокси или брандмауэр, либо "
                "сеть очень медленная. Проверьте доступ к generativelanguage.googleapis.com и HTTPS_PROXY.")


def _with_deadline(fn: Callable[[], Any], seconds: float) -> Any:
    """Вызов с жёстким пределом времени (поток-демон): зависший сокет не держит doctor дольше ``seconds``."""
    import threading
    box: dict[str, Any] = {}

    def run() -> None:
        try:
            box["value"] = fn()
        except BaseException as exc:  # noqa: BLE001 - передаём наружу как есть
            box["error"] = exc

    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(max(0.1, seconds))
    if t.is_alive():
        raise ProviderError("timeout", NET_HEADLINE.format(s=seconds))
    if "error" in box:
        raise box["error"]
    return box.get("value")


def _quick_probe(instance: Any, budget_s: float) -> None:
    """Политика пробного вызова Gemini: один короткий повтор вместо 2/5/10 с, 429 — без ожидания Retry-After."""
    for attr, value in (("retry_delays", (1.0,)), ("network_delays", (1.0,)), ("max_rate_wait_s", 0.0),
                        ("total_timeout_s", max(5.0, budget_s))):
        if hasattr(instance, attr):
            setattr(instance, attr, value)


def run_doctor(*, live: bool = False, provider: str | None = None, model: str | None = None,
               timeout_s: float | None = None,
               env: Mapping[str, str] | None = None, out: Callable[[str], None] = print,
               which: Callable[[str], str | None] | None = None,
               factory: Callable[..., Any] | None = None, list_models: bool = True) -> int:
    """Печатает диагностику. Код: 0 — можно запускать; 1 — нет рабочего провайдера; 2 — пробный вызов не прошёл."""
    env = os.environ if env is None else env
    which = which or shutil.which
    factory = factory or make_provider
    problems: list[str] = []
    out("Диагностика bcc_review")
    out("")

    v = sys.version_info
    py_ok = v >= (3, 11)
    out(f"{OK if py_ok else NO} Python {platform.python_version()} ({sys.executable})"
        + ("" if py_ok else " — нужен Python 3.11 или новее"))
    if not py_ok:
        problems.append("Установите Python 3.11+ (https://www.python.org/downloads/).")

    out("")
    out("Пакеты:")
    for dist, module, why, required in PACKAGES:
        ver = _pkg_version(dist, module)
        if ver:
            out(f"  {OK} {dist} {ver} ({why})")
        else:
            out(f"  {NO if required else WARN} {dist} не установлен ({why}): pip install {dist}")
            if required:
                problems.append(f"Установите зависимости: pip install -r requirements.txt (нет {dist}).")

    out("")
    out("Ключи и настройки (значения ключей не показываются):")
    for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
        out(f"  {OK if _has(env, name) else '[ ]  '} {name}: {'задан' if _has(env, name) else 'не задан'}")
    for name in ("GEMINI_MODEL", "GEMINI_FALLBACK_MODELS", "ANTHROPIC_MODEL", "OPENAI_BASE_URL", "OPENAI_MODEL",
                 "CLAUDE_CLI_MODEL", "CLAUDE_CLI_EFFORT"):
        value = (env.get(name) or "").strip()
        if value:
            out(f"  {OK} {name} = {value}")

    from bcc_review.v2.providers.claude_cli import find_cli
    cli = find_cli(env, which)
    out("")
    if cli:
        out(f"{OK} Claude Code CLI: {' '.join(cli)} — {_cli_version(cli)}")
    else:
        out(f"[ ]   Claude Code CLI не найден (нужен только для провайдера claude_cli)")

    try:
        chosen = normalize_name(provider)
    except ProviderError as exc:
        out(f"{NO} {exc.message}")
        return 1
    reason = "указан явно"
    if chosen == "auto":
        chosen, reason = resolve_auto(env, which)
    out("")
    out(f"Провайдер: {chosen} — {TITLES.get(chosen, chosen)} ({reason})")
    if chosen == "offline":
        problems.append("Модель не настроена: отчёт будет построен только правилами, качество ниже. "
                        + GEMINI_KEY_HELP)

    started_all = time.monotonic()
    budget = float(timeout_s) if timeout_s else LIVE_BUDGET_S.get(chosen, LIVE_BUDGET_DEFAULT_S)
    list_s = min(budget / 2, 5.0) if live else 30.0
    known: ProviderError | None = None
    instance = None
    if chosen not in ("offline",):
        try:
            instance = factory(chosen, env=env)
        except ProviderError as exc:
            out(f"{NO} {explain(exc, chosen)}")
            problems.append(f"Провайдер {chosen} не настроен.")

    if chosen == "gemini" and instance is not None:
        from bcc_review.v2.providers.gemini import GeminiProvider
        chain = instance.model_chain(model) if isinstance(instance, GeminiProvider) else []
        out(f"  Цепочка моделей: {' -> '.join(chain)}")
        if list_models and hasattr(instance, "list_models"):
            try:
                ids = [str(m.get("id")) for m in _with_deadline(instance.list_models, list_s)]
            except ProviderError as exc:
                if exc.kind in ("auth", "network", "timeout", "not_configured"):
                    known = exc   # диагноз уже ясен: пробный вызов дал бы то же самое, только дольше
                out(f"  {NO} Список моделей (models.list) не получен: {explain(exc, 'gemini')}")
                problems.append("Доступ к Google API закрыт прокси или брандмауэром сети." if _proxy_refusal(
                    exc.message) else {"auth": "Ключ Gemini отклонён: проверьте GEMINI_API_KEY.",
                                 "not_configured": f"Gemini не настроен: {exc.message}",
                                 "timeout": "Google API не отвечает: проверьте сеть, прокси и брандмауэр.",
                                 "network": "Нет соединения с Google API: проверьте интернет и прокси."}.get(
                    exc.kind, f"Список моделей Gemini не получен ({exc.kind})."))
            else:
                for m in chain:
                    out(f"  {OK if m in ids else NO} {m}" + ("" if m in ids else " — нет у этого ключа"))
                if not any(m in ids for m in chain):
                    problems.append("Ни одна модель цепочки недоступна ключу: задайте GEMINI_MODEL из списка ниже.")
                flash = [i for i in ids if "flash" in i][:12]
                if flash:
                    out(f"  Доступные модели Flash: {', '.join(flash)}")
        out(f"  {WARN} {FREE_TIER_NOTE}")

    code = 0 if not problems else 1
    if live and instance is not None and known is not None:
        out("")
        out(f"{NO} Пробный вызов не делаю — причина уже найдена: {headline(known, chosen)}")
        problems.append("Пробный вызов модели не прошёл.")
        code = 2
    elif live and instance is not None:
        out("")
        out(f"Пробный вызов ({chosen}{', модель ' + model if model else ''}) …")
        started = time.monotonic()
        left = max(5.0, budget - (started - started_all))
        if chosen == "gemini":
            _quick_probe(instance, left)
        try:
            r = _with_deadline(lambda: instance.invoke(model=model, messages=PROBE_MESSAGES, schema=PROBE_SCHEMA,
                                                       timeout_s=max(5.0, left - 1.0)), left + 1.0)
        except ProviderError as exc:
            out(f"{NO} {explain(exc, chosen)}")
            if exc.kind in ("rate_limit", "quota") and chosen == "gemini":
                out(f"{WARN} Ключ рабочий: Google принял его, но лимит запросов сейчас исчерпан.")
            problems.append("Пробный вызов модели не прошёл.")
            code = 2
        else:
            dt = time.monotonic() - started
            u = r.get("usage") or {}
            meta = r.get("meta") or {}
            for line in _attempt_lines(meta.get("attempts") or []):
                out(line)
            out(f"{OK} Модель ответила за {dt:.1f} с: {r.get('model')}"
                + (" (запасная)" if meta.get("fallback_used") else "")
                + f", токенов {u.get('input_tokens', '?')} -> {u.get('output_tokens', '?')}")
            out(f"       Ответ: {json.dumps(r.get('data'), ensure_ascii=False)[:300]}")
    elif live and chosen == "offline":
        code = max(code, 1)

    out("")
    if problems:
        out("Что исправить:")
        for p in dict.fromkeys(problems):
            out(f"  - {p}")
    else:
        out("Всё готово. Запуск: python -m bcc_review release/input/requirements.md reports/requirements.md")
        if not live:
            out("Проверить модель пробным вызовом: python -m bcc_review doctor --live")
    return code


def main(argv: Sequence[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass
    parser = argparse.ArgumentParser(prog="python -m bcc_review doctor",
                                     description="Проверка окружения, ключей и модели для bcc_review")
    parser.add_argument("--live", action="store_true", help="сделать пробный вызов модели с коротким JSON")
    parser.add_argument("--provider", default=None, help=f"провайдер: {', '.join(PROVIDER_NAMES)} (по умолчанию auto)")
    parser.add_argument("--model", default=None, help="модель для пробного вызова")
    parser.add_argument("--timeout", type=float, default=None,
                        help="предел времени пробного вызова, с (по умолчанию: Gemini — 10, claude -p — 120)")
    parser.add_argument("--env-file", default=".env", help="файл с ключами (по умолчанию .env)")
    args = parser.parse_args(argv)
    found = load_dotenv(args.env_file)
    if found:
        print(f"Файл настроек: {Path(args.env_file).resolve()}")
    try:
        return run_doctor(live=args.live, provider=args.provider, model=args.model, timeout_s=args.timeout)
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
