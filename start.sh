#!/usr/bin/env bash
# BCC Review — запуск одной командой (macOS, Linux):  ./start.sh
# Находит Python 3.11+, создаёт .venv, ставит зависимости (только когда изменились requirements.txt или
# constraints.txt) и открывает веб-интерфейс в браузере. Повторный запуск — за секунды.
#   ./start.sh --check        проверить установку: поднять сервер, получить /healthz и /, выйти
#   ./start.sh --port 9000    другие флаги передаются в python -m bcc_review.v2.web
# Из интернета скачивается только `pip install -r requirements.txt`.
set -u

cd "$(dirname "$0")" || exit 1
ROOT="$(pwd)"
export PYTHONUTF8=1 PYMUPDF_SUGGEST_LAYOUT_ANALYZER=0 PIP_DISABLE_PIP_VERSION_CHECK=1
# код агента — из этой копии (без `pip install -e .`: ему нужен setuptools из интернета)
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

say() { printf '%s\n' "$*"; }
fail() { printf '%s\n' "$*" >&2; exit 1; }

os="$(uname -s 2>/dev/null || echo unknown)"
if [ "$os" = "Darwin" ]; then
  # двойной щелчок по start.command: в PATH может не быть Homebrew и python.org
  PATH="$PATH:/opt/homebrew/bin:/usr/local/bin:/Library/Frameworks/Python.framework/Versions/Current/bin"
fi

good_python() {  # $1 — команда; 0, если это Python 3.11–3.15
  command -v "$1" >/dev/null 2>&1 || return 1
  if [ "$os" = "Darwin" ] && [ "$(command -v "$1")" = "/usr/bin/python3" ] && ! xcode-select -p >/dev/null 2>&1; then
    return 1  # заглушка macOS: без Command Line Tools вместо Python откроется окно установки Xcode
  fi
  "$1" -c 'import sys; sys.exit(0 if (3, 11) <= sys.version_info[:2] < (3, 16) else 1)' >/dev/null 2>&1
}

PY="$ROOT/.venv/bin/python"
if [ -e .venv ] && ! "$PY" -c 'import sys' >/dev/null 2>&1; then
  say "Окружение .venv повреждено или создано другим Python — создаю заново."
  rm -rf .venv
fi

if [ ! -x "$PY" ]; then
  base=""
  for c in python3.12 python3.13 python3.11 python3.14 python3 python; do
    if good_python "$c"; then base="$c"; break; fi
  done
  if [ -z "$base" ]; then
    if [ "$os" = "Darwin" ]; then
      fail "Нужен Python 3.11 или новее: brew install python@3.12 (или установщик с https://www.python.org/downloads/), затем снова ./start.sh"
    else
      fail "Нужен Python 3.11 или новее: sudo apt install python3 python3-venv (Fedora: sudo dnf install python3), затем снова ./start.sh"
    fi
  fi
  say "Создаю окружение .venv ($("$base" --version 2>&1))…"
  if ! "$base" -m venv .venv >/dev/null 2>"$ROOT/.venv-error.log"; then
    rm -rf .venv
    cat "$ROOT/.venv-error.log" >&2
    rm -f "$ROOT/.venv-error.log"
    fail "Не удалось создать .venv. Ubuntu/Debian: sudo apt install python3-venv, затем снова ./start.sh"
  fi
  rm -f "$ROOT/.venv-error.log"
fi

# метка установки: хеш requirements.txt + constraints.txt; совпал — pip не запускаем
want="$("$PY" -c 'import hashlib; print(hashlib.sha256(open("requirements.txt","rb").read() + open("constraints.txt","rb").read()).hexdigest())')"
stamp=".venv/.bcc-req"
if [ ! -f "$stamp" ] || [ "$(cat "$stamp" 2>/dev/null)" != "$want" ]; then
  log=".venv/pip.log"
  t0=$(date +%s)
  "$PY" -m pip install -q -r requirements.txt >"$log" 2>&1 &
  pid=$!
  while kill -0 "$pid" 2>/dev/null; do
    printf '\rУстанавливаю зависимости (только при первом запуске, 1–3 минуты)… %s с ' "$(( $(date +%s) - t0 ))"
    sleep 1
  done
  if ! wait "$pid"; then
    printf '\n'
    tail -n 25 "$log" >&2
    fail "Установка зависимостей не удалась (полный журнал: .venv/pip.log). Проверьте интернет и запустите ./start.sh ещё раз."
  fi
  printf '\rЗависимости установлены за %s с.%40s\n' "$(( $(date +%s) - t0 ))" ""
  printf '%s' "$want" > "$stamp"
fi

exec "$PY" -m bcc_review.v2.web --open "$@"
