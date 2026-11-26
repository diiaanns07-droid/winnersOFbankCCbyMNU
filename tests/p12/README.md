# №12 · Воспроизводимый запуск на Gemini

Адаптер `src/bcc_review/providers/gemini.py` и его тесты. Документ служит передачей для Max (движок,
владелец контракта), №11 (адаптер Anthropic) и №18 (холодный прогон). Основа — `bcc/integration`
3e6b569 (контракт v1 431f76d), влитая в ветку `claude/vigilant-sagan-xjr7yo`.

## 1. Контракт (как в `bcc_review.contracts.ProviderAdapter`)

```python
from bcc_review.providers.gemini import GeminiAdapter
from bcc_review.contracts import ProviderError

adapter = GeminiAdapter.from_env()      # GEMINI_API_KEY, GEMINI_MODEL, GEMINI_FALLBACK_MODELS, …
result = adapter.invoke(model=None, messages=[...], schema={...}, timeout_s=90)   # None → GEMINI_MODEL
# {"data", "usage", "model", "request_id", "stop_reason", "meta"}
```

| Поле | Значение |
| :--- | :--- |
| `data` | объект JSON, прошедший **полную** валидацию по исходной схеме (`jsonschema`, draft 2020-12) |
| `usage` | `input_tokens`, `output_tokens`, `thinking_tokens`, `cache_read_input_tokens`, `total_tokens`, `physical_calls` |
| `model` | фактическая модель из `modelVersion` ответа, иначе вызванный id. Это значение идёт в `run.model` и `models_seen` |
| `request_id` | `responseId` Gemini |
| `stop_reason` | `finish_reason` Gemini; при успехе всегда `"STOP"` |
| `meta` (дополнительно) | `requested_model`, `called_model`, `model_version`, `fallback_used`, `attempts`, `schema_adjustments`, `latency_s` |

`messages`: `{"role": "system"|"user"|"assistant", "content": str | [{"type":"text","text":…}]}`.
`system` уходит в `system_instruction`, `assistant` становится ролью `model`, подряд идущие реплики одной
роли склеиваются.

**Ошибка** — `GeminiError`, подкласс общего `bcc_review.contracts.ProviderError`: `kind`, `message`,
`retry_after_s`, `status`, `request_id`, `usage`, `model`, `transient` совпадают с контрактом (это проверяет
тест). Дополнительно есть `subkind` (точная причина), `retry_after_source`, `physical_calls`, `attempts`,
`detail`, `provider="gemini"` и `to_dict()`. Других исключений `invoke` не выпускает. Сам адаптер не
повторяет запросы: SDK-ретраи выключены (`HttpRetryOptions(attempts=1)`).

## 2. Категории ошибок (словарь контракта v1)

| kind | transient | Gemini: условие → `subkind` | резервная модель |
| :--- | :---: | :--- | :---: |
| `not_configured` | нет | нет ключа → `missing_key`, нет SDK → `missing_sdk`, нет jsonschema, неверное число в env → `bad_env`. Сеть не трогается | нет |
| `auth` | нет | **400 INVALID_ARGUMENT + `API_KEY_INVALID`** (так отвечает живой API, а не 401) → `invalid_key`; 401/403 → `permission_denied`; 400 FAILED_PRECONDITION → `location_or_billing` | нет |
| `rate_limit` | да | 429 без признака дневной квоты → `per_minute` / `unspecified` | да |
| `quota` | нет | 429 с `quotaId …PerDay…` → `per_day`; `quotaValue "0"` → `limit_zero` (модели нет на бесплатном тарифе ключа) | да |
| `overloaded` | да | 503 UNAVAILABLE → `http_503` | да |
| `server` | да | 500 INTERNAL, 502 и прочие 5xx → `http_500` и т. п. | да |
| `not_found` | нет | 404 NOT_FOUND → `model` | да |
| `timeout` | да | клиентский тайм-аут → `client_timeout`; 504/408 → `server_timeout`; `timeout_s <= 0` → `budget_exhausted_before_call` (0 вызовов) | нет |
| `network` | да | DNS, соединение, прокси → имя исключения | нет |
| `bad_request` | нет | сервер отверг схему → `schema_rejected`; схему нельзя привести → `schema_conversion`; неверная схема → `invalid_schema`; неверные messages → `messages` | нет |
| `refusal` | нет | `promptFeedback.blockReason` → `prompt_<reason>`; finish SAFETY/RECITATION/… → `finish_<reason>` | нет |
| `truncated` | нет | finish `MAX_TOKENS` → `max_tokens`, даже если текст похож на JSON. `usage.thinking_tokens` показывает, сколько съели рассуждения | нет |
| `invalid_output` | нет | нет кандидатов → `empty_candidates`; пустой текст → `empty_text`; не JSON → `not_json`; нарушение полной схемы → `schema_mismatch` (`detail.violations` с путями); finish не STOP → `finish_<reason>` | нет |
| `unknown` | нет | прочие исключения → имя класса | нет |

`retry_after_s` берётся только из реальных данных ответа (`retry_after_source`): `RetryInfo.retryDelay`,
затем заголовок `Retry-After`, затем «retry in N s» из текста сервера. Для `quota/per_day` значение
передаётся как есть, но `transient=False`: сервер может прислать `retryDelay` в секундах и при исчерпанной
дневной квоте.

Ответ принимается **только** при `finish_reason == STOP`, непустом тексте (части `thought` отбрасываются),
валидном JSON и полной валидации по схеме. Пустой `[]`, `{"candidates": []}` или «нет находок» — нормальный
результат, а не пустой ответ. На ошибках по ответу (`truncated`, `invalid_output`, `refusal`) заполнены
`usage`, `model` и `request_id`: токены уже потрачены.

## 3. Резервная модель: точные условия

1. Список задаётся **только** явно: `GEMINI_FALLBACK_MODELS=id1,id2` или `GeminiAdapter(fallback_models=[…])`.
   По умолчанию он пуст. Префикс `models/` снимается, дубли и сама основная модель удаляются.
2. К следующей модели адаптер переходит только при `kind ∈ {not_found, quota, overloaded, server, rate_limit}`
   (настраивается параметром `fallback_on`). При остальных категориях цепочка обрывается сразу.
3. Каждая модель вызывается не больше одного раза за `invoke`. Резервная модель вызывается только если до
   конца `timeout_s` осталось не меньше `min_attempt_s` (по умолчанию 5 с, `GEMINI_MIN_ATTEMPT_S`). Иначе в
   `attempts` пишется `{"skipped": "budget"}`. Тайм-аут HTTP-запроса равен остатку бюджета.
4. Модель с `quota` или `not_found` до конца жизни экземпляра адаптера (одного прогона) больше не вызывается:
   в `attempts` пишется `{"skipped": …, "earlier_in_run": true}`, физического вызова нет. Сброс:
   `reset_model_state()`. Временные 429/503 не запоминаются.
5. Фактическая смена видна в `result["model"]`, `meta.fallback_used`, `meta.called_model` и `meta.attempts`.
   Движку стоит писать `result["model"]` каждого этапа в `run.models_seen`, а при `fallback_used` добавлять
   запись в `warnings`.

## 4. Отчёт о совместимости схемы

Решение: `response_mime_type="application/json"` + `response_json_schema` с **явным** приведением на нашей
стороне (`to_gemini_schema`) и **полной** локальной валидацией. На маленькой схеме сравнивались два варианта:

* `response_json_schema`: SDK 3.6.1 передаёт словарь на сервер **дословно**, клиентской проверки нет.
  Поэтому отправляемое подмножество контролируем сами.
* `response_schema` (OpenAPI-подмножество): SDK 3.6.1 падает ещё на клиенте (`const` →
  `ValueError: Literal values must be strings`). Этот вариант отклонён.

| Ключевое слово | Gemini (№12, этот адаптер) | Anthropic (№11, по его HANDOFF) | Кто гарантирует правило |
| :--- | :--- | :--- | :--- |
| `$ref` / `$defs` | подставляется inline; рекурсия и внешние ссылки дают `bad_request` до вызова | в HANDOFF №11 не указано | провайдер (структура) |
| `const` | `enum: [значение]` | в HANDOFF №11 не указано | провайдер + локально |
| `type: [T, "null"]` | `anyOf: [{type: T…}, {type: null}]`, `description` снаружи | сохраняется как есть | провайдер + локально |
| `oneOf` | `anyOf` | `anyOf` | **локально** (слабее, чем «ровно один») |
| `pattern`, `minLength`, `maxLength`, `uniqueItems`, `multipleOf`, прочие `format` | удаляются, **текстом дописываются в `description`** (`[ограничения: pattern=…]`) | дописываются в `description` | **локально** |
| `minimum`, `maximum`, `minItems`, `maxItems` | передаются | `minimum`, `maxItems` и `minItems > 1` уходят в `description` | провайдер + локально |
| `additionalProperties` | передаётся (true или false) | только `false`, иное уходит в `description` | провайдер + локально |
| `$schema`, `$id`, `$comment`, неизвестные ключи | удаляются с записью в журнал | — | — |
| `type`, `enum`, `required`, `properties`, `items`, `prefixItems`, `anyOf`, `title`, `description` | передаются, кириллица без изменений | передаются; регистр `enum` №11 дополнительно выравнивает | провайдер + локально |

Реальный журнал приведения: общая синтетическая схема №12 — 13 записей (два `$ref` подставлены, `const` и
`type[]` переписаны, 7 ограничений перенесены в `description`, `$schema` и `$id` удалены). Схема №11 —
`minLength` переносится в `description`, `inspected_block_ids: ["array","null"]` становится `anyOf`,
`hints.minItems: 1` передаётся. Весь `contracts/v1.json` тоже приводится без ошибок (тест).

Список «что принимает сервер Gemini» основан на памяти о документации Google: `ai.google.dev` из этой
среды не открылся (DNS). Если сервер отвергнет ключевое слово, `doctor` вернёт `bad_request/schema_rejected`,
и это слово переносится из `_PASSTHROUGH` в удаляемые (одна строка).

**Найдено на стыке:** общая схема №11 разрешает `inspected_block_ids: null`, а `Candidate` в контракте
требует массив, и HANDOFF прямо говорит «пустые списки — `[]`, не `null`». Кандидаты из
`expected_candidates.json` №11 не проходят `contracts.validate(…, "Candidate")`. Это зафиксировано тестом
`test_p11_schema_allows_null_lists_that_contract_rejects`. Решает №11 или Max: либо схема этапа требует
`[]`, либо движок нормализует `null → []` перед `validate`.

Правила, при которых схемы этапов одинаково переносимы на оба провайдера: у объектов
`additionalProperties: false` и полный `required`; пустое значение выражается как `[]`, `""` или `null`
по контракту; без рекурсии; `enum` из строк, короткие имена; не опираться на `pattern`/`minLength`/`oneOf` в
генерации (их держит локальная валидация, нарушение даёт `invalid_output`).

## 5. Модель и квоты

* По умолчанию `GEMINI_MODEL=gemini-2.5-flash`. Её актуальность для конкретного ключа **не проверена**: без
  ключа `models.list` недоступен, а сайт документации из среды не открылся. Перед демо обязательно выполните
  `python -m bcc_review.providers.gemini models` и выберите Flash-модель из выдачи.
* Бесплатная квота зависит от модели и аккаунта. Адаптер не хардкодит лимиты: он различает RPM, RPD и limit 0
  по `quotaId` и `quotaValue` из ответа.
* Gemini 2.5 Flash по умолчанию «думает», а рассуждения расходуют выходной бюджет. Поэтому `maxOutputTokens`
  по умолчанию **не задаётся**; `truncated` показывает `thinking_tokens`. Рассуждения можно отключить через
  `GEMINI_THINKING_BUDGET=0` (2.5 Flash) или `GEMINI_THINKING_LEVEL=low` (Gemini 3).
* `temperature`: 0 для 2.x. Для id с префиксом `gemini-3` не передаётся (рекомендация Google по памяти, не
  проверена); `GEMINI_TEMPERATURE` её переопределяет.

Для `.env.example` (файл ведут Max и №18):

```text
GEMINI_API_KEY=
GEMINI_MODEL=gemini-2.5-flash
# Резервные Flash-модели, только явно и через запятую; id берите из `python -m bcc_review.providers.gemini models`
GEMINI_FALLBACK_MODELS=
# GEMINI_MIN_ATTEMPT_S=5
# GEMINI_THINKING_BUDGET=0
```

## 6. Что проверено реально (2026-11-26, эта среда)

| Проверка | Результат |
| :--- | :--- |
| `google-genai` на PyPI: последняя версия **3.6.1**; поля `response_json_schema`, `response_schema`, `thinking_config`, `http_options.timeout` (мс), `HttpRetryOptions` | есть; при `retry_options=None` SDK не повторяет (исходник), адаптер явно ставит `attempts=1` |
| Транспорт SDK 3.6.1 | по умолчанию `httpx2` (резерв `httpx`). Тайм-аут и обрыв приходят «сырыми» `httpx2.ReadTimeout`/`ConnectError`, HTTP-ошибки — `errors.ClientError`/`ServerError` с полным телом; `thinkingConfig` уходит в snake_case |
| Живой API без ключа | 403 PERMISSION_DENIED, `ACCESS_DENIED` (фикстура снята) |
| Живой API с фальшивым ключом | **400 INVALID_ARGUMENT, `API_KEY_INVALID`** (фикстура снята) |
| `doctor` и `models` против живого API с фальшивым ключом | `auth/invalid_key`, `transient=false`, русское сообщение со ссылкой на AI Studio, exit 2, ключ не выводится |
| `doctor` без ключа | `not_configured/missing_key`, 0 сетевых вызовов, exit 2 |
| `pytest tests/contract tests/p12` на Python 3.13.18 | 133 passed, 4 skipped (адаптер №11 не влит, 3 живых теста без ключа) |
| `cold_run.sh` на свежем клоне, Python **3.11.18**, чистый venv, `pip install -e ".[dev]" google-genai==3.6.1` | exit 0: те же 133 passed и 4 skipped; `doctor` из этого venv против живого API даёт `auth/invalid_key`, exit 2 |
| ruff (E,F,W,B,UP,I), mypy по адаптеру | чисто |

**Не проверено** (нужен ключ команды): успешный `generateContent` с `response_json_schema` на реальной модели,
актуальный список Flash-моделей и их бесплатные лимиты, реальная форма 429/503/500 (фикстуры
реконструированы), поддержка сервером каждого ключевого слова из `_PASSTHROUGH`.

## 7. Холодный прогон (для №18) и проверка другого ключа

```bash
git clone https://github.com/diiaanns07-droid/winnersOFbankCCbyMNU && cd winnersOFbankCCbyMNU
git checkout claude/vigilant-sagan-xjr7yo
bash tests/p12/cold_run.sh python3.11
```

Без ключа выполняется только офлайн-часть. С ключом добавляются `models`, `doctor` и живые тесты (расход
4–5 запросов):

```bash
GEMINI_API_KEY=... GEMINI_MODEL=gemini-2.5-flash bash tests/p12/cold_run.sh python3.11
```

Вручную, в уже установленном окружении:

```bash
python -m bcc_review.providers.gemini models
python -m bcc_review.providers.gemini doctor --model gemini-2.5-flash
P12_LIVE=1 python -m pytest tests/p12/test_p12_live.py -v -s
```

Коды выхода `doctor`: 0 — успех, 2 — ключ или настройка, 3 — квота или лимит, 4 — модели нет, 1 — прочее.
`doctor` печатает паспорт: `requested_model`, фактическую `model`, `fallback_used`, `request_id`,
`stop_reason`, `usage` (включая `thinking_tokens` и `physical_calls`), `latency_s`. Его стоит приложить к
передаче вместе с датой.

## 8. Сценарии из задания и где они проверены

| Требование | Тест |
| :--- | :--- |
| Успех с одной находкой и с пустым массивом проходит общую схему | `test_p12_contract_join.py::test_one_finding_and_empty_list_pass_stage_schema` (схемы №12, №11 и `Candidate` контракта), `test_p12_invoke.py::test_one_finding_passes_full_schema`, `::test_empty_findings_are_a_valid_result_not_an_empty_response`, `::test_top_level_empty_array_is_accepted` |
| 503 → успех, 429 → истечение бюджета без бесконечного цикла | `test_p12_runtime_scenarios.py::test_503_then_success_is_one_retry`, `::test_429_until_deadline_stops_without_infinite_loop` |
| Недействительный ключ даёт понятную ошибку | `test_p12_errors.py::test_invalid_key_message_is_actionable` (фикстура с живого API), `test_p12_runtime_scenarios.py::test_invalid_key_stops_everything_with_clear_message` |
| Пустой или усечённый ответ не получает статус «полный» | `test_p12_errors.py::test_incomplete_responses_never_succeed`, `test_p12_runtime_scenarios.py::test_truncated_stage_never_counts_as_complete`, `::test_empty_response_is_reported_not_complete` |
| Запасной model_id применён и отражён в метаданных | `test_p12_fallback.py::test_fallback_model_is_used_and_reported`, `test_p12_runtime_scenarios.py::test_fallback_mid_run_is_visible_in_passport` |
| Отключение провайдера после части этапов | `test_p12_runtime_scenarios.py::test_provider_disconnect_after_two_stages_gives_partial` |
| Кириллица в запросе и ответе | `test_p12_invoke.py::test_wire_request_shape`, `::test_one_finding_passes_full_schema` |
| Стык с контрактом Max | `test_p12_contract_join.py` (наследование `ProviderError`, словарь `kind`, протокол `invoke`, `Candidate`, `contracts/v1.json`) |

`p12_runtime.py` — эталонный мини-runtime для этих сценариев. Это **не** код Max, а протокол из
`contracts/HANDOFF.md`, которого ждёт адаптер: повтор только при `transient`, пауза `retry_after_s` (иначе
своя), проверка «пауза влезает в общий дедлайн», выключение провайдера после
`not_configured`/`auth`/`not_found`/`quota` или исчерпанных повторов, статус `complete|partial|failed`.

## 9. Открытые вопросы к Max

1. В `pyproject.toml` нет extra для Gemini. Предложение: `gemini = ["google-genai==3.6.1"]` и добавить его в `all`.
2. `invalid_output` в контракте не временная, поэтому пустой content (`subkind` `empty_candidates` или
   `empty_text`) движок не повторит. Если повтор нужен, его можно включить по `subkind`, не меняя словарь.
3. Схема №11 разрешает `null` для списков, контракт — нет (раздел 4).

Проверено: `src/bcc_review/providers/` без `__init__.py` попадает и в обычный `pip install .`
(у `packages.find` в `pyproject.toml` по умолчанию `namespaces = true`), импорт адаптера работает.
