#!/usr/bin/env bash
# Проверка «как у жюри» (№42): свежий git clone во временную папку → ./start.sh --check → второй запуск.
# Печатает время каждого шага и «от клона до ответа сервера». Браузер не открывается.
#
#   scripts/check_start.sh                              клон этой папки (её текущей ветки)
#   scripts/check_start.sh https://github.com/diiaanns07-droid/winnersOFbankCCbyMNU release
#
# Кэш pip выключен (как на пустом компьютере); CACHE=1 — разрешить. KEEP=1 — не удалять временную папку.
set -u

src="${1:-$(cd "$(dirname "$0")/.." && pwd)}"
branch="${2:-}"
if [ -z "$branch" ] && [ -d "$src/.git" ]; then
  branch="$(git -C "$src" rev-parse --abbrev-ref HEAD)"
fi
[ "${CACHE:-0}" = "1" ] || export PIP_NO_CACHE_DIR=1

tmp="$(mktemp -d "${TMPDIR:-/tmp}/bcc-check.XXXXXX")" || exit 1
dest="$tmp/bcc review"   # пробел в пути — как в профиле пользователя
cleanup() { [ "${KEEP:-0}" = "1" ] && echo "папка оставлена: $tmp" || rm -rf -- "$tmp"; }
trap cleanup EXIT

now() { python3 -c 'import time; print(time.time())' 2>/dev/null || date +%s; }
dt() { python3 -c "print(f'{$2 - $1:.1f}')" 2>/dev/null || echo $(( ${2%.*} - ${1%.*} )); }

t0=$(now)
echo "== 1. git clone ${branch:+-b $branch }$src"
git clone -q ${branch:+-b "$branch"} "$src" "$dest" || { echo "git clone не удался" >&2; exit 1; }
t1=$(now)

echo "== 2. ./start.sh --check (первый запуск: .venv, зависимости, сервер)"
(cd "$dest" && ./start.sh --check) || { echo "ПРОВАЛ: первый запуск ./start.sh --check" >&2; exit 1; }
t2=$(now)

echo "== 3. ./start.sh --check (повторный: без установки)"
out="$(cd "$dest" && ./start.sh --check 2>&1)" || { echo "$out" >&2; echo "ПРОВАЛ: повторный запуск" >&2; exit 1; }
t3=$(now)
case "$out" in
  *"ставлю зависимости"*) echo "ПРОВАЛ: повторный запуск снова ставил зависимости" >&2; exit 1 ;;
esac

echo
echo "git clone:                        $(dt "$t0" "$t1") с"
echo "первый ./start.sh --check:        $(dt "$t1" "$t2") с"
echo "повторный ./start.sh --check:     $(dt "$t2" "$t3") с"
echo "от клона до ответа сервера:       $(dt "$t0" "$t2") с"
echo "ИТОГ: ok"
