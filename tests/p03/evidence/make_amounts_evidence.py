"""Пример №03 «сумма в тексте и две такие же в таблице»: входы, копии, карта диапазонов.

Запуск из корня репозитория (после слияния с bcc/integration -- ещё и путь через движок):
    python tests/p03/evidence/make_amounts_evidence.py

Пишет в tests/p03/evidence/amounts/:
* amounts.docx, amounts_user.docx -- входы (p03_fixtures.amounts_doc);
* direct.annotated.docx + direct.json -- read_docx → Report (F-A, F-B, F-C без опоры,
  F-D с неверной опорой) → write_docx; карта диапазонов и счётчик пропусков;
* engine.annotated.docx + engine.json -- run_review(provider=mock, записанные ответы,
  резерв для review_individual/review_set) → write_docx; только если движок есть;
* engine_libreoffice.png -- рендер LibreOffice с примечаниями на полях (если есть soffice).
Карта диапазонов считается независимо от экспортёра (p03_ooxml.range_map).
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "amounts"
sys.path[:0] = [str(HERE.parents[2] / "src"), str(HERE.parent)]

import p03_ooxml as ox  # noqa: E402
from p03_fixtures import amounts_doc, amounts_mock_script  # noqa: E402
from test_p03_amounts import build  # noqa: E402

from bcc_review.exports.word import annotate_docx  # noqa: E402
from bcc_review.readers.docx import read_docx  # noqa: E402


def range_map(src: Path, out: Path) -> list[dict]:
    new = sorted(set(ox.comments(out)) - set(ox.comments(src)))
    rows = []
    for cid, r in ox.range_map(out, new + sorted(ox.comments(src)), read_docx(out)).items():
        rows.append({"comment_id": cid, "author": r["author"], "head": r["head"], "block_id": r["block_id"],
                     "start": r["start"], "end": r["end"], "node": r["start_node"], "covered": r["covered"],
                     "existing": cid not in new})
    return sorted(rows, key=lambda x: (x["node"], x["start"], x["comment_id"]))


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    amounts_doc(OUT / "amounts.docx")
    src = amounts_doc(OUT / "amounts_user.docx", user_comment=True)

    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        _, _, report, _, _ = build(t)  # тот же Report, что в test_p03_amounts (без комментария пользователя)
        res = annotate_docx(report, t / "amounts.docx", OUT / "direct.annotated.docx")
        direct = {"input": "amounts.docx", "status": res.status, "counts": res.counts,
                  "skipped": [s.to_dict() for s in res.skipped], "warnings": res.warnings(),
                  "ranges": range_map(t / "amounts.docx", OUT / "direct.annotated.docx")}
    (OUT / "direct.json").write_text(json.dumps(direct, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print("прямой путь:", res.summary_ru())

    try:
        from bcc_review import engine
        from bcc_review.contracts import RunOptions
    except ImportError:
        print("движка нет в этой ветке: engine.* не построены")
        return
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        (t / "mock.json").write_text(json.dumps(amounts_mock_script(read_docx(src)), ensure_ascii=False), encoding="utf-8")
        for var in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
            os.environ.pop(var, None)
        os.environ["BCC_FORCE_FALLBACK"] = "review_individual,review_set"
        engine.load_dotenv = lambda *a, **k: None
        opts = RunOptions.coerce({"provider": "mock", "mock_script": str(t / "mock.json"), "exports": ["docx"],
                                  "cache_dir": str(t / "cache"), "use_cache": False, "artifacts_dir": str(t / "art")})
        engine.run_review(src, t / "out" / "report.md", options=opts)
        rep = json.loads((t / "out" / "report.json").read_text(encoding="utf-8"))
        shutil.copyfile(t / "out" / "report.annotated.docx", OUT / "engine.annotated.docx")
    eng = {"input": "amounts_user.docx", "run_status": rep["run"]["status"], "provider": rep["run"]["provider"],
           "modules": {k: v for k, v in rep["run"]["modules"].items()
                       if k in ("read_docx", "build_inventory", "review_set", "resolve_hint", "resolve_candidate",
                                "provider")},
           "evidence_audit": {k: v for k, v in rep["run"]["evidence_audit"].items() if k != "note"},
           "findings": [{"id": f["id"], "title": f["title"], "evidence": f["evidence"]} for f in rep["findings"]],
           "rejected": [{"title": x["candidate"].get("title"), "reason": x["reason"][:120]} for x in rep.get("rejected", [])],
           "docx_warnings": [w for w in rep["warnings"] if str(w.get("code", "")).startswith("docx_export")],
           "ranges": range_map(src, OUT / "engine.annotated.docx")}
    (OUT / "engine.json").write_text(json.dumps(eng, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print("движок: замечаний", len(eng["findings"]), "| отсечено", len(eng["rejected"]), "| аудит", eng["evidence_audit"])
    soffice = shutil.which("soffice")
    if soffice and shutil.which("pdftoppm"):
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run([soffice, f"-env:UserInstallation=file://{tmp}/lo", "--headless", "--convert-to",
                            'pdf:writer_pdf_Export:{"ExportNotesInMargin":{"type":"boolean","value":"true"}}',
                            "--outdir", tmp, str(OUT / "engine.annotated.docx")], check=True, capture_output=True,
                           timeout=240)
            subprocess.run(["pdftoppm", "-r", "90", "-png", "-f", "1", "-l", "1", "-singlefile",
                            str(Path(tmp) / "engine.annotated.pdf"), str(OUT / "engine_libreoffice")],
                           check=True, capture_output=True)


if __name__ == "__main__":
    main()
