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
