# Комплект релиза bcc-review: сборка 12ed4d7 (2026-11-27)

Агент статического ревью ТЗ (BCC-HUB × MNU FinTech Hackathon). Комплект нужен, чтобы
повторить прогон с нуля и сверить отчёт с источником без доверия к автору отчёта.

**Версия агента:** ветка `bcc/integration`, коммит сборки `12ed4d70e5d91ba9a8ba8ec1b89b5fc7921ac1a3`
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
Готовность «можно начинать» в этом режиме невозможна: без семантических этапов агент её не утверждает.
Если правила подтвердили критичный дефект, вердикт — «нельзя начинать»; иначе — «не определено».

## Итоговый живой прогон (владелец ключа)

Ключ держите в переменной окружения текущей сессии, не в файлах репозитория. Кэш выключен,
чтобы все ответы модели были получены в этом прогоне.

```powershell
$env:ANTHROPIC_API_KEY = "<ключ>"
.venv\Scripts\python -m bcc_review release\input\requirements.md release\reports\live\requirements.md --provider anthropic --no-cache --export html,jira --max-calls 40 --max-seconds 1800
.venv\Scripts\python -m bcc_review verify release\reports\live\requirements.json release\input\requirements.md
.venv\Scripts\python -m bcc_review release\input\other_topic_cashback.md release\reports\live\other_topic_cashback.md --provider anthropic --no-cache --export html --max-calls 40 --max-seconds 1800
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
* `run.agent_commit` — SHA сборки (`12ed4d7…` или новее) без `-dirty`;
* `verify` печатает `OK`.

Если бюджет или лимиты провайдера оборвали прогон, отчёт всё равно пишется: `run.status = partial`,
в `run.status_reasons` и `run.incomplete_stages` названы невыполненные этапы, готовность не будет «можно
начинать». Такой отчёт не сдавать как итоговый: повторить прогон.

## Что получено от настоящей модели

Ничего. В среде сборки командного ключа не было (`.env`, `ANTHROPIC_API_KEY`, `ant` — проверено): все числа
в `reports/offline` получены детерминированными правилами, `run.calls.physical = 0`. Статус и готовая
команда официального прогона — в `reports/live/README.md`.

## Отчёты офлайн-прогона в этом комплекте

Сгенерированы на коммите `12ed4d7` командой из раздела «Повторить офлайн-отчёты» (`--no-cache`), `verify` — OK.

| Вход | Длительность прогона | Требований | Замечаний (крит./сущ./незн.) | Опор проверено verify | Готовность разр./тест. | `.md` | `.json` | `.html` |
| :--- | ---: | ---: | :--- | ---: | :--- | ---: | ---: | ---: |
| `requirements.md` | 1.2 с | 53 | 27 (2/11/14) | 594 | нельзя / нельзя | 341 КБ | 889 КБ | 1065 КБ |
| `requirements.pdf` | 6.2 с | 53 | 25 (2/10/13) | 589 | нельзя / нельзя | 338 КБ | 1164 КБ | 1052 КБ |
| `other_topic_cashback.md` | 0.7 с | 20 | 19 (1/10/8) | 181 | нельзя / нельзя | 152 КБ | 326 КБ | 430 КБ |

### Три решения для аналитика

- **F-001, месяц покупки.** По Ф-2 покупка 31 января в 23:58 относится к январю (строка 38). Приёмка ожидает пополнения февральского счётчика после проведения 1 февраля в 00:03 (строка 64). Владельцу нужно выбрать момент учёта и уточнить часовой пояс первого события, иначе тест и реализация могут разнести одну покупку по разным месяцам.
- **F-002, загрузка экрана.** Часть A обещает чтение и сохранение настроек (строка 52). На экране нужны порог и накопленная сумма (строка 29). В части B описано сохранение через `/alerts/saveLimit`. Для реализации и приёмки загрузки экрана нужны операция чтения и состав её ответа.
- **F-004, сравнение сумм.** Покупка хранится в тиынах, порог в тенге (строка 49). API задаёт порог целым числом тенге (строка 124). Владелец может зафиксировать сравнение в тиынах и ожидаемый результат для покупки на один тиын ниже порога.

Для официального Markdown команда `verify` подтвердила 594 вхождения опор. В диагностике есть две опоры вне блока связанного требования и две повторяющиеся в блоке цитаты. Полный перечень доступен через `verify --json`. Официальный онлайн-прогон выполняет владелец ключа.
