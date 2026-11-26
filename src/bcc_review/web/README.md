# bcc_review.web — веб-демо для банковского аналитика (№15)

Аналитик загружает ТЗ (PDF/Markdown/DOCX), видит этапы и вердикт, открывает фрагменты
замечаний, отвечает на вопросы, подтверждает новую редакцию, сравнивает отчёты и скачивает
файлы, которые действительно записал движок. Своей логики качества и своего клиента LLM у
веба нет: каждый анализ — это вызов `bcc_review.run_review(input_path, report_md, options=…)`.

## Запуск

```bash
pip install -e ".[dev]"
```

```bash
python -m bcc_review.web
```

Откройте <http://127.0.0.1:8015/>. Ключ читается из `.env` (`ANTHROPIC_API_KEY` или `GEMINI_API_KEY`).

| Флаг | Что делает |
| :--- | :--- |
| `--provider anthropic\|gemini\|mock` | явный провайдер (иначе — тот, чей ключ найден) |
| `--mock-script FILE` | сценарий mock-провайдера движка: настоящий движок без ключа и сети |
| `--cache-dir DIR` | кэш ответов модели движка (`RunOptions.cache_dir`) |
| `--engine dev` | подставной движок `devengine` для разработки UI; все отчёты помечены mock |
| `--demo DIR` | плюс сохранённые прогоны по адресу `/demo/…` (только просмотр, с датой и моделью) |
| `--demo-answers FILE` | демонстрационные ответы команды с подписью происхождения |
| `--data-dir DIR` | хранилище запусков (по умолчанию `./.bcc_web`, внутри свой `.gitignore`) |
| `--export html` | экспорты движка (`RunOptions.exports`), по умолчанию HTML №13 |

Сохранить готовый прогон (и его родительские редакции) для показа без сети:

```bash
python -m bcc_review.web pack RUN_ID --out demo_bundle
```

## Хранилище

`<data>/runs/<run_id>/`: `run.json` (статус, родитель, цепочка редакций, артефакты),
`events.jsonl` (этапы), `input/` (документ, `answers.md`), `tmp/` (удаляется после прогона),
`artifacts/` (что записал движок), `artifacts/web/` (что сформировал веб: `questions.md`),
`claims/` (атомарные заявки). `run_id` = `ГГГГММДД-ччммсс-xxxxxx`, имя файла очищается
(`safe_filename`), исходное хранится в `run.json`.

* Две загрузки с одним именем файла → разные `run_id`.
* Повторная отправка той же формы загрузки (тот же `upload_key`) → тот же запуск.
* Повторное подтверждение тех же ответов → тот же дочерний запуск (заявка `os.link`/`O_EXCL`;
  проверено на 50 одновременных кликах: наивная проверка давала 26–43 платных запуска, заявка — 1).
* Решение к устаревшей редакции → 409 и ссылка на актуальный результат.
* Ответы накапливаются по цепочке; повтор без новых ответов и без нового документа отклоняется.
* Запуски, прерванные перезапуском сервера, при старте помечаются `failed` (`interrupted`).

## Статусы и режимы

`started → running → complete | partial | failed`. Итоговый статус берётся из
`report.run.status`; без `report.json` — `failed` с причиной. Режим (`rules_plus_llm`,
`rules_only`, `mock`) — из `report.run.mode`; всё, кроме `rules_plus_llm`, а также
`partial` и коды неполного чтения в `document.warnings` показываются как «Отчёт неполный».
Нет ключа → веб заранее предупреждает и передаёт `offline_lint=True`. Если движок всё же
упал на ключе (`ProviderError` `auth`/`not_configured`), страница предлагает «Проверить
только по правилам». Оценка времени — только медиана реально измеренных прогонов того же
движка и режима.

Настоящий движок без ключа (репетиция полного пути):

```bash
python -m bcc_review.web --provider mock --mock-script tests/p15/fixtures/mock_case_web.json --demo-answers tests/p15/fixtures/demo_answers.md
```

## Стык с движком (contracts v1, `bcc/integration` 091e504)

Веб передаёт только поля `RunOptions`: `provider`, `offline_lint`, `exports`,
`answers_path`, `compare_path`, `run_id`, `parent_run_id`, `artifacts_dir`,
`mock_script`, `cache_dir`.
`progress` и `tmp_dir` передаются, только если их объявит `RunOptions` (сейчас их там нет —
веб пишет это в паспорт запуска). Живые этапы во время прогона веб читает из JSONL-трассы
движка `artifacts_dir/*trace*.jsonl` (поля `stage|name` и `status|state|event`), после
прогона — из `report.run.stages`.

Формат `answers.md` совместим с `runtime.fallback.decisions.parse_answers` (слот №08):

```text
source_sha256: <SHA-256 документа, который проверит новая редакция>

## Q-001
Вопрос: <prompt>
Источник ответа: аналитик (веб-форма) | демонстрационный ответ команды (…) | вариант N из вопроса … (предложение движка, модель …)
Ответ: <текст ответа>
Правка: «фрагмент как в документе» → «новый текст»
```

Ответ без правки фиксирует решение (`report.decisions`), но документ остаётся прежним.
Правка превращается в редакцию B: движок пишет её отдельным файлом
`artifacts/<имя>.rev-….md` и проверяет уже её. Веб показывает этот файл в «Файлах запуска».

## Тесты

```bash
python -m pytest tests/contract tests/p15
```

`tests/p15/test_browser.py` проходит путь аналитика в Chromium (Node Playwright);
без node/playwright тест пропускается. Скриншоты: `P15_SHOTS=out/p15 python -m pytest tests/p15/test_browser.py`.
