"""№30: полнота офлайн-режима (без модели) — новые общие правила; на чистых ТЗ не срабатывают."""
from __future__ import annotations

from pathlib import Path

from bcc_review.v2 import docview, rules

ROOT = Path(__file__).resolve().parents[2]


def _run(tmp_path: Path, text: str) -> dict:
    p = tmp_path / "doc.md"
    p.write_text(text, encoding="utf-8")
    return rules.run(docview.load(str(p)))


def _src(out: dict, prefix: str) -> list[dict]:
    return [c for c in out["candidates"] if c["source"].startswith(prefix)]


CAP = """# Напоминания об оплате

## Функциональные требования
* **ФТ-1.** Когда до даты платежа остаётся 3 дня, клиент получает SMS. Клиенту приходит не более одного SMS в сутки.
* **ФТ-2.** Если клиент изменил дату платежа, новое наступление срока вызывает SMS независимо от истории отправок.
"""


def test_period_cap_vs_regardless(tmp_path: Path) -> None:
    out = _run(tmp_path, CAP)
    c = _src(out, "rules:conflicts.event_quantity")
    assert len(c) == 1 and c[0]["severity"] == "critical"
    assert {e["line"] for e in c[0]["evidence"]} == {4, 5}


def test_period_cap_without_regardless_is_silent(tmp_path: Path) -> None:
    out = _run(tmp_path, CAP.replace(" независимо от истории отправок", ", но не чаще лимита ФТ-1"))
    assert _src(out, "rules:conflicts.event_quantity") == []
    # «независимо от» о другом предмете — не конфликт
    out = _run(tmp_path, CAP.replace("вызывает SMS независимо от истории отправок",
                                     "пересчитывает график независимо от истории изменений"))
    assert _src(out, "rules:conflicts.event_quantity") == []


def test_official_offline_finds_cap_conflict() -> None:
    out = rules.run(docview.load(str(ROOT / "release" / "input" / "requirements.md")))
    c = _src(out, "rules:conflicts.event_quantity")
    assert len(c) == 1 and c[0]["severity"] == "critical"
