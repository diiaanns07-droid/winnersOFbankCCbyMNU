"""Пример №03 «объединённая шапка»: единица «за сутки» на два столбца, исключение в одной ячейке.

Запуск из корня репозитория (нужен движок bcc/integration):
    python tests/p03/evidence/make_merged_header_evidence.py

Оба документа идут через штатный вход ``python -m bcc_review`` (провайдер mock с
записанными ответами, экспорт DOCX; редакция ещё и с ``--compare`` к отчёту чистого
документа). Пишет в tests/p03/evidence/merged_header/:
* limits.docx, limits_month.docx -- чистый документ и редакция (у Л-2 «300 000 за месяц»);
* limits.mock.json, limits_month.mock.json -- записанные ответы модели для каждой версии;
* limits.annotated.docx, limits_month.annotated.docx -- копии с комментариями от движка;
* evidence.json -- команды, ожидаемые и фактические соответствия ячеек (вход, report.json,
  повторно открытая копия), диапазоны комментариев по OOXML, цитата комментария в
  изменённой ячейке, результат повторного чтения, сравнение версий движком;
* limits_month_libreoffice.png -- рендер LibreOffice с примечаниями на полях (если есть soffice).
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = HERE / "merged_header"
sys.path[:0] = [str(ROOT / "src"), str(HERE.parent)]

import p03_ooxml as ox  # noqa: E402
from p03_fixtures import LIMITS_COLUMNS, limits_doc, limits_mock_script  # noqa: E402
from test_p03_merged_header import cell_map, cell_path, expected_cells  # noqa: E402

from bcc_review.readers.docx import read_docx  # noqa: E402

FOCUS = {"limits": ["t1.r3.c4"], "limits_month": ["t1.r3.c4", "t1.r4.c2"]}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_cli(args: list[str]) -> str:
    env = {k: v for k, v in os.environ.items()
           if k not in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "GEMINI_API_KEY", "GOOGLE_API_KEY")}
    env.update(PYTHONPATH=str(ROOT / "src"), BCC_FORCE_FALLBACK="review_individual,review_set",
               PYTHONIOENCODING="utf-8")
    cmd = [sys.executable, "-m", "bcc_review", *args]
    res = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True, timeout=300)
    if res.returncode != 0:
        raise SystemExit(f"{' '.join(cmd)}\n{res.stdout}\n{res.stderr}")
    return res.stdout


def reread(src: Path, out: Path) -> dict:
    """Повторное открытие копии: тот же текст, та же связь, те же объединения, пары маркеров."""
    a, b = read_docx(src), read_docx(out)
    root_in, root_out = ox.part(src), ox.part(out)
    q = {"w": ox.W}

    def merges(root):
        return {"tr1_tc2_gridSpan": root.xpath("string(w:body/w:tbl[1]/w:tr[1]/w:tc[2]/w:tcPr/w:gridSpan/@w:val)",
                                               namespaces=q),
                "tc1_vMerge": [v.get(ox.w("val")) or "continue" for v in
                               root.xpath("w:body/w:tbl[1]/w:tr[position()<=2]/w:tc[1]/w:tcPr/w:vMerge", namespaces=q)]}

    new = sorted(set(ox.comments(out)) - set(ox.comments(src)))
    return {
        "blocks_same": [(x.id, x.kind, x.text) for x in a.blocks] == [(x.id, x.kind, x.text) for x in b.blocks],
        "cell_map_same": cell_map(a) == cell_map(b),
        "columns": b.blocks[2].loc["table"]["columns"],
        "header_rows": b.blocks[2].loc["table"]["header_rows"],
        "merges_input": merges(root_in), "merges_copy": merges(root_out),
        "comments_added": len(new),
        "markers_paired": all(ox.marker_counts(out, c) == {"start": 1, "end": 1, "ref": 1} for c in new),
        "source_sha256_unchanged": True,  # проверяется в main по SHA до и после
    }


def main() -> None:
    try:
        import bcc_review.engine  # noqa: F401
    except ImportError:
        raise SystemExit("движка нет в этой ветке: пример строится после слияния с bcc/integration")
    OUT.mkdir(parents=True, exist_ok=True)
    result: dict = {"columns_expected": LIMITS_COLUMNS, "versions": {}}
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        for name, monthly in (("limits", False), ("limits_month", True)):
            src = limits_doc(OUT / f"{name}.docx", monthly=monthly)
            src_sha = sha(src)
            script = OUT / f"{name}.mock.json"
            script.write_text(json.dumps(limits_mock_script(read_docx(src)), ensure_ascii=False, indent=1) + "\n",
                              encoding="utf-8")
            report_md = t / name / "report.md"
            args = [str(src.relative_to(ROOT)), str(report_md), "--provider", "mock", "--mock-script",
                    str(script.relative_to(ROOT)), "--export", "docx", "--no-cache", "--cache-dir", str(t / "cache")]
            if monthly:
                args += ["--compare", str(t / "limits" / "report.json")]
            stdout = run_cli(args)
            rep = json.loads(report_md.with_suffix(".json").read_text(encoding="utf-8"))
            out = OUT / f"{name}.annotated.docx"
            shutil.copyfile(t / name / "report.annotated.docx", out)
            expected, from_input = expected_cells(monthly), cell_map(read_docx(src))
            from_report, from_copy = cell_map(rep["document"]), cell_map(read_docx(out))
            new = sorted(set(ox.comments(out)) - set(ox.comments(src)))
            rmap = ox.range_map(out, new, read_docx(out))
            cells = []
            for ref in FOCUS[name]:
                row, col = int(ref.split(".r")[1].split(".c")[0]), int(ref.rsplit(".c", 1)[1])
                hit = [r for r in rmap.values() if r["start_node"] == cell_path(row, col)]
                cells.append({
                    "cell": ref, "expected": dict(zip(("column_header", "header_refs", "text"), expected[ref])),
                    "actual_input": dict(zip(("column_header", "header_refs", "text"), from_input[ref])),
                    "actual_report_json": dict(zip(("column_header", "header_refs", "text"), from_report[ref])),
                    "actual_reopened_copy": dict(zip(("column_header", "header_refs", "text"), from_copy[ref])),
                    "comment": {"node": hit[0]["start_node"], "covered": hit[0]["covered"], "head": hit[0]["head"]}
                    if len(hit) == 1 else None,
                })
            info = reread(src, out)
            info["source_sha256_unchanged"] = sha(src) == src_sha == rep["document"]["id"]
            entry = {
                "command": "python -m bcc_review " + " ".join(
                    a if not a.startswith(str(t)) else "<tmp>" + a[len(str(t)):] for a in args),
                "env": "BCC_FORCE_FALLBACK=review_individual,review_set, без ключей провайдеров",
                "stdout_tail": stdout.strip().splitlines()[-3:],
                "run": {k: rep["run"][k] for k in ("mode", "status", "provider", "model")},
                "modules": {k: v for k, v in rep["run"]["modules"].items()
                            if k in ("read_docx", "build_inventory", "review_set", "resolve_hint", "provider")},
                "all_cells_match": expected == from_input == from_report == from_copy,
                "cells": cells,
                "findings": [{"id": f["id"], "severity": f["severity"], "status": f["status"], "title": f["title"],
                              "evidence": [{k: e[k] for k in ("block_id", "start", "end", "quote")}
                                           for e in f["evidence"]]} for f in rep["findings"]],
                "comment_ranges": sorted(({"comment_id": c, "node": r["start_node"], "covered": r["covered"],
                                           "head": r["head"]} for c, r in rmap.items()),
                                         key=lambda x: (x["node"], x["comment_id"])),
                "reread": info,
            }
            if monthly:
                changed = [r for r in rmap.values() if r["start_node"] == cell_path(4, 2)]
                entry["changed_cell_comment"] = changed[0]["body"] if len(changed) == 1 else None
                d = rep.get("diff") or {}
                entry["compare"] = {k: [{"old_ids": x.get("old_ids"), "new_ids": x.get("new_ids"),
                                         "title": (x.get("title") or {}).get("new") or (x.get("title") or {}).get("old")}
                                        for x in d.get(k, [])] for k in ("introduced", "resolved", "persisting")}
            result["versions"][name] = entry
            print(name, "| ячейки совпали:", entry["all_cells_match"], "| комментариев:", info["comments_added"],
                  "| повторное чтение:", info["blocks_same"] and info["cell_map_same"])
    (OUT / "evidence.json").write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if soffice and shutil.which("pdftoppm"):
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run([soffice, f"-env:UserInstallation=file://{tmp}/lo", "--headless", "--convert-to",
                            'pdf:writer_pdf_Export:{"ExportNotesInMargin":{"type":"boolean","value":"true"}}',
                            "--outdir", tmp, str(OUT / "limits_month.annotated.docx")], check=True,
                           capture_output=True, timeout=240, env=dict(os.environ, HOME=tmp))
            subprocess.run(["pdftoppm", "-r", "150", "-png", "-f", "1", "-l", "1", "-singlefile",
                            str(Path(tmp) / "limits_month.annotated.pdf"), str(OUT / "limits_month_libreoffice")],
                           check=True, capture_output=True)
        with zipfile.ZipFile(OUT / "limits_month.annotated.docx") as z:
            assert "word/comments.xml" in z.namelist()
        print("рендер:", OUT / "limits_month_libreoffice.png")


if __name__ == "__main__":
    main()
