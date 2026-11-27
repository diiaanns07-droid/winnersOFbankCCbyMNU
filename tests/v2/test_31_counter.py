"""№31: счётчик — «вытесненная» строгая пара получает второй шанс (С15, просьба №26), строго и детерминированно."""
import json
from pathlib import Path

import pytest

from evaluation.v2 import score as sc

MEAS = Path(__file__).resolve().parents[2] / "evaluation" / "v2" / "measurements"


def _score(name: str, displaced: bool) -> dict:
    gold = sc.load_gold(sc.DEFAULT_GOLD)
    d = MEAS / name
    rep = sc.as_report(json.loads((d / "report.json").read_text(encoding="utf-8")), gold)
    return sc.score_report(rep, gold, arbiter="off", displaced=displaced)


def _assigned(res: dict) -> dict[str, str]:
    return {a["finding"]: a["gold"] for a in res["assignment"]}


@pytest.mark.skipif(not (MEAS / "w4_07_zamorozka_c6aa9b5_haiku").exists(), reason="нет сохранённого замера")
def test_displaced_pair_gets_its_own_item():
    # D-14 «Ключ повтора события процессинга не назван» — об идемпотентности (С14); лучший пункт по оценке (С7)
    # уже занят более сильным замечанием, в заголовке нет слов С14 — раньше уходил в «дубль С7»
    before, after = _score("w4_07_zamorozka_c6aa9b5_haiku", False), _score("w4_07_zamorozka_c6aa9b5_haiku", True)
    assert "С14" not in before["recall"]["major"]["found"]
    assert _assigned(after).get("D-14") == "С14"
    assert "D-14" not in {x["finding"] for x in after["duplicates"]}
    assert set(before["recall"]["critical"]["found"]) == set(after["recall"]["critical"]["found"])


@pytest.mark.skipif(not (MEAS / "zamer_15_20_bc3562c_haiku").exists(), reason="нет сохранённого замера")
def test_displaced_needs_same_kind():
    # «Цель расходится с задержкой» (противоречие) не становится М1 «терминология» по слову «бюджет»;
    # «диапазон записан дважды» (повтор) не становится М4б «границы не названы»
    before, after = _score("zamer_15_20_bc3562c_haiku", False), _score("zamer_15_20_bc3562c_haiku", True)
    assert _assigned(after) == _assigned(before)
    assert after["counts"]["duplicates"] == before["counts"]["duplicates"]


@pytest.mark.skipif(not (MEAS / "w4_07_zamorozka_c6aa9b5_haiku").exists(), reason="нет сохранённого замера")
def test_counter_deterministic():
    a, b = _score("w4_07_zamorozka_c6aa9b5_haiku", True), _score("w4_07_zamorozka_c6aa9b5_haiku", True)
    assert a["assignment"] == b["assignment"] and a["duplicates"] == b["duplicates"]


@pytest.mark.skipif(not (MEAS / "zamer_13_00_9bd5954_haiku").exists(), reason="нет сохранённого замера")
def test_counterdiff_three_counters():
    from evaluation.v2 import counterdiff as cd

    (row,) = cd.compute([MEAS / "zamer_13_00_9bd5954_haiku"])
    assert row["before"]["K"] == row["c14"]["K"] == row["now"]["K"] == 5
    assert row["before"]["C"] <= row["c14"]["C"] <= row["now"]["C"]
    assert "С14" in row["now"]["C_found"] and "С14" not in row["before"]["C_found"]
