"""Тесты №12 (адаптер Gemini).

Пакет, чтобы ``tests/p12/conftest.py`` не занимал общее имя модуля ``conftest`` (тесты №11 делают
``from conftest import ...``). Без установки пакета ``src`` добавляется в путь здесь: этот файл
импортируется раньше conftest и тестовых модулей, так что ``python -m pytest tests/p12 -q`` работает
и из чистого checkout.
"""

import sys
from pathlib import Path

_SRC = str(Path(__file__).resolve().parents[2] / "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)
