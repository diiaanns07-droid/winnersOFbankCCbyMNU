# Официальный онлайн-прогон: не выполнен

**Состояние на 2026-11-26:** каталог пуст сознательно. В среде сборки нет командного ключа Anthropic:
нет `.env` в корне репозитория, не заданы `ANTHROPIC_API_KEY` и `ANTHROPIC_AUTH_TOKEN`, не установлен
`ant`. Обращений к модели не было (0 физических вызовов), отчёта онлайн-прогона нет. Офлайн-результаты
этой же версии лежат в `../offline/` и помечены `rules_only`.

**Версия агента для прогона:** `8e8e95f4bb8a65bdd10d7e4599dd4747ffe8c803` (сборка), контракт Report v1.0.
**Вход:** `release/input/requirements.md`, SHA-256 `e7dae55e5453a250d93e335f5ff9c7f775f4457ccddd333f4a67e47b20d74381`.
**Модель:** из конфигурации адаптера №11 — `ANTHROPIC_MODEL`, по умолчанию `claude-opus-5-5`, усилие `high`.

## Команда для владельца ключа

Из корня репозитория на ветке `bcc/integration`, дерево без изменений (иначе в паспорте будет `-dirty`):

```powershell
git switch bcc/integration
git pull --ff-only
.venv\Scripts\python -m pip install -e ".[all]"
$env:ANTHROPIC_API_KEY = "<командный ключ>"
.venv\Scripts\python -m bcc_review release\input\requirements.md release\reports\live\requirements.md --provider anthropic --no-cache --export html,jira --max-calls 40 --max-seconds 1800
.venv\Scripts\python -m bcc_review verify release\reports\live\requirements.json release\input\requirements.md
```

Бюджет: на этой версии прогон делает около 13 физических вызовов (замер на подставном провайдере:
нарезка 2, отдельные требования 4, набор 3, вопросы 3, чек-лист 1, плюс проверка смысла при наличии
кандидатов модели). `--max-calls 40` оставляет запас на повторы 429/529, `--max-seconds 1800` — общий
лимит времени. Если ответы обрываются на `max_tokens`, повторить с `$env:ANTHROPIC_MAX_TOKENS = "32000"`.

## Прогон годится для сдачи, если в `requirements.json`

* `run.mode = "rules_plus_llm"`, `run.status = "complete"`, `run.incomplete_stages = []`;
* `run.model` — фактическая модель из ответа, `run.calls.physical > 0`, `run.calls.cache_hits = 0`;
* `run.agent_commit` = SHA сборки без `-dirty`;
* `verify` печатает `OK`.

Если статус `partial`, отчёт не сдавать как итоговый: причины и незавершённые этапы — в
`run.status_reasons` и `run.incomplete_stages`, повторить прогон. После успешного прогона закоммитить этот
каталог; SHA упаковки будет отличаться от SHA генерации (`run.agent_commit`), это нормально.
