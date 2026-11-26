"""Стык со штатными модулями: reader №01, CLI ``python -m bcc_review verify`` и движок с mock-транспортом.

Пример ``fixtures/two_sections.md``: фраза «сумма не превышает 10 000 ₸» дважды в блоке раздела
«Ограничения» (строки 5 и 6) и ещё раз в разделе «Уведомления» (строка 10); перед вторым вхождением
стоит символ вне BMP «𝟙». Команды запускаются отдельными процессами, как у рецензента;
``offline_cli.py`` пишет, какие реализации загрузил реестр модулей, и запрещает сеть.
"""

from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import report_builder
from p07_helpers import FIXTURES

from bcc_review import contracts as C
from bcc_review.analysis.evidence import check_evidence, locate, resolve_hint

reader_01 = pytest.importorskip("bcc_review.readers.text", reason="reader №01 ещё не влит в эту ветку")
pytest.importorskip("bcc_review.cli")

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
SOURCE = FIXTURES / "two_sections.md"
SCRIPT = FIXTURES / "two_sections.mock.json"
PHRASE = "сумма не превышает 10 000 ₸"
CONTEXT = "Для 𝟙-й карты клиента сумма не превышает 10 000 ₸ в сутки."


def read(path: str | Path) -> dict:
    """Тот же путь чтения, что у движка и CLI: reader №01 + нормализация стыка."""
    return C.normalize_document(reader_01.read_text(path))


def run(*args: str | Path, cwd: Path) -> subprocess.CompletedProcess:
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(ROOT / "src"), os.environ.get("PYTHONPATH", "")])}
    env.pop("BCC_REVIEW_READER", None)
    env.pop("BCC_FORCE_FALLBACK", None)
    return subprocess.run([sys.executable, *map(str, args)], cwd=cwd, env=env, capture_output=True,
                          text=True, encoding="utf-8", timeout=180)


def offline(*args: str | Path, cwd: Path) -> subprocess.CompletedProcess:
    return run(HERE / "offline_cli.py", *args, cwd=cwd)


@pytest.fixture(scope="module")
def doc() -> dict:
    return read(SOURCE)


@pytest.fixture(scope="module")
def good_report() -> dict:
    b = report_builder.Builder(SOURCE, reader=read)
    req = b.requirement("R-001.2", None, "𝟙", CONTEXT)
    cand = {"scope": "requirement", "kind": "ambiguity", "criterion": "unambiguous", "severity": "major",
            "title": "Лимит: на одну операцию или за сутки", "impact": "Разные реализации лимита",
            "req_ids": ["R-001.2"], "hints": [{"block_id": "b0003", "quote": PHRASE, "context": CONTEXT}]}
    report = b.report([req], [b.finding("D-1", cand, [req])], [])
    C.validate(report)
    assert C.evidence_errors(report) == []
    return report


def write(path: Path, report: dict) -> Path:
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


# --- reader №01 и resolve_hint ----------------------------------------------------------


def test_real_reader_shape(doc: dict) -> None:
    assert Path(reader_01.__file__).resolve() == (ROOT / "src/bcc_review/readers/text.py").resolve()
    blocks = {b["id"]: b for b in doc["blocks"]}
    assert blocks["b0003"]["section"][-1] == "Ограничения"
    assert blocks["b0005"]["section"][-1] == "Уведомления"
    assert blocks["b0003"]["text"].count(PHRASE) == 2 and blocks["b0005"]["text"].count(PHRASE) == 1
    second = blocks["b0003"]["text"].rindex(PHRASE)
    assert "𝟙" in blocks["b0003"]["text"][:second]


def test_resolve_hint_ambiguous_then_context(doc: dict) -> None:
    amb = resolve_hint(doc, {"block_id": "b0003", "quote": PHRASE})
    assert amb["status"] == "ambiguous" and amb["reason"] == "multiple_occurrences"
    assert [(o["block_id"], o["start"], o["end"]) for o in amb["occurrences"]] == [("b0003", 19, 46), ("b0003", 70, 97)]
    everywhere = resolve_hint(doc, {"block_id": None, "quote": PHRASE})
    assert everywhere["status"] == "ambiguous" and len(everywhere["occurrences"]) == 3

    one = resolve_hint(doc, {"block_id": "b0003", "quote": PHRASE, "context": CONTEXT})
    assert one["status"] == "matched"
    ev = one["evidence"]
    text = next(b["text"] for b in doc["blocks"] if b["id"] == ev["block_id"])
    assert text[ev["start"]:ev["end"]] == ev["quote"] == PHRASE
    assert (ev["block_id"], ev["start"], ev["end"]) == ("b0003", 70, 97)
    assert len(text[:ev["start"]].encode("utf-16-le")) // 2 == 71  # 𝟙 — одна кодовая точка, в UTF-16 две позиции
    where = locate(doc, ev)
    raw_line = SOURCE.read_text(encoding="utf-8").split("\n")[where["line"] - 1]
    assert (where["line"], where["line_end"]) == (6, 6)
    assert raw_line[where["col"]:where["col_end"]] == PHRASE  # строка и столбец по reader-координатам
    other = resolve_hint(doc, {"block_id": "b0005", "quote": PHRASE})
    assert other["status"] == "matched" and locate(doc, other["evidence"])["line"] == 10


# --- штатная команда verify ---------------------------------------------------------------


def test_cli_accepts_correct_pair(tmp_path: Path, good_report: dict) -> None:
    report = write(tmp_path / "report.json", good_report)
    res = offline("verify", report, SOURCE, cwd=tmp_path)
    assert res.returncode == C.EXIT_OK, res.stderr
    assert res.stdout.startswith("verify: OK")
    assert f"загружено: bcc_review.verification:verify_report ({ROOT / 'src/bcc_review/verification.py'})" in res.stderr
    assert f"загружено: bcc_review.readers.text:read_text ({ROOT / 'src/bcc_review/readers/text.py'})" in res.stderr
    assert "сетевых соединений: 0; модули провайдеров: нет" in res.stderr
    plain = run("-m", "bcc_review", "verify", report, SOURCE, "--json", cwd=tmp_path)
    data = json.loads(plain.stdout)
    assert plain.returncode == 0 and data["ok"]
    assert data["implementation"]["reader"].endswith("bcc_review.readers.text:read_text")
    assert data["implementation"]["verify"].startswith("bcc_review.verification:verify_report")
    # повтор фразы в блоке выделен опорой требования R-001.2: место подтверждено, а не «неоднозначно»
    assert {k: data["counts"][k] for k in ("checked", "confirmed", "ambiguous", "rejected")} == \
        {"checked": 2, "confirmed": 2, "ambiguous": 0, "rejected": 0}
    assert data["counts"]["repeats"] == {"objects": 1, "places": 1, "places_distinguished": 1,
                                         "places_undistinguished": 0}
    assert data["repeats"][0]["verdicts"][0]["detail"].endswith("внутри опоры R-001.2, другие вхождения вне её")


@pytest.mark.parametrize(
    ("label", "quote", "code"),
    [
        ("убрано отрицание", "сумма превышает 10 000 ₸", "evidence_quote_mismatch"),
        ("изменено число", "сумма не превышает 10 001 ₸", "evidence_quote_mismatch"),
    ],
)
def test_cli_rejects_distorted_quote(tmp_path: Path, good_report: dict, label: str, quote: str, code: str) -> None:
    report = copy.deepcopy(good_report)
    report["findings"][0]["evidence"][0]["quote"] = quote  # остальные поля, включая координаты, сохранены
    res = offline("verify", write(tmp_path / "report.json", report), SOURCE, cwd=tmp_path)
    assert res.returncode == C.EXIT_VERIFY_FAILED, label
    assert f"{code} findings[0].evidence[0]" in res.stderr
    assert f"по координатам «{PHRASE}», в отчёте «{quote}»" in res.stderr
    assert "сетевых соединений: 0" in res.stderr


def test_cli_rejects_wrong_occurrence(tmp_path: Path, good_report: dict) -> None:
    """Литерал и координаты верны, но это вхождение чужого требования (строка 5), а не R-001.2 (строка 6)."""
    report = copy.deepcopy(good_report)
    ev = report["findings"][0]["evidence"][0]
    ev.update(start=19, end=46, loc={"line": 5, "line_end": 5})
    res = offline("verify", write(tmp_path / "report.json", report), SOURCE, cwd=tmp_path)
    assert res.returncode == C.EXIT_VERIFY_FAILED
    assert "evidence_wrong_occurrence findings[0].evidence[0]" in res.stderr
    assert "в отчёте [19,46) b0003, строка 5" in res.stderr
    assert "у R-001.2 та же цитата стоит в [70,97) b0003, строка 6" in res.stderr


def test_cli_rejects_foreign_edition(tmp_path: Path, good_report: dict) -> None:
    edited = tmp_path / "two_sections.md"
    raw = SOURCE.read_bytes()
    edited.write_bytes(raw.replace("Для первой покупки".encode(), "Для второй покупки".encode()))
    assert edited.read_bytes() != raw
    # фраза осталась на том же месте: по координатам расхождение не видно, его ловит только SHA-256
    fresh = read(edited)
    assert check_evidence(fresh, good_report["findings"][0]["evidence"][0])["status"] in {"confirmed", "ambiguous"}
    res = offline("verify", write(tmp_path / "report.json", good_report), edited, cwd=tmp_path)
    assert res.returncode == C.EXIT_VERIFY_FAILED
    assert "source_sha_mismatch run.source_sha256" in res.stderr and "document_id_mismatch document.id" in res.stderr
    assert "сетевых соединений: 0" in res.stderr


# --- движок с mock-транспортом и обе точки входа verify --------------------------------------


def test_engine_report_with_mock_transport_verifies(tmp_path: Path) -> None:
    out = tmp_path / "report.md"
    res = offline(SOURCE, out, "--provider", "mock", "--mock-script", SCRIPT, "--no-cache", cwd=tmp_path)
    assert res.returncode == C.EXIT_OK, res.stderr
    assert "сетевых соединений: 0; модули провайдеров: нет" in res.stderr
    report = json.loads(out.with_suffix(".json").read_text(encoding="utf-8"))
    assert report["run"]["provider"] == "mock"
    assert report["run"]["modules"]["read_text"] == "team:bcc_review.readers.text:read_text"
    assert report["run"]["modules"]["resolve_candidate"] == "team:bcc_review.analysis.evidence:resolve_candidate"
    # безопасность: замечание про R-001.2 не подтверждается опорой на чужое вхождение
    spans = {r["id"]: r["evidence"] for r in report["requirements"]}
    r12 = next(rid for rid, evs in spans.items() if any(e["quote"] == CONTEXT for e in evs))
    for f in report["findings"]:
        if r12 in f["req_ids"] and f["scope"] == "requirement":
            for ev in f["evidence"]:
                assert any(e["block_id"] == ev["block_id"] and e["start"] <= ev["start"] and ev["end"] <= e["end"]
                           for e in spans[r12])
    ver = offline("verify", out.with_suffix(".json"), SOURCE, cwd=tmp_path)
    assert ver.returncode == C.EXIT_OK, ver.stderr


def test_both_verify_entry_points_agree_on_engine_report(tmp_path: Path) -> None:
    source = FIXTURES / "bcc_requirements.md"
    out = tmp_path / "report.md"
    assert run("-m", "bcc_review", source, out, "--offline-lint", "--no-cache", "-q", cwd=tmp_path).returncode == 0
    results = []
    for entry in (("-m", "bcc_review", "verify"), ("-m", "bcc_review.verification", "verify")):
        res = run(*entry, out.with_suffix(".json"), source, "--json", cwd=tmp_path)
        data = json.loads(res.stdout)
        assert res.returncode == 0 and data["ok"], data["errors"][:3]
        results.append({k: data["counts"][k] for k in ("checked", "confirmed", "ambiguous", "rejected")})
    assert results[0] == results[1] and results[0]["checked"] > 100
