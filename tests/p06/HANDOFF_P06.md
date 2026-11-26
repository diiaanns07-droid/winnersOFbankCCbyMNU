# №06 · Межраздельные противоречия и покрытие приёмкой — передача

Файлы направления: `src/bcc_review/analysis/cross.py`, `src/bcc_review/analysis/facts.py`,
`src/bcc_review/prompts/cross.{pairs.md,coverage.md,schema.json}`, `tests/p06/`. Чужие файлы не менялись.
Ветка влита поверх `bcc/integration` @ `091e504`; контракт v1 — `431f76d`. Стык проверен:
* выход модуля проходит `contracts.validate` (Candidate, Fact, Coverage, EvidenceAudit);
* кандидаты принимает `resolve_candidate` №07/резерва;
* `run_review` подключает модуль как `team:bcc_review.analysis.cross:review_set`, отчёт проходит
  `validate(report)` и `evidence_errors(report) == []`.

## Протокол (как вызывает движок)

```python
review_set(document, requirements, ask=None, *, fact_hints=None, resolve=None, max_pairs=60, pairs_per_call=30)
# -> {facts, coverage, candidates, warnings,                                  # контракт
#     coverage_summary, comparisons, evidence_audit, stats, acceptance}       # пояснения для отчёта
reconcile_facts(document, fact_hints=None, *, resolve=None)
# -> {facts, candidates, comparisons, endpoints, warnings, evidence_audit}
```

* **ask.** Два подэтапа, `cross#pairs` (пакеты по 30 пар) и `cross#coverage` (1 вызов). `StageStats` сводит
  их в этап `cross` паспорта. Payload — `{task, input, context:{mode:"auto", block_ids}}`, текст документа
  прикладывает движок. Схемы ответов лежат в `prompts/cross.schema.json`: строгие (`additionalProperties:false`,
  полный `required`, без `$ref`), отсутствующее значение — `""` или `[]`.
* **Ошибки модели.** Если не удался ни один вызов и пришёл `AskError`/`BudgetExhausted`, модуль поднимает его.
  Движок отмечает `cross: failed` и перезапускает модуль с `ask=None`, результат правил сохраняется.
  Если не удалась часть вызовов, модуль возвращает частичный результат: `stats.status="partial"`,
  `stats.llm_failed` и причины в `warnings`. **Max:** сейчас движок в этом случае ставит этапу `ok`.
  Предлагаю читать `out["stats"]["status"]`.
* **Цитаты.** Проверяет №07: `bcc_review.analysis.evidence:resolve_hint`, иначе резерв движка. Параметр
  `resolve` не нужен. Ответ `{status, evidence}` учитывается в `evidence_audit`
  (`checked`, `confirmed`, `ambiguous`, `rejected`, `relocated`, `note`). При `missing` и указанном блоке
  выполняется повтор с `relocate=True`. Локальный резолвер — запасной, с тем же инвариантом.
* **fact_hints (№04).** Список или `{"facts": [...]}` элементов
  `{field, subject?, direction?, type?, value?, range?, unit?, condition?, hint:{block_id, quote}}`.
  Подсказка заполняет пустые слоты факта из таблиц. Если она расходится с разбором, пишется предупреждение,
  разбор остаётся.

### Кандидаты (Candidate v1 + поля №06)

| subkind | kind / criterion | когда | ключевые поля |
| :--- | :--- | :--- | :--- |
| `conflict` | conflict / set_consistent | один вход удовлетворяет обоим предусловиям, исходы несовместимы, обе опоры найдены | `witness` = WitnessDraft (`input` — строка, `outcome_a/b`, `hint_a/b`) + `evidence_a/b`, `input_detail{description, document_data[{name,value,evidence}], illustrative[{name,value,why}]}`, `outcome_*_value`; `cause`, `checks`, `slots`, `acceptance_ids` |
| `missing_contract` | omission / set_complete | обещана операция через API, а метода нет | `inspected_block_ids`, `inspected_scope{sections, span}`, `searched_for`, `found`, `promise` |
| `question` | ambiguity / set_consistent | общий вход не построен — для №08 | `question`, `condition_a/b`, `reason`, `needs` |

У каждого кандидата есть `impact`, `blocked_decision`, `recommendation`, `source` (rules|llm), `stage:"cross"`
и `origin`. `criteria.toml`: значения по умолчанию можно переопределить секциями `[cross.<subkind>]`
с ключами `criterion` и `severity`.

### Факты и покрытие

* `Fact` = `{id, subject, field, scope, direction, type, value, range, unit, condition, evidence:[Evidence], req_ids}`
  + `binding`, `aliases`, `cells` (опора каждого слота), `value_minor` / `range.*_minor` (тиыны, int).
* `Coverage` = `{req_id, obligation_id, obligation, acceptance_ids, status, explanation, hints, evidence, branches,
  branches_checked, links}`.
  * Обязательство — предложение требования из разделов правил, интеграции, данных, НФТ, UI и логики метода.
  * Строки контракта API, примеры JSON, паспортные таблицы и схемы в знаменатель не входят:
    `coverage_summary.excluded` с причиной.
  * В нарезке Max строки приёмки — тоже требования (`R-14…`), их id попадают в `acceptance_ids` и в `req_ids` конфликта.
  * `covered` — модель подтвердила все ветви, и строка приёмки сама не в противоречии.
  * `partial` — проверена часть ветвей или есть только лексическая связь (без модели).
  * `conflict` — подтверждённый witness.
  * `uncovered` — связей нет, документ прочитан полностью.
  * `unknown` — связей нет, но в `document.warnings` есть код из `PARTIAL_READ_CODES` или в `loc.page` разрыв.

## Команды и результаты (выполнено в этой среде)

```bash
python3 -m pytest tests/p06 tests/contract -p no:cacheprovider
```
Python 3.13.18: **76 passed, 1 skipped**. Пропущен паритет MD/PDF: в системном Python нет PyMuPDF.

```bash
uv venv --python /usr/bin/python3.11 .venv
```

```bash
VIRTUAL_ENV=.venv uv pip install -e ".[dev]" "pymupdf>=1.24"
```

```bash
.venv/bin/python -m pytest -p no:cacheprovider
```
Python 3.11.18, весь репозиторий: **13 failed, 166 passed, 1 skipped**. Все 13 — тесты Max, см. ниже.

```bash
git apply tests/p06/patches/integration-pin-fallback.patch && .venv/bin/python -m pytest -p no:cacheprovider
```
С патчем для Max: **179 passed, 1 skipped**.

```bash
ruff check --select E9,F --target-version py311 src/bcc_review/analysis tests/p06
```
Замечаний нет.

```bash
.venv/bin/python tests/p06/demo_case.py tests/p06/fixtures/case_ab.md OUT
```
Сквозной прогон: читатель и нарезка движка → `review_set` → JSON + Markdown. Флаг `--scripted`
подключает подставной транспорт; это не ответ модели.

```text
case_ab-rules:              question=1 conflict=1 missing_contract=1; coverage 0/25 covered, 1 conflict, 9 partial, 15 uncovered
bcc_requirements-pdf-rules: question=1 conflict=1 missing_contract=1; coverage 0/25 covered, 1 conflict, 9 partial, 15 uncovered
case_ab-scripted:           conflict=3 missing_contract=1;            coverage 0/25 covered, 1 conflict, 2 partial, 22 uncovered; llm_calls=3
```
Образцы таблицы покрытия с доказательствами лежат в `tests/p06/sample/case_ab-rules.md` и `case_ab-scripted.md`.

## ⚠️ Для Max: 13 интеграционных тестов привязаны к резерву слота

`tests/integration` передаёт mock-провайдеру сценарий `mock_bcc.json["cross"]` в схеме **резервной**
реализации (`conflicts/issues/coverage/facts`). Mock ищет ответ по полному имени, затем по базовому, поэтому
отдаёт этот ответ и на `cross#pairs`. Ответ не проходит схему №06, движок перезапускает модуль без модели,
и ожидаемых LLM-находок («Ф-4», «метод чтения»…) нет.

Причина подтверждена: если убрать `analysis/cross.py`, падает только PDF-тест, и то лишь без PyMuPDF.
Свои тесты движка я не трогал. Патч `tests/p06/patches/integration-pin-fallback.patch` (3 строки в
`tests/integration/conftest.py`) закрепляет резерв слота `review_set` для mock-сценариев. Поведение №06
через движок покрывает `tests/p06/test_p06_integration.py`: офлайн, mock с K2, отказ модели, паритет MD/PDF.
Вторая возможность — добавить в `mock_bcc.json` ключи `cross#pairs` и `cross#coverage`; пример сборки есть
в `_k2_script`. **Без одного из двух вариантов влитие №06 в `bcc/integration` сделает эти 13 тестов красными.**

## Проверенные случаи (tests/p06, 48 тестов)

1. **Граница периода, независимый сюжет** (кешбэк 1 % → 2 %).
   Покупка 30.06 в 23:55, проведение 01.07 в 00:05. Цитаты «…1 %…» и «…2 % — 200 ₸» дают разные исходы одного
   события; пояс UTC+5 помечен как иллюстративное допущение. Покупка 1 июля совместима. Два правила привязки
   к разным событиям тоже дают конфликт.
2. **Негативный контроль** (подтверждённый и отменённый платёж).
   Без модели конфликта нет. Если «наивная» модель заявит конфликт, его отклоняют непересекающиеся
   ограничения; без ограничений такой ответ становится максимум вопросом.
3. **Покрытие.** Л-1 — одно обязательство covered, второе conflict, итог covered 1/3. Без модели covered
   не выставляется. При пропущенной стр. 3 — unknown, а положительные выводы сохраняются.
4. **Три пары.** Конфликт дают только разные границы, минимальный пример 300 001 ₸.
   Совместимы: 1 ₸ = 100 тиын; integer→string с оговорённым представлением; 200-ERROR рядом с 401
   «не передан токен». Тип без оговорки уходит вопросом minor.
5. **Кейс A+B** (три загрузчика дают одинаковый результат):
   * К1 — witness на строке 64; К4 — обещание в строке 52, охват строк 95–197, найден только
     `GET /alerts/saveLimit — сохранение`; 200-ERROR/400 — вопрос.
   * С подставной моделью К2 и К3 (`amount=999 outside range:FX-…`) подтверждаются программой.
   * Выдуманная цитата отклоняется; сбой провайдера даёт partial.
6. **Стык.**
   * `validate` по контракту; `resolve_candidate` №07 → `supported`;
   * `run_review` офлайн и через mock (К2 доходит до `findings` с witness);
   * если модель не ответила ни разу, этап `cross` = failed, прогон partial, правила сохранены;
   * `AskError` поднимается, только если не удался ни один вызов;
   * **паритет Markdown/PDF**.
7. **Ложные срабатывания.**
   * «push через сервис» не считается обещанием API;
   * неоднозначная метка времени не даёт конфликта (тест падает на прежней логике);
   * мягкие переносы PDF не режут обязательства (до исправления PDF давал 37 обязательств вместо 25);
   * одна таблица приёмки получает уникальные id.

## Кому что

* **Max.** Применить патч или ключи сценария (см. выше); читать `stats.status` у `cross`. `facts` → `Report.facts`,
  `coverage` → `Report.coverage`, `coverage_summary` (знаменатель, `linked`, `excluded`) — в раздел покрытия.
* **№10.** `coverage` + `coverage_summary.by_requirement`; `linked` ≠ `covered`.
* **№07.** Опоры witness — `hint_a/hint_b` и `evidence_a/b`, плюс `input_detail.document_data[].evidence`.
  Модуль вызывает `resolve_hint(document, hint, index=…)`, а при `missing` повторяет с `relocate=True`.
* **№08.** Кандидаты `subkind="question"` (`kind="ambiguity"`) с полями `question`, `condition_a/b`, `reason`.
* **№04.** Формат `fact_hints` описан выше. Полезнее всего единицы и включённость границ, которых нет в таблице.

## Открытые зависимости

* Реальный прогон `ask` на Gemini или Anthropic ключом команды (Max, №18). Здесь проверены только mock движка,
  подставной транспорт и строгие схемы через `jsonschema`.
* Решение Max по 13 тестам `tests/integration`: патч или ключи сценария.
* Коды критериев (`set_consistent`, `set_complete`) — сверить с `criteria.toml` №05, когда он появится.
