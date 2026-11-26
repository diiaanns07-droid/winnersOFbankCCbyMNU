# Интеграция v2: сводка №01

Ведёт №01. Обновляется на каждом цикле интеграции (в начале часа) и при каждом объявлении.
Интеграционная ветка — `bcc/v2`. В неё сливает только №01 (`git merge --no-ff`).

## Объявления (новые сверху)

* **27.11 02:48 — КАРКАС В `bcc/v2`, ВСЕ ВЕТКИ v2/02…16 СЛИТЫ (`09f0dfb`).** Координатор каркас не прислал,
  его написал №01 (`0dd6619`) под интерфейсы, которые вы уже используете. Сделайте сейчас:
  `git fetch origin && git merge origin/bcc/v2`, `python -m pytest tests/v2 -q`, push.
  * Установка для `python -m bcc_review`: `pip install --no-deps -e .` (или `PYTHONPATH=src`). Тесты видят `src/`
    сами (`tests/v2/conftest.py`).
  * Полный прогон: `python -m bcc_review release/input/requirements.md out/r.md --provider claude_cli --model sonnet`
    (mock: `--provider mock`, без модели: `--provider offline`). Рядом пишутся `.json` и `.html`.
  * **Перезапуск одного этапа на готовых входах:**
    `python -m bcc_review stage lens_analyst --doc release/input/requirements.md --from runs/<id> --provider claude_cli --model sonnet`
    — этапы `segment, lens_analyst, lens_qa, lens_architect, lens_risk, consistency, judge, clarify`; остальные этапы
    берутся из `--from`, код (правила, сверка цитат, вердикт, отчёт) пересчитывается; `--downstream` — перезапустить
    и следующие этапы модели (для линзы — судью и вопросы). Новый прогон — в `runs/<новый id>`, отчёт —
    `runs/<новый id>/report.md` (или `--out`).
  * Артефакты: `runs/<id>/stages/<этап>.json` = `{stage, status, seconds, calls, error, input, output, warnings}`,
    `runs/<id>/trace.jsonl` (каждый вызов модели), `runs/<id>/report.{md,json,html}`.
  * Кэш ответов модели — `.bcc_cache/v2/` (ключ: провайдер, модель, system, user, схема); `--no-cache` — мимо кэша.
* **27.11 01:31** — ветка `bcc/v2` создана от `origin/claude/gallant-gauss-vbjqc8` (`c0b8368`) и запушена.

## Красное после слияния — владельцам

`python -m pytest tests/v2 -q` на `09f0dfb`: **634 passed, 3 failed**. Каждая ветка по отдельности зелёная, падает
сочетание:

| Тест | Владелец | Причина | Что сделать |
| :--- | :--- | :--- | :--- |
| `test_06_lens_qa.py::test_clean_bases_have_no_conflicts[autopay.base, cardblock.base]` | №06 (+№04) | записанные ответы `06_qa/*.haiku.json` сделаны на нарезке №01 (`f26f06a`), а №04 перезаписал `tests/v2/fixtures/<база>/segment.json` своей нарезкой — ID строк приёмки сместились (`R-14`, `R-15`) | №06: перезаписать ответы на текущей нарезке (`stage lens_qa --from …`) или сопоставлять строки приёмки по цитате, а не по ID |
| `test_11_recheck.py::test_apply_answers_changes_verdict` | №11 (+№10) | с настоящим `stages/judge.py` новые кандидаты recheck не становятся `D-29`: `new_findings == []` | №11: в тесте подменять `judge.run` или принимать ID судьи |

## Как №01 сливает ветку

Ветка считается готовой к слиянию, если:

1. `docs/plan-v2/status/NN.md` в ветке обновлён: SHA, «как проверить», что готово к слиянию;
2. ветка содержит последний `origin/bcc/v2` (`git merge origin/bcc/v2`) или сливается без конфликтов;
3. `python -m pytest tests/v2 -q` зелёный на результате слияния;
4. mock-прогон `python -m bcc_review release/input/requirements.md out/mock.md --provider mock` даёт отчёт;
5. изменены только файлы владельца (CONTRACT.md, раздел 1). Чужие файлы — причина вернуть ветку.

Красную ветку №01 не вливает и пишет в таблицу ниже, что сломано. Исправляйте у себя и пушьте — на следующем
цикле №01 проверит снова.

## Ветки исполнителей

| № | Ветка | Слито в `bcc/v2` | Тесты после слияния | Заметки |
| :--- | :--- | :--- | :--- | :--- |
| 01 | `bcc/v2` | `09f0dfb` | 634/637 | каркас `0dd6619` |
| 02 | `v2/02-providers` | `d8bc983` | ✅ | `v2/__init__.py`, `providers/__init__.py` — версия каркаса |
| 03 | `v2/03-docview` | `381e038` | ✅ | |
| 04 | `v2/04-segment` | `438169d` | ✅ | перезаписал фикстуры баз → красный тест №06 |
| 05 | `v2/05-analyst` | `7e03eda` | ✅ | |
| 06 | `v2/06-qa` | `caff94d` | ❌ 2 | см. «Красное» |
| 07 | `v2/07-architect` | `568e0f4` | ✅ | `SCHEMA` модуля линзы подхватывается `lens.run` |
| 08 | `v2/08-risk` | `8a22fa2` | ✅ | `dropped` → `rejected` отчёта (`reason_code = lens_dropped`) |
| 09 | `v2/09-consistency` | `0235e2d` | ✅ | |
| 10 | `v2/10-judge` | `e954e60` | ✅ | `prompts/judge_check.md` — ваш файл, внесён в контракт |
| 11 | `v2/11-clarify` | `8f367d6` | ❌ 1 | см. «Красное»; `examples/v2/answers.md` — ваш файл, внесён в контракт |
| 12 | `v2/12-rules` | `4b4524e` | ✅ | |
| 13 | `v2/13-report` | `7f3adfb` | ✅ | |
| 14 | `v2/14-html-web` | `b0ca566` | ✅ | |
| 15 | `v2/15-eval` | `270983c` | ✅ | |
| 16 | `v2/16-release` | `825716f` | ✅ | |
| 17 | `eval/blind-v2` | не сливается | — | отдельная ветка жюри |

## Сквозные прогоны `bcc/v2`

| Время | SHA | Провайдер / модель | Статус | Вызовов | Время | К1–К5 | Замечаний (cr/maj/min) | Строк отчёта |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 02:48 | `09f0dfb` | mock (пустые ответы линз) | complete | 9 | 1 с | — | 0/0/0 | — |

## Решения интегратора

* **02:45.** Каркас написан №01 (координатор не прислал к 02:35). Ответы на просьбы из статусов — в CONTRACT.md,
  раздел 9 «Решения №01».
* **01:35.** Нумерация PDF в `try_prompt.py` проверена на `release/input/requirements.pdf`: 128 строк, 6 страниц,
  префикс `[с.N]`. Нужен пакет `pymupdf` (`pip install pymupdf`), без него читатель v1 падает с понятной ошибкой.
