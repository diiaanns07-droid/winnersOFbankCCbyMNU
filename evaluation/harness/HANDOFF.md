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
