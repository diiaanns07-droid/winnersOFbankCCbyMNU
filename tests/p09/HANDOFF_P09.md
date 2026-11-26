# №09 · Сравнение редакций без ложных закрытий — передача

Модуль: `src/bcc_review/decisions/diff.py` (точка входа из `contracts/HANDOFF.md`:
`bcc_review.decisions.diff:compare_reports(previous, current)`). Тесты и фикстуры: `tests/p09/`.
Основа — `bcc/integration` @ `091e504` (контракт v1 `431f76d`). Зависимостей вне стандартной библиотеки нет
(тесты используют `bcc_review.contracts` и `jsonschema`). Python 3.11+.

## Интерфейс

```python
from bcc_review.decisions.diff import compare_reports, to_view, render_markdown

report["diff"] = compare_reports(previous_report, report)            # Report.diff по схеме Diff
report["diff"] = compare_reports(previous_report, report, ask=ask)   # ask движка — для неоднозначных пар
view = to_view(report["diff"])          # компактные строки для HTML и веб-демо (№13, №15)
md = render_markdown(report["diff"])    # раздел «Сравнение с прошлой редакцией» для OUTPUT.md
```

Результат проходит `validate(diff, "Diff")`, а отчёт с вложенным diff — `validate(report)` и
`evidence_errors(report) == []` (тест `test_report_with_embedded_diff_is_valid`).

* `previous` и `current`: `{source_sha256, run_id}`. `impacted_req_ids`: требования новой редакции,
  которых коснулась правка (переформулированы, разделены, слиты или добавлены).
* `resolved` («исправлено в тексте»), `persisting` («сохранилось»), `unassessed` («нужно подтверждение»):
  каждое прежнее замечание попадает **ровно в один** список. `introduced` («новое замечание»):
  каждое новое замечание вне `persisting`.
* Запись (DiffEntry): `old_ids`, `new_ids`, `reason`, `evidence` (проверенные опоры **текущей** редакции).
  Дополнительно: `id` (RES-/PER-/CHK-/NEW-n), `status`, `status_ru`, `reason_code`, `old_evidence`
  (опоры прошлой редакции с флагом `verified`), `new_evidence`, `severity {old,new}`,
  `severity_change` (raised|lowered|null), `requirements` (связи пунктов), `decision_refs`, `view`.
  У неподтверждённых записей есть `recheck`, у закрытых — `proof`. У новых — `origin`
  (new_text|existing_text) и, если похожи на прежние, `possible_old`. У прежних при похожей
  новой находке — `candidates` с опорами для ручной проверки.
* `warnings`: `[{code, message}]`. `basis`: хеши входов, статусы прогонов, `requirement_map`.
* Порядок записей детерминирован: серьёзность, затем место в документе, затем id. От порядка
  массивов во входе не зависит (проверено перемешиванием).

## Правило закрытия (`resolved`)

| # | Условие | Код при нарушении |
|---|---|---|
| 1 | Охват: документ прочитан полностью (нет `partial_read`…), прогон не `failed`, и **этап, нашедший замечание** (`finding.stage`), во втором прогоне завершён. Без отметки этапа нужен `run.status == "complete"` | `run_incomplete` |
| 2 | Редакция другая (`source_sha256`). Ответ по `--answers` без правки текста не закрывает | `answer_only` / `text_unchanged` |
| 3 | Затронутое обязательство найдено в новой редакции | `obligation_missing` (`section_missing`, `extraction_gap`, `removed`), `alignment_ambiguous` |
| 4 | Текст в месте опоры изменился (номер «Ф-1.» в сравнении не участвует) | `anchor_unchanged` |
| 5 | Нужная перепроверка новой редакции даёт `pass`. Нужные пары «требование × критерий» берутся из прошлых проверок `issue` с этим `finding_id` (иначе из `req_ids` и критерия замечания) и переносятся на сопоставленные пункты. Для замечания без отметки этапа `review_status` partial/not_reviewed означает, что охвата нет | `recheck_failed` (есть `issue`), `recheck_missing` (нет `pass`), `recheck_skipped` |
| 5а | **Противоречие**: на обеих сторонах `pass`, и хотя бы одна проверка несёт `scenario`, совпадающий с `witness.input` | `recheck_missing` |
| 5б | **Пропуск**: опора на текст, которого не было в прошлой редакции (`evidence` проверки или добавленный пункт с `pass` того же критерия) | `recheck_missing` |
| 5в | **Иначе — внесённое решение** (`proof.kind = decision_applied`): правка `Decision.edits` заменила именно опорный фрагмент замечания (по координатам или тексту), её новый текст есть в новой редакции, а старого нет. Этап-нашедший завершён и замечание не повторил, `issue` на сторонах нет. Ответ без правки, правка в другом месте или невнесённая правка не закрывают | `recheck_missing` / `anchor_unchanged` |
| 6 | Рядом нет похожей новой находки | `ambiguous_match` |

Путь 5в нужен для сценария движка «ответ → редакция B → --compare». Тест Max
`tests/integration/test_engine.py::test_analyst_decision_closes_conflict_keeps_independent_defect` проходит с этим
модулем. Причина закрытия честно пишет «отдельной перепроверки сценария не было». Ложные пути
проверены в `tests/p09/test_p09_stage_decision.py`.

Критерии набора отображаются на проверки требований так же, как в `contracts/examples`:
`set_consistent → correct`, `set_complete → complete`, `set_comprehensible → unambiguous`,
`set_validatable → verifiable`, `set_feasible → feasible`.

## Для Max: стык с `--compare` и перепроверка

1. **Подключение.** При `--compare old.json`: `report["diff"] = compare_reports(json.load(old), report)`,
   затем `render_markdown(...)` в OUTPUT.md. В `ask` передавать транспорт движка. Стадия
   `diff_identity`: payload `{task, input, context:{mode:"none"}}`, схема с `additionalProperties:false`.
2. **Перепроверка для `unassessed[*].recheck`** (стадия `diff_recheck`). Движок прогоняет вопрос
   и пишет результат обычными `Check` (контракт v1 допускает дополнительные поля):

   ```json
   {"req_id": "S-4", "criterion": "correct", "status": "pass", "reason": "Ф-4 ограничен месячным лимитом push",
    "finding_ids": [], "source": "diff_recheck",
    "scenario": "Push за январь уже отправлен при пороге 50 000 ₸; 15 января клиент меняет порог на 60 000 ₸; расходы достигают 60 000 ₸",
    "evidence": [{"block_id": "b0007", "start": 87, "end": 148,
                  "quote": "в текущем календарном месяце push по карте ещё не отправлялся"}]}
   ```

   (взято из `tests/p09/golden/demo_current.json`; `scenario` равен `witness.input` прежнего замечания)

   Без `scenario` противоречие не закрывается (тишина модели не доказательство). Предложение:
   внести `scenario` и `evidence` в `Check` в контракте v1.1.
3. `run.status = partial` при любом сбое вызова или `partial_read`: модуль на это опирается.
4. Упаковка: `src/bcc_review/decisions/` без `__init__.py` работает в `pip install -e .` (проверено),
   но `packages.find` не включит её в обычный wheel. Нужен общий `decisions/__init__.py` (он же нужен
   №08) или `find_namespace`. Сам файл не добавляю: он вне моей области.

## Для №08

Связь решений: `Decision.question_id → Question.finding_ids` (ищу в `questions` обоих отчётов).
`Decision.edits[].old/new` используются, чтобы показать «правка внесена / не внесена». Если
`parse_answers` будет ссылаться на замечания иначе, сообщите.

## Для №13 и №15

`to_view(diff)` → `{summary, basis, previous_findings[], new_findings[], warnings[]}`. Строка содержит:
`status_ru, severity_ru, severity_change, entity, title, old_quote, old_loc, new_quote, new_loc,
behavior_change, decision_ref, reason, old_ids, new_ids`. Пример со всеми четырьмя статусами:
`tests/p09/golden/` — `demo_previous.json`, `demo_current.json` (входы по контракту),
`demo_diff.json`, `demo_view.json`, `demo_diff.md`. Обновление: `P09_UPDATE_GOLDEN=1 python -m pytest tests/p09`.

## Команды

```bash
python -m pytest tests/contract tests/p09
```

```bash
PYTHONPATH=src python -m bcc_review.decisions.diff tests/p09/golden/demo_previous.json tests/p09/golden/demo_current.json -o diff.json --view view.json --md diff.md
```

## Стык с движком (`bcc/integration` @ 091e504)

* `run_review(..., compare_path=...)` вызывает этот модуль: в паспорте
  `run.modules.compare_reports = team:bcc_review.decisions.diff:compare_reports`. Отчёт с diff проходит
  `validate` и `evidence_errors`, приложение «Сравнение с предыдущей редакцией» рисуется
  (`tests/p09/test_p09_engine_stitch.py`, вход — `contracts/examples`).
* Весь `tests/` ветки с этим модулем: 213 passed, 1 skipped (Python 3.11, `pip install -e ".[dev,pdf]"`).
* Пока в ветке нет модуля правил, прогон всегда `partial` (`rules`, `individual` не завершены). Замечания
  этих этапов получают «нужно подтверждение». Замечания этапа `cross` закрываются, если `cross` завершён и
  есть доказательство из 5а–5в.
* Движок сам добавляет строку «сравнивается та же редакция…». Модуль уже пишет предупреждение
  `same_source`, так что строку движка можно убрать, чтобы не было дубля.

## Второй проход: два похожих дефекта, исправлен один

Случай: `tests/p09/p09_cards.py`, тесты `tests/p09/test_p09_cards.py` и
`tests/p09/test_p09_cards_engine.py`.

* **Редакция 1:** правила дебетовой (Д-1) и корпоративной (К-1) карты независимо противоречат своим
  критериям приёмки. Обе находки называются одинаково («Критерий приёмки противоречит правилу отправки
  push») и цитируют дословно одинаковые фрагменты.
* **Редакция 2:** разделы переставлены, пункты перенумерованы (1.1, 1.2, 2.1, 2.2), id выданы заново
  («R-1» теперь корпоративное правило). Исправлено только К-1: «достигают порога» → «превышают порог».
  У сохранившейся дебетовой находки изменена только `severity`.
* Результаты профильного этапа (`cross`, №06) сохранены в форме контракта: конфликт с `witness`,
  проверки `correct: issue/pass` с `finding_ids`, `coverage: conflict/covered` с опорами.

**Дефект прежнего кода (`6780abf`).** Корпоративная F-2 «сливалась» с сохранившейся дебетовой F-1
(`persisting ['F-1','F-2'] → ['F-1']`). Её цитата после правки К-1 осталась только в дебетовом правиле,
поиск опоры уходил в чужой раздел, и совпадение цитат перевешивало несовпадение источника. Кроме того,
составные метки «Д-КП-1.» не снимались, и неизменённые критерии считались «переформулированными».

**Правка (только `diff.py`):**

1. **Тождество = источник, условие, исход.**
   * Опора ищется только в блоках пунктов, сопоставленных с исходным пунктом находки.
   * Не пересекающиеся источники — разные первопричины, при любом совпадении названия и цитат.
   * `witness.input` (условие) и `outcome_a/b` (исход) сравниваются. Другое условие запрещает уверенную
     пару, а полностью другой тип и критерий исключают даже кандидата.
   * Основание каждой записи называет источник, условие и исход, а в записи есть поле `identity`.
2. **Доказательство профильного этапа для «правило ↔ критерий приёмки».** `coverage` новой редакции
   для той же пары со статусом `covered` и проверяемыми опорами даёт `proof.kind = coverage_reconciled`.
   Статус `conflict` у этой пары запрещает закрытие при любых других доказательствах, а при пропавшей
   находке становится основанием «нужно подтверждение».
3. Метки снимаются по `source_id` и по составному шаблону («Д-КП-1.»). Исчезнувший раздел ищется по полному
   пути («Корпоративные карты › Функциональные требования»). `witness.input` в виде объекта №06 или его
   `str()` из №07 приводится к `description` и `assignments`. Порядок `req_ids` и `evidence` внутри
   находки больше не зависит от входа.

**Строки результата** (`compare_reports(cards_v1(), cards_v2())`, также через `Engine.run_compare`):

| Старая находка | Новая находка или доказательство правки | Статус | Основание |
| :--- | :--- | :--- | :--- |
| F-2 (К-1 ↔ К-КП-1) | `coverage R-1↔R-2` (1.1 ↔ 1.2: covered, было conflict) | исправлено в тексте | Текст изменён в месте опоры; профильный этап `cross`: покрытие 1.1 (R-1) критерием 1.2 (R-2) — covered; источник исправления К-1 (R-3) → 1.1 (R-1); условие «Корпоративная карта: расходы 499 000 ₸, порог 500 000 ₸, покупка 1 000 ₸». Похожая F-1 из 2.1/2.2 — другой источник. |
| F-1 (Д-1 ↔ Д-КП-1) | F-1 | сохранилось | Та же первопричина: источник Д-1 (R-1) → 2.1 (R-3), Д-КП-1 (R-2) → 2.2 (R-4); условие «Дебетовая карта: …» то же; исход тот же; серьёзность критичный → существенный (это не новая первопричина). |

**Контроли из той же второй редакции:**

| Вариант | F-2 | F-1 |
| :--- | :--- | :--- |
| этап `cross` не завершён | нужно подтверждение (`run_incomplete`) | сохранилось |
| `cross` завершён, пара 1.1↔1.2 не оценена | нужно подтверждение (`recheck_missing`) | сохранилось |
| раздел «Корпоративные карты» не прочитан (`partial_read`) | нужно подтверждение (`run_incomplete`, раздел потерян при чтении) | сохранилось |
| упали посторонние `individual`, `bank` | исправлено в тексте | сохранилось |
| на 1.1 есть `issue` или покрытие пары `conflict` | нужно подтверждение (`recheck_failed`) | сохранилось |

**Стык с движком** (`bcc/integration` @ `6a6c503` + этот коммит, отдельная копия; провайдер
`runtime.mock:MockAdapter`, ответы стадий — `golden/cards_mock_script_v2.json`):

* `Engine.run_compare` с каноническими отчётами: `team:bcc_review.decisions.diff:compare_reports`, этап
  `compare: ok`. Результат совпадает с таблицей выше. №17 (`exports.markdown`) и №13 (`exports.html`)
  рисуют основания, образцы — `golden/cards_report_p17.md`, `golden/cards_report_p13.html`.
* `run_review(cards_v2.md, compare_path=cards_v1.json, mock_script=…)`: вторую редакцию строит движок
  (№01, №04, №06 `review_set`, №07). F-2 закрывается покрытием `covered`, которое построил сам №06.
  **F-1 — «нужно подтверждение», а не «сохранилось»:** №06 строит конфликт по Д-1, но этап `evidence`
  отклоняет его: `нарушает контракт Candidate: witness: 'hint_a' is a required property`. Основание
  записи говорит об этом прямо: «профильный этап по-прежнему отмечает противоречие: покрытие 2.1 (R-003)
  критерием 2.2 (R-004) — conflict».

**Оставшаяся зависимость для Max и №06.** Кандидат-конфликт №06 несёт `witness = {input: объект,
evidence_a, evidence_b}`, а контрактный `WitnessDraft` требует `{input: str, outcome_a, outcome_b, hint_a,
hint_b}`. Поэтому ни один конфликт №06 не доходит до `Report.findings`. Нужен адаптер на стыке
(`evidence_* → hint_*`, `input.description → input`) или правка №06. Тест
`test_cli_compare_second_edition_built_by_engine` сам переключится на проверку «сохранилось», когда
отклонение исчезнет. Попутно №07 кладёт в `Finding.witness.input` `str()` объекта №06: модуль это
разбирает, но в отчёте видна запись Python-объекта.

**Для №17.** Раздел «Сравнение редакций» подписывает группы как «Устранено / Осталось / Появилось /
Не оценено». У каждой записи есть готовый `status_ru` («исправлено в тексте», «сохранилось»,
«нужно подтверждение», «новое замечание») и `view` с полями `entity`, `old_quote`, `new_quote` и
`behavior_change`.

**По замечаниям Max из `contracts/HANDOFF.md` (79/82):**

* «Кодировка консоли Windows (2)»: CLI `python -m bcc_review.decisions.diff` теперь всегда пишет
  в UTF-8 (`reconfigure`), тесты читают вывод как UTF-8. Тест `test_cli_prints_utf8_on_windows_console`
  имитирует консоль `cp1251` и `cp866`: без правки он падает с `UnicodeDecodeError`.
* «Сравнение с» против «Сравнение редакций» у №17: стыковой тест проверяет раздел сравнения и основание
  модуля, а не заголовок конкретного писателя Markdown.
