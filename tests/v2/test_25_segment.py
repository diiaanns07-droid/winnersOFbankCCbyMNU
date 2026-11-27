"""№25, v2.1: нарезка одного документа одинакова в MD, PDF и DOCX; номера пунктов вложенных списков без своих ID.

* Паритет: эвристическая нарезка (без модели) официального ТЗ и ТЗ ``open2`` даёт одинаковые source_id в одном
  порядке во всех трёх форматах (до склейки слов в ячейках PDF — 8 из 9 ТЗ ``open2``, после — 9 из 9).
* Вложенный нумерованный список («1. Заказ» › «1. Клиент выбирает…», «2. Клиент указывает…» › «a. …»): у пунктов
  было три одинаковых source_id «Функциональные требования, п. 1»; теперь «п. 1.1», «п. 1.2», «п. 1.2.a» — в
  эвристике и в ответе модели (canonical_source_ids переводит «п. 1» вложенного пункта в «п. 1.1»).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from bcc_review.v2 import docview as dv
from bcc_review.v2.stages import segment as S

ROOT = Path(__file__).resolve().parents[2]
Z = ROOT / "tests/v2/fixtures/25_zoo"


def _has(mod: str) -> bool:
    try:
        __import__(mod)
        return True
    except Exception:  # noqa: BLE001
        return False


def _ids(path: Path) -> list[str]:
    return [r.get("source_id") or "" for r in S.heuristic_segment(dv.load(path))["requirements"]]


@pytest.mark.skipif(not (_has("pymupdf") and _has("docx")), reason="нужны pymupdf и python-docx")
@pytest.mark.parametrize("base", ["release/input/requirements", "evaluation/v2/open2/insurance_clean/source",
                                  "evaluation/v2/open2/capital_clean/source", "evaluation/v2/open2/qr/source"])
def test_same_segmentation_in_md_pdf_docx(base):
    md = _ids(ROOT / f"{base}.md")
    assert len(md) >= 30
    assert _ids(ROOT / f"{base}.pdf") == md
    assert _ids(ROOT / f"{base}.docx") == md


def _nested_expected(ids: list[str]) -> None:
    want = ["Функциональные требования, п. 1", "Функциональные требования, п. 1.1",
            "Функциональные требования, п. 1.2", "Функциональные требования, п. 1.2.a",
            "Функциональные требования, п. 1.2.b", "Функциональные требования, п. 2",
            "Функциональные требования, п. 2.1", "Функциональные требования, п. 2.2"]
    got = [i for i in ids if i.startswith("Функциональные требования")]
    assert got == want, got


@pytest.mark.skipif(not _has("pymupdf"), reason="нет pymupdf")
def test_nested_list_ids_pdf():
    _nested_expected(_ids(Z / "pdf_from_word.pdf"))


def test_nested_list_ids_md(tmp_path):
    p = tmp_path / "t.md"
    # в Markdown «a.» — не пункт списка (только цифры), третий уровень — цифрами
    p.write_text("# Т\n\n## Функциональные требования\n\n1. Заказ перевыпуска\n    1. Клиент выбирает карту.\n"
                 "    2. Клиент указывает причину.\n        1. Для утери блокируется сразу.\n"
                 "        2. Для повреждения действует.\n2. Оплата\n    1. Стоимость списывается.\n"
                 "    2. Нехватка средств — ожидание.\n", encoding="utf-8")
    got = [i for i in _ids(p) if i]
    assert got == ["Функциональные требования, п. " + x for x in ("1", "1.1", "1.2", "1.2.1", "1.2.2", "2", "2.1",
                                                                     "2.2")], got


@pytest.mark.skipif(not _has("docx"), reason="нет python-docx")
def test_nested_list_ids_docx():
    """DOCX как PDF того же документа. Пока не влит патч v1 (просьба №22, нумерация вложенных списков) Word-номер
    «2. Оплата» читается как «1.» — тогда ожидаем ту же схему от «1»; после патча — ровно как в PDF."""
    v = dv.load(Z / "docx_autonum.docx")
    if any(ln["text"] == "2. Оплата" for ln in v["lines"]):
        _nested_expected(_ids(Z / "docx_autonum.docx"))
    else:
        got = [i for i in _ids(Z / "docx_autonum.docx") if i.startswith("Функциональные требования")]
        assert got[:5] == ["Функциональные требования, п. " + x for x in ("1", "1.1", "1.2", "1.2.a", "1.2.b")]


def test_model_answer_nested_item_gets_parent_number(tmp_path):
    p = tmp_path / "t.md"
    p.write_text("# Т\n\n## Функциональные требования\n\n1. Заказ перевыпуска\n    1. Клиент выбирает карту из списка.\n"
                 "    2. Клиент указывает причину перевыпуска.\n2. Оплата\n    1. Стоимость списывается в день выпуска.\n",
                 encoding="utf-8")
    v = dv.load(p)
    n = {ln["text"]: ln["n"] for ln in v["lines"] if ln["text"]}
    raw = {"requirements": [
        {"id": "R-1", "source_id": "Функциональные требования, п. 1", "line_start": n["1. Клиент выбирает карту из списка."],
         "line_end": n["1. Клиент выбирает карту из списка."], "quote": "Клиент выбирает карту из списка",
         "summary": "Выбор карты", "kind": "functional"},
        {"id": "R-2", "source_id": "Функциональные требования, п. 1",
         "line_start": n["1. Стоимость списывается в день выпуска."],
         "line_end": n["1. Стоимость списывается в день выпуска."], "quote": "Стоимость списывается в день выпуска",
         "summary": "Списание", "kind": "functional"},
    ], "excluded": []}
    out = S.segment_from_response(v, raw)
    sids = sorted(r["source_id"] for r in out["requirements"] if r.get("source_id"))
    assert sids == ["Функциональные требования, п. 1.1", "Функциональные требования, п. 2.1"], sids


def test_flat_lists_keep_old_numbers(tmp_path):
    p = tmp_path / "t.md"
    p.write_text("# Т\n\n## Критерии\n\n1. Первый критерий выполняется.\n2. Второй критерий выполняется.\n",
                 encoding="utf-8")
    assert [i for i in _ids(p) if i] == ["Критерии, п. 1", "Критерии, п. 2"]
