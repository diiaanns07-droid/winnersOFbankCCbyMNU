#!/usr/bin/env bash
# Кладёт официальные знаки в assets/logos/ и проверяет, что это картинки, а не страница ошибки.
# Затем: node tools/render.mjs — кадры пересоберутся уже с логотипами.
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p assets/logos
fetch() {
  local url=$1 out=$2 kind=$3
  curl -fsSL --retry 3 -o "$out.part" "$url"
  if ! file -b --mime-type "$out.part" | grep -q "^image/$kind"; then
    echo "Не картинка ($kind): $url → $(file -b --mime-type "$out.part")" >&2
    rm -f "$out.part"; return 1
  fi
  mv "$out.part" "$out"
  echo "OK $out ($(wc -c <"$out") байт, sha256 $(sha256sum "$out" | cut -c1-16)…)"
}
fetch https://bcchubagents.mnu.kz/assets/logos/bcc-hub-full.png assets/logos/bcc-hub-full.png png
fetch https://bcchubagents.mnu.kz/assets/logos/mnu-ai-club.webp assets/logos/mnu-ai-club.webp webp
