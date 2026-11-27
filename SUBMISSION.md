# Сдача: BCC Review — ИИ-агент проверки требований

Кейс BCC-HUB × MNU FinTech Hackathon «ИИ-агент проверки требований»
([ТЗ](https://github.com/BCC-HUB/ai-requirements-validator-task)). Команда STUPITS.

## Что сдаём и где

| Что | Где |
| :--- | :--- |
| Репозиторий | <https://github.com/diiaanns07-droid/winnersOFbankCCbyMNU/tree/main> — ветка `main` (= `release`, тот же коммит); клонировать: `git clone -b main https://github.com/diiaanns07-droid/winnersOFbankCCbyMNU.git` |
| Как запустить | [`README.md`](README.md): в самом начале — одна команда (`./start.sh`, `START.cmd` или `docker compose up`) открывает систему в браузере, ключ можно не вводить; ниже «Быстрый старт» — три шага в командной строке на бесплатном Gemini, Windows и macOS/Linux |
| Одна команда | `python -m bcc_review <файл требований> <файл отчёта.md>` |
| Исходный документ | [`release/input/requirements.md`](release/input/requirements.md) — официальный, байт в байт; его PDF — [`release/input/requirements.pdf`](release/input/requirements.pdf); происхождение и SHA-256 — [`release/input/PROVENANCE.md`](release/input/PROVENANCE.md) |
| Отчёт агента по документу | [`reports/requirements.md`](reports/requirements.md), интерактивный [`reports/requirements.html`](reports/requirements.html), для программ [`reports/requirements.json`](reports/requirements.json); Word — [`requirements.docx`](reports/requirements.docx), импорт в Jira — [`requirements.jira.csv`](reports/requirements.jira.csv). Sonnet, без кэша, код `0a30c67`: К 5 из 5 (все критичными), С 20 из 20, ложных критичных 0, цитат 83 из 83 |
| Тот же документ из PDF | [`reports/requirements_pdf.md`](reports/requirements_pdf.md); копия PDF с выделенными цитатами — [`requirements_pdf.annotated.pdf`](reports/requirements_pdf.annotated.pdf). К 5 из 5, С 18 из 20, цитат 87 из 87 |
| Прогон на бесплатном Gemini | Отчёта на Gemini в `reports/` нет: в замере 27.11 19:35 бесплатная квота `gemini-3.8-flash` кончилась на первом вызове, агент перешёл на запасные модели (К 3 и 5 из 5, С 8 и 9 из 20 — это потолок запасных, не Flash; [`docs/JURY.md`](docs/JURY.md), раздел 3). Как прогнать самим — [`README.md`](README.md), шаги 2–3 (или `scripts\gemini_report.ps1` на Windows) |
| Второй документ (другая тема) | [`reports/other_topic_cashback.md`](reports/other_topic_cashback.md) — «Кэшбэк в выбранной категории», чистый контрольный документ корпуса ([`source.md`](evaluation/dev/corpus/cases/cashback.base/source.md), дефекты в него не закладывались): критичных 0, существенных 0, 6 незначительных, вердикт «можно» |
| Цепочка уточнения на чужом ТЗ | [`reports/demo_answers/README.md`](reports/demo_answers/README.md) — вопросы → ответы владельца → исправленное ТЗ → повторная проверка |
| Все прогоны, модели, время, `verify` | [`reports/README.md`](reports/README.md) |
| Видео-демо (2–3 мин) | [`presentation/demo.mp4`](presentation/demo.mp4); с вшитыми субтитрами — [`presentation/demo_subtitled.mp4`](presentation/demo_subtitled.mp4), отдельно — [`presentation/demo.srt`](presentation/demo.srt) |
| Презентация | В сдаче 27.11 слайдов (`presentation/deck.pdf`) нет — их готовим к финалу 4.12; агента показывает видео-демо выше |
| Как проверить нас за 5 минут | [`docs/JURY.md`](docs/JURY.md) — три команды, каждое число с прогоном и командой пересчёта, худшие прогоны рядом с лучшими |
| Качество: эталон, корпус, стабильность | [`evaluation/v2/RESULTS.md`](evaluation/v2/RESULTS.md); полные таблицы последних замеров — в ветке №31 (ссылка в `docs/JURY.md`) |
| Разбор задачи и эталон дефектов | [`docs/task-analysis.md`](docs/task-analysis.md) |

Каждый отчёт в корне `reports/` сформирован командой `python -m bcc_review …` без кэша и руками не правился.
Коммит агента — в паспорте отчёта: это финальная сборка `bcc/v2` 27.11 (у `reports/demo_answers/` — более ранняя
сборка, она названа в его README). Что изменилось в коде после неё в ветке `main`, показывает
`git log --oneline <коммит из паспорта>..main -- src`. `python -m bcc_review verify отчёт.json исходник` заново
находит каждую цитату в исходнике и сверяет SHA-256 входа. Команды и сводка прогонов —
[`reports/README.md`](reports/README.md).

## Соответствие п. 7 ТЗ

| Требование | Где выполнено |
| :--- | :--- |
| Код агента и файл зависимостей | `src/bcc_review/`, [`requirements.txt`](requirements.txt) (версии зафиксированы), `pyproject.toml` |
| Как получить ключ LLM | README, шаг 2: Google AI Studio → Create API key |
| Куда положить ключ | README, шаг 2: `.env` в корне (шаблон [`.env.example`](.env.example) без ключа) |
| Какой командой запустить | README, шаг 3 |
| Куда ляжет отчёт | README, «Куда ложится отчёт»: `.md`, `.json`, `.html` рядом с указанным путём |
| Модель указана в инструкции | `gemini-3.8-flash` с запасными `gemini-3.7-flash` → `3.6-flash` → `3.5-flash` → `3.5-flash-lite` → `3.1-flash-lite` (как `GEMINI_FALLBACK_MODELS` в `.env.example`); фактическая — в паспорте отчёта |
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
- [ ] **Ветка по умолчанию — `main`:** Settings → General → Default branch → ⇄ → `main` → Update. Сейчас по
      умолчанию стоит ветка с разбором задачи (`claude/nice-edison-gpkcfl`), и жюри по ссылке без `/tree/main`
      увидело бы её README. README и эта страница уже ведут на `main` (`git clone -b main`, `/tree/main`).
- [ ] **CI.** Для публичного репозитория Actions бесплатны — после открытия зелёные прогоны «Тесты» (3 ОС, Docker)
      появятся на `main`. Для приватного: Settings → Billing and plans — сейчас задания не
      стартуют из-за неуспешного платежа или лимита расходов.
- [ ] **По желанию — секрет `GEMINI_API_KEY`:** Settings → Secrets and variables → Actions → New repository secret,
      имя `GEMINI_API_KEY`. Тогда Actions → «Сформировать отчёт» → Run workflow строит отчёт на Gemini прямо
      на GitHub (отчёт — в артефактах запуска). Workflow виден, только когда лежит в ветке по умолчанию.
- [ ] **Видео:** `presentation/demo.mp4` открывается по ссылке выше. Если видео
      загружено ещё и на YouTube или Google Drive, вписать ссылку сюда: _____
- [ ] **Проверка глазами жюри:** открыть репозиторий в окне инкогнито (или аккаунтом без доступа к команде): виден
      README ветки `main`, ссылки на отчёт и видео открываются (`python scripts/check_links.py` — 0 битых).
- [ ] **Форма сдачи:** ссылка на репозиторий (`…/winnersOFbankCCbyMNU/tree/main`), рядом — отчёт (`reports/requirements.md` или `.html`) и исходный
      документ (`release/input/requirements.md`).
