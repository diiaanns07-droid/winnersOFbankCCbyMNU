#!/usr/bin/env bash
# Проверка «как у жюри» одной командой (macOS и Linux): ключ и модель → прогон официального документа без кэша →
# verify → сверка с эталоном К1–К5, С1–С20 → сводка с воротами (статус complete, время, вызовы).
#
#   scripts/jury_check.sh                         # Gemini, модель по умолчанию (ключ GEMINI_API_KEY в .env)
#   scripts/jury_check.sh gemini gemini-3.6-flash
#   scripts/jury_check.sh claude_cli haiku
#   scripts/jury_check.sh mock                    # без сети: проверка установки
#
# Отчёт: out/jury/requirements.<провайдер>.md (+ .json, .html, score.md). Код выхода 0 — все ворота пройдены.
# Пределы: MAX_MINUTES (по умолчанию 6 для gemini, 15 для остальных), MAX_CALLS (12).
set -uo pipefail

PROVIDER="${1:-gemini}"
MODEL="${2:-}"

# shellcheck source=scripts/_env.sh
source "$(dirname "$0")/_env.sh"

if [ "$PROVIDER" = "gemini" ]; then
  MAX_MINUTES="${MAX_MINUTES:-6}"
else
  MAX_MINUTES="${MAX_MINUTES:-15}"
fi
MAX_CALLS="${MAX_CALLS:-12}"
DOC=release/input/requirements.md
OUTDIR=out/jury
OUT="$OUTDIR/requirements.${PROVIDER}.md"
JSON="${OUT%.md}.json"
model_args=()
[ -n "$MODEL" ] && model_args=(--model "$MODEL")

echo "== коммит агента: $(git rev-parse --short HEAD 2>/dev/null || echo 'нет .git')"

if [ "$PROVIDER" != "mock" ] && [ "$PROVIDER" != "offline" ]; then
  echo "== 1. ключ и пробный вызов модели"
  if ! "$PY" -m bcc_review doctor --live --provider "$PROVIDER" ${model_args[@]+"${model_args[@]}"}; then
    echo
    echo "Модель не ответила — исправьте то, что написано в «Что исправить» выше, и запустите снова." >&2
    exit 3
  fi
fi

echo
echo "== 2. прогон официального документа без кэша: $DOC -> $OUT"
rm -f "$JSON"
start=$(date +%s)
"$PY" -m bcc_review "$DOC" "$OUT" --provider "$PROVIDER" ${model_args[@]+"${model_args[@]}"} --no-cache --export jira
code=$?
seconds=$(( $(date +%s) - start ))
echo "время: ${seconds} с, код выхода ${code}"
if [ ! -f "$JSON" ]; then
  echo "Отчёт не записан." >&2
  [ "$code" -eq 0 ] && code=1
  exit "$code"
fi

echo
echo "== 3. verify"
"$PY" -m bcc_review verify "$JSON" "$DOC"
verify=$?

score_args=()
if [ -d evaluation/v2 ]; then
  echo
  echo "== 4. сверка с эталоном (строгий счёт, без модели)"
  if "$PY" -m evaluation.v2.score "$JSON" --report-md "$OUT" --out "$OUTDIR/score.${PROVIDER}.json" \
       --md "$OUTDIR/score.${PROVIDER}.md" >/dev/null; then
    score_args=(--score "$OUTDIR/score.${PROVIDER}.json")
    echo "разбор: $OUTDIR/score.${PROVIDER}.md"
  else
    echo "счётчик эталона не отработал — пропускаю" >&2
  fi
fi

"$PY" scripts/run_summary.py "$JSON" ${score_args[@]+"${score_args[@]}"} --verify-code "$verify" --seconds "$seconds" \
  --max-minutes "$MAX_MINUTES" --max-calls "$MAX_CALLS" --check
