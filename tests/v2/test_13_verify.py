"""№13: verify — перепроверка report.json по исходнику без модели."""

from __future__ import annotations

import copy
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from bcc_review.v2 import verify  # noqa: E402

SAMPLE = ROOT / "tests" / "v2" / "fixtures" / "13_report_sample.json"
SOURCE = ROOT / "release" / "input" / "requirements.md"


@pytest.fixture()
def sample() -> dict:
    return json.loads(SAMPLE.read_text(encoding="utf-8"))


def run_cli(tmp_path, report, source=SOURCE, capsys=None):
    p = tmp_path / "report.json"
    p.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
    return verify.main([str(p), str(source)])


def test_sample_ok(tmp_path, sample, capsys):
    assert run_cli(tmp_path, sample) == 0
    out = capsys.readouterr().out
    assert "verify: OK" in out and "67 из 67" in out


def test_wrong_line_is_reported_with_hint(tmp_path, sample, capsys):
    bad = copy.deepcopy(sample)
    bad["findings"][0]["evidence"][0]["line_start"] = bad["findings"][0]["evidence"][0]["line_end"] = 41
    assert run_cli(tmp_path, bad) == 4
    err = capsys.readouterr().err
    assert "D-01 цитата №1" in err and "найдена в строке 39" in err


def test_invented_quote_fails(sample):
    bad = copy.deepcopy(sample)
    bad["findings"][3]["evidence"][0]["quote"] = "Такой фразы в документе нет"
    res = verify.verify_report(bad, SOURCE)
    assert not res["ok"] and res["errors"][0]["code"] == "quote"
    assert "в документе не найдена" in res["errors"][0]["message"]


def test_fuzzy_quote_near_line_passes(sample):
    r = copy.deepcopy(sample)
    ev = r["findings"][0]["evidence"][0]
    ev["quote"] = ev["quote"].replace("приходится", "приходиться")
    ev["verified"] = "fuzzy"
    assert verify.verify_report(r, SOURCE)["ok"]
    ev["verified"] = "exact"
    assert not verify.verify_report(r, SOURCE)["ok"]


def test_other_source_fails_sha(tmp_path, sample):
    other = tmp_path / "requirements.md"
    other.write_text(SOURCE.read_text(encoding="utf-8").replace("Ф-3.", "Ф-3 "), encoding="utf-8")
    res = verify.verify_report(sample, other)
    assert any(e["code"] == "sha256" for e in res["errors"])


def test_counters_must_match(sample):
    bad = copy.deepcopy(sample)
    bad["summary"]["findings"]["critical"] = 4
    res = verify.verify_report(bad, SOURCE)
    assert [e["code"] for e in res["errors"]] == ["summary"]


def test_verdict_must_follow_rule(sample):
    bad = copy.deepcopy(sample)
    bad["verdict"]["development"] = "yes"
    res = verify.verify_report(bad, SOURCE)
    assert any(e["code"] == "verdict" for e in res["errors"])


def test_commit_checked(sample):
    bad = copy.deepcopy(sample)
    bad["run"]["commit"] = "не коммит"
    res = verify.verify_report(bad, SOURCE)
    assert any(e["code"] == "commit" for e in res["errors"])
    # архив без .git (№16): коммита нет — предупреждение, отчёт проходит
    for value in ("", "unknown"):
        zip_run = copy.deepcopy(sample)
        zip_run["run"]["commit"] = value
        res = verify.verify_report(zip_run, SOURCE)
        assert res["ok"] and any("коммит агента не записан" in w for w in res["warnings"]), res["errors"][:2]
    tagged = copy.deepcopy(sample)
    tagged["run"]["commit"] = "v2.0.0"
    assert verify.verify_report(tagged, SOURCE)["ok"]


def test_dangling_references(sample):
    bad = copy.deepcopy(sample)
    bad["questions"][0]["finding_ids"] = ["D-99"]
    bad["findings"][1]["requirement_ids"].append("R-77")
    codes = [e["code"] for e in verify.verify_report(bad, SOURCE)["errors"]]
    assert codes.count("refs") == 2


def test_unreadable_input_is_exit_4(tmp_path, capsys):
    p = tmp_path / "broken.json"
    p.write_text("{", encoding="utf-8")
    assert verify.main([str(p), str(SOURCE)]) == 4


def test_normalize_matches_contract():
    assert verify.normalize("«Порог» — **5 000** ₸") == verify.normalize('"порог" - 5 000 ₸')
    assert verify.normalize("* пункт списка") == "пункт списка"


def test_garbage_report_is_exit_4(tmp_path, capsys):
    p = tmp_path / "r.json"
    p.write_text(json.dumps({"schema": "bcc-review/2", "findings": [1, 2], "document": [], "run": "x"}),
                 encoding="utf-8")
    assert verify.main([str(p), str(SOURCE)]) == 4


def test_handles_detects_v2(tmp_path):
    assert verify.handles(SAMPLE)
    p = tmp_path / "v1.json"
    p.write_text('{"schema_version": "1.0"}', encoding="utf-8")
    assert not verify.handles(p)


def test_pdf_pages_checked_with_docview(tmp_path):
    """Вход PDF: цитата сверяется по строке DocView, страница — по номеру страницы этой строки."""
    pytest.importorskip("fitz")
    docview = pytest.importorskip("bcc_review.v2.docview")
    from bcc_review.v2.render import jsonout, markdown

    pdf = ROOT / "release" / "input" / "requirements.pdf"
    view = docview.load(str(pdf))
    picked = [ln for ln in view["lines"] if ln.get("page") and len(ln.get("text", "").strip()) > 30][5:8]
    assert picked
    findings = [{"id": f"D-{i:02d}", "title": "Проверка страницы", "kind": "ambiguity", "criterion": "unambiguous",
                 "severity": "minor", "requirement_ids": [], "blocks": "none", "problem": "п", "recommendation": "р",
                 "evidence": [{"quote": ln["text"].strip()[:60], "line_start": ln["n"], "line_end": ln["n"],
                               "page": ln["page"], "section": ln.get("section", ""), "verified": "exact"}]}
                for i, ln in enumerate(picked, 1)]
    import hashlib
    report = {"schema": "bcc-review/2",
              "run": {"agent": "BCC Review", "version": "2", "commit": "abcdef1", "started_at": "2026-11-27T03:00:00Z",
                      "provider": "mock", "status": "complete", "stages": {}},
              "document": {"title": "т", "file": pdf.name, "format": "pdf", "lines": len(view["lines"]),
                           "pages": view.get("pages"), "sha256": hashlib.sha256(pdf.read_bytes()).hexdigest()},
              "requirements": [], "findings": findings, "verdict": {}}
    jsonout.finalize(report)
    assert verify.verify_report(report, pdf)["ok"]
    assert f"с. {picked[0]['page']}, строка" in markdown.render(report)
    report["findings"][0]["evidence"][0]["page"] = picked[0]["page"] + 1
    res = verify.verify_report(report, pdf)
    assert not res["ok"] and "страница" in res["errors"][0]["message"]


def test_markdown_numbers_checked_next_to_json(tmp_path, sample):
    """verify сверяет числа Markdown-отчёта, лежащего рядом с report.json, с самим JSON."""
    from bcc_review.v2.render import markdown
    rj = tmp_path / "r.json"
    rj.write_text(json.dumps(sample, ensure_ascii=False), encoding="utf-8")
    md = markdown.render(sample)
    (tmp_path / "r.md").write_text(md, encoding="utf-8")
    res = verify.verify_report(rj, SOURCE)
    assert res["ok"] and res["markdown_checked"], res["errors"][:3]
    # ручная правка отчёта: число критичных на первом экране не то, одна карточка удалена
    bad = md.replace("🔴 **5** критичных", "🔴 **4** критичных").replace('<a id="d-07"></a>', "")
    (tmp_path / "r.md").write_text(bad, encoding="utf-8")
    res = verify.verify_report(rj, SOURCE)
    msgs = [e["message"] for e in res["errors"] if e["code"] == "markdown"]
    assert not res["ok"] and any("«Кратко»" in m for m in msgs) and any("D-07" in m for m in msgs), msgs


def test_markdown_verdict_blockers_and_counts_checked(sample):
    """Вердикт в «Кратко» и «Итоге», число блокеров, требования в сводке и кандидаты «Как получено» = приложение Д —
    те же, что в JSON; ручная правка любого из них — ошибка."""
    from bcc_review.v2.render import markdown
    md = markdown.render(sample)
    errors, _ = verify.check_markdown(sample, md)
    assert not errors, errors
    brief_end = md.find('id="s1"')
    tampered = {
        "Кратко": md[:brief_end].replace("| **⛔ нельзя начинать** | **⛔ нельзя начинать** |",
                                         "| **✅ можно начинать** | **⛔ нельзя начинать** |", 1) + md[brief_end:],
        "Итог": md.replace("| разработку | **⛔ нельзя начинать** |", "| разработку | **⚠️ можно с условиями** |"),
        "блокеров": md.replace("**Блокеры (5)**", "**Блокеры (3)**"),
        "Требований выделено": re.sub(r"\| Требований выделено \| (\d+) \|",
                                      lambda m: f"| Требований выделено | {int(m.group(1)) + 1} |", md),
        "приложении Д": re.sub(r"найдено (\d+) возможн", lambda m: f"найдено {int(m.group(1)) + 3} возможн", md),
        "Проверка каждого требования": re.sub(r"✅ Без замечаний \((\d+)\)",
                                              lambda m: f"✅ Без замечаний ({int(m.group(1)) + 1})", md),
    }
    for word, text in tampered.items():
        assert text != md, word
        errors, _ = verify.check_markdown(sample, text)
        assert any(word in e for e in errors), (word, errors)
