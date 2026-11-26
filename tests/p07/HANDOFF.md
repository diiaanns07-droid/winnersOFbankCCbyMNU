# p07 · Проверка каждой цитаты — передача

База: `bcc/integration@3e6b569` (контракт v1 `431f76d`). Мои файлы: `src/bcc_review/analysis/evidence.py`,
`src/bcc_review/verification.py`, `tests/p07/`. Кроме того, добавлен пустой `src/bcc_review/analysis/__init__.py`
(только docstring): пакета `analysis` в bootstrap ещё нет. При слиянии с №04/05/06 оставьте любую из версий.

Зависимостей вне стандартной библиотеки и `bcc_review.contracts` нет. Тестам нужны `pytest`, `jsonschema`, а для
PDF и DOCX ещё `pdfplumber` и `python-docx`; без них эти тесты пропускаются.

## 1. Интерфейс

```python
from bcc_review.analysis.evidence import (
    resolve_hint, resolve_candidate, check_evidence, check_finding_support, locate,
    DocumentIndex, RepairBudget, EvidenceAudit, REASONS, describe,
)
from bcc_review.verification import verify_report, render_text, summary_counts, find_reader, main
```

| Функция | Вход | Выход |
| :--- | :--- | :--- |
| `resolve_hint(document, hint, *, index=None, budget=None, audit=None, relocate=False)` | `Hint = {block_id, quote, context?}` (дополнительно `before`/`after`) | `{status: matched\|missing\|ambiguous, evidence, reason, message, warnings, occurrences, candidates, hint}` |
| `resolve_candidate(document, candidate, *, index, budget, audit, requirements=None)` | `Candidate` v1; конфликт — `witness` (`WitnessDraft` с `hint_a`/`hint_b`) или `role: a/b` у hints; пропуск — `inspected_block_ids`, необязательно `absent_terms` | `{anchor_status: supported\|incomplete, evidence, witness: Witness\|None, inspected_block_ids?, warnings, reasons, hint_results}` |
| `check_evidence(document, evidence)` | готовая `Evidence` | `{status: confirmed\|ambiguous\|rejected, reason}` |
| `check_finding_support(document, finding)` | `Finding` | список причин; пустой список значит, что опор достаточно |
| `locate(document, evidence)` | `Evidence` | `{block_id, section, line, col, line_end, col_end \| page, page_end, rects \| part, path, label}` |
| `verify_report(report_path, source_path, *, reader=None)` | пути к файлам | `{ok, exit_code, errors[{code,path,message}], warnings, counts, source}` |

Результаты — обычные `dict`. `res["evidence"]` проходит `validate(..., "Evidence")`, `res["witness"]` —
`"Witness"`, `EvidenceAudit().to_dict()` — `"EvidenceAudit"` (поле `note` + расширения `unit`, `by_reason`,
`repairs_used`, `repair_budget`). Для прогона передавайте общий `DocumentIndex(document)`, `RepairBudget(limit=N)`
и `EvidenceAudit(budget=...)`.

Предлагаемая сборка `Finding` (так делает `tests/p07/report_builder.py`): `evidence`, `anchor_status`, `witness`,
`inspected_block_ids` — из `resolve_candidate`; `status = "confirmed"` только при `anchor_status == "supported"`
(и решении №05/06 о смысле); причины отказа — в `notes` (строки `code: текст`).

### Правила поиска

* Подтверждённая `Evidence` всегда буквальная: `block.text[start:end] == quote`. Координаты задаются в кодовых
  точках Unicode, с нуля, правая граница не входит. **Для HTML/JS (№13)** индексы нужно пересчитать в UTF-16:
  `𝟙` занимает одну позицию в Python и две в JS.
* Допустимые различия: пробелы любого вида (NBSP, U+202F, табуляция, `\n`) сворачиваются в один, мягкий перенос
  и символы нулевой ширины игнорируются, перенос слова («про-\nверка») и дефис между буквами не различаются,
  применяется NFC. Для `format = markdown` ещё игнорируются `*` и `` ` ``. Цифры, знаки сравнения, валюта,
  регистр, тире и отрицания **не** нормализуются.
* Отказ по границе цитаты: разрезанное число, разрезанное слово (в том числе приставка «не-»), отрицание или знак
  числа за пределами цитаты. Слово сравнения или единица за пределами цитаты отмечаются только предупреждением.
* Повторы. Одно вхождение даёт `matched`. Несколько вхождений: выбирает `context` (или `before`/`after`), полное
  совпадение с границей слова. Без контекста или при ничьей результат `ambiguous`.
* Номер строки от модели игнорируется: опору задают `block_id` и литерал, место считает `locate` по `block.loc`.
* Существующий `block_id` при цитате из другого блока даёт `missing / found_in_other_block` с точными кандидатами.
  Перенос включается явно (`relocate=True`, предупреждение `block_relocated`). Без `block_id` или с несуществующим
  ID поиск идёт по всему документу; единственное вхождение принимается с предупреждением.
* Нечёткий поиск (`difflib`, порог 0.6) выдаёт только `candidates` с `differences` (`number_mismatch`,
  `negation_mismatch`, `currency_mismatch`, `comparison_mismatch`, `wording_mismatch`). Кандидат **никогда** не
  становится `evidence`: его показывают модели при повторном запросе («процитируй дословно или откажись») или
  человеку. Каждый нечёткий поиск расходует единицу `RepairBudget`; при исчерпании — `repair_budget_exhausted`.

### Минимум опор для `supported`

* Все hints кандидата обязаны дать `matched`; подтверждённые опоры сохраняются и при `incomplete`.
* **Конфликт** (`conflict|contradiction|inconsistency`): по одной подтверждённой опоре на сторону `a` и `b`; опоры
  не пересекаются и не совпадают по тексту (допустимы два диапазона одного блока); `witness.input`, разные
  `outcome_a`/`outcome_b`. Иначе `witness = None` (Finding v1 допускает `null`).
* **Пропуск** (`omission|missing|gap|absence`): непустой `inspected_block_ids` из существующих блоков. Цитата
  обещания необязательна, но если дана, должна подтвердиться. Если что-то из `absent_terms` буквально есть в
  области поиска, кандидат опровергнут (`absent_term_present`).
* Для остальных видов нужна хотя бы одна опора.

## 2. Причины (`REASONS`, `describe(code)` → русский текст)

| Статус | Коды |
| :--- | :--- |
| `missing` | `empty_quote`, `not_found`, `found_in_other_block`, `negation_outside_quote`, `sign_outside_quote`, `number_boundary`, `partial_word`, `number_mismatch`, `negation_mismatch`, `currency_mismatch`, `comparison_mismatch`, `wording_mismatch` |
| `ambiguous` | `multiple_occurrences`, `context_not_unique`, `context_mismatch`, `duplicate_block_id` |
| предупреждения при `matched` | `normalized_match`, `unknown_block_id`, `no_block_id`, `block_relocated`, `context_ignored`, `context_unusable`, `outer_quotes_stripped`, `comparison_outside_quote`, `unit_outside_quote`, `repair_budget_exhausted` |
| кандидат и замечание | `no_hints`, `conflict_side_missing`, `conflict_sides_unspecified`, `conflict_same_anchor`, `conflict_witness_missing`, `conflict_outcomes_equal`, `witness_evidence_not_in_finding`, `omission_scope_missing`, `unknown_inspected_block`, `absent_term_present`, `anchor_not_supported`, `evidence_outside_requirement` (предупреждение) |

## 3. Две единицы учёта

* `run.evidence_audit` (`EvidenceAudit.to_dict()`) — **опора-подсказка** `{block_id, quote}` от модели или
  правила: проверено = подтверждено + неоднозначно + отклонено; плюс `by_reason`.
* `verify_report(...)["counts"]` — **объект Evidence в REPORT.json**, каждое вхождение отдельно (требования,
  замечания, свидетели, факты, покрытие, чек-лист). Неоднозначно означает, что опора верна по координатам, но та
  же цитата повторяется в блоке. Отклонено — неверны блок, координаты, текст, граница или место. Если источник
  не совпал: `checked = 0`, `skipped = N`.

На демо-паре это 13 подсказок (одна отклонена: `number_mismatch`) и 13 объектов Evidence: свидетель повторяет
две опоры конфликта, а у отклонённого D-4 опор нет.

## 4. `verify_report` — что проверяется без модели

1. JSON Schema v1 (`contracts.validation_errors`) → `schema_invalid`.
2. SHA-256 файла против `run.source_sha256` и `document.id`. При расхождении сверка опор пропускается.
3. Оригинал читается заново штатным reader. Сравниваются `document.title/format/warnings` и каждый блок
   (`text`, `section`, `kind`, `loc`).
4. Каждая Evidence (вне `run`, `diff`, `document`, `rejected`): блок, диапазон, литерал, граница, `section` и
   `loc`/`line`/`col`/`page`/`path`, если они указаны. Правки `decisions[].edits` для текущего SHA: `old`
   по координатам.
5. Уникальность ID; ссылки `req_ids`, `req_id`, `affected_req_ids`, `finding_ids`, `critical_ids`, `fact_ids`,
   `question_id`, `open_question_id`, `block_ids`, `inspected_block_ids`, `block_id`.
6. Замечания `confirmed`: `anchor_status = supported`; конфликт — witness с двумя разными опорами, которые входят
   в `evidence`, и разными исходами; пропуск — область поиска.
7. Числа фактов присутствуют в их цитатах.
8. `summary` пересчитывается по спискам (`summary_counts`): `requirements`, `reviewed_requirements`, `findings`,
   `by_severity` и `by_status` (разбиения **всех** замечаний), `critical_ids` (**подтверждённые** критичные),
   `checks`.
9. `verdict`: `ready` недопустим при подтверждённом критичном замечании, блокирующем эту цель (`blocks`, по
   умолчанию обе), и при прогоне не `complete` (кроме `run.options.allow_partial_ready`). `partial_read` и другие
   `PARTIAL_READ_CODES` в документе при `run.status = complete` дают ошибку.
10. Арифметика `run.evidence_audit`.

Покрывает все инварианты `contracts.evidence_errors` и сверяет их с источником, прочитанным заново, а не с копией
в отчёте.

Reader: аргумент `reader=` → `BCC_REVIEW_READER=module:function` → `bcc_review.readers:read_document` /
`bcc_review.engine:read_document` (если появятся) → по расширению `readers.text:read_text`,
`readers.pdf:read_pdf`, `readers.docx:read_docx`. Если reader не найден, возвращается ошибка
`reader_unavailable` (код 1); молча проверка не проходит.

Коды выхода по `contracts`: `0` — пройдена, `1` — ошибка выполнения (нет файла или reader), `2` — вызов,
`4` — расхождение. Оболочка Max: `return verification.main(argv)`; ведущее слово `verify` принимается.

## 5. Сравнение с RAG и выбор подхода

`diiaanns07-droid/RAG@ba64cc7`, `validate_graph_evidence`: проверка `quote in chunk.content` и полноты имени через
`(?<!\w)name(?!\w)`. Координат нет, повторы не различаются, ошибка на первой опоре. Сравнение на маленьком примере:

| Случай | `in` (RAG) | regex с допусками | нормализация + карта (выбрано) |
| :--- | :--- | :--- | :--- |
| NBSP в «100 ₸» | не найдено | найдено | найдено |
| «не более 10» внутри «не более 100» | **принято** | **принято** | найдено → отклонено границей |
| «более 100 ₸» после «не» | принято | принято | найдено → отклонено границей |
| «про-\nверка» | не найдено | найдено | найдено |
| повтор в блоке | не различается | 2 вхождения | 2 вхождения → контекст |
| «Не» внутри «Нӗ» (е + бреве) | **принято (разрез графемы)** | **принято** | не найдено |

## 6. Пример Evidence для каждого типа файла (`pytest tests/p07/test_formats.py -s`)

```text
[md]   {"block_id": "b0013", "start": 0, "end": 42, "quote": "Знак 𝟙 обозначает первичный лимит 50 000 ₸"}  →  строка 23, раздел «Символы»
[pdf]  {"block_id": "b0003", "start": 18, "end": 52, "quote": "про-\nверку порога по времени UTC+5"}  →  стр. 1
[docx] {"block_id": "b0007", "start": 20, "end": 59, "quote": "максимум один push за календарный месяц"}  →  абзац body/tbl[1]/tr[2]/tc[2], раздел «Функциональные требования»
```

В MD-примере между «50», «000» и «₸» стоят NBSP; цитата в Evidence буквальная. Для PDF `locate` возвращает ещё
`rects` двух строк-фрагментов (для подсветки у №14). Для MD — `col`/`col_end` по `loc.map`.

## 7. Поставщикам координат (№01/02/03)

Синтетический reader `tests/p07/synthetic_reader.py` выдаёт ровно форму контракта и побайтно воспроизводит
`document` из `contracts/examples/minimal_report.json`: `b0001`…, `section` заголовка — его родители, MD без
маркера списка, `**` и `` ` `` с `loc.map`, PDF с `page` и `fragments[{start,end,rect}]`, DOCX с `part` и `path`.
`locate` читает именно эти ключи. Расширения на случай блоков через строку или страницу: `line_starts`,
`page_breaks`. Модель должна видеть ровно `block.text`: только тогда её цитаты совпадут с литералом.

## 8. Команды и результаты (выполнено в этой среде)

```bash
pip install -e ".[dev]"
```

```bash
python -m pytest tests/p07 tests/contract -p no:cacheprovider
```
Результат: `160 passed` на Python 3.13.18 и 3.11.18 (venv: pytest, jsonschema, pdfplumber, python-docx).

```bash
ruff check --select E,F,W,B,UP,SIM,I --line-length 120 --target-version py311 src/bcc_review/analysis src/bcc_review/verification.py tests/p07
```
Результат: замечаний нет.

```bash
BCC_REVIEW_READER=synthetic_reader:read PYTHONPATH=tests/p07 python -m bcc_review.verification verify contracts/examples/minimal_report.json contracts/examples/two_linked_requirements.md
```
Результат: `проверено 6 · подтверждено 6`, `ИТОГ: ПРОЙДЕНА`, код 0. Демо-пара `case.md`:
`проверено 13 · подтверждено 12 · неоднозначно 1 · отклонено 0`, код 0. С подменой `summary.by_severity.critical`
— код 4, `summary_count_mismatch`. С изменённым источником — код 4, `source_sha_mismatch` и
`document_id_mismatch`, `пропущено 13`.

Мутационная проверка (вручную): без защиты границ падает 13 тестов; без сверки литерала в `check_evidence`,
без обратной проверки нормализации, с переносом по умолчанию, без проверки одной опоры у конфликта, без выбора
по контексту — падает хотя бы один тест в каждом случае.

## 9. Проверенные случаи

* Повтор фразы дважды в блоке и в соседнем блоке: без контекста `ambiguous` (2 и 3 вхождения), `context` или
  `before`/`after` выбирают нужное; при равном контексте `context_not_unique`; при неверном `context_mismatch`;
  граница слова в контексте.
* «не более 10 ₸» и «более 100 ₸»: неверная сумма, отрезанное отрицание, «не более 10» внутри «100», `$` и «тенге»
  вместо ₸, «менее» вместо «более», цитата из соседнего блока, `-5`, `10,5`, `000 000`, «невозможна», «без»,
  «кроме».
* NBSP + кириллица + `𝟙`: `[5, 32)` в кодовых точках (в UTF-16 было бы 33); переносы с `-`, `­`, `‑`;
  табуляция и узкий NBSP; ZWSP; NFD в тексте; графема не режется, в том числе при расширении NFC (U+0958);
  разметка MD игнорируется только для `markdown`; регистр и тире не сворачиваются.
* Свойство: 800 случайных выборок слов из `case.md` и `bcc_requirements.md` с испорченными пробелами; для каждого
  `matched` выполняется `block.text[start:end] == quote`.
* Reader-координаты: строка и колонка MD через `loc.map` совпадают с исходным файлом; страница PDF совпадает с
  `pdfplumber`, а `rects` содержат текст; путь DOCX совпадает с ячейкой `python-docx`.
* Кейс BCC (`fixtures/bcc_requirements.md` — копия `BCC-HUB/ai-requirements-validator-task@928c1aa`): К2 Ф-3↔Ф-4
  и К3 400↔`{"result":"ERROR"}` в 200 подтверждены; К4 «нет метода чтения» — область из 30+ блоков Части B;
  «от 1 000 до 100 000 ₸» отклонено, кандидат указывает на строку 37.
* Стык с контрактом: резолвер воспроизводит `evidence`, `witness` и `evidence_audit` примера Max; `verify`
  принимает пример и ловит подмены сводки и источника; отчёты из `report_builder` проходят `validate(report)` и
  `evidence_errors(report) == []`.
* `verify`: 26 подмен (цитата, координата, строка, критичные: число и список, `by_status`, `ready` при критичном
  и при `partial`, блок, диапазон, ссылки на требование и вопрос, дубль ID, confirmed без опоры, одна опора у
  конфликта, одинаковые исходы, область пропуска, аудит, число факта, раздел, встроенные блок, `loc.map` и
  warnings документа, схема, обрезанное число, правка решения), неполное чтение при `complete`, изменённый
  источник, отсутствующий reader, битый JSON. Каждый случай даёт `ok=false`, свой код и код выхода 4 (или 1).
  Сеть заблокирована, модули LLM не импортируются, reader вызывается заново.

## 10. Открытые вопросы к контракту и следующий получатель

1. **Max**: подтвердить семантику `summary.by_severity` (у меня — все замечания, как `by_status`) и
   `critical_ids` (у меня — подтверждённые критичные). Пример контракта не различает эти варианты.
2. **Max**: где хранить причины отказа опор у `needs_review` — сейчас в `Finding.notes`. Ключ `loc` внутри
   Evidence — моё расширение (схема его допускает); если он мешает экспортам, `report_builder` его не добавляет.
3. **Max**: подключить `verification.main` в `cli.py` для `verify`; передать общий `RepairBudget` и `EvidenceAudit`
   на прогон. Цикл исправления: `missing` с `candidates` → повторный `ask` → снова `resolve_hint`, в пределах
   бюджета.
4. **№01/02/03**: после вливания reader запустить `pytest tests/p07` без `BCC_REVIEW_READER`. Тесты `verify` на
   стыке перейти со `synthetic_reader.read` на штатный reader (одна строка в `test_verify_report.py`).
5. **№08, №13, №14, №17**: подпись места — `locate(...)["label"]`; подсветка — `col`/`col_end` (MD) и `rects`
   (PDF); `candidates` не показывать как доказательство; в HTML пересчитать индексы в UTF-16.
