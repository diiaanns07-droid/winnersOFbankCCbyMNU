# Официальный онлайн-прогон: не выполнен

Официальный прогон координирует Max. В комплекте `0ffbbaa` опубликован офлайн-отчёт. Ниже одна команда генерации для владельца командного ключа и проверка, которую можно повторить без ключа на полученном JSON. [Комплект для жюри](https://github.com/diiaanns07-droid/winnersOFbankCCbyMNU/tree/0ffbbaa1c36d547840d8831329eb173013bff4b4/release) · [Офлайн-отчёты](../offline/)

**Версия агента для прогона:** `12ed4d70e5d91ba9a8ba8ec1b89b5fc7921ac1a3` на `bcc/integration` (в `70d2617` и раньше живой Claude отвечал
400 на лишнее поле `cache` в сообщении — исправлено в `f84f730`), контракт Report v1.0.
**Вход:** `release/input/requirements.md`, SHA-256 `e7dae55e5453a250d93e335f5ff9c7f775f4457ccddd333f4a67e47b20d74381`.
**Модель:** из конфигурации адаптера №11 — `ANTHROPIC_MODEL`, по умолчанию `claude-opus-5-5`, усилие `high`.

## Команда для владельца ключа

Начните в новом каталоге PowerShell с Git и Python 3.13. Задайте `ANTHROPIC_API_KEY` в окружении исполнителя или в локальном `.env` клона. Если ключа нет, движок сохранит диагностический отчёт и вернёт код 5. На Linux используйте `python3 -m venv .venv` и `.venv/bin/python`. Во время генерации рабочее дерево должно быть чистым.

```powershell
git clone --branch bcc/integration --single-branch https://github.com/diiaanns07-droid/winnersOFbankCCbyMNU.git bcc-live
if ($LASTEXITCODE) { throw 'Не удалось получить репозиторий' }
Set-Location bcc-live
$expectedCommit = '12ed4d70e5d91ba9a8ba8ec1b89b5fc7921ac1a3'
git switch --detach $expectedCommit
if ($LASTEXITCODE -or (git rev-parse HEAD) -ne $expectedCommit) { throw 'Проверьте SHA агента' }
py -3.13 -m venv .venv
if ($LASTEXITCODE) { throw 'Не удалось создать venv' }
$py = (Resolve-Path .venv/Scripts/python.exe).Path
& $py -m pip install -e ".[anthropic]"
if ($LASTEXITCODE) { throw 'Не удалось установить SDK' }
& $py -m bcc_review release/input/requirements.md out/live/requirements.md --provider anthropic --no-cache --fail-on partial --export html,jira --max-calls 40 --max-seconds 1800
if ($LASTEXITCODE) { throw 'Прогон не завершён. См. out/live/requirements.json и вывод CLI.' }
```

Бюджет: прогон делает около 13–16 физических вызовов (замер на подставном провайдере:
нарезка 2, отдельные требования 4, набор 3, вопросы 3, чек-лист 1, плюс проверка смысла при наличии
кандидатов модели и эвристических правил). `--max-calls 40` оставляет запас на повторы 429/529, `--max-seconds 1800` — общий
лимит времени. Если ответы обрываются на `max_tokens`, повторить с `$env:ANTHROPIC_MAX_TOKENS = "32000"`.

Запасной путь через подписку Claude Code требует авторизованного CLI и сборки, в которой соединены движок v1 и адаптер v2. На `bcc/integration@d0bc06d` одного флага `--provider claude_cli` недостаточно. Проверка на этом SHA вернула `rules_only/partial` и ноль вызовов. Для официального SDK-прогона выше используется `12ed4d7`. [Условия плана Б](../../../contracts/HANDOFF.md)

## Проверка полученного отчёта без вызова модели

Из корня проверенного клона выполните второй блок. Получатель может положить переданные файлы в `out/live/` и повторить его отдельно. Команда `verify` сверяет байты, цитаты и счётчики. Следующая проверка сверяет режим, модель и версию с выбранным кандидатом.

```powershell
$py = (Resolve-Path .venv/Scripts/python.exe).Path
$expectedCommit = '12ed4d70e5d91ba9a8ba8ec1b89b5fc7921ac1a3'
$sourceHash = 'e7dae55e5453a250d93e335f5ff9c7f775f4457ccddd333f4a67e47b20d74381'
& $py -m bcc_review verify out/live/requirements.json release/input/requirements.md
if ($LASTEXITCODE) { throw 'verify обнаружил расхождение' }
$report = Get-Content -Raw -Encoding utf8 out/live/requirements.json | ConvertFrom-Json
$run = $report.run
$accepted = ($run.agent_commit -eq $expectedCommit -and $report.document.id -eq $sourceHash -and
    $run.provider -eq 'anthropic' -and $run.mode -eq 'rules_plus_llm' -and $run.status -eq 'complete' -and
    @($run.incomplete_stages).Count -eq 0 -and $run.model -and $run.calls.physical -gt 0 -and $run.calls.cache_hits -eq 0)
if (-not $accepted) { throw 'Паспорт не соответствует официальному онлайн-прогону v1' }
$run | Select-Object agent_commit, provider, model, mode, status, calls
```

После обеих проверок передайте Max сгенерированные файлы из `out/live/`, включая Markdown, JSON, HTML, Jira CSV и каталог артефактов. Max размещает их в `release/reports/live/` в коммите упаковки. При коде 5 причину можно найти в `run.status_reasons` и `run.incomplete_stages`.
