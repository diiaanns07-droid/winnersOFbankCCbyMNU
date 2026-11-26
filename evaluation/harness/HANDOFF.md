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
python -m evaluation.harness --gold tests/p16/fixtures/hand_example/labels.jsonl \
       --pred tests/p16/fixtures/hand_example/predictions_with_duplicate.jsonl --out /tmp/m.json
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
