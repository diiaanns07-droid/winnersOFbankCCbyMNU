#!/usr/bin/env bash
# Чистая установка дословно по README (macOS/Linux): свежий клон, новый venv, установка, прогоны, verify.
#
#   scripts/check_clean_install.sh [ВЕТКА или ТЕГ] [ПРОВАЙДЕРЫ...]
#   scripts/check_clean_install.sh bcc/v2 mock offline claude_cli
#   scripts/check_clean_install.sh v2.0.0-rc1                  # проверка кандидата в релиз (15:00)
#
# Каталог проверки: $CHECK_DIR (по умолчанию временный). Каждый шаг печатается; первая ошибка останавливает скрипт.
set -euo pipefail

BRANCH="${1:-bcc/v2}"
shift || true
PROVIDERS=("$@")
[ ${#PROVIDERS[@]} -eq 0 ] && PROVIDERS=(mock offline)
REPO_URL="${REPO_URL:-https://github.com/diiaanns07-droid/winnersOFbankCCbyMNU.git}"
PYTHON="${PYTHON:-python3.12}"
CHECK_DIR="${CHECK_DIR:-$(mktemp -d)}"

step() { printf '\n== %s\n' "$*"; }

step "клон $REPO_URL ($BRANCH) в $CHECK_DIR"
git clone --quiet --branch "$BRANCH" "$REPO_URL" "$CHECK_DIR/winnersOFbankCCbyMNU"
cd "$CHECK_DIR/winnersOFbankCCbyMNU"
git log --oneline -1

step "шаг 1 README: venv и установка"
"$PYTHON" -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install -q -r requirements.txt -e .
python --version

step "шаг 2 README: .env из шаблона"
cp .env.example .env

for provider in "${PROVIDERS[@]}"; do
  out="reports/my/requirements.${provider}.md"
  step "шаг 3 README: прогон --provider $provider"
  start=$(date +%s)
  python -m bcc_review release/input/requirements.md "$out" --provider "$provider"
  echo "время: $(( $(date +%s) - start )) с"
  step "verify ($provider)"
  python -m bcc_review verify "${out%.md}.json" release/input/requirements.md
  ls -la "$(dirname "$out")" | grep "requirements.${provider}" || true
done

step "CI: прогон без модели по PDF и verify (чтение PDF на этой ОС)"
python -m bcc_review release/input/requirements.pdf reports/my/requirements_pdf.offline.md --provider offline --no-cache
python -m bcc_review verify reports/my/requirements_pdf.offline.json release/input/requirements.pdf

step "CI: колёса зависимостей для всех ОС и Python 3.11–3.14"
python scripts/check_wheels.py || echo "внимание: проверка колёс не прошла (нужна сеть до pypi.org)" >&2

step "одна команда для жюри: scripts/jury_check.sh mock"
scripts/jury_check.sh mock | tail -n 16

step "тесты tests/v2 (как в CI: PYTHONUTF8=1 только для pytest)"
PYTHONUTF8=1 python -m pytest tests/v2 -q

step "дерево после прогонов (должно быть чистым)"
git status --short

step "готово: $CHECK_DIR/winnersOFbankCCbyMNU"
