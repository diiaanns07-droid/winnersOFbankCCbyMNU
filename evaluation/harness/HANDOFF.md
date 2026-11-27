# HANDOFF №16: инструменты измерения и открытые тестовые документы

Основа: `bcc/integration` @ `3e6b569` (контракт v1 из коммита `431f76d`). Ветка платформы:
`claude/sleepy-gates-1zbw4l`. Предпочтительное имя по HANDOFF Max — `bcc/p16-eval-tools`;
переименование или влитие оставлено Max или №18.
Свои файлы: `evaluation/harness/`, `evaluation/dev/`, `tests/p16/`. Чужие файлы не менялись.

## Что сдано

| Что | Где |
| :--- | :--- |
| Счётчик TP/FP/FN, дублей, ложных тревог, пропусков измерения | `python -m evaluation.harness --gold … --pred … --out metrics.json` |
| Адаптер Report (контракт v1) → предсказания | `python -m evaluation.harness adapt`, `evaluation/harness/adapter.py` |
| Адаптер плоских меток → эталон с anchors | `python -m evaluation.harness adapt-labels` |
| Прогон двух режимов с сетевой песочницей для rules_only | `python -m evaluation.harness run --mode rules_only\|rules_plus_llm\|mock` |
| Сравнительная таблица режимов | `python -m evaluation.harness compare` |
| Проверка изоляции закрытого набора по хешам | `fingerprint`, `leakcheck` |
| Открытый корпус: 4 темы, 33 кейса, 41 метка, MD + PDF/DOCX | `evaluation/dev/corpus/`, генератор `python -m evaluation.dev` |
| Протокол и инструкция для GPT Pro | `evaluation/dev/README.md`, `evaluation/harness/README.md` |

## Команды и результаты (выполнено в среде лично, Python 3.13 и 3.11)

```bash
python -m pytest tests/p16 tests/contract          # 92 passed, 1 skipped (тот же набор в venv на 3.11 — зелёный)
python -m evaluation.dev hash --seeds 1             # 8ddcb3f85b7d6f2d2392dddd5ea4ee1744f1a4fb1e35b7a9e807e44b041f7288 (дважды)
python -m evaluation.dev check --corpus evaluation/dev/corpus --with-binaries   # OK: корпус воспроизводится
python -m evaluation.harness --gold evaluation/harness/controls/hand_2tp/labels.jsonl \
       --pred evaluation/harness/controls/hand_2tp/predictions_with_duplicate.jsonl --out /tmp/m.json
# TP=2 FP=1 FN=1 дубли=1; precision=0.6667 = 2/3; recall=0.6667 = 2/3; precision_strict=0.5
```

Пропущен один тест: `test_real_product_rules_only_if_engine_connected`. В `bcc/integration`
`cli.py` пока временная оболочка и не пишет `OUTPUT.json`. Тест включится сам, когда движок
начнёт писать отчёт.

## Проверенные случаи

* Ручной пример: 2 TP, 1 FP, 1 FN → precision 2/3, recall 2/3. Повтор находки → `duplicates=1`,
  precision остаётся 2/3, `precision_strict` = 2/4 (`tests/p16/test_counting.py`).
* Групповая находка с опорами двух дефектов закрывает один, второй — FN с `claimed_by_group`.
  Максимальное паросочетание не теряет TP из-за порядка находок.
* Пустые знаменатели: ноль находок → precision `null`, recall 0; чистый документ без находок →
  все три `null`; чистый документ с находками → precision 0, recall `null`, `clean_false_alarms`.
* Пустой файл `edge.empty` (0 байт): прогон есть, находок 0, предупреждение о пустом входе учтено.
* Три формата одного `case_id`: `independent_cases` не растёт (33 кейса при 45 физических
  представлениях), PDF/DOCX идут в `per_format` и `format_consistency`.
* Пропуск или `failed` прогона — `missing_measurements`, а не ноль находок; в таблице «—» с причиной.
* `rules_only`: ключи удалены из окружения, прокси закрыт, `calls.physical = 0`. Подставной продукт
  с `FAKE_MISBEHAVE` ловится как нарушение. Разные настройки кэша → `compare` возвращает «несопоставимо».
* Оракул (эталон как предсказания) на всём корпусе: P = R = 1, ложных тревог 0; нулевой предсказатель:
  precision `null`, recall 0.
* Отчёт подставного продукта и пример `contracts/examples/minimal_report.json` проходят
  `bcc_review.contracts.validate` и `evidence_errors`; адаптер их читает. Все 15 `FINDING_KINDS`
  отображены в таксономию.
* Закрытая цитата, скопированная в dev-текст, обнаруживается `leakcheck`; отпечаток не содержит текста.

Проверка конвейера на **подставном** продукте (`tests/p16/fake_bcc_review.py`, это не качество
агента): rules_only — TP 10, FP 1, FN 18, 0 вызовов, 0 ложных тревог на 9 чистых;
rules_plus_llm с подставным LLM — TP 11, FP 33, FN 17, 99 вызовов, 8 ложных тревог на 9 чистых; 28 FP на мутантах помечены как фон базы.

## Открытые зависимости и вопросы к контракту (Max)

1. `Finding.kind` не различает подтипы конфликта: event/status/unit/boundary приходят как `conflict`.
   В режиме `--type-match hierarchy` это совпадение уровня `parent`; при `exact` они уходят на разбор.
   Если №06 добавит `Finding.cause.object` или поле подтипа, адаптер начнёт давать точный тип.
2. `run.tokens` в контракте обязателен. Если провайдер не сообщил токены, нужно `null` или отдельная
   пометка, а не 0, иначе таблица не отличит «нет данных» от «ноль».
3. CLI: нет флага каталога кэша. Счётчик передаёт `--no-cache` при `--cache off` и пишет
   `BCC_REVIEW_CACHE*` в окружение только для справки.
4. `.gitattributes`: `*.md text eol=lf` сохраняет байты корпуса на Windows. Если правило изменится,
   добавьте `evaluation/dev/corpus/** -text`, иначе `source_sha256` разойдутся.

## Следующие получатели

* **GPT Pro**: формат меток и манифеста, `fingerprint`/`leakcheck`, запуск на закрытой выборке —
  `evaluation/dev/README.md`, раздел «Инструкция для GPT Pro». Нужны общедоступные примеры их
  разметки, чтобы сверить `issue_type` и `anchor_policy` до прогона.
* **№18**: реальные прогоны с ключом команды:
  `python -m evaluation.harness run --manifest evaluation/dev/corpus/manifest.json --mode rules_only --out out/eval/ro --gold evaluation/dev/corpus/labels.jsonl`,
  затем `--mode rules_plus_llm --provider gemini --out out/eval/llm` и `compare`. Для PDF/DOCX
  добавьте `--format pdf` и `--format docx`.
* **№02/№03**: PDF и DOCX корпуса с `render_check` — регрессионный вход для парсеров.
  В PDF токены 4 из 15 опор идут не подряд из-за переносов в ячейках таблиц.

---

# Второй проход: устойчивость счётчика (0.1.1, `bcc-eval-policy/1`)

Версия для GPT Pro: `python -m evaluation.harness --version` →
`0.1.1 bcc-eval-policy/1 e1a4d18b5be80a466f6762e0975d8e96cc9099f82ee56e3731bbecb0ce4bfe1f`.
Хеш покрывает `evaluation/harness/*.py` и `taxonomy.toml` и пишется в каждый `metrics.json`
(`harness_sha256`, `policy_version`).

## Порядок работы
1. `af8f633`: контрольный граф и ручной ответ (`controls/robustness/expected.json`) до запуска.
   На коде 0.1.0 падали 5 тестов `tests/p16/test_robustness.py`. Счётные метрики во всех 120
   перестановках совпадали с ручным ответом. Но при равных оценках TP получала то Y, то Z
   (по 60/60 перестановок), в `exact` менялся порядок FP, конфликтующие строки run брались по
   порядку, сводка не называла правило типов.
2. Минимальная правка `matching.py`: при равной оценке выбор по `pred_key`, метки по `label_id`,
   отсортированные списки. В `score.py` из разных строк run одного представления берётся худший
   статус. В сводке появились режим, правило типов, число TP уровня parent и хеш версии.
   Тот же вход повторно: 1 результат на 120 перестановках в обоих режимах.

## Ручной ответ / счётчик (`python -m evaluation.harness selfcheck`, полная таблица — `controls/SELFCHECK.md`)

| Контроль | Ручной ответ | Счётчик |
| :--- | :--- | :--- |
| hand_2tp | TP 2, FP 1, FN 1; P 2/3, R 2/3 | 2, 1, 1; 0.6667, 0.6667 |
| hand_2tp + повтор F-2 | дубли 1; P 2/3; P_strict 2/4 | 1; 0.6667; 0.5 |
| граф A/B, hierarchy | TP 2 (A←Y, B←X), FP 2, FN 0, дубль Z, спорная W↔A | совпадает |
| граф A/B, exact | TP 1 (A←Y), FP 3, FN 1, спорные W↔A, X↔A, X↔B | совпадает |
| 120 перестановок находок / 24 перестановки эталона | 1 результат | 1 / 1 |
| повтор формата MD+DOCX | 3 независимых кейса, micro как у MD | 3, равно |
| пустые знаменатели | rb.clean_empty: P, R, F1 = null; rb.clean: R = null | совпадает |

## Открытый прогон через CLI продукта (реальные метрики, не контроль)

`evaluation/dev/results/open_run_rules_only.json`, команда — `evaluation/dev/README.md`.
Тестовая копия: `bcc/integration` @ `6be9e97` + `readers/docx.py` из `bcc/p03-word` @ `d2e8f30`.
Режим `rules_only`, провайдер `none`, 0 физических вызовов, сеть закрыта.

| Показатель | Значение |
| :--- | :--- |
| Независимых кейсов / размечено | 31 / 33 |
| Пропуски измерения | 2: прерванный таймаутом прогон `autopay.event_conflict.insufficient_funds_credit`; `edge.empty` (движок: status=failed) |
| Физических представлений | 32 (MD 31, DOCX 1 того же case_id, что в MD) |
| TP / FP / FN | 0 / 160 / 27; precision 0/160, recall 0/27 |
| Ложные тревоги на чистых | 40 на 8 из 8 измеренных |
| results_sha256 | `ae71bea74dc0fd43c8bb3649ab6b0c84316f9312c889ea8844814ff45e2f8f31` (3 прогона подряд) |
| Код счётчика 0.1.0 на тех же строках | те же micro, per_format, per_case, пропуски |

Реализации из `Report.run.modules`:
* командные: `read_text`, `read_docx` (из p03), `build_inventory`, `review_individual`, `review_set`,
  `reconcile_facts`, `resolve_hint`, `resolve_candidate`, `load_criteria`;
* резервные: `build_questions`, `build_bank_pack`.

Режим `mock` проверен стыковым тестом на одном кейсе: подставной транспорт движка, 6 вызовов,
сеть закрыта.

## Оставшиеся зависимости
* **Max / №07:** находки `omission` цитируют фрагменты по 2 токена («Приложение читает»), и 3 верных
  по типу пропуска метода чтения не засчитываются по политике v1 (порог 3 токена). Нужны цитаты
  до законченного фрагмента, либо решение GPT Pro о политике v2.
* **Max:** пустой файл даёт Report со `status=failed` при коде выхода 0. По политике v1 это пропуск
  измерения. Если пустой вход должен считаться измеренным, нужен `complete` или `partial`
  с предупреждением.
* **№03:** `read_docx` пока не влит в `bcc/integration`, в реестре у него нет резервной реализации.
* **Корпус v1.1 (моя зона):** в `transfer_limit.base` поле `limit` в ответе — string, в запросе —
  integer. Движок это находит (6 FP). Это кандидат `new_real_defect`; исправлю в следующей версии
  корпуса с новым смысловым хешем.

---

# Третий проход: измерение, которое можно повторить (0.1.2, `bcc-eval-policy/1`)

Версия: `python -m evaluation.harness --version` →
`0.1.2 bcc-eval-policy/1 7b54d224c8115c5ec18c71ade817df4e53911ed53324c1e3f131c06bc0dc4660`.
Счётные правила те же, что в 0.1.0. Новое:
* `matrix.jsonl`, `--out-dir`, `run --docs` (манифест по SHA-256);
* короткие каталоги отчётов;
* контроли на открытом корпусе.

## Одна команда для GPT Pro (закрытый корпус, без правок кода)

```bash
python -m evaluation.harness run --gold CLOSED/labels.jsonl --docs CLOSED/docs --mode rules_only --out out/closed
```

Результаты: `metrics.json`, `matrix.jsonl`, `adjudication.jsonl`, `summary.txt`, `manifest.json`, `predictions.jsonl`.
Нужен checkout `bcc/integration` с этим модулем; Max вливает его вместе со срезом.

## Замечания Max по `545ff52` (60/64 на Windows)

* **WinError 206 (3 теста `test_fake_product_reports_are_contract_valid[md|pdf|docx]`).** Каталог отчёта был
  полным `render_id`; вместе с `report.artifacts/stages/…` это 140 символов относительного пути.
  Теперь каталог — 12 hex: худший путь 65 символов от `--out` с артефактами движка.
  Тест `test_report_paths_fit_windows_budget` держит запас ≤ 80.
* **«Тест ждёт чистое дерево» (1).** На Linux не воспроизвёлся. Наиболее вероятный кандидат —
  `test_dev_corpus_has_no_closed_material`: он обходил все файлы на диске. Теперь он смотрит только
  отслеживаемые git файлы (`git ls-files evaluation/dev`) и не падает от локальных неотслеживаемых файлов.
  Если на Windows падает другой тест, нужно его имя.

## Контроли на открытом корпусе: ручной ответ / счётчик

Ручной ответ — `evaluation/dev/controls/expected.json`; таблица — `controls/SELFCHECK.md` (98 строк, 0 расхождений).

```bash
python -m evaluation.harness --gold evaluation/dev/controls/labels.jsonl --pred evaluation/dev/controls/predictions.jsonl --manifest evaluation/dev/controls/manifest.json --out-dir out/controls
```

| Исход | Кейс | Дефект | Находка | Почему |
| :--- | :--- | :--- | :--- | :--- |
| TP | cardblock.combo…(похожая цитата) | #1 | F-07 | обе опоры, exact |
| FP | cardblock.combo… | — | F-08 | только общая опора БК-2: спор с #1 и #2, на разборе |
| FN | cardblock.combo… | #2 | — | кандидаты F-07, F-08 покрывают 1 из 2 опор |
| TP | transfer_limit.event_conflict.cancel_no_restore | #1 | F-02 | parent; равная оценка с F-01, меньший `pred_key` |
| DUP | transfer_limit.event_conflict.cancel_no_restore | #1 | F-01 | оставлена F-02 |
| FP | cashback.base | — | F-01 | ложная тревога на чистом документе |

Итог: TP 2, FP 2, FN 1, дубли 1; P 2/4, R 2/3, F1 4/7. В режиме exact: TP 1, FP 4, FN 2.
Без находок: P = null, R = 0/3, у `cashback.base` P, R, F1 = null.
На 120 перестановках находок в обоих режимах результат один; файл в обратном порядке строк через
CLI даёт ту же матрицу.

## Тот же вход через настоящий движок (реальная выдача, не контроль)

`evaluation/dev/results/controls_rules_only.json`. Тестовая копия `/tmp/s16`: `bcc/integration` @ `2821989`
плюс эта ветка (поэтому `agent_commit` с `-dirty`).
* Режим `rules_only`, провайдер `none`, 0 вызовов, `read_text` — командный.
* TP 0, FP 17, FN 3; 5 ложных тревог на `cashback.base`.
* `matrix.jsonl` совпадает побайтно в двух прогонах: sha256 `a4f41bf5…`.

## Где запускалось

| Где | Python | Результат |
| :--- | :--- | :--- |
| рабочий каталог ветки (без движка) | 3.13 | `tests/p16`: 84 passed, 2 skipped (стык с движком) |
| короткий путь `/tmp/s16` (интеграция + ветка) | 3.13 | 86 passed; `selfcheck` 0 расхождений; сквозной сценарий выше |
| короткий путь `/tmp/s16` | 3.11.18 | 86 passed; `selfcheck` 0 расхождений |
| Windows | — | недоступен в этой среде; защита — тест длины путей |

---

# Четвёртый проход: состав прогонов до подсчёта (`bcc-eval-audit/1`)

Ветка следующего кандидата: `claude/p16-composition-audit` от `a79a47d`. Сборка 2821989 для парного
эксперимента Max не менялась. Политика сопоставления дефектов не менялась: код подсчёта
(`evaluation/harness/*.py`, `taxonomy.toml`) не тронут, `python -m evaluation.harness --version` до и после —
`0.1.2 bcc-eval-policy/1 7b54d224c8115c5ec18c71ade817df4e53911ed53324c1e3f131c06bc0dc4660`.

## Для GPT Pro: выполнить до сравнения F1

```bash
python -m evaluation.harness.audit --gold CLOSED/labels.jsonl \
  --run rules_only=out/closed/ro --run rules_plus_llm=out/closed/llm \
  --expect-agent-commit 2821989 --out out/closed/audit
```

* Работает только с файлами каталогов прогона: продукт и сеть не нужны, ключ не нужен.
  Подходит для каталогов, которые пишет счётчик сборки 2821989 (0.1.0).
* Код 0 — все пары допустимы, можно идти в `compare`. Partial с ответом модели допустим и вынесен в
  раздел «partial — допустимо».
* Код 3 — есть нарушения: `matrix.jsonl` и `composition.md` перечисляют нарушение → case_id → причину.
  Сравнивать F1 на этом составе нельзя. Варианты: перезапустить затронутые кейсы, или (решение GPT Pro)
  считать только по `admissible_case_ids.txt`.
* Код 4 — нарушений нет, но часть пар не доказана: старые отчёты без полей (`unknown`).
* `config_mismatch` с `case_id = *` блокирует все пары; `admissible_case_ids.txt` тогда пуст.
* Симметричный пропуск (кейс не измерен ни в одном прогоне, например пустой файл) — не нарушение:
  кейс выпадает из обоих наборов одинаково и указан в `excluded_symmetric`.

## Доказательство на открытом стенде (выполнено)

`python -m evaluation.dev composition --stand ../stand-2821989 --python ../venv/bin/python --out out/composition`:
* настоящий продукт и раннер 2821989;
* записанный транспорт Anthropic из `tests/p11/fixtures` — синтетические записи, реальных запросов нет;
* по одному нарушению на копию LLM-прогона;
* ручной ответ — `evaluation/dev/composition_controls/expected.json`.

Итог: 8/8 совпали (`evaluation/dev/results/composition_open_stand.json`, сборка с нуля 5 мин 25 с).
Существующий `compare` во всех 8 сценариях ответил «сопоставимо: да».

| Нарушение (введено) | case_id | Аудит | Причина |
| :--- | :--- | :--- | :--- |
| файл изменён под тем же именем | cashback.unit_change.accrued_in_tiyn | `sha_mismatch`, код 3 | отчёт по `89c8f351…`, манифест/строка run — `386739bb…` |
| документ запущен дважды | autopay.two_statuses.range_422 | `repeat`, код 3 | 2 строки run, 2 отчёта, 2 `run_id` |
| на чистом входе нет report | cardblock.base | `missing_report`, код 3 | продукт упал на 529 в `bank` (exit 1); помечено, что precision завысится |
| запрошен rules_plus_llm, отчёт rules_only | transfer_limit.range_boundary.reaching_rejects | `mode_mismatch`, код 3 | 0 вызовов, адаптер не создан без ключа |
| валидный partial после успешного ответа (контроль) | cashback.two_statuses.bad_category_200 | допустимо, код 0, partial | 5 этапов ok, `individual=failed` |
| старый отчёт без полей | autopay.paraphrase.nfr | `unknown`, код 4 | нет `run.mode`, `run.calls.physical`, `run.stages` |
| скрытый partial (контроль) | cardblock.unit_change.blocked_at_utc | допустимо, код 0, partial | отчёт `complete`, 2 ошибки 529 видны только в `stderr.txt` |

## Для Max: что стенд показал о сборке 2821989 (код продукта, не меняю)

Адаптер Anthropic команды бросает `_BootstrapProviderError`: он ищет общий `ProviderError` в
`bcc_review.providers.base` или `bcc_review.errors`, а класс лежит в `bcc_review.contracts`. `asker`
перехватывает только `contracts.ProviderError`. На записанном транспорте:
* 529 на `bank` → процесс падает, `report.json` нет;
* 529 на `cross.pairs` → `status=complete`, этап не записан;
* 529 на `individual` → этап failed с `calls=0`.

В обоих последних случаях `calls.physical` занижен на число неуспешных вызовов, `calls.failed=0`, а
`--max-retries 3` не даёт повторов. Если в живом прогоне Max будут 429/529, это даст пропуски и
скрытые partial; аудит их показывает по `stderr.txt`.

## Тесты (выполнено)

`python -m pytest tests/p16 tests/contract -q` → 136 passed, 2 skipped на Python 3.13 и 3.11. Оба пропуска
прежние: тест реального продукта, которого нет в этом checkout. Новые тесты — `tests/p16/test_composition_audit.py`:
обе раскладки раннера, каждое нарушение отдельно, удалённый отчёт при строке `complete`, симметричный
пропуск, `agent_commit`, нечитаемый отчёт, CLI и коды выхода, независимость от кода подсчёта, сквозной
прогон раннера ветки с подставным продуктом. Мутационная проверка: если отключить детекторы повтора и SHA,
падают ровно их тесты.

## Не выполнялось

* Аудит каталогов настоящего прогона Max: их у меня нет. Отчёты реального API не проверялись.
  Был ли ответ модели живым, по файлам не доказать.
* Windows в этом проходе не проверялся (Linux, Python 3.13 и 3.11).
* Неуспешные вызовы, которых нет ни в `run.stages`, ни в `stderr.txt` (например, если stderr не сохранён),
  аудит не видит.
