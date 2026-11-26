# Решения владельца: вопросы → ответы → редакция (№08)

Модуль `src/bcc_review/decisions/` превращает подтверждённые находки в вопросы
владельцу продукта, читает его ответы и готовит правки «было → стало». Закрытие
замечания засчитывается только после повторного анализа реально записанной
редакции.

Всё в этой папке относится к **синтетическому документу**: тема — досрочное
погашение кредита, комиссия и график платежей. Ответы в `answers_team_*.md` —
**демонстрационные ответы команды**, а не решения владельца продукта.

## Файлы

| Файл | Что это |
| :--- | :--- |
| `synthetic_loan_tz.md` | «До»: синтетическое ТЗ с двумя независимыми конфликтами (комиссия; перенос платежа), неоднозначностью, на которую документ отвечает сам («банковский день» ↔ раздел «Термины»), и пропуском лимита |
| `answers_team_A.md` | Заполненный файл вопросов. Q-01=A, Q-02 отложен, Q-03 — свой ответ с «Формулировка:», Q-04=A |
| `answers_team_B.md` | Другие ответы на те же вопросы: Q-01=B, Q-03=B (вариант с выдуманным лимитом, в редакцию не попадает), Q-02 и Q-04 пусты |
| `answers_html_export.md` | Эталон минимального экспорта из HTML №13 (только `## Q-NN` и `Ответ:`) |
| `generated/` | Вывод `demo`: копия «до», `questions.md`, `revision_{A,B}.md` («после»), манифесты `*.revision.json`, сводки `*.apply.md`, итоги повторного анализа `*.closure.json` |

## Повторить (№18)

Без ключа и сети: находки подставные, транспорт `ask` подставной, повторный
анализ — подставная перепроверка `_demo.recheck`, которая читает файл редакции
с диска.

```bash
python -m pip install -e ".[dev]"
```

```bash
python -m bcc_review.decisions demo --out /tmp/p08_demo
```

```bash
diff -r /tmp/p08_demo examples/team_answers/generated && echo "совпадает"
```

```bash
python -m pytest tests/contract tests/p08
```

Ожидаемо: `diff` пустой; `tests/contract` — 29 passed, `tests/p08` — 113 passed.

Штатный путь через движок (`python -m bcc_review … --answers`, экспорт №13,
другой SHA, коллизия) с парой входов и выходов для №09 и №18 описан в
[`engine_cli/README.md`](engine_cli/README.md). Два вопроса к разным сторонам одного
противоречия, ответ на один, «нужно уточнить» и повторный импорт — в
[`two_sided/README.md`](two_sided/README.md).

Результат `demo`:

| Вариант | Q-01 комиссия | Q-02 перенос платежа | Q-03 мин. сумма | Q-04 банковский день |
| :--- | :--- | :--- | :--- | :--- |
| A | A → закрыто | отложен → конфликт остаётся | свой (10 000 ₸ от владельца) → закрыто | A → закрыто |
| B | B → закрыто | пусто → конфликт остаётся | B: выдуманный «50 000 ₸» отклонён → остаётся | пусто → остаётся |

В редакции B исчезает только конфликт о комиссии. Независимый конфликт о
переносе платежа (`N-02`) остаётся в обеих редакциях и уходит к №09.

## Формат `answers.md`

`parse_answers` одним кодом читает три формата:

1. экспорт HTML №13 (`format: bcc-review-answers/1`): фронтматтер с
   `source_sha256`, `## Q-01`, строка `Варианты: A. … | B. …`, заголовок
   `### Ответ` и текст ответа ниже, экранирование `\#` снимается;
2. резервный формат движка: `Ответ: …` и строки `Правка: «старое» → «новое»`;
3. файл вопросов №08 (ниже).

По букве варианта правка восстанавливается без доступа к отчёту. Каждая
проверенная правка варианта дописана в `Question.options` как
`· Правка [b0009]: «было» → «стало»`, и экспорт №13 печатает эту строку в файл.
Явная строка `Правка:` в ответе владельца важнее правки варианта в том же месте.

```text
<!-- bcc-review:answers v1 -->
source_sha256: <64 hex — SHA-256 исходного документа>

## Q-01            ← заголовок ## или ###, дальше любой текст карточки
Ответ: A           ← всё после «Ответ:» до следующего ## Q-… — это ответ

## Q-03
Ответ:
многострочный ответ
Формулировка: новый текст предложения
```

* В карточке №08 есть та же машинная строка `Варианты: …`, что у №13.
* Пустой ответ, «—» или «?» — вопрос остаётся открытым.
* `A` / `B. комментарий` / `Вариант C` — выбран вариант. Кириллические «А», «В»,
  «С» читаются по начертанию, «Б» — как B. Кириллическая буква без точки или
  тире после неё («В течение…») считается своим ответом.
* `отложить` — решение отложено, документ не меняется.
* «нужно уточнить» (и «надо уточнить», «требует уточнения», «не знаю») — решения нет:
  вопрос остаётся открытым, `decision_status: needs_clarification`, текст ответа сохраняется в
  `Report.decisions`, правок нет.
* Другой текст — свой ответ. Без строки `Правка: «…» → «…»` или `Формулировка:`
  решение сохраняется, но текст документа не меняется. `Формулировка:` требует
  цитату вопроса, поэтому в файле №13 надёжнее писать `Правка:`.
* `A, B` — выбрано несколько вариантов, решение не принимается.
* Допускаются `**Ответ:**`, CRLF, BOM, NBSP и HTML-комментарии.
* Ошибки и предупреждения разбора: `[no_sha]`, `[sha_conflict]`,
  `[stale_answers]` («ответы относятся к другой редакции …»), `[unknown_id]`,
  `[duplicate_id]`, `[duplicate_conflict]`, `[missing_card]`, `[no_answer_field]`,
  `[collision]`. Правки двух решений, пересекающиеся в одном диапазоне,
  отклоняются для обоих решений на разборе: только там видны все ответы сразу.

## Два разных статуса (для №15 и №09)

| Поле | Значения | Кто ставит |
| :--- | :--- | :--- |
| `decision_status` — факт решения | `open`, `needs_clarification` («нужно уточнить» — вопрос открыт), `deferred`, `accepted`, `accepted_needs_wording`, `stale`, `collision`, `blocked`, `invalid` | `parse_answers` (в `Decision.to_dict()`), `apply_answers` |
| `patch_state` — текст | `applied`, `proposed`, `needs_wording`, `already_applied`, `precondition_failed`, `stale`, `collision`, `open`, `deferred` | `propose_patch` / `write_revision` |
| `fix_status` — закрытие | штатный путь движка @2821989: статус «внесено, ожидает проверки» — в манифесте `*.revision.json` (`status: applied_not_verified`, у вопроса `patch_state: applied`); `python -m bcc_review.decisions status PREV.json CUR.json` показывает его по вопросам; `applied_not_verified` → после повторного анализа `closed_after_reanalysis` / `still_present`; для текста без изменений: `open_still_present` / `absent_without_decision`; при анализе не той версии: `applied_unverified` | `closure_status(manifest, new_doc, new_findings)` |

Закрытие требует, чтобы SHA-256 перечитанного документа совпадал с
`revision.sha256` в манифесте. Иначе ставится `[not_reanalyzed]` и статус
«закрыто» не присваивается.

## Стык с движком (Max, `bcc/integration` @ `2821989`, `engine.apply_answers`)

Движок вызывает `parse_answers(path, document, questions=, expected_sha=)`,
`propose_patch(document, finding, decision, question=)` (вопрос и находка — из
`--compare`) и `write_revision(document, edits, output, source=, questions=,
decisions=)`. Решение в `Report.decisions` — это `Decision.to_dict()` на момент
разбора: `decision_status`, `finding_ids`, `choice` и правки (у правок только поля
контракта). Пустой `questions` (без `--compare`) значит «данных о вопросах нет»: ответы
не отбрасываются как неизвестные. Итерация `AnswerSet` отдаёт только решения к текущей
версии.

Вопросы к разным сторонам одного противоречия. Если модель на этапе `clarify`
возвращает несколько вопросов на группу с `target`, или без модели находка о
несогласованности (`set_consistent`, `conflict`, `incorrect`, без witness) опирается на
фразы разных разделов, строится по вопросу на каждую фразу. У такого вопроса есть
`side`, `counterpart_ids`, своя цель правки, и он меняет только свою фразу.

* Точки входа: `bcc_review.decisions.clarify:build_questions`,
  `bcc_review.decisions.patches:propose_patch/write_revision`,
  `bcc_review.decisions.answers:parse_answers(path, document)`.
* `build_questions` возвращает `list[Question]`, где `Question` — подкласс `dict`
  (Question v1). Движок кладёт его в `Report.questions` без преобразований, JSON и
  схема видят обычный объект, атрибуты №08 (`q.id`, `q.option("A").edits`) работают.
* `parse_answers(path, document)` возвращает `AnswerSet`. Как `list[Decision]` он
  итерируется по решениям. Для движка есть `out.get("decisions")` (dict Decision v1
  к текущей версии, с уже разрешёнными правками) и `out.get("warnings")`.
* `propose_patch(document, None, decision)` — вызов движка без вопроса: правки
  берутся из решения. Итог записывается в этот же dict (`edits`, `patch_state`,
  `decision_status`, `fix_status: awaiting_revision`, `note`), и он попадает в
  `Report.decisions`. Прежний вызов `propose_patch(..., question=q)` не изменился.
* `write_revision(document, edits, path, source_path=…)` — как вызывает движок;
  прежний `source=` тоже работает. Записанные правки отмечаются в тех же dict:
  `status: applied_not_verified`, `revision`, `revision_sha256` — «внесено,
  ожидает проверки». Возвращается фактический путь: для PDF/DOCX это `*.md`.
  Чтобы движок читал именно его, нужен `engine_cli/max_engine_apply_answers.diff`.
* Этап модели: `ask("clarify", {task, input, context}, CLARIFY_SCHEMA)`. В `task`
  лежит промпт (`clarify.CLARIFY_INSTRUCTIONS`), в `input` — группы находок с
  цитатами, в `context` — `{"mode": "auto", "block_ids": […]}`. Текст документа
  прикладывает движок. Схема рассчитана на structured outputs: у всех объектов
  `additionalProperties: false` и полный `required`, ограничений `min*`/`max*`
  нет (это проверяет тест). На каждые ≤6 групп уходит один вызов, на малом ТЗ —
  один вызов всего. Каждую правку модели код проверяет сам: `old` должен быть
  точной и однозначной подстрокой `block.text`. Если ask падает (`AskError`,
  `BudgetExhausted`), вопросы строятся по правилам из `witness`.
* Из находок используются поля `id`, `status`, `kind`, `criterion`, `severity`,
  `title`, `impact`, `blocked_decision`, `blocks`, `req_ids`, `evidence`,
  `witness`. Вопросы строятся только по находкам с `status == "confirmed"` и
  опорой, совпадающей с текстом. Редакционные виды находок (`format`,
  `duplicate`, `non_singular`, `traceability`, `design_in_requirement`;
  `terminology` и `placeholder` при `minor`) вопросов не дают. Явный
  `needs_decision: true/false` переопределяет это правило.
* `Report.questions = [q.to_dict() for q in build_questions(...)]`. По контракту
  `options` — это строки «A. метка — наблюдаемый результат»; полные варианты с
  правками лежат в `option_details`, `Question.from_dict` читает оба вида.
* Свой цикл модуля (`apply_answers` + `closure_status`) остаётся для
  `python -m bcc_review.decisions` и демо. Движок им не пользуется.
* Правка переносится в исходный Markdown точно по `loc.map`. Если карты нет,
  работает выравнивание по символам; остальные байты файла не меняются. Для
  бинарного исходника (PDF или DOCX) пишется явная текстовая редакция с
  заголовками разделов и ссылкой на исходник. Если владелец сам подготовил новую
  версию, её принимает `accept_user_revision(base_doc, path, ...)`.
* ID вопросов — `Q-01` (как в задании №08), у Max в примере `Q-001`. Парсер
  принимает `Q-` с 1–4 цифрами.
