"""Общая настройка тестов v2 (№01): пакет из src/ без установки, ответы модели — только mock."""
from __future__ import annotations

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

# Подпроцессы тестов (`python -m bcc_review …`) тоже видят пакет без установки.
import os  # noqa: E402

_pp = os.environ.get("PYTHONPATH", "")
if str(SRC) not in _pp.split(os.pathsep):
    os.environ["PYTHONPATH"] = str(SRC) + (os.pathsep + _pp if _pp else "")
