"""№22 — ядро для маскирования ПДн №30 (``rules/redact.py``): ``--redact``; ПДн в ``runs/`` и кэше маскированы, а
повтор и пересмотр получают их обратно из текста документа — цитаты сходятся, отчёт тот же."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

redact = pytest.importorskip("bcc_review.v2.rules.redact")

ROOT = Path(__file__).resolve().parents[2]
FX = ROOT / "tests" / "v2" / "fixtures" / "30_redact"


def _cards(n: int = 1, tail: str = "678", last: str | None = None) -> list[str]:
    """Номера карт, проходящие проверку Луна; с ``last`` — с одинаковыми последними четырьмя цифрами."""
    out = []
    for i in range(1, 100000):
        body = f"4400{i:08d}{tail}"
        d = next(str(x) for x in range(10) if redact.luhn(body + str(x)))
        if last is None or d == last:
            out.append(body + d)
        if len(out) == n:
            return out
    raise AssertionError("нет номеров")


def _spaced(card: str) -> str:
    return " ".join(card[i:i + 4] for i in range(0, 16, 4))


def _view(*texts: str) -> dict:
    return {"lines": [{"n": i + 1, "text": t} for i, t in enumerate(texts)]}


def test_restorer_maps_masks_back_from_document():
    from bcc_review.v2.runs import mask_pd, pd_restorer
    card = _spaced(_cards()[0])
    line = f"Карта клиента {card}, почта asel.n@mail.kz"
    restore = pd_restorer(_view("Заголовок", line))
    assert restore is not None
    rec = {"output": {"candidates": [{"quote": line, "title": "почта asel.n@mail.kz в примере", "n": 3}]}}
    masked = mask_pd(rec)
    assert card not in json.dumps(masked, ensure_ascii=False) and "asel.n@" not in json.dumps(masked)
    assert restore(masked) == rec


def test_restorer_skips_ambiguous_and_literal_masks():
    from bcc_review.v2.runs import pd_restorer
    assert pd_restorer(_view("Без персональных данных", "Сумма 250,00 ₸, срок 5 дней")) is None
    c1, c2 = (_spaced(c) for c in _cards(2, last="9"))
    assert c1 != c2 and c1[-4:] == c2[-4:]
    assert pd_restorer(_view(f"карта {c1}", f"карта {c2}")) is None  # одна маска — два значения
    shown = redact.mask(f"карта {c1}")[len("карта "):]
    assert pd_restorer(_view(f"карта {c1}", f"В интерфейсе номер показан как {shown}")) is None  # маска есть в документе


@pytest.mark.skipif(not (FX / "mock").is_dir(), reason="фикстуры №30")
def test_runs_masked_and_replay_restores_quotes(tmp_path):
    from bcc_review.v2.__main__ import main
    out_a, out_b = tmp_path / "a.md", tmp_path / "b.md"
    common = ["--no-html", "--no-cache", "-q"]
    assert main([str(FX / "pd_doc.md"), str(out_a), "--provider", "mock", "--mock-dir", str(FX / "mock"),
                 "--runs-dir", str(tmp_path / "runs"), *common]) in (0, 1)
    run = next((tmp_path / "runs").iterdir())
    assert redact.scan_paths([tmp_path / "runs"]) == []
    assert main([str(FX / "pd_doc.md"), str(out_b), "--replay", str(run), "--runs-dir", str(tmp_path / "runs2"),
                 *common]) in (0, 1)
    a = json.loads(out_a.with_suffix(".json").read_text(encoding="utf-8"))
    b = json.loads(out_b.with_suffix(".json").read_text(encoding="utf-8"))

    def sig(r: dict) -> list:
        return [(f["id"], f.get("title"), [e.get("quote") for e in f.get("evidence") or []]) for f in r["findings"]]

    assert sig(a) == sig(b)
    assert any(redact.find(q or "") for _, _, qs in sig(a) for q in qs)  # цитаты с ПДн — есть, и в повторе те же
    assert b["run"]["replay"]["calls_live"] == 0
    assert redact.scan_paths([tmp_path / "runs2"]) == []


def test_cache_skips_payload_with_pd(tmp_path):
    from bcc_review.v2.llm import LLMClient
    from bcc_review.v2.providers.mock import MockProvider
    llm = LLMClient(MockProvider(fixtures_dir=tmp_path), model=None, provider_name="mock", cache_dir=tmp_path / "c")
    llm._cache_put("k1", {"data": {"x": "без персональных данных"}})
    llm._cache_put("k2", {"data": {"x": "почта asel.n@mail.kz"}})
    assert sorted(p.stem for p in (tmp_path / "c").glob("*.json")) == ["k1"]


def test_redact_without_module_exit_2(tmp_path, monkeypatch, capsys):
    import bcc_review.v2.runs as runs
    from bcc_review.v2.__main__ import main
    monkeypatch.setattr(runs, "redact_available", lambda: False)
    doc = tmp_path / "d.md"
    doc.write_text("# ТЗ\n\n1. Система отправляет уведомление.\n", encoding="utf-8")
    assert main([str(doc), str(tmp_path / "r.md"), "--provider", "mock", "--redact", "-q", "--no-html"]) == 2
    assert "--redact" in capsys.readouterr().err
