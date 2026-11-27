Просьба от F4: проведи экзамен ответов владельца — если есть свободный лимит sonnet; если нет — сразу после сброса.

Ветка `v2/21-scenario` от свежей `bcc/v2`; вся серия — на одном коммите. Файлы F4 — ветка `origin/codex/f4-precision-audit`, папка `docs/plan-v2/f4/answers_exam/`: `git fetch origin && git checkout origin/codex/f4-precision-audit -- docs/plan-v2/f4/answers_exam`. Команды — раздел «Запуск» в её `README.md` (PowerShell; на bash — те же аргументы): `--provider claude_cli --model sonnet --no-cache --no-html`.

1. **car-loan** (новое ТЗ F4): первый прогон `baseline` — запушь сразу: по его вопросам F4 зафиксирует ответы.
2. **official и qr** (ответы уже есть): прогон с `--answers … --revise`, `verify`, повторный прогон на `*.revised.md`, `verify` — ровно как в README.
3. Сохрани отчёты MD/JSON, исправленный текст и данные этапов пересмотра и правки (`runs/<id>/stages/`) в `evaluation/v2/answers_exam/<документ>/`, запушь; путь и SHA — оператору.

Эталон F4 не открывай, даже если он появится в ветке. Агента под экзамен не меняй и результаты не трактуй — счёт ведёт F4.
