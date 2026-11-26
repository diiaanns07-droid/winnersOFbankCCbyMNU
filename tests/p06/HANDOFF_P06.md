# №06 · Межраздельные противоречия и покрытие приёмкой — передача

Файлы направления: `src/bcc_review/analysis/cross.py`, `src/bcc_review/analysis/facts.py`,
`src/bcc_review/prompts/cross.{pairs.md,coverage.md,schema.json}`, `tests/p06/`.
Других файлов модуль не создаёт. `__init__.py` нет: пакет работает как namespace (PEP 420),
поэтому после bootstrap Max достаточно его собственных `__init__.py`.

База — `claude/nice-edison-gpkcfl` @ `76ab976`. `bcc/integration` и `contracts/HANDOFF.md` на момент работы
не были опубликованы, поэтому типы приняты по контракту v1 «утиным» способом: dict или объект с атрибутами.
Стыковой тест с реальным загрузчиком и `ask` Max ещё не прогнан (см. «Открытые зависимости»).

## Протокол

```python
from bcc_review.analysis.cross import review_set
from bcc_review.analysis.facts import reconcile_facts

review_set(document, requirements, ask=None, *, fact_hints=None, resolve=None, max_pairs=60, pairs_per_call=30)
# -> {facts, coverage, candidates, warnings,                  # контракт
#     coverage_summary, comparisons, evidence_audit, stats, acceptance}   # пояснения для отчёта
reconcile_facts(document, fact_hints=None, *, resolve=None)
# -> {facts, candidates, comparisons, endpoints, warnings, evidence_audit}
```

* `ask(stage, payload, schema) -> dict`. Стадии: `cross.pairs` (пакеты по 30 пар) и `cross.coverage` (1 вызов).
  На кейсе A+B получается 3 вызова. В `payload["instructions"]` лежит текст промпта из `prompts/cross.<stage>.md`,
  схема ответа берётся из `prompts/cross.schema.json[stage]`: подмножество JSON Schema без `$ref`.
  Если `ask` бросает исключение или возвращает не объект, детерминированный результат сохраняется,
  в `warnings` попадает причина, а `stats.status = "partial"`.
* `resolve(document, hint) -> Evidence | None` — точка подключения №07. Если резолвер передан, решение
  за ним. Иначе работает локальный резолвер с тем же инвариантом `block.text[start:end] == quote`:
  точное совпадение, затем нормализация пробелов, ё и Markdown, затем перенос в единственный другой блок.
* `fact_hints` (№04) — список или `{"facts": [...]}` элементов
  `{field, subject?, direction?, type?, value?, range?, unit?, condition?, hint: {block_id, quote}}`.
  Подсказка заполняет пустые слоты факта из таблицы. Если она расходится с разбором, разбор остаётся,
  а в `warnings` пишется предупреждение. Подсказка без найденной цитаты отклоняется.

### Кандидаты

Базовые поля по контракту: `scope, kind, criterion, severity, title, impact, req_ids, hints`. Дополнительно:

| kind | когда | доп. поля |
| :--- | :--- | :--- |
| `conflict` | один вход удовлетворяет обоим предусловиям, исходы несовместимы, обе опоры найдены | `witness = {input:{description, document_data[{name,value,evidence}], illustrative[{name,value,why}]}, outcome_a, outcome_b, outcome_a_value?, outcome_b_value?, evidence_a, evidence_b}`, `checks` (что проверила программа: evidence, preconditions, outcomes), `slots` (объект, владелец, условие, момент, единицы, ожидаемое), `acceptance_ids`, `origin` (rules/facts/llm) |
| `missing_contract` | обещана операция через API, а метода нет | `promise`, `inspected_block_ids`, `inspected_scope {sections, span}`, `searched_for`, `found` |
| `question` | общий вход не построен (→ №08) | `question`, `condition_a`, `condition_b`, `reason`, `needs` |

`criterion` и `severity` берутся из `src/bcc_review/criteria.toml`, секции `[cross.<kind>]` или `[kinds.<kind>]`
с ключами `criterion` и `severity`. Пока файла нет, действуют значения по умолчанию:
conflict — consistency/critical, missing_contract — completeness/critical, question — consistency/major,
вопрос о типе — minor.

### Покрытие

Каждое обязательство — одно предложение требования:
`{req_id, obligation_id, obligation, acceptance_ids, status, explanation, hints, branches, branches_checked, links}`.

* `covered` — модель указала проверку всех ветвей, и связанная приёмка сама не участвует в противоречии.
* `partial` — проверена часть ветвей, либо есть только лексическая связь (режим без модели),
  либо модель заявила противоречие без подтверждённого входа.
* `conflict` — подтверждённый witness связывает эту строку приёмки с этим предложением.
* `uncovered` — связей нет, а все страницы извлечены.
* `unknown` — связей нет, но часть страниц пропущена (по `document.warnings` или по разрыву в `loc.page`).

`coverage_summary` сохраняет знаменатель и отдельно считает `linked`: наличие ссылки не даёт covered.

## Команды и результаты (выполнено в этой среде)

```bash
python3 -m pytest tests/p06 -q -p no:cacheprovider        # Python 3.13.18: 38 passed
```

```bash
uv venv --python /usr/bin/python3.11 .venv311 && VIRTUAL_ENV=.venv311 uv pip install pytest jsonschema
.venv311/bin/python -m pytest tests/p06 -q -p no:cacheprovider   # Python 3.11.18: 38 passed
```

```bash
ruff check --select E9,F --target-version py311 src/bcc_review/analysis tests/p06   # чисто
```

```bash
python3 tests/p06/demo_case.py tests/p06/fixtures/case_ab.md OUT            # только правила
python3 tests/p06/demo_case.py tests/p06/fixtures/case_ab.md OUT --scripted # подставной транспорт, не реальная модель
```

Вывод демо (по одной строке на прогон):

```text
case_ab-rules:    conflict=1 missing_contract=1 question=1; coverage 0/10 covered, 1 conflict, 6 partial, 3 uncovered; llm_calls=0
case_ab-scripted: conflict=3 missing_contract=1;            coverage 0/10 covered, 1 conflict, 2 partial, 7 uncovered; llm_calls=3
cashback_boundary-rules: conflict=1; coverage 0/3, 2 conflict, 1 partial
payment_states-rules:    кандидатов нет; coverage 0/4, 2 partial, 2 uncovered
transfers_pairs-rules:   conflict=1 (только разные границы); coverage 0/2 (нет приёмки)
```

## Проверенные случаи (tests/p06)

1. **Граница расчётного периода, независимый сюжет** (`test_p06_period_boundary.py`, кешбэк 1 % → 2 %).
   Покупка совершена 30 июня в 23:55 и проведена 1 июля в 00:05. Цитаты «…1 %…» (КБ-1) и «…2 % — 200 ₸» (приёмка)
   дают разные исходы одного события. Моменты времени взяты из документа, пояс UTC+5 помечен как
   иллюстративное допущение. Строка с покупкой 1 июля совместима. Вариант с двумя правилами привязки
   к разным событиям тоже даёт конфликт.
2. **Негативный контроль** (`test_p06_negative_control.py`): условия «подтверждённый» и «отменённый» платёж.
   Без модели конфликта нет. Если «наивная» модель заявит конфликт, проверка ограничений отклонит его
   как непересекающийся. Без ограничений такой ответ становится максимум вопросом.
3. **Два обязательства в Л-1** (`test_p06_coverage.py`): одно covered, другое conflict, итог covered 1/3.
   Witness вычислен программой: 45 000 + 10 000 > 50 000. Без модели covered не выставляется.
   При пропущенной странице 3 (PDF) статус Л-2 — unknown, а положительные выводы сохраняются.
4. **Три пары** (`test_p06_three_pairs.py`). Только разные границы (100–500 000 и 100–300 000) дают конфликт
   с минимальным примером 300 001 ₸. Пары 1 ₸ = 100 тиын и integer→string с оговорённым представлением
   совместимы. 200-ERROR рядом с 401 «не передан токен» не даёт ни конфликта, ни вопроса.
   Расхождение типов без оговорки уходит вопросом с серьёзностью minor.
5. **Кейс A+B** (`test_p06_case_ab.py`, строки и целая таблица дают одинаковый результат):
   * К1 — witness на данных строки 64.
   * К4 — обещание в строке 52, просмотрены строки 95–197, найден только `GET /alerts/saveLimit — сохранение`.
   * 200-ERROR/400 — вопрос. Со сценарием модели (подставной транспорт) К2 (Ф-3↔Ф-4) и К3
     (`amount=999 outside range:FX-…`) подтверждаются программой, вопрос снимается.
   * Выдуманная цитата отклоняется и учитывается в `evidence_audit`.
   * Сбой провайдера даёт статус partial, а результаты правил сохраняются.
6. **Ложные срабатывания** (`test_p06_false_positives.py`):
   * «получает push через сервис» не считается обещанием API;
   * неоднозначная метка времени не даёт конфликта (тест падает на прежней логике выбора метки);
   * таблица приёмки, пришедшая одним требованием, получает уникальные id;
   * результат сериализуется в JSON и имеет форму контракта на всех фикстурах.

## Кому что

* **Max:** вызывать `review_set(doc, requirements, ask, fact_hints=inv04, resolve=evidence07)`.
  `facts` → `Report.facts`; `coverage` и `coverage_summary` → `Report.coverage`;
  `evidence_audit` можно сложить с аудитом №07; `stats.mode` и `stats.llm_calls` → `run`.
  Кандидаты с `witness` уже содержат Evidence с обеих сторон.
* **№10:** `coverage` + `coverage_summary.by_requirement` (знаменатель, linked ≠ covered).
* **№07:** пары опор — `witness.evidence_a/evidence_b`, `hints`, `input.document_data[].evidence`.
  Ожидаемая сигнатура резолвера — `resolve(document, hint) -> Evidence | None`.
* **№08:** кандидаты `kind="question"` с полями `question`, `condition_a`, `condition_b`, `reason`.
* **№04:** формат `fact_hints` описан выше. Полезнее всего единицы и включённость границ, которые не читаются из таблицы.

## Открытые зависимости

* Bootstrap `bcc/integration`: сверить Document и Requirement с `contracts/v1.json`, прогнать стыковой тест
  с реальным загрузчиком MD/PDF/DOCX (формат `loc` и разбивку таблиц на блоки модуль поддерживает в трёх
  вариантах: целая таблица, строка, ячейка с `loc.row/col`).
* Реальный прогон `ask` на Gemini или Anthropic ключом команды (Max и №18). Здесь проверены только
  подставной транспорт и схемы через `jsonschema.validate`.
* `criteria.toml`: согласовать коды критериев (`consistency` и `completeness` → коды Max).
