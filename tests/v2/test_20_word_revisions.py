"""«Было → стало» исправлениями Word: правки --revise в копии DOCX режимом рецензирования.

Правки — записанные агентом для документа кейса (examples/v2/demo_answers, живой прогон sonnet), документ —
release/input/requirements.docx. «Отклонить все» должно вернуть исходный текст, «Принять все» — дать «стало».
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

docx = pytest.importorskip("docx")
from docx.oxml.ns import qn  # noqa: E402

from bcc_review.v2.render import word_revisions as W  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
DOCX = ROOT / "release/input/requirements.docx"
REWRITES = json.loads((ROOT / "examples/v2/demo_answers/requirements.json").read_text(encoding="utf-8"))["rewrites"]


def _text(doc, mode: str) -> str:
    """Текст тела после «Принять все» (accept) или «Отклонить все» (reject)."""
    out = []
    for p in doc.element.body.iter(qn("w:p")):
        ppr_ins = p.find(f"{qn('w:pPr')}/{qn('w:rPr')}/{qn('w:ins')}")
        if mode == "reject" and ppr_ins is not None:
            continue
        parts = []
        for el in p.iter():
            tag = el.tag
            if tag == qn("w:t"):
                in_ins = any(a.tag == qn("w:ins") for a in el.iterancestors())
                if mode == "reject" and in_ins:
                    continue
                parts.append(el.text or "")
            elif tag == qn("w:delText") and mode == "reject":
                parts.append(el.text or "")
        out.append("".join(parts))
    return "\n".join(out)


@pytest.fixture(scope="module")
def revised(tmp_path_factory):
    out = tmp_path_factory.mktemp("rev") / "r.docx"
    stats = W.write_revisions(DOCX, REWRITES, None, out)
    return stats, out


def test_most_rewrites_land_as_tracked_changes(revised):
    stats, out = revised
    assert stats["applied"] >= 35 and stats["total"] == len([r for r in REWRITES if r.get("applied") is not False])
    xml = (docx.Document(str(out))).element.xml
    assert xml.count("<w:del ") >= 30 and xml.count("<w:ins ") >= 30
    assert 'w:author="BCC Review"' in xml


def test_reject_all_restores_original_text(revised):
    _, out = revised
    original = _text(docx.Document(str(DOCX)), "accept")
    assert _text(docx.Document(str(out)), "reject") == original


def test_accept_all_gives_new_wording(revised):
    _, out = revised
    accepted = _text(docx.Document(str(out)), "accept")
    assert "Месяц определяется по дате и времени совершения покупки" in accepted
    assert "Месяц определяется по дате совершения покупки в Алматы." not in accepted
    assert "/alerts/limit" in accepted or "PUT" in accepted


def test_ambiguous_fragment_is_left_alone(tmp_path):
    rw = [{"finding_id": "D-1", "action": "replace", "line_start": 999, "before": "или", "after": "и"}]
    stats = W.write_revisions(DOCX, rw, None, tmp_path / "x.docx")
    assert stats["applied"] == 0 and not (tmp_path / "x.docx").exists()


def test_insert_after_uses_view_line_and_marks_paragraph(tmp_path):
    d = docx.Document(str(DOCX))
    target = next(p.text for p in d.paragraphs if p.text.startswith("Ф-3") or "Ф-3." in p.text)
    view = {"lines": [{"n": 7, "text": target}]}
    rw = [{"finding_id": "D-9", "action": "insert_after", "line_start": 7, "before": "",
           "after": "#### Новый пункт\n\n| Поле | Значение |\n| :--- | :--- |\n| a | b |"}]
    stats = W.apply_rewrites(d, rw, view)
    assert stats["applied"] == 1
    texts = [W._para_text(p._p) for p in d.paragraphs]  # python-docx .text не видит run внутри w:ins
    i = texts.index(target)
    assert texts[i + 1:i + 4] == ["Новый пункт", "Поле · Значение", "a · b"]
    assert _text(d, "reject").count("Новый пункт") == 0
