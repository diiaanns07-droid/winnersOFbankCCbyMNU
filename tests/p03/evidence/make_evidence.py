"""Пересобрать доказательства №03: аннотированный DOCX кейса, результат и рендер LibreOffice.

Запуск из корня репозитория:
    python tests/p03/evidence/make_evidence.py

LibreOffice (soffice) и pdftoppm нужны только для PDF/PNG; без них пишутся DOCX и JSON.
"""

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parents[2] / "src"), str(HERE.parent)]

from p03_fixtures import CASE_DOCX  # noqa: E402
from test_p03_case import case_report  # noqa: E402

from bcc_review.exports.word import annotate_docx  # noqa: E402


def main() -> None:
    doc, report = case_report()
    out = HERE / "report.annotated.docx"
    res = annotate_docx(report, CASE_DOCX, out)
    data = res.to_dict()
    root = HERE.parents[2]
    for key in ("input_path", "output_path"):
        data[key] = Path(data[key]).resolve().relative_to(root).as_posix()
    (HERE / "report.annotated.result.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(res.summary_ru())
    print(json.dumps(res.checks, ensure_ascii=False))
    soffice = shutil.which("soffice")
    if not soffice:
        print("soffice не найден: PDF/PNG не построены")
        return
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run([soffice, f"-env:UserInstallation=file://{tmp}/lo", "--headless", "--convert-to",
                        'pdf:writer_pdf_Export:{"ExportNotesInMargin":{"type":"boolean","value":"true"}}',
                        "--outdir", tmp, str(out)], check=True, capture_output=True, timeout=240)
        pdf = Path(tmp) / "report.annotated.pdf"
        if shutil.which("pdftoppm"):
            subprocess.run(["pdftoppm", "-r", "80", "-png", "-f", "2", "-l", "2", "-singlefile", str(pdf),
                            str(HERE / "libreoffice_page2")], check=True, capture_output=True)
            print(HERE / "libreoffice_page2.png")


if __name__ == "__main__":
    main()
