# №10. Чек-лист банка и приёмочные сценарии

Код: `src/bcc_review/bank/checklist.py`, `src/bcc_review/bank/acceptance.py`. Тесты: `tests/p10/`.
База: `bcc/integration` 6a6c503 (контракт v1 431f76d; влиты №01–09, 11–17).

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

* диапазоны: «от A до B», «A–B» в колонке Logic, «не менее / не более / больше / меньше»;
* включённость границ, в том числе по соседнему правилу («обе границы включены»);
* целочисленность, единицы, шаг 0,01 ₸ при суммах в тиынах;
* правило и часовой пояс расчётного месяца, включаемые и исключаемые операции, возврат;
* порог срабатывания, лимит уведомлений, сброс при смене порога;
* повторную доставку события, срок НФТ;
* метод, параметры, статусы и примеры ответов API.

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
pip install -e ".[dev]"
pytest tests/contract tests/p10
pytest tests
python -m tests.p10.make_samples
```

* `pytest tests/contract tests/p10` — 84 passed.
* `pytest tests` — 662 passed, 15 skipped, 1 failed. Нужны `pip install -e ".[all,dev]"`. Падает
  `tests/p11/test_anthropic_success.py::test_from_fixture_files_entry_point`: он зависит от порядка,
  в одиночку проходит и так же падает на базе без №10.
* `python -m tests.p10.make_samples` пересобирает образцы в `tests/p10/samples/` (JSON и Markdown до и
  после решений).

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

## Передача соседям

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
