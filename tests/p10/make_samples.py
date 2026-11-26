"""Образцы выхода №10 для №13 (HTML) и №17 (Markdown/Jira): пакет кейса до и после решений,
пакет случая «лимит одной операции» до решения, после решения и чистый контроль.

Запуск из корня репозитория:  python -m tests.p10.make_samples
Тестами не сравнивается: образцы пересобираются этой командой при изменении модуля.
"""

from __future__ import annotations

import json
from pathlib import Path

from bcc_review.bank import build_bank_pack, collect_questions, render_markdown

from . import fixture as fx
from . import limit_case as lc

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
    limit_samples()


def limit_samples() -> None:
    """Лимит операции «до 500 000 ₸»: до решения, после решения «включительно», чистый контроль."""
    doc = lc.document()
    reqs, f = lc.requirements(doc), lc.finding(doc)
    qs = lc.questions(doc, [f])
    before = lc.pack(doc, reqs, [f], [], qs)
    dec = [lc.decision(doc, qs[0]["id"], "A", note=f"Формулировка: {lc.INCLUSIVE_WORDING}")]
    after = lc.pack(doc, reqs, [f], dec, qs, previous=before)
    bound = "— до 500 000 ₸ включительно."
    cdoc = lc.document(bound)
    clean = lc.pack(cdoc, lc.requirements(cdoc, bound), [], [], [])
    for name, pack in (("limit_pack", before), ("limit_pack.agreed", after), ("limit_pack.clean", clean)):
        data = dict(pack, questions=collect_questions(pack))
        (OUT / f"{name}.json").write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        (OUT / f"{name}.md").write_text(render_markdown(pack), encoding="utf-8")
    row = lc.testability(after)
    print(f"лимит: {row['id']} «{row['text']}» — {lc.testability(before)['cells']['checked']} → {row['cells']['checked']}; "
          f"чистый контроль — {lc.testability(clean)['cells']['checked']}")


if __name__ == "__main__":
    main()
