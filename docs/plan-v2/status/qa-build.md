# Статус qa-build — контроль сборки `bcc/v2` после интеграции №16

Ветка: `v2/qa-build` (от `origin/bcc/v2`). Модель живых прогонов — `--provider claude_cli --model sonnet --no-cache`,
Linux, Python 3.13, чистая рабочая копия HEAD (`git worktree`). Время — Астана (UTC+5).
Промпты агента, судью и линзы не трогаю; логику — только просьбой владельцу (зоны — `CONTRACT.md`, раздел 1).

**Готово к слиянию: `12da8b9`** (`v2/qa-build`) — кодировки Блокнота, строка 1 ниже. С `bcc/v2` `04eca94` сливается
без конфликтов; `pytest tests/v2` с правкой — 1610 passed, 0 красных.

## Поломки

| # | Что | Команда повтора | Коммит | Зона | Статус |
| :-- | :--- | :--- | :--- | :--- | :--- |
| 1 | **ТЗ и ответы из Блокнота (ANSI cp1251, UTF-16) не читаются.** `docview` такой файл читает, а нарезка (`segment._raw_source_lines`), редакция (`revise._source_lines`) и ответы (`recheck.load_answers`) — только UTF-8. ТЗ из текущей папки: **0 требований**, код 0; `--answers`/`--revise`: «Режим --answers/--revise не выполнен: UnicodeDecodeError», редакции нет, код 0 | `cd папка_с_ТЗ && python -m bcc_review tz_ansi.md out/tz.md --provider mock --answers answers_utf16.md --revise` (файлы — `iconv -t cp1251` / `-t utf-16`) | давно (есть на `d430a3c` и `04eca94`; №14 нашёл часть с ответами — xfail) | 04 (`segment.py`), 11 (`revise.py`, `recheck.py`) | **исправлено `12da8b9`**: `docview._decode_text`, как у самого документа; тест `tests/v2/test_qa_build.py` (8 зелёных; без правки 6 красных); закрывает и xfail №14 `test_answers_file_in_cp1251_is_read` |
| 2 | **Mock-прогон: судья ссылается на несуществующих кандидатов C-068…C-070, у дефектов чужие цитаты и источники.** Фикстура `tests/v2/fixtures/official` записана до постобработки `lens_risk` (отсев minor без зацепки, противоречий с приёмкой): линза теперь оставляет меньше кандидатов, номера `C-…` у набора и правил сдвинулись, записанные решения судьи попадают не на те замечания. Примеры: D-31 «Не указаны версия, дата» — цитаты `GET /alerts/saveLimit` (`rules:api.get_mutation.saveLimit`); D-20 «Правило… записано дважды» — `rules:promises.read_operation`; D-03 — цитата «сервис настроек». К 5/5, но **критичными 4/5**, английских слов 2. Демонстрационный отчёт README (`--provider mock`) — именно этот | `python -m bcc_review release/input/requirements.md out/m.md --provider mock` → «! судья сослался на несуществующего кандидата C-070» | первый плохой — `7e16ccd` (merge `v2/08-risk` `29ea935`, 06:06), `git bisect --first-parent 9102bfb..fab3280` | 01 (фикстура `official`, `providers/mock.py`) | **просьба №01 / №16**: перезаписать фикстуру живым прогоном на текущем `bcc/v2`. Готовый вариант — ветка `v2/qa-build-mockfix`: ответы прогона sonnet `qa-md-d430a3c` (К 5/5 critical, С 18/20) → mock без предупреждений, К 5/5 critical, С 18/20, английских 0. Тест-сторож — `test_mock_judge_refers_to_existing_candidates` (xfail, нестрогий) |

## Ворота на официальном документе

| Проверка | `d430a3c` | `04eca94` |
| :--- | :--- | :--- |
| `pytest tests/v2 -q` | 1602 passed, 1 skipped, 4 xfailed, 17 xpassed | 1613 passed, 1 skipped, 3 xfailed, 18 xpassed |
| mock + `verify` | отчёт, verify OK; **поломка 2** | то же |
| offline (режим без модели) + `verify` | «Предварительная проверка без модели», 15 дефектов, 34/34, verify OK | то же |
| MD, sonnet | №1: 3 мин 06 с (первая минута — параллельно с pytest), К 5/5 critical, С 18/20, verify OK; №2 (один): **2 мин 17 с**, К 5/5 critical, **С 17/20** (С8, С10, С12), verify OK | — |
| PDF, sonnet | 2 мин 27 с, К 5/5 critical, **С 17/20** (С14, С17, С18), «с. N» у 85/85 цитат и 40/40 требований, verify OK | — |
| DOCX, sonnet | 2 мин 35 с, К 5/5 critical, С 19/20 (С10), verify OK | — |
| HTML (Playwright, 1440 и 390) | mock, живой MD, offline — 0 ошибок консоли, 0 упавших запросов, без горизонтальной прокрутки, внешних ресурсов нет | — |
| Веб-демо (`python -m bcc_review.v2.web`, mock) | загрузка файла → отчёт за 6 с, ссылки скачивания 200 (скрытые — только для существующих файлов); «Загрузить ответы» → новый прогон, есть «Исправленное ТЗ»; 0 ошибок консоли на 1440 и 390 | — |
| `.env` в UTF-16 (с BOM и без) | читается: `doctor` — «GEMINI_API_KEY: задан» | — |
| `doctor` без ключа | `--provider gemini/anthropic/openai`: по-русски, что сделать и где взять ключ, код 1 | — |
| `doctor --live` с неверным ключом | Gemini: «Google не принял ключ Gemini…», код 2, 0,8 с; Anthropic: «Claude API не принял ключ…», код 2, 1,1 с | — |

**С ≥ 18/20 — нестабильно:** 2 прогона из 4 — 17/20, промахи каждый раз разные («есть близкое замечание, но не та
проблема или не те строки» — решения судьи). Это не поломка слияния (утром у №01/№02 — 18–20/20), но запас у ворот
нулевой. **№10, №15:** посмотрите С17 (не найден в 3 из 4) и С10.

## Мелкое (просьбы)

* **№02:** `doctor --live --provider anthropic` с неверным ключом печатает перед понятным сообщением сырую строку
  журнала `anthropic {"ts": …, "status": "error", "kind": "auth", …}` — это `log.warning` из v1
  `providers/anthropic.py:1112` (уровень WARNING уходит в stderr через lastResort). В `doctor` (и в прогоне) стоит
  поднять уровень логгера `bcc_review.providers.anthropic` до ERROR или повесить `NullHandler`.

## Журнал проверок

* 14:53 — `bcc/v2` = `d430a3c`: pytest, mock, offline, doctor, кодировки, HTML, веб, MD/PDF/DOCX sonnet.
* 15:20 — `bcc/v2` = `04eca94` (+ 19-measure-clean, 15-eval, 05-analyst): pytest, mock, offline — без новых поломок;
  режим ответов и PDF на sonnet — идут.
