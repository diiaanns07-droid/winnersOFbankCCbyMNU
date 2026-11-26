# №05 — проверка отдельного требования: передача

Ветка: `claude/practical-ride-4z65ch` (назначена платформой вместо `bcc/p05-individual`). В неё влит
`bcc/integration` @ `6a6c503` (контракт v1 из `431f76d`, движок, срезы 01–17). Точка входа совпадает с таблицей в
`contracts/HANDOFF.md`. Движок сам выбирает модуль №05: `run.modules.review_individual = team:bcc_review.analysis.individual:review_individual`.

В `bcc/integration @ 6a6c503` влита версия №05 `f91f296`. Второго прохода (область действия определения, `4930afa`) там
ещё нет: его нужно влить из этой ветки. Зона №05 в интеграции поверх `f91f296` не менялась, конфликтов нет.

## Что входит
| Файл | Назначение |
| :--- | :--- |
| `src/bcc_review/criteria.toml` | единый конфиг. Критерии `necessary…conforming` (И1–И9) и `set_complete…traceable` (Н1–Н8) с русскими определениями, источником ISO/IEC/IEEE 29148:2018 или IEEE 830-1998, применимостью (`not_for`), видом находки (`kind`) и связями с 14 пунктами банковского чек-листа. Ещё рубрика critical/major/minor, политика и правила серьёзности, пределы, роли разделов, `kind_alias` для `Requirement.kind`, уровни документа, словарь неоперациональных слов, параметры этапа |
| `src/bcc_review/criteria.py` | `load_criteria(path=None)`: проверка схемы, отпечаток `tag`/`fingerprint`, `resolve()` (код, `И3`, русское имя), роль и уровень, `rule_severity()`, `cap_for()`, `render_*()` для промптов, `to_dict()` для отчёта |
| `src/bcc_review/analysis/individual.py` | `review_individual(document, requirements, ask=None, *, criteria=None)`, `build_prompt`, `response_schema`, `prompt_version` |
| `src/bcc_review/prompts/individual.md` | промпт `individual/1.2.0`: инструкция этапа (`task`), плейсхолдеры `{{…}}` из TOML, правило 14 об области действия определения. Версия = front matter + SHA-256 файла |
| `src/bcc_review/prompts/individual.schema.json` | строгая схема ответа: `additionalProperties: false`, полный `required`, без `minLength`/`$ref`. Перечни `criterion` и `kind` подставляются из TOML и `contracts.FINDING_KINDS` |
| `tests/p05/` | 74 теста: четыре доказательства, область действия определения (`test_scope.py`, три ТЗ `fixtures/transfer_*.md`), ложные срабатывания, модельный режим, настоящий Asker с кэшем (`test_asker_cache.py`), кейс BCC, стык с контрактом и движком, упаковка |

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
* `warnings` (`Warning`): `{code: "individual.<…>", message, stage}`. Коды: `missing_answer`, `quote_not_found`, `ask_failed`, `generic_pass`, `bad_check`, `unexpected_req`, `template_rows`, `no_blocks`, `unknown_block`, `na_overridden`, `out_of_scope_basis`.
* `meta`: `{stage, mode: rules_only|rules_plus_llm, prompt_version, criteria_version, criteria_fingerprint, criteria_tag, calls, requirements}`.
* `ask("individual#N", payload, schema)` — имя этапа на каждый пакет, как у резерва (кэш и трасса различают пакеты):
  * `payload = {task, input, context}`;
  * `input` = `{prompt_version, criteria_tag, criteria_fingerprint, req_ids, requirements:[{req_id, source_id, role, level, section, applicable, not_applicable, block_ids, text, neighbors, definitions:{scope, applicable, other_scope}, rule_signals}]}`;
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
   * диапазон и включённость, в том числе по тем же числам в области действия пункта (см. ниже);
   * отсылка к неназванному значению («в установленный срок», «установленный лимит»): проверяемо, только если значение определено в области действия пункта;
   * единичность: от 3 обязательств, только ФТ и НФТ;
   * уровень документа для `appropriate`.
2. **Модель**: инструкция с таблицей критериев, рубрикой и ролями из TOML, данные пункта (роль, раздел, соседи, применимые и чужие определения) и сигналы правил для подтверждения или опровержения.
3. **Слияние**:
   * объективная находка правила (прочерк, заглушка) переживает pass модели, эвристическую модель может отклонить с обоснованием;
   * issue без буквальной цитаты превращается в unknown и `quote_not_found`;
   * общий pass («Соответствует.») становится unknown;
   * если ответа нет, ставится unknown;
   * числа в правке, которых нет в пункте и его области действия, превращаются в `<уточнить у владельца: …?>` и попадают в вопрос;
   * pass по `verifiable`, `unambiguous`, `complete`, обоснованный числом из чужой области, не принимается: `out_of_scope_basis`, статус берётся из правил или ставится unknown с вопросом.
4. **Калибровка**:
   * правила не дают critical (`rules_max = major`);
   * critical от модели требует `blocks`, `scenario`, `impact` и `blocked_decision`, иначе становится major (то же требует движок);
   * `blocks = none` ограничивает серьёзность значением minor;
   * пределы `[[severity.cap]]` действуют и на модель: Prod/Swagger — не выше major.

## Область действия определения (второй проход)
Число, срок или порог в другом месте документа делает пункт проверяемым, только если определение действует на этот пункт:
1. **явная ссылка** — ID правила («по правилу ОП-1»), «раздел «…»», «часть X», в самом пункте или во вводном абзаце его части («Дочерний документ части A»);
2. **тот же раздел** — общий родитель пункта (для `Документ › Часть › Подраздел` — `Документ › Часть`) и тот же предмет;
3. **общий раздел** — заголовок из `[rules.scope].general` (общие правила, термины и определения, глоссарий) и тот же предмет.

Предмет сравнивается по основам слов, стоп-основы лежат в `[context.scope].stop_stems`. Определение из раздела про другой продукт область не расширяет. Оно попадает в `other_scope`, его называют в основании оценки и в вопросе владельцу, а его число в правке стоит только внутри маркера `<уточнить у владельца: …?>`. Правила области действия используются в отсылках, в заимствовании включённости диапазона и в проверке pass модели.

Три ТЗ про подтверждение перевода, `criteria 1.1.0`, `rules_only`:

| Вход | Критерий | Статус | Основание |
| :--- | :--- | :--- | :--- |
| `transfer_linked.md` ПР-1 «…в установленный срок по правилу ОП-1» | verifiable | pass | определение ОП-1 «не позднее 120 секунд с момента отправки кода» [b0003], явная ссылка «ОП-1» |
| `transfer_other_product.md` ПР-1 «…в установленный срок» | verifiable | issue, major | срок не определён ни в пункте, ни в разделе «Переводы между картами», ссылки нет; «не позднее 300 секунд…» [b0004] есть только в «Кредитные карты › Подтверждение платежа». Вопрос: действует ли срок из КК-1 |
| `transfer_undefined.md` ПР-1 «…в установленный срок» | verifiable | issue, major | срок не определён ни в пункте, ни в разделе, ни в общих правилах. Вопрос: какой срок и от какого события |
| ПР-2 «кнопка «Подтвердить быстро»» (во всех трёх) | verifiable | unknown, без замечаний | слово «быстро» стоит внутри названия «Подтвердить быстро» и обязательством не считается |

Заблокированное решение по ПР-1 (ТЗ 2 и 3): «Разработка: какой тайм-аут и от какого события заложить для «Клиент подтверждает перевод»; приёмка: при каком времени тест ожидает успех, а при каком — отказ». `blocks: development, testing`.

Воспроизведение на прежнем коде (`f91f296` + `6be9e97`):
* правила давали всем трём ТЗ одно и то же: `verifiable → unknown`, «Без модели не оценивается»;
* при ответе модели «срок задан: не позднее 300 секунд…» для ТЗ 2 старый код принимал `pass` на числе из раздела «Кредитные карты»;
* «включительно» заимствовалось из диапазона другого продукта.

После правки: `tests/p05/test_scope.py` (13 тестов) зелёный, ошибочный pass модели отклоняется с `out_of_scope_basis`.

## Команды и результаты (выполнено в этой среде, Linux)
```bash
python3.11 -m venv .venv && .venv/bin/pip install -e ".[dev,pdf,anthropic]"
.venv/bin/python -m pytest tests/p05 -q       # 74 passed
.venv/bin/python -m pytest tests -q           # ветка + 6a6c503: 1181 passed, 14 skipped, 13 failed — все 13 падают и на чистой bcc/integration @ 6a6c503 (там 14, плюс нестабильный p15 restart); №05 среди причин нет
.venv/bin/python -m pytest tests/p05/test_scope.py tests/p05/test_asker_cache.py -q
python -m bcc_review tests/p05/fixtures/transfer_other_product.md report.md --offline-lint
```

Стык в отдельных копиях (worktree):
* `bcc/integration @ 6be9e97` с наложенными файлами №05 — 622 passed, 18 skipped, 1 failed (p11, как и без №05);
* чистая `6a6c503` против ветки (`6a6c503` + второй проход) — одинаковый список падений соседних модулей. Причины: схема `Warning` у №02; `Document` объектом вместо `dict` у №04 и №08; тексты отчётов у №09 и №15; выделения в PDF у №14; режим оценки у №16; `entry_point` у №11.

Сквозной прогон движка на трёх ТЗ (`--offline-lint`, ветка с `6a6c503`). Участвовали модули команды: `read_text` №01, `build_inventory` №04, `load_criteria` и `review_individual` №05, `review_set` №06, `resolve_candidate`/`resolve_hint` №07, `build_questions` №08; `build_bank_pack` пока резервный. Плюс правила движка `runtime/fallback/rules.py`. Результат: ТЗ 1 — 0 замечаний; ТЗ 2 и ТЗ 3 — по одному `verifiable major confirmed` (`rule_id: vague.reference`). Кнопка не дала замечаний ни у одного модуля.

Кэш (`test_asker_cache.py`). Участвуют настоящие `runtime.asker.Asker`, `runtime.mock.MockAdapter`, `runtime.core.Cache/Budget/StageStats/Tracer` и `runtime.context.ContextBuilder`; ответ `individual` валиден по схеме №05:
* вызов 1: `adapter.calls = ['individual#1']`, `physical = 1`, `cache_hits = 0`;
* вызов 2: `adapter.calls = []`, `physical = 0`, `cache_hits = 1`, checks и candidates совпадают.

То же через `engine.run_review` дважды с одним `cache_dir`: прогон 1 — `physical = 5`; прогон 2 — `physical = 0`, `cache_hits = 5`, этап `individual` в статусе `ok`, `cache_hits = 1`.

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
1. **Общая mock-фикстура** (`tests/integration/fixtures/mock_bcc.json`, `"individual": {"requirements": []}`). Это по-прежнему формат резервного модуля: для схемы №05 ответ невалиден (`'requirements' was unexpected`). На `6be9e97` она интеграционный тест не ломает, потому что `test_engine.py` включает `BCC_FORCE_FALLBACK`, а `test_team_pipeline.py` работает без сценария. Diff не нужен: одна запись не может быть валидна сразу для двух схем этапа `individual#N`. Путь кэша с модулем команды покрыт `tests/p05/test_asker_cache.py`. Если понадобится сценарий конвейера команды, нужен отдельный файл с ответом `{"results": [...]}`.
2. `verify_candidates` перезаписывает `notes` кандидата, поэтому `calibration` №05 (почему изменилась серьёзность) до `Finding.notes` не доходит. Стоит дописывать `c.get("calibration", [])` в `notes`.
3. Кандидат, слитый из находки правила и ответа модели, приходит с `source: llm+rules` и уходит к критику. Без оценки критика (mock) он становится `needs_review`, хотя цитата и правило объективны.
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
