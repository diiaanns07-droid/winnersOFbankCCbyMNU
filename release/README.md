# Комплект релиза bcc-review: кандидат 2026-11-26

Агент статического ревью ТЗ (BCC-HUB × MNU FinTech Hackathon). Комплект нужен, чтобы
повторить прогон с нуля и сверить отчёт с источником без доверия к автору отчёта.

**Версия агента:** ветка `bcc/integration`, коммит кода `f91d3b6f485e883d316c94fc5e032f1a8d6c2553`
(контракт Report v1.0, `contracts/v1.json`). Коммит записан в паспорте каждого отчёта
(`run.agent_commit`) без пометки `-dirty`.

## Что внутри

| Путь | Что это | SHA-256 |
| :--- | :--- | :--- |
| `input/requirements.md` | исходник организаторов: `docs/requirements.md` из BCC-HUB/ai-requirements-validator-task @ `928c1aa`, байт в байт | `e7dae55e5453a250d93e335f5ff9c7f775f4457ccddd333f4a67e47b20d74381` |
| `input/requirements.pdf` | PDF того же текста, собран для проверки PDF-входа (не выдан организаторами) | `fbca9c8282f440754d43c2ec689a27a9ccc32ac07a1c4b30a7ca22c21d7e4de2` |
| `input/other_topic_cashback.md` | документ другой тематики (кэшбэк) с засеянными дефектами; ключ — `tests/integration/fixtures/other_topic_cashback.expected.md` | `dba611718f649983b808d5f502e79fea4f8abe64b29b10da325bc0581ecd0b4b` |
| `reports/offline/` | отчёты **без модели** (`--offline-lint`): `.md`, `.json`, `.html`, `.jira.csv`, `*.artifacts/` (результаты этапов и JSONL-трасса) | — |
| `reports/live/` | пусто. Сюда кладётся итоговый отчёт живого прогона, см. ниже | — |

Отчёты не правились руками. `python -m bcc_review verify` проверяет каждую цитату, счётчики и паспорт по источнику.

## Чистая установка

Python 3.11 или 3.12. Windows PowerShell:

```powershell
git clone https://github.com/diiaanns07-droid/winnersOFbankCCbyMNU
cd winnersOFbankCCbyMNU
git switch bcc/integration
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -e ".[all]"
```

macOS и Linux: `python3.12 -m venv .venv && .venv/bin/python -m pip install -e ".[all]"`.

## Повторить офлайн-отчёты (без ключа, ~2 с на документ)

```powershell
.venv\Scripts\python -m bcc_review release\input\requirements.md out\requirements.md --offline-lint --export html,jira
.venv\Scripts\python -m bcc_review verify out\requirements.json release\input\requirements.md
```

В паспорте: `run.mode = rules_only`, `run.status = partial`, `run.model = null`, 0 вызовов модели.
Готовность «не определено»: без семантических этапов агент не утверждает, что документ готов.

## Итоговый живой прогон (владелец ключа)

Ключ держите в переменной окружения текущей сессии, не в файлах репозитория. Кэш выключен,
чтобы все ответы модели были получены в этом прогоне.

```powershell
$env:ANTHROPIC_API_KEY = "<ключ>"
.venv\Scripts\python -m bcc_review release\input\requirements.md release\reports\live\requirements.md --provider anthropic --no-cache --export html,jira,pdf
.venv\Scripts\python -m bcc_review verify release\reports\live\requirements.json release\input\requirements.md
.venv\Scripts\python -m bcc_review release\input\other_topic_cashback.md release\reports\live\other_topic_cashback.md --provider anthropic --no-cache --export html
.venv\Scripts\python -m bcc_review verify release\reports\live\other_topic_cashback.json release\input\other_topic_cashback.md
```

Запасной воспроизводимый профиль (бесплатный ключ Google AI Studio):

```powershell
$env:GEMINI_API_KEY = "<ключ>"
.venv\Scripts\python -m bcc_review release\input\requirements.md release\reports\live\requirements.gemini.md --provider gemini --no-cache
```

Прогон годится для сдачи, если в `requirements.json`:

* `run.mode = "rules_plus_llm"`, `run.status = "complete"`, `run.incomplete_stages = []`;
* `run.model` — фактическая модель из ответа провайдера, `run.calls.physical > 0`, `run.calls.cache_hits = 0`;
* `run.agent_commit` совпадает с `git rev-parse HEAD` и без `-dirty`;
* `verify` печатает `OK`.

Если бюджет или лимиты провайдера оборвали прогон, отчёт всё равно пишется: `run.status = partial`,
в `run.status_reasons` и `run.incomplete_stages` названы невыполненные этапы, готовность не будет «можно
начинать». Такой отчёт не сдавать как итоговый: повторить прогон.

## Что получено от настоящей модели

Ничего. В сессии сборки ключа не было: все числа в `reports/offline` получены детерминированными
правилами, `run.calls.physical = 0`. Живой прогон по командам выше остаётся за владельцем ключа.

## Отчёты офлайн-прогона в этом комплекте

Сгенерированы на коммите `f91d3b6` командой из раздела «Повторить офлайн-отчёты» (`--no-cache`), `verify` — OK.

| Вход | Длительность прогона | Требований | Замечаний (сущ./незн.) | Опор проверено verify | `.md` | `.json` | `.html` |
| :--- | ---: | ---: | :--- | ---: | ---: | ---: | ---: |
| `requirements.md` | 1,2 с | 49 | 26 (12/14) | 319 | 294 КБ | 660 КБ | 723 КБ |
| `requirements.pdf` | 6,3 с | 49 | 25 (11/14) | 309 | 288 КБ | 917 КБ | 701 КБ |
| `other_topic_cashback.md` | 1,0 с | 20 | 19 (11/8) | 147 | 146 КБ | 289 КБ | 371 КБ |

Критичных замечаний офлайн нет: противоречия К1, К2 и пропуски К4, К5 находят семантические этапы с моделью.
Режим `rules_only` честно отмечен в паспорте, готовность к разработке и тестированию — «не определено».
