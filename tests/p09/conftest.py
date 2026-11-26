"""Пакет bcc_review лежит в src/; до публикации bootstrap Max добавляем путь здесь."""

import pathlib
import sys

SRC = pathlib.Path(__file__).resolve().parents[2] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
