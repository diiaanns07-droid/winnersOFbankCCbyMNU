"""Тесты №10 запускаются и без установки пакета: src добавляется в путь."""

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
