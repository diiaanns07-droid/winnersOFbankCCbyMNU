# Новые команды-конкуренты: поиск 26.11.2026

**Кейс:** ИИ-агент проверки качества ТЗ, BCC-HUB × MNU FinTech Hackathon 2026.
Задание: <https://github.com/BCC-HUB/ai-requirements-validator-task>.

**Дата проверки:** 26.11.2026. Репозитории смотрел примерно до 20:40 по Астане (UTC+5). Самый поздний
коммит, который я видел, сделан в 20:35. Сдача работ 27.11 в 23:59 (см. раздел 6), поэтому
репозитории ещё могут измениться.

**Итог:** 9 новых подтверждённых команд и 2 неподтверждённых кандидата. По команде 9 есть оговорка: она может
совпадать с уже исключённым аккаунтом Adil-Meiramov.

Из выдачи исключены 34 аккаунта, изученные раньше: azekowka, almassuleimenov, saynzz, l9kk,
mynbaev1989-cell, Dossm04, yerikoov, yernururue, Nurdaulet362, q4erty, VllSunday, Kirirto-kun,
SaginbekDaniel, OralbekUrusbekov, 01danl, DidarAbsatar, bkht17, Akmaral30, doni9977, gooflamingo75,
L4RBIX, DieeLLl, Akylzhan9837, Abu-Jamilya, AdilPython, zhneo, mirranet, Adil-Meiramov,
I-am-King-of-the-World, astmirzhan, Amirzhan8920, jjjjjsasda, Aidos227, Baurzhanovvv.

**Как читать.** Для каждой команды есть две ссылки: где видна связь с кейсом и где лежит её
собственная работа. Пометка «Видно» означает, что я проверил это в коде или отчёте. Пометка
«Только в README» означает обещание, которое по файлам не подтверждено. Номера строк в `.md`
открываются по ссылке с `?plain=1#L…`.

---

## Сводная таблица

| # | Команда / репозиторий | Отчёт по документу кейса в репо | Модель в отчёте | Требований / дефектов (крит.) | Вердикт отчёта |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | [ERA216/Hac](https://github.com/ERA216/Hac), «Ревизор ТЗ» | есть | gemini-3.6-flash | 37 / 26 (5) | нельзя |
| 2 | [khusrav11/solohive](https://github.com/khusrav11/solohive), SoloHive | есть + исправленное ТЗ | gemini-3.8-flash через OpenRouter | 40 / 55 (6) | не готов; после уточнения «с условиями» |
| 3 | [Da0ss/-ship](https://github.com/Da0ss/-ship) | есть (старый, 25.11) | gemini-3.6-flash | 43 / 42 (15) | нельзя |
| 4 | [nurkhan0/hackathon-](https://github.com/nurkhan0/hackathon-) | есть | gemini-3.5-flash-lite | 23 / 136 (44) | «неполная проверка, решение не принимается» |
| 5 | [Garryflop/Revizorro](https://github.com/Garryflop/Revizorro) | нет | — | — | — |
| 6 | [Aqtanbi/clarifai](https://github.com/Aqtanbi/clarifai), ClarifAI | нет (есть демо-сайт) | — | — | — |
| 7 | [Raimbek-pro/SpecAgent](https://github.com/Raimbek-pro/SpecAgent) | нет | — | — | — |
| 8 | [sagudenovam-collab/Crumbl_cookies_cream_ai](https://github.com/sagudenovam-collab/Crumbl_cookies_cream_ai) | нет (сами признают) | — | — | — |
| 9 | [omkas07/requirements-review-agent](https://github.com/omkas07/requirements-review-agent) | нет, каркас | — | — | — |

Самые сильные из новых — **ERA216** и **SoloHive**. У обоих есть уточняющие вопросы, тест-кейсы,
собственный эталон дефектов и измерение по нему.

---

## 1. Подтверждённые команды: есть отчёт по документу кейса и код

### 1.1. ERA216 — «Ревизор ТЗ»
Репозиторий: <https://github.com/ERA216/Hac>. Один автор (ERA216), 22 коммита, с 25.11 21:01 по 26.11 20:35 (UTC+5).

- **Связь с кейсом:** <https://github.com/ERA216/Hac/blob/main/README.md?plain=1#L5> («для BCC-HUB x MNU
  FinTech Hackathon»). Отчёт сделан по документу «Уведомление о расходах по карте».
- **Своя работа:** <https://github.com/ERA216/Hac/blob/main/reports/report.md>, рядом `report.html` и
  `report.json`. Код в [`revizor/orchestrator.py`](https://github.com/ERA216/Hac/blob/main/revizor/orchestrator.py)
  (707 строк). Промпты-«линзы» `revizor/prompts/lenses/analyst|architect|qa|security.md`. Тесты, в том числе
  `tests/test_injection.py`.
- **Открыть первым:** `reports/report.md` (итог с [строки 630](https://github.com/ERA216/Hac/blob/main/reports/report.md?plain=1#L630)),
  затем [`eval/RESULTS.md`](https://github.com/ERA216/Hac/blob/main/eval/RESULTS.md).
- **Видно в отчёте:**
  - Паспорт: revizor 0.1.0 (git `af49d06`), прогон 25.11.2026 в 21:48 (Алматы). Запрошена
    `gemini-3.8-flash`, фактически ответила `gemini-3.6-flash`. 8 вызовов LLM (7 из кэша), 71 с.
  - 37 требований, 26 дефектов: 5 критичных, 15 существенных, 6 замечаний. Требований без замечаний: 10 из 37.
  - 10 уточняющих вопросов, из них 5 блокирующих. Есть раздел «Недостающие тест-кейсы».
  - Структура: паспорт → нарезка → каждое требование → набор → вопросы → тест-кейсы → сводка → итог → приложения.
  - Итог: разработку и тестирование начинать нельзя. Исправить первым D-02, противоречие Ф-2 и критерия приёмки
    о том, к какому месяцу относится покупка.
- **Видно в eval/RESULTS.md:** 12 из 12 ключевых дефектов, 25 из 27 по эталону, 53 из 53 цитат подтверждены.
  В отчёте 26 дефектов, из них 4 вне эталона. Есть второй случай `eval/cases/p2p/`.
- **Оговорки:** эталон составила сама команда. Отчёт последний раз коммитился 25.11 в 21:50, а код менялся
  весь день 26.11, например коммит `c1055d4` «Попарная сверка требований». Отчёт на новом коде не пересобран.
  Кэш ответов модели лежит в `reports/llm-cache/`.

### 1.2. khusrav11 — SoloHive (один участник)
Репозиторий: <https://github.com/khusrav11/solohive>. Автор Khusravkhon Ziyoboev, 68 коммитов, с 25.11 23:51 по 26.11 18:35.

- **Связь с кейсом:** <https://github.com/khusrav11/solohive/blob/main/README.md?plain=1#L3> («Команда SoloHive ·
  BCC-HUB x MNU FinTech Hackathon 2026») и
  [`eval/gold_defects.yaml`](https://github.com/khusrav11/solohive/blob/main/eval/gold_defects.yaml)
  («учебный кейс BCC-HUB»).
- **Своя работа:** <https://github.com/khusrav11/solohive/blob/main/reports/report.md> (2164 строки), рядом
  PDF, DOCX, HTML и JSON. Исправленное ТЗ:
  [`reports/report_revised.md`](https://github.com/khusrav11/solohive/blob/main/reports/report_revised.md).
  Агенты: `solohive/agents/` (segmenter, analyst, reviewer, critic, scenarist, interviewer, reviser).
- **Открыть первым:** `reports/report.md`, итог с [строки 1917](https://github.com/khusrav11/solohive/blob/main/reports/report.md?plain=1#L1917).
  Затем `reports/report_answers.json` и `reports/report_revised.md`.
- **Видно в отчёте:**
  - Паспорт: SoloHive Requirements Validator v1.5.1, коммит `a3cb339`. Модель `google/gemini-3.8-flash`
    через OpenRouter (не AI Studio), temperature 0,2.
  - Вход `requirements.pdf`, 26.11.2026 в 18:23. 11 вызовов LLM, около 120 тыс. токенов на вход, 212 с.
  - 40 требований, 55 нарушений: 6 критичных, 37 существенных, 12 замечаний.
  - Вердикт: не готов к разработке и не готов к тестированию.
  - Раздел 8 «Уточнение»: 11 ответов, устранено 32 дефекта, после этого «готов с условиями».
- **Оговорки:** вердикт после уточнения опирается на ответы в `reports/report_answers.json`. Это заранее
  написанные решения, например «критерий приёмки №2 исправить». Цифры «38 из 40 по эталону (95%)» и
  «≈ $0.45 за прогон» я видел только в README.

### 1.3. Da0ss — `-ship`
Репозиторий: <https://github.com/Da0ss/-ship>. Автор в коммитах «Aydin Deniz». Ветка по умолчанию
`claude/ai-requirements-validator-pevqat`; ветка `features/fintech-review` указывает на тот же коммит `ec5c38e`.
Это не тот же человек, что исключённый Dossm04: другой автор и другая структура кода (сравнил с
`Dossm04/saqta-tz-auditor`).

- **Связь с кейсом и своя работа:**
  <https://github.com/Da0ss/-ship/blob/claude/ai-requirements-validator-pevqat/reports/report.md>. Это отчёт по
  «Уведомлению о расходах по карте» с разбором `/alerts/saveLimit`. Код:
  [`validator/pipeline.py`](https://github.com/Da0ss/-ship/blob/claude/ai-requirements-validator-pevqat/validator/pipeline.py)
  (722 строки), а также `facts.py`, `review.py`, `critic` и другие модули.
- **Открыть первым:** `reports/report.md`, итог со строки 495, вердикт со строки 532.
- **Видно в отчёте:**
  - Паспорт: 2026-11-25 11:55 UTC, `gemini-3.6-flash`, агент `v0.3.0-0-g8e4797b`.
  - 43 требования, 42 замечания: 15 критичных, 16 существенных, 11 незначительных.
  - Вердикт: разработку и тестирование начинать нельзя.
  - Исправить первым: Ф-3 ↔ Ф-4; для saveLimit заменить GET на POST или PUT; коды HTTP; покупку 31.01 отнести к январю.
- **Только в README или только на чужом документе:** банковская проверка, критик, раздел 7 «Чек-лист ревью»,
  раздел 8 «Вопросы к владельцу продукта», блок «Кратко», HTML-отчёт. В отчёте по кейсу их нет, там шесть
  разделов, и последний раз он менялся 25.11 в коммите `5419985`. Эти части есть только в
  `reports/autopay/report.md`, отчёте по документу, который команда написала сама (`docs/samples/autopay.md`,
  22 заложенных дефекта). Метрика в `reports/autopay/metrics.txt`: найдено 21 из 22, 69 замечаний, 55% совпали
  с эталоном. Она относится к их собственному документу, а не к кейсу.

### 1.4. nurkhan0 — `hackathon-`
Репозиторий: <https://github.com/nurkhan0/hackathon->. Автор Nurkhan, 8 коммитов. Код агента появился 26.11 в 19:51, отчёт в 20:30.

- **Связь с кейсом:** [`docs/TASK.md`](https://github.com/nurkhan0/hackathon-/blob/main/docs/TASK.md) и
  `docs/requirements.md`, копии задания. Сама по себе копия ничего не доказывает, но по ней сделан отчёт.
- **Своя работа:** <https://github.com/nurkhan0/hackathon-/blob/main/reports/report.md> (4129 строк). Код в
  `validator/` (ingest, segment, review, setlevel, verify, lint, report, llm).
- **Открыть первым:** `reports/report.md`, сводка со строки 4063, итог со строки 4117.
- **Видно в отчёте:**
  - Паспорт: 26.11.2026 15:27 UTC, `gemini-3.5-flash-lite`, коммит `3e78430`.
  - В сводке 23 требования, 3 сценария приёмки, 5 спецификаций интерфейса и 7 примеров.
  - 136 подтверждённых нарушений, 44 критичных. Многие из них общие: «нет критериев успешности».
  - Итог: «Неполная проверка, решение не принимается». Упали пачки R-001 и R-022.
  - Рядом лежит `reports/report.mock.md` с пометкой «черновик имитации» (FakeClient).

---

## 2. Подтверждённые команды: есть код и связь с кейсом, отчёта по документу кейса в репо нет

### 2.1. Garryflop — Revizorro
Репозиторий: <https://github.com/Garryflop/Revizorro>. Автор Harryfloppa, 23 коммита, с 25.11 18:36 по 26.11 12:39.

- **Связь с кейсом:** <https://github.com/Garryflop/Revizorro/blob/main/eval/expected_defects.yaml#L10>. Это
  их эталон из 37 дефектов именно для документа кейса; D01 — Ф-2 против «Февральский счётчик вырос». Второй
  эталон: `eval/generalization/phone_transfer.md`, 14 дефектов.
- **Своя работа:** [`backend/src/revizorro/pipeline/orchestrator.py`](https://github.com/Garryflop/Revizorro/blob/main/backend/src/revizorro/pipeline/orchestrator.py)
  и `backend/src/revizorro/agents/` (segmenter, reviewers, set_reviewers, critic, clarifier, summarizer).
  Веб-интерфейс на React и Ant Design в `frontend/`.
- **Только в README:** таблица качества. «Баланс» (OpenAI `gpt-6-luna` / `gpt-6.1-terra`): 34 из 37 на `.md`,
  35 из 37 на `.pdf`, 13 из 14 на втором документе. Бесплатный Gemini: 17 из 37. Файлов отчётов в репозитории нет.
- С «Ревизором ТЗ» от ERA216 названия похожи, но это разные команды: разная структура, разные шаблоны промптов
  (Jinja и `$`-подстановка), сходство промптов около 25%. С исключённым l9kk/reqcheck структура тоже разная.

### 2.2. Aqtanbi — ClarifAI (сайт и репозиторий — одна находка)
Репозиторий: <https://github.com/Aqtanbi/clarifai>. Авторы aqs_h и zhasmira.mamyrbayeva, 30 коммитов. Первый коммит
26.11 в 10:16 называется «initial commit: bcc hub case».

- **Связь с кейсом:** <https://github.com/Aqtanbi/clarifai/blob/main/README.md?plain=1#L11>. Там цитируются
  дефекты кейса: Ф-2 против критерия приёмки №2, Ф-3 против Ф-4.
- **Своя работа:** [`validator/pipeline.py`](https://github.com/Aqtanbi/clarifai/blob/main/validator/pipeline.py)
  (526 строк), `mcp_server.py`, сайт (`render.yaml`, `vercel.json`).
- **Демо:** <https://clarifai-rv5l.onrender.com>, код доступа указан в README. Из нашей облачной среды адрес не
  открылся (DNS), так что результат на демо не проверен.
- **Только в README:** «56–71% на эталоне из 34 дефектов» на `gemini-3.5-flash-lite`. Файла эталона в
  репозитории я не нашёл (есть только `eval/run_eval.py`). В `reports/` пусто.

### 2.3. Raimbek-pro — SpecAgent (C#/.NET 10)
Репозиторий: <https://github.com/Raimbek-pro/SpecAgent>. Авторы Raiymbek (15 коммитов) и Sanzhar (7). Создан 19.11,
документ кейса добавлен 25.11 в 22:29, последний коммит 26.11 в 20:20.

- **Связь с кейсом:** <https://github.com/Raimbek-pro/SpecAgent/blob/main/doc1/README.md?plain=1#L5>.
  Документ кейса лежит в `doc1/prototype/dataset/specs/bcc-card-expenses.md`. Промпт
  `Prompts/critic.logic.md`, строка 10, прямо упоминает `saveLimit`.
- **Своя работа:** [`AuditOrchestrator.cs`](https://github.com/Raimbek-pro/SpecAgent/blob/main/doc1/prototype/src/SpecAgent.Agents/Orchestration/AuditOrchestrator.cs)
  и `Agents/*.cs` (Supervisor, Critic, MetaCritic, Checklist, RuleBasedCritic, PatchLoop).
  Запуск из командной строки: `dotnet run --project src/SpecAgent.Api -- --input ... --output report.md`.
- **Только в README:** оценка качества 0–100, Go/No-Go, автоисправление ТЗ, экспорт в PDF и DOCX, RAG на Qdrant,
  Postgres. Таблица Precision/Recall в
  [`doc1/evaluation-and-demo.md`](https://github.com/Raimbek-pro/SpecAgent/blob/main/doc1/evaluation-and-demo.md?plain=1#L61)
  пустая. Основная модель — платная Kimi K3 (`MOONSHOT_API_KEY`), Gemini используется только для эмбеддингов.

### 2.4. sagudenovam-collab и Nazerke06 — Crumbl_cookies_cream_ai (одна команда)
Репозиторий: <https://github.com/sagudenovam-collab/Crumbl_cookies_cream_ai>. Это форк
<https://github.com/Nazerke06/Crumbl_cookies_cream_ai>. Участницы: Medina Sagudenova и Abdimalik Nazerke; много
коммитов с автором «Claude». В About написано «BBC HACATON».

- **Связь с кейсом:** README.md, строка 5: «создан для BCC-HUB × MNU FinTech Hackathon».
- **Своя работа:** `cream_ai/src/main/java/com/crumble_cookies/cream_ai/analysis/AnalysisOrchestrator.java`
  (Java/Spring Boot, в `analysis/` около 1500 строк), React в `frontend/`.
- **Открыть первым:**
  <https://github.com/sagudenovam-collab/Crumbl_cookies_cream_ai/blob/main/COMPLIANCE_CHECKLIST.md?plain=1#L178>.
  Там сами пишут, что отчёт по документу организаторов не создан. Есть только свой демо-документ
  `docs/demo-requirements.md` («Demo Bank»).
- **Демо:** сборка GitHub Pages в Actions прошла успешно (run #2), но github.io из нашей среды не открылся.
  Судя по названию коммита, там витрина без бэкенда.

### 2.5. omkas07 — requirements-review-agent (Омар, Рамазан, Адильхан)
Репозиторий: <https://github.com/omkas07/requirements-review-agent>. Автор Omar Umirzakov, 4 коммита 26.11 с 11:04 до 12:08.
Ветка `feature/ai-agent-build` влита в `main` через PR #1.

- **Связь с кейсом:** `CONTEXT.md`, строка 21, даёт прямую ссылку на задание; есть копия документа
  `examples/requirements.md`.
- **Своя работа:** [`validator/agents/graph.py`](https://github.com/omkas07/requirements-review-agent/blob/main/validator/agents/graph.py),
  граф LangGraph: парсер, затем три эксперта (developer, tester, security), модератор, clarifier.
  В агентах около 725 строк.
- **Видно в коде:** `TEAM.md`, строка 41: «Граф проверен на фейковом LLM. На реальном Gemini пока не
  запускался». Папка `reports/` пустая, `main.py` нет. Это каркас.
- **Оговорка:** в `TASK.md`, строка 17, участником назван «Адильхан». У исключённого аккаунта Adil-Meiramov
  есть пустой репозиторий `ai-requirements-validator` от 26.11. Связь не доказана, но перед подсчётом её
  стоит проверить. Если это одна команда, новых будет 8. С исключённым q4erty/requirements-review-agent
  совпадает только название: у q4erty Java, у omkas07 Python.

---

## 3. Неподтверждённые кандидаты

| Репозиторий | Что есть | Чего не хватает |
| :--- | :--- | :--- |
| [Vister-scolette/req-validator](https://github.com/Vister-scolette/req-validator) | создан 25.11, внутри только README с заголовком и `.gitignore` | кода и любой связи с кейсом |
| [konopelko95/QC-Agent](https://github.com/konopelko95/QC-Agent) | создан 24.11, описание про контроль требований | содержимого: репозиторий пустой |

## 4. Проверено и отброшено

- `erdpav-cmd/ai-doc-reviewer` — выпускной проект курса Zerocoder, с кейсом не связан.
- `Da0ss/CheckUAgents` — бенчмарк prompt injection (injectbench).
- `zr0548582894-blip/SpecGuard-AI` — проект с README на иврите, к кейсу не относится.
- `wml516518/requirement-review-agent` — по описанию не наш кейс.
- `aluasshka/mnuwork` — лендинг MATERNLEX.
- `foxfordkz-cyber/mnu` — клон запросил авторизацию, недоступен.
- `Aaituov/Agentic-AI-hackathon-web-site` — исходники сайта организаторов, списков команд там нет.

## 5. Что и как искал

1. **Сеть форков задания.** Форков ровно два: azekowka и AdilPython, оба исключены. Переименованных нет (страницы
   `/forks` и `/network/members`). Ветки проверены: у AdilPython только `main`, единственный PR в задание (#1)
   от azekowka. Новых команд из форков ноль.
2. **Редкие строки из задания.**
   - Поиск по коду GitHub: «Февральский счётчик вырос», «Месячный порог расходов по карте», `alerts/saveLimit`,
     `saveLimit cardId`, `bcchubagents.mnu.kz`, `bcchubagents`, «Уведомление о расходах по карте»,
     `AlertsController limit_kzt`, «Практикум без Jira-задачи», «Школа тестирования» AlertsController,
     `demo-42 saveLimit`, «Проверьте сумму» limit_kzt, `limit_kzt card_id enabled`, «MNU FinTech Hackathon»,
     «BCC-HUB x MNU», «BCC-HUB × MNU». Так нашлись Da0ss, Garryflop и Raimbek-pro.
   - `bcchubagents.mnu.kz` в поиске по коду дал 0 совпадений, хотя адрес есть во многих README. Индекс отстаёт
     для свежих репозиториев.
   - Внешний веб-поиск по каждой фразе отдельно, а также с `site:github.com` и `site:gitlab.com`, точных
     совпадений не дал.
   - Поиск по коммитам за даты с 20–25.11 и без фильтра по дате: «BCC-HUB», «MNU hackathon», «29148»,
     «ТЗ агент», «IEEE 830», «проверки требований» и другие. Так нашлись nurkhan0, ERA216, khusrav11 и Aqtanbi.
   - Поиск по названиям и описаниям репозиториев (requirements validator / review / agent / checker, bcc, mnu,
     ТЗ, 29148 и другие, с датой создания и без) дал omkas07. Поиск по PR дал sagudenovam-collab.
3. **От демо к исходникам.** Запросы «BCC-HUB MNU», «агент проверки требований», «requirements validator» с
   github.io, vercel и youtube, и «талаптарды тексеру» на казахском дали только уже известные репозитории и ни
   одного видео. Адреса `bcchubagents.mnu.kz`, `*.github.io` и `*.onrender.com` из облачной среды не
   разрешаются (DNS), поэтому демо ClarifAI и Crumbl не проверены.

## 6. Сроки хакатона

По `TASKS.md` в репозитории сайта организаторов (`Aaituov/Agentic-AI-hackathon-web-site`):

- 20–27.11 — разработка;
- **27.11 до 23:59 — сдача работ** (прототип, видео и презентация);
- 28.11–1.12 — оценка и отбор финалистов;
- 4.12 — финал в MNU, Астана.
