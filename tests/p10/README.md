# №10. Чек-лист банка и приёмочные сценарии

Код: `src/bcc_review/bank/checklist.py`, `src/bcc_review/bank/acceptance.py`. Тесты: `tests/p10/`.
База: `bcc/integration` 2821989 (контракт v1 431f76d с дополнениями; влиты №01–09, 11–18).

```python
from bcc_review.bank import build_bank_pack, collect_questions, render_markdown

pack = build_bank_pack(document, requirements, findings, decisions, ask,           # позиционно, как зовёт движок
                       coverage=report_coverage, questions=report_questions,     # необязательно, см. «Предложения Max»
                       previous=previous_report, complete=None, criteria=None)
# -> {"checklist": [ChecklistRow…], "test_cases": [TestCase…], "warnings": [Warning…]}
```

## Чек-лист

Строки берутся из таблицы входного документа. Шаблон определяется по колонкам с отметками вида
«Да / Нет / Не требуется», а не по готовому списку. Модуль сохраняет исходный порядок, текст проверки,
примечание шаблона и допустимые отметки каждой ячейки. Если таблицы нет, `checklist = []`, а в
предупреждения пишется `bank.checklist_absent`.

| Поле | Что внутри |
| :--- | :--- |
| `available`, `checked` | отметки контракта `yes / no / na / unknown` |
| `cells.available`, `cells.checked` | исходный токен шаблона («Да», «Нет», «Не требуется», «Н/П»…) или `null` |
| `allowed` | допустимые отметки этой ячейки в исходном написании; у разных строк они могут отличаться |
| `presence` | есть ли описание (раздел, строка «поле — значение»), опоры и проверенные блоки |
| `machine` | машинная проверка по подтверждённым замечаниям; `blocking_finding_ids` — critical/major |
| `approval` | согласование человеком: `requires_confirmation`, `recorded`, `confirmed`, `rejected` или `not_required` |
| `not_required_basis` | обязательное основание для «Не требуется» |
| `question` | `Q-CHK-NN` для строки, которая ждёт подтверждения |
| `criteria_link` | запись `[[checklist]]` из criteria.toml №05 (`CL01…CL14`) и её критерии |
| `note`, `evidence`, `finding_ids`, `changes`, `source` | обоснование по-русски, опоры, причины изменений и место строки в шаблоне |

* Строка о согласовании («…согласовано с архитекторами») заполняется по отдельности. `available = yes`
  подкреплено опорой, а `checked = unknown` с примечанием «требует подтверждения» и ссылкой на пустой блок
  согласующих. Дефект архитектуры при этом виден в `machine`, но ячейку «Проверено» не заполняет.
* Если в примечании шаблона есть «… — чек-лист» (ИБ, архитектура), положительный итог оставляется
  профильному чек-листу. Отрицательный вывод по найденным замечаниям ставится.
* Без модели (`ask is None`) по умолчанию действует `complete = False`: «Да» по отсутствию замечаний не
  ставится, а «Нет» по найденным замечаниям ставится.
* Связь «критерий → строка» берётся из `[[checklist]]` в `criteria.toml` №05 через
  `bcc_review.criteria.load_criteria()`: регулярное выражение `match` и список `criteria`. Как
  замечание относится к строке:
  * строки-свойства (бизнес-покрытие, структура, тестируемость, противоречия, влияние) — по критерию;
  * строки-артефакты (sequence, UI, данные, архитектура, процесс, интеграция, версия, откат) — только
    при опоре в разделе своей темы;
  * строка ИБ — при признаке ИБ в замечании.

  Для другого шаблона без записей №05 темы берутся из `bank_topics` или встроенной таблицы по кодам
  контракта.

## Сценарии

Модуль извлекает из текста:

* диапазоны: «от A до B», «A–B» в колонке Logic, «не менее / не более / не превышает / больше / меньше», «до N»;
* включённость границ: «включительно» и «(включительно)», по соседнему правилу («обе границы включены»);
  «до N» без «включительно» — граница открыта до решения владельца;
* целочисленность, единицы, шаг 0,01 ₸ при суммах в тиынах;
* правило и часовой пояс расчётного месяца, включаемые и исключаемые операции, возврат;
* порог срабатывания, лимит уведомлений, сброс при смене порога;
* повторную доставку события, срок НФТ;
* метод, параметры, статусы и примеры ответов API.

Значения у границ берутся с шагом диапазона (`values.step`, единица — `values.unit`): у известной границы —
пара «за границей / на границе»; у открытой — ещё и соседнее значение внутри (его исход от решения не
зависит); у одностороннего лимита («до N», «не более N») — всегда три точки «N − шаг, N, N + шаг». Для суммы
одной операции (перевод, платёж, покупка) исход — «операция на X проводится / отклоняется», сообщение об
отказе берётся из правила «… сверх лимита отклоняется с сообщением «…»».

Поля сценария:

* `precondition`, `action`, `expected`, `gherkin` («Дано / Когда / Тогда»);
* `req_ids`, `obligation` (атомарное предложение или строка таблицы с опорой), `evidence`, `values`;
* `status`: `draft`, `open` или `agreed`.

Когда правила дают два исхода, сценарий получает статус `open`: в нём есть `open_question` и `options`
с опорой на каждый вариант. `open_question_id` модуль ставит, только если вызывающий передал `questions`
(даже пустой список) и тем самым обязуется добавить `collect_questions(pack)` в `Report.questions`.
Иначе поле остаётся `null`, а в предупреждения пишется `bank.questions_unlinked`. Так `verify` №07 не
находит висячих ссылок. Решение владельца (`Decision.answer`: «A»,
«вариант B», «Б)», подпись варианта) переводит сценарий в `agreed` с конкретным `expected`, `decision_id`
и записью в `changes`. Один вопрос может закрыть несколько сценариев: например, Q-03 закрывает все три
недопустимые суммы в API.

Неоднозначность (`ambiguity`, `unverifiable`) на цитате самой границы — причина открытого вопроса о
включённости: она попадает в `open_question.finding_ids`, а если №08 уже задал вопрос по этому замечанию,
сценарий берёт его id (второй вопрос о том же не заводится). Буква решения на такой вопрос относится к
вариантам №08, поэтому включённость берётся из текста выбранного варианта, примечания и правок владельца
(«Формулировка: … до N ₸ включительно» — включена, «… меньше N ₸» — нет). Если ответ включённость не задаёт
(«B. Оставить как есть, риск принят», та же формулировка «до N»), сценарий остаётся открытым, в
предупреждениях — `bank.decision_unmapped`.

Строка «Требование может быть протестировано» связана с граничными сценариями: замечание, из-за которого
исход на границе открыт, блокирует её («Нет»); пока граничный сценарий открыт без замечания, «Да» не
ставится. Когда решение владельца согласовало все такие сценарии замечания, оно снимается с этой строки
(`machine.resolved`, запись «Нет → Да» в `changes` с `decision_id`); остаётся в `finding_ids`, а примечание
говорит, изменена ли формулировка документа. Другие строки решение не снимает: дефект текста остаётся до
новой редакции.

Строки «не покрыто» №06 (`Coverage.status = uncovered|partial`, `obligation`) сначала сопоставляются с
готовыми сценариями (поле `covers_gaps`). Для остальных создаётся адресный черновик `coverage_gap`.
Свидетель конфликта (`Finding.witness`) присоединяется к сценарию с обеими опорами, иначе становится
отдельным сценарием `conflict`.

LLM вызывается только после правил: этап `bank#checklist` для нераспознанных строк шаблона и
`bank#scenarios` для требований без сценариев. Схемы строгие, payload имеет вид `{task, input, context}`.
Ответ модели проверяет код:

* цитата должна найтись в блоке;
* числа должны выводиться из текста документа;
* `req_id` должен быть известен.

Отклонённое попадает в `warnings`.

## Как проверить

```bash
pip install -e ".[all,dev]"
python -m pytest tests/p10 -q
python -m pytest tests/contract tests/integration -q
python -m bcc_review release/input/requirements.md out/requirements.md --offline-lint --no-cache
python -m bcc_review verify out/requirements.json release/input/requirements.md
python -m tests.p10.make_samples
```

* `python -m pytest tests/p10 -q` — 76 passed (Python 3.11 и 3.13).
* `python -m pytest tests -q` — 1247 passed, 15 skipped, 7 failed; те же 7 падают и на чистом 11a8f1f
  (p04, p08, p09, p11, p14, p15, p16 — вне `bank/`), там 1231 passed.
* `python -m pytest tests/contract tests/integration -q` на 2821989 + №10 — 167 passed; интеграционные
  тесты движка идут через модуль `team:bcc_review.bank.checklist`.
* Выданное ТЗ после правок границ: те же 36 сценариев (ключи, исходы, статусы) и те же отметки 14 строк,
  что и на 11a8f1f; в JSON добавились только поля `values.step` и `machine.resolved`.
* Публичный вход на выданном ТЗ (`release/input/requirements.md`, SHA-256 `e7dae55e…74381`): в паспорте
  `run.modules.build_bank_pack = team:bcc_review.bank.checklist:build_bank_pack`, 14 строк чек-листа,
  `verify` = OK. Офлайн (`--offline-lint`) этап `bank` = `partial`, 0 вызовов; с
  `--provider mock --mock-script tests/integration/fixtures/mock_bcc.json` — `ok`, 1 вызов.
* `python -m tests.p10.make_samples` пересобирает образцы в `tests/p10/samples/` (JSON и Markdown до и
  после решений; `limit_pack*` — лимит операции до решения, после решения и чистый контроль).

### Лимит операции: неоднозначная граница → тест банка

Вход — `fixtures/operation_limit.md`: Л-1 «Сумма одной операции перевода — до 500 000 ₸. Сумма задаётся целым
числом тенге», Л-2 «Перевод сверх лимита отклоняется с сообщением «Превышен лимит операции»». Помощники —
`limit_case.py`, вопрос строит настоящий `build_questions` №08 без модели.

| Точка (₸, шаг 1 ₸) | До решения | После «до 500 000 ₸ включительно» | После «меньше 500 000 ₸» |
| :--- | :--- | :--- | :--- |
| 499 999 (порог − 1) | проводится (проверяемо) | проводится | проводится |
| 500 000 (порог) | открыт до решения Q-01 | проводится | отклоняется с сообщением |
| 500 001 (порог + 1) | отклоняется с сообщением (проверяемо) | отклоняется с сообщением | отклоняется с сообщением |
| CHK-02 «может быть протестировано», «Проверено» | Нет (F-LIM) | Да, `changes`: Нет → Да (`answer:Q-01`) | Да |

Чистый контроль — тот же документ с «до 500 000 ₸ включительно» / «(включительно)» / «не более» /
«не превышает»: три исхода как после решения «включительно», вопросов нет, блокеров нет (без модели —
«не определено», но не «Нет»). Движок: `fixtures/mock_operation_limit.json` — запись mock-транспорта для
этапа `individual` (неоднозначность на «до 500 000 ₸»); `mock_operation_limit.revised.json` — ответ на
редакцию после `--answers` (замечания нет). Обе записи составлены вручную, это не ответы реальной модели.

| Проверка | Тест |
| :--- | :--- |
| 14/14 строк в исходном порядке, допустимые отметки ячеек (настоящий загрузчик и два синтетических) | `test_all_14_template_rows_in_source_order_with_allowed_marks` |
| согласование: наличие «Да» с опорой, «Проверено» требует подтверждения | `test_approval_row_has_separate_presence_and_confirmation` |
| интервал 1 000–1 000 000 → 5–9: пары у границ 4/5 и 9/10, в коде нет чисел кейса | `test_changed_range_5_9_moves_boundary_pairs_to_4_5_and_9_10`, `test_no_case_numbers_hardcoded_in_source` |
| неоднозначный расчётный месяц: открыт до решения, после решения конкретный исход со ссылкой | `test_ambiguous_settlement_month_open_then_agreed_with_reference` |
| ТЗ без банковской таблицы: явная пометка, таблицы API не принимаются за чек-лист | `test_without_bank_table_absence_is_explicit_and_api_tables_are_not_mistaken` |
| ложное срабатывание: текст строки шаблона не доказывает наличие раздела | `test_presence_is_not_taken_from_checklist_row_itself` |
| другой шаблон: одна колонка отметок, «Н/П» с основанием, отметка автора | `test_other_template_rows_marks_and_not_required_basis` |
| пересчёт после `--answers` и перепроверки с причинами | `test_recheck_after_answers_recalculates_rows_with_reasons`, `test_owner_decision_confirms_approval_with_reason` |
| сквозной `run_review` (mock и none): движок берёт модуль `team:`, Report валиден, опоры сходятся, `verify` №07 = OK | `test_engine_end_to_end_uses_bank_module` |
| привязка строк к критериям по `[[checklist]]` №05 без ложных «Нет» у ИБ и UI | `test_team_criteria_toml_checklist_rows_link_criteria` |
| иная тема со своим набором пунктов (`fixtures/other_topic_checklist.md`): строки и колонки — из документа, ни одной из 14 банковских формулировок в выходе, границы «от 1 до 3 … включительно» → 0/1/3/4 | `test_other_topic_uses_its_own_items_and_no_fixed_bank_wording` |
| документ кэшбэка без таблицы (`release/input/other_topic_cashback.md`): чек-лист пуст, банковских строк нет | `test_release_cashback_without_table_has_no_bank_rows` |
| у отметки «Нет» опора — цитаты блокирующих замечаний | `test_no_row_evidence_is_quoted_from_the_blocking_findings` |
| лимит «до N ₸»: N−1 и N+1 проверяемы, N открыт на вопросе №08, CHK-02 «Нет» с F-LIM | `test_before_decision_verifiable_expectations_are_separated_from_undecided` |
| решение владельца («включительно» / «меньше»): три конкретных исхода в ₸, CHK-02 «Нет → Да» с `decision_id` | `test_owner_decision_gives_concrete_expectations_for_three_points` |
| answers.md → `parse_answers` №08 («A» + «Формулировка: …»): включённость из `wording` | `test_answers_md_parsed_by_module_08_reaches_the_boundary` |
| ответ без включённости («риск принят», снова «до N»): сценарий открыт, `bank.decision_unmapped` | `test_decision_that_does_not_fix_the_boundary_keeps_it_open` |
| чистый контроль (4 формулировки × с моделью/без): нет вопроса и блокера | `test_clean_inclusive_boundary_has_no_extra_blocker` |
| открытая граница без замечания: строка не «Да» | `test_open_boundary_without_finding_is_not_reported_as_testable` |
| движок на записи mock: `team:` против `BCC_FORCE_FALLBACK=build_bank_pack`, `verify` = OK | `test_engine_team_module_vs_fallback_on_limit` |
| движок `--answers` → редакция «включительно» → три исхода, CHK-02 «Да», `diff.resolved` | `test_engine_answers_cycle_revision_gives_clean_boundary` |
| диапазон без включённости: соседи внутри (6 и 8) проверяемы | `test_range_without_inclusivity_keeps_boundaries_open` |

## Передача соседям

* **Max (перенос в интеграцию).** Ветка `claude/stoic-pasteur-sbuepk` (продолжение 11a8f1f из
  `claude/jolly-dijkstra-oakxea`) уже содержит `bcc/integration` 2821989; её отличие от интеграции — только
  `src/bcc_review/bank/` и `tests/p10/`. Перенос одной командой
  без истории ветки: `git checkout <SHA> -- src/bcc_review/bank tests/p10`, затем
  `python -m pytest tests/p10 tests/contract tests/integration -q`. Резерв
  `runtime/fallback/bank.py` можно оставить: движок сам выбирает модуль `team`.
* **Max (движок).**
  1. В `run_bank` передавать `coverage=coverage, questions=questions`. При `--compare` или повторе после
     `--answers` передавать ещё `previous=<прежний report>`, а `complete=` — по `run.status`.
  2. Вместе с `questions=` добавлять `collect_questions(bank)` в `report["questions"]`. Тогда вопросы
     `Q-CHK-NN` и `Q-BANK-xxxxxx` попадут в answers.md, а `open_question_id` будет заполнен. Сейчас
     движок их не передаёт, поэтому поле `null`, а решения применяются только к вопросам пакета.
  3. Предупреждения модуля — строки контракта `Warning` (класс `BankWarning(str)`), поэтому они
     переживают `as_plain` и `str(w)`. Код доступен как `w.code`, данные — через `w.as_dict()`.
     Префикс «bank:» получает только отказ модели, чтобы этап отметился `partial`.
  4. Предложение схемы пакета для контракта: `tests/p10/bank_schema.json`.
  5. Лимит операции через движок (проверено на записи mock, `test_engine_team_module_vs_fallback_on_limit`):
     без `questions=` открытый TC на границе остаётся на своём `Q-BANK-F15769`, хотя №08 задал `Q-01` по
     тому же `F-001`; решение по `Q-01` без правки текста этот TC не закрывает. С `questions=questions`
     сценарий берёт `Q-01` и закрывается решением (`test_owner_decision_gives_concrete_expectations_for_three_points`).
     Путь с правкой (`--answers` с «Формулировка: …») работает и сейчас: редакция даёт чистую границу.
  6. Что отработало — в `run.modules.build_bank_pack`: `team:bcc_review.bank.checklist:build_bank_pack`
     (три граничных сценария, CHK-02 по F-001) или `fallback:bcc_review.runtime.fallback.bank:build_bank_pack`
     (сценариев нет, строки `CL-NN` с `unknown`). Сравнение — `BCC_FORCE_FALLBACK=build_bank_pack`.
* **№08.** Буква «A» («Уточнить формулировку») вместе со строкой «Формулировка: …» правку текста не даёт
  (`[needs_wording]`); правка применяется к ответу своими словами. Банк в обоих случаях берёт
  включённость из формулировки, но редакцию документа создаёт только второй.
* **№05.** `[[checklist]]` уже используется. У CL11 (ИБ) критерии `complete` и `feasible` слишком
  широкие, поэтому модуль требует признак ИБ в `title` или `impact`: вида «ИБ» в `FINDING_KINDS` нет.
  Для других шаблонов можно задать `bank_topics = [...]`. Темы перечислены в
  `bcc_review.bank.checklist.TOPICS`.
* **№06.** Пробел покрытия задаётся одной записью `Coverage` на обязательство со статусом `uncovered` или
  `partial`. Текст пробела — в `obligation`.
* **№08.** У `Question.finding_ids` должен быть ID конфликта: по нему открытый сценарий принимает ID вашего
  вопроса. `Decision.answer` — буква варианта или его подпись.
* **№13 и №17.** Показывайте `cells.*` (исходные «Да/Нет/Не требуется») и `approval.status`. Для
  сценариев: `status`, `options`, `changes`, `notes`, `source_ids`. Пример вывода — `render_markdown`;
  образцы лежат в `samples/`.
