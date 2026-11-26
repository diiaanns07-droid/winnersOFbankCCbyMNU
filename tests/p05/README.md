# №05 — проверка отдельного требования: передача

## Что входит
| Файл | Назначение |
| :--- | :--- |
| `src/bcc_review/criteria.toml` | единый конфиг: критерии И1–И9 и Н1–Н8 с источниками, рубрика серьёзности, правила и пределы, роли разделов, уровни документа, словарь неоперациональных слов, 14 пунктов банковского чек-листа, параметры этапа |
| `src/bcc_review/criteria.py` | `load_criteria(path=None)`: чтение и проверка TOML, отпечаток версии `tag`/`fingerprint`, поиск роли и уровня, серьёзность правил, рендер рубрики для промптов |
| `src/bcc_review/analysis/individual.py` | `review_individual(document, requirements, ask=None, *, criteria=None)`, `build_prompt`, `response_schema`, `prompt_version` |
| `src/bcc_review/prompts/individual.md` | промпт `individual/1.0.0` (system + user, плейсхолдеры `{{…}}`), версия = front matter + SHA-256 файла |
| `src/bcc_review/prompts/individual.schema.json` | схема ответа модели; перечень кодов `criterion` подставляется из TOML |
| `tests/p05/` | 51 тест: четыре доказательства готовности, ложные срабатывания, модельный режим, кейс BCC, упаковка, стык с `contracts/v1.json` |

Временные файлы ветки (bootstrap ещё не опубликован): `pyproject.toml`, `src/bcc_review/__init__.py`,
`src/bcc_review/analysis/__init__.py`. При слиянии берутся версии `bcc/integration`. Перенести нужно
только блок упаковки:

```toml
[tool.setuptools.package-data]
bcc_review = ["criteria.toml", "prompts/*.md", "prompts/*.json"]
```

## Интерфейс
`review_individual(...)` → `{checks, candidates, warnings, meta}`.

* `checks`: матрица «требование × критерий И1–И9», запись есть всегда.
  `{req_id, criterion, status: pass|issue|unknown|na, reason, origin: rules|llm|rules+llm|config, [question], [severity], [refs]}`.
  `refs` указывает на `candidates[].ref`.
* `candidates`: контракт v1 `{scope:"requirement", kind:"defect", criterion, severity, title, impact, req_ids, hints:[{block_id, quote, context?}]}`
  и поля `condition`, `fix`, `question`, `root_cause`, `origin`, `ref`, `calibration`, а у правил ещё `rule` и `severity_rule`.
  Одна первопричина даёт одну кандидатуру. Слияние идёт по `root_cause` или по пересечению цитат в одном блоке.
  `quote` и `context` — буквальные подстроки `block.text`.
* `warnings`: строки `individual.<код>: …` (`missing_answer`, `quote_not_found`, `ask_failed`, `generic_pass`, `template_rows`, `no_blocks` и др.).
* `meta`: `{stage, mode: rules_only|rules_plus_llm, prompt_version, criteria_version, criteria_fingerprint, criteria_tag, calls, requirements}`.
* `ask("individual", payload, schema)`: в `payload` поля `system`, `user`, `prompt_version`, `criteria_tag`,
  `criteria_fingerprint`, `req_ids`, `temperature: 0`. Пакеты задаёт `[individual].batch_size` (15), на кейсе BCC это 2 вызова.

## Как устроена оценка
1. **Правила без модели** (`ask=None`):
   * заглушки («заполняются тестировщиками», TBD, `<указать>`);
   * пустые поля; прочерк как значение (в многоколоночной таблице прочерк значит «не применяется» и пропускается);
   * строки шаблона «Да / Нет» — это не требование, все критерии получают na;
   * неоперациональные слова ISO 29148 5.2.7: перед поиском маскируются цитаты, названия кнопок и экранов, примеры и речь клиента, а заголовки не проверяются;
   * измеримое ограничение в том же пункте или в соседней строке без своего ID снимает неоднозначность;
   * срок: таймер, граница, точка отсчёта, период;
   * диапазон и включённость границ, в том числе по тем же числам в другом месте документа;
   * единичность (не меньше 3 обязательств, только ФТ и НФТ);
   * уровень документа для И2.
2. **Модель.** Получает документ целиком (если он длиннее 60 000 символов, только родительские разделы), роль и раздел каждого пункта, применимые критерии, рубрику из TOML и сигналы правил для подтверждения или опровержения.
3. **Слияние.**
   * Объективная находка правила (прочерк, заглушка) переживает pass модели. Эвристическую модель может отклонить с обоснованием.
   * Issue без буквальной цитаты превращается в unknown и предупреждение. Общий pass без обоснования («Соответствует.») тоже становится unknown.
   * Если модель не дала ответа, ставится unknown с причиной.
   * Числа в правке модели, которых нет в документе, превращаются в `<уточнить у владельца: …?>` и попадают в вопрос.
4. **Калибровка.**
   * Правила не дают critical (`rules_max = major`).
   * Critical от модели требует `blocks` и `scenario`, иначе становится major.
   * `blocks = none` ограничивает серьёзность значением minor.
   * Пределы `[[severity.cap]]` действуют и на ответы модели: Prod/Swagger — не выше major.

## Команды и результаты (выполнено в этой среде)
```bash
python3.11 -m venv .venv && .venv/bin/pip install -q setuptools wheel pytest jsonschema
.venv/bin/python -m pytest tests/p05 -q          # 50 passed, 1 skipped (стык ждёт contracts/v1.json)
python3 -m pytest tests/p05 -q                   # системный 3.13 Debian: 49 passed, 2 skipped (колесо не собирается пропатченным setuptools 68)
```

Прогон правил на выданном документе (`tests/p05/fixtures/bcc_case.md`, SHA-256 `e7dae55e…`, нарезка 27 пунктов в `docfix.BCC_REQS`):
* 243 записи checks, 5 кандидатур, ни одной critical:
  * Ф-2 — 4 обязательства в одном пункте (И5, minor);
  * «заполняются тестировщиками» (И4, minor);
  * `Prod: —` (И4, minor);
  * `**Swagger** | —` (И4, minor);
  * «400, 401 и далее» (И4, major).
* Содержательный pass:
  * Ф-1 (тест 999 / 1 000 / 1 000 000 / 1 000 001);
  * НФТ («в течение минуты» + «после получения события»);
  * `amount` 1 000–1 000 000 (включённость взята из Ф-1).
* Без ложных срабатываний:
  * прочерки в колонке DB field;
  * строки критериев приёмки;
  * «Целое число тенге, обе границы включены»;
  * «REST» внутри «…».
* Цель «в момент покупки» получает unknown с вопросом, а не дефект. Строка чек-листа получает na.

## Проверенные случаи (доказательства)
1. «Операция выполняется быстро» — issue И7 major с правкой без числа и вопросом. «не позднее 60 секунд после получения события процессинга» — pass с таймером, границей и точкой отсчёта (`test_timing_pair.py`).
2. «Быстрый перевод» в заголовке, названии экрана и кнопке не даёт дефекта. «Перевод выполняется быстро» получает дефект, подсказка указывает только на блок обязательства (`test_context_rules.py`).
3. Подставная модель (`test_model.py`):
   * у всех требований 9 записей checks;
   * корректное требование без дефектов, с содержательным pass;
   * выдуманная цитата даёт unknown;
   * пропущенный ответ даёт unknown и `missing_answer`;
   * сбой транспорта не роняет этап.
4. Prod URL (`test_severity_prod.py`):
   * по умолчанию minor (`placeholder.release-field`);
   * major, если документ требует приёмку на Prod;
   * critical от модели урезается до major;
   * изменённое правило в тестовом TOML одновременно меняет серьёзность находки, текст промпта и `criteria_tag` в payload и meta.

Самый рискованный выбор — словарь размытых слов. На наборе из 8 строк наивный поиск по словарю дал 4 ложных срабатывания, контекстные правила — 0 при том же recall (`test_naive_regex_vs_context_aware_rules`).

## Открытые зависимости
* `bcc/integration` и `contracts/HANDOFF.md` не опубликованы (на 26.11 в origin только `claude/nice-edison-gpkcfl` @ `76ab976`). Когда появятся, нужно:
  * сверить имена полей Check и Candidate с `contracts/v1.json`;
  * запустить `pytest tests/p05/test_contract.py::test_stitch_with_bootstrap_contract`, он включится сам.
* Реальный прогон на Gemini или Anthropic не выполнялся (ключа нет). Его проводят Max и №18: `ask` из движка, `batch_size` при необходимости меняется в TOML.
* Сайт bcchubagents.mnu.kz из среды недоступен (DNS). Веса критериев жюри взяты из брифа.

## Кому и что
* **№04**: Requirement с `evidence` (start/end) сужает спаны. Без них берётся весь блок, и правила видят соседние пункты.
* **№07**: `hints[].quote` и `context` — буквальные подстроки. Пустые `hints` бывают только у требований без блоков.
* **Max**: объединять по `root_cause` и `refs`. В `calibration` записано, почему изменилась серьёзность. `meta` идёт в `Report.run`.
* **№06**: критерии набора Н1–Н8 и правила серьёзности уже в TOML (`load_criteria().for_scope("set")`, `render_severity()`).
* **№10**: `checklist` CL01–CL14 с `match` и связями с критериями. Строки чек-листа во входе №05 помечает na и `template_rows`.
* **№17**: `load_criteria().to_dict()` для раздела «Методика». `checks` даёт матрицу «требование × критерий».
