# Max — проверка пути жюри на настоящей Windows (27.11, ветка `v2/max-windows`)

Ветка от `bcc/v2` `75a9b3a`. Все облачные сессии на Linux; здесь — Windows 11, **Windows PowerShell 5.1**,
Python с python.org 3.13 и 3.14, чистый клон `git clone --branch bcc/v2`.

## Что проверено по README (шаги 1–3) — работает

| Сценарий | Результат |
| :--- | :--- |
| Шаг 1: `py -3.13 -m venv`, `Activate.ps1`, `pip install -r requirements.txt -e .` | ✓ все импорты (pymupdf, docx, google-genai, anthropic) |
| То же на **Python 3.14** (сейчас ставится по умолчанию с python.org) | ✓ установка, mock-прогон PDF, `tests/v2` 1034 passed |
| Без ключа: `python -m bcc_review release/input/requirements.md reports/my/requirements.md` | ✓ первая строка «Модель не настроена: предварительная проверка правилами», отчёт помечен «без модели» |
| `--provider offline`, `--provider mock`, пути с `\`, вход PDF | ✓ |
| `doctor` без ключа | ✓ код 1, совет с адресом ключа |
| `verify` | ✓ 102 из 102 цитат |
| `powershell -ExecutionPolicy Bypass -File scripts\run_official.ps1 … --provider mock` | ✓ прогон, verify, сводка, код 0 |

## Что исправлено в ветке (владельцам — посмотреть дифф)

| Файл | Владелец | Что |
| :--- | :--- | :--- |
| `scripts/_env.ps1`, `scripts/_env.sh` | №16 | пускали только Python 3.11–3.13 → у жюри с 3.14 «Нужен Python 3.11, 3.12 или 3.13» и выход. Теперь 3.11–3.14 (3.14 проверен) |
| `README.md` (2 строки) | №16 | «Python 3.11–3.14», пример `py -3.14` |
| `src/bcc_review/v2/providers/doctor.py` | №02 | `which=shutil.which` в объявлении `resolve_auto`/`run_doctor` фиксировался при импорте → подмена в тестах не действовала; тест «Gemini важнее claude» проходил только там, где `claude` реально установлен (облако). Теперь `which` берётся в момент вызова |
| `tests/v2/test_02_doctor.py` | №02 | подделка отвечает и на `claude.exe` (так CLI ищется на Windows) |
| `tests/v2/test_02_jury_scripts.py` | №02 | `bash -n` — только если bash видит файл (на Windows `bash` — заглушка WSL; Git Bash не открывает `C:\…`); дочерний Python сводки — с `PYTHONUTF8=1`, как в `_env.ps1` |
| `tests/v2/test_03_quotes.py` | №03 | вывод дочернего Python читается в UTF-8 при любом `PYTHONIOENCODING` |

**Итог на Windows:** `tests/v2` было 1034 passed / 3 failed → **1037 passed, 0 failed** (Python 3.13, без
`PYTHONIOENCODING`); затронутые файлы зелёные и с `PYTHONIOENCODING=utf-8`.

## Просьбы

* **Владелец репозитория:** ветка по умолчанию на GitHub сейчас `claude/nice-edison-gpkcfl` (`76ab976`, только
  `docs/task-analysis.md`). `git clone` из README у жюри даст пустой репозиторий. Переключить на `release`
  (чек-лист `SUBMISSION.md`) — до сдачи.
* **№01:** mock-фикстуры отстали от кандидатов: в каждом `--provider mock` жюри видит «судья сослался на
  несуществующего кандидата C-068 / C-069 / C-070». Перезаписать `tests/v2/fixtures/official/judge.json` с
  живого прогона текущей сборки.
* **№16:** в CI добавить задание `windows-latest` для `tests/v2` и Python 3.14 в матрицу — обе ошибки выше CI
  поймал бы сам.

## Вторая проверка (после слияния свежей `bcc/v2`)

| Сценарий (Windows PowerShell 5.1, Python 3.13, без `PYTHONIOENCODING`) | Результат |
| :--- | :--- |
| Вход из папки с кириллицей и пробелами `C:\t\Документы банка\ТЗ уведомления.{pdf,docx,md,txt,html}`, отчёт в `C:\t\Отчёты банка\тз *.md` | ✓ все 5 форматов: прогон 0, `verify` 0 |
| `--export docx,pdf,jira` для DOCX | ✓ `.annotated.docx` (15 из 15 дефектов, 34 места), `.jira.csv`; для PDF — понятное сообщение «PDF с выделениями строится для входа PDF или Markdown» |
| `scripts\jury_check.ps1 mock` | ✓ все ворота: К 5/5 (4 критичными), С 18/20, ложных критичных 0, `verify` OK, код 0 |
| `scripts\jury_check.ps1 mock -Doc release\input\requirements.pdf` | `partial`, К 2/5 — ожидаемо: ответы mock записаны на Markdown (README так и говорит); с Gemini этот вход не проверить без ключа |

Замечание для своих тестовых скриптов PowerShell: без BOM Windows PowerShell 5.1 читает кириллицу как ANSI —
скрипты `scripts\*.ps1` команды сохранены с BOM правильно.

## Веб-демо: не работало с папкой данных по умолчанию (исправлено, владелец №14)

`python -m bcc_review.v2.web` → «Проверить пример» → **«Анализ завершился с ошибкой. Файл не найден:
.bcc_web\jobs\…\input\requirements.md»**. Причина: `--data-dir` по умолчанию относительный (`.bcc_web`),
а анализ идёт дочерним процессом с `cwd` = папка задания — относительный путь загрузки оттуда не находится.
Тесты №14 передают абсолютный `tmp_path`, поэтому не ловили. Это не только Windows: так на любой ОС.

* `src/bcc_review/v2/web/runner.py`: `JobStore` делает корень абсолютным (`Path(root).resolve()`), одна строка.
* `tests/v2/test_max_web_relative_data_dir.py`: относительная папка данных — путь абсолютный, задание
  `offline` проходит до `report.md`. Без правки оба теста падают, с ней — зелёные (`test_14_web.py` тоже).
* Проверено в браузере на Windows: пример `requirements.md` в режиме «Демо» — все этапы, вердикт «нельзя /
  нельзя», 31 замечание (4 критичных), 100 % цитат, кнопки HTML / Markdown / JSON / Word / PDF / Jira CSV.

## Режим ответов `--answers … --revise` на Windows (исправлено, владельцы №11 и №01)

Сценарий README: `python -m bcc_review <ТЗ> <отчёт.md> --answers <ответы.md> --revise`, вход и ответы — в папке
с кириллицей и пробелами, файл ответов сохранён так, как его сохраняет Блокнот.

| Файл ответов | До | После |
| :--- | :--- | :--- |
| UTF-8, LF / CRLF / с BOM | ✓ 7 ответов, 10 решений, `.revised.md` | ✓ без изменений |
| **ANSI (cp1251, «ANSI» Блокнота русской Windows)** | ✗ ответы не применены, `.revised.md` нет, **ни одного предупреждения**, код 0 | ✓ как у UTF-8 |
| UTF-16 («Юникод» Блокнота) | ✗ то же | ✓ как у UTF-8 |

* `src/bcc_review/v2/stages/recheck.py` (№11): `read_answers_file` — UTF-8 (с BOM и без) → UTF-16 с BOM → cp1251;
  если не подошло — понятная ошибка «сохраните в Блокноте с кодировкой UTF-8». В cp1251 нет знака «₸»: Блокнот
  заменит его на «?», ответы при этом сопоставляются.
* `src/bcc_review/v2/pipeline.py` (№01): сбой режима `--answers/--revise` ловился после сборки отчёта, и
  предупреждение не доходило ни до отчёта, ни до терминала. Теперь оно в `run.warnings`. Статус и вердикт не
  трогал: они считаются по этапам до режима ответов.
* `tests/v2/test_max_answers_encoding.py`: 4 кодировки Блокнота и видимость сбоя. Без правок 3 из 5 падают.

## Третья проверка: весь `tests/v2` на Windows на `bcc/v2` `3e4d650` (27.11, после волны 3 судьи №10)

Python 3.13, без `PYTHONIOENCODING`, последовательно: **1742 passed, 2 failed**, 4 skipped, 4 xfailed, 2 xpassed (12 мин).

| Тест | Причина | Что сделано |
| :--- | :--- | :--- |
| `test_05_analyst.py::test_prompt_has_clean_document_filters` | `read_text()` без кодировки: на Windows промпт читается как cp1251 → `UnicodeDecodeError` | исправлено в ветке: `read_text(encoding="utf-8")`; файл 54 passed. В коде продукта `v2` таких чтений нет (проверено поиском) |
| `test_14_edge.py::test_long_document_leaves_budget_for_judge` | **зависит от скорости машины.** Если нарезка ТЗ ×10 через mock идёт дольше `FAST_START_PROBE_S` = 8 с, включается быстрый старт: у рецензента таблица эвристики со строками приёмки всех 10 копий, №04 добирает их вызовами `lens_qa_rows` ×2 и `lens_qa_retry` ×1; из 16 вызовов судье остаётся 2 → `judge: partial` («вторая проверка серьёзности не удалась (BudgetExceeded)», «судья не рассмотрел 31 кандидат»). На облачном Linux нарезка короче 8 с — тест зелёный | **не правил** (решение владельцев), см. просьбу ниже. Воспроизведение: `fast_start=True` — падает 2 из 2, `fast_start=False` — проходит 2 из 2; без флага на этой машине 3 из 6 |

**Просьба №01, №06, №14.** В живом прогоне длинного ТЗ нарезка моделью всегда дольше 8 секунд, поэтому быстрый старт и есть основной путь. Сейчас судья на длинных документах может остаться без вызовов: добор строк приёмки в `lens_qa` (`_ask_rows`) не оставляет судье резерва из бюджета `max_calls` = 16, а значение `partial` у судьи меняет итог прогона. Варианты:
* №01 — резерв вызовов для судьи и clarify в `LLMClient` (добирающие вызовы рецензентов не берут последние N);
* №06 — добор строк только в пределах остатка бюджета минус резерв;
* №14 — запускать тест с `fast_start=True` и `fast_start=False`: сейчас он проверяет только быстрый путь машины, на которой запущен.

Остальное на Windows на этой сборке зелёное, в том числе тесты на файл ответов, веб-демо и скрипты жюри, которые я добавил раньше.

**PDF на Windows без tesseract (находка №02):** исправлено №03 в `34ef75b` (`docview._no_tesseract_probe`). Проверено: `python -m bcc_review tests/p02/fixtures/p02_scan_mixed.pdf … --provider offline` с `PYTHONUTF8=1` — код 0, трейсбэков 0. Отдельная правка в читателе v1 не нужна: она отключала бы OCR у тех, у кого tesseract стоит в `Program Files`, но не в `PATH`.
