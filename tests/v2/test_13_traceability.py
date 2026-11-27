"""№13-Б: прослеживаемость — журнал снятых и склеенных кандидатов, матрица словами, цитаты нарезки."""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from bcc_review.v2.render import markdown  # noqa: E402

SAMPLE = ROOT / "tests" / "v2" / "fixtures" / "13_report_sample.json"
OFFICIAL = ROOT / "evaluation" / "v2" / "measurements"


@pytest.fixture()
def sample() -> dict:
    return json.loads(SAMPLE.read_text(encoding="utf-8"))


def _section(md: str, start: str, end: str) -> str:
    return md[md.index(start):md.index(end, md.index(start))]


def test_journal_every_rejected_has_id_and_fate(sample):
    md = markdown.render(sample)
    part = _section(md, "**Журнал снятых и склеенных кандидатов**", "Приложение Е")
    rows = [ln for ln in part.splitlines() if ln.startswith("| ") and not ln.startswith("| Кандидат")
            and not ln.startswith("| :")]
    assert len(rows) == len(sample["rejected"])
    for r, row in zip(sample["rejected"], rows):
        cells = [x.strip() for x in row.strip("|").split(" | ")]
        assert cells[0] == r["id"]
        assert cells[-1].startswith(("склеен → ", "снят"))
        if r.get("duplicate_of"):
            assert f"[{r['duplicate_of']}](#" in cells[-1]
    # склейки — из findings[].candidate_ids
    merged = [f for f in sample["findings"] if len(f.get("candidate_ids") or []) > 1]
    f = merged[0]
    assert " + ".join(f["candidate_ids"]) + f" → [{f['id']}](#" in part


def test_journal_missing_id_is_reported_not_invented(sample):
    r = copy.deepcopy(sample)
    r["rejected"] = [{"candidate_id": "", "source": "lens:risk", "title": "Повтор противоречия",
                      "reason": "противоречие с критерием приёмки (дубль)", "line": 38}]
    md = markdown.render(r)
    assert "| ID не передан |" in md
    assert "| — | риски |" not in md
    assert "Пробел в данных прогона" in md and "`candidate_id` пустой" in md and "`duplicate_of`" in md


def test_duplicate_of_candidate_resolves_to_card(sample):
    r = copy.deepcopy(sample)
    f = next(f for f in r["findings"] if f.get("candidate_ids"))
    r["rejected"] = [{"id": "C-900", "source": "lens:qa", "title": "Повтор", "reason": "повтор",
                      "duplicate_of": f["candidate_ids"][0]}]
    md = markdown.render(r)
    assert f"| C-900 | тестировщик | Повтор | склеен → [{f['id']}](#" in md


def test_matrix_names_criteria_in_words(sample):
    md = markdown.render(sample)
    part = _section(md, "### 3.1.", "### 3.2.")
    assert "| Требование | Итог | Нарушенные критерии | Дефекты |" in part
    assert "Как читать:" in part
    for short in ("| Од |", "| Пл |", "| Нб |", "| Рс |", "| · |"):
        assert short not in part
    assert "критичный: " in part or "существенный: " in part


def test_segmentation_quote_full_or_head_and_tail(sample):
    r = copy.deepcopy(sample)
    short = "Порог задаётся целым числом от 1 000 до 1 000 000 ₸ включительно."
    long_ = ("Начало требования про порог " + "и ещё одно условие для проверки " * 8 + "конец требования здесь.")
    r["requirements"][0]["quote"] = short
    r["requirements"][1]["quote"] = long_
    r["requirements"][1]["page"] = 3
    md = markdown.render(r)
    seg = _section(md, "2. Нарезка", "3. Проверка каждого")
    assert f"«{short}»" in seg
    row = next(ln for ln in seg.splitlines() if ln.startswith(f'| <a id="{r["requirements"][1]["id"].lower()}"'))
    assert "«Начало требования про порог" in row and "конец требования здесь.»" in row and " … " in row
    assert "стр. 3, строк" in row


@pytest.mark.parametrize("path", sorted(OFFICIAL.glob("*/report.json")), ids=lambda p: p.parent.name)
def test_official_runs_fit_900(path):
    assert markdown.render(json.loads(path.read_text(encoding="utf-8"))).count("\n") <= 900
