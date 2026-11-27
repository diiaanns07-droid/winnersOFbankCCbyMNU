"""№02: фатальная ошибка провайдера, пойманная внутри этапа, всё равно объясняется первой строкой.

Живой случай (27.11 10:57, sonnet): лимит подписки Claude Code кончился на второй проверке серьёзности судьи.
Судья ловит ``LLMError`` сам («вторая проверка серьёзности не удалась (LLMError)»), обёртка этапа ошибку не
видит — прогон ``partial``, а причины (лимит подписки и время сброса) нет ни в консоли, ни в отчёте. Ворота
волны 3: «``partial`` — всегда с понятной причиной». Правка — в ``pipeline.stage`` (файл №01), патч
``tests/v2/fixtures/02_providers/patches/01_fatal_caught_inside_stage.patch``; до слияния тест помечен xfail.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from bcc_review.contracts import ProviderError
from bcc_review.v2.providers.mock import MockProvider

ROOT = Path(__file__).resolve().parents[2]
LIMIT = ("Исчерпан лимит подписки Claude Code. Сброс лимита: 8:50am (UTC). До сброса выберите другую модель "
         "(--model haiku) или провайдера (--provider gemini с GEMINI_API_KEY). "
         "[claude -p, модель sonnet: You've hit your 5-hour limit · resets 8:50am (UTC)]")


class LimitOnSecondJudge(MockProvider):
    """Ответы mock-фикстур официального документа; второй вызов судьи — лимит подписки (как в живом прогоне)."""
    name = "claude_cli"

    def invoke(self, *, stage: str = "", **kw):
        if stage == "judge" and self.counts.get("judge", 0) >= 1:
            raise ProviderError("quota", LIMIT, model="sonnet")
        return super().invoke(stage=stage, **kw)


def _patched() -> bool:
    text = (ROOT / "src" / "bcc_review" / "v2" / "pipeline.py").read_text(encoding="utf-8")
    return "Этап мог сам поймать фатальную ошибку провайдера" in text


@pytest.mark.xfail(not _patched(), reason="ждёт патч №01: tests/v2/fixtures/02_providers/patches/"
                                          "01_fatal_caught_inside_stage.patch", strict=False)
def test_subscription_limit_inside_judge_is_first_warning(tmp_path, monkeypatch, capsys):
    from bcc_review.v2 import __main__ as cli
    from bcc_review.v2.providers import doctor

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(doctor, "make_provider", lambda name, **kw: LimitOnSecondJudge(
        fixtures_dir=ROOT / "tests" / "v2" / "fixtures" / "official", model="sonnet"))
    doc = ROOT / "release" / "input" / "requirements.md"
    cli.main([str(doc), str(tmp_path / "r.md"), "--provider", "claude_cli", "--model", "sonnet", "--no-cache",
              "--no-html"])
    report = json.loads((tmp_path / "r.json").read_text(encoding="utf-8"))
    first = report["run"]["warnings"][0]
    assert first.startswith("Исчерпан лимит подписки Claude Code. Сброс лимита: 8:50am (UTC)."), \
        report["run"]["warnings"][:3]
    assert report["run"].get("model_error", "").startswith("Исчерпан лимит подписки")
