"""Шаблоны промптов v2: Markdown-файлы рядом с этим модулем, подстановки ``{{имя}}``.

``_system.md`` — общий системный промпт (CONTRACT.md, раздел 6), ``<этап>.md`` — текст задания этапа.
Если в файле задания есть разделы ``## system`` и ``## user``, первый заменяет общий системный промпт.
"""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

DIR = Path(__file__).resolve().parent
_VAR = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")
_SPLIT = re.compile(r"^## system\s*$(.*?)^## user\s*$(.*)", re.S | re.M)


@lru_cache(maxsize=64)
def load(name: str) -> str:
    """Текст шаблона ``<name>.md``. Нет файла — ``FileNotFoundError`` с понятным текстом."""
    path = DIR / f"{name}.md"
    if not path.is_file():
        raise FileNotFoundError(f"Нет шаблона промпта {path.name} в {DIR}")
    return path.read_text(encoding="utf-8")


def exists(name: str) -> bool:
    return (DIR / f"{name}.md").is_file()


def render(text: str, **variables: object) -> str:
    """Подставить ``{{имя}}``. Неизвестные имена остаются как есть (их видно в трассе и в тесте)."""
    def sub(m: re.Match) -> str:
        key = m.group(1)
        return str(variables[key]) if key in variables else m.group(0)
    return _VAR.sub(sub, text)


def system() -> str:
    return load("_system").strip()


def task(name: str, **variables: object) -> tuple[str | None, str]:
    """(свой system или None, текст задания) для этапа ``name`` с подстановками."""
    raw = load(name)
    m = _SPLIT.search(raw)
    if m:
        return render(m.group(1).strip(), **variables), render(m.group(2).strip(), **variables)
    return None, render(raw.strip(), **variables)
