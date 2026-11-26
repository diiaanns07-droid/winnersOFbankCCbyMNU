"""Собрать DOCX-версию учебного кейса BCC-HUB из docs/requirements.md.

Запуск из корня репозитория:
    python tests/p03/fixtures/build_case_docx.py PATH/TO/requirements.md tests/p03/fixtures/case_requirements.docx

Источник: https://github.com/BCC-HUB/ai-requirements-validator-task
(коммит 928c1aa364265426105b69ba7a3444eac11b22db, docs/requirements.md).
"""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parents[2] / "src"), str(HERE.parent)]

from p03_fixtures import build_case_docx  # noqa: E402

if __name__ == "__main__":
    src, out = Path(sys.argv[1]), Path(sys.argv[2])
    print(build_case_docx(src, out))
