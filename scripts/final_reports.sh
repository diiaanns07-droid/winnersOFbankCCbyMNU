#!/usr/bin/env bash
# Финальные отчёты на теге релиза: официальный документ (MD и PDF) и второй документ, verify, таблица прогонов.
#
#   scripts/final_reports.sh [ПРОВАЙДЕР] [МОДЕЛЬ]        # по умолчанию claude_cli opus
#   SECOND_DOC=evaluation/dev/corpus/cases/cashback.base/source.md SECOND_NAME=cashback scripts/final_reports.sh
#   ANSWERS= scripts/final_reports.sh                    # без прогона с ответами владельца
#
# Требования к прогону для сдачи: рабочее дерево чистое (коммит в паспорте без -dirty), HEAD на теге v2.*,
# кэш выключен (все ответы модели получены в этом прогоне). Отчёты руками не править.
set -euo pipefail

PROVIDER="${1:-claude_cli}"
MODEL="${2:-}"
[ -z "$MODEL" ] && [ "$PROVIDER" = "claude_cli" ] && MODEL=opus
EXPORT="${EXPORT:-jira,docx}"
SECOND_DOC="${SECOND_DOC:-release/input/other_topic_cashback.md}"
SECOND_NAME="${SECOND_NAME:-$(basename "${SECOND_DOC%.*}")}"
ANSWERS="${ANSWERS-examples/v2/answers.md}"
OUT="${OUT:-reports}"

cd "$(dirname "$0")/.."

if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
  echo "рабочее дерево изменено: закоммитьте или отложите правки, иначе в паспорте будет -dirty" >&2
  exit 1
fi
# Код агента — из этой копии (worktree на теге), даже если python из чужого .venv с editable-установкой другого
# каталога: иначе паспорт запишет чужой коммит, а отчёт построит не тот код.
export PYTHONPATH="$PWD/src${PYTHONPATH:+:$PYTHONPATH}"
used="$(python -c 'import bcc_review, pathlib; print(pathlib.Path(bcc_review.__file__).resolve().parents[1])')"
if [ "$used" != "$(cd src && pwd -P)" ]; then
  echo "python берёт bcc_review из $used, а не из $PWD/src — запустите из окружения этой копии" >&2
  exit 1
fi
tag="$(git describe --tags --exact-match 2>/dev/null || true)"
echo "коммит: $(git rev-parse --short HEAD) ${tag:+(тег $tag)}; код агента: $used"
[ -z "$tag" ] && echo "внимание: HEAD не на теге релиза" >&2

suffix=""
[ "$PROVIDER" != "claude_cli" ] && suffix=".${PROVIDER}"

run() {  # вход, имя отчёта, форматы экспорта, дополнительные параметры агента
  local input="$1" name="$2" export="${3:-$EXPORT}"
  shift 3 2>/dev/null || shift $#
  local args=(--provider "$PROVIDER" --no-cache --export "$export" "$@")
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
# Ответы владельца (examples/v2/answers.md, №11): пересмотр «до / после» и исправленная редакция ТЗ, затем
# повторная проверка исправленной редакции тем же агентом. ANSWERS= (пусто) — пропустить.
if [ -n "$ANSWERS" ] && [ -f "$ANSWERS" ]; then
  run release/input/requirements.md "requirements.answers${suffix}" "$EXPORT" --answers "$ANSWERS" --revise
  revised="$OUT/requirements.answers${suffix}.revised.md"
  if [ -f "$revised" ]; then
    run "$revised" "requirements.answers${suffix}.revised.review" "$EXPORT"
  else
    echo "внимание: исправленная редакция не записана ($revised)" >&2
  fi
fi
if [ -f "$SECOND_DOC" ]; then
  run "$SECOND_DOC" "${SECOND_NAME}${suffix}"
fi

python scripts/reports_table.py "$OUT" --write --src "${SECOND_NAME}=$SECOND_DOC"
