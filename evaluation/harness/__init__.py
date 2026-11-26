"""Счётчик качества ревью требований (протокол bcc-eval v1).

Публичная команда:
    python -m evaluation.harness --gold labels.jsonl --pred predictions.jsonl --out metrics.json
"""
from __future__ import annotations

import hashlib
from pathlib import Path

__version__ = "0.1.2"
# Версия правил подсчёта (пороги покрытия, паросочетание, дубли, null-знаменатели, таксономия v1).
# 0.1.1 — выбор при равных оценках и порядок списков; 0.1.2 — matrix.jsonl, --out-dir, run --docs, короткие
# каталоги отчётов. Счётные правила 0.1.0 сохраняются.
POLICY_VERSION = "bcc-eval-policy/1"


def harness_sha256() -> str:
    """Хеш версии счётчика: код *.py пакета и taxonomy.toml (переводы строк приведены к LF)."""
    root = Path(__file__).resolve().parent
    h = hashlib.sha256()
    for p in sorted([*root.glob("*.py"), root / "taxonomy.toml"]):
        h.update(p.name.encode("utf-8") + b"\0")
        h.update(p.read_bytes().replace(b"\r\n", b"\n") + b"\0")
    return h.hexdigest()
