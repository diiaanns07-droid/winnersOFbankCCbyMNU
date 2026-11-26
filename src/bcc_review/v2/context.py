"""Контекст прогона v2: документ, клиент модели, опции, результаты предыдущих этапов, сборка сообщений.

Порядок сообщения к модели (общий префикс для кэша провайдера): ``system`` = ``prompts/_system.md``;
``user`` = ``<документ>`` → ``<требования>`` → ``<сигналы>`` → текст задания этапа (последним).
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import prompts

# Какому этапу какие сигналы правил показывать (rules.format_signals(audience=…), №12).
AUDIENCE = {"lens_analyst": "analyst", "lens_qa": "qa", "lens_architect": "architect", "lens_risk": "risk",
            "consistency": "consistency"}
# Этапы, которым таблица требований и сигналы не нужны (они получают свои блоки через переменные).
NO_DOC = {"segment"}


def numbered(view: dict, start: int = 1, end: int | None = None) -> str:
    """«L038| текст», для PDF/DOCX «L045| [с.3] текст» (docview №03, иначе запасной вариант)."""
    try:
        from . import docview
        return docview.numbered(view, start, end)
    except Exception:  # noqa: BLE001 — docview ещё не слит или упал: та же нумерация своими силами
        out = []
        for x in view.get("lines") or []:
            n = int(x.get("n") or 0)
            if n < start or (end is not None and n > end):
                continue
            page = f"[с.{x['page']}] " if x.get("page") else ""
            out.append(f"L{n:03d}| {page}{x.get('text', '')}")
        return "\n".join(out)


def requirements_table(requirements: list[dict]) -> str:
    rows = []
    for r in requirements or []:
        place = f"строки {r.get('line_start')}–{r.get('line_end')}"
        if r.get("page"):
            place = f"с. {r['page']}, " + place
        rows.append(f"{r.get('id', '')} | {r.get('source_id', '') or '—'} | {r.get('kind', '')} | {place} | "
                    f"{r.get('summary', '')}")
    return "ID | ID в документе | вид | место | кратко\n" + "\n".join(rows)


def signals_block(signals: list[dict], audience: str | None) -> str:
    if not signals:
        return ""
    try:
        from . import rules
        text = rules.format_signals(signals, audience=audience)
    except Exception:  # noqa: BLE001
        text = "\n".join(f"{s.get('id', '')} · L{s.get('line', 0):03d} · «{s.get('quote', '')}» — {s.get('message', '')}"
                         for s in signals)
    text = (text or "").strip()
    if not text or text.startswith("Сигналов правил нет"):
        return ""
    return text if text.startswith("<сигналы>") else f"<сигналы>\n{text}\n</сигналы>"


@dataclass
class Context:
    view: dict
    llm: Any = None
    options: dict = field(default_factory=dict)
    requirements: list = field(default_factory=list)
    excluded: list = field(default_factory=list)
    signals: list = field(default_factory=list)
    run_dir: Path | None = None
    warnings: list = field(default_factory=list)
    trace: Any = None
    _numbered: str | None = field(default=None, repr=False)
    _lock: Any = field(default_factory=threading.Lock, repr=False)

    def warn(self, msg: str) -> None:
        msg = str(msg).strip()
        if not msg:
            return
        with self._lock:
            if msg not in self.warnings:
                self.warnings.append(msg)

    def document_block(self) -> str:
        if self._numbered is None:
            self._numbered = numbered(self.view)
        return f"<документ>\n{self._numbered}\n</документ>"

    def prompt(self, name: str, **variables: Any) -> tuple[str, str]:
        """(system, user) для этапа: общий системный промпт и задание ``prompts/<name>.md`` в конце сообщения."""
        own_system, task = prompts.task(name, **variables)
        system = own_system or prompts.system()
        parts = [self.document_block()]
        if name not in NO_DOC:
            if self.requirements:
                parts.append(f"<требования>\n{requirements_table(self.requirements)}\n</требования>")
            block = signals_block(self.signals, AUDIENCE.get(name)) if name in AUDIENCE else ""
            if block:
                parts.append(block)
        parts.append(task)
        return system, "\n\n".join(parts)
