#!/usr/bin/env bash
# Финальные отчёты на теге релиза: официальный документ (MD и PDF) и второй документ, verify, таблица прогонов.
#
#   scripts/final_reports.sh [ПРОВАЙДЕР] [МОДЕЛЬ]        # по умолчанию claude_cli opus
#   SECOND_DOC=evaluation/dev/corpus/cases/cashback.base/source.md scripts/final_reports.sh
#
# Требования к прогону для сдачи: рабочее дерево чистое (коммит в паспорте без -dirty), HEAD на теге v2.*,
# кэш выключен (все ответы модели получены в этом прогоне). Отчёты руками не править.
set -euo pipefail

PROVIDER="${1:-claude_cli}"
MODEL="${2:-opus}"
EXPORT="${EXPORT:-html,jira}"
SECOND_DOC="${SECOND_DOC:-release/input/other_topic_cashback.md}"
OUT="${OUT:-reports}"

cd "$(dirname "$0")/.."

if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
  echo "рабочее дерево изменено: закоммитьте или отложите правки, иначе в паспорте будет -dirty" >&2
  exit 1
fi
tag="$(git describe --tags --exact-match 2>/dev/null || true)"
echo "коммит: $(git rev-parse --short HEAD) ${tag:+(тег $tag)}"
[ -z "$tag" ] && echo "внимание: HEAD не на теге релиза" >&2

suffix=""
[ "$PROVIDER" != "claude_cli" ] && suffix=".${PROVIDER}"

run() {  # вход, имя отчёта
  local input="$1" name="$2"
  echo
  echo "== $input -> $OUT/$name.md ($PROVIDER $MODEL)"
  local start; start=$(date +%s)
  python -m bcc_review "$input" "$OUT/$name.md" --provider "$PROVIDER" --model "$MODEL" --no-cache --export "$EXPORT"
  echo "время: $(( $(date +%s) - start )) с"
  python -m bcc_review verify "$OUT/$name.json" "$input"
}

run release/input/requirements.md "requirements${suffix}"
run release/input/requirements.pdf "requirements_pdf${suffix}"
if [ -f "$SECOND_DOC" ]; then
  run "$SECOND_DOC" "$(basename "${SECOND_DOC%.*}")${suffix}"
fi

python scripts/reports_table.py "$OUT" --write
