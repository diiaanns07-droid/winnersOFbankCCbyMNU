# Счётчик качества (`evaluation/harness`, протокол bcc-eval v1)

Модуль №16. Он считает TP, FP, FN, дубли и ложные тревоги на чистых документах по эталону
и предсказаниям продукта и сравнивает режимы `rules_only` и `rules_plus_llm`.
Счётчик не обращается к LLM. Зависимости: стандартная библиотека Python 3.11+;
для PDF/DOCX в генераторе — reportlab, python-docx, pdfplumber.

```bash
python -m evaluation.harness --gold labels.jsonl --pred predictions.jsonl --out metrics.json
```

| Подкоманда | Что делает |
| :--- | :--- |
| *(без подкоманды)* | подсчёт: `--gold --pred --out [--manifest] [--adjudication] [--adjudication-out] [--type-match hierarchy\|exact] [--render-format md\|pdf\|docx] [--mode] [--status]` |
| `run` | прогон продукта по манифесту: `--manifest --mode rules_only\|rules_plus_llm\|mock --out DIR [--format] [--provider] [--cache off\|on] [--cases] [--gold]` |
| `adapt` | `report.json` продукта (контракт v1) → `predictions.jsonl` |
| `adapt-labels` | плоские метки (`defect_id, type, criterion, severity, quote, line/locator, related_quote, explanation`) → эталон с `anchors` |
| `compare` | таблица режимов: `--metrics rules_only=A/metrics.json --metrics rules_plus_llm=B/metrics.json --out compare.md` |
| `fingerprint`, `leakcheck` | проверка, что закрытые ответы не попали в открытый dev-набор (по хешам) |

Коды выхода: 0 — успешно, 2 — ошибка формата входа (сообщение называет файл, строку и поле),
3 — `compare`: режимы несопоставимы, 1 — `leakcheck`: найдена утечка.

## Форматы

**Эталон** (`labels.jsonl`, одна строка на дефект или на кейс). Обязательные поля, общие с GPT Pro:
`case_id, family, source_sha256, issue_type, anchors, expected_outcome`.

```json
{"label_id": "cashback.unit_change.cap_in_tiyn#1", "case_id": "cashback.unit_change.cap_in_tiyn",
 "family": "cashback", "source_sha256": "<SHA-256 размеченного файла>", "issue_type": "unit_mismatch",
 "anchors": [{"role": "a", "quote": "Сумма кэшбэка за месяц не превышает 10 000 тиынов.", "locator": "md:L27"},
             {"role": "b", "quote": "Провести покупку «Такси» на 4 000 ₸ | Кэшбэк месяца 10 000 ₸"}],
 "anchor_policy": "all", "expected_outcome": "present", "severity": "major",
 "criterion": "ISO29148-5.2.5:unambiguous", "scenario": "…", "explanation": "…", "visibility": "public"}
```

* `expected_outcome`: `present` — дефект, который нужно найти; `clean` — кейс без дефектов
  (`issue_type: null`, `anchors: []`), любая находка на нём — ложная тревога; `absent` —
  контрольное место (роль опоры `control`): находка здесь отмечается как `control_hit`.
* `anchor_policy`: `all` — находка должна процитировать все опоры (противоречия: обе стороны,
  как требует контракт v1 для конфликтов); `any` — достаточно одной (пропуск обещанного элемента).
* Опора — дословный видимый текст документа без Markdown-разметки. `locator` — справочный:
  сравнение идёт по тексту, поэтому одна разметка подходит для MD, PDF и DOCX.
* Каждый размеченный кейс полностью описан эталоном: строка `clean` или строки `present`.

**Предсказания** (`predictions.jsonl`): строки `record: "finding"` и `record: "run"`.
`adapt` и `run` строят их из `report.json`; можно подать и вручную в плоской форме.

```json
{"record": "finding", "source_sha256": "…", "mode": "rules_plus_llm", "defect_id": "F-003",
 "issue_type": "contradiction", "kind": "conflict", "severity": "major", "status": "confirmed",
 "anchors": [{"quote": "…", "locator": "line_end=27,line_start=27"}, {"quote": "…"}]}
{"record": "run", "source_sha256": "…", "mode": "rules_plus_llm", "status": "complete",
 "physical_calls": 9, "cache_hits": 0, "tokens_in": 41000, "tokens_out": 5200, "duration_s": 74.2}
```

Предсказание привязывается к кейсу по `render_id`, по `source_sha256` через манифест
(SHA-256 файла MD, PDF или DOCX), по `source_sha256` эталона или по явному `case_id`.
Если строки `run` есть, кейс без строки `run` или с `status: failed` считается **пропуском
измерения**, а не нулём находок. Пропуски перечислены в `missing_measurements`.

**Адаптер Report → предсказания** (контракт v1, `contracts/v1.json`): `Finding.evidence[].quote`
(при отсутствии — `block.text[start:end]`), `witness.evidence_a/b`, при пустых evidence — `hints`;
`Finding.kind` → `issue_type` по `taxonomy.toml`. `conflict` отображается в родителя `contradiction`:
продукт не различает подтипы event/status/unit/boundary, совпадение будет уровня `parent`.
Неизвестный `kind` даёт `other`, попадает в `unmapped_kinds` и не может стать TP без разбора.
Из `run` берутся `calls.physical`, `calls.cache_hits`, `tokens.input/output`, `duration_s`,
`mode`, `status`; `document.format: markdown` → формат представления `md`.

## Правила подсчёта

1. **Пара допустима**, если совпадают `case_id`, совместим вид дефекта (`exact`; `parent` при
   `--type-match hierarchy`, по умолчанию) и цитаты находки покрывают опоры по `anchor_policy`.
2. **Один к одному**: из допустимых пар строится паросочетание максимальной мощности (алгоритм
   Куна, порядок детерминирован). Групповая находка с опорами трёх дефектов закрывает один;
   остальные остаются FN с пометкой `claimed_by_group`.
3. **Дубль** — находка, допустимая только для уже закрытых дефектов. Дубли показываются отдельно,
   не входят ни в TP, ни в FP основной precision; `precision_strict` считает их FP.
   Из двух находок на один дефект TP получает точный тип, родительский тип уходит в дубли.
4. **На разбор** (`pending`): пограничный синоним типа (`borderline` в `taxonomy.toml`) или
   покрытие части опор. До решения это FP. Решения подаются `--adjudication decisions.jsonl`:
   `{"pred_key", "decision": "match"|"false_alarm"|"new_real_defect"|"duplicate", "label_id"}`.
   `new_real_defect` исключается из FP и TP и попадает в `new_real_defects`. Лист разбора по всем FP
   пишет `--adjudication-out`; `--review-seed S --review-sample N` даёт воспроизводимую выборку.
5. **Пустые знаменатели**: precision = TP/(TP+FP), `null` при TP+FP = 0; recall = TP/(TP+FN),
   `null` при TP+FN = 0; F1 = 2TP/(2TP+FP+FN), `null` при нуле. Пустой документ и полностью
   чистый документ без находок дают `null` по всем трём, а не 0 или 1.
6. **Форматы.** Независимый кейс — `case_id`. Основные метрики считаются по одному представлению
   (`primary_render` манифеста, обычно MD, или `--render-format`). PDF и DOCX идут в `per_format`
   и `format_consistency` как проверка парсера и экспорта, а не как новые победы.
7. **Чистые документы.** `clean_controls` — ложные тревоги на кейсах `clean`. Для мутантов
   `fp_background` отмечает ложную находку, которая есть и на чистой базе того же семейства.

### Почему непрерывный отрезок токенов (сравнение на малом примере)

Самый рискованный выбор — когда цитата находки «покрывает» опору эталона. Пять способов
проверены на 12 парах, включая надмножество-абзац, фрагмент, разметку, разрыв строки PDF,
пересказ LLM, соседнее предложение, отличие в числе и перемешанные ячейки PDF:

| Способ | Верно |
| :--- | ---: |
| вхождение подстроки после нормализации | 10/12 |
| мешок токенов, доля опоры ≥ 0.6 | 9/12 |
| символьный LCS ≥ 0.6 | 9/12 |
| **непрерывный общий отрезок токенов** | **11/12** |
| общая подпоследовательность токенов | 9/12 |

Символьные способы и мешок токенов путают «1 000 ₸» с «10 000 ₸» и строки приёмки,
отличающиеся одним числом. Итоговое правило (`normalize.coverage`):
* непрерывный общий отрезок ≥ 0.6 токенов опоры;
* или фрагмент опоры ≥ 4 токенов и ≥ 0.3 её длины (≥ 3 токенов, если в нём есть число или единица);
* или фрагмент ≥ 3 токенов, который встречается в документе кейса ровно один раз
  (по контракту v1 продукт цитирует дословный фрагмент блока).

Если на краю общего отрезка с одной из сторон стоит число, отрицание или единица измерения
(«тенге»/«тиынах», «UTC+5»/«UTC»), покрытия нет. Перемешанные ячейки PDF не засчитываются
автоматически и уходят на разбор как частичное покрытие. Таблица случаев зафиксирована
в `tests/p16/test_normalize.py`.

## Режимы продукта

`run` вызывает `python -m bcc_review INPUT OUTPUT.md` по контракту v1 и сравнивает режимы
на одинаковых манифесте, формате и настройке кэша. Всё это записано в `run_config.json` и в
каждой строке `run`; `compare` отказывается сравнивать несопоставимые прогоны.

* `rules_only` → `--offline-lint`. Дочерний процесс запускается в **сетевой песочнице**:
  ключи провайдеров (`*_API_KEY`, `ANTHROPIC_*`, `GEMINI_*`, `GOOGLE_*`, `OPENAI_*`, токены)
  удалены из окружения, `HTTP(S)_PROXY` указывает на закрытый порт `127.0.0.1:9`. Реальный запрос
  к LLM не может уйти. Дополнительно проверяется `run.calls.physical == 0` и `run.mode == rules_only`;
  иначе в строке `run` появляется `violations`.
* `rules_plus_llm` → `--provider anthropic|gemini`; `mock` → `--provider mock`.
* `--cache off` (по умолчанию) передаёт `--no-cache`, чтобы физические вызовы были настоящими.
* Длительность — время процесса по часам счётчика; вызовы и токены — из `report.json`.
  Не сообщённое значение в таблице показано как «—» с причиной, а не как 0.

## Что перенесено из qazaq-loc-qa (`src/evaluation.mjs`)

Перенесены функция метрик с `null` при пустом знаменателе, подсчёт дублей отдельно от уникальных
находок, блок `assumptions` в выходе и выбор без генератора случайных чисел через ранг
`sha256(seed, id)`. Последний используется в генераторе корпуса и в `--review-seed`.
Не перенесены: тождество `(key, issue_type)` вместо сопоставления по опорам, 11 типов локализации,
поля `source/target/confidence`.
