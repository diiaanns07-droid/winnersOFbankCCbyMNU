# Открытый dev-корпус bcc-eval (`evaluation/dev`)

Публичный учебный корпус для настройки и самопроверки продукта. Закрытый корпус,
независимая разметка и выводы для защиты принадлежат GPT Pro и сюда не попадают.

## Состав (`corpus/`, генератор 1.0.0, seed 1)

33 кейса, 41 строка эталона, 28 дефектов `present`. Смысловой хеш корпуса:
`8ddcb3f85b7d6f2d2392dddd5ea4ee1744f1a4fb1e35b7a9e807e44b041f7288`.

* **4 независимые темы** в банковском шаблоне (часть A — бизнес-требования, часть B — REST API):
  `cashback` (кэшбэк в категории), `autopay` (автопополнение связи), `cardblock` (блокировка карты),
  `transfer_limit` (суточный лимит переводов). Тексты написаны с нуля и не повторяют кейс организаторов.
* **9 чистых контролей**: 4 базы (`*.base`), 4 чистых перефраза (`*.paraphrase.*`, место перефраза
  размечено как `absent`) и пустой файл `edge.empty` (0 байт).
* **20 мутантов** с одним дефектом: по каждому оператору в каждой теме.
* **4 комбинации** с двумя дефектами (`*.combo.*`): проверяют правило «одна находка — один дефект».

| Оператор | issue_type | Что меняется |
| :--- | :--- | :--- |
| `event_conflict` | `event_conflict` | добавлено правило: то же событие получает несовместимый исход |
| `unit_change` | `unit_mismatch` | единица в одном месте заменена (тенге/тиыны, сутки/час, секунды/минуты, UTC+5/UTC) |
| `range_boundary` | `boundary_conflict` | граница диапазона включена в одном месте и исключена в другом |
| `two_statuses` | `status_conflict` | одному входу назначен второй код ответа |
| `drop_promised` | `missing_element` | удалён метод, поле, статус или данные, обещанные в другом месте |
| `paraphrase` | — | чистый перефраз без смены смысла (контроль ложных тревог) |

Каждый кейс лежит в `corpus/cases/<case_id>/`:
* `source.md` — исходный текст (UTF-8, LF), его SHA-256 — `source_sha256` эталона;
* `mutation.json` — база (`base_case_id`, `base_source_sha256`), преобразование (`transformation`:
  строка базы, удалённый и вставленный текст), ожидаемый эффект, unified diff, метки с опорами;
* `source.pdf`, `source.docx` — только для баз, комбинаций и пустого файла.

`corpus/manifest.json` связывает `case_id` с представлениями (`render_id = <case_id>@md|pdf|docx`,
SHA-256 файла). После рендера текст извлекается обратно (pdfplumber, python-docx):
* `render_check.tokens_present` — все токены опор есть в файле: MD 57/57, PDF 15/15, DOCX 15/15.
* `exact_sequence` — токены идут подряд: MD 57/57, DOCX 15/15, PDF 11/15. В PDF порядок нарушают
  переносы в ячейках таблиц; это и проверяет парсер №02.

PDF и DOCX одного `case_id` — физические представления. Они проверяют парсер и экспорт
и не увеличивают число независимых кейсов: счётчик учитывает их в `per_format`.

## Воспроизводимость

```bash
python -m evaluation.dev hash --seeds 1                 # 8ddcb3f8… — тот же хеш при той же версии
python -m evaluation.dev check --corpus evaluation/dev/corpus [--with-binaries]
python -m evaluation.dev generate --out /tmp/c --seeds 1,2,3 --all-variants
```

* Выбор варианта: `sha256(версия|seed|тема|оператор) mod число_вариантов`, без генератора случайных
  чисел. Тот же seed и та же версия дают совпадающие смысловые хеши (`semantic_sha256` кейса и корпуса).
* `case_id` зависит только от содержания (тема, оператор, вариант). Разные seed, выбравшие один
  вариант, дают один кейс, а не два «независимых».
* Опоры проверяются генератором: токены каждой опоры встречаются в тексте ровно один раз; цитата
  одной стороны конфликта не покрывает другую. Локатор `md:L<строка>` вычисляет программа.
* PDF собран с `invariant=1`, ZIP внутри DOCX — с фиксированным временем. На одной машине байты
  совпадают (`check --with-binaries`). На другой машине байты PDF могут отличаться из-за версии
  шрифта DejaVu или reportlab. Смысловой хеш от этого не зависит, а закоммиченные файлы — эталон.

## Воспроизводимый прогон через CLI продукта

```bash
git worktree add --detach ../stand origin/bcc/integration
git -C ../stand checkout origin/bcc/p03-word -- src/bcc_review/readers/docx.py   # пока №03 не влит
python -m evaluation.dev open-run --product-src ../stand/src --out out/open_run
```

Прогон идёт в режиме `rules_only` с `--no-cache`, сеть закрыта песочницей. Состав:
* MD всех кейсов, кроме `autopay.event_conflict.insufficient_funds_credit`;
* DOCX кейса `cashback.combo.event_conflict-category_effective_now+range_boundary-cap_strict`;
* отдельный прогон `autopay.event_conflict.insufficient_funds_credit`, прерванный таймаутом счётчика 0.001 с.
  Он технически не завершён (`failed`) и виден как пропуск измерения.

`summary.json` содержит:
* число независимых кейсов, пропуски измерения, режим;
* физические вызовы, транспорт, реализации модулей;
* `results_sha256` — хеш смысловых итогов без времени и путей.

Зафиксированный результат лежит в `results/`.

## Контрольные случаи на открытом корпусе (`controls/`)

Ручной ответ — `controls/expected.json`, записан до запуска CLI.

| Случай | Документ | Находки | Ручной ответ |
| :--- | :--- | :--- | :--- |
| два дефекта с похожей цитатой | `cardblock.combo.range_boundary-days_api_exclusive+range_boundary-days_400_at_30` (собран генератором, общая опора БК-2) | F-07: строка API + БК-2; F-08: только БК-2 | TP #1←F-07, FP F-08 (спор с #1 и #2), FN #2 |
| дефект и дубль находки | `transfer_limit.event_conflict.cancel_no_restore` | F-01 и F-02, `kind=conflict`, одинаковые цитаты | TP #1←F-02 (меньший `pred_key`), DUP F-01 |
| чистый документ с тревогой | `cashback.base` | F-01 `ambiguity` | FP F-01 (`clean_false_alarm`) |

```bash
python -m evaluation.harness --gold evaluation/dev/controls/labels.jsonl --pred evaluation/dev/controls/predictions.jsonl --manifest evaluation/dev/controls/manifest.json --out-dir out/controls
python -m evaluation.dev controls --check
```

Итог: TP 2, FP 2, FN 1, дубли 1; P 2/4, R 2/3. Режим `--type-match exact`: TP 1, FP 4, FN 2.
Без находок: P = null, R = 0/3. Контроли ссылаются на документы корпуса seed 1 и его хеш не меняют.

## Контроли состава прогонов (`composition_controls/`)

Проверяют `python -m evaluation.harness.audit` на **настоящих** отчётах сборки 2821989 до подсчёта.
Ручной ответ — `composition_controls/expected.json`, записан до запуска. Сценарий `hidden_llm_failure`
добавлен после первого запуска семи, его ответ тоже записан до его прогона.

```bash
git worktree add --detach ../stand-2821989 2821989
python -m venv --system-site-packages ../venv && ../venv/bin/pip install anthropic==2.14.0
python -m evaluation.dev composition --stand ../stand-2821989 --python ../venv/bin/python --out out/composition
```

Как устроен стенд:
* Прогоны идут раннером и счётчиком стенда (раскладка 0.1.0, как у Max) на 33 кейсах MD.
* `rules_only` — `python -m bcc_review --offline-lint` в сетевой песочнице.
* `rules_plus_llm` — тот же движок через `replay_product.py`: подменён только HTTP-транспорт адаптера
  Anthropic. Отвечают конверты записей `tests/p11/fixtures`, они синтетические (`"_synthetic": true`).
  Реальных запросов к Anthropic нет, ключ не нужен.
* Пара: `rules_only` базы и `rules_plus_llm` сценария. Каждый сценарий меняет ровно один кейс.

Фактический результат (`results/composition_open_stand.json`, 8 из 8 совпали с ручным ответом,
сборка с нуля — 5 мин 25 с):

| Сценарий | Код аудита | Нарушение → case_id | Причина (из матрицы) | Существующий `compare` |
| :--- | ---: | :--- | :--- | :--- |
| base | 0 | — (32 пары допустимы, `edge.empty` — симметричный пропуск) | — | сопоставимо |
| same_name_changed | 3 | `sha_mismatch` → cashback.unit_change.accrued_in_tiyn | отчёт по `89c8f351…`, манифест и строка run — `386739bb…`, имя то же | сопоставимо |
| run_twice | 3 | `repeat` → autopay.two_statuses.range_422 | 2 строки run, 2 `report.json`, два `run_id`, 8 находок объединятся | сопоставимо |
| clean_without_report | 3 | `missing_report` → cardblock.base (чистый) | `status=failed (exit=1)`, stderr: `_BootstrapProviderError: overloaded … 529` | сопоставимо |
| requested_llm_got_rules_only | 3 | `mode_mismatch` → transfer_limit.range_boundary.reaching_rejects | запрошен `rules_plus_llm`, отчёт `rules_only`, 0 вызовов: адаптер не создан без ключа | сопоставимо |
| valid_partial | 0 | — (partial: cashback.two_statuses.bad_category_200) | 5 этапов с ответом модели ok, `individual=failed`; 3 ошибки 529 в stderr, отчёт их не учёл | сопоставимо |
| old_report_fields | 4 | `unknown` → autopay.paraphrase.nfr | нет `run.mode`, `run.calls.physical`, `run.stages` | сопоставимо |
| hidden_llm_failure | 0 | — (partial: cardblock.unit_change.blocked_at_utc) | отчёт `complete`, но 2 ошибки 529 на `cross.pairs` есть только в stderr | сопоставимо |

Что стенд показал о сборке 2821989 (это код продукта, не зона №16; передано Max):
* Адаптер команды ищет общий `ProviderError` в `bcc_review.providers.base` и `bcc_review.errors`. Класс
  лежит в `bcc_review.contracts`, поэтому адаптер бросает `_BootstrapProviderError`, а `asker`
  такую ошибку не перехватывает. Следствия:
  * 529 на этапе `bank` роняет процесс (exit 1, `report.json` нет);
  * 529 на `cross.pairs` не виден в отчёте: `status=complete`, этап не записан, `calls.physical`
    занижен на число неуспешных вызовов, `calls.failed=0`;
  * повторов нет: при `--max-retries 3` каждый пакет `individual` с ответом 529 запрошен один раз,
    `run.calls.retries=0`.
* Без `ANTHROPIC_API_KEY` прогон `--provider anthropic` завершается с кодом 0 и отчётом `mode=rules_only`.

## Изоляция закрытого набора

* В dev-корпусе только `visibility: public`. Тест `test_dev_corpus_has_no_closed_material`
  проверяет это и отсутствие файлов с `closed/private/hidden` в именах.
* Генератор читает только `families.py`; закрытые данные он не получает.
* Закрытые метки и документы храните вне этого репозитория или в игнорируемом каталоге
  (`/out/` уже в `.gitignore`).

## Инструкция для GPT Pro: запуск на закрытой выборке

1. Разметка в общем формате: `case_id, family, source_sha256, issue_type, anchors, expected_outcome`.
   Типы — из `evaluation/harness/taxonomy.toml`. Плоскую разметку (`defect_id, type, quote,
   line/locator, related_quote, …`) приведите командой:
   ```bash
   python -m evaluation.harness adapt-labels --in closed_flat.jsonl --out closed_labels.jsonl
   ```
2. Манифест закрытого набора в том же формате, что `corpus/manifest.json`. Поля `case_id`,
   `primary_render` и `renders[]` с `render_id`, `format`, `path` и `sha256` обязательны,
   `path` указывается относительно манифеста. Без манифеста счётчик свяжет предсказания с кейсами по
   `source_sha256` эталона, но не сможет учесть другие форматы и правило уникального фрагмента.
3. Проверка утечки без раскрытия ответов:
   ```bash
   python -m evaluation.harness fingerprint --labels closed_labels.jsonl --docs closed_docs/ --out closed.fp.json
   python -m evaluation.harness leakcheck --dev evaluation/dev/corpus --fingerprint closed.fp.json
   ```
   Выводятся только количества совпадений (SHA-256 файлов, case_id, 5–8-граммы цитат); код 1 — утечка.
4. Одна команда без ручного манифеста (файлы сопоставляются с эталоном по SHA-256):
   ```bash
   python -m evaluation.harness run --gold closed_labels.jsonl --docs closed_docs/ --mode rules_only --out out/closed
   ```
   Результаты: `metrics.json`, `matrix.jsonl`, `adjudication.jsonl`, `summary.txt`.
   Прогон двух режимов на одном манифесте и одной настройке кэша (ключ выдаёт команда, координирует №18):
   ```bash
   python -m evaluation.harness run --manifest closed/manifest.json --mode rules_only --out out/closed/ro --gold closed_labels.jsonl
   python -m evaluation.harness run --manifest closed/manifest.json --mode rules_plus_llm --provider gemini --out out/closed/llm --gold closed_labels.jsonl
   python -m evaluation.harness compare --metrics rules_only=out/closed/ro/metrics.json --metrics rules_plus_llm=out/closed/llm/metrics.json --out out/closed/compare.md
   ```
5. Разбор: `out/closed/*/adjudication.jsonl` — все FP с подсказкой (near_miss, clean_false_alarm,
   control_hit, background). Заполните `decision`, затем повторите подсчёт с `--adjudication`.
   Для выборки зафиксируйте seed до просмотра: `--review-seed 2026-11-27 --review-sample 50`.
