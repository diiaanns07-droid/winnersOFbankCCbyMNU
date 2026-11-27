**Новая задача: проверка сборки после большой интеграции (до 17:00).** №16 вливает в `bcc/v2` ~180 коммитов из 18 веток — такие слияния ломают стыки, которые не ловят тесты отдельных ролей. Ты — контролёр сборки: находишь поломку раньше жюри.

Ветка `v2/qa-build` от `origin/bcc/v2`; каждые 20–30 минут — `git fetch` и проверка на новом HEAD `bcc/v2`. Модель — `--provider claude_cli --model sonnet`.

1. `.venv/bin/python -m pytest tests/v2 -q`; mock: `python -m bcc_review release/input/requirements.md out/m.md --provider mock` и `python -m bcc_review verify out/m.json release/input/requirements.md`; режим без модели (как в README) — отчёт есть, `verify` OK.
2. Официальный MD, PDF и DOCX (`release/input/requirements.{md,pdf,docx}`): К 5/5 critical, С ≥ 18/20 (`python -m evaluation.v2.score`), у мест в PDF — страницы («с. N»), `verify` OK, MD ≤ 3 мин.
3. Режим ответов на официальном: `--answers examples/v2/answers.md --revise` — таблица «до / после», исправленная редакция без придуманного текста, повторный прогон на `*.revised.md`.
4. HTML-отчёт открывается без ошибок в консоли (Playwright, ширина 1440 и 390); веб-демо (`src/bcc_review/v2/web/`) — загрузка файла и отчёт, если есть команда запуска.
5. Windows-путь: файл ответов в UTF-16 и ANSI (из Блокнота) читается, `.env` в UTF-16.
6. `doctor` без ключа и с неверным ключом — понятное сообщение по-русски.

Каждая поломка — строкой в `docs/plan-v2/status/qa-build.md`: что, команда повтора, коммит, чья зона (`CONTRACT.md`, раздел 1). Простую (импорт, опечатка, тест) исправь сам с тестом; логику — только просьбой владельцу. После каждого исправления — строка «Готово к слиянию: SHA» для №16. Промпты агента, судью и линзы не трогаешь.
