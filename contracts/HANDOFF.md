# HANDOFF: контракт v1 для 18 модулей

Ветка интеграции: `bcc/integration` (от `76ab976`, коммит команды с разбором задачи).
Контракт v1 зафиксирован в коммите **`431f76d9fdd7cc26623e10335098e0ed878da1fb`**.
Берите ветку не старее коммита с этим файлом: в нём же `.gitattributes`, без которого
на Windows меняются байты примеров и их SHA-256.

```powershell
git fetch origin bcc/integration
git switch -c bcc/pNN-имя origin/bcc/integration
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
.venv\Scripts\python -m pytest tests/contract
```

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
резервная реализация из `src/bcc_review/runtime/fallback/` (зона Max). Паспорт отчёта показывает,
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

`parse_answers` у №08 — предложение Max; если сигнатура другая, напишите в передаче.

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
