# Финальные отчёты агента

Все отчёты в этом каталоге сформированы командой `python -m bcc_review …` на теге `v2.0.0` и руками не
правились. Коммит агента записан в паспорте каждого отчёта (раздел «1. Паспорт прогона» в `.md`,
поле `run.commit` в `.json`). Любой отчёт можно проверить независимо от агента: команда `verify` заново
ищет каждую цитату в исходнике и сверяет счётчики и SHA-256 входа.

```bash
python -m bcc_review verify reports/requirements.json release/input/requirements.md
```

Таблицу ниже собирает `python scripts/reports_table.py reports --write` из паспортов отчётов; при сборке
`verify` запускается для каждого отчёта заново.

<!-- таблица прогонов: начало (scripts/reports_table.py) -->
Отчёты появятся на теге `v2.0.0`.
<!-- таблица прогонов: конец -->

## Как повторить

| Отчёт | Команда |
| :--- | :--- |
| `requirements.*` | `python -m bcc_review release/input/requirements.md reports/requirements.md --provider claude_cli --model opus --no-cache --export jira` |
| `requirements_pdf.*` | `python -m bcc_review release/input/requirements.pdf reports/requirements_pdf.md --provider claude_cli --model opus --no-cache --export jira,pdf` |
| `requirements.gemini.*` | `python -m bcc_review release/input/requirements.md reports/requirements.gemini.md --provider gemini --no-cache --export jira` |
