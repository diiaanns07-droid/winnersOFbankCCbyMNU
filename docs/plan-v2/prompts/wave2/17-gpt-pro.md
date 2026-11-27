**Обновление для №17 (GPT Pro), 27.11 04:45 по Астане.** Ядро v2 работает: интеграционная ветка `bcc/v2` в https://github.com/diiaanns07-droid/winnersOFbankCCbyMNU. На sonnet через Claude Code CLI: `complete`, 9 вызовов, 4 минуты, К 5/5 (критичными 4), С 18/20, ложных критичных 0, отчёт ~800 строк. **Gemini ни разу не запускался живьём** — у облачных сессий нет ключа. Ты и оператор — единственный путь проверить то, что увидит жюри. План второй волны: `docs/plan-v2/WAVE2.md` (в ветке `claude/gallant-gauss-vbjqc8`).

Если не можешь запускать команды сам — давай оператору точные блоки PowerShell и проси вставить вывод.

1. **Сейчас — Windows + Gemini на `bcc/v2`:**
   ```powershell
   git clone https://github.com/diiaanns07-droid/winnersOFbankCCbyMNU bcc-v2; cd bcc-v2; git switch bcc/v2
   py -3.12 -m venv .venv; .venv\Scripts\python -m pip install -r requirements.txt -e .
   copy .env.example .env   # вписать GEMINI_API_KEY=...
   .venv\Scripts\python -m bcc_review doctor --live
   .venv\Scripts\python -m bcc_review release\input\requirements.md out\gemini.md --provider gemini
   .venv\Scripts\python -m bcc_review verify out\gemini.json release\input\requirements.md
   ```
   Сверь каждый шаг с README (что в нём неверно или не хватает). Зафиксируй время, число вызовов, фактическую модель, статус прогона, ошибки, первый экран отчёта. Повтори с явными `--model gemini-3.6-flash` и `--model gemini-3.5-flash-lite`. Итог оператор кладёт в `docs/plan-v2/status/17.md` (ветка `eval/blind-v2`) — или передаёт №01 и №02 через их сессии.
2. **Слепые ТЗ** (если ещё не сделаны): 3 документа в шаблоне банка и чистая версия одного, эталон у тебя. Прогон на Gemini, оценка по закрытому эталону, обратная связь категориями, без раскрытия эталона.
3. **Разбор официального отчёта глазами жюри** (оператор пришлёт `out/official.md` последнего прогона №01 или твой `out/gemini.md`): оценки 1–10 за полноту, точность, доказательность, читаемость, пользу для аналитика и соответствие п. 6 ТЗ; 10 конкретных правок с номерами строк — адресно №13 (текст), №10 (критичность и дубли), линзам №05–09 (промахи).
4. **Питч к 14:00** (раньше, чем планировали: №14 собирает слайды и видео): `presentation/pitch.md` — питч на 3–5 минут, содержание 10–12 слайдов, сценарий видео на 2–3 минуты с таймкодами, 20 вопросов жюри с короткими ответами.
5. **В 15:00 и 17:00** — повтор пункта 1 на тегах `v2.0.0-rc1` и `v2.0.0`; прогон Gemini на финальном теге — отчёт `reports/requirements.gemini.*` для №16.
