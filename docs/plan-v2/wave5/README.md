# Волна 5 — интерфейс для жюри (27.11, вечер; сдача до 23:59 Астаны)

Владелец, 27.11 19:14 Астаны: «одной командой всё скачали → вылезает милый BCC AI и мило просит API → открывается
система, где можно проверить что угодно; можно дать и готовые данные. Дизайн как в моём проекте Зерде: чисто, текста
немного, но по факту; цвета BCC; для глаза как мёд, плавно, liquid glass уместный». Презентация и питч — только к
финалу (№37 отложен).

**База уже есть.** Веб-демо v2 на стандартной библиотеке: `python -m bcc_review.v2.web` (`src/bcc_review/v2/web/`:
`server.py` — страницы и маршруты, `runner.py` — задания, провайдеры, `.env`, `assets/app.css`, `assets/app.js`).
Отчёт v2 — `src/bcc_review/v2/render/html_assets/report.css`. Задача волны — не новый продукт, а сделать этот веб
красивым, дружелюбным и запускаемым одной командой. Логику качества (pipeline, правила, линзы, судья) не трогаем.

**Дизайн:** `docs/design/bcc-ui.md` (в `bcc/v2` и `release`) — обязателен всем, кроме №44. Исходник маскота —
`docs/design/source/stupits-title-slide.html`.

| № | Кто | Задача | Ветка от `origin/bcc/v2` | Свои файлы |
| :--- | :--- | :--- | :--- | :--- |
| 39 | Claude, свежий | Дизайн-система и главный экран | `v2/39-design` | `assets/tokens.css`, `assets/app.css`, `_layout`, `index_page` |
| 40 | Claude, свежий | BCC AI: маскот и знакомство с ключом | `v2/40-bcc-ai` | `assets/agent.js`, `assets/agent.css`, `v2/web/onboarding.py` |
| 41 | Claude, свежий | Прогресс и отчёт в новом дизайне | `v2/41-report-ui` | `job_page` и прогресс в `server.py`/`app.js`, `render/html_assets/report.css` |
| 42 | Claude, 68 % свободно | Одна команда: `start.sh`, `START.cmd`, Docker | `v2/42-start` | `start.sh`, `start.ps1`, `START.cmd`, `docker-compose.yml`, `main()` в `server.py` |
| 43 | Claude, половина | Готовые отчёты и примеры документов | `v2/43-ready` | `v2/web/gallery.py`, `v2/web/examples/` |
| 44 | Codex на ноутбуке | Путь жюри на настоящем компьютере | `v2/44-laptop` | только `docs/plan-v2/status/44.md` |

## Договорённости между исполнителями

- №39 → всем: `tokens.css` с базовыми классами `.b-*` — к 20:15 в `v2/39-design`. Соседи: `git merge origin/v2/39-design`.
- №40 → №39, №41: `assets/agent.js` к 20:15 (заглушка с первым кадром), полностью к 21:15. API:
  `BCCAgent.mount(el, {size, mood}) → agent`; `agent.mood('idle'|'scanning'|'analyzing'|'verified'|'alert')`;
  `agent.say(text)`; `agent.destroy()`. Автоподключение для каждого `[data-bcc-agent]` с `data-size`, `data-mood`.
- №39 оставляет в шапке `<div data-bcc-agent data-size="40" data-mood="idle"></div>`, на главной вызывает
  `gallery_block(app) -> str` из `v2/web/gallery.py` (№43); пока модуля нет — `try/except ImportError`, пустой блок.
- №40 — маршруты `/welcome`, `POST /api/key`; №43 — `/examples/…`; №41 — `/jobs/…`. Маршрут в `server.py` —
  одна строка в начале `do_GET`/`do_POST` с пометкой `# №NN`. Конфликты при вливании разрешает №11.
- README и SUBMISSION ведёт №36. Блок «Быстрый старт» между `<!-- quickstart -->` и `<!-- /quickstart -->` в начале
  README — у №42.

## Расписание (Астана; в Бишкеке на час больше)

- 19:45 — старт; каждые 5 минут commit + push (можно «WIP: …»).
- 20:15 — `tokens.css` (№39) и заглушка `agent.js` (№40) в своих ветках.
- 21:15 и 21:45 — №11 вливает готовое в общую сборку, проверяет и пишет замечания в `status/NN.md` исполнителя.
- **21:45 — «Готово к вливанию: SHA»** в статусе у каждого; после этого — только исправления.
- 22:15 — интерфейс в `bcc/v2` и `release`, если `tests/v2` зелёные и снимки в порядке; иначе в релизе остаётся
  прежний веб, ничего не ломаем.
- 22:15–22:45 — №44: свежий клон `release` на ноутбуке, одна команда, весь путь жюри. ~23:15 — тег `v2.0.0`.

## Общие правила

- Всё по-русски. В интерфейсе — коротко, по делу, на «вы».
- Только свои файлы. Нужна правка в чужом — строка в своём статусе «Прошу №NN: …», что именно и зачем.
- Ни одной новой зависимости и ни одной внешней ссылки при работе страницы (CDN, Google Fonts): жюри может быть
  офлайн. Шрифт — стек из токенов; Inter можно вложить файлом (лицензия OFL, до 300 КБ).
- Не трогать: `src/bcc_review/v2/stages|lenses|judge|rules` и всё, что меняет содержание отчёта; `reports/`,
  README (кроме блока №42), SUBMISSION.
- Тесты: `PYTHONPATH=src python -m pytest tests/v2/test_14_web.py tests/v2/test_34_web_release.py
  tests/v2/test_max_web_relative_data_dir.py -q` и свой `tests/v2/test_NN_*.py` — без сети и без ключа. Перед
  «Готово» — весь `tests/v2` (норма — 0 failed; если не хватает `pymupdf` или `google-genai` —
  `pip install -r requirements.txt`).
- Модель не вызывать: смотреть на `--provider mock` (официальный документ: `release/input/requirements.md`) и
  `offline`; готовый отчёт для показа — `PYTHONPATH=src python -m bcc_review release/input/requirements.md
  out/mock.md --provider mock`, потом `python -m bcc_review.v2.web --fixture out/mock.json`.
- Снимки: Playwright уже стоит (`require('playwright')`, `chromium.launch()`), 1440×900 и 390×844, файлы
  `docs/plan-v2/wave5/shots/NN-*.png` (до 300 КБ каждый). Без снимков работа не принимается.
- Ключи не коммитить и в чат не вставлять; `.env` уже в `.gitignore`.
- Статус — `docs/plan-v2/status/NN.md`: «➜ Сейчас», «Остановился на: … Следующий шаг: …», «Готово к вливанию: SHA»
  (упрётся чат в лимит — другой продолжит с того же места).
