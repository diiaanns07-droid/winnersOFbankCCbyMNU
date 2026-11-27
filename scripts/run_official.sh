#!/usr/bin/env bash
# Одна команда: окружение, проверка документа, verify, сводка (macOS и Linux).
#
#   scripts/run_official.sh                                  # официальный документ кейса, модель — по ключу в .env
#   scripts/run_official.sh путь/к/ТЗ.pdf                    # свой документ (.pdf, .docx, .md, .html, .txt)
#   scripts/run_official.sh release/input/requirements.md --provider mock   # любые параметры bcc_review после пути
#
# Отчёт: reports/my/<имя документа>.md (для PDF, DOCX и др. — <имя>_<расширение>.md), рядом .json и .html.
# Первый запуск сам создаёт .venv и ставит зависимости.
set -uo pipefail

DOC="release/input/requirements.md"
if [ $# -gt 0 ] && [ "${1#-}" = "$1" ]; then
  DOC="$1"
  shift
  # путь от текущего каталога: дальше скрипт работает из корня репозитория
  if [ -f "$DOC" ]; then
    DOC="$(cd "$(dirname "$DOC")" && pwd)/$(basename "$DOC")"
  fi
fi

# shellcheck source=scripts/_env.sh
source "$(dirname "$0")/_env.sh"
if [ ! -f "$DOC" ]; then
  echo "Файл не найден: $DOC" >&2
  exit 2
fi
stem="$(basename "${DOC%.*}")"
ext="${DOC##*.}"
[ "$ext" != "md" ] && [ "$ext" != "$DOC" ] && stem="${stem}_${ext}"
OUT="${OUT:-reports/my}/${stem}.md"
JSON="${OUT%.md}.json"

echo "== проверка документа: $DOC -> $OUT"
start=$(date +%s)
"$PY" -m bcc_review "$DOC" "$OUT" "$@"
code=$?
seconds=$(( $(date +%s) - start ))
if [ ! -f "$JSON" ]; then
  exit "$code"
fi

echo
echo "== verify: каждая цитата ищется в документе заново"
"$PY" -m bcc_review verify "$JSON" "$DOC"
verify=$?

"$PY" scripts/run_summary.py "$JSON" --verify-code "$verify" --seconds "$seconds"
if [ "$verify" -ne 0 ]; then
  exit "$verify"
fi
exit "$code"
