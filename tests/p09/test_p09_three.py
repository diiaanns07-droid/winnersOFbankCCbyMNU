"""Повторное ревью при изменении порядка пунктов: три редакции одного ТЗ, отчёты штатным путём.

Отчёты строит движок (`run_review`, `--offline-lint`: правила без модели). Правила объединяют одинаковый
дефект двух похожих формулировок в одну находку F-001 с двумя пунктами. Когда правят одну из них,
части F-001 получают разные статусы: кредитная — «исправлено в тексте», дебетовая — «сохранилось».
"""

import json
import os
import pathlib
import random
import subprocess
import sys

import pytest

pytest.importorskip("bcc_review.engine", reason="движок Max ещё не в ветке")

from bcc_review.contracts import validate  # noqa: E402
from bcc_review.decisions.diff import compare_reports  # noqa: E402
from p09_case import (  # noqa: E402
    S_FT,
    assert_valid_report,
    clone,
    document,
    finding,
    issue_checks,
    report,
    requirements,
)
from p09_three import CREDIT_V3, EDITIONS, run_standard, write_inputs  # noqa: E402

SRC = pathlib.Path(__file__).resolve().parents[2] / "src"


@pytest.fixture(scope="module")
def runs(tmp_path_factory):
    """v1, v2, v3 и неполный повтор v3 — штатным путём; v2 и v3 ещё и с --compare к предыдущей."""
    root = tmp_path_factory.mktemp("three")
    inp = write_inputs(root / "input")
    rep = root / "reports"  # отчёты отдельно от входов: движок не защищает вход от перезаписи
    out = {k: run_standard(inp[k], rep / f"{k}.md") for k in ("v1", "v2", "v3", "v3_unreadable")}
    out["v2_cmp"] = run_standard(inp["v2"], rep / "v2_cmp.md", compare=rep / "v1.json")
    out["v3_cmp"] = run_standard(inp["v3"], rep / "v3_cmp.md", compare=rep / "v2.json")
    for name, text in EDITIONS.items():
        assert inp[name].read_bytes() == text.encode("utf-8")  # вход не тронут
    out["_input"], out["_reports"] = root / "input", rep
    return out


def matrix(diff: dict) -> list[tuple]:
    """(старая находка[часть], новая находка, статус, код) — строки матрицы."""
    rows = []
    for key in ("resolved", "persisting", "unassessed", "introduced"):
        for e in diff[key]:
            part = f"@{'/'.join(e['part']['req_ids'])}" if e.get("part") else ""
            rows.append(
                (
                    (",".join(e["old_ids"]) + part) or "—",
                    ",".join(e["new_ids"]) or "—",
                    e["status_ru"],
                    e["reason_code"],
                )
            )
    return sorted(rows)


def test_editions_are_built_by_engine_and_valid(runs):
    for k in ("v1", "v2", "v3", "v3_unreadable", "v2_cmp", "v3_cmp"):
        assert_valid_report(runs[k])
        assert runs[k]["run"]["mode"] == "rules_only"
    f = {k: [(x["id"], x["req_ids"], x["title"]) for x in runs[k]["findings"]] for k in ("v1", "v2", "v3")}
    assert f["v1"] == [("F-001", ["R-001", "R-002"], "Размытый срок «своевременно» в требовании Ф-1")]
    assert f["v2"] == [("F-001", ["R-002", "R-003"], "Размытый срок «своевременно» в требовании 2")]
    assert f["v3"] == [
        ("F-001", ["R-003"], "Размытый срок «своевременно» в требовании 3"),
        ("F-002", ["R-004"], "Открытый перечень «сумму за месяц и т. д.» в требовании 4"),
    ]
    # одинаковые id означают разное: R-003 в v1 — порог, в v2 и v3 — дебетовая формулировка
    assert runs["v1"]["requirements"][2]["text"].startswith("Порог")
    assert runs["v2"]["requirements"][2]["text"].startswith("Держатель дебетовой")


def test_v1_to_v2_reorder_and_renumber_keeps_defect(runs):
    diff = compare_reports(runs["v1"], runs["v2"])
    validate(diff, "Diff")
    assert matrix(diff) == [("F-001", "F-001", "сохранилось", "same_root_cause")]
    [e] = diff["persisting"]
    assert "источник Ф-1 (R-001) → 3 (R-003); Ф-2 (R-002) → 2 (R-002)" in e["reason"]
    rm = {r["old_ids"][0]: r for r in diff["basis"]["requirement_map"] if r["old_ids"]}
    assert rm["R-001"]["new_ids"] == ["R-003"] and rm["R-001"]["changes"] == ["renumbered"]
    assert rm["R-003"]["new_ids"] == ["R-001"] and rm["R-003"]["changes"] == ["renumbered"]
    assert diff["impacted_req_ids"] == []  # перестановка и перенумерация — не правка


def test_v2_to_v3_one_fixed_one_kept_one_new(runs):
    diff = compare_reports(runs["v2"], runs["v3"])
    validate(diff, "Diff")
    assert matrix(diff) == [
        ("F-001@R-002", "—", "исправлено в тексте", "text_changed_rechecked"),
        ("F-001@R-003", "F-001", "сохранилось", "same_root_cause"),
        ("—", "F-002", "новое замечание", "new_root_cause"),
    ]
    res = diff["resolved"][0]
    assert res["part"] == {
        "of": "F-001",
        "req_ids": ["R-002"],
        "labels": ["2 (R-002)"],
        "whole_req_ids": ["R-002", "R-003"],
    }
    assert res["proof"]["kind"] == "requirement_rechecked" and res["proof"]["check_refs"] == ["R-002/verifiable"]
    assert res["reason"].startswith("Часть прежнего F-001 в 2 (R-002): текст изменён в месте опоры")
    assert res["view"]["behavior_change"].startswith("2: «своевременно получает push, когда» → ")
    assert any(CREDIT_V3 in x["quote"] for x in res["evidence"])
    kept = diff["persisting"][0]
    assert kept["part"]["req_ids"] == ["R-003"] and "источник 3 (R-003) → 3 (R-003)" in kept["reason"]
    new = diff["introduced"][0]
    assert new["origin"] == "new_text" and "новизна условна" not in new["reason"]  # этап rules был завершён


def test_v1_to_v3_direct_uses_original_ids(runs):
    diff = compare_reports(runs["v1"], runs["v3"])
    assert matrix(diff) == [
        ("F-001@R-001", "F-001", "сохранилось", "same_root_cause"),
        ("F-001@R-002", "—", "исправлено в тексте", "text_changed_rechecked"),
        ("—", "F-002", "новое замечание", "new_root_cause"),
    ]
    st = {e["part"]["labels"][0]: e for k in ("resolved", "persisting") for e in diff[k]}
    assert "источник Ф-1 (R-001) → 3 (R-003)" in st["Ф-1 (R-001)"]["reason"]
    assert "Источник исправления Ф-2 (R-002) → 2 (R-002)" in st["Ф-2 (R-002)"]["reason"]


def test_engine_compare_option_gives_same_matrix(runs):
    """--compare внутри движка вызывает этот же модуль и кладёт diff в отчёт."""
    for name, prev in (("v2_cmp", "v1"), ("v3_cmp", "v2")):
        rep = runs[name]
        assert rep["run"]["modules"]["compare_reports"] == "team:bcc_review.decisions.diff:compare_reports"
        validate(rep["diff"], "Diff")
        assert matrix(rep["diff"]) == matrix(compare_reports(runs[prev], rep))


def test_unreadable_rerun_keeps_only_what_is_still_proven(runs):
    """Неполный повтор v3: два байта кредитного пункта не прочитаны (decode_error без указания места)."""
    rep = runs["v3_unreadable"]
    assert rep["run"]["status"] == "partial" and "read" in rep["run"]["incomplete_stages"]
    assert rep["document"]["warnings"][0]["code"] == "decode_error"
    diff = compare_reports(runs["v2"], rep)
    assert matrix(diff) == [
        ("F-001@R-002", "—", "нужно подтверждение", "run_incomplete"),
        ("F-001@R-003", "F-001", "сохранилось", "same_root_cause"),
        ("—", "F-002", "новое замечание", "new_root_cause"),
    ]
    assert "прочитана не полностью" in diff["unassessed"][0]["reason"]


def test_localized_unreadable_block_blocks_only_its_source(runs):
    """Если чтение указало место (Warning.block_ids), исправление вне задетого блока остаётся доказанным."""

    def damaged(block_text: str) -> dict:
        rep = clone(runs["v3"])
        bid = next(b["id"] for b in rep["document"]["blocks"] if block_text in b["text"])
        rep["document"]["warnings"] = [
            {"code": "partial_read", "message": f"блок {bid} прочитан частично", "block_ids": [bid]}
        ]
        rep["run"]["incomplete_stages"] = sorted(set(rep["run"]["incomplete_stages"]) | {"read"})
        return rep

    elsewhere = compare_reports(runs["v2"], damaged("Экран уведомлений"))
    assert ("F-001@R-002", "—", "исправлено в тексте", "text_changed_rechecked") in matrix(elsewhere)
    hit = compare_reports(runs["v2"], damaged(CREDIT_V3))
    row = next(e for e in hit["unassessed"] if e.get("part", {}).get("req_ids") == ["R-002"])
    assert row["reason_code"] == "run_incomplete" and "задет источник замечания" in row["reason"]


def test_failed_foreign_stage_keeps_rule_proof(runs):
    """Неполный повтор с моделью: семантические этапы не завершены, этап rules — да."""
    rep = clone(runs["v3"])
    for st in rep["run"]["stages"]:
        if st["name"] in ("individual", "cross"):
            st.update(status="failed", reason="обращение к модели не удалось")
    rep["run"].update(mode="rules_plus_llm", status="partial")
    assert ("F-001@R-002", "—", "исправлено в тексте", "text_changed_rechecked") in matrix(
        compare_reports(runs["v2"], rep)
    )
    rules_failed = clone(rep)
    for st in rules_failed["run"]["stages"]:
        if st["name"] == "rules":
            st.update(status="failed", reason="правила не выполнены")
    rules_failed["run"]["incomplete_stages"] = sorted(set(rules_failed["run"]["incomplete_stages"]) | {"rules"})
    row = next(e for e in compare_reports(runs["v2"], rules_failed)["unassessed"] if e.get("part"))
    assert row["reason_code"] == "run_incomplete" and "этап rules, который нашёл замечание" in row["reason"]


def test_shuffled_inputs_same_matrix(runs):
    base = compare_reports(runs["v2"], runs["v3"])
    rnd = random.Random(7)
    for _ in range(8):
        p, c = clone(runs["v2"]), clone(runs["v3"])
        for rep in (p, c):
            for key in ("findings", "requirements", "checks"):
                rnd.shuffle(rep[key])
            for f in rep["findings"]:
                rnd.shuffle(f["req_ids"])
                rnd.shuffle(f["evidence"])
        out = compare_reports(p, c)
        assert matrix(out) == matrix(base)
        assert [e["reason"] for k in ("resolved", "persisting") for e in out[k]] == [
            e["reason"] for k in ("resolved", "persisting") for e in base[k]
        ]


def _cli(*args):
    env = {**os.environ, "PYTHONPATH": str(SRC), "PYTHONIOENCODING": "utf-8"}
    return subprocess.run(
        [sys.executable, "-m", *map(str, args)], capture_output=True, encoding="utf-8", env=env, check=False
    )


def test_public_commands(runs, tmp_path):
    inp, reps = runs["_input"], runs["_reports"]
    proc = _cli(
        "bcc_review", inp / "v3.md", tmp_path / "v3.md", "--offline-lint", "--no-cache", "--compare", reps / "v2.json"
    )
    assert proc.returncode == 0, proc.stderr
    rep = json.loads((tmp_path / "v3.json").read_text(encoding="utf-8"))
    assert matrix(rep["diff"]) == matrix(compare_reports(runs["v2"], runs["v3"]))
    proc = _cli(
        "bcc_review.decisions.diff",
        reps / "v2.json",
        reps / "v3.json",
        "-o",
        tmp_path / "d.json",
        "--md",
        tmp_path / "d.md",
    )
    assert proc.returncode == 0, proc.stderr
    assert "исправлено в тексте: 1; сохранилось: 1; нужно подтверждение: 0; новые: 1" in proc.stderr
    md = (tmp_path / "d.md").read_text(encoding="utf-8")
    assert "F-001 [2 (R-002)] → —" in md and "F-001 [3 (R-003)] → F-001" in md


# --- честная неопределённость: два равноправных кандидата ------------------------------------
GENERIC = "Держатель карты своевременно получает push, когда расходы за месяц достигают порога."
DEBIT = "Держатель дебетовой карты своевременно получает push, когда расходы за месяц достигают порога."
CREDIT = "Держатель кредитной карты своевременно получает push, когда расходы за месяц достигают порога."


def _tie_pair():
    """Одна общая формулировка заменена двумя равноправными; у каждой своя находка с тем же дефектом."""
    pp = [(S_FT, "Ф-1", GENERIC, "R-1")]
    pd = document(pp)
    old = finding(
        "F-1",
        pd,
        req_ids=["R-1"],
        kind="unverifiable",
        criterion="verifiable",
        severity="major",
        title="Размытый срок «своевременно»",
        quotes=["своевременно"],
    )
    prev = report(pd, requirements(pd, pp), [old])
    cp = [(S_FT, "1.1", DEBIT, "R-1"), (S_FT, "1.2", CREDIT, "R-2")]
    cd = document(cp)
    news = [
        finding(
            f"F-{k}",
            cd,
            req_ids=[f"R-{k}"],
            kind="unverifiable",
            criterion="verifiable",
            severity="major",
            title="Размытый срок «своевременно»",
            quotes=["своевременно"],
        )
        for k in (1, 2)
    ]
    news[1]["evidence"] = [{**news[1]["evidence"][0], **_ev_in(cd, CREDIT, "своевременно")}]
    news[1]["hints"] = [{"block_id": news[1]["evidence"][0]["block_id"], "quote": "своевременно"}]
    cur = report(cd, requirements(cd, cp), news, checks=issue_checks(news), run_id="run-2")
    return prev, cur


def _ev_in(doc, near, quote):
    b = next(b for b in doc["blocks"] if near in b["text"])
    p = b["text"].find(quote)
    return {"block_id": b["id"], "start": p, "end": p + len(quote), "quote": quote}


def test_two_equal_candidates_stay_uncertain():
    prev, cur = _tie_pair()
    assert_valid_report(prev)
    assert_valid_report(cur)
    diff = compare_reports(prev, cur)
    validate(diff, "Diff")
    assert matrix(diff) == [("F-1", "F-1,F-2", "нужно подтверждение", "ambiguous_match")]
    [e] = diff["unassessed"]
    assert "Два равноправных кандидата" in e["reason"] and "выбрать одного по порядку нельзя" in e["reason"]
    assert [c["new_id"] for c in e["candidates"]] == ["F-1", "F-2"]
    assert e["candidates"][0]["score"] == e["candidates"][1]["score"]
    assert not diff["introduced"] and not diff["persisting"]  # ни одна из двух не объявлена «продолжением»
    assert diff["basis"]["requirement_map"][0]["relation"] == "ambiguous"  # смысл равно близок к обоим пунктам


def test_tie_does_not_depend_on_input_order():
    prev, cur = _tie_pair()
    base = matrix(compare_reports(prev, cur))
    for order in ([1, 0], [0, 1]):
        c = clone(cur)
        c["findings"] = [cur["findings"][k] for k in order]
        c["requirements"] = [cur["requirements"][k] for k in order]
        assert matrix(compare_reports(prev, c)) == base


def test_inputs_are_published_for_the_team():
    """Использованный вход лежит в tests/p09/golden/three_*.md байт в байт."""
    golden = pathlib.Path(__file__).parent / "golden"
    for name, text in EDITIONS.items():
        path = golden / f"three_{name}.md"
        if os.environ.get("P09_UPDATE_GOLDEN") == "1":
            path.write_bytes(text.encode("utf-8"))
        assert path.read_bytes() == text.encode("utf-8")


def three_matrix(runs) -> str:
    """Матрица трёх версий с реальными id: место дефекта → находка в v1/v2/v3 → статусы и основание."""
    d12 = compare_reports(runs["v1"], runs["v2"])
    d23 = compare_reports(runs["v2"], runs["v3"])
    d2u = compare_reports(runs["v2"], runs["v3_unreadable"])
    back = {n: r["old_ids"][0] for r in d12["basis"]["requirement_map"] if r["old_ids"] for n in r["new_ids"]}
    fwd = {r["old_ids"][0]: r["new_ids"] for r in d23["basis"]["requirement_map"] if r["old_ids"]}
    label = {k: {q["id"]: f"{q['source_id']} ({q['id']})" for q in runs[k]["requirements"]} for k in ("v1", "v2", "v3")}
    word = {"R-002": "«своевременно», кредитная", "R-003": "«своевременно», дебетовая"}

    def status(diff, req):
        return next(
            e
            for k in ("resolved", "persisting", "unassessed")
            for e in diff[k]
            if e.get("part", {}).get("req_ids") == [req]
        )

    rows = []
    for req in ("R-003", "R-002"):  # места F-001 в v2
        e23, e2u = status(d23, req), status(d2u, req)
        v3 = (f"{', '.join(e23['new_ids'])} · " if e23["new_ids"] else "— · ") + ", ".join(
            label["v3"][n] for n in fwd[req]
        )
        rows.append(
            [
                word[req],
                f"F-001 · {label['v1'][back[req]]}",
                f"F-001 · {label['v2'][req]}",
                v3,
                d12["persisting"][0]["status_ru"],
                e23["status_ru"],
                e2u["status_ru"],
                e23["reason"],
            ]
        )
    new = d23["introduced"][0]
    rows.append(
        [
            "«и т. д.», экран уведомлений (новый пункт)",
            "—",
            "—",
            f"{new['new_ids'][0]} · {label['v3'][runs['v3']['findings'][1]['req_ids'][0]]}",
            "—",
            new["status_ru"],
            d2u["introduced"][0]["status_ru"],
            new["reason"],
        ]
    )
    head = ["Дефект и место", "v1", "v2", "v3", "v1→v2", "v2→v3", "v2→v3 (неполный повтор)", "Основание v2→v3"]
    lines = ["| " + " | ".join(head) + " |", "|" + " :--- |" * len(head)]
    lines += ["| " + " | ".join(c.replace("|", "\\|") for c in r) + " |" for r in rows]
    return "\n".join(lines) + "\n"


def test_three_matrix_for_the_team(runs):
    golden = pathlib.Path(__file__).parent / "golden" / "three_matrix.md"
    text = three_matrix(runs)
    if os.environ.get("P09_UPDATE_GOLDEN") == "1":
        golden.write_text(text, encoding="utf-8")
    assert golden.read_text(encoding="utf-8") == text
    assert "| F-001 · Ф-2 (R-002) | F-001 · 2 (R-002) | — · 2 (R-002) | сохранилось | исправлено в тексте |" in text
