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
  замечания, свидетели, факты, покрытие, чек-лист). Неоднозначно означает, что опора верна по координатам, та
  же цитата повторяется в блоке и отчёт не выделяет это вхождение ничем, кроме координат (с раздела 12: опора
  требования или подпись факта в ячейке выделяют его, такое место считается подтверждённым). Отклонено — неверны блок, координаты, текст, граница или место. Если источник
  не совпал: `checked = 0`, `skipped = N`.

На демо-паре это 13 подсказок (одна отклонена: `number_mismatch`) и 13 объектов Evidence: свидетель повторяет
две опоры конфликта, а у отклонённого D-4 опор нет.

## 4. `verify_report` — что проверяется без модели

1. JSON Schema v1 (`contracts.validation_errors`) → `schema_invalid`.
2. SHA-256 файла против `run.source_sha256` и `document.id`. При расхождении сверка опор пропускается.
3. Оригинал читается заново штатным reader и приводится `contracts.normalize_document` (как в движке).
   Сравниваются `document.title/format/warnings` и каждый блок (`text`, `section`, `kind`, `loc`).
4. Каждая Evidence (вне `run`, `diff`, `document`, `rejected`): блок, диапазон, литерал, граница, `section` и
   `loc`/`line`/`col`/`page`/`path`, если они указаны. Правки `decisions[].edits` для текущего SHA: `old`
   по координатам. Опора замечания `scope = requirement` должна лежать внутри опор его требований: если та же
   цитата стоит внутри требования, а отчёт указывает на другое вхождение, — ошибка `evidence_wrong_occurrence`;
   если внутри требования такой цитаты нет — предупреждение `evidence_outside_requirement`.
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
`4` — расхождение. Результат содержит `implementation = {verify, reader}`: какая функция проверки и какой reader
реально отработали (для CLI: `bcc_review.cli:cmd_verify.<locals>.<lambda> → bcc_review.readers.text:read_text`).

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
Результат первого прохода: `160 passed`; после второго прохода (раздел 11) — `169 passed` (`tests/p07` — 140),
на Python 3.13.18 и 3.11.18 (venv: pytest, jsonschema, pdfplumber, python-docx).

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

## 11. Второй проход: перепроверка реального файла из командной строки

База: `bcc/integration@6be9e97` (влиты №01 reader, движок, CLI и мой `cfebfff`). Тестовая копия — отдельный
worktree этого коммита и отдельный venv; reader №01 — `bcc_review.readers.text:read_text`, транспорт модели —
`runtime.mock:MockAdapter`, сеть запрещена.

Пример `tests/p07/fixtures/two_sections.md` (SHA-256 `fdb97025…`): фраза «сумма не превышает 10 000 ₸» дважды в
блоке `b0003` раздела «Ограничения» (строки 5 и 6) и в `b0005` раздела «Уведомления» (строка 10); перед вторым
вхождением `𝟙`. `resolve_hint` без контекста — `ambiguous` `[19,46)` и `[70,97)`; с контекстом
«Для 𝟙-й карты клиента сумма не превышает 10 000 ₸ в сутки.» — `matched` `b0003[70:97)`, строка 6, столбец 22
(в UTF-16 смещение было бы 71).

Воспроизведение на прежнем коде (`cfebfff`) штатной командой и результат после правки:

| Пара | До | После |
| :--- | :--- | :--- |
| правильная | 0, `verify: OK` | 0, `verify: OK` |
| убрано «не» в цитате | 4, `evidence_quote_mismatch` | то же |
| 10 000 → 10 001 в цитате | 4, `evidence_quote_mismatch` | то же |
| чужая редакция («первой» → «второй», фраза на месте) | 4, `source_sha_mismatch`, `document_id_mismatch` | то же |
| опора замечания R-001.2 переставлена на вхождение строки 5 | **0 — ложное подтверждение** | 4, `evidence_wrong_occurrence` с обоими местами |
| `python -m bcc_review.verification` на отчёте движка с таблицами | **4 — ложный `document_block_mismatch` (`loc.columns`)** | 0, счётчики равны CLI |

Правки в `verification.py`: проверка вхождения для замечаний уровня требования, `normalize_document` после
reader, `implementation` в результате. Регрессии: `tests/p07/test_real_reader_cli.py` (9 тестов, на прежнем коде
падают 3). Ложных срабатываний новой проверки нет: отчёт движка `--offline-lint` по `bcc_requirements.md` —
290 опор, `ok`, два обоснованных предупреждения `evidence_outside_requirement`; образцы №17 дают те же коды, что и
до правки.

Команды для Max и №18 (из корня репозитория):

```bash
python -m bcc_review verify REPORT.json SOURCE.md
```

```bash
python -m bcc_review verify REPORT.json SOURCE.md --json
```

```bash
python tests/p07/offline_cli.py verify REPORT.json SOURCE.md
```

Третья команда — тот же CLI с журналом: что загрузил реестр модулей (`[p07-offline] загружено: …`), число
сетевых соединений и импортированные модули провайдеров.

Найдено на стыке (не в моей зоне):

1. **№05 / Max**: `individual._cand_from_answer` передаёт hint `{block_id, quote}` без `context`, хотя цитата
   найдена внутри конкретного требования; движок вызывает `resolve_candidate(document, candidate)` без
   `requirements`. На повторяющейся фразе резолвер честно отвечает `ambiguous`, и верное замечание уходит в
   `rejected` (прогон `two_sections.md` с `fixtures/two_sections.mock.json`). Ложного подтверждения нет, но теряется
   находка. Достаточно одного: №05 кладёт в hint `context` = текст требования (резолвер уже его использует), либо
   Max передаёт `requirements=` и я добавляю выбор вхождения внутри опор требования.
2. **Max**: `cli.cmd_verify` возвращает 4 на любую ошибку, в том числе `reader_unavailable`, где по контракту
   нужен 1. Можно вернуть `result.get("exit_code", 4)`.
3. **№17**: образцы `tests/p17/samples/*/report.json` построены синтетическим документом, а не reader №01, поэтому
   `verify` по их `source-*.md` справедливо сообщает о расхождении блоков и опор.

## 12. Третий проход: повторы цитат и выбор ячейки в выпущенных отчётах

База: моя ветка `00a901e` + слияние `bcc/integration@2821989` (`00a901e` в интеграцию ещё не влит; в ней `verify`
первого прохода). Вход: `release/reports/offline/requirements_pdf.json` (SHA-256 `d105f58e…`) +
`release/input/requirements.pdf` (`fbca9c82…`, как в `release/README.md`), reader №02 `bcc_review.readers.pdf`
на PyMuPDF 2.2; для сравнения — `requirements.json` + `requirements.md`, reader №01.

| Пара | Код verify | проверено | подтверждено | неоднозначно | отклонено |
| :--- | :--- | ---: | ---: | ---: | ---: |
| PDF | `bcc/integration@2821989` (до) | 323 | 309 | 14 | 0 |
| PDF | эта ветка (после) | 323 | 321 | 2 | 0 |
| MD | до | 333 | 319 | 14 | 0 |
| MD | после | 333 | 331 | 2 | 0 |

14 повторных опор — это 8 исходных мест (каждое упомянуто фактом дважды: `facts[i].evidence[0]` и
`facts[i].cells.*`). Позиция, блок и страница подтверждаются буквальным совпадением по координатам; таблица,
строка и столбец теперь вычисляются из `loc.table.cells` (№02) или `loc.cells` (№01) — `locate()` и
`table_cell()`:

| Место (PDF) | Ячейка по reader | Признак отчёта | Итог |
| :--- | :--- | :--- | :--- |
| `b0041 [24,32)` «50 000 ₸» | стр. 2, T2, строка 1, столбец 1 «Исходные условия» | FX-005 «порог» только в этой ячейке | подтверждено |
| `b0041 [70,78)` «50 000 ₸» | стр. 2, T2, строка 1, столбец 3 «Ожидаемый результат» | FX-007 «Итог» | подтверждено |
| `b0042 [29,36)` «4 000 ₸» | стр. 2, T2, строка 2, столбец 1 | FX-008 «Покупка» | подтверждено |
| `b0042 [107,114)` «4 000 ₸» | стр. 2, T2, строка 2, столбец 3 | FX-009 «счётчик вырос» | подтверждено |
| `b0043 [8,16)` «19 900 ₸» | стр. 2, T2, строка 3, столбец 1 | FX-010 «Расходы» | подтверждено |
| `b0043 [72,80)` «19 900 ₸» | стр. 2, T2, строка 3, столбец 3 | FX-013 «Счётчик показывает» | подтверждено |
| `b0098 [0,7)` «enabled» | стр. 5, T5, строка 3, столбец 1 «Parameter» | подпись = цитата, есть и в столбце 7 «DB field» | неоднозначно |
| `b0107 [0,7)` «enabled» | стр. 5, T6, строка 3, столбец 1 «Parameter» | то же, двойник в столбце 5 «DB field» | неоднозначно |

Правило (`verification._distinguish`): повтор подтверждается, только если отчёт выделяет вхождение своим
признаком — опорой требования (замечание `scope = requirement`) или подписью факта `field`, которая есть в ячейке
этой опоры и отсутствует в ячейках двойников. Если подписи нет в своей ячейке, но она есть у двойника, — ошибка
`fact_wrong_cell`. Иначе «неоднозначно», в предупреждении названа вычисленная ячейка и столбцы двойников.
Результат содержит `counts.repeats` и список `repeats` (место, страница/строка, таблица, строка, столбец,
заголовок, ссылки, вердикт).

Контрольные изменения тестовой копии отчёта (`tests/p07/test_release_repeats.py`, PDF и MD):

| Изменение | До | После | Что доказано |
| :--- | :--- | :--- | :--- |
| C1: обе опоры FX-005 «порог» → второе «50 000 ₸» строки (`[70,78)`) | 0, OK | 4, `fact_wrong_cell` ×2 | ячейка без подписи «порог», подпись стоит у двойника в столбце 1 |
| C2: цитата FX-005 «50 000 ₸» → «500 000 ₸», координаты прежние | 4, `evidence_quote_mismatch` | то же | текст по координатам другой |
| C1b: `cells.field` FX-016 → «enabled» столбца 7 «DB field» | 0, OK | 0, предупреждение с вычисленным столбцом 7 | доказать нечем: та же подпись в обоих столбцах |
| C1b + `loc: {"header": "Parameter"}` в опоре | 0 | 4, `evidence_loc_mismatch` | заявленный столбец ≠ вычисленному reader |

Пример для защиты: в строке 1 таблицы критериев приёмки «50 000 ₸» написано дважды — «порог 50 000 ₸» (столбец
«Исходные условия») и «Итог 50 000 ₸» (столбец «Ожидаемый результат»). Факт FX-005 «порог» указывает на первое.
verify заново читает PDF, вычисляет страницу 2, таблицу T2, строку 1, столбец 1 и видит подпись «порог» только в
этой ячейке. Если переставить координаты на второе «50 000 ₸», буквальное совпадение сохраняется, но verify
отвечает кодом 4: «ячейка «Итог 50 000 ₸ и один push» без подписи; та же цитата с подписью стоит в столбце 1».

Команды (из корня репозитория, нужен `pip install -e ".[all]"` для PDF):

```bash
python -m bcc_review verify release/reports/offline/requirements_pdf.json release/input/requirements.pdf --json
```

```bash
python -m bcc_review.verification verify release/reports/offline/requirements_pdf.json release/input/requirements.pdf
```

Вторая печатает сводку повторов по местам.

Открытое:

1. **Max**: влить `00a901e` и этот коммит; после слияния числа в `release/README.md` («Опор проверено verify»
   309/319) станут «подтверждено» 321/331 — счётчики изменились по смыслу, а не по составу опор.
2. **№06 (факты)**: столбец в API-таблицах доказуем, только если отчёт его заявляет. Достаточно класть в
   `cells.*` заголовок столбца (`loc.header`) или его номер (`loc.cell`) — verify уже сверяет их с reader.
3. На `bcc/integration@2821989` в этой среде падают 8 чужих тестов (p04, p08, p09, p11, p14, p15 ×2, p16) — те же
   до и после моих изменений.
