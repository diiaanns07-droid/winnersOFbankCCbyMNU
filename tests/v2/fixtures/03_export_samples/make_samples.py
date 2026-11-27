"""Образцы экспорта для демо и видео (№03 → №14).

    python tests/v2/fixtures/03_export_samples/make_samples.py

Прогон без модели (mock) на ответах живого прогона sonnet (tests/v2/fixtures/official) для официального документа
в трёх форматах; результаты экспорта и кадры PNG кладутся рядом со скриптом:

* official.annotated.docx — копия requirements.docx с комментариями ревью Word на местах цитат и сводным комментарием;
* official.annotated.pdf — копия requirements.pdf с выделениями цитат (цвет — серьёзность) и примечаниями;
* official.jira.csv — задачи Jira (строка на дефект);
* official.report.docx — Word-версия отчёта (для входа Markdown);
* png/*.png — кадры: страницы PDF с выделениями, Word с комментариями на полях (через LibreOffice).
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
MOCK = ROOT / "tests/v2/fixtures/official"


def run(inp: Path, out_dir: Path) -> Path:
    out = out_dir / inp.stem / "report.md"
    cmd = [sys.executable, "-m", "bcc_review", str(inp), str(out), "--provider", "mock", "--mock-dir", str(MOCK),
           "--export", "jira,docx,pdf", "--no-html"]
    env = {"PYTHONPATH": str(ROOT / "src"), "PATH": "/usr/bin:/bin:/usr/local/bin", "PYMUPDF_SUGGEST_LAYOUT_ANALYZER": "0"}
    import os
    env = {**os.environ, **env}
    subprocess.run(cmd, check=False, capture_output=True, timeout=600, cwd=ROOT, env=env)
    return out.parent


def png_pdf(pdf: Path, pages: list[int], prefix: str, dpi: int = 110) -> list[Path]:
    import pymupdf
    outs = []
    (HERE / "png").mkdir(exist_ok=True)
    with pymupdf.open(str(pdf)) as d:
        for p in pages:
            if 1 <= p <= d.page_count:
                o = HERE / "png" / f"{prefix}_p{p}.png"
                d[p - 1].get_pixmap(dpi=dpi, annots=True).save(str(o))
                outs.append(o)
    return outs


def docx_with_margin_comments(docx: Path, tmp: Path) -> Path | None:
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice:
        return None
    flt = 'pdf:writer_pdf_Export:{"ExportNotesInMargin":{"type":"boolean","value":"true"}}'
    subprocess.run([soffice, "--headless", "--convert-to", flt, "--outdir", str(tmp), str(docx)],
                   check=False, capture_output=True, timeout=240)
    pdf = tmp / (docx.stem + ".pdf")
    return pdf if pdf.exists() else None


def main() -> int:
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        dx = run(ROOT / "release/input/requirements.docx", tmp)
        pdf = run(ROOT / "release/input/requirements.pdf", tmp)
        md = run(ROOT / "release/input/requirements.md", tmp)
        shutil.copy(dx / "report.annotated.docx", HERE / "official.annotated.docx")
        shutil.copy(pdf / "report.annotated.pdf", HERE / "official.annotated.pdf")
        shutil.copy(md / "report.jira.csv", HERE / "official.jira.csv")
        shutil.copy(md / "report.docx", HERE / "official.report.docx")
        shutil.rmtree(HERE / "png", ignore_errors=True)
        shots = png_pdf(HERE / "official.annotated.pdf", [2, 5, 6], "pdf_highlights")
        rendered = docx_with_margin_comments(HERE / "official.annotated.docx", tmp)
        if rendered:
            shots += png_pdf(rendered, [1, 2, 4], "word_comments", dpi=100)
    for p in sorted(HERE.glob("official.*")) + shots:
        print(p.relative_to(ROOT), p.stat().st_size)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
