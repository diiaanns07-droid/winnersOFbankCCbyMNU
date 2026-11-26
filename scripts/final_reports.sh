#!/usr/bin/env bash
# Финальные отчёты на теге релиза: официальный документ (MD и PDF) и второй документ, verify, таблица прогонов.
#
#   scripts/final_reports.sh [ПРОВАЙДЕР] [МОДЕЛЬ]        # по умолчанию claude_cli opus
#   SECOND_DOC=evaluation/dev/corpus/cases/cashback.base/source.md SECOND_NAME=cashback scripts/final_reports.sh
#
# Требования к прогону для сдачи: рабочее дерево чистое (коммит в паспорте без -dirty), HEAD на теге v2.*,
# кэш выключен (все ответы модели получены в этом прогоне). Отчёты руками не править.
set -euo pipefail

PROVIDER="${1:-claude_cli}"
MODEL="${2:-}"
[ -z "$MODEL" ] && [ "$PROVIDER" = "claude_cli" ] && MODEL=opus
EXPORT="${EXPORT:-jira}"
SECOND_DOC="${SECOND_DOC:-release/input/other_topic_cashback.md}"
SECOND_NAME="${SECOND_NAME:-$(basename "${SECOND_DOC%.*}")}"
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

run() {  # вход, имя отчёта, форматы экспорта
  local input="$1" name="$2" export="${3:-$EXPORT}"
  local args=(--provider "$PROVIDER" --no-cache --export "$export")
  [ -n "$MODEL" ] && args+=(--model "$MODEL")
  echo
  echo "== $input -> $OUT/$name.md ($PROVIDER ${MODEL:-модель по умолчанию})"
  local start; start=$(date +%s)
  python -m bcc_review "$input" "$OUT/$name.md" "${args[@]}"
  echo "время: $(( $(date +%s) - start )) с"
  python -m bcc_review verify "$OUT/$name.json" "$input"
}

run release/input/requirements.md "requirements${suffix}"
run release/input/requirements.pdf "requirements_pdf${suffix}" "${EXPORT},pdf"
if [ -f "$SECOND_DOC" ]; then
  run "$SECOND_DOC" "${SECOND_NAME}${suffix}"
fi

python scripts/reports_table.py "$OUT" --write --src "${SECOND_NAME}=$SECOND_DOC"
