# HANDOFF: контракт v1 и состояние интеграции 18 модулей

**Интеграционная ветка:** `bcc/integration`. **Сборка для официального прогона:** `12ed4d70e5d91ba9a8ba8ec1b89b5fc7921ac1a3` (комплект `release/`, CLI
`python -m bcc_review`). Независимая оценка GPT Pro запечатана на прежнем кандидате `f91d3b6`.
Контракт v1 зафиксирован в `431f76d9fdd7cc26623e10335098e0ed878da1fb`, дополнения v1 (необязательные
поля) — в последующих коммитах этой ветки; несовместимых изменений не было.

```powershell
git fetch origin bcc/integration
git switch -c bcc/pNN-имя origin/bcc/integration
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -e ".[all,dev]"
.venv\Scripts\python -m pytest tests/contract tests/integration
```

Тесты модулей запускайте по папкам (`pytest tests/p05`): у части папок нет `__init__.py`, и общий
запуск `pytest tests` может столкнуть одноимённые модули.

## Состояние 18 модулей на сборке `8e8e95f` (обновления до `70d2617` — в журнале ветки)

«team» — модуль владельца влит и вызывается движком (паспорт: `run.modules`). Резервных реализаций на
пути прогона не осталось: все слоты, кроме собственного этапа правил движка, — модули владельцев.

| № | Модуль | Ветка @ SHA | В сборке | Тесты владельца на сборке | Риск |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 01 | Markdown/TXT | `claude/dazzling-meitner-ptmc1o` @ `9a79c20` | team | 69 ✓ | — |
| 02 | PDF | `claude/youthful-mayer-67swfl` @ `6383421` | team | 52 ✓ | многоколоночная вёрстка — эвристика |
| 03 | DOCX и Word | `bcc/p03-word` @ `05130b3` | team | 39 ✓ | — |
| 04 | Нарезка | `claude/modest-noether-1dyn5q` @ `fb5007d` | team | 50/54: реестр MD и PDF документа банка расходится | средний |
| 05 | Отдельное требование | `claude/practical-ride-4z65ch` @ `975142e` | team | 82 ✓ | промпты не проверены на живой модели |
| 06 | Набор, факты, покрытие | `claude/epic-mccarthy-uhlsri` @ `2cdb9d3` | team | 56 ✓ | живая модель не проверена |
| 07 | Цитаты и verify | `bcc/p07-evidence` @ `82c0904` | team | 148/151: образцы собраны прежним читателем №01 | — (verify отчётов сборки — OK) |
| 08 | Вопросы и решения | `claude/compassionate-cannon-xc9gxg` @ `557c0b1` | team | 112/113: кодировка вывода подпроцесса в тесте (Windows) | — |
| 09 | Сравнение редакций | `bcc/p09-versions` @ `cddf0d9` | team | 119/121: ожидаемый SHA фикстуры | — |
| 10 | Чек-лист банка, тест-кейсы | `claude/jolly-dijkstra-oakxea` @ `11a8f1f` | team (впервые) | 58 ✓ | — |
| 11 | Claude API | `claude/anthropic-adapter-errors-v5roi9` @ `a6a8c23` | team | 50 ✓ | **живой вызов не выполнялся: ключа в среде сборки нет** |
| 12 | Gemini | `claude/vigilant-sagan-xjr7yo` @ `ecba6ab` + `max_asker_call_gate.diff` в `asker.py` | team | 137 ✓ | живой вызов не выполнялся |
| 13 | HTML | `claude/kind-johnson-tu7ps7` @ `9901fd0` | team | 57 ✓ | — |
| 14 | PDF с выделениями | `bcc/p14-annotated-pdf` @ `3ed0ba2` | team | 67 ✓ | — |
| 15 | Веб-демо | `claude/gallant-wozniak-e9i4q8` @ `fd0b1e5` | team | 56/68: разбор `answers.md`/`questions.md` нового формата №08, 2 обрыва соединения | веб вручную не проверялся |
| 16 | Оценка | `claude/sleepy-gates-1zbw4l` @ `a79a47d` | team | 81/86 | — |
| 17 | Markdown и Jira | `bcc/p17-reports` @ `419f86c` | team | 137/138: кодировка вывода подпроцесса в тесте (Windows) | — |
| 18 | Выпуск | `bcc/p18-release` @ `feb1187` | team | `tests/p18` | Windows, Linux и Docker описаны в протоколе владельца |

Ворота Max на сборке: `tests/contract` 29 ✓, `tests/integration` 138 ✓. Офлайн-отчёты сборки и `verify` —
`release/reports/offline/`; официальный онлайн-прогон — `release/reports/live/README.md`.

Снимок всех веток для сборки опубликован в [BRANCHES.md](BRANCHES.md). Обновления №10 и №16 включены из `896b49c` и `a4fc5de`.

## План Б: выпуск на движке v1 (для №01 v2)

`bcc/integration` держит v1 готовым к выпуску, если в 12:00 v2 не пройдёт ворота качества.

1. Влить `bcc/integration` в `bcc/v2`. Код движка сливается без конфликтов; конфликтуют только файлы
   упаковки, которые завели и №18 v1, и №16 v2 (`README.md`, `.env.example`, `Dockerfile`, `.dockerignore`) —
   в `bcc/v2` оставить версии v2: `git checkout --ours README.md .env.example Dockerfile .dockerignore`.
   Проверено на временном слиянии: `tests/contract` + `tests/integration` зелёные, `--engine v1` работает.
2. Живой прогон v1 без API-ключа — в сессии с Claude Code CLI:

```sh
python -m bcc_review --engine v1 release/input/requirements.md out/planb/requirements.md --provider claude_cli --no-cache --export html,jira --max-calls 40 --max-seconds 2700
python -m bcc_review verify out/planb/requirements.json release/input/requirements.md
```

   Модель — `CLAUDE_CLI_MODEL` (по умолчанию `opus`). Прежний прогон v1 через `claude -p` на Opus: 28 мин,
   17 вызовов, ≈ $6,3, все К1–К5. С ключом API вместо CLI — `--provider anthropic` (сборка `f84f730` или новее:
   в старых Claude отвечал 400 на поле `cache`).
3. Годность: `run.mode = rules_plus_llm`, `run.status = complete`, `verify` — OK. Обрезанные пакеты теперь
   делятся пополам (`ask_split` в трассе), цитаты привязываются к блоку своего требования.

## Что движок выравнивает на стыках (просьбы к владельцам)

Движок принимает отклонения ниже и пишет предупреждение или запись трассы. Лучше исправить у себя:

| № | Отклонение от контракта | Что сделать |
| :--- | :--- | :--- |
| 01 | `read_text` возвращает объект `Document`, а не dict; `section` — только ближайший заголовок (полный путь — в `loc.section_ids`) | вернуть dict (`to_dict()`), `section` — полный путь от корня |
| 01 | файл UTF-8 с несколькими битыми байтами целиком перечитывается как cp1251: кириллица превращается в мусор, а прогон считается полным | при малой доле битых байт — UTF-8 с заменой и предупреждение `decode_error` (входит в `PARTIAL_READ_CODES`) |
| 04 | тест `test_engine_model_branch_with_mock_provider` берёт Document через `Modules().get("read_text").func` | брать `bcc_review.engine.read_document(path)` — тот же путь, что у движка |
| 05, 06 | коды критериев вне справочника (`consistency`), вид `question` | коды из `criteria.toml` (`set_consistent`), виды из `contracts.FINDING_KINDS` |
| 06 | `ask` получает `{instructions, document, pairs, …}` вместо `{task, input, context}` и прикладывает документ сам | `{"task": промпт, "input": данные, "context": {"mode": "auto"}}`: документ приложит движок, кэш и контекст станут общими |
| 06 | факты: `evidence` одиночным объектом, `subject: null` | `evidence` — список, `subject` — строка |
| 05, 06 | ошибки `ask` перехватываются внутри модуля без признака в ответе | вернуть `failed: {req_id: причина}` (№05) или `warnings` с кодом; движок теперь сам видит этап без единого ответа модели и ставит `failed` |
| 08 | `parse_answers` возвращает `AnswerSet`, `propose_patch` ждёт объект `Question` | движок передаёт `Question.from_dict(...)`; в карточке вопроса покажите, какой фрагмент заменит «Формулировка» (сейчас заменяется сторона A конфликта) |
| 08 | `questions.md` на Windows пишется с CRLF, тест `test_committed_examples_are_reproducible` падает | писать с `newline="\n"` |
| 09 | CLI `python -m bcc_review.decisions.diff` печатает в кодировке консоли, тесты читают UTF-8 | `sys.stdout.reconfigure(encoding="utf-8")` |
| 13 | выделения цитат строятся скриптом, в статическом HTML нет `<mark>` | оставить якоря `#finding-…`, `#block-…` (есть) и, по возможности, статическое выделение для печати |
| 15 | тест ждёт «нельзя начинать» на сценарии `mock_bcc.json`, который написан под схемы резервных этапов | для полного пути с модулями команды — свой сценарий mock под этапы `cross.pairs`, `cross.coverage`, `individual#N` |
| все | объекты модулей (dataclass, `to_dict()`) | движок приводит их к dict (`contracts.as_plain`), но на стыке ожидается dict |

## Решения интегратора по контракту

* `loc.map`: синтетический символ без позиции в исходнике (перевод строки, « | ») — запись `[text_start, 0, 0]`.
* `loc.columns` — заголовки столбцов строки таблицы; `loc.table` — любой тип (у №01 объект, у PDF — номер).
* Необязательные поля `Loc`: `level`, `columns`, `bbox`, `table`, `row`, `empty`, `furniture`, `lang`; `Warning.page`.
* Информационные коды чтения (на полноту не влияют): `INFO_WARNING_CODES`.
* `messages[i]["cache"] = True` у сообщения с документом — подсказка адаптеру для кэширования промпта.
* `usage`: `input_tokens`, `output_tokens`, `cache_read_input_tokens` (или `cache_read`).
* Ответы аналитика (`--answers`) сопоставляются с вопросами и находками отчёта из `--compare`.

## Что лежит в контракте

| Файл | Назначение |
| :--- | :--- |
| `src/bcc_review/contracts.py` | единственный источник схемы и типов: `REPORT_SCHEMA`, `DEFS`, `validate(obj, name)`, `evidence_errors(report)`, `ProviderError`, `AskError`, `BudgetExhausted`, `RunOptions`, коды выхода |
| `contracts/v1.json` | JSON Schema Report (draft 2020-12), генерируется: `python -m bcc_review.contracts --write` |
| `contracts/examples/two_linked_requirements.md` | вход: два связанных требования |
| `contracts/examples/minimal_report.json` | минимальный валидный Report: конфликт с двумя привязками, witness, вопрос, вердикт |

Проверка своего объекта на стыке:

```python
from bcc_review.contracts import validate, evidence_errors
validate(document, "Document")      # Block, Requirement, Candidate, Finding, Fact, Coverage, Question, Decision, ...
validate(report)                    # весь Report
assert evidence_errors(report) == []  # block.text[start:end] == quote, ссылки на требования, witness
```

## Правила, которые проверяет движок на каждом стыке

* `Document.id` — SHA-256 исходных байтов. ID блока: `b0001`, `b0002`… в порядке чтения; область — текущая версия документа.
* `Block = {id, kind, section, text, loc}`; `kind` ∈ `heading|paragraph|list_item|table_header|table_row|code|quote|other`;
  `section` — список заголовков от корня.
* Координаты в `block.text` — кодовые точки Unicode с нуля, правая граница исключена (`str` в Python).
* `loc` Markdown/TXT: `line_start`, `line_end` с 1 включительно. Если видимый текст отличается от исходника
  (`**`, `* `, `|`), `loc.map = [[text_start, line, col], ...]`: с позиции `text_start` в `block.text`
  символы идут подряд с (`line`, `col`) исходника; `col` с нуля в кодовых точках.
* `loc` PDF: `page` с 1, `fragments = [{start, end, rect:[x0,y0,x1,y1]}]` в пунктах неповёрнутой страницы PyMuPDF.
* `loc` DOCX: `part` (например `word/document.xml`), `path` к абзацу или ячейке, `runs`.
* Неполное чтение помечайте в `Document.warnings` кодом из `PARTIAL_READ_CODES`
  (`partial_read`, `unreadable_page`, `decode_error`, `ocr_required`, `truncated_input`): тогда прогон `partial`
  и готовность не может быть `ready`.
* Пустые списки — `[]`, не `null`. Перечисления — из `contracts.py`.
* Подтверждение цитаты (`anchor_status`) и подтверждение смысла (`meaning_status`) — разные поля.
  `confirmed` возможен только при `anchor_status = supported`. Конфликт подтверждается двумя опорами в `witness`.
* Критичное замечание обязано иметь `impact` (бизнес-последствие) и `blocked_decision` (какое решение
  разработчика или тестировщика оно блокирует), иначе движок понижает его до `major` с предупреждением.

## ask(stage, payload, schema) для семантических модулей (№04, 05, 06, 08, 10)

```python
payload = {
    "task": "инструкция этапа на русском (ваш промпт)",
    "input": {...},                                   # любой JSON
    "context": {"mode": "auto", "block_ids": [...]},  # необязательно; auto — решает движок
}
data = ask("individual", payload, schema)  # dict, уже проверенный по schema
```

* Схема — JSON Schema с `additionalProperties: false` у объектов и полным `required`
  (ограничение structured outputs). Без `minimum/maxLength`, без рекурсии.
* Текст документа прикладывает движок: малый документ целиком (части A и B вместе), большой — индекс
  всех требований, запрошенные блоки и блоки по межсекционным ссылкам. Блоки в контексте помечены `[b0012]`,
  поэтому модель отвечает подсказками `{block_id, quote}`; координаты считает №07.
* Ошибка → `AskError` (или `BudgetExhausted`). Перехватите и верните частичный результат с
  `warnings`, либо дайте исключению уйти: движок отметит этап `failed` и запустит ваш модуль с `ask=None`.
* Бюджет, повторы с Retry-After, кэш, трасса и паспорт — в движке. Модулю их делать не нужно.

## Адаптеры провайдеров (№11 Anthropic, №12 Gemini)

```python
class AnthropicAdapter:
    name = "anthropic"
    def invoke(self, *, model, messages, schema, timeout_s) -> dict:
        # messages: [{"role": "system"|"user", "content": str}]
        return {"data": obj, "usage": {"input_tokens": n, "output_tokens": m}, "model": "<фактическая>",
                "request_id": "...", "stop_reason": "end_turn"}
```

Ошибка — `ProviderError(kind, message, retry_after_s=None, status=None)`; `kind`:
временные `rate_limit|overloaded|server|timeout|network`, остальные
`auth|not_configured|bad_request|not_found|refusal|truncated|invalid_output|quota|unknown`.
`stop_reason=max_tokens` → `ProviderError("truncated")`. Сам адаптер не повторяет запрос.
Переменные: `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL`; `GEMINI_API_KEY`, `GEMINI_MODEL`.

## Подключение модулей

Движок ищет модуль владельца по пути из таблицы ниже. Пока модуля нет в ветке, работает
резервная реализация из `src/bcc_review/runtime/fallback/` (зона Max); `BCC_FORCE_FALLBACK=slot1,slot2` включает резерв принудительно. Паспорт отчёта показывает,
какая реализация отработала (`run.modules`). Как только ваш модуль влит, он используется автоматически,
а его выход проверяется по контракту; при нарушении движок пишет предупреждение и переходит на резерв.

| № | Ветка | Точка входа |
| :--- | :--- | :--- |
| 01 | `bcc/p01-text` | `bcc_review.readers.text:read_text(path) -> Document` |
| 02 | `bcc/p02-pdf-reader` | `bcc_review.readers.pdf:read_pdf(path) -> Document` |
| 03 | `bcc/p03-word` | `bcc_review.readers.docx:read_docx(path)`, `bcc_review.exports.word:write_docx(report, input_path, output_path)` |
| 04 | `bcc/p04-inventory` | `bcc_review.analysis.inventory:build_inventory(document, ask=None)` |
| 05 | `bcc/p05-individual` | `bcc_review.analysis.individual:review_individual(document, requirements, ask=None)`, `bcc_review.criteria:load_criteria()` |
| 06 | `bcc/p06-cross` | `bcc_review.analysis.cross:review_set(document, requirements, ask=None, *, fact_hints=None)`, `bcc_review.analysis.facts:reconcile_facts(document, fact_hints)` |
| 07 | `bcc/p07-evidence` | `bcc_review.analysis.evidence:resolve_hint/resolve_candidate`, `bcc_review.verification:verify_report(report_path, source_path)` |
| 08 | `bcc/p08-decisions` | `bcc_review.decisions.clarify:build_questions`, `bcc_review.decisions.patches:propose_patch/write_revision`, `bcc_review.decisions.answers:parse_answers(path, document) -> list[Decision]` |
| 09 | `bcc/p09-versions` | `bcc_review.decisions.diff:compare_reports(previous, current)` |
| 10 | `bcc/p10-bank` | `bcc_review.bank.checklist:build_bank_pack(document, requirements, findings, decisions, ask)` |
| 11 | `bcc/p11-anthropic` | `bcc_review.providers.anthropic:AnthropicAdapter` |
| 12 | `bcc/p12-gemini` | `bcc_review.providers.gemini:GeminiAdapter` |
| 13 | `bcc/p13-html` | `bcc_review.exports.html:write_html(report, output_path)` |
| 14 | `bcc/p14-annotated-pdf` | `bcc_review.exports.pdf:write_pdf(report, input_path, output_path)` |
| 15 | `bcc/p15-web` | `bcc_review.web` вызывает `bcc_review.run_review(input_path, report_md, options=RunOptions|dict)` |
| 16 | `bcc/p16-eval-tools` | `evaluation/harness` читает `report.json` по `contracts/v1.json` |
| 17 | `bcc/p17-reports` | `bcc_review.exports.markdown:write_markdown`, `bcc_review.exports.jira:write_jira_csv` |
| 18 | `bcc/p18-release` | `python -m bcc_review INPUT OUTPUT.md`, коды выхода ниже |

№08: движок вызывает `parse_answers(path, document, questions=, expected_sha=)`, `propose_patch(document, finding, decision, question=)`, `write_revision(document, edits, output, source=)`; вопросы и находки берёт из отчёта `--compare`.

## CLI и коды выхода (для №18)

```text
python -m bcc_review INPUT OUTPUT.md [--provider anthropic|gemini|mock] [--model M]
                     [--offline-lint] [--answers answers.md] [--compare old.json]
                     [--export html,pdf,docx,jira] [--fail-on blocker|partial] [--no-cache]
python -m bcc_review verify REPORT.json SOURCE
```

| Код | Значение |
| :--- | :--- |
| 0 | отчёт записан (или verify прошёл) |
| 1 | ошибка выполнения |
| 2 | ошибка аргументов |
| 3 | `--fail-on blocker` и готовность разработки или тестирования не `ready` |
| 4 | verify нашёл расхождение |
| 5 | `--fail-on partial` и прогон не `complete` |

## Как сдать модуль

1. Ветка `bcc/pNN-…` от `bcc/integration`, тесты в `tests/pNN/`, только свои файлы.
2. `pytest tests/contract tests/pNN` зелёные; объекты проходят `validate(...)`.
3. Сообщение о передаче: ветка и SHA, команда тестов, открытые вопросы к контракту.
   Изменение контракта — только через Max (владелец интерфейса).
