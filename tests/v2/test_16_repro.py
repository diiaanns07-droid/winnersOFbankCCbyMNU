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
_TIME_KEYS = {"run_id", "started_at", "finished_at", "duration_s", "seconds", "model_seconds"}  # model_seconds: 0.0/0.1 под нагрузкой (Max, Windows)

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
    # порядок ключей тоже сравнивается: этапы идут в порядке конвейера (правка №01)
    assert json.dumps(ja, ensure_ascii=False, sort_keys=False) == json.dumps(jb, ensure_ascii=False, sort_keys=False)
    for key in ("findings", "requirements", "questions", "verdict", "rejected"):
        assert a.get(key) == b.get(key), key
    md_a = _mask_md((tmp_path / "a" / "r.md").read_text(encoding="utf-8"))
    md_b = _mask_md((tmp_path / "b" / "r.md").read_text(encoding="utf-8"))
    assert md_a == md_b


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


def _repro_check():
    import importlib.util

    spec = importlib.util.spec_from_file_location("repro_check", ROOT / "scripts" / "repro_check.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_repro_check_ignores_time_but_not_content(tmp_path):
    rc = _repro_check()
    base = {"run": {"run_id": "20261127-090141-54d9", "started_at": "t1", "duration_s": 237.3,
                    "stages": {"segment": "ok", "judge": "ok"}, "calls": {"total": 9, "cached": 0}},
            "findings": [{"id": "D-01", "title": "А"}]}
    later = json.loads(json.dumps(base))
    later["run"].update({"run_id": "20261127-090637-630d", "started_at": "t2", "duration_s": 0.2})
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    a.write_text(json.dumps(base, ensure_ascii=False), encoding="utf-8")
    b.write_text(json.dumps(later, ensure_ascii=False), encoding="utf-8")
    a.with_suffix(".md").write_text("Прогон 27.11.2026 09:02–09:06 (UTC+5), 3 мин 57 с\n", encoding="utf-8")
    b.with_suffix(".md").write_text("Прогон 27.11.2026 09:06 (UTC+5), 0 с\n", encoding="utf-8")
    assert rc.main([str(a), str(b)]) == 0
    later["run"]["calls"] = {"total": 0, "cached": 9}  # из кэша: паспорт другой, содержимое то же
    b.write_text(json.dumps(later, ensure_ascii=False), encoding="utf-8")
    assert rc.main([str(a), str(b)]) == 1
    assert rc.main([str(a), str(b), "--content"]) == 0
    later["findings"][0]["title"] = "Б"
    b.write_text(json.dumps(later, ensure_ascii=False), encoding="utf-8")
    assert rc.main([str(a), str(b), "--content"]) == 1
    later["findings"][0]["title"] = "А"
    later["run"]["stages"] = {"judge": "ok", "segment": "ok"}  # другой порядок этапов — тоже различие
    b.write_text(json.dumps(later, ensure_ascii=False), encoding="utf-8")
    assert rc.main([str(a), str(b), "--content"]) == 1


def test_report_content_does_not_depend_on_hash_seed(tmp_path):
    """Разный PYTHONHASHSEED (порядок обхода множеств) не меняет находки, требования, вопросы и вердикт."""
    import os
    import subprocess
    import sys

    reports = []
    for seed in ("0", "1"):
        out = tmp_path / seed / "r.md"
        env = {**os.environ, "PYTHONHASHSEED": seed, "PYTHONIOENCODING": "utf-8"}
        proc = subprocess.run([sys.executable, "-m", "bcc_review", str(DOC), str(out), "--provider", "mock",
                               "--no-cache", "-q", "--no-html", "--runs-dir", str(tmp_path / "runs")],
                              capture_output=True, env=env, timeout=300)
        assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")[-2000:]
        reports.append(json.loads(out.with_suffix(".json").read_text(encoding="utf-8")))
    a, b = reports
    for key in ("requirements", "excluded", "findings", "rejected", "questions", "verdict", "acceptance_checks",
                "pair_checks", "trace", "glossary", "test_cases", "checklist"):
        assert a.get(key) == b.get(key), key


def test_report_has_no_local_paths(tmp_path, monkeypatch):
    """В отчёте нет абсолютных путей машины, где он сделан: тот же вход в другой папке даёт тот же отчёт."""
    import shutil

    deep = tmp_path / "Мои документы" / "ТЗ v2"
    deep.mkdir(parents=True)
    doc = deep / DOC.name
    shutil.copyfile(DOC, doc)
    from bcc_review.v2 import __main__ as cli

    out = deep / "отчёт" / "r.md"
    assert cli.main([str(doc), str(out), "--provider", "mock", "--no-cache", "--runs-dir", str(tmp_path / "runs"),
                     "-q", "--no-html"]) == 0
    for path in (out, out.with_suffix(".json")):
        text = path.read_text(encoding="utf-8")
        for needle in (str(tmp_path), str(ROOT), str(Path.home())):
            assert needle not in text, f"{path.name}: локальный путь {needle}"


@pytest.mark.xfail(strict=False, reason="просьба №04 (статус №16, патч 04_segment_latin_cache.patch): кэш _doc_latin "
                                        "не срабатывает — словарь пересчитывается по всему документу на каждое требование")
def test_segment_document_caches_are_reused():
    """Длинное ТЗ: словарь латиницы и индекс строк считаются один раз на документ, а не на каждое требование."""
    from bcc_review.v2.stages import segment

    view = {"lines": [{"n": i, "text": f"Строка {i} amountValue saveLimit", "page": None, "section": ""}
                      for i in range(1, 2001)]}
    assert segment._doc_latin(view) is segment._doc_latin(view)
    if hasattr(segment, "_by_n"):
        assert segment._by_n(view) is segment._by_n(view)


@pytest.mark.xfail(strict=False, reason="просьба №01 (статус №16, патч 01_fast_start_repeatable.patch): «проба» быстрого "
                                        "старта при нарезке из кэша выбирает другой путь — повтор не из кэша")
def test_fast_start_decision_is_replayed_when_segment_comes_from_cache(tmp_path):
    """Живой прогон записывает решение «пробы»; повтор с нарезкой из кэша идёт тем же путём, даже если проба
    (нарезка закончилась мгновенно) сказала бы «обычный путь»."""
    import concurrent.futures as cf

    from bcc_review.v2 import pipeline

    p = pipeline.Pipeline.__new__(pipeline.Pipeline)
    p.provider_name = "claude_cli"

    class FakeLLM:
        cache_dir = tmp_path
        model = "sonnet"
        fatal = None
        stats = {"by_stage": {"segment": {"calls": 1, "cached": 0}}}

    done: cf.Future = cf.Future()
    done.set_result({})
    view = {"sha256": "ab" * 32}
    assert p._fast_start_decision(view, FakeLLM(), done, True) is True       # живой прогон: быстрый старт
    FakeLLM.stats = {"by_stage": {"segment": {"calls": 0, "cached": 1}}}      # повтор: нарезка из кэша
    assert p._fast_start_decision(view, FakeLLM(), done, False) is True      # путь тот же
    other = {"sha256": "cd" * 32}                                              # другой документ — решения нет
    assert p._fast_start_decision(other, FakeLLM(), done, False) is False
