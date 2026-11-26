# №06 · Межраздельные противоречия и покрытие приёмкой — передача

Файлы направления: `src/bcc_review/analysis/cross.py`, `src/bcc_review/analysis/facts.py`,
`src/bcc_review/prompts/cross.{pairs.md,coverage.md,schema.json}`, `tests/p06/`. Чужие файлы не менялись.
Ветка `claude/epic-mccarthy-uhlsri` (назначена платформой вместо `bcc/p06-cross`), влита поверх
`bcc/integration` @ `2821989`. В интеграции пока лежит первая версия №06 (`ecaa84f`): все пункты таблицы
«Что движок выравнивает» для №06 закрыты начиная с `f1cd2d1`:
* payload `{task, input, context}`;
* `Fact.evidence` — список, `subject` — строка;
* коды `set_consistent`/`set_complete`, виды из `FINDING_KINDS`;
* `AskError` поднимается, если модель не ответила ни разу.

**Имена этапов изменились:** `cross#pairs` и `cross#coverage` вместо `cross.pairs`/`cross.coverage`.
`StageStats` сводит их в этап `cross`. Сценарий mock для №15 нужно писать под новые ключи.

## Сквозной сценарий через настоящий Asker (`tests/p06/test_p06_asker_cashback.py`)

Одна точка входа: `engine.read_document` → нарезка движка → `review_set(doc, reqs, Asker(...))`. Asker
движка (контекст, кэш, бюджет, проверка схемы, `StageStats`) работает поверх `RecordedTransport`
(`tests/p06/p06_helpers.py`), который воспроизводит кассету `fixtures/cassette_cashback.json` с
имитированными ответами и записывает каждый физический запрос.

1. `cashback_two_dates.md` — **конфликт.** Правило нашла программа, модель подтвердила его через Asker,
   дубля нет. Две точные опоры:
   * `b0005[7:89]`, строка 7 (КЭШ-2): «Расчётный месяц кэшбэка определяется по дате совершения покупки по времени Астаны.»
   * `b0007[58:141]`, строка 10 (требования к интеграции): «Расчётный месяц кэшбэка определяется по дате проведения операции по времени Астаны.»
   * Общий объект — «Расчётный месяц кэшбэка». `blocked_decision`: по какой дате относить операцию к месяцу.
2. `cashback_by_operation.md` — **конфликта нет.** «Для покупок …» и «Для возвратов …» при разных условиях
   совместимы. «Наивный» ответ модели отклонён проверкой ограничений (тип операции). Строка приёмки о
   возврате проверена по правилу для возвратов.
3. `cashback_missing_rule.md` — **пропуск правила** (`omission`, `set_complete`).
   * Перечень просмотренных разделов и строки 6–13; что искали.
   * Вопрос с моментами «31 марта в 23:58» / «1 апреля в 00:03» и ставками 1 % / 2 %.
   * Все опоры — подстроки документа. Выдуманную отрицательную цитату модели отклонил №07 (`rejected=1`).

Физических вызовов двойника — по 2 на документ (`cross#pairs` + `cross#coverage`), всего 6. Повтор с кэшем
даёт 0 физических вызовов и `cache_hits=2`. Тот же сценарий 1 проходит через `run_review`: отчёт v1 валиден,
находка конфликта с двумя опорами (строки 7 и 10), этап `cross`: `ok`, `calls=2`.

```bash
python -m pytest tests/p06 -q
```

```bash
python tests/p06/demo_asker_cashback.py
```
Вывод сохранён в `tests/p06/sample/asker_cashback.txt`.

## Протокол (как вызывает движок)

```python
review_set(document, requirements, ask=None, *, fact_hints=None, resolve=None, max_pairs=60, pairs_per_call=30)
# -> {facts, coverage, candidates, warnings,                                  # контракт
#     coverage_summary, comparisons, evidence_audit, stats, acceptance}       # пояснения для отчёта
reconcile_facts(document, fact_hints=None, *, resolve=None)
# -> {facts, candidates, comparisons, endpoints, warnings, evidence_audit}
```

* **ask.** Два подэтапа, `cross#pairs` (пакеты по 30 пар) и `cross#coverage` (1 вызов). `StageStats` сводит
  их в этап `cross`. Payload — `{task, input, context:{mode:"auto", block_ids}}`, текст документа прикладывает
  движок. Схемы ответа в `prompts/cross.schema.json` строгие (`additionalProperties:false`, полный `required`,
  без `$ref`); отсутствующее значение — `""` или `[]`.
* **Ошибки модели.** Если не удался ни один вызов (`AskError`/`BudgetExhausted`), модуль поднимает ошибку.
  Движок отмечает `cross: failed` и перезапускает модуль с `ask=None`, результат правил сохраняется.
  Если не удалась часть вызовов, модуль возвращает частичный результат: `stats.status="partial"`,
  `stats.llm_failed`, причины в `warnings`. **Max:** движок сейчас ставит этапу `ok` — предлагаю читать
  `out["stats"]["status"]`.
* **Цитаты** проверяет `resolve_hint` №07 (`index=DocumentIndex.of(doc)`, при `missing` — повтор с
  `relocate=True`). Учёт ведётся в `evidence_audit`: `checked`, `confirmed`, `ambiguous`, `rejected`,
  `relocated`, `note`. Локальный резолвер — запасной.
* **fact_hints №04** принимаются в формате инвентаря: `{id, field, direction (request|response|business), type,
  value, unit, range, condition, required, size, values, db_field, hints[], evidence[], req_ids}`. Опоры —
  готовые `evidence[]` (с проверкой инварианта), иначе `hints[]` через №07. Подсказка дополняет пустые слоты
  факта из разбора. Новый факт создаётся, только если есть поле, значение или ограниченный диапазон.
  На кейсе 14 подсказок дали 0 отклонений и 1 новый факт («уведомление выключено»).

### Кандидаты (Candidate v1 + поля №06)

| subkind | kind / criterion | когда | ключевые поля |
| :--- | :--- | :--- | :--- |
| `conflict` | conflict / set_consistent | один вход удовлетворяет обоим предусловиям, исходы несовместимы, обе опоры найдены | `witness` = WitnessDraft (`input` — строка, `outcome_a/b`, `hint_a/b`) + `evidence_a/b`, `input_detail{description, document_data[{name,value,evidence}], illustrative[{name,value,why}]}`, `outcome_*_value`; `cause`, `checks`, `slots`, `acceptance_ids` |
| `missing_contract` | omission / set_complete | обещана операция через API, а метода нет | `inspected_block_ids`, `inspected_scope{sections, span}`, `searched_for`, `found`, `promise` |
| `question` | ambiguity / set_consistent | общий вход не построен — для №08 | `question`, `condition_a/b`, `reason`, `needs` |

У каждого кандидата есть `impact`, `blocked_decision`, `recommendation`, `source` (rules|llm), `stage:"cross"`,
`origin`. Переопределение в `criteria.toml`: секции `[cross.<subkind>]` с ключами `criterion` и `severity`.

### Факты и покрытие

* `Fact` = `{id, subject, field, scope, direction, type, value, range, unit, condition, evidence:[Evidence], req_ids}`
  + `binding`, `aliases`, `cells` (опора каждого слота), `value_minor` / `range.*_minor` (тиыны, int), `enriched_by`.
* `Coverage` = `{req_id, obligation_id, obligation, acceptance_ids, status, explanation, hints, evidence, branches,
  branches_checked, links}`.
  * Обязательство — предложение требования из разделов правил, интеграции, данных, НФТ, UI и логики метода.
    При атомарной нарезке №04 (одно предложение — одно требование) берётся `evidence`-спан требования.
  * Контракт API, примеры, паспортные таблицы и схемы не входят в знаменатель:
    `coverage_summary.excluded` с причиной.
  * Строки приёмки №04 — требования (`R-009…`), они идут в `acceptance_ids`, а при конфликте — и в `req_ids`.
  * `covered` — модель подтвердила все ветви, и приёмка сама не в противоречии.
  * `partial` — часть ветвей или только лексическая связь (без модели).
  * `conflict` — подтверждённый witness.
  * `uncovered` — связей нет, документ прочитан полностью.
  * `unknown` — связей нет, но в `document.warnings` есть код из `PARTIAL_READ_CODES` или разрыв в `loc.page`.

## Команды и результаты (выполнено в этой среде)

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[all,dev]"
```

HANDOFF интеграции советует запускать тесты по папкам. На `bcc/integration` @ `2821989` + №06, Python 3.11.18:

```bash
.venv/bin/python -m pytest tests/p06 -q
```
**56 passed**.

```bash
.venv/bin/python -m pytest tests/contract -q
```
**29 passed**.

```bash
.venv/bin/python -m pytest tests/integration -q
```
**138 passed**.

```bash
python3 -m pytest tests/p06 -q
```
Python 3.13.18: **55 passed, 1 skipped** (без PyMuPDF пропускается паритет MD/PDF).

```bash
ruff check --select E9,F --target-version py311 src/bcc_review/analysis/cross.py src/bcc_review/analysis/facts.py tests/p06
```
Замечаний нет.

```bash
.venv/bin/python tests/p06/demo_case.py tests/p06/fixtures/case_ab.md OUT
```
Читатель и нарезка движка → `review_set` → JSON + Markdown. С флагом `--scripted` работает подставной
транспорт; это не ответ модели.

```text
case_ab-rules:              question=1 conflict=1 missing_contract=1; coverage 0/25 covered, 1 conflict, 9 partial, 15 uncovered
bcc_requirements-pdf-rules: question=1 conflict=1 missing_contract=1; coverage 0/25 covered, 1 conflict, 9 partial, 15 uncovered
case_ab-scripted:           conflict=3 missing_contract=1;            coverage 0/25 covered, 1 conflict, 2 partial, 22 uncovered; llm_calls=3
```
Образцы таблицы покрытия с доказательствами — `tests/p06/sample/case_ab-rules.md` и `case_ab-scripted.md`.

## Проверенные случаи (tests/p06, 56 тестов)

1. **Граница периода, независимый сюжет** (кешбэк 1 % → 2 %).
   * Покупка 30.06 в 23:55 проведена 01.07 в 00:05; цитаты «…1 %…» и «…2 % — 200 ₸» дают разные исходы
     одного события.
   * Пояс UTC+5 помечен как иллюстративное допущение; строка с покупкой 1 июля совместима.
   * Два правила привязки к разным событиям тоже дают конфликт.
2. **Негативный контроль** (подтверждённый и отменённый платёж): без модели конфликта нет.
   * «Наивный» конфликт от модели отклоняют непересекающиеся ограничения.
   * Без ограничений он остаётся максимум вопросом.
3. **Покрытие.** Л-1 — одно обязательство covered, другое conflict, итог covered 1/3.
   Без модели covered не появляется; при пропущенной стр. 3 статус unknown, положительные выводы сохраняются.
4. **Три пары.** Конфликт дают только разные границы, минимальный пример 300 001 ₸.
   * Совместимы: 1 ₸ = 100 тиын, integer→string с оговоркой, 200-ERROR рядом с 401 «не передан токен».
   * Тип без оговорки уходит вопросом minor.
5. **Кейс A+B** (три загрузчика): К1 по строке 64; К4 — обещание в строке 52, охват 95–197/198;
   200-ERROR/400 — вопрос.
   * Подставная модель подтверждает К2 и К3 программой.
   * Выдуманная цитата отклоняется; сбой провайдера даёт partial.
6. **Стык.**
   * `validate` и `resolve_candidate` (supported) на нарезке №04.
   * `run_review` офлайн и через mock: К2 доходит до `findings`.
   * Модель не ответила → `cross: failed`, прогон partial; паритет Markdown/PDF.
7. **Ложные срабатывания.**
   * «push через сервис» не считается обещанием API.
   * Неоднозначная метка времени не даёт конфликта (тест падает на прежней логике).
   * Мягкие переносы PDF не режут обязательства: было 37 вместо 25.
   * Таблица приёмки одним требованием получает уникальные id.

## Кому что

* **Max.** Резерв `review_set` в `tests/integration/test_engine.py` уже закреплён (`SEMANTIC_FALLBACK`), и это
  правильно: их сценарий `mock_bcc.json["cross"]` написан под схему резерва. Если нужен mock-прогон с №06,
  добавьте ключи `cross#pairs` и `cross#coverage`, пример в `test_p06_integration._k2_script`.
  Ещё прошу читать `stats.status` у `cross`.
* **№11 и №17.** `tests/p11/test_anthropic_success.py` импортирует `from conftest import FIXTURES`, а в полном
  прогоне модуль `conftest` уже занят `tests/p17/conftest.py`. №06 обходит это модулем `tests/p06/p06_helpers.py`;
  у вас поможет то же самое или `__init__.py` в каталогах тестов.
* **№10.** `coverage` + `coverage_summary.by_requirement`; помнить, что `linked` ≠ `covered`.
* **№07.** Опоры witness: `hint_a/hint_b`, `evidence_a/b`, `input_detail.document_data[].evidence`.
* **№08.** Кандидаты `subkind="question"` (`kind="ambiguity"`) с полями `question`, `condition_a/b`, `reason`.
* **№04.** Ваш формат `fact_hints` принят как есть. При атомарной нарезке нужен `evidence`-спан у каждого
  требования, он уже есть.

## Открытые зависимости

* Реальный прогон `ask` на Gemini или Anthropic ключом команды (Max и №18). Проверены только mock движка,
  подставной транспорт и строгие схемы через `jsonschema`.
* При атомарной нарезке получается 230 пар, к модели уходят 60 с наибольшим весом (2 вызова). Если бюджет
  позволит, `max_pairs` можно поднять; пары правило×приёмка и правило×правило идут первыми.
