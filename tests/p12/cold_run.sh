#!/usr/bin/env bash
# Холодный прогон адаптера Gemini (№12) для №18: чистый venv, офлайн-тесты, затем живая часть.
#
#   bash tests/p12/cold_run.sh                  # python3.11 по умолчанию
#   bash tests/p12/cold_run.sh python3.13
#   GEMINI_API_KEY=... GEMINI_MODEL=gemini-2.5-flash bash tests/p12/cold_run.sh
#
# Без GEMINI_API_KEY выполняется только офлайн-часть: квота не тратится.
# Живая часть тратит 4–5 запросов: doctor (1+) и test_p12_live.py (2) плюс models.list.
set -euo pipefail

PY="${1:-python3.11}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VENV="${P12_VENV:-$(mktemp -d)/venv}"

"$PY" -m venv "$VENV"
cd "$ROOT"
"$VENV/bin/python" -m pip install -q --disable-pip-version-check -e ".[dev]" "google-genai==3.6.1"
"$VENV/bin/python" -c "import sys, google.genai as g; print('python', sys.version.split()[0], '| google-genai', g.__version__)"
"$VENV/bin/python" -m pytest tests/contract tests/p12 -q -p no:cacheprovider -rs

if [ -z "${GEMINI_API_KEY:-}" ]; then
  echo "GEMINI_API_KEY не задан: живая часть пропущена (см. tests/p12/README.md, раздел 7)."
  exit 0
fi
echo "== models.list (ключ видит эти модели с generateContent)"
"$VENV/bin/python" -m bcc_review.providers.gemini models
echo "== doctor: один вызов с общей синтетической схемой"
"$VENV/bin/python" -m bcc_review.providers.gemini doctor
echo "== живые тесты: одна находка и пустой массив"
P12_LIVE=1 "$VENV/bin/python" -m pytest tests/p12/test_p12_live.py -v -s -p no:cacheprovider
