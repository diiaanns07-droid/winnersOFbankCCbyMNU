# №12 · Воспроизводимый запуск на Gemini

Адаптер `src/bcc_review/providers/gemini.py` и его тесты. Документ служит передачей для Max (движок,
владелец контракта), №11 (адаптер Anthropic) и №18 (холодный прогон). Основа — `bcc/integration`
2821989 (движок, `runtime.asker`, контракт v1 431f76d), влитая в ветку `claude/vigilant-sagan-xjr7yo`.
Второй проход (общий бюджет и честное число запросов) — раздел 10.

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
3. Каждая модель вызывается не больше одного раза за `invoke`. **Второй физический запрос внутри одного
   `invoke` уходит только после `call_gate(model_id)` вызывающего** (раздел 10). Без гейта `invoke` делает
   ровно один запрос: в `attempts` пишется `{"skipped": "no_call_gate"}`, в `detail.fallback_available` —
   запасная модель, и следующий `invoke` (повтор движка) начинается с неё (`"failed_in_previous_invoke"` в
   `attempts`). Дополнительный запрос делается только если до конца `timeout_s` осталось не меньше
   `min_attempt_s` (по умолчанию 5 с, `GEMINI_MIN_ATTEMPT_S`), иначе `{"skipped": "budget"}`. Тайм-аут
   HTTP-запроса равен остатку бюджета.
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
| `pytest tests/contract tests/p12` на Python 3.13.18 (второй проход, с влитым 6be9e97) | 166 passed, 3 skipped (3 живых теста без ключа) |
| `cold_run.sh` на свежем клоне c7d7f7a, Python **3.11.18**, чистый venv, `pip install -e ".[dev]" google-genai==3.6.1` | exit 0: 164 passed, 5 skipped (ещё 2 пропуска: без пакета `anthropic` тесты с адаптером №11 пропускаются); в первом проходе `doctor` из такого venv против живого API давал `auth/invalid_key`, exit 2 |
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

0. **Влить эту ветку заново**: в `bcc/integration` 6a6c503 (`ced537d`) лежит первый проход `6f7bfbf`. На нём
   `GeminiAdapter()` без аргументов (так его создаёт `engine.setup_provider`) не читает `GEMINI_API_KEY`:
   даже с ключом прогон даёт `not_configured` и уходит в rules_only. Плюс перерасход запросов (раздел 10).
   **Влить `tests/p12/max_asker_call_gate.diff`** (раздел 10): без него запасная модель недостижима при
   `quota`/`not_found` и при Retry-After длиннее остатка времени, хотя бюджет и счёт запросов уже честные.
1. Extra `gemini` в `pyproject.toml` (2821989) — `google-genai>=1.0`. Адаптер опирается на `response_json_schema` и `HttpOptions(httpx_client=…)`, проверен на **3.6.1**; предлагаю `google-genai>=3.6,<4`.
2. `invalid_output` в контракте не временная, поэтому пустой content (`subkind` `empty_candidates` или
   `empty_text`) движок не повторит. Если повтор нужен, его можно включить по `subkind`, не меняя словарь.
3. Схема №11 разрешает `null` для списков, контракт — нет (раздел 4).

Проверено: `src/bcc_review/providers/` без `__init__.py` попадает и в обычный `pip install .`
(у `packages.find` в `pyproject.toml` по умолчанию `namespaces = true`), импорт адаптера работает.

## 10. Общий бюджет и честное число запросов (второй проход)

**Проблема (воспроизведена на `6f7bfbf` с настоящим `runtime.asker.Asker` из 6be9e97 и повторно на
действующем `bcc/integration` 6a6c503, где лежит этот же адаптер).** `Asker` делает
`budget.check` и `budget.note_call` один раз перед `invoke`, а `run.calls.physical` складывается из
`stats.call`, которых тоже одна на `invoke`. Прежний адаптер с запасной моделью делал внутри одного `invoke`
два `generate_content`: при `max_calls=1` уходило 2 запроса. В сквозном `run_review` при `max_calls=2` уходило
4 запроса при `run.calls.physical = 2`, а неудачная основная модель не попадала в `models_seen`.

**Минимальная правка адаптера (`gemini.py`).** Публичный `invoke(*, model, messages, schema, timeout_s)` не
изменился. Добавлены необязательный `call_gate` и признак `GeminiAdapter.supports_call_gate = True`:

* первый физический запрос `invoke` учитывает вызывающий, как и раньше;
* каждый следующий запрос внутри того же `invoke` уходит только после `call_gate(model_id)`. Исключение из
  гейта (например, `BudgetExhausted`) отменяет запрос: `{"skipped": "call_gate"}`, `detail.fallback_blocked`,
  наружу выходит исходная ошибка основной модели;
* без гейта `invoke` никогда не делает больше одного запроса, а запасную модель берёт следующий `invoke`;
* в `attempts` у каждой попытки есть `t_s` (смещение от начала `invoke`), у результата — `meta.t_s`;
* `GeminiAdapter()` без аргументов читает `GEMINI_*` из окружения: движок создаёт адаптер именно так
  (`engine.setup_provider`: `res.func()`). Прежний адаптер в этом случае остался бы без ключа;
* `params` (temperature, max_output_tokens, thinking_*) попадают в ключ кэша `Asker`.

**Правка для Max (`tests/p12/max_asker_call_gate.diff`, 33 строки в `runtime/asker.py`).** Заменяемые
фрагменты лежат в `tests/p12/p12_asker_patch.py`. Тест применяет их к текущему `asker.py` и сверяет с
закоммиченным diff. `git apply --check` проходит на 6a6c503 (и проходил на 6be9e97). Полный `pytest tests`
на копии 6a6c503 с diff и этим адаптером даёт те же 17 падений, что и чистый 6a6c503 (шрифты и PDF №14, №02,
№04, №08, №09, №15, №16, `conftest` №11), и ни одного в `tests/p12`; пройдено 1192 вместо 1161.

* `_call_gate(stage, attempt)`: только для адаптеров с `supports_call_gate` (Mock и Anthropic не затронуты,
  это проверено тестом). Гейт делает `budget.check` + `budget.note_call` и пишет в трассу `fallback_call`;
* `_note_inner_attempts`: неудачные запросы внутри `invoke` записываются в `stats.call(ok=False)`, поэтому
  `run.calls.physical` и `failed` совпадают с транспортом;
* ошибка с `physical_calls == 0` (модель уже отключена в этом прогоне) не считается вызовом, как и
  `not_configured`.

**Результат.** Имитируются только HTTP-транспорт SDK (`MockTransport` + фикстуры) и часы. `Asker`, `Budget`,
`Cache`, `StageStats`, `Tracer`, `ContextBuilder` и SDK google-genai 3.6.1 настоящие. Одна стадия
`individual`; основная модель `gemini-2.5-flash`, запасная `gemini-2.5-flash-lite`; задержка ответа 1,5 с.

```bash
python -m tests.p12.p12_budget
```

| Asker | Случай | Ушло запросов (flash / lite) | Отчёт: calls.physical · model · models_seen | Статус | Причина остановки |
|---|---|---|---|---|---|
| HEAD 6a6c503 | лимит 1, flash 503 → lite | 1 / 0 | 1 · flash · [flash] | budget_exhausted | исчерпан лимит вызовов модели (1) |
| HEAD 6a6c503 | лимит 2, flash 503 → lite | 1 / 1 | 2 · lite · [flash, lite] | ok | — |
| HEAD 6a6c503 | лимит 2, flash quota → lite | 1 / 0 | 1 · flash · [flash] | ask_error:quota | quota не временная, повтора нет |
| HEAD 6a6c503 | тёплый кэш после лимита 2 | 0 / 0 | 0 · lite · [lite], cache_hits 1 | ok | — |
| HEAD 6a6c503 | лимит 2, Retry-After 39 с, остаток 30 с | 1 / 0 | 1 · flash · [flash] | budget_exhausted | пауза Retry-After превышает остаток |
| + diff Max | лимит 1, flash 503 → lite | 1 / 0 | 1 · flash · [flash] | budget_exhausted | гейт отказал: лимит вызовов (1) |
| + diff Max | лимит 2, flash 503 → lite | 1 / 1 | 2 · lite · [flash, lite] | ok | — |
| + diff Max | лимит 2, flash quota → lite | 1 / 1 | 2 · lite · [flash, lite] | ok | — |
| + diff Max | тёплый кэш после лимита 2 | 0 / 0 | 0 · lite · [lite], cache_hits 1 | ok | — |
| + diff Max | лимит 2, Retry-After 39 с, остаток 30 с | 1 / 1 | 2 · lite · [flash, lite] | ok | — |

Таймлайн лимита 2 (503 → lite). HEAD: flash в 0,0 с (503), пауза движка 2 с, lite в 3,5 с (200), конец
этапа 5,0 с. С diff: flash в 0,0 с, гейт, lite в 1,5 с, конец этапа 3,0 с, пауз нет.

Сквозной `run_review` (настоящий движок, `run.modules.provider = team:bcc_review.providers.gemini:GeminiAdapter`,
пример `contracts/examples/two_linked_requirements.md`): при `max_calls=1` ушёл 1 запрос и
`run.calls.physical = 1`; при `max_calls=2` ушло 2 запроса, `physical = 2`, `run.model = gemini-2.5-flash-lite`.
На прежнем адаптере было 2 при `physical 1` и 4 при `physical 2`.

| Тест | Что доказывает |
| :--- | :--- |
| `test_p12_asker_budget.py` | лимиты 1 и 2, quota, тёплый кэш, Retry-After больше остатка; оба варианта Asker; таймлайн; diff применяется и совпадает |
| `test_p12_engine_budget.py` | то же число запросов в `Report.run` сквозного `run_review` |
| `test_p12_fallback.py::test_without_gate_*`, `::test_gate_*` | протокол гейта на уровне адаптера |

На прежнем адаптере (`gemini.py` из 6f7bfbf в отдельной копии дерева) `test_p12_asker_budget.py` даёт 17 падений
из 24, а `test_p12_engine_budget.py` — 2 из 2. На действующем 6a6c503 (тот же адаптер) оба файла вместе дают
19 падений из 27.
