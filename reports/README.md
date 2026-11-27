# Финальные отчёты агента

Все отчёты в этом каталоге (кроме [`demo_answers/`](demo_answers/README.md) — у него свой README) сформированы
командой `python -m bcc_review …` без кэша на финальной сборке `bcc/v2` 27.11 и руками не правились. Коммит агента
записан в паспорте каждого отчёта (раздел «1. Паспорт прогона» в `.md`, поле `run.commit` в `.json`); что
изменилось в коде после него в ветке `main` — `git log --oneline <коммит>..main -- src`. Любой отчёт можно проверить независимо от
агента: команда `verify` заново ищет каждую цитату в исходнике и сверяет счётчики и SHA-256 входа.

```bash
python -m bcc_review verify reports/requirements.json release/input/requirements.md
```

Таблицу ниже собирает `python scripts/reports_table.py reports --write` из паспортов отчётов; при сборке
`verify` запускается для каждого отчёта заново. Столбец «Эталон кейса» — сверка отчёта по документу кейса с нашим
эталоном (5 критичных дефектов К1–К5, 20 существенных С1–С20, [`docs/task-analysis.md`](../docs/task-analysis.md),
раздел 5) счётчиком `python -m evaluation.v2.score` в строгом счёте: без модели-арбитра, спорное не засчитывается.

<!-- таблица прогонов: начало (scripts/reports_table.py) -->
Отчёты появятся после финальной сборки 27.11.
<!-- таблица прогонов: конец -->

## Как повторить

Модель — Sonnet через подписку Claude (`claude_cli`, `claude -p`), как в замерах качества
[`evaluation/v2/RESULTS.md`](../evaluation/v2/RESULTS.md).

| Отчёт | Команда |
| :--- | :--- |
| `requirements.*` | `python -m bcc_review release/input/requirements.md reports/requirements.md --provider claude_cli --model sonnet --no-cache --export jira,docx` |
| `requirements_pdf.*` | `python -m bcc_review release/input/requirements.pdf reports/requirements_pdf.md --provider claude_cli --model sonnet --no-cache --export jira,docx,pdf` |
| `other_topic_cashback.*` | `python -m bcc_review evaluation/dev/corpus/cases/cashback.base/source.md reports/other_topic_cashback.md --provider claude_cli --model sonnet --no-cache --export jira,docx` |

Все три разом, с `verify` и этой таблицей (чистое дерево, коммит в паспорте без `-dirty`):

```bash
SECOND_DOC=evaluation/dev/corpus/cases/cashback.base/source.md SECOND_NAME=other_topic_cashback ANSWERS= scripts/final_reports.sh claude_cli sonnet
```

На бесплатном Gemini (ключ AI Studio в `.env`) — тот же документ, отчёт рядом: на Windows
`powershell -ExecutionPolicy Bypass -File scripts\gemini_report.ps1`, на любой ОС
`python -m bcc_review release/input/requirements.md reports/my/requirements.md --provider gemini --no-cache`.
