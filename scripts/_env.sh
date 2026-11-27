# Общая часть scripts/run_official.sh и scripts/jury_check.sh (подключается через source, сама не запускается).
# Переходит в корень репозитория, создаёт .venv (если его нет), ставит зависимости (если они изменились)
# и создаёт .env из .env.example. После неё в $PY — python из активированного окружения или из .venv.

cd "$(dirname "${BASH_SOURCE[0]}")/.." || exit 1
export PYTHONUTF8=1 PYMUPDF_SUGGEST_LAYOUT_ANALYZER=0

if [ -n "${VIRTUAL_ENV:-}" ] && [ -x "$VIRTUAL_ENV/bin/python" ]; then
  PY="$VIRTUAL_ENV/bin/python"   # уже активированное окружение (шаг 1 README)
elif [ -x .venv/bin/python ]; then
  PY=.venv/bin/python
else
  base=""
  for candidate in python3.12 python3.13 python3.11 python3 python; do
    if command -v "$candidate" >/dev/null 2>&1 &&
       "$candidate" -c 'import sys; sys.exit(0 if (3, 11) <= sys.version_info[:2] < (3, 14) else 1)' 2>/dev/null; then
      base="$candidate"
      break
    fi
  done
  if [ -z "$base" ]; then
    echo "Нужен Python 3.11, 3.12 или 3.13: https://www.python.org/downloads/" >&2
    exit 1
  fi
  echo "== создаю окружение .venv ($("$base" --version))"
  if ! "$base" -m venv .venv; then
    echo "Не удалось создать .venv. На Ubuntu поставьте пакет venv: sudo apt install python3-venv" >&2
    exit 1
  fi
  PY=.venv/bin/python
fi

stamp="$(dirname "$(dirname "$PY")")/.bcc_requirements"
if [ ! -f "$stamp" ] || ! cmp -s requirements.txt "$stamp" || ! "$PY" -c "import bcc_review" 2>/dev/null; then
  echo "== установка зависимостей (1–2 минуты при первом запуске)"
  "$PY" -m pip install -q --disable-pip-version-check -r requirements.txt -e . || {
    echo "Установка не удалась — сообщение pip выше." >&2
    exit 1
  }
  cp requirements.txt "$stamp"
fi

if [ ! -f .env ]; then
  cp .env.example .env
  echo "== создан .env из шаблона: впишите ключ в строку GEMINI_API_KEY= (https://aistudio.google.com/apikey)"
fi
