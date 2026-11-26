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
4. Прогон двух режимов на одном манифесте и одной настройке кэша (ключ выдаёт команда, координирует №18):
   ```bash
   python -m evaluation.harness run --manifest closed/manifest.json --mode rules_only --out out/closed/ro --gold closed_labels.jsonl
   python -m evaluation.harness run --manifest closed/manifest.json --mode rules_plus_llm --provider gemini --out out/closed/llm --gold closed_labels.jsonl
   python -m evaluation.harness compare --metrics rules_only=out/closed/ro/metrics.json --metrics rules_plus_llm=out/closed/llm/metrics.json --out out/closed/compare.md
   ```
5. Разбор: `out/closed/*/adjudication.jsonl` — все FP с подсказкой (near_miss, clean_false_alarm,
   control_hit, background). Заполните `decision`, затем повторите подсчёт с `--adjudication`.
   Для выборки зафиксируйте seed до просмотра: `--review-seed 2026-11-27 --review-sample 50`.
