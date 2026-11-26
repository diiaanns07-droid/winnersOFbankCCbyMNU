# №12 · Воспроизводимый запуск на Gemini

Адаптер `src/bcc_review/providers/gemini.py` и его тесты. Документ служит передачей для Max (runtime),
№11 (адаптер Anthropic) и №18 (холодный прогон).

## 1. Контракт

```python
from bcc_review.providers.gemini import GeminiAdapter, ProviderError, ErrorKind

adapter = GeminiAdapter.from_env()          # GEMINI_API_KEY, GEMINI_FALLBACK_MODELS, …
result = adapter.invoke(model="gemini-2.5-flash", messages=[...], schema={...}, timeout_s=90)
# result = {"data", "usage", "model", "request_id", "meta"}
```

| Поле | Значение |
| :--- | :--- |
| `data` | объект JSON, прошедший **полную** валидацию по исходной схеме (`jsonschema`, draft 2020-12) |
| `usage` | `input_tokens`, `output_tokens`, `thinking_tokens`, `cached_tokens`, `total_tokens`, `physical_calls` |
| `model` | фактическая модель из `modelVersion` ответа, иначе вызванный id. Это значение идёт в паспорт |
| `request_id` | `responseId` Gemini |
| `meta` | дополнительный ключ: `requested_model`, `called_model`, `model_version`, `fallback_used`, `attempts`, `finish_reason`, `schema_adjustments`, `latency_s` |

`messages`: `{"role": "system"|"user"|"assistant", "content": str | [{"type":"text","text":…}]}`.
`system` уходит в `system_instruction`, `assistant` становится ролью `model`, подряд идущие реплики одной
роли склеиваются. Нетекстовые блоки и неизвестные роли дают `ProviderError(bad_request)`.

**Правило для runtime:** `invoke` выпускает наружу только `ProviderError`. Ретраев внутри нет: SDK-ретраи
выключены (`HttpRetryOptions(attempts=1)`), каждая модель вызывается не больше одного раза за `invoke`.

## 2. Категории ошибок (`ProviderError.kind`)

| kind | Когда | retryable | резервная модель | `retry_after` |
| :--- | :--- | :---: | :---: | :--- |
| `config` | нет `GEMINI_API_KEY`, нет `google-genai`/`jsonschema`, неверное число в env. Сеть не трогается | нет | нет | — |
| `auth` | `API_KEY_INVALID` (**приходит как 400 INVALID_ARGUMENT, а не 401**), 401, 403 PERMISSION_DENIED, 400 FAILED_PRECONDITION (регион или биллинг) | нет | нет | — |
| `rate_limited` | 429 без признака дневной квоты (RPM/TPM) | да | да | `RetryInfo.retryDelay` → `Retry-After` → «retry in Ns» из текста сервера |
| `quota_exhausted` | 429 с `quotaId …PerDay…` или `quotaValue: "0"` (`detail.limit_zero`: модели нет на бесплатном тарифе ключа) | **нет**, даже если сервер прислал `retryDelay` | да | передаётся как есть |
| `overloaded` | 503 UNAVAILABLE, 500 INTERNAL, 502, прочие 5xx | да | да | если есть |
| `model_unavailable` | 404 NOT_FOUND (модель снята или не видна ключу) | нет | да | — |
| `timeout` | клиентский тайм-аут httpx/httpx2, 504 DEADLINE_EXCEEDED, 408, `timeout_s <= 0` (0 вызовов) | да | нет | — |
| `network` | DNS, соединение, прокси | да | нет | — |
| `bad_request` | прочие 400; `detail.schema_rejected`, если сервер отверг схему | нет | нет | — |
| `blocked` | `promptFeedback.blockReason`, finish `SAFETY`/`RECITATION`/`PROHIBITED_CONTENT`/… | нет | нет | — |
| `empty` | нет кандидатов, пустой текст | да | нет | — |
| `truncated` | finish `MAX_TOKENS`, даже если текст выглядит как JSON. В `detail.usage` есть `thinking_tokens` | нет | нет | — |
| `invalid_output` | не JSON, finish не `STOP`, нарушение полной схемы (`detail.violations` с путями) | да | нет | — |
| `unknown` | любое другое исключение SDK | нет | нет | — |

Ответ принимается **только** при `finish_reason == STOP`, непустом тексте (части `thought` отбрасываются),
валидном JSON и полной валидации по схеме. Пустой `[]`, `{"candidates": []}` или находки без ошибок
считаются нормальным результатом, а не «пустым ответом».

У каждой ошибки есть `provider`, `model`, `status`, `request_id`, `physical_calls`, `attempts`, `detail` и
`to_dict()`. Сообщение (`message`) написано по-русски для пользователя и не содержит ключа. Это проверяет тест.

## 3. Резервная модель: точные условия

1. Список задаётся **только** явно: `GEMINI_FALLBACK_MODELS=id1,id2` или `GeminiAdapter(fallback_models=[…])`.
   По умолчанию он пуст. Префикс `models/` снимается, дубли и сама основная модель удаляются.
2. К следующей модели адаптер переходит только при `kind ∈ {model_unavailable, quota_exhausted, overloaded, rate_limited}`
   (параметр `fallback_on` это настраивает). При auth, bad_request, truncated, invalid_output, blocked,
   timeout и network цепочка обрывается сразу.
3. Каждая модель вызывается не больше одного раза за `invoke`. Резервная модель вызывается только если до
   конца `timeout_s` осталось не меньше `min_attempt_s` (по умолчанию 5 с, `GEMINI_MIN_ATTEMPT_S`). Иначе в
   `attempts` пишется `{"skipped": "budget"}`. Тайм-аут HTTP-запроса равен остатку бюджета.
4. Модель с `quota_exhausted` или `model_unavailable` до конца жизни экземпляра адаптера (то есть одного
   прогона) больше не вызывается: в `attempts` пишется `{"skipped": …, "earlier_in_run": true}`, физического
   вызова нет. Сброс: `reset_model_state()`. Временные 429/503 не запоминаются.
5. Фактическая смена модели видна в `result["model"]`, `meta.fallback_used`, `meta.called_model` и
   `meta.attempts`. В паспорт `run` пишется `result["model"]` каждого этапа; при `fallback_used` в
   `warnings` нужна запись.

## 4. Совместимость схемы

Решение: `response_mime_type="application/json"` + `response_json_schema` с **явным** приведением на нашей
стороне (`to_gemini_schema`) и **полной** локальной валидацией. На маленькой схеме сравнивались два варианта:

* `response_json_schema`: SDK 3.6.1 передаёт словарь на сервер **дословно**, без клиентской проверки. Поэтому
  отправляемое подмножество контролируем сами.
* `response_schema` (OpenAPI-подмножество): SDK 3.6.1 падает ещё на клиенте (`const` → `ValueError: Literal
  values must be strings`). Этот вариант отклонён.

Журнал приведения общей синтетической схемы (реальный вывод `to_gemini_schema`, 1756 → 1425 символов):

| Ключевое слово | Где в схеме | Что уходит в Gemini | Кто гарантирует правило |
| :--- | :--- | :--- | :--- |
| `$ref` / `$defs` | `candidates.items`, `hints.items` | подставлено inline; рекурсия и внешние ссылки дают `bad_request` до вызова | Gemini (структура) |
| `const` | `stage` | `enum: [значение]` | Gemini + локально |
| `type: ["string","null"]` | `notes` | `anyOf: [{type: string}, {type: null}]`, `description` остаётся снаружи | Gemini + локально |
| `oneOf` | — (в тесте) | `anyOf` (слабее, чем «ровно один») | **локально** |
| `pattern` | `criterion`, `req_ids[]`, `block_id` | удаляется | **локально** (тест ловит `Ф-1` вместо `R-001`) |
| `minLength`, `maxLength`, `uniqueItems` | `title`, `quote`, `inspected_block_ids` | удаляются | **локально** |
| `format` ≠ date-time/date/time | — | удаляется | локально (jsonschema без format-checker не проверяет) |
| `$schema`, `$id`, `$comment`, прочие неизвестные ключи | корень | удаляются с записью в журнал | — |
| `type`, `enum`, `required`, `properties`, `additionalProperties`, `items`, `prefixItems`, `anyOf`, `minItems`, `maxItems`, `minimum`, `maximum`, `title`, `description` | везде | передаются как есть, кириллица без изменений | Gemini + локально |

Колонка «что поддерживает сервер Gemini» взята из памяти о документации Google: страница `ai.google.dev`
из этой среды не открылась (DNS). Живая проверка покажет расхождение сразу: `doctor` вернёт
`bad_request` с `detail.schema_rejected`. Тогда ключевое слово переносится из `_PASSTHROUGH` в удаляемые,
это одна строка.

Правила для схем этапов, которые одинаково переносимы на оба провайдера (предложение для Max и №11):

* у каждого объекта `additionalProperties: false` и явный `required` со всеми полями; nullable пишется как `type: [T, "null"]`;
* без рекурсии и внешних `$ref`, `enum` только из строк, вложенность до 5 уровней, короткие имена и enum (у Gemini
  есть ошибка 400 «schema produces a constraint that has too many states»);
* не полагаться на `pattern`/`minLength`/`oneOf` в генерации: их держит локальная валидация, а нарушение
  даёт `invalid_output`, после чего runtime делает повторный запрос;
* колонку Anthropic в этой таблице заполняет №11: в его адаптере должен быть тот же принцип «подмножество на
  провод + полная схема локально», тогда различия провайдеров влияют только на частоту повторов.

## 5. Модель и квоты

* По умолчанию `GEMINI_MODEL=gemini-2.5-flash`. Её актуальность для конкретного ключа **не проверена**: без
  ключа `models.list` недоступен, а сайт документации из среды не открылся. Перед демо обязательно выполните
  `python -m bcc_review.providers.gemini models` и выберите Flash-модель из выдачи.
* Бесплатная квота зависит от модели и аккаунта. Адаптер не хардкодит лимиты, а различает RPM, RPD и limit 0
  по `quotaId` и `quotaValue` из ответа.
* Gemini 2.5 Flash по умолчанию «думает», а рассуждения расходуют выходной бюджет. Поэтому `maxOutputTokens`
  по умолчанию **не задаётся**. Если runtime его ставит, `truncated` покажет `thinking_tokens`. Отключить
  рассуждения можно через `GEMINI_THINKING_BUDGET=0` (2.5 Flash) или `GEMINI_THINKING_LEVEL=low` (Gemini 3).
* `temperature`: 0 для 2.x. Для id с префиксом `gemini-3` температура не передаётся (рекомендация Google по
  памяти, не проверена). `GEMINI_TEMPERATURE` её переопределяет.

Переменные для `.env.example` (файл ведёт Max):

```text
GEMINI_API_KEY=
GEMINI_MODEL=gemini-2.5-flash
# Резервные Flash-модели, только явно и через запятую; берите id из `... gemini models`
GEMINI_FALLBACK_MODELS=
# GEMINI_MIN_ATTEMPT_S=5
# GEMINI_THINKING_BUDGET=0
```

## 6. Что проверено реально (2026-11-26, эта среда)

| Проверка | Результат |
| :--- | :--- |
| `google-genai` с PyPI: последняя версия **3.6.1**; поля `response_json_schema`, `response_schema`, `thinking_config`, `http_options.timeout` (мс), `HttpRetryOptions` | есть; при `retry_options=None` ретраев нет (исходник SDK), мы явно ставим `attempts=1` |
| Транспорт SDK 3.6.1 | по умолчанию `httpx2` (резерв `httpx`); тайм-аут и обрыв соединения приходят «сырыми» `httpx2.ReadTimeout`/`ConnectError`, HTTP-ошибки — `errors.ClientError`/`ServerError` с полным телом |
| Живой API без ключа | 403 PERMISSION_DENIED, `ACCESS_DENIED` (фикстура снята) |
| Живой API с фальшивым ключом | **400 INVALID_ARGUMENT, `API_KEY_INVALID`** (фикстура снята) |
| `doctor` против живого API с фальшивым ключом | `kind=auth`, русское сообщение со ссылкой на AI Studio, exit 2, ключ не выводится |
| `doctor` без ключа | `kind=config`, 0 сетевых вызовов, exit 2 |
| Офлайн-тесты: Python 3.13.18 (рабочая копия) и **Python 3.11.18 в свежем venv на чистом клоне** (`cold_run.sh`) | 90 passed, 8 skipped (5 стыковых ждут bootstrap, 3 живых ждут ключ) |
| ruff (E,F,W,B,UP,I), mypy по адаптеру | чисто |

**Не проверено** (нужен ключ команды): успешный `generateContent` с `response_json_schema` на реальной модели,
актуальный список Flash-моделей и их бесплатные лимиты, реальная форма 429/503 (фикстуры реконструированы),
поддержка сервером каждого ключевого слова из `_PASSTHROUGH`.

## 7. Холодный прогон (для №18) и проверка другого ключа

```bash
git clone https://github.com/diiaanns07-droid/winnersOFbankCCbyMNU && cd winnersOFbankCCbyMNU
git checkout claude/vigilant-sagan-xjr7yo
bash tests/p12/cold_run.sh python3.11
```

Без ключа скрипт выполняет только офлайн-часть. С ключом добавляются `models`, `doctor` и живые тесты
(расход 4–5 запросов):

```bash
GEMINI_API_KEY=... GEMINI_MODEL=gemini-2.5-flash bash tests/p12/cold_run.sh python3.11
```

Те же шаги вручную:

```bash
PYTHONPATH=src python -m bcc_review.providers.gemini models
PYTHONPATH=src python -m bcc_review.providers.gemini doctor --model gemini-2.5-flash
P12_LIVE=1 PYTHONPATH=src python -m pytest tests/p12/test_p12_live.py -v -s
```

Коды выхода `doctor`: 0 — успех, 2 — ключ или настройка, 3 — квота или лимит, 4 — модели нет, 1 — прочее.
`doctor` печатает паспорт: `requested_model`, фактическую `model`, `fallback_used`, `request_id`, `usage`
(включая `thinking_tokens` и `physical_calls`), `latency_s` и `finish_reason`. Его стоит приложить к
передаче вместе с датой и названием модели.

## 8. Сценарии из задания и где они проверены

| Требование | Тест |
| :--- | :--- |
| Успех с одной находкой и с пустым массивом проходит общую схему | `test_p12_invoke.py::test_one_finding_passes_full_schema`, `::test_empty_findings_are_a_valid_result_not_an_empty_response`, `::test_top_level_empty_array_is_accepted` |
| 503 → успех, 429 → истечение бюджета без бесконечного цикла | `test_p12_runtime_scenarios.py::test_503_then_success_is_one_retry`, `::test_429_until_deadline_stops_without_infinite_loop` |
| Недействительный ключ даёт понятную ошибку | `test_p12_errors.py::test_invalid_key_message_is_actionable` (фикстура с живого API), `test_p12_runtime_scenarios.py::test_invalid_key_stops_everything_with_clear_message` |
| Пустой или усечённый ответ не получает статус «полный» | `test_p12_errors.py::test_incomplete_responses_never_succeed`, `test_p12_runtime_scenarios.py::test_truncated_stage_never_counts_as_complete` |
| Запасной model_id применён и отражён в метаданных | `test_p12_fallback.py::test_fallback_model_is_used_and_reported`, `test_p12_runtime_scenarios.py::test_fallback_mid_run_is_visible_in_passport` |
| Отключение провайдера после части этапов | `test_p12_runtime_scenarios.py::test_provider_disconnect_after_two_stages_gives_partial` |
| Кириллица в запросе и ответе | `test_p12_invoke.py::test_wire_request_shape`, `::test_one_finding_passes_full_schema` |

`p12_runtime.py` — эталонный мини-runtime для этих сценариев. Это **не** код Max, а описание протокола,
которого ждёт адаптер: ретрай только при `retryable`, пауза `retry_after` (иначе своя), проверка
«пауза влезает в общий дедлайн», выключение провайдера после `config`/`auth`/`model_unavailable`/
`quota_exhausted` или исчерпанных ретраев 429/503, статус `complete|partial|failed`.

## 9. Стык с bootstrap

`gemini.ProviderError` наследуется от общего `ProviderError`, если он найден в `bcc_review.providers.base` или
`bcc_review.providers.errors`. Иначе используется локальный класс. Условие: эти модули не должны импортировать
`gemini` на верхнем уровне, иначе возникнет циклический импорт и молчаливый откат к локальному классу.
`test_p12_contract_join.py` после публикации bootstrap проверяет наследование, словарь `ErrorKind`,
сигнатуру `invoke` у №11 и приводимость `contracts/v1.json`:

```bash
PYTHONPATH=src python -m pytest tests/p12/test_p12_contract_join.py -v -rs
```

Зависимости для `requirements.txt` или `pyproject.toml` (их ведёт Max): `google-genai==3.6.1` (проверенная
версия), `jsonschema>=4.18`. Для тестов нужен `pytest>=8`.
