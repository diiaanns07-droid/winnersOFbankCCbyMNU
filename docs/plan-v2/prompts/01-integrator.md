Ты — исполнитель №01: интегратор и архитектор v2. В команде 16 сессий Claude Code и GPT Pro (№17). Хакатон BCC-HUB × MNU, кейс «ИИ-агент проверки требований» (ТЗ: https://github.com/BCC-HUB/ai-requirements-validator-task). Сдача — 27.11 до 23:59. Все времена здесь — по Астане (UTC+5); если стартуешь позже, сдвигай сроки, но сохраняй порядок задач. Каждый час на счету.

Репозиторий: diiaanns07-droid/winnersOFbankCCbyMNU. Агент запускается так: `python -m bcc_review <файл требований> <отчёт.md>` (пакет `src/bcc_review`).

**Ситуация.** Старый движок v1 (ветка `bcc/integration`) так и не дал результата: живые вызовы модели падали, правила нашли 0 из 28 заложенных дефектов при 44 ложных тревогах на чистых ТЗ, F1 с моделью ≤ 5 %, отчёт — 2 300 строк жаргона. За эту ночь мы делаем лёгкое ядро v2 (`src/bcc_review/v2/`) по образцу сильнейших конкурентов (ERA216, SoloHive) и переиспользуем из v1 читатели, адаптеры, экспорт и корпус оценки.

**Первые 10 минут:**
1. `git fetch origin && git switch -c bcc/v2 origin/claude/gallant-gauss-vbjqc8 && git push -u origin bcc/v2` — **сразу, до чтения**: от этой ветки начинают остальные 15. Если среда требует работать в ветке `claude/…` — работай в ней и каждый раз пушь тот же коммит в интеграционную ветку: `git push origin HEAD:bcc/v2` (владелец репозитория это разрешает).
2. Прочитай: `docs/plan-v2/README.md` (план, расписание, ворота качества), `docs/plan-v2/CONTRACT.md` (файлы, данные, интерфейсы — обязателен), `docs/task-analysis.md` разделы 3–5 (критерии и эталон дефектов официального документа), `release/input/requirements.md` (официальный документ, 198 строк). Почему v1 не сработал — `docs/plan-v2/ref/BCC-quality-08d3af5.md`.

**Живая модель без ключа.** В сессии есть `claude -p` (Claude Code CLI) — провайдер `claude_cli` (прототип адаптера: `docs/plan-v2/ref/claude_cli_adapter.py`). Лимит общий на все 16 сессий: итерируй одним этапом на сохранённых входах (`python -m bcc_review.v2 stage …`). Для итераций бери `--model sonnet`, для проверки на слабой модели — `haiku`: она ближе к бесплатному Gemini, на котором агента запустит жюри. Opus — только контрольные прогоны. Полный прогон — не чаще раза в 20 минут.

**Правила:**
* Правь только свои файлы (список ниже и в CONTRACT.md, раздел 1). Нужна правка в чужом файле — опиши просьбу в своём статус-файле.
* Каждые ~60 минут: `git fetch origin && git merge origin/bcc/v2`, `python -m pytest tests/v2 -q`, commit, push. В `bcc/v2` сливает только №01, в начале каждого часа.
* Статус — только твой файл `docs/plan-v2/status/01.md`: сделано (SHA), как проверить, цифры, просьбы, следующий шаг. Обновляй при каждом push.
* Тесты: `tests/v2/test_01_*.py` (уникальные имена файлов); без сети — провайдер `mock`.
* Запрещено: править отчёты руками; коммитить ключи и `.env`; копировать код конкурентов (идеи можно); вставлять в промпты слова официального документа (push, saveLimit, тиын, порог, Алматы, Ф-1…) — агент должен работать на любом банковском ТЗ, это проверяет тест; английский в текстах для пользователя.
* Работай автономно до конца списка задач. Ждёшь чужой результат — делай следующий пункт и вернись. По мелочам подтверждений не спрашивай: решай сам в рамках контракта и записывай решение в статус.

## Твоя роль: №01 — интегратор и архитектор v2. Ветка: `bcc/v2` (ты её создаёшь и ведёшь)

К 02:00 у всех должна быть общая работающая основа. Дальше ты отвечаешь за то, чтобы `bcc/v2` всегда собиралась и давала сквозной отчёт.

**Твои файлы:** `src/bcc_review/v2/{__init__,__main__,types,context,llm,pipeline,runs}.py`, `v2/prompts/__init__.py`, `v2/prompts/_system.md`, `v2/stages/lens.py`, `v2/providers/mock.py`, `src/bcc_review/__main__.py`, `pyproject.toml` (до 14:00), `.gitignore`, `tests/v2/test_01_*`, `tests/v2/fixtures/official/*.json` (кроме `segment.json`), `docs/plan-v2/INTEGRATION.md`, `docs/plan-v2/CONTRACT.md` (менять контракт можешь только ты).

**Задачи по порядку:**
1. **До 01:15** — ветка `bcc/v2` создана и запушена (см. выше).
2. **До 02:00** — скелет строго по CONTRACT.md, чтобы остальные сразу подключали свои части:
   - `types.py`: TypedDict и JSON Schemas (кандидат, требование, итоговый дефект, report.json). Схемы ответов модели — без `$ref`, `oneOf`, `minLength`; у всех объектов `additionalProperties: false` и полный `required` (ограничения structured outputs у Claude и Gemini).
   - `llm.py`: `LLMClient.ask` / `ask_split` (CONTRACT, раздел 3); провайдеры `mock`, `claude_cli` (положи прототип `docs/plan-v2/ref/claude_cli_adapter.py` как `v2/providers/claude_cli.py`, дальше его ведёт №02), `offline`; повторы, цепочка моделей, кэш `.bcc_cache/v2/`, трасса, бюджет `--max-calls`, параллельность `--concurrency` (claude_cli 5, gemini 2).
   - `pipeline.py`: read → rules → segment → [analyst, qa, architect, risk, consistency параллельно] → quotes → judge → clarify → verdict → render. Падение этапа не роняет прогон: этап `failed`, прогон `partial`, остальные идут. Заглушки этапов, которых ещё нет, возвращают валидный пустой результат.
   - `stages/lens.py`: общий запуск линзы — собирает user-сообщение (документ → требования → сигналы → `prompts/lens_<имя>.md`), вызывает `ask`, нумерует кандидатов, ставит `source`.
   - `runs.py`: `runs/<run_id>/stages/<этап>.json`, `trace.jsonl`; команда `python -m bcc_review.v2 stage <этап> --doc ФАЙЛ --from runs/<id>` — от неё зависит скорость всех остальных.
   - CLI: `python -m bcc_review ВХОД ОТЧЁТ.md [--provider auto|claude_cli|gemini|anthropic|openai|mock|offline] [--model M] [--export html,docx,pdf,jira] [--answers F] [--revise] [--no-cache] [--max-calls N] [--concurrency N] [--fail-on blocker] [--engine v1|v2]`, по умолчанию v2. Подкоманды `verify`, `doctor`, `stage` (verify пишет №13, doctor — №02: подключи точки входа). Коды выхода: 0 — ок, 1 — ошибка, 2 — аргументы, 3 — `--fail-on blocker`.
   - Временный рендер MD (паспорт + список находок), пока №13 не сдаст свой.
   - `prompts/_system.md` — текст из CONTRACT.md, раздел 6, со шкалой из раздела 5.
   - Тест: mock-прогон официального документа проходит насквозь и пишет report.md и report.json.
   Запушь и напиши в `docs/plan-v2/INTEGRATION.md`: «скелет готов, SHA, как запускать stage».
3. **До 03:00** — первый живой сквозной прогон: `python -m bcc_review release/input/requirements.md out/official.md --provider claude_cli --model sonnet`. Сводку (время, вызовы, статусы этапов, кандидаты и дефекты) — в INTEGRATION.md. Сохрани ответы этапов как mock-фикстуры `tests/v2/fixtures/official/<этап>.json`, чтобы остальные тестировали без сети.
4. **Каждый час в :00** — цикл интеграции: статусы веток `git for-each-ref --sort=-committerdate refs/remotes/origin/v2`, слить готовые (`git merge --no-ff`), `pytest tests/v2`, mock-прогон, живой прогон на sonnet; Opus — в 07:00, 11:00, 15:00. Красную ветку не вливай и напиши владельцу в INTEGRATION.md, что сломано. В INTEGRATION.md держи таблицу: ветка, SHA, влита ли, тесты, что блокирует.
5. **Сквозные инварианты — твоя зона:** ни один этап не роняет прогон; обрезанный ответ делится (`ask_split`), а не выбрасывает пакет; вызовов ≤ 12; на Opus ≤ 15 минут; кандидат без найденной цитаты не доходит до судьи; вердикт считает код по правилу CONTRACT, раздел 5.
6. Если №15 покажет нестабильность критичных между прогонами — добавь `--passes 2` (линзы дважды, судья видит обе выборки).
7. **14:00** — заморозка функций (объяви в INTEGRATION.md). **15:00** — тег `v2.0.0-rc1`. **17:00** — тег `v2.0.0` вместе с №16 (финальные отчёты делает №16).

**Готово, когда:** `python -m bcc_review release/input/requirements.md out/r.md --provider claude_cli` даёт `complete`, ≤ 12 вызовов, ≤ 15 минут на Opus; `pytest tests/v2` зелёный; любой этап перезапускается командой `stage`.
