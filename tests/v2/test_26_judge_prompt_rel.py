"""Промпт судьи (№26, релиз, промпт 45): строки общими словами — разные места правки, пояс городом,
неполное правило документа. Слов официального документа в промпте нет (antifit)."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TEXT = (ROOT / "src" / "bcc_review" / "v2" / "prompts" / "judge.md").read_text(encoding="utf-8")


def test_prompt_states_rule_in_general_words():
    assert "одна и та же правка в одном и том же месте" in TEXT
    assert "«что хранить» и «что показать или отправить пользователю»" in TEXT


def test_prompt_city_zone_is_not_exact_sense():
    assert "Часовой пояс, названный городом или регионом без смещения от UTC, — не точный" in TEXT


def test_prompt_incomplete_rule_of_document_is_not_wish():
    assert "а кандидат показывает, что правило неполно, — это" in TEXT
    assert "не пожелание: `wish = false`" in TEXT
