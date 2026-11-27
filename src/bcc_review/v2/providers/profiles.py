"""Профили моделей (№02): лимит ответа, рассуждение, параллельность и темп — в одном месте.

Профиль выбирается по имени модели (``for_model``); переменные окружения и опции CLI важнее профиля.
Каждое число здесь — из замера (``docs/plan-v2/status/02.md``, раздел «Волна 3»):

* **Gemini Flash** — бесплатный тариф: окно 10 запросов в минуту на модель, все 5 параллельных этапов разом
  (модель времени ``tests/v2/test_02_wallclock.py``); рассуждения ``medium`` (Gemini 3) / бюджет 4096 (2.5);
  лимит ответа 65 536 — потолок модели (haiku на наборе выдал 34,5 тыс. токенов с рассуждением: 32 000 мало).
* **Gemini Flash-Lite** — 15 запросов в минуту; рассуждения как у Flash (модель отвергнет — провайдер
  повторит без них).
* **Gemini Pro** — на бесплатном тарифе 5 запросов в минуту: параллельность 2, окно 5.
* **haiku** — ``effort=low`` (замер №01 05:05: вдвое быстрее при тех же К и С; у haiku рассуждения — 70 %
  вывода); лимит ответа CLI не ниже 64 000 (рассуждения в лимите).
* **sonnet / opus** — рассуждение по умолчанию CLI; лимит ответа 64 000.

``STAGE_EFFORT`` — отступления по этапам (только проверенные замером на ``stage``): у этапов, где ответ —
извлечение или короткий текст (нарезка, вопросы), глубокое рассуждение тратит десятки секунд без пользы.
"""

from __future__ import annotations

from typing import Any

__all__ = ["PROFILES", "STAGE_EFFORT", "claude_effort", "family", "for_model", "gemini_max_output", "gemini_thinking"]

PROFILES: dict[str, dict[str, Any]] = {
    "gemini-flash": {"rpm": 10, "concurrency": 5, "max_output_tokens": 65536,
                     "thinking_level": "medium", "thinking_budget": 4096},
    "gemini-flash-lite": {"rpm": 15, "concurrency": 5, "max_output_tokens": 65536,
                          "thinking_level": "medium", "thinking_budget": 4096},
    "gemini-pro": {"rpm": 5, "concurrency": 2, "max_output_tokens": 65536,
                   "thinking_level": "medium", "thinking_budget": 4096},
    "gemini": {"rpm": 10, "concurrency": 5, "max_output_tokens": 65536,
               "thinking_level": "medium", "thinking_budget": 4096},
    "haiku": {"effort": "low", "max_output_tokens": 64000},
    "sonnet": {"effort": None, "max_output_tokens": 64000},
    "opus": {"effort": None, "max_output_tokens": 64000},
    "claude": {"effort": None, "max_output_tokens": 64000},
    "other": {"max_output_tokens": 16000},
}

# Рассуждение по этапам: {семейство: {этап: effort}}; этапа нет — профиль модели.
# Замер sonnet 27.11 09:15–09:25 (stage на сохранённых входах, официальный документ и open2/grace):
#   segment low: 29 → 18 с, те же 40 из 40 требований (grace: 43 из 43, одно — сдвиг строки);
#   clarify low: 50 → 24 с, те же 10 вопросов / 5 блокирующих (grace: 28 → 20 с, 10 вопросов вместо 7, те же пункты);
#   judge low — отклонён: К5 понижен до major (ворота «все критичными»); judge medium: 86 → 80 с — в пределах шума;
#   consistency low — отклонён: 59 → 20 с, но потеряно 4 из 13 кандидатов (в т. ч. Ф-2 ↔ приёмка).
# Gemini Flash — по тем же этапам (нарезка — извлечение, вопросы — короткий текст; haiku со всеми этапами
# на low держит К 5/5); линзы, набор и судья — medium.
_FAST = {"segment": "low", "clarify": "low"}
STAGE_EFFORT: dict[str, dict[str, str]] = {
    "sonnet": dict(_FAST),
    "gemini-flash": dict(_FAST),
    "gemini-flash-lite": dict(_FAST),
    "gemini": dict(_FAST),
}
GEMINI25_BUDGET = {"low": 1024, "medium": 4096, "high": 8192}   # Gemini 2.5: уровень → бюджет рассуждений


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
        staged = STAGE_EFFORT.get(prof["family"], {}).get(stage)
        return {"thinking_budget": int(GEMINI25_BUDGET.get(staged, prof["thinking_budget"]))}
    return {}


def gemini_max_output(model: str) -> int:
    """Потолок ответа Gemini: 2.5 и 3.x — 65 536 (рассуждения входят в лимит), старшие модели — 8 192."""
    m = (model or "").lower().removeprefix("models/")
    if m.startswith(("gemini-2.5", "gemini-3")) or ("gemini" in m and not m.startswith(("gemini-1", "gemini-2.0"))):
        return int(for_model(m).get("max_output_tokens") or 65536)
    return 8192


def claude_effort(model: str | None, stage: str = "") -> str | None:
    """``--effort`` для Claude по профилю модели и этапу; ``None`` — по умолчанию CLI."""
    fam = family(model)
    return STAGE_EFFORT.get(fam, {}).get(stage) or PROFILES.get(fam, {}).get("effort")
