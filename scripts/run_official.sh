#!/usr/bin/env bash
# Одна команда: установить агента и проверить официальный документ кейса (Linux, macOS).
#
#   scripts/run_official.sh                       # провайдер по ключам в .env (auto)
#   scripts/run_official.sh gemini                # бесплатный Gemini (ключ GEMINI_API_KEY в .env)
#   scripts/run_official.sh claude_cli sonnet     # Claude Code CLI с выбранной моделью
#   DOC=release/input/requirements.pdf scripts/run_official.sh
#
# Скрипт создаёт .venv (если его нет), ставит зависимости, проверяет настройку (doctor), запускает агента,
# сверяет отчёт с документом (verify) и печатает, где лежат файлы. Отчёт — в reports/my/ (не попадает в git).
set -euo pipefail

PROVIDER="${1:-auto}"
MODEL="${2:-}"
DOC="${DOC:-release/input/requirements.md}"
OUT="${OUT:-reports/my/$(basename "${DOC%.*}").md}"
PYTHON="${PYTHON:-python3}"
export PIP_DISABLE_PIP_VERSION_CHECK=1

cd "$(dirname "$0")/.."

if [ ! -x .venv/bin/python ]; then
  echo "== создаю .venv ($PYTHON)"
  "$PYTHON" -m venv .venv
fi
py=.venv/bin/python

echo "== установка"
"$py" -m pip install -q -r requirements.txt -e .

if [ ! -f .env ] && [ -f .env.example ]; then
  cp .env.example .env
  echo "создан .env из .env.example — впишите ключ в строку GEMINI_API_KEY="
fi

echo "== проверка настройки"
"$py" -m bcc_review doctor --provider "$PROVIDER" || true

args=(--provider "$PROVIDER")
[ -n "$MODEL" ] && args+=(--model "$MODEL")

echo
echo "== прогон: $DOC -> $OUT"
code=0
"$py" -m bcc_review "$DOC" "$OUT" "${args[@]}" || code=$?

json="${OUT%.md}.json"
if [ ! -f "$json" ]; then
  echo "отчёт не записан (код выхода $code)" >&2
  [ "$code" -eq 0 ] && code=1
  exit "$code"
fi

echo
echo "== verify"
verify=0
"$py" -m bcc_review verify "$json" "$DOC" || verify=$?

echo
echo "Отчёт: $OUT"
for f in "${OUT%.md}".html "$json"; do [ -f "$f" ] && echo "       $f"; done
if [ "$code" -eq 3 ]; then
  echo "Модель недоступна: отчёт собран только правилами. Проверьте ключ: $py -m bcc_review doctor --live" >&2
fi
[ "$verify" -ne 0 ] && exit "$verify"
exit "$code"
