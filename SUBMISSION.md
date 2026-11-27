# Сдача: BCC Review — ИИ-агент проверки требований

Кейс BCC-HUB × MNU FinTech Hackathon «ИИ-агент проверки требований»
([ТЗ](https://github.com/BCC-HUB/ai-requirements-validator-task)). Команда STUPITS.

## Что сдаём и где

| Что | Где |
| :--- | :--- |
| Репозиторий | <https://github.com/diiaanns07-droid/winnersOFbankCCbyMNU>, ветка по умолчанию `release` = тег `v2.0.0` |
| Как запустить | [`README.md`](README.md), «Быстрый старт»: три шага на бесплатном Gemini, Windows и macOS/Linux |
| Одна команда | `python -m bcc_review <файл требований> <файл отчёта.md>` |
| Исходный документ | [`release/input/requirements.md`](release/input/requirements.md) — официальный, байт в байт; его PDF — [`release/input/requirements.pdf`](release/input/requirements.pdf); происхождение и SHA-256 — [`release/input/PROVENANCE.md`](release/input/PROVENANCE.md) |
| Отчёт агента по документу | [`reports/requirements.md`](reports/requirements.md), интерактивный [`reports/requirements.html`](reports/requirements.html), для программ [`reports/requirements.json`](reports/requirements.json) |
| Тот же документ из PDF | [`reports/requirements_pdf.md`](reports/requirements_pdf.md) (+ копия PDF с выделенными цитатами) |
| Прогон на бесплатном Gemini | [`reports/requirements.gemini.md`](reports/requirements.gemini.md) — Windows, ключ AI Studio |
| Второй документ (другая тема) | [`reports/other_topic_cashback.md`](reports/other_topic_cashback.md) |
| Все прогоны, модели, время, `verify` | [`reports/README.md`](reports/README.md) |
| Видео-демо (2–3 мин) | [`presentation/demo.mp4`](presentation/demo.mp4) |
| Презентация | [`presentation/deck.pdf`](presentation/deck.pdf) (и `deck.pptx`) |
| Качество: эталон, корпус, стабильность | [`evaluation/v2/RESULTS.md`](evaluation/v2/RESULTS.md) |
| Разбор задачи и эталон дефектов | [`docs/task-analysis.md`](docs/task-analysis.md) |

Каждый отчёт сформирован командой `python -m bcc_review …` на теге `v2.0.0` и руками не правился: коммит агента —
в паспорте отчёта, а `python -m bcc_review verify отчёт.json исходник` заново находит каждую цитату в исходнике.

## Соответствие п. 7 ТЗ

| Требование | Где выполнено |
| :--- | :--- |
| Код агента и файл зависимостей | `src/bcc_review/`, [`requirements.txt`](requirements.txt) (версии зафиксированы), `pyproject.toml` |
| Как получить ключ LLM | README, шаг 2: Google AI Studio → Create API key |
| Куда положить ключ | README, шаг 2: `.env` в корне (шаблон [`.env.example`](.env.example) без ключа) |
| Какой командой запустить | README, шаг 3 |
| Куда ляжет отчёт | README, «Куда ложится отчёт»: `.md`, `.json`, `.html` рядом с указанным путём |
| Модель указана в инструкции | `gemini-3.8-flash` с запасными `gemini-3.6-flash`, `gemini-3.5-flash-lite`; фактическая — в паспорте отчёта |
| Секретов в репозитории нет | `.env` в `.gitignore`; тест `test_no_secrets_in_tracked_files`; аудит истории всех веток |

## Как жюри проверить за пять минут

1. Открыть [`reports/requirements.md`](reports/requirements.md) на GitHub — первый экран: вердикт, блокеры,
   «что исправить первым». Интерактивная версия — скачать [`reports/requirements.html`](reports/requirements.html)
   и открыть двойным щелчком (работает без интернета).
2. Запустить агента самим по README (три шага) или одной командой проверки — она проверит ключ, прогонит документ
   кейса без кэша, запустит `verify` и сверку с нашим эталоном и напечатает сводку:

   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts\jury_check.ps1
   ```

   ```bash
   scripts/jury_check.sh
   ```

3. Без ключа: `python -m bcc_review release/input/requirements.md out/mock.md --provider mock` — весь конвейер за
   секунду на записанных ответах живого прогона модели.

## Чек-лист оператора перед сдачей

- [ ] **Доступ жюри.** Сделать репозиторий публичным: Settings → General → Danger Zone → Change repository
      visibility → Public. Публичными станут все ветки и вся история; аудит секретов по всей истории всех веток
      пройден (только заведомые подделки в тестах). Если публиковать нельзя — Settings → Collaborators → Add people
      (логины жюри, роль Read).
- [ ] **Ветка по умолчанию — `release`:** Settings → General → Default branch → ⇄ → `release` → Update. Сейчас по
      умолчанию стоит ветка с разбором задачи, и жюри увидело бы её README.
- [ ] **CI.** Для публичного репозитория Actions бесплатны — после открытия зелёные прогоны «Тесты» (3 ОС, Docker)
      появятся на `release` и теге `v2.0.0`. Для приватного: Settings → Billing and plans — сейчас задания не
      стартуют из-за неуспешного платежа или лимита расходов.
- [ ] **По желанию — секрет `GEMINI_API_KEY`:** Settings → Secrets and variables → Actions → New repository secret,
      имя `GEMINI_API_KEY`. Тогда Actions → «Сформировать отчёт» → Run workflow строит отчёт на Gemini прямо
      на GitHub (отчёт — в артефактах запуска). Workflow виден, только когда лежит в ветке по умолчанию.
- [ ] **Видео и слайды:** `presentation/demo.mp4` и `presentation/deck.pdf` открываются по ссылкам выше. Если видео
      загружено ещё и на YouTube или Google Drive, вписать ссылку сюда: _____
- [ ] **Проверка глазами жюри:** открыть репозиторий в окне инкогнито (или аккаунтом без доступа к команде): виден
      README ветки `release`, ссылки на отчёт, видео и слайды открываются.
- [ ] **Форма сдачи:** ссылка на репозиторий, рядом — отчёт (`reports/requirements.md` или `.html`) и исходный
      документ (`release/input/requirements.md`).
