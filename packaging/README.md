# Проверка выпуска №18

Откройте [готовый отчёт](../release/reports/offline/requirements.md), [исходный документ](../release/input/requirements.md) и [установку для Windows и Linux](../README.md). Коммит агента `70d26174e7f448eb2f061f6268b2c566baacf7c1` записан в отчёте. Комплект готовых отчётов взят из `099dd32ddbc3525c8e09dfcf79514eb32f80921a`. SHA-256 официального Markdown — `e7dae55e5453a250d93e335f5ff9c7f775f4457ccddd333f4a67e47b20d74381`. [Квитанция с версиями пакетов, размерами и хешами](clean-run.json)

## Чистая установка и повтор 27 ноября 2026 года

| Среда | Первый / повторный запуск | Результат на официальном Markdown |
| --- | --- | --- |
| Windows 11, сборка 26300, CPython 3.13.6, новый клон и venv | 2,07 / 1,60 с | 27 замечаний, `verify` подтвердил 594 опоры |
| Debian 12 в чистом Linux-контейнере на WSL2, CPython 3.12.16, новый клон и venv | 1,63 / 0,97 с | 27 замечаний, 594 опоры |
| Образ приложения, Docker Engine 29.1.5, сеть отключена | один запуск | 27 замечаний, 594 опоры |

В первом окружении установка `pip install -e .` заняла 13,50 с. Debian получил код из локальной копии проверенного Git-клона. Время в таблице относится к CLI. Оба повтора использовали `--offline-lint --no-cache`. В каждом паспорте указаны `rules_only`, `partial`, ноль вызовов и пустое значение модели. В отчёте 53 требования, 26 подтверждённых замечаний, одно замечание на ручную проверку, 17 вопросов и 14 строк чек-листа. Сверка восьми разделов свежего отчёта с опубликованным дала полное совпадение. Команда `verify` вернула 0 с пятью предупреждениями. Две опоры выходят за границы своего требования (строки 110 и 188), цитата `enabled` повторяется в двух блоках (строки 144 и 157), прогон имеет статус `partial`. Команда проверяет привязки цитат и паспорт. Точность смыслового анализа модели здесь не измерялась.

Минимальное окружение Windows использовало 425 790 байт готовых wheel-файлов базовых зависимостей. Дополнительные wheel-файлы для `.[all,dev]` составили 137 737 750 байт. Это размеры опубликованных файлов PyPI без накладных расходов сети и временных зависимостей сборки. Проверены `anthropic 2.14.0`, `google-genai 3.6.1`, `PyMuPDF 2.2`, `fonttools 4.69.1`, `python-docx 1.2.0` и `pytest 9.2.0`. В квитанции есть версии, размеры и SHA-256 каждого выбранного wheel.

## Показ жюри

Из корня клона выполните команды установки из корневого README. Далее `python` обозначает интерпретатор созданного venv. Чтобы получить локальный интерактивный отчёт и PDF с пометками, выполните следующие команды.

```sh
python -m bcc_review release/input/requirements.md out/requirements.md --offline-lint --no-cache --export html
python -m pip install -e ".[pdf]"
python -m bcc_review release/input/requirements.pdf out/pdf/report.md --offline-lint --no-cache --export pdf
python -m bcc_review verify out/pdf/report.json release/input/requirements.pdf
```

В `out/pdf/report.annotated.pdf` проверены 6 страниц и 104 аннотации. PDF выпущен командой из официального Markdown. В `out/requirements.html` найдите строку чек-листа `CHK-06`, связанное замечание `F-017` и вопрос `Q-01`. Для репетиции введите `B` в ответ на этот вопрос, остальные поля оставьте пустыми. Нажмите «Выгрузить ответы (.md)» и сохраните файл как `out/answers.md`. Выбор иллюстрирует решение аналитика на стыке двух месяцев. Принятую банком политику определяет владелец ТЗ.

```sh
python -m bcc_review release/input/requirements.md out/decision/r2.md --answers out/answers.md --offline-lint --no-cache --run-id p18-demo
python -m bcc_review verify out/decision/r2.json out/decision/requirements.rev-p18-demo.md
```

При репетиции движок принял одно решение, записал одну правку и создал редакцию с SHA-256 `0be2b3d50e25f865de2893193f79bad0bdaabe16894897d131e0a0385bf9e574`. `verify` принял именно эту редакцию. Исходное ТЗ сохранило опубликованный хеш. [Вопросы и решения в готовом отчёте](../release/reports/offline/requirements.md)

## Docker и CI

В отдельном каталоге получите ветку упаковки. Этот пример использует Linux или WSL. Сеть нужна при первой сборке. Образ включает SDK Claude и Gemini, модули PDF и Word. В контекст сборки входят описание пакета и код из `src/bcc_review`.

```sh
git clone --branch bcc/p18-release --single-branch https://github.com/diiaanns07-droid/winnersOFbankCCbyMNU.git bcc-package
cd bcc-package
code=70d26174e7f448eb2f061f6268b2c566baacf7c1
git diff --exit-code "$code" HEAD -- src pyproject.toml &&
  docker build --build-arg BCC_AGENT_COMMIT="$code" -t bcc-review:p18 .
mkdir -p out
docker run --rm --network none -v "$PWD/release/input:/input:ro" -v "$PWD/out:/out" bcc-review:p18 /input/requirements.md /out/requirements.md --offline-lint --no-cache
docker run --rm --network none -v "$PWD/release/input:/input:ro" -v "$PWD/out:/out:ro" bcc-review:p18 verify /out/requirements.json /input/requirements.md
```

Результат доступен на хосте в `out/`. Размер проверенного образа по `docker image inspect` — 218 912 072 байта. Для официального прогона Max задаёт `ANTHROPIC_API_KEY` в своей оболочке и передаёт переменную в контейнер по имени. Ниже команда для среды команды.

```sh
docker run --rm -e ANTHROPIC_API_KEY -v "$PWD/release/input:/input:ro" -v "$PWD/out:/out" bcc-review:p18 /input/requirements.md /out/live/requirements.md --provider anthropic --no-cache --export html,jira --max-calls 40 --max-seconds 1800
```

Для запуска тестов на ветке упаковки выполните команды ниже в venv. Те же тесты используются в GitHub Actions. Три вызова pytest сохраняют штатные локальные настройки каждого набора. [Тесты упаковки](../tests/p18/test_release.py) · [Запуски CI](https://github.com/diiaanns07-droid/winnersOFbankCCbyMNU/actions?query=branch%3Abcc%2Fp18-release)

```sh
python -m pip install -e ".[anthropic,pdf]" pytest
python -m pytest -q tests/p18
python -m pytest -q tests/p11/test_anthropic_errors.py tests/p11/test_asker_path.py
python -m pytest -q tests/p08/test_engine_answers.py::test_cli_answers_changes_only_the_agreed_phrase
```

Если в Windows pytest получает `WinError 5` при создании `pytest-of-…` в общем временном каталоге, выделите новый каталог для этого запуска и повторите команды тестов в той же оболочке. На машине проверки использован отдельный временный каталог.

```powershell
$runTemp = Join-Path ([System.IO.Path]::GetTempPath()) ([guid]::NewGuid().ToString())
$env:PYTEST_DEBUG_TEMPROOT = (New-Item -ItemType Directory -Path $runTemp).FullName
```

На Windows и в Linux прошли по 8 тестов упаковки, 28 тестов адаптера и 1 тест решения аналитика. В локальном `mock` повтор на той же фикстуре дал 6 попаданий в кэш и 0 новых вызовов после 6 вызовов подставного транспорта. При 429 транспорт выдерживает `Retry-After`, при 503 возвращает повторяемую ошибку после одного запроса адаптера. Наборы также проверяют тайм-аут, отсутствие ключа, ответ с обрывом из-за лимита токенов, прерывание атомарной записи JSON, путь с пробелами и кириллицей, пустой документ и PDF без текстового слоя.

## Если проверка прервалась

Проверьте `run.status_reasons` и `run.incomplete_stages` в JSON. При расхождении SHA возьмите исходник этой версии. Для отчёта после `--answers` используйте новую редакцию из каталога результата. Пустой файл или скан без текста дают статус `failed`. Для скана подготовьте текстовый слой и запустите проверку в новом каталоге. Предыдущий принятый JSON сохраняется при прерывании его атомарной замены.

Коды штатного CLI в этой сборке — `0` при успешном выполнении команды, `1` при ошибке выполнения, `2` при ошибке аргументов, `3` при срабатывании `--fail-on blocker`, `4` при расхождении в `verify`, `5` при срабатывании `--fail-on partial`. Код 0 для офлайн-прогона совместим со статусом `partial`. Для проверки полноты используйте паспорт. [Контракт кодов выхода](../src/bcc_review/contracts.py)
