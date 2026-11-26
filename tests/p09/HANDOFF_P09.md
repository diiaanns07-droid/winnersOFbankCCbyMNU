# №09 · Сравнение редакций без ложных закрытий — передача

Модуль: `src/bcc_review/decisions/diff.py`. Тесты и фикстуры: `tests/p09/`.
Зависимостей вне стандартной библиотеки нет. Python 3.11+.

## Интерфейс

```python
from bcc_review.decisions.diff import compare_reports, to_view, render_markdown

diff = compare_reports(previous_report, current_report)          # dict по контракту v1
diff = compare_reports(previous_report, current_report, ask=ask)  # ask(stage, payload, schema) движка, необязательно
view = to_view(diff)           # компактные строки для HTML и веб-демо (№13, №15)
md   = render_markdown(diff)   # раздел «Сравнение с прошлой редакцией» для OUTPUT.md
```

Результат: `{resolved, persisting, introduced, unassessed, warnings, basis}`.

* Каждое замечание прошлого отчёта встречается **ровно один раз** в `resolved` («исправлено в тексте»),
  `persisting` («сохранилось») или `unassessed` («нужно подтверждение»).
* Каждое замечание нового отчёта встречается **ровно один раз** в `persisting` или `introduced`
  («новое замечание»).
* Запись: `id` (RES-/PER-/CHK-/NEW-n), `status`, `status_ru`, `old_ids`, `new_ids`, `reason`, `reason_code`,
  `old_evidence` (опоры прошлой редакции, у каждой `verified`), `new_evidence` (опоры новой редакции),
  `severity {old,new}`, `severity_change` (raised|lowered|null), `requirements` (связи пунктов),
  `decision_refs`, `view`. У неподтверждённых записей есть ещё `recheck` (запрос движку) и, при
  неоднозначности, `candidates`. У закрытых есть `proof`. У новых есть `origin`
  (new_text|existing_text) и, при сомнении, `possible_old`.
* `warnings`: `[{code, message}]`. `basis`: хеши обоих входов (`source_sha256`, `report_sha256`), статусы
  прогонов, `same_source`, `requirement_map` (old_ids → new_ids, relation, changes).
* Порядок детерминирован. Внутри списка записи идут по серьёзности, затем по месту в документе, затем по
  id. От порядка массивов во входе результат не зависит (проверено тестом), меняется только
  `report_sha256` входа.

## Правило закрытия (`resolved`)

Все условия должны выполниться по порядку. Первое невыполненное даёт `unassessed` с кодом причины.

| # | Условие | Код при нарушении |
|---|---|---|
| 1 | `current.run.status == "complete"` | `run_incomplete` |
| 2 | Редакция другая (`source_sha256` различается). Ответ по `--answers` без правки текста не закрывает | `answer_only` / `text_unchanged` |
| 3 | Затронутое обязательство найдено в новой редакции | `obligation_missing` (подтип: `section_missing` / `extraction_gap` / `removed`), `alignment_ambiguous` |
| 4 | Текст в месте опоры изменился | `anchor_unchanged` |
| 5 | Явная перепроверка в новом отчёте: положительная проверка (`checks[]`) по тому же критерию на всех сопоставленных пунктах. Для **противоречия**: проверка охватывает обе стороны, сценарий совпадает с `witness.input`, у каждой стороны проверенная опора. Для **пропуска**: опора на текст, которого не было в прошлой редакции | `recheck_missing` / `recheck_failed` / `recheck_skipped` |
| 6 | В новом отчёте нет похожей находки рядом | `ambiguous_match` |

Тишина второго вызова модели, принятое решение и удаление источника ничего не закрывают.

## Сопоставление

* **Требования.** Шаги: тот же нормализованный текст → разделение (вложение шинглов ≥ 0.75, части
  покрывают ≥ 0.75 целого) → слияние → 1:1 по сходству (0.5 × Dice основ + 0.5 × SequenceMatcher,
  уверенно от 0.55; от 0.40 только при совпадении номера или раздела и отрыве ≥ 0.08). Остальное либо
  неоднозначно (кандидаты), либо исчезло (объясняется причина). Номер (`source_id`) и раздел только
  добавляют надбавку и сами пару не решают. Номера строк и порядковые id не используются.
  Обоснование порогов на маленьком примере кейса: `test_p09_false_positive.py`.
* **Замечания (первопричины).** Учитываются место (перекрытие опор; общее требование даёт только нижнюю
  границу 0.4), тип (kind и criterion), предмет (заголовок). Серьёзность в сопоставлении не участвует,
  поэтому её смена — это `persisting` с `severity_change`, а не новое замечание.
* `ask`: только для неоднозначных пар требований, стадия `diff_identity`. Ответ принимается, если
  обе цитаты модели дословно есть в текстах. Даже принятый ответ ничего не закрывает: условие 5
  остаётся.

## Что читаю из Report v1 (сверить с `contracts/v1.json`, когда появится)

| Поле | Как используется |
|---|---|
| `run.status`, `run.source_sha256`, `run.mode`, `schema_version` | условия 1–2, предупреждения |
| `document.id/blocks/warnings` | проверка опор `block.text[start:end] == quote`, поиск цитат, причины «раздел не извлечён» |
| `requirements[]` `{id, source_id, text, block_ids, evidence}` | сопоставление пунктов |
| `findings[]` `{id, status, scope, kind, criterion, severity, title, impact, req_ids, evidence, hints, witness, inspected_block_ids}` | первопричины; `witness` означает противоречие, `inspected_block_ids` означает пропуск |
| `checks[]` **(форма в контракте пока не зафиксирована)** — принимаю `{id, scope, req_ids or req_id, criterion, status or result: passed/ok/consistent… или failed/violated… или прочее (=не проверено), evidence[], scenario or witness_input or witness.input, reason}` | условие 5 |
| `coverage` (необязательно): `{requirements: {req_id: [criteria]}, unassessed: [{req_ids, reason}]}` | запасное доказательство для простых дефектов и причины `recheck_skipped` |
| `decisions[]` `{id, finding_ids or finding_id or targets, answer or summary, status, question_id, edit}` | ссылка на решение в записи; `answer_only` |

## Данные для №13 и №15

`to_view(diff)` → `{summary, basis, previous_findings[], new_findings[], warnings[]}`. Строка содержит:
`status_ru, severity_ru, severity_change, entity, title, old_quote, old_loc, new_quote, new_loc,
behavior_change, decision_ref, reason, old_ids, new_ids`.
Готовый пример со всеми четырьмя статусами лежит в `tests/p09/golden/`:
`demo_previous.json` и `demo_current.json` (входы), `demo_diff.json`, `demo_view.json`, `demo_diff.md`.
Эталоны обновляются командой `P09_UPDATE_GOLDEN=1 python -m pytest tests/p09`.

## Команды

```bash
python -m pytest tests/p09 -q
```

```bash
PYTHONPATH=src python -m bcc_review.decisions.diff tests/p09/golden/demo_previous.json tests/p09/golden/demo_current.json -o diff.json --view view.json --md diff.md
```

## Для Max (стык с `--compare`)

* В `__main__` при `--compare PREV.json`: `report["diff"] = compare_reports(json.load(open(PREV)), report)`,
  затем `render_markdown(report["diff"])` в OUTPUT.md. В `ask` передавать транспорт движка.
* Для записей `unassessed[*].recheck` со стадией `diff_recheck` движок может выполнить точечную
  перепроверку и записать результат в `checks[]` (для противоречия — со `scenario` = `witness.input` и
  опорами обеих сторон), затем повторить сравнение.
* `run.status = partial`, если хотя бы один вызов модели упал: модуль на это опирается.
* Типы `Report.diff` и `checks[]` нужно внести в `contracts/v1.json`, после чего запустить стыковой тест.
