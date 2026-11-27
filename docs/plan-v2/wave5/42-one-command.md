# Волна 5 — №42: одна команда — скачал, запустил, открылось

Ты — сессия Claude Code команды STUPITS (хакатон BCC-HUB × MNU, кейс «ИИ-агент проверки требований»), роль №42.
Репозиторий: https://github.com/diiaanns07-droid/winnersOFbankCCbyMNU. Всё по-русски.
**Сдача — сегодня, 27.11, до 23:59 Астаны (UTC+5). Твоё «Готово к вливанию» — к 21:45 Астаны.** Тимлид — №11.
У тебя занято около трети лимита: коммить и пушь каждые 5 минут, большие файлы целиком не читай.

Владелец: «жюри одной командой всё скачало → вылезает BCC AI и просит ключ → открывается система». Твоя часть — от
пустого компьютера до открытого браузера: без единого вопроса, без ручной установки пакетов, на Windows, macOS и Linux.

## Сначала (10 минут)
1. `git fetch origin bcc/v2 v2/11-clarify`; ветка `v2/42-start` от `origin/bcc/v2`.
2. `git show origin/v2/11-clarify:docs/plan-v2/wave5/README.md` — договорённости, расписание, правила.
3. Что уже есть: `src/bcc_review/v2/web/server.py` (`main()`: `--port`, `--host`, `--open`, `--data-dir`),
   `Dockerfile`, `.env.example`, `scripts/jury_check.sh|.ps1`, `scripts/run_official.sh|.ps1`, раздел «Docker» в
   README; что `tests/v2/test_16_release.py` проверяет у `scripts/*.ps1`.

## Задача
1. **`start.sh`** (macOS, Linux) в корне: найти Python ≥ 3.11 (`python3.12`, `python3.11`, `python3`); нет —
   одна понятная строка, как поставить (macOS: `brew install python@3.12` или python.org; Ubuntu:
   `sudo apt install python3 python3-venv`); `.venv`, если нет; `pip install -r requirements.txt` только при
   изменении `requirements.txt`/`constraints.txt` (хеш в `.venv/.bcc-req`), тихо, с одной строкой прогресса;
   затем `python -m bcc_review.v2.web --open`. Повторный запуск — за секунды. Плюс `start.command` (двойной щелчок
   на macOS) — одна строка, зовущая `start.sh`.
2. **`START.cmd` + `start.ps1`** (Windows, двойной щелчок или `.\START.cmd` в PowerShell): `START.cmd` —
   `chcp 65001`, `cd /d "%~dp0"`, `powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1"`, при ошибке
   `pause`; сам `.cmd` — только ASCII. `start.ps1` совместим с PowerShell 5.1 (без `&&`, без `?.`), сохранён в UTF-8
   **с BOM** (иначе 5.1 читает кириллицу как cp1251); путь с пробелами и кириллицей в профиле пользователя не
   ломает; Python ищет через `py -3.12`, `py -3.11`, `python`; нет — предлагает `winget install -e --id
   Python.Python.3.12` (спросить Y/N) или ссылку python.org. В `.gitattributes`: `*.cmd`, `*.ps1` — `eol=crlf`,
   `*.sh`, `*.command` — `eol=lf`; у `.sh` и `.command` бит исполнения в git.
3. **`main()` в `server.py`**: порт занят → следующий свободный (8014…8030) и честно напечатать адрес; браузер
   открывается, когда сервер уже отвечает; в консоли крупно: «BCC Review работает: http://127.0.0.1:8014 —
   остановить: Ctrl+C»; флаг `--check` — поднять сервер, получить `/healthz` и `/`, выйти с кодом 0 (для проверки
   установки и CI). Хост по умолчанию — только `127.0.0.1`.
4. **Docker:** `docker-compose.yml` — `docker compose up` → http://localhost:8014 (внутри `--host 0.0.0.0`,
   наружу `127.0.0.1:8014:8014`); без файла `.env` не падает; образ содержит всё, что нужно галерее №43
   (`v2/web/examples/`) — договорись с ним в статусе.
5. **README — блок «Быстрый старт»** между `<!-- quickstart -->` и `<!-- /quickstart -->` сразу под заголовком
   (остальной README ведёт №36 — больше ничего не трогай): три строки — macOS/Linux, Windows, Docker — и одна строка
   «без git: Code → Download ZIP → START.cmd / start.command». Команды:
   `git clone -b release https://github.com/diiaanns07-droid/winnersOFbankCCbyMNU bcc-review && cd bcc-review && ./start.sh`
   и для PowerShell `git clone -b release … bcc-review; cd bcc-review; .\START.cmd`.
6. **Проверка как у жюри:** `scripts/check_start.sh` — свежий `git clone` во временный каталог, `./start.sh --check`,
   время каждого шага. Прогони сам; время «от клона до ответа сервера» — в статус. Windows-скрипты проверь глазами
   построчно и `pwsh`-разбором, если `pwsh` есть (`[System.Management.Automation.Language.Parser]::ParseFile`);
   на настоящем Windows их запустит №44 (Codex на ноутбуке владельца) — оставь ему в статусе, что проверить.

## Готово, когда
- Свежий клон → `./start.sh --check` проходит; повторный запуск без переустановки; `docker compose config` валиден.
- Свой `tests/v2/test_42_start.py` без сети: скрипты на месте и с нужными окончаниями строк и битами; `start.ps1`
  с BOM; `--check` поднимает сервер и выходит 0; занятый порт → следующий. Весь `tests/v2` — 0 failed.
- «Готово к вливанию: SHA» в `docs/plan-v2/status/42.md` к 21:45, там же время установки и список того, что должен
  проверить №44 на Windows.

## Правила
Общие правила волны — в `wave5/README.md`: только свои файлы, без новых зависимостей, commit + push каждые 5 минут,
строка «Остановился на: … Следующий шаг: …». Модель не вызывать. Скрипты не скачивают и не запускают ничего из
интернета, кроме `pip install -r requirements.txt` (и `winget` только с согласия человека).
