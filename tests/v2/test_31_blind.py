"""№31: слепой набор — ключ в виде эталона, прогон mock, счёт только числами."""
import json
from pathlib import Path

from evaluation.v2 import blind

FIX = Path(__file__).parent / "fixtures" / "31_blind"


def test_key_to_gold_reads_quotes_evidence_and_clean():
    g = blind.key_to_gold({"items": [{"id": "X", "severity": "Critical", "quotes": ["а"]},
                                     {"type": "ambiguity", "evidence": [{"quote": "б", "line_start": 4}]}]},
                          FIX / "OF-01.md")
    assert [i["id"] for i in g["items"]] == ["X", "B02"]
    assert g["items"][0]["severity"] == "critical"
    assert g["items"][1]["anchors"]["groups"] == [{"quote": "б", "lines": "4-4"}]
    assert blind.key_to_gold({"expected": "clean"}, FIX / "CL-02.md")["expected"] == "clean"
    assert blind.key_to_gold([], FIX / "CL-02.md")["expected"] == "clean"


def test_mock_run_and_numbers_only(tmp_path, capsys):
    assert blind.main(["run", "--dir", str(FIX), "--out", str(tmp_path), "--provider", "mock"]) == 0
    assert blind.main(["score", "--dir", str(FIX), "--out", str(tmp_path), "--json"]) == 0
    n = json.loads((tmp_path / "numbers.json").read_text(encoding="utf-8"))
    assert n["documents"] == 2 and n["support"] == 2 and n["failed"] == 0
    assert n["clean"]["n"] == 1 and n["quotes"]["total"] >= n["quotes"]["found"] > 0
    out = capsys.readouterr().out
    key_text = json.loads((FIX / "OF-01.key.json").read_text(encoding="utf-8"))["items"][0]["quotes"][0]
    assert key_text not in out  # ключ не утекает в вывод


def test_no_keys_means_no_score(tmp_path):
    d = tmp_path / "docs"
    d.mkdir()
    (d / "A-1.md").write_text("# Т\n", encoding="utf-8")
    assert blind.main(["score", "--dir", str(d), "--out", str(tmp_path / "o")]) == 1
