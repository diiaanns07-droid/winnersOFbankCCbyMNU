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
