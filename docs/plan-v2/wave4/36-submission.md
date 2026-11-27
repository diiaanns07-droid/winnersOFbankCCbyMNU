# Волна 4 — №36: сдача — настоящие отчёты, рабочие ссылки, всё, что обещает SUBMISSION

Ты — сессия Claude Code команды STUPITS (хакатон BCC-HUB × MNU, кейс «ИИ-агент проверки требований»), роль №36.
Если раньше ты был другим номером — твоя прежняя ветка и статус остаются, это новая задача.
Репозиторий: https://github.com/diiaanns07-droid/winnersOFbankCCbyMNU. Тимлид — №11, доска:
`git fetch origin v2/11-clarify && git show origin/v2/11-clarify:docs/plan-v2/wave4/BOARD.md` — читай в начале и раз в час.
Всё, что видит жюри, и ответы владельцу (Сергей) — по-русски. **Сдача — 27.11 до 23:59 Астаны (UTC+5).**

## Где мы (27.11, 19:00 Астаны)
- Релиз — `bcc/v2` (голова `3e7133c2`); исправления до 21:00 вливает №11, около 21:05 он объявит финальную голову
  в `docs/plan-v2/INTEGRATION.md`. Потом №11 ставит тег `v2.0.0` и ветку `release` (по умолчанию на GitHub).
- **Чего нет, хотя `SUBMISSION.md` и `README.md` на это ссылаются:** `reports/requirements.md`, `.json`, `.html`,
  `reports/requirements_pdf.md`, `reports/other_topic_cashback.md`, `reports/requirements.gemini.md`, таблица в
  `reports/README.md` («Отчёты появятся на теге v2.0.0»), `presentation/deck.pdf` (делает №37).
- Файлы №16 (README, SUBMISSION, `reports/`, `scripts/reports_table.py`) — теперь твои: №16 недоступен.

## Задача
1. **До 21:00 — подготовка.** Ветка `v2/36-submission` от `origin/bcc/v2`. Скрипт проверки ссылок
   (`scripts/check_links.py` + тест `tests/v2/test_36_links.py`): каждая относительная ссылка в `README.md`,
   `SUBMISSION.md`, `reports/README.md`, `presentation/README.md` ведёт на файл в дереве. Список «чего нет» — в статус.
   Строки SUBMISSION, которые к ночи не станут правдой (например, прогон на Gemini под Windows, если ключа нет),
   — переписать честно или убрать.
2. **После финальной головы (~21:05) — отчёты на ней, без кэша, руками не править:**
   - официальный: `python -m bcc_review release/input/requirements.md reports/requirements.md --provider claude_cli --model sonnet --no-cache --export jira,docx`
     (модель — sonnet, как в замерах №31; Opus — только если владелец скажет);
   - тот же документ из PDF: `release/input/requirements.pdf` → `reports/requirements_pdf.md`;
   - другая тема: `evaluation/dev/corpus/cases/cashback.base/source.md` → `reports/other_topic_cashback.md`;
   - Gemini — только если есть ключ (у №24 или владелец прогонит на ноутбуке), иначе строку убрать;
   - `python -m bcc_review verify <отчёт>.json <исходник>` — для каждого; `python scripts/reports_table.py reports --write`.
3. **Числа в README и SUBMISSION** — только из замера №31 на финальной голове (`evaluation/v2/RESULTS.md`), с датой.
4. **Передача:** commit + push каждые 5 минут; к 22:15 — строка в статусе «Готово к сдаче: SHA» (только `reports/`,
   README, SUBMISSION, `scripts/check_links.py`, тест). Вливает №11, он же ставит тег и `release`.
**Готово, когда:** `scripts/check_links.py` — 0 битых ссылок; все отчёты из SUBMISSION есть и проходят `verify`.

## Правила
- Статус — `docs/plan-v2/status/36.md`: таблица «➜ Сейчас в работе у №36», строка «Остановился на: … Следующий шаг: …».
- Живые вызовы — общий лимит: только прогоны из п. 2 (3–4 полных), заранее напиши №31 в статусе, когда пойдёшь.
- Ключи не коммитить и в чат не вставлять. Репозиторий приватный — открыть его жюри решает владелец (чек-лист SUBMISSION).
- Отчёт владельцу — коротко: что готово (SHA), чего не хватает, что нужно от него.
