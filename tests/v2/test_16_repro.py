"""№16: повторяемость — одинаковый вход (и кэш) → одинаковый отчёт байт в байт, кроме времени.

Без сети и без модели: провайдер mock (записанные ответы) и поддельный провайдер с кэшем во временном каталоге.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / "release" / "input" / "requirements.md"

# Порядок этапов, как их запускает конвейер (линзы — в порядке types.LENSES).
CANON = ["segment", "rules", "lens_analyst", "lens_qa", "lens_architect", "lens_risk", "consistency", "quotes",
         "judge", "clarify", "recheck"]

# Поля паспорта, в которых разница между прогонами допустима: время и номер прогона.
_TIME_KEYS = {"run_id", "started_at", "finished_at", "duration_s", "seconds"}

# В Markdown: дата и время прогона, длительности этапов и всего прогона.
_MD_TIME = [
    re.compile(r"\d{2}\.\d{2}\.\d{4} \d{2}:\d{2}(?:–\d{2}:\d{2})?(?: \(UTC[+-]\d+\))?"),
    re.compile(r"\b\d+ мин(?: \d+ с)?\b|\b\d+(?:[.,]\d+)? с\b"),
    re.compile(r"\b\d{8}-\d{6}-[0-9a-f]{4}\b"),  # run_id
]


def _mask_md(text: str) -> str:
    for rx in _MD_TIME:
        text = rx.sub("<время>", text)
    return text


def _mask_json(x):
    if isinstance(x, dict):
        return {k: ("<время>" if k in _TIME_KEYS else _mask_json(v)) for k, v in x.items()}
    if isinstance(x, list):
        return [_mask_json(v) for v in x]
    return x


def _run_mock(out: Path, runs: Path, monkeypatch, delays: dict[str, float] | None = None) -> dict:
    """Прогон mock в этом же процессе; delays — задержка ответа по этапам (меняет порядок завершения линз)."""
    from bcc_review.v2 import __main__ as cli
    from bcc_review.v2.providers import mock

    if delays:
        orig = mock.MockProvider.invoke

        def slow(self, **kw):
            time.sleep(delays.get(kw.get("stage") or "", 0.0))
            return orig(self, **kw)

        monkeypatch.setattr(mock.MockProvider, "invoke", slow)
    code = cli.main([str(DOC), str(out), "--provider", "mock", "--no-cache", "--runs-dir", str(runs), "-q",
                     "--no-html"])
    assert code == 0
    return json.loads(out.with_suffix(".json").read_text(encoding="utf-8"))


@pytest.mark.xfail(strict=False, reason="просьба №01 (статус №16, «Волна 3»): pipeline записывает этапы в порядке "
                                        "завершения потоков; нужен канонический порядок в run.stages/stage_stats")
def test_stage_order_does_not_depend_on_which_lens_finishes_first(tmp_path, monkeypatch):
    """Линзы идут параллельно; порядок их завершения не должен менять ни JSON, ни Markdown."""
    a = _run_mock(tmp_path / "a" / "r.md", tmp_path / "runs", monkeypatch)
    # первая по порядку линза отвечает последней
    b = _run_mock(tmp_path / "b" / "r.md", tmp_path / "runs", monkeypatch,
                  delays={"lens_analyst": 0.6, "lens_qa": 0.4, "lens_architect": 0.2})
    for rep in (a, b):
        keys = list(rep["run"]["stages"])
        assert keys == sorted(keys, key=lambda k: CANON.index(k) if k in CANON else len(CANON)), keys
        keys = list(rep["run"]["stage_stats"])
        assert keys == sorted(keys, key=lambda k: CANON.index(k) if k in CANON else len(CANON)), keys
    md_a = _mask_md((tmp_path / "a" / "r.md").read_text(encoding="utf-8"))
    md_b = _mask_md((tmp_path / "b" / "r.md").read_text(encoding="utf-8"))
    assert md_a == md_b


def test_two_mock_runs_give_same_report_except_time(tmp_path, monkeypatch):
    """Два прогона одного входа: JSON совпадает после маскировки времени (содержимое, счётчики, порядок ключей)."""
    a = _run_mock(tmp_path / "a" / "r.md", tmp_path / "runs", monkeypatch)
    b = _run_mock(tmp_path / "b" / "r.md", tmp_path / "runs", monkeypatch)
    ja, jb = _mask_json(a), _mask_json(b)
    # порядок этапов проверяет тест выше (xfail до правки №01) — здесь сравниваем содержимое
    for j in (ja, jb):
        j["run"]["stages"] = dict(sorted(j["run"]["stages"].items()))
        j["run"]["stage_stats"] = dict(sorted(j["run"]["stage_stats"].items()))
    assert json.dumps(ja, ensure_ascii=False, sort_keys=False) == json.dumps(jb, ensure_ascii=False, sort_keys=False)
    for key in ("findings", "requirements", "questions", "verdict", "rejected"):
        assert a.get(key) == b.get(key), key


class _FakeProvider:
    """Отвечает одинаково; считает вызовы — так видно, что второй прогон взят из кэша."""

    name = "fake"

    def __init__(self) -> None:
        self.calls = 0

    def invoke(self, *, model, messages, schema, timeout_s=0, max_output_tokens=None, stage="", **_):
        self.calls += 1
        return {"data": {"ok": True}, "model": "fake-model-1", "usage": {"input_tokens": 10, "output_tokens": 5},
                "stop_reason": "end_turn", "meta": {"models_used": ["fake-model-1"]}}


def test_cache_returns_same_answer_without_calling_model(tmp_path):
    from bcc_review.v2.llm import LLMClient

    schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]}
    p1, p2 = _FakeProvider(), _FakeProvider()
    first = LLMClient(p1, model="m", cache_dir=tmp_path).ask("judge", "system", "user", schema)
    second = LLMClient(p2, model="m", cache_dir=tmp_path).ask("judge", "system", "user", schema)
    assert first == second
    assert (p1.calls, p2.calls) == (1, 0)


@pytest.mark.xfail(strict=False, reason="просьба №01 (статус №16, «Волна 3»): при ответе из кэша llm.py не добавляет "
                                        "модель в models_used → отчёт пишет «режим без модели»")
def test_cached_answers_keep_model_in_passport(tmp_path):
    """Прогон целиком из кэша — это всё ещё ответы модели: паспорт называет модель, а не «без модели»."""
    from bcc_review.v2.llm import LLMClient

    schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]}
    live = LLMClient(_FakeProvider(), model="m", cache_dir=tmp_path)
    live.ask("judge", "system", "user", schema)
    cached = LLMClient(_FakeProvider(), model="m", cache_dir=tmp_path)
    cached.ask("judge", "system", "user", schema)
    assert cached.summary()["calls"]["cached"] == 1
    assert cached.summary()["models_used"] == live.summary()["models_used"] == ["fake-model-1"]


@pytest.mark.xfail(strict=False, reason="просьба №13 (статус №16, «Волна 3»): отчёт считает прогон «без модели», "
                                        "если models_used пуст, даже когда все этапы модели выполнены из кэша")
def test_report_from_cache_is_not_called_offline(tmp_path, monkeypatch):
    """Паспорт прогона из кэша (models_used пуст, все вызовы — кэш) не должен рендериться как режим без модели."""
    from bcc_review.v2.render import markdown

    report = _run_mock(tmp_path / "a" / "r.md", tmp_path / "runs", monkeypatch)
    run = report["run"]
    run["provider"] = "claude_cli"
    run["models_used"] = []
    run["calls"] = {"total": 0, "cached": 9, "failed": 0, "split": 0}
    md = markdown.render(report)
    assert "Режим без модели" not in md
