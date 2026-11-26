"""Общий запуск линзы: промпт ``prompts/lens_<имя>.md``, схема, вызов модели, деление при обрезке.

* ``run(ctx, name)`` — «сырой» вызов модели. Схема — ``SCHEMA`` из ``stages/lens_<имя>.py``, если она там
  есть (у архитектора — ``inventory`` + ``candidates``), иначе общая схема кандидатов (CONTRACT 2.3).
  Обрезанный ответ делится по требованиям (``ask_split``): модель видит весь документ, но проверяет
  только свою половину таблицы требований.
* ``run_named(ctx, name)`` — то, что зовёт конвейер: ``stages/lens_<имя>.run(ctx)``, если модуль есть
  (постобработка владельца линзы), иначе ``run(ctx, name)``.
"""
from __future__ import annotations

import importlib
from typing import Any

from .. import prompts
from ..llm import merge_lists
from ..types import CANDIDATES_SCHEMA

MAX_OUTPUT_TOKENS = 16000
FOCUS = ("\n\nОграничение этого запроса: ответ предыдущего запроса не поместился в лимит. Проверяй только "
         "требования {ids} (документ остальной — для контекста). Кандидатов по другим требованиям не выдавай.")


def module(name: str):
    try:
        return importlib.import_module(f"bcc_review.v2.stages.lens_{name}")
    except ModuleNotFoundError as exc:
        if exc.name and exc.name.endswith(f"lens_{name}"):
            return None
        raise


def schema_for(name: str) -> dict:
    mod = module(name)
    sch = getattr(mod, "SCHEMA", None) if mod else None
    return sch if isinstance(sch, dict) else CANDIDATES_SCHEMA


def run(ctx: Any, name: str) -> dict:
    stage = f"lens_{name}"
    if not prompts.exists(stage):
        ctx.warn(f"Линза «{name}»: нет промпта {stage}.md — этап пропущен")
        return {"candidates": []}
    schema = schema_for(name)
    system, user = ctx.prompt(stage)
    reqs = [r.get("id") for r in ctx.requirements or [] if r.get("id")]

    def build(ids: list) -> tuple[str, str]:
        if len(ids) == len(reqs):
            return system, user
        return system, user + FOCUS.format(ids=", ".join(ids))

    llm = ctx.llm
    if reqs and hasattr(llm, "ask_split"):
        data = llm.ask_split(stage, build, reqs, schema, merge_lists, max_output_tokens=MAX_OUTPUT_TOKENS)
    else:
        data = llm.ask(stage, system, user, schema, max_output_tokens=MAX_OUTPUT_TOKENS)
    data = dict(data or {})
    data.setdefault("candidates", [])
    for c in data["candidates"]:
        if isinstance(c, dict):
            c.setdefault("source", f"lens:{name}")
    return data


def run_named(ctx: Any, name: str) -> dict:
    mod = module(name)
    fn = getattr(mod, "run", None) if mod else None
    out = fn(ctx) if callable(fn) else run(ctx, name)
    out = dict(out or {})
    out.setdefault("candidates", [])
    for c in out["candidates"]:
        if isinstance(c, dict):
            c.setdefault("source", f"lens:{name}")
    return out
