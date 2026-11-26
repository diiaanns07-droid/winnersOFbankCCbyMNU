"""Образцы выхода №10 для №13 (HTML) и №17 (Markdown/Jira): пакет кейса до и после решений.

Запуск из корня репозитория:  python -m tests.p10.make_samples
Тестами не сравнивается: образцы пересобираются этой командой при изменении модуля.
"""

from __future__ import annotations

import json
from pathlib import Path

from bcc_review.bank import build_bank_pack, collect_questions, render_markdown

from . import fixture as fx

OUT = Path(__file__).parent / "samples"


def main() -> None:
    c = fx.case()
    args = dict(coverage=fx.coverage(), questions=fx.questions(), criteria=fx.CRITERIA, complete=True)
    before = build_bank_pack(c["document"], c["requirements"], c["findings"], [], None, **args)
    after = build_bank_pack(c["document"], c["requirements"], c["findings"], fx.decisions(c["document"]), None, previous=before, **args)
    OUT.mkdir(exist_ok=True)
    for name, pack in (("case_pack.json", before), ("case_pack.agreed.json", after)):
        data = dict(pack, questions=collect_questions(pack))
        (OUT / name).write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    (OUT / "case_pack.md").write_text(render_markdown(before), encoding="utf-8")
    (OUT / "case_pack.agreed.md").write_text(render_markdown(after), encoding="utf-8")
    print(f"чек-лист: {len(before['checklist'])} строк; сценариев: {len(before['test_cases'])}; "
          f"открыто до решений: {sum(t['status'] == 'open' for t in before['test_cases'])}, "
          f"после: {sum(t['status'] == 'open' for t in after['test_cases'])}")


if __name__ == "__main__":
    main()
