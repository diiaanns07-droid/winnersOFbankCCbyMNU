# Исполняемый код mynbaev и SoloHive

## Что происходит при запуске агента

### Вывод

У обеих команд нормальная точка входа читает переданный файл, строит собственный отчёт и записывает полученные замечания. Штатной развилки «узнал официальный файл по имени или SHA — верни старый отчёт» в прослеженных путях я не нашёл. У SoloHive есть сильные подсказки по содержанию исходного кейса. У mynbaev кэш и оценка используют опубликованные данные. [Вызов на входном пути](https://github.com/mynbaev1989-cell/bcc-requirements-agent/blob/73e44d8cc7d18661222f8fe74ccdb7cd8d9f4a67/reqcheck/pipeline.py?plain=1#L81) · [Загрузка и конвейер](https://github.com/khusrav11/solohive/blob/1236c23b38dc305ac35849c82fa1d1a2ca03bcb5/solohive/pipeline.py?plain=1#L41) · [Примеры в промпте](https://github.com/khusrav11/solohive/blob/1236c23b38dc305ac35849c82fa1d1a2ca03bcb5/solohive/prompts/system_consistency.md?plain=1#L9)

### Подтверждено источниками

- **mynbaev, `73e44d8c`.** `python main.py --input <ТЗ> --output <отчёт>` передаёт путь в `run`, затем в `load_document`. План выполняет сегментацию, детерминированные правила, проверки моделью, сверку цитат и консолидацию. Без модели шаги могут переходить к детерминированному исполнению с диагностикой. Кэш учитывает содержание запроса и фактическую модель. Идентификаторы текущих замечаний и вопросы с ответами отдельно проходят через Resolver. На момент проверки main и severity-calibration совпали, stage-d — их более ранний предок. [CLI](https://github.com/mynbaev1989-cell/bcc-requirements-agent/blob/73e44d8cc7d18661222f8fe74ccdb7cd8d9f4a67/reqcheck/cli.py?plain=1#L67) · [Читатель входа](https://github.com/mynbaev1989-cell/bcc-requirements-agent/blob/73e44d8cc7d18661222f8fe74ccdb7cd8d9f4a67/reqcheck/steps.py?plain=1#L53) · [План](https://github.com/mynbaev1989-cell/bcc-requirements-agent/blob/73e44d8cc7d18661222f8fe74ccdb7cd8d9f4a67/reqcheck/steps.py?plain=1#L503) · [Запасной путь](https://github.com/mynbaev1989-cell/bcc-requirements-agent/blob/73e44d8cc7d18661222f8fe74ccdb7cd8d9f4a67/reqcheck/orchestrator.py?plain=1#L116) · [Ключ кэша](https://github.com/mynbaev1989-cell/bcc-requirements-agent/blob/73e44d8cc7d18661222f8fe74ccdb7cd8d9f4a67/reqcheck/llm.py?plain=1#L180) · [Сверка цитат](https://github.com/mynbaev1989-cell/bcc-requirements-agent/blob/73e44d8cc7d18661222f8fe74ccdb7cd8d9f4a67/reqcheck/steps.py?plain=1#L282)
- **SoloHive, `1236c23b`, единственная публичная ветка main.** `python -m solohive --input <ТЗ> --output <отчёт>` загружает документ, объединяет карточки правил и модельных рецензентов, убирает карточку без единой подтверждённой цитаты и пересчитывает вердикт. Если у карточки есть одна подтверждённая и другая неподтверждённая цитата, неподтверждённая остаётся в конце. Поиск цитат допускает нечёткое совпадение с порогом по умолчанию 87. При обычном запуске без ключа настройка завершает работу ошибкой. Офлайн включается отдельным `--offline`. Тестовый `mock` — отдельный провайдер. [CLI](https://github.com/khusrav11/solohive/blob/1236c23b38dc305ac35849c82fa1d1a2ca03bcb5/solohive/cli.py?plain=1#L62) · [Сборка](https://github.com/khusrav11/solohive/blob/1236c23b38dc305ac35849c82fa1d1a2ca03bcb5/solohive/pipeline.py?plain=1#L97) · [Проверка доказательств](https://github.com/khusrav11/solohive/blob/1236c23b38dc305ac35849c82fa1d1a2ca03bcb5/solohive/pipeline.py?plain=1#L151) · [Поиск цитаты](https://github.com/khusrav11/solohive/blob/1236c23b38dc305ac35849c82fa1d1a2ca03bcb5/solohive/document.py?plain=1#L201) · [Выбор провайдера](https://github.com/khusrav11/solohive/blob/1236c23b38dc305ac35849c82fa1d1a2ca03bcb5/solohive/config.py?plain=1#L157) · [Офлайн и тестовый провайдер](https://github.com/khusrav11/solohive/blob/1236c23b38dc305ac35849c82fa1d1a2ca03bcb5/solohive/llm/__init__.py?plain=1#L19)
- У SoloHive правило сравнивает обещание чтения с описанием методов. Модель отдельно получает примеры возврата к исходной покупке, смены порога, признака включения уведомлений, границы месяца и различия авторизации и клиринга. Формулировки перекрываются с задачей организаторов. Это основание снизить уверенность в переносимости известного результата на другие банковские продукты. [Правило чтения](https://github.com/khusrav11/solohive/blob/1236c23b38dc305ac35849c82fa1d1a2ca03bcb5/solohive/linters.py?plain=1#L768) · [Доменная подсказка](https://github.com/khusrav11/solohive/blob/1236c23b38dc305ac35849c82fa1d1a2ca03bcb5/solohive/prompts/system.md?plain=1#L22) · [Подсказки к полноте](https://github.com/khusrav11/solohive/blob/1236c23b38dc305ac35849c82fa1d1a2ca03bcb5/solohive/prompts/system_completeness.md?plain=1#L7)

### Оценка

Наличие демонстрационных JSON или тестового клиента в дереве само по себе ничего не говорит о штатном пути. Два свежих документа ниже дали новые хеши источника и собственные цитаты в CLI обеих команд. [Ввод mynbaev](https://github.com/mynbaev1989-cell/bcc-requirements-agent/blob/73e44d8cc7d18661222f8fe74ccdb7cd8d9f4a67/reqcheck/steps.py?plain=1#L53) · [Ввод SoloHive](https://github.com/khusrav11/solohive/blob/1236c23b38dc305ac35849c82fa1d1a2ca03bcb5/solohive/pipeline.py?plain=1#L49)

### Чего не хватает

Здесь не проводился новый платный вызов моделей конкурентов. Отключение модели меняет конвейер и полноту, а у SoloHive также исключает модельного критика. [Поведение без LLM](https://github.com/mynbaev1989-cell/bcc-requirements-agent/blob/73e44d8cc7d18661222f8fe74ccdb7cd8d9f4a67/reqcheck/orchestrator.py?plain=1#L118) · [Модельный критик](https://github.com/khusrav11/solohive/blob/1236c23b38dc305ac35849c82fa1d1a2ca03bcb5/solohive/pipeline.py?plain=1#L105)

## Что воспроизводят цифры соперников

### Вывод

**mynbaev** исполняет даже полный семидокументный контроль на опубликованном кэше. **SoloHive** воспроизводит свои 39/40 на MD и 38/40 на PDF. В обоих проектах точная арифметика сочетается с широкой эвристикой сопоставления. Ни одна из этих цифр сама по себе не измеряет долю правильных карточек по независимой смысловой оценке. [Сопоставление mynbaev](https://github.com/mynbaev1989-cell/bcc-requirements-agent/blob/73e44d8cc7d18661222f8fe74ccdb7cd8d9f4a67/tools/eval_score.py?plain=1#L131) · [Сопоставление SoloHive](https://github.com/khusrav11/solohive/blob/1236c23b38dc305ac35849c82fa1d1a2ca03bcb5/solohive/evaluate.py?plain=1#L61)

### Подтверждено источниками

- В копии **mynbaev** выполнил `python tools/ablation.py --cache eval/llm_cache --gate`. Получил **100/104**, **85,8% precision** как среднее по документам, 52% точных уровней, 1 формально ложный critical (0 после дополнительной авторской разметки), промахов кэша 0. Счётчик для recall и precision проверяет расстояние в **±1 строку** между любыми цитатами разметки и любой карточки. Объяснение, предмет замечания и тип не обязательны для такого попадания. Проверил реализацию на своём ТЗ: добавил одно заведомо постороннее контрольное замечание к строке 9, о дате активации гарантии. Реальный агент нашёл только minor про идентификаторы и версию. Счётчик всё равно показал 1/1, а у контрольной метки за пределами текста — 0/1. [Штатная команда и gate](https://github.com/mynbaev1989-cell/bcc-requirements-agent/blob/73e44d8cc7d18661222f8fe74ccdb7cd8d9f4a67/tools/ablation.py?plain=1#L206) · [Агрегация по документам](https://github.com/mynbaev1989-cell/bcc-requirements-agent/blob/73e44d8cc7d18661222f8fe74ccdb7cd8d9f4a67/tools/ablation.py?plain=1#L147) · [Условие совпадения](https://github.com/mynbaev1989-cell/bcc-requirements-agent/blob/73e44d8cc7d18661222f8fe74ccdb7cd8d9f4a67/tools/eval_score.py?plain=1#L140) · [Настройка на тех же семи документах](https://github.com/mynbaev1989-cell/bcc-requirements-agent/blob/73e44d8cc7d18661222f8fe74ccdb7cd8d9f4a67/eval/README.md?plain=1#L112)
- В копии **mynbaev** `python tools/score_answers.py reports/independent_answers/blind2` дал **25/30** (18/18 конкретных, 6/6 уклончивых, 1/6 противоречивых). Для `…/blind2/after_rules` — **28/30**, включая 4/6 противоречивых. Пара обнаруженных коммитов подтверждает последовательность: публичные ответы с ключами появились в 16:08, отчёты в 16:15. Внутри инструмента положительное решение засчитано, если в строке итога для нужного Q-ID хотя бы одна находка закрыта. Отдельной проверки, что выбранная норма точно записана в конечную редакцию, у этой метрики нет. [Что засчитывается](https://github.com/mynbaev1989-cell/bcc-requirements-agent/blob/73e44d8cc7d18661222f8fe74ccdb7cd8d9f4a67/tools/score_answers.py?plain=1#L24) · [Ответы до прогона](https://github.com/mynbaev1989-cell/bcc-requirements-agent/commit/cbda1d383fa0583790a3a63f720e402895aeb704) · [Отчёты после](https://github.com/mynbaev1989-cell/bcc-requirements-agent/commit/71d4a094e82792d864404717a1afc0bc79cbc210) · [Команда раскрывает доработку](https://github.com/mynbaev1989-cell/bcc-requirements-agent/blob/73e44d8cc7d18661222f8fe74ccdb7cd8d9f4a67/reports/independent_answers/README.md?plain=1#L85)
- **SoloHive.** `python -m solohive.evaluate reports/requirements_report.json` воспроизвёл **39/40 на 59 активных карточках**. `python -m solohive.evaluate reports/report.json` — **38/40 на 55**. Эталон команды появился 25 ноября и был известен до публикации MD-прогона 27 ноября. Код засчитывает пункт, когда у действующей карточки есть одна общая строка цитаты и одно ключевое слово в названии или объяснении. Уровень, корректность утверждения и одно-однозначность связывания не проверяются. Для 39 попаданий выбраны 34 различные карточки. Например, G29 о терминах «держатель / владелец» программа засчитала по D‑14 о статусе карты, а G01 про повторный push после смены порога — по D‑18 о возврате. Сама команда действительно нашла G01 отдельной D‑36. [Формула](https://github.com/khusrav11/solohive/blob/1236c23b38dc305ac35849c82fa1d1a2ca03bcb5/solohive/evaluate.py?plain=1#L67) · [История эталона](https://github.com/khusrav11/solohive/commit/96d61661730eb598aacc4926e3902097eb9af301) · [Конкурсный MD-прогон](https://github.com/khusrav11/solohive/commit/b1c6930cef0f6125c196ffe791eb4a8ab7f07972) · [Реальная D‑36](https://github.com/khusrav11/solohive/blob/1236c23b38dc305ac35849c82fa1d1a2ca03bcb5/reports/requirements_report.md?plain=1#L1600)
- **Холодные вызовы и воспроизведение.** У mynbaev у конкурсного отчёта версия агента `54fa2d2`, 0 новых обращений, 13/13 из кэша, 0,85 с. У слепых отчётов о решениях владельца для трёх документов по одному новому обращению и 12, 13, 12 кэшированных, у пересобранных после настройки 0 новых и 13, 14, 13 из кэша. В коде попадание возвращается до счётчика нового обращения и до `generate_content`. У SoloHive в конкурсном Markdown-JSON 13 записей успешных запросов с `cached=false`, фактической моделью google/gemini-3.8-flash и общим временем 281,2 с. Клиент проверяет кэш отдельно от сетевого вызова через OpenRouter. Это даёт сильнее свидетельство холодной сборки SoloHive, но файлы создал сам участник. В предъявленных артефактах нет верифицируемой квитанции провайдера, которая независимо удостоверяла бы каждое историческое обращение, его автора или отсутствие последующей правки файлов. [Паспорт mynbaev](https://github.com/mynbaev1989-cell/bcc-requirements-agent/blob/73e44d8cc7d18661222f8fe74ccdb7cd8d9f4a67/reports/requirements_report.md?plain=1#L34) · [Клиент mynbaev](https://github.com/mynbaev1989-cell/bcc-requirements-agent/blob/73e44d8cc7d18661222f8fe74ccdb7cd8d9f4a67/reqcheck/llm.py?plain=1#L210) · [Учёт токенов первого слепого документа](https://github.com/mynbaev1989-cell/bcc-requirements-agent/blob/73e44d8cc7d18661222f8fe74ccdb7cd8d9f4a67/reports/independent_answers/blind2/credit_card_application.json) · [Паспорт SoloHive](https://github.com/khusrav11/solohive/blob/1236c23b38dc305ac35849c82fa1d1a2ca03bcb5/reports/requirements_report.md?plain=1#L50) · [Первичные события вызовов](https://github.com/khusrav11/solohive/blob/1236c23b38dc305ac35849c82fa1d1a2ca03bcb5/reports/requirements_report.json) · [Проверка кэша](https://github.com/khusrav11/solohive/blob/1236c23b38dc305ac35849c82fa1d1a2ca03bcb5/solohive/llm/base.py?plain=1#L201) · [Обращение к API](https://github.com/khusrav11/solohive/blob/1236c23b38dc305ac35849c82fa1d1a2ca03bcb5/solohive/llm/openai_compat.py?plain=1#L48)
- **SoloHive после ответов.** Модель получает весь документ и ответы. Затем код принимает допустимые `fid` из её решений со статусом `resolved` и вычитает их из старого списка. Вердикт считается по остатку. Автоматическое второе чтение исправленного ТЗ в этом пути отсутствует. Файл `report_revised.md` содержит 23 изменённых требования в формате «было/стало», пять добавленных и новые критерии. Это журнал правок, позволяющий владельцу видеть последствия. В полном исправленном документе пришлось бы сохранить остальные исходные разделы. [Передача документа модели](https://github.com/khusrav11/solohive/blob/1236c23b38dc305ac35849c82fa1d1a2ca03bcb5/solohive/agents/reviser.py?plain=1#L106) · [Вычитание решённых карточек](https://github.com/khusrav11/solohive/blob/1236c23b38dc305ac35849c82fa1d1a2ca03bcb5/solohive/agents/reviser.py?plain=1#L141) · [Формирование редакции](https://github.com/khusrav11/solohive/blob/1236c23b38dc305ac35849c82fa1d1a2ca03bcb5/solohive/agents/reviser.py?plain=1#L158) · [Файл демонстрации](https://github.com/khusrav11/solohive/blob/1236c23b38dc305ac35849c82fa1d1a2ca03bcb5/reports/report_revised.md?plain=1#L7)

### Оценка

У mynbaev более убедителен сам протокол эксперимента с ответами и сохранение неудачных опытов. У SoloHive готовность «после» слабее, чем кажется по первому экрану. Команда показывает фактическое решение рецензента на исходном ТЗ. Повторное чтение полной редакции, как в сценарии BCC, даёт более строгую проверку. [Ошибки независимого набора](https://github.com/mynbaev1989-cell/bcc-requirements-agent/blob/73e44d8cc7d18661222f8fe74ccdb7cd8d9f4a67/reports/independent_answers/README.md?plain=1#L64) · [Вердикт после уточнения](https://github.com/khusrav11/solohive/blob/1236c23b38dc305ac35849c82fa1d1a2ca03bcb5/solohive/agents/reviser.py?plain=1#L141) · [Пример перечитывания BCC](https://github.com/diiaanns07-droid/winnersOFbankCCbyMNU/blob/d629aa0a/reports/demo_answers/README.md?plain=1#L28)

### Чего не хватает

Для сравнительного уровня точности у BCC и этих двух команд нужен один незнакомый смешанный корпус, одни условия и рецензирование по смыслу. Бизнес-защита и материалы интерфейса по-прежнему оцениваются отдельно. [Критерии организаторов](https://bcchubagents.mnu.kz/)

## Что показали новые входы без LLM

### Вывод

В паре одинаковых ТЗ для BCC, mynbaev и SoloHive поменяли только верхнюю границу перевода в методе API с 12 700 на 24 500. У mynbaev и SoloHive штатные автономные пути пропустили конфликт. Отдельно у SoloHive воспроизведён ложный запрет разработки на GET для чтения расписания переговорных комнат. [Автономный режим mynbaev](https://github.com/mynbaev1989-cell/bcc-requirements-agent/blob/73e44d8cc7d18661222f8fe74ccdb7cd8d9f4a67/reqcheck/cli.py?plain=1#L28) · [Автономный режим SoloHive](https://github.com/khusrav11/solohive/blob/1236c23b38dc305ac35849c82fa1d1a2ca03bcb5/solohive/cli.py?plain=1#L44) · [Причина ложного critical](https://github.com/khusrav11/solohive/blob/1236c23b38dc305ac35849c82fa1d1a2ca03bcb5/solohive/linters.py?plain=1#L216)

### Подтверждено источниками

| Проверка | mynbaev | SoloHive |
| --- | --- | --- |
| Согласованный лимит 12 700, хеш `1afedacecd47…` | 6 требований, 2 minor, условно из-за неполной смысловой проверки | 6 требований, 2 minor, оба старта разрешены |
| Несовместимый лимит 24 500, хеш `d296ea13471d…` | Те же 2 minor и вердикт | Те же 2 minor и вердикты |
| Read-only GET со словом «записи» | Отдельный для SoloHive тест правила | Ложный critical, разработка запрещена, тестирование с условиями |
| Та же операция со словом «список» | — | Critical исчез, оба старта разрешены |

Исполнил опубликованные CLI в изолированной временной директории, без ключей, кэша и внешней сети. Для mynbaev команда `python -m reqcheck --offline --no-cache --formats md,json --input <вход> --output <отчёт.md>`. Для SoloHive — `python -m solohive --offline --no-cache --quiet --input <вход> --output <отчёт.md>`. Python 3.12, исходники на закреплённых SHA. Исходник PDF и доступ к моделям для этого теста не требуются. [Параметры mynbaev](https://github.com/mynbaev1989-cell/bcc-requirements-agent/blob/73e44d8cc7d18661222f8fe74ccdb7cd8d9f4a67/reqcheck/cli.py?plain=1#L22) · [Параметры SoloHive](https://github.com/khusrav11/solohive/blob/1236c23b38dc305ac35849c82fa1d1a2ca03bcb5/solohive/cli.py?plain=1#L40)

Для независимого повтора нужны чистые копии mynbaev и SoloHive на указанных выше SHA. Команды ниже выполняются в PowerShell с Python проектов и опубликованными зависимостями. Укажите абсолютные пути к каталогам с этой заметкой и клонами. Внутри автономных команд ключи не нужны.

```powershell
$audit = 'C:\audit\notes'
$mynRepo = 'C:\audit\bcc-requirements-agent'
$soloRepo = 'C:\audit\solohive'
$runDir = 'C:\audit\new-probes'
$replay = Join-Path $audit 'code-leaders-replay.py'
python $replay prepare $runDir
Push-Location $mynRepo
foreach ($doc in 'aligned', 'clash') {
  python -m reqcheck --offline --no-cache --formats md,json --input "$runDir/$doc.md" --output "$runDir/myn-$doc.md"
}
Pop-Location
Push-Location $soloRepo
foreach ($doc in 'aligned', 'clash', 'read-records', 'read-list') {
  python -m solohive --offline --no-cache --quiet --input "$runDir/$doc.md" --output "$runDir/solo-$doc.md"
}
Pop-Location
python $replay check $runDir
```

В проверенной копии `check` сверил все шесть отчётов по хешам входов, вердиктам, количеству модельных обращений, уровням, именам карточек и строкам цитат. [Набор входов и результаты](code-leaders-evidence.json) · [Скрипт подготовки и проверки](code-leaders-replay.py)

Для воспроизведения ложного critical SoloHive достаточно девяти строк.

```md
# Календарь комнат

## REST API
| Параметр | Значение |
| --- | --- |
| HTTP method | GET |
| URL | /rooms/availability |
| Description | Чтение расписания комнат |
1. Вернуть записи на запрошенную дату.
```

Замените только «записи» на «список». У чтения с существительным «записи» код находит `запис\w*` в логике метода и маркирует это как изменение состояния. Хеши двух входов `0955f8c58612…` и `900e9f01264d…`. Результат повторился на более длинном документе. [Глаголы записи и замен](https://github.com/khusrav11/solohive/blob/1236c23b38dc305ac35849c82fa1d1a2ca03bcb5/solohive/linters.py?plain=1#L216) · [Выбор доказательства и critical](https://github.com/khusrav11/solohive/blob/1236c23b38dc305ac35849c82fa1d1a2ca03bcb5/solohive/linters.py?plain=1#L230) · [Влияние на вердикт](https://github.com/khusrav11/solohive/blob/1236c23b38dc305ac35849c82fa1d1a2ca03bcb5/solohive/pipeline.py?plain=1#L188)

### Оценка

По совокупности проверок кода я ставлю **1. mynbaev, 2. BCC Review, 3. SoloHive** среди этой тройки. Первому отдаю воспроизводимую работу с уточнениями, BCC — повторное чтение всей редакции и точность на официальном ТЗ, SoloHive — понятность демонстрации. До разбора исходников я ставил SoloHive на второе место. Презентация и защита могут изменить порядок. Доказать универсальное лидерство какого-либо продукта на этих двух документах невозможно. [Условия снятия блокировки](https://github.com/khusrav11/solohive/blob/1236c23b38dc305ac35849c82fa1d1a2ca03bcb5/solohive/agents/reviser.py?plain=1#L141)

### Чего не хватает

LLM-критик SoloHive в сетевом режиме может снять ошибочную карточку «записи». Поведение этого конкретного примера с платной моделью не проверялось. У mynbaev не измеряли поведение живой модели на новых входах. [Место критика в штатном пайплайне](https://github.com/khusrav11/solohive/blob/1236c23b38dc305ac35849c82fa1d1a2ca03bcb5/solohive/pipeline.py?plain=1#L105) · [Подключение модели](https://github.com/mynbaev1989-cell/bcc-requirements-agent/blob/73e44d8cc7d18661222f8fe74ccdb7cd8d9f4a67/reqcheck/steps.py?plain=1#L112)
