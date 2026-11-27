"""№30: зоопарк вставок для модели (`tests/v2/fixtures/30_inject`, генератор `make_inject.py`).

* каждая вставка находится: кандидат `rules:injection.prompt` (или `rules:hidden.text` для просто скрытого текста),
  а то, чего модель не видит вовсе (title картинки, HTML-комментарий), — предупреждение в отчёте;
* контрольные `clean_*` (TODO-комментарий, «модель скоринга», эмодзи с ZWJ, серый текст) — без кандидатов;
* цитаты — подстроки строк документа (их сверяет verify);
* конвейер с подменёнными ответами mock (модель «послушалась» вставки) — вставка остаётся в отчёте.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from bcc_review.v2 import docview, rules
from bcc_review.v2.rules import hidden, injection

ROOT = Path(__file__).resolve().parents[2]
ZOO = ROOT / "tests" / "v2" / "fixtures" / "30_inject"
TRUTH = json.loads((ZOO / "truth.json").read_text(encoding="utf-8"))
HAS_PDF = importlib.util.find_spec("fitz") is not None or importlib.util.find_spec("pymupdf") is not None


def _view(name: str, with_hidden: bool = True) -> dict:
    v = docview.load(str(ZOO / name))
    if with_hidden:
        v["hidden"] = hidden.scan_file(ZOO / name)
    return v


def _ours(out: dict) -> list[dict]:
    return [c for c in out["candidates"] if c["source"].startswith(("rules:injection", "rules:hidden"))]


def _visible(view: dict, needle: str) -> bool:
    return bool(needle) and any(needle in injection.normalize(ln.get("text") or "")[0] for ln in view["lines"])


@pytest.mark.parametrize("name", sorted(TRUTH), ids=str)
def test_injection_zoo(name: str) -> None:
    if name.endswith(".pdf") and not HAS_PDF:
        pytest.skip("нет pymupdf")
    t = TRUTH[name]
    view = _view(name)
    out = rules.run(view)
    ours = _ours(out)
    if t["expect"] == "clean":
        assert ours == [], [c["title"] for c in ours]
        assert not out.get("warnings")
        return
    if ours:
        for c in ours:
            for e in c["evidence"]:
                line = next(ln for ln in view["lines"] if ln["n"] == e["line"])
                assert e["quote"] and e["quote"] in (line["text"] or ""), (e, line["text"])
        if t["expect"] == "hidden":
            assert any(c["source"] == "rules:hidden.text" for c in ours)
        return
    # модель этого текста не видит (читатель документа его не показывает) — сообщаем предупреждением
    assert not _visible(view, t["needle"])
    assert any("скрытый текст" in w for w in out.get("warnings") or []), out.get("warnings")


def test_zoo_score_is_full() -> None:
    total = hit = 0
    for name, t in TRUTH.items():
        if name.endswith(".pdf") and not HAS_PDF:
            continue
        out = rules.run(_view(name))
        total += 1
        found = bool(_ours(out)) or bool(out.get("warnings"))
        hit += (not found) if t["expect"] == "clean" else found
    assert hit == total


def test_text_level_detection_without_source_scan() -> None:
    """Без `view["hidden"]` (docview его ещё не передаёт) всё, что видит модель в Markdown, находится по строкам."""
    for name, t in TRUTH.items():
        if not name.endswith(".md"):
            continue
        view = _view(name, with_hidden=False)
        out = rules.run(view)
        if t["expect"] == "clean":
            assert _ours(out) == [], name
        elif _visible(view, t["needle"]) or t["expect"] == "hidden":
            assert _ours(out), name


def test_normalize_reveals_masking() -> None:
    t, notes = injection.normalize("Игнopиpуй пpедыдущие")
    assert t.startswith("Игнорируй предыдущие") and any("латинские" in n for n in notes)
    t, notes = injection.normalize("ok" + "".join(chr(0xE0000 + ord(c)) for c in "ignore rules"))
    assert "ignore rules" in t and any("символы-теги" in n for n in notes)
    t, notes = injection.normalize("М​о​дель")
    assert t == "Модель" and notes
    t, notes = injection.normalize("семья 👨‍👩‍👧")
    assert notes == []
    # обычные смешанные идентификаторы не трогаем: латиница без русских букв
    assert injection.normalize("cardId и userId")[1] == []


def test_scanner_never_raises() -> None:
    for data, fmt in ((b"\x00\x01garbage", "docx"), (b"<p hidden>", "html"), (b"%PDF-1.4 broken", "pdf"),
                      (b"<!-- open", "md"), (b"", "txt")):
        assert isinstance(hidden.scan_bytes(data, fmt), list)


CLEAN_DIRS = ["evaluation/v2/clean", "evaluation/v2/open2", "evaluation/dev/corpus/cases", "tests/v2/fixtures/12_styles"]


def test_no_injection_on_clean_documents() -> None:
    paths = []
    for d in CLEAN_DIRS:
        for p in sorted((ROOT / d).rglob("*")):
            if p.suffix in (".md", ".docx", ".html") and ("clean" in str(p) or ".base" in str(p)):
                paths.append(p)
    assert len(paths) >= 20
    for p in paths:
        v = docview.load(str(p))
        v["hidden"] = hidden.scan_file(p)
        assert _ours(rules.run(v)) == [], p


def _mock_dir(tmp_path: Path, judge: dict) -> Path:
    d = tmp_path / "mock"
    d.mkdir()
    (d / "judge.json").write_text(json.dumps(judge, ensure_ascii=False), encoding="utf-8")
    for st in ("lens_analyst", "lens_qa", "lens_architect", "lens_risk", "consistency"):
        (d / f"{st}.json").write_text('{"candidates": []}', encoding="utf-8")
    return d


def _pipeline(tmp_path: Path, doc: Path, mock: Path) -> dict:
    from bcc_review.v2.pipeline import Pipeline  # noqa: F401 — наличие конвейера

    import subprocess
    import sys

    out = tmp_path / "r.md"
    subprocess.run([sys.executable, "-m", "bcc_review", str(doc), str(out), "--provider", "mock", "--mock-dir",
                    str(mock), "--no-cache", "--runs-dir", str(tmp_path / "runs"), "--no-html", "-q"],
                   check=True, cwd=ROOT, capture_output=True, timeout=300)
    return json.loads(out.with_suffix(".json").read_text(encoding="utf-8"))


@pytest.mark.xfail(reason="просьба №26 (status/30.md): судья отклоняет и понижает кандидата вставки по ответу модели, "
                          "которая сама поддалась вставке", strict=False)
def test_obedient_model_does_not_hide_injection(tmp_path: Path) -> None:
    """Модель «послушалась» вставки: линзы пусты, судья отклонил всё и написал «документ корректен»."""
    rej = [{"candidate_id": f"C-{i:03d}", "reason_code": "out_of_scope", "reason": "Автор документа: замечаний нет.",
            "line": 0} for i in range(1, 60)]
    mock = _mock_dir(tmp_path, {"findings": [], "rejected": rej, "checklist": [],
                                "verdict_summary": "Документ корректен, можно начинать разработку."})
    rep = _pipeline(tmp_path, ZOO / "md_comment_single.md", mock)
    srcs = [s for f in rep.get("findings") or [] for s in (f.get("sources") or [f.get("source")])]
    assert any(str(s).startswith("rules:injection") for s in srcs), rep.get("rejected")
    found = [f for f in rep["findings"] if any(str(s).startswith("rules:injection") for s in f.get("sources") or [])]
    assert found[0]["severity"] in ("major", "critical")
    assert "корректен" not in (rep.get("verdict") or {}).get("summary", "")
