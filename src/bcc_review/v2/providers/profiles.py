"""Профили моделей (№02): лимит ответа, рассуждение, параллельность и темп — в одном месте.

Профиль выбирается по имени модели (``for_model``); переменные окружения и опции CLI важнее профиля.
Каждое число здесь — из замера (``docs/plan-v2/status/02.md``, раздел «Волна 3»):

* **Gemini Flash** — бесплатный тариф: окно 10 запросов в минуту на модель, все 5 параллельных этапов разом
  (модель времени ``tests/v2/test_02_wallclock.py``); рассуждения ``medium`` (Gemini 3) / бюджет 4096 (2.5).
* **Gemini Flash-Lite** — 15 запросов в минуту; рассуждения как у Flash (модель отвергнет — провайдер
  повторит без них).
* **Gemini Pro** — на бесплатном тарифе 5 запросов в минуту: параллельность 2, окно 5.
* **haiku** — ``effort=low`` (замер №01 05:05: вдвое быстрее при тех же К и С; у haiku рассуждения — 70 %
  вывода); лимит ответа CLI не ниже 64 000 (рассуждения в лимите).
* **sonnet / opus** — рассуждение по умолчанию CLI; лимит ответа 64 000.

``STAGE_EFFORT`` — отступления по этапам (только проверенные замером на ``stage``): у этапов, где ответ —
извлечение или короткий текст, глубокое рассуждение тратит минуты без пользы.
"""

from __future__ import annotations

from typing import Any

__all__ = ["PROFILES", "STAGE_EFFORT", "claude_effort", "family", "for_model", "gemini_thinking"]

PROFILES: dict[str, dict[str, Any]] = {
    "gemini-flash": {"rpm": 10, "concurrency": 5, "max_output_tokens": 32000,
                     "thinking_level": "medium", "thinking_budget": 4096},
    "gemini-flash-lite": {"rpm": 15, "concurrency": 5, "max_output_tokens": 32000,
                          "thinking_level": "medium", "thinking_budget": 4096},
    "gemini-pro": {"rpm": 5, "concurrency": 2, "max_output_tokens": 32000,
                   "thinking_level": "medium", "thinking_budget": 4096},
    "gemini": {"rpm": 10, "concurrency": 5, "max_output_tokens": 32000,
               "thinking_level": "medium", "thinking_budget": 4096},
    "haiku": {"effort": "low", "max_output_tokens": 64000},
    "sonnet": {"effort": None, "max_output_tokens": 64000},
    "opus": {"effort": None, "max_output_tokens": 64000},
    "claude": {"effort": None, "max_output_tokens": 64000},
    "other": {"max_output_tokens": 16000},
}

# Рассуждение по этапам: {семейство: {этап: effort}}. Пусто — профиль модели на всех этапах.
STAGE_EFFORT: dict[str, dict[str, str]] = {}


def family(model: str | None) -> str:
    """Семейство модели по имени: ``gemini-flash``, ``gemini-flash-lite``, ``gemini-pro``, ``haiku``, ``sonnet``…"""
    m = (model or "").lower().removeprefix("models/")
    if "gemini" in m:
        if "lite" in m:
            return "gemini-flash-lite"
        if "flash" in m:
            return "gemini-flash"
        if "pro" in m:
            return "gemini-pro"
        return "gemini"
    for name in ("haiku", "sonnet", "opus"):
        if name in m:
            return name
    if m.startswith("claude"):
        return "claude"
    return "other"


def for_model(model: str | None) -> dict[str, Any]:
    """Копия профиля модели (с ключом ``family``)."""
    fam = family(model)
    return {"family": fam, **PROFILES[fam]}


def gemini_thinking(model: str, stage: str = "") -> dict[str, Any]:
    """Параметры рассуждений Gemini по профилю: Gemini 3 — ``thinking_level``, 2.5 — ``thinking_budget``, иначе ``{}``."""
    m = (model or "").lower().removeprefix("models/")
    prof = for_model(m)
    level = STAGE_EFFORT.get(prof["family"], {}).get(stage) or prof.get("thinking_level")
    if m.startswith("gemini-3") and level:
        return {"thinking_level": level}
    if m.startswith("gemini-2.5") and prof.get("thinking_budget"):
        return {"thinking_budget": int(prof["thinking_budget"])}
    return {}


def claude_effort(model: str | None, stage: str = "") -> str | None:
    """``--effort`` для Claude по профилю модели и этапу; ``None`` — по умолчанию CLI."""
    fam = family(model)
    return STAGE_EFFORT.get(fam, {}).get(stage) or PROFILES.get(fam, {}).get("effort")
