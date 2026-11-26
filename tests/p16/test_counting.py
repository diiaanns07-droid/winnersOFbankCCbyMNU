"""Подсчёт: ручной пример 2 TP / 1 FP / 1 FN, дубли, групповая находка, разбор, пустые знаменатели."""
from __future__ import annotations

import json
import subprocess
import sys
from fractions import Fraction
from pathlib import Path

import pytest

from evaluation.harness.schema import ProtocolError

from .helpers import do_score, gold_row, pred_row, run_row

HAND = Path(__file__).resolve().parents[2] / "evaluation" / "harness" / "controls" / "hand_2tp"
REPO = Path(__file__).resolve().parents[2]

A1 = "Возврат покупки уменьшает кэшбэк следующего начисления."
A2 = "Возврат покупки не меняет начисленный кэшбэк."
U1 = "limit — лимит в тиынах"
U2 = "Лимит задаётся целым числом от 10 000 до 3 000 000 ₸ включительно."
P1 = "Приложение читает лимит методом getTransferLimit"


def close(value, frac: Fraction) -> bool:
    return value is not None and abs(value - float(frac)) < 1e-12


def hand_gold():
    return [gold_row("c", "event_conflict", [("a", A1), ("b", A2)], label_id="H1"),
            gold_row("c", "unit_mismatch", [("a", U1), ("b", U2)], label_id="H2"),
            gold_row("c", "missing_element", [("promise", P1)], policy="any", label_id="H3")]


def hand_preds():
    return [pred_row("c", "event_conflict", [A1, A2], "F-1"),
            pred_row("c", "unit_mismatch", [U1, U2], "F-2"),
            pred_row("c", "ambiguity", ["Сутки — с 00:00:00 до 23:59:59 по UTC+5."], "F-3")]


def test_hand_example_2tp_1fp_1fn():
    m = do_score(hand_gold(), hand_preds())
    mi = m["micro"]
    assert (mi["tp"], mi["fp"], mi["fn"], mi["duplicates"]) == (2, 1, 1, 0)
    assert close(mi["precision"], Fraction(2, 3))
    assert close(mi["recall"], Fraction(2, 3))
    assert close(mi["f1"], Fraction(2, 3))
    assert [x["label_id"] for x in m["false_negatives"]] == ["H3"]
    assert [x["defect_id"] for x in m["false_positives"]] == ["F-3"]


def test_duplicate_is_reported_separately():
    """Повтор F-2 не добавляет TP и не входит в FP основной precision; precision_strict его учитывает."""
    preds = hand_preds() + [pred_row("c", "unit_mismatch", [U1, U2], "F-2-repeat")]
    m = do_score(hand_gold(), preds)
    mi = m["micro"]
    assert (mi["tp"], mi["fp"], mi["fn"], mi["duplicates"]) == (2, 1, 1, 1)
    assert close(mi["precision"], Fraction(2, 3))
    assert close(mi["recall"], Fraction(2, 3))
    assert close(mi["precision_strict"], Fraction(2, 4))
    dup = m["duplicates"][0]
    assert dup["duplicate_of"] == "H2" and dup["defect_id"] in ("F-2", "F-2-repeat")


def test_duplicate_keeps_exact_type_over_parent():
    """Из двух находок на один дефект TP получает точный тип, родительский тип уходит в дубли."""
    preds = [pred_row("c", "contradiction", [U1, U2], "parent"), pred_row("c", "unit_mismatch", [U1, U2], "exact")]
    m = do_score([gold_row("c", "unit_mismatch", [("a", U1), ("b", U2)], label_id="H2")], preds)
    assert m["true_positives"][0]["defect_id"] == "exact"
    assert m["duplicates"][0]["defect_id"] == "parent"


def test_group_finding_closes_only_one_target():
    """Одна находка с опорами двух дефектов закрывает только один; второй остаётся FN с пометкой."""
    preds = [pred_row("c", "contradiction", [A1, A2, U1, U2], "GROUP")]
    m = do_score(hand_gold(), preds)
    mi = m["micro"]
    assert (mi["tp"], mi["fp"], mi["fn"]) == (1, 0, 2)
    claimed = [fn for fn in m["false_negatives"] if fn["claimed_by_group"]]
    assert len(claimed) == 1 and claimed[0]["label_id"] in ("H1", "H2")


def test_one_to_one_maximum_matching():
    """Находка X подходит к H1 и H2, находка Y — только к H1. Паросочетание даёт 2 TP, а не 1 TP + дубль."""
    gold = [gold_row("c", "contradiction", [("a", A1)], policy="any", label_id="H1"),
            gold_row("c", "contradiction", [("a", U1)], policy="any", label_id="H2")]
    preds = [pred_row("c", "contradiction", [A1, U1], "X"), pred_row("c", "contradiction", [A1], "Y")]
    m = do_score(gold, preds)
    assert (m["micro"]["tp"], m["micro"]["duplicates"], m["micro"]["fn"]) == (2, 0, 0)
    assert {(t["label_id"], t["defect_id"]) for t in m["true_positives"]} == {("H1", "Y"), ("H2", "X")}


def test_type_match_hierarchy_vs_exact():
    gold = [gold_row("c", "unit_mismatch", [("a", U1), ("b", U2)], label_id="H2")]
    preds = [pred_row("c", "contradiction", [U1, U2], "F")]
    h = do_score(gold, preds, type_match="hierarchy")
    assert h["micro"]["tp"] == 1 and h["true_positives"][0]["match_level"] == "parent"
    e = do_score(gold, preds, type_match="exact")
    assert e["micro"]["tp"] == 0 and e["micro"]["pending_adjudication"] == 1


def test_borderline_and_partial_go_to_adjudication():
    gold = [gold_row("c", "unit_mismatch", [("a", U1), ("b", U2)], label_id="H2")]
    preds = [pred_row("c", "ambiguity", [U1, U2], "SYN"),            # пограничный синоним
             pred_row("c", "unit_mismatch", [U1], "HALF")]           # одна опора из двух
    m = do_score(gold, preds)
    assert m["micro"]["tp"] == 0 and m["micro"]["fp"] == 2 and m["micro"]["pending_adjudication"] == 2
    reasons = {fp["defect_id"]: fp["near"][0]["reason"] for fp in m["false_positives"]}
    assert reasons["SYN"].startswith("borderline_type")
    assert reasons["HALF"].startswith("partial_anchors:1/2")


def test_adjudication_decisions_applied():
    from evaluation.harness.schema import parse_decisions
    gold = [gold_row("c", "unit_mismatch", [("a", U1), ("b", U2)], label_id="H2")]
    preds = [pred_row("c", "ambiguity", [U1, U2], "SYN"), pred_row("c", "ambiguity", ["Сутки по UTC+5"], "NEW")]
    base = do_score(gold, preds)
    keys = {fp["defect_id"]: fp["pred_key"] for fp in base["false_positives"]}
    dec = parse_decisions([{"pred_key": keys["SYN"], "decision": "match", "label_id": "H2"},
                           {"pred_key": keys["NEW"], "decision": "new_real_defect", "reviewer": "qa"}])
    m = do_score(gold, preds, decisions=dec)
    mi = m["micro"]
    assert (mi["tp"], mi["fp"], mi["fn"], mi["new_real_defects"], mi["tp_adjudicated"]) == (1, 0, 0, 1, 1)
    assert mi["precision"] == 1.0


def test_empty_denominators():
    # ноль предсказаний при непустом эталоне: precision не определена, recall = 0
    m = do_score(hand_gold(), [run_row("c")])
    assert m["micro"]["precision"] is None and m["micro"]["recall"] == 0.0 and m["micro"]["f1"] == 0.0
    # чистый документ и ноль предсказаний: все три метрики не определены, ложных тревог нет
    m = do_score([gold_row("clean", None, [], outcome="clean")], [run_row("clean")])
    assert (m["micro"]["precision"], m["micro"]["recall"], m["micro"]["f1"]) == (None, None, None)
    assert m["clean_controls"] == {**m["clean_controls"], "cases": 1, "cases_with_alarms": 0, "false_alarms": 0}
    # чистый документ и две находки: обе ложные тревоги, precision = 0, recall не определён
    m = do_score([gold_row("clean", None, [], outcome="clean")],
                 [run_row("clean"), pred_row("clean", "ambiguity", ["x y z w"], "A"),
                  pred_row("clean", "ambiguity", ["q r s t"], "B")])
    assert m["micro"]["precision"] == 0.0 and m["micro"]["recall"] is None
    assert m["clean_controls"]["false_alarms"] == 2 and m["micro"]["clean_false_alarms"] == 2


def test_control_spot_hit_is_reported():
    para = "Изменённый лимит применяется к каждому переводу после изменения."
    gold = [gold_row("p", None, [], outcome="clean"), gold_row("p", None, [("control", para)], outcome="absent")]
    m = do_score(gold, [run_row("p"), pred_row("p", "ambiguity", [para], "F")])
    assert m["micro"]["control_hits"] == 1 and m["false_positives"][0]["reasons"] == ["clean_false_alarm", "control_hit"]


def test_missing_and_failed_runs_are_not_scored_as_zero():
    gold = [gold_row("a", "unit_mismatch", [("a", U1), ("b", U2)]), gold_row("b", "unit_mismatch", [("a", U1), ("b", U2)]),
            gold_row("c2", "unit_mismatch", [("a", U1), ("b", U2)])]
    preds = [run_row("a"), pred_row("a", "unit_mismatch", [U1, U2]), run_row("b", status="failed")]
    m = do_score(gold, preds)
    assert m["counts"]["independent_cases"] == 1
    assert {x["case_id"]: x["reason"] for x in m["missing_measurements"]} == {
        "b": "прогон завершился со статусом failed", "c2": "нет прогона"}
    assert m["micro"]["recall"] == 1.0


def test_mixed_modes_require_choice():
    gold = [gold_row("c", "unit_mismatch", [("a", U1), ("b", U2)])]
    preds = [run_row("c", mode="rules_only"), run_row("c", mode="rules_plus_llm")]
    with pytest.raises(ProtocolError):
        do_score(gold, preds)
    assert do_score(gold, preds, mode="rules_only")["counts"]["independent_cases"] == 1


def test_gold_validation_errors():
    with pytest.raises(ProtocolError):
        do_score([gold_row("c", "not_a_type", [("a", U1)])], [])
    with pytest.raises(ProtocolError):  # clean и present в одном кейсе
        do_score([gold_row("c", None, [], outcome="clean"), gold_row("c", "unit_mismatch", [("a", U1)])], [])
    with pytest.raises(ProtocolError):  # кейс описан только контрольным местом
        do_score([gold_row("c", None, [("control", U1)], outcome="absent")], [])


def test_cli_public_command(tmp_path):
    out = tmp_path / "metrics.json"
    r = subprocess.run([sys.executable, "-m", "evaluation.harness", "--gold", str(HAND / "labels.jsonl"),
                        "--pred", str(HAND / "predictions_with_duplicate.jsonl"), "--out", str(out)],
                       cwd=REPO, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    m = json.loads(out.read_text(encoding="utf-8"))
    assert (m["micro"]["tp"], m["micro"]["fp"], m["micro"]["fn"], m["micro"]["duplicates"]) == (2, 1, 1, 1)
    assert "precision=0.6667 = 2/3" in r.stdout and "recall=0.6667 = 2/3" in r.stdout
    assert m["inputs"]["gold"]["sha256"] and m["runs"]["physical_calls"]["total"] == 4


def test_cli_reports_format_errors(tmp_path):
    bad = tmp_path / "bad.jsonl"
    bad.write_text('{"case_id": "x"}\n', encoding="utf-8")
    r = subprocess.run([sys.executable, "-m", "evaluation.harness", "--gold", str(bad), "--pred", str(bad),
                        "--out", str(tmp_path / "m.json")], cwd=REPO, capture_output=True, text=True)
    assert r.returncode == 2 and "bad.jsonl:1" in r.stderr


def test_review_sample_is_reproducible():
    from evaluation.harness.score import adjudication_sheet
    preds = [pred_row("c", "ambiguity", [f"уникальная фраза номер {i} для проверки"], f"F{i}") for i in range(12)]
    m = do_score(hand_gold(), preds)
    a = adjudication_sheet(m, seed="2026-11-26", sample=5)
    b = adjudication_sheet(m, seed="2026-11-26", sample=5)
    c = adjudication_sheet(m, seed="other", sample=5)
    assert [r["pred_key"] for r in a] == [r["pred_key"] for r in b] and len(a) == 5
    assert [r["pred_key"] for r in a] != [r["pred_key"] for r in c]
    assert all(r["decision"] is None for r in a)
