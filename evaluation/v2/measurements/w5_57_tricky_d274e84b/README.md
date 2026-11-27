# №57 — живые прогоны каверзных входов (код d274e84b + строка «Большой документ» из 90cd1e56)

Входы — `input/` (созданы тестом/скриптом, без слов официального ТЗ). Команда:
`python -m bcc_review input/<вход>.md <модель>/<вход>.md --provider claude_cli --model <модель> --no-cache`.
`base_bcc_v2/` — тот же вход на `origin/bcc/v2` (до правки) для колонки «было».

| Вход | Модель | Каталог |
| :--- | :--- | :--- |
| рецепт (не ТЗ) | haiku; было — haiku на `bcc/v2` | `haiku/recipe.*`, `base_bcc_v2/recipe_haiku.*` |
| ТЗ + вставка «игнорируй инструкции…» и то же ТЗ без неё | sonnet ×2 | `sonnet/tz_clean*`, `sonnet/tz_inj_text*` |
| английское ТЗ, казахское ТЗ | haiku | `haiku/tz_en.*`, `haiku/tz_kz.*` |
| ≈82 страницы (склейка официального, clean, open2) | haiku | `haiku/long_80p.*` |
