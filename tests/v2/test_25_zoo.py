"""№25: «зоопарк» трудных входов — каждый документ банка читается без потерь, с верной страницей и разделом.

Файлы и ожидания (``truth.json``) пересоздаёт tests/v2/fixtures/25_zoo/make_zoo.py. Для каждого файла:

* строки пронумерованы подряд, документ читается без исключений;
* каждая фраза из ``keep`` целиком лежит на одной строке, раздел строки содержит ожидаемый, страница верна;
* сверка цитат находит фразу именно на этой строке (как цитату модели — без подсказки строки);
* фраз из ``absent`` (колонтитулы, удалённый текст, примечания рецензента, служебные знаки) в тексте нет.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bcc_review.v2 import docview as dv
from bcc_review.v2 import quotes as Q

Z = Path(__file__).resolve().parent / "fixtures/25_zoo"
TRUTH = json.loads((Z / "truth.json").read_text(encoding="utf-8"))


def _has(mod: str) -> bool:
    try:
        __import__(mod)
        return True
    except Exception:  # noqa: BLE001
        return False


def _skip(name: str):
    if name.endswith(".pdf") and not _has("pymupdf"):
        pytest.skip("нет pymupdf")
    if name.endswith(".docx") and not _has("docx"):
        pytest.skip("нет python-docx")


_VIEWS: dict[str, dict] = {}


def _view(name: str) -> dict:
    if name not in _VIEWS:
        _VIEWS[name] = dv.load(Z / name)
    return _VIEWS[name]


def _flat(s: str) -> str:
    return " ".join(s.split())


CASES = [(name, i) for name, t in TRUTH.items() for i in range(len(t["keep"]))]


def test_zoo_size():
    assert len(TRUTH) >= 12


@pytest.mark.parametrize("name", sorted(TRUTH))
def test_reads_numbered_without_loss_markers(name):
    _skip(name)
    v = _view(name)
    assert [ln["n"] for ln in v["lines"]] == list(range(1, len(v["lines"]) + 1))
    joined = "\n".join(ln["text"] for ln in v["lines"])
    for bad in TRUTH[name]["absent"]:
        assert bad not in joined, f"{name}: лишнее в тексте: {bad!r}"
    for bad, why in TRUTH[name].get("known_absent", {}).items():
        if bad in joined:
            print(f"известное ограничение: {bad!r} — {why}")
    for w in TRUTH[name]["warn"]:
        assert any(w in x for x in v["warnings"]), (name, v["warnings"])


@pytest.mark.parametrize("name,i", CASES, ids=[f"{n}-{i}" for n, i in CASES])
def test_phrase_on_one_line_with_place(name, i):
    _skip(name)
    v = _view(name)
    want = TRUTH[name]["keep"][i]
    if want.get("known"):
        pytest.xfail(want["known"])  # известное ограничение; снятие ловит test_known_limits_still_open
    phrase = _flat(want["text"])
    hits = [ln for ln in v["lines"] if phrase in _flat(ln["text"])]
    assert hits, f"{name}: фраза не на одной строке: {phrase!r}\n" + dv.numbered(v)
    ln = hits[0]
    if want["section"]:
        assert want["section"] in ln["section"], (name, phrase, ln["section"])
    if want["page"] is not None:
        assert ln["page"] == want["page"], (name, phrase, ln["page"])
    m = Q.verify_quote(v, want["text"])
    assert m and m["line_start"] <= ln["n"] <= m["line_end"], (name, phrase, m)


def test_known_limits_still_open():
    """Известные ограничения записаны честно: если исправлено — снимите запись в make_zoo.KNOWN."""
    for name, t in TRUTH.items():
        for w in t["keep"]:
            if w.get("known") and not (name.endswith(".pdf") and not _has("pymupdf")):
                v = _view(name)
                assert not any(_flat(w["text"]) in _flat(ln["text"]) for ln in v["lines"]), \
                    f"{name}: ограничение снято — уберите из KNOWN: {w['text']}"
