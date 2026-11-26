# №05 — проверка отдельного требования: передача

Ветка: `claude/practical-ride-4z65ch` (назначена платформой вместо `bcc/p05-individual`). В неё влит
`bcc/integration` @ `091e504` (контракт v1 из `431f76d` и движок). Точка входа совпадает с таблицей в
`contracts/HANDOFF.md`. Движок сам выбирает модуль №05: `run.modules.review_individual = team:bcc_review.analysis.individual:review_individual`.

## Что входит
| Файл | Назначение |
| :--- | :--- |
| `src/bcc_review/criteria.toml` | единый конфиг. Критерии `necessary…conforming` (И1–И9) и `set_complete…traceable` (Н1–Н8) с русскими определениями, источником ISO/IEC/IEEE 29148:2018 или IEEE 830-1998, применимостью (`not_for`), видом находки (`kind`) и связями с 14 пунктами банковского чек-листа. Ещё рубрика critical/major/minor, политика и правила серьёзности, пределы, роли разделов, `kind_alias` для `Requirement.kind`, уровни документа, словарь неоперациональных слов, параметры этапа |
| `src/bcc_review/criteria.py` | `load_criteria(path=None)`: проверка схемы, отпечаток `tag`/`fingerprint`, `resolve()` (код, `И3`, русское имя), роль и уровень, `rule_severity()`, `cap_for()`, `render_*()` для промптов, `to_dict()` для отчёта |
| `src/bcc_review/analysis/individual.py` | `review_individual(document, requirements, ask=None, *, criteria=None)`, `build_prompt`, `response_schema`, `prompt_version` |
| `src/bcc_review/prompts/individual.md` | промпт `individual/1.1.0`: инструкция этапа (`task`), плейсхолдеры `{{…}}` из TOML. Версия = front matter + SHA-256 файла |
| `src/bcc_review/prompts/individual.schema.json` | строгая схема ответа: `additionalProperties: false`, полный `required`, без `minLength`/`$ref`. Перечни `criterion` и `kind` подставляются из TOML и `contracts.FINDING_KINDS` |
| `tests/p05/` | 59 тестов: четыре доказательства, ложные срабатывания, модельный режим, кейс BCC, стык с контрактом и движком, упаковка |

Упаковку TOML и промптов уже обеспечивает `pyproject.toml` интеграционной ветки (`"*" = ["*.toml", "*.json", "*.md", …, "prompts/*"]`).
Тест собирает колесо из копии и читает конфиг из установленного пакета. Из общих файлов ветка добавляет только
`src/bcc_review/analysis/__init__.py`: без него `packages.find` не увидит пакет `analysis`.

## Интерфейс (контракт v1)
`review_individual(...)` → `{checks, candidates, warnings, failed, meta}`.

* `checks` (`Check`): матрица «требование × 9 критериев», запись есть всегда.
  `{req_id, criterion, status: pass|issue|unknown|na, reason, source: llm|rules, basis: llm|rules|rules+llm|config}`
  плюс `question`, `severity` (у issue) и `candidate_refs`.
  * `source = llm`, если модель оценила этот критерий пункта: так движок в `build_checks` ставит `review_status = reviewed`. Неприменимые критерии у отвеченного пункта тоже идут с `llm`.
  * `basis` показывает, откуда взят итоговый статус.
  * `candidate_refs` — ссылки на `IND-…`; движок переводит их в `finding_ids`.
* `failed`: `{req_id: причина}` для пунктов без оценки модели, по тому же правилу, что у резерва движка:
  * `ask=None` — все пункты;
  * `AskError` — пункты пакета;
  * `budget_exhausted` — пункты пакета и все последующие, вызовы прекращаются;
  * модель пропустила пункт.
* `candidates` (`Candidate`): `{scope:"requirement", kind ∈ FINDING_KINDS, criterion ∈ INDIVIDUAL_CRITERIA, severity, title, impact, req_ids, hints:[{block_id, quote, context?}], recommendation, blocked_decision, cause:{object, condition, outcomes}, source, stage:"individual"}`.
  Дополнительно `blocks` (`development|testing`, как в `Finding`), `question`, `root_cause`, `ref` (`IND-001`…), `calibration` (почему изменилась серьёзность), а у ответа модели `scenario`, у правил `rule_id` (движок переносит его в Finding) и `severity_rule`.
  Одна первопричина — одна кандидатура. Слияние идёт по `root_cause` или по пересечению цитат в блоке.
  `quote` и `context` — буквальные подстроки `block.text`. `block_id = null` бывает только у требования без блоков.
* `warnings` (`Warning`): `{code: "individual.<…>", message, stage}`. Коды: `missing_answer`, `quote_not_found`, `ask_failed`, `generic_pass`, `bad_check`, `unexpected_req`, `template_rows`, `no_blocks`, `unknown_block`, `na_overridden`.
* `meta`: `{stage, mode: rules_only|rules_plus_llm, prompt_version, criteria_version, criteria_fingerprint, criteria_tag, calls, requirements}`.
* `ask("individual#N", payload, schema)` — имя этапа на каждый пакет, как у резерва (кэш и трасса различают пакеты):
  * `payload = {task, input, context}`;
  * `input` = `{prompt_version, criteria_tag, criteria_fingerprint, req_ids, requirements:[{req_id, source_id, role, level, section, applicable, not_applicable, block_ids, text, neighbors, rule_signals}]}`;
  * `context = {mode:"auto", block_ids}` — блоки пунктов и их родительских разделов;
  * текст документа прикладывает движок;
  * пакет — `[individual].batch_size = 15`, на кейсе BCC это 2 вызова;
  * `AskError`/`BudgetExhausted` перехватываются: этап возвращает частичный результат (правила и unknown), `failed` и `ask_failed`. Движок по `failed` помечает этап `failed` или `partial`.
* `load_criteria()` → `Criteria`. Объект поддерживает и mapping-доступ, как резервный справочник движка: `for code, info in crit.items(): info["name"], info["standard"], info["question"]`.

## Как устроена оценка
1. **Правила без модели** (`ask=None`, они же `--offline-lint`):
   * заглушки («заполняются тестировщиками», TBD, `<указать>`) и пустые поля;
   * прочерк как значение (в многоколоночной таблице это «не применяется» и пропускается);
   * строки шаблона «Да / Нет» — не требование, все критерии na;
   * неоперациональные слова ISO 29148 5.2.7. Перед поиском маскируются цитаты, названия кнопок и экранов, примеры и речь клиента; заголовки не проверяются;
   * измеримое ограничение в пункте или соседней строке без своего ID снимает неоднозначность;
   * срок: таймер, граница, точка отсчёта, период. «За 30 дней» — окно данных, а не срок;
   * диапазон и включённость, в том числе по тем же числам в другом месте документа;
   * единичность: от 3 обязательств, только ФТ и НФТ;
   * уровень документа для `appropriate`.
2. **Модель**: инструкция с таблицей критериев, рубрикой и ролями из TOML, данные пункта (роль, раздел, соседи) и сигналы правил для подтверждения или опровержения.
3. **Слияние**:
   * объективная находка правила (прочерк, заглушка) переживает pass модели, эвристическую модель может отклонить с обоснованием;
   * issue без буквальной цитаты превращается в unknown и `quote_not_found`;
   * общий pass («Соответствует.») становится unknown;
   * если ответа нет, ставится unknown;
   * числа в правке, которых нет в документе, превращаются в `<уточнить у владельца: …?>` и попадают в вопрос.
4. **Калибровка**:
   * правила не дают critical (`rules_max = major`);
   * critical от модели требует `blocks`, `scenario`, `impact` и `blocked_decision`, иначе становится major (то же требует движок);
   * `blocks = none` ограничивает серьёзность значением minor;
   * пределы `[[severity.cap]]` действуют и на модель: Prod/Swagger — не выше major.

## Команды и результаты (выполнено в этой среде, Linux)
```bash
python3.11 -m venv .venv && .venv/bin/pip install -e ".[dev,pdf]"
.venv/bin/python -m pytest tests/p05          # 59 passed
.venv/bin/python -m pytest tests              # 189 passed, 1 skipped, 1 failed — см. «Открытые вопросы», п. 1
python3 -m pytest tests/p05 tests/contract    # системный 3.13 Debian: 87 passed, 1 skipped (колесо не собирается пропатченным setuptools 68)
python -m bcc_review tests/integration/fixtures/bcc_requirements.md report.md --offline-lint
```

Сквозной прогон движка (`--offline-lint`, резервные читатель и нарезка):
* `run.modules.review_individual = team:…`, `validate(report)` проходит, `evidence_errors(report) == []`;
* 44 пункта резервной нарезки, 4 замечания №05, все `confirmed`, `anchor_status: supported`, `meaning_status: deterministic`:
  * «и далее» — `complete`/`incomplete`, major;
  * Ф-2 — `singular`, minor;
  * `Prod: —` — minor;
  * `Swagger | —` — minor.

Прогон правил на выданном документе (`tests/p05/fixtures/bcc_case.md`, SHA-256 `e7dae55e…`, нарезка 27 пунктов в `docfix.BCC_REQS`):
* 243 записи checks, 5 кандидатур, ни одной critical:
  * Ф-2 — 4 обязательства (`singular`/`non_singular`, minor);
  * «заполняются тестировщиками» (`complete`/`placeholder`, minor);
  * `Prod: —` (minor);
  * `Swagger | —` (minor);
  * «400, 401 и далее» (`complete`/`incomplete`, major).
* Содержательный pass:
  * Ф-1 (тест 999 / 1 000 / 1 000 000 / 1 000 001);
  * НФТ («в течение минуты» + «после получения события»);
  * `amount` 1 000–1 000 000 (включённость взята из Ф-1).
* Без ложных срабатываний: прочерки в колонке DB field, строки критериев приёмки, «Целое число тенге, обе границы включены», «REST» внутри «…».
* Цель «в момент покупки» получает unknown с вопросом. Строка чек-листа получает na.
* Инструкция `task` — около 12 тыс. символов, запрошено 101 блок контекста.

## Проверенные случаи (доказательства)
1. «Операция выполняется быстро» → `verifiable` issue major: правка без числа, вопрос о сроке, `blocks: development, testing`. «не позднее 60 секунд после получения события процессинга» → pass с таймером, границей и точкой отсчёта (`test_timing_pair.py`).
2. «Быстрый перевод» в заголовке, названии экрана и кнопке не даёт дефекта. «Перевод выполняется быстро» даёт дефект, подсказка указывает только на блок обязательства (`test_context_rules.py`).
3. Подставная модель (`test_model.py`):
   * у всех требований 9 записей checks;
   * корректное требование без дефектов, с содержательным pass;
   * выдуманная цитата даёт unknown;
   * пропущенный ответ даёт unknown и `missing_answer`;
   * `BudgetExhausted` не роняет этап.
4. Prod URL (`test_severity_prod.py`):
   * по умолчанию minor (`placeholder.release-field`);
   * major, если документ требует приёмку на Prod;
   * critical от модели урезается до major;
   * изменённое правило в тестовом TOML одновременно меняет серьёзность находки, `task` и `criteria_tag` в payload и meta.
5. Стык (`test_contract.py`):
   * `contracts.validate` проходят Document, Requirement, Check, Candidate и Warning в обоих режимах;
   * схема ответа удовлетворяет ограничениям structured outputs;
   * у critical есть `impact` и `blocked_decision`.

Самый рискованный выбор — словарь размытых слов. На 8 строках наивный поиск по словарю дал 4 ложных срабатывания, контекстные правила — 0 при том же recall (`test_naive_regex_vs_context_aware_rules`).

## Открытые вопросы к контракту и движку (для Max)
1. **`tests/integration/fixtures/mock_bcc.json`: `"individual": {"requirements": []}`** — это формат резервного модуля. С модулем №05 ответ не проходит схему (`invalid_output`), не кэшируется, и `test_cache_hit_on_rerun_and_miss_on_model_change` видит 6 повторных вызовов. Исправление — `"individual": {"results": []}` или удалить ключ, тогда mock синтезирует ответ по схеме. Проверено: с этой правкой `tests/integration` даёт 31 passed. Файл в зоне Max, в ветке №05 не менялся.
2. Слот `rules` (`runtime/fallback/rules.py`) в `091e504` отсутствует, этап `rules` в паспорте помечен failed. Детерминированные правила №05 работают внутри `review_individual(ask=None)` и дают находки и в `--offline-lint`.
3. `verify_candidates` перезаписывает `notes` кандидата, поэтому `calibration` №05 (почему изменилась серьёзность) до `Finding.notes` не доходит. Стоит дописывать `c.get("calibration", [])` в `notes`.
* `Check.finding_ids`: №05 отдаёт `candidate_refs` (`IND-…`), потому что `Finding.id` назначает движок. Нужна замена при сборке Report.
* `Candidate.blocks`: в типе `Candidate` поля нет, в `Finding` оно есть. №05 отдаёт его дополнительно (`additionalProperties` разрешает).
* Читатель №01 снимает `**` и маркеры списка, но формат строки таблицы в контракте не зафиксирован. Правила №05 работают и с ` | `, и с исходным Markdown (проверено тестами в обоих видах).

## Открытые зависимости
* Реальный прогон на Gemini или Anthropic не выполнялся (ключа нет). Его проводят Max и №18. `batch_size` при необходимости меняется в TOML. Сквозной путь с моделью проверен только на подставном транспорте и mock-провайдере движка.
* Сайт bcchubagents.mnu.kz из среды недоступен (DNS). Веса критериев жюри взяты из брифа.

## Кому и что
* **№04**: `Requirement.kind` (`functional`, `nonfunctional`, `acceptance`, `goal`, `api`, …) точнее заголовков: таблица `[context.kind_alias]`. `evidence` со `start`/`end` сужает спаны до пункта.
* **№07**: `hints[].quote` и `context` — буквальные подстроки блока.
* **Max**: объединять по `root_cause` и `ref`; `calibration` — для `Finding.notes`; `meta` — для `run.stages`.
* **№06**: `load_criteria().for_scope("set")`, `render_severity()` и та же политика critical.
* **№10**: `checklist` CL01–CL14 (`match` + связи с кодами критериев). Строки чек-листа во входе №05 помечает na и `template_rows`.
* **№17**: `load_criteria().to_dict()` для раздела «Методика»; `short` (`И3`) — метка для таблиц.
