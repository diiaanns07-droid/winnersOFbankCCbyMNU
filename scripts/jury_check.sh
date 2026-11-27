#!/usr/bin/env bash
# Проверка агента так, как его запустит жюри: doctor --live -> прогон официального документа -> verify -> сводка.
# Черновик №02, принят №16.
#
#   bash scripts/jury_check.sh                               # Gemini, ключ — строка GEMINI_API_KEY=... в .env
#   PROVIDER=claude_cli MODEL=haiku bash scripts/jury_check.sh
#   DOC=release/input/requirements.pdf bash scripts/jury_check.sh
set -u
cd "$(dirname "$0")/.."
PROVIDER="${PROVIDER:-gemini}"
MODEL="${MODEL:-}"
DOC="${DOC:-release/input/requirements.md}"
OUT="${OUT:-out/jury_check}"
if [ -z "${PYTHON:-}" ] && [ -x .venv/bin/python ]; then PY=.venv/bin/python; else PY="${PYTHON:-python3}"; fi
# Массивы не бывают пустыми: в bash 3.2 (macOS) пустой массив при set -u — ошибка «unbound variable».
doctor=(doctor --live --provider "$PROVIDER")
run=(--provider "$PROVIDER" --no-cache)
if [ -n "$MODEL" ]; then doctor+=(--model "$MODEL"); run+=(--model "$MODEL"); fi
mkdir -p "$OUT"
name="$(basename "${DOC%.*}")"

echo "== 1/4 проверка модели: doctor --live --provider $PROVIDER"
if ! "$PY" -m bcc_review "${doctor[@]}"; then
  echo "СТОП: модель не ответила. Исправьте по подсказке «Что исправить» выше и запустите скрипт снова."
  exit 2
fi

echo "== 2/4 прогон: $DOC -> $OUT/$name.md"
start=$(date +%s)
"$PY" -m bcc_review "$DOC" "$OUT/$name.md" "${run[@]}"
code=$?
secs=$(( $(date +%s) - start ))

echo "== 3/4 verify: цитаты и паспорт отчёта"
"$PY" -m bcc_review verify "$OUT/$name.json" "$DOC"
vcode=$?

echo "== 4/4 сводка"
"$PY" scripts/jury_summary.py "$OUT/$name.json" "$secs" "$code" "$vcode"
