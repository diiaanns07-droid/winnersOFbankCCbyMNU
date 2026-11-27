# BCC Review · MNU AI Club

Агент проверяет банковское ТЗ до разработки. В русском отчёте каждое замечание связано с цитатой, а готовность к разработке и тестированию оценивается отдельно. Для знакомства откройте первые два замечания и перейдите к указанным строкам исходника. [Готовый офлайн-отчёт](release/reports/offline/requirements.md) · [Исходное ТЗ](release/input/requirements.md) · [Отчёт JSON](release/reports/offline/requirements.json)

## Запустить пример жюри без ключа

Нужны Git и Python 3.11 или новее. Отчёты для жюри упакованы в `0ffbbaa`. Команды ниже получают код агента, который их создал, — `12ed4d70e5d91ba9a8ba8ec1b89b5fc7921ac1a3`. Для закрытого репозитория используется учётная запись GitHub с доступом команды. [Комплект для жюри](https://github.com/diiaanns07-droid/winnersOFbankCCbyMNU/tree/0ffbbaa1c36d547840d8831329eb173013bff4b4/release) · [Интеграционная ветка](https://github.com/diiaanns07-droid/winnersOFbankCCbyMNU/tree/bcc/integration)

```sh
git clone --branch bcc/integration --single-branch https://github.com/diiaanns07-droid/winnersOFbankCCbyMNU.git bcc-review
cd bcc-review
git switch --detach 12ed4d70e5d91ba9a8ba8ec1b89b5fc7921ac1a3
```

**Windows PowerShell**, пример для установленного Python 3.13. При другой версии укажите её номер в первой строке.

```powershell
py -3.13 -m venv .venv
$py = (Resolve-Path .venv/Scripts/python.exe).Path
& $py -m pip install -e .
& $py -m bcc_review release/input/requirements.md out/requirements.md --offline-lint --no-cache
& $py -m bcc_review verify out/requirements.json release/input/requirements.md
```

**Linux** с модулем `venv` и `pip` (в Ubuntu они доступны с пакетом `python3-venv`).

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/python -m bcc_review release/input/requirements.md out/requirements.md --offline-lint --no-cache
.venv/bin/python -m bcc_review verify out/requirements.json release/input/requirements.md
```

Откройте `out/requirements.md`. В соседнем `requirements.json` проверьте `run.mode = rules_only`, `run.status = partial`, `run.model = null` и `run.calls.physical = 0`. Пропущенные этапы перечислены в `run.incomplete_stages`. Команда `verify` заново читает исходный файл и возвращает `OK` при согласованных байтах, ссылках и счётчиках. Для повторной проверки укажите тот же исходник. Для нового запуска сохраняйте результат в отдельный каталог.

## Полный прогон Claude для владельца ключа

Max координирует платный запуск. Командный ключ Claude API задаётся в переменной окружения `ANTHROPIC_API_KEY` или в файле `.env` в рабочем каталоге. `ANTHROPIC_MODEL` позволяет выбрать модель, а фактическая модель записывается в паспорт результата. [Пустой шаблон переменных](.env.example) · [Ключи Claude Console](https://platform.claude.com/settings/keys) · [Состояние официального прогона](release/reports/live/README.md)

Используйте Python из того же окружения. Ниже `python` обозначает `.venv/bin/python` в Linux или `.venv\Scripts\python.exe` в Windows.

```sh
python -m pip install -e ".[anthropic]"
python -m bcc_review release/input/requirements.md out/live/requirements.md --provider anthropic --no-cache --fail-on partial --export html,jira --max-calls 40 --max-seconds 1800
```

Код 5 у этой команды означает неполный прогон. Причина записана в `out/live/requirements.json`. После кода 0 выполните `python -m bcc_review verify out/live/requirements.json release/input/requirements.md` и сверьте паспорт по инструкции владельца. В нём должны быть `rules_plus_llm`, `complete`, фактическая модель, физические вызовы и SHA `12ed4d7`. Для PDF и Word доступны группы установки `.[pdf]` и `.[docx]`. [Приёмка официального отчёта](release/reports/live/README.md)

Проверенный путь от чек-листа до решения аналитика, команды Docker и результаты установки на двух ОС собраны в [протоколе №18](packaging/README.md).
