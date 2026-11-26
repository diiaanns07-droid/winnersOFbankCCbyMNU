# №11 → Max, №12, №18, №07: передача адаптера Claude API

Область №11: `src/bcc_review/providers/anthropic.py` и `tests/p11/`. Остальные файлы не менялись.
Адаптер сверен с контрактом движка на срезе `bcc/integration` `2821989` (`contracts.py`, `runtime/asker.py`):
ошибки — общий `bcc_review.contracts.ProviderError` со словарём `PROVIDER_ERROR_KINDS`.

## 1. Интерфейс

```python
from bcc_review.providers.anthropic import AnthropicAdapter, ProviderError

adapter = AnthropicAdapter(on_physical_call=budget.count)  # живой режим, читает ANTHROPIC_* из окружения
res = adapter.invoke(model=None, messages=msgs, schema=stage_schema, timeout_s=180)
res == {"data": <dict по схеме>, "usage": {...}, "model": "<фактическая модель>", "request_id": "req_...",
       "stop_reason": "end_turn"}   # все поля contracts.ProviderAdapter
```

* `model=None` берёт `ANTHROPIC_MODEL`, по умолчанию `claude-opus-5-5`. Ведущие сообщения `role=system`
  уходят в параметр `system`, на последнем блоке ставится `cache_control: ephemeral`.
* `schema` — JSON Schema (dict) или модель pydantic. Перед вызовом схема проверяется (`check_schema`).
* JSON outputs: `output_config.format = json_schema`. Ключи, которые API не принимает (`minLength`,
  `minimum`, `maxItems`, `pattern`, неподдержанные `format`, `minItems > 1`, `additionalProperties` ≠ false),
  дописываются текстом в `description`, а полная исходная схема проверяется локально через `jsonschema`.
  `oneOf` превращается в `anyOf`, `"type": [..., "null"]` сохраняется (на нём падает `anthropic.transform_schema`).
* Регистр `enum` документация не гарантирует. Если совпадение без учёта регистра единственное, значение
  исправляется, а число исправлений пишется в журнал (`enum_case_fixes`).
* `temperature`, `top_p`, `top_k`, `thinking`, `tool_choice` не передаются. С API `2026-10-21` первые три
  дают 400, у Opus 5.5 мышление адаптивное и включено всегда. `effort` задаётся через `ANTHROPIC_EFFORT`.
* **Серверный fallback включён по умолчанию** (`fallbacks="default"`, beta `server-side-fallback-2026-07-01`).
  Если модель отказала по политике, тот же запрос внутри одного HTTP-вызова выполняет другая модель.
  Фактическая модель приходит в `res["model"]`, факт подмены — в `last_call.fallback_used` и
  `passport().fallback_used`. Выключение: `ANTHROPIC_FALLBACKS=off`.

## 2. Таблица категорий ошибок (`ProviderError.kind`)

Класс — общий `bcc_review.contracts.ProviderError` (его ловит `Asker`), `kind` — строго из
`PROVIDER_ERROR_KINDS`. Конструктор: `ProviderError(kind, message, retry_after_s=, status=, request_id=,
usage=, model=)`; `message` = `detail` (рус., без секретов), `status` = HTTP-статус, `usage` — всегда dict.
Повтор решает движок по `err.transient` (`TRANSIENT_KINDS`). Атрибутами добавлены: `subkind, detail,
http_status, error_type, error_code, requested_model, retryable, ambiguous, alternatives, provider="anthropic"`.

| kind | Условие (HTTP / SDK / stop_reason) | subkind (примеры) | retryable | retry_after_s | Что делать Max |
| :--- | :--- | :--- | :---: | :---: | :--- |
| `not_configured` | нет `ANTHROPIC_API_KEY` (в конструкторе, до любого запроса) | `missing_key` | нет | — | `Engine.setup_provider` ставит `unavailable`, 0 HTTP-запросов |
| `auth` | 401, 403, `organization_on_hold` | `authentication`, `permission` | нет | — | стоп этапа, run `failed` или `rules_only` с пометкой |
| `quota` | 402 `billing_error`; 429 с `enforced/contract/linked_*_spend_limit*` | `billing`, `enforced_spend_limit_reached` | нет | обычно — | стоп, повтор бессмыслен |
| `rate_limit` | 429 с Retry-After / `retry-after-ms`, `ramp_limit_exceeded` | `rate_limit`, `ramp_limit_exceeded` | да | секунды | ждать и повторить из общего бюджета |
| `rate_limit` + `ambiguous=True` | 429 без Retry-After и без `error_code` | `no_retry_after`, `alternatives=("quota",)` | да | `None` | один повтор с backoff, затем считать квотой |
| `overloaded` | 529 / `overloaded_error` | `overloaded` | да | если есть | backoff |
| `timeout` | истёк `timeout_s` у клиента; 408/504 / `timeout_error` | `client_timeout`, `server_timeout` | да | если есть | повтор или увеличить `timeout_s` |
| `truncated` | HTTP 200, `stop_reason` ∈ max_tokens, model_context_window_exceeded, pause_turn, tool_use, compaction | имя stop_reason | нет | — | данные не приняты; поднять `ANTHROPIC_MAX_TOKENS` или разбить этап |
| `invalid_output` | HTTP 200, пустой текст, не JSON, JSON не по схеме | `empty_output`, `invalid_json`, `schema_mismatch` | да (атрибут) | — | движок **не** повторяет: `invalid_output` нет в `TRANSIENT_KINDS`; `detail` содержит пути ошибок |
| `refusal` | HTTP 200, `stop_reason=refusal` (и fallback не спас) | категория: `cyber`, `bio`, … | нет | — | этап `failed`, без «пустого успеха» |
| `bad_request` | 400/413/422; локально: prefill, пустые messages, плохая схема | `context_overflow`, `schema_too_complex`, `beta_not_enabled`, `prefill`, `invalid_schema` | нет | — | ошибка конфигурации; при `beta_not_enabled` выставить `ANTHROPIC_FALLBACKS=off` |
| `not_found` | 404 на GET /v1/models/{id} или `model: …` | `model` | нет | — | неверный `ANTHROPIC_MODEL`; ни одного токена не потрачено |
| `server` | 500, 502, 503 | `api_error`, `http_503` | да | если есть | backoff |
| `network` | ошибка соединения до ответа | `ConnectError`, … | да | — | backoff |
| `unknown` | 409, неизвестный stop_reason, нераспознанный конверт ответа | `conflict`, `unexpected_stop_reason`, `invalid_envelope` | 409 — да, иначе нет | если есть | лог и стоп |

При ошибках `truncated`, `invalid_output` и `refusal` токены уже потрачены. Поэтому `err.usage`,
`err.model` и `err.request_id` заполнены, а потраченное входит в `passport().usage_total`.

## 3. Счётчик и таймер (согласовать с Max)

* **Повторы SDK выключены** (`max_retries=0`). Один `invoke` даёт ровно один физический `POST /v1/messages`,
  а повторы планирует только общий бюджет Max. Если повторы включить, event hook httpx2 всё равно
  посчитает каждую попытку (тест `test_sdk_retries_if_enabled_are_still_counted`).
* `on_physical_call(event)` вызывается на **каждый** HTTP-запрос:
  `{"provider","mode","endpoint": "messages"|"models"|"other","method","retry_count"}`.
  Исключение из хука глотается и пишется в лог, иначе SDK выдал бы его за сетевую ошибку. Поэтому лимит
  бюджета Max проверяет **до** вызова `invoke`.
* Проверка модели (`GET /v1/models/{id}`, без токенов) выполняется один раз на модель за жизнь адаптера,
  перед первым `invoke`. В счётчике у неё `endpoint="models"`, отдельно от `messages`.
* `timeout_s` — лимит одной физической попытки: `httpx2.Timeout(read=write=pool=timeout_s,
  connect=min(10, timeout_s))`. Запрос не потоковый, поэтому `read` фактически равен ожиданию ответа.
  Для проверки модели берётся `min(timeout_s, 30)`.

## 4. usage, паспорт, режимы

`usage`: `input_tokens, output_tokens, cache_creation_input_tokens, cache_read_input_tokens,
cache_creation{ephemeral_5m_input_tokens, ephemeral_1h_input_tokens}, service_tier, inference_geo, speed,
iterations (при fallback), physical_calls, cost_usd, cost_basis`. Чего нет в ответе, то `None`.
`cost_usd` = `None`, пока тариф не передан явно (`prices={"claude-opus-5-5": {"input":…, "output":…,
"cache_read":…, "cache_write_5m":…, "cache_write_1h":…}}` в USD/MTok). Если тарифа не хватает,
`cost_basis` говорит почему.

`adapter.passport()` → поля для `Report.run`:

| Поле | Значение |
| :--- | :--- |
| `run_mode` | `rules_plus_llm` (живой API) или `mock` (записанные ответы). `rules_only` ставит Max, адаптер в нём не создаётся |
| `transport` | `https` / `recorded-fixture` / `custom-transport` |
| `official_endpoint` | `True` только для живого вызова `https://api.anthropic.com` |
| `credential` | `ANTHROPIC_API_KEY` / `argument` / `mock`. `ANTHROPIC_AUTH_TOKEN` (подписка, OAuth) **не используется никогда** |
| `models_seen`, `verified_models` | фактические модели ответов и данные GET /v1/models |
| `physical_calls` | `{"messages": n, "models": m, "other": 0}` |
| `api_versions`, `sdk` | `["2026-10-21"]`, `anthropic==2.14.0` |
| `usage_total`, `cost_usd`, `fallback_used`, `effort`, `max_tokens`, `provider_error_source` | сводка запуска |

`adapter.journal` — список очищенных записей по каждому вызову: модель, request_id, статус, kind,
stop_reason, задержка, токены. Те же записи уходят в logger `bcc_review.providers.anthropic`.

## 5. Для №18: окружение и запуск

```dotenv
# .env.example — блок Anthropic (значения ключа в git не класть)
ANTHROPIC_API_KEY=
ANTHROPIC_MODEL=claude-opus-5-5
ANTHROPIC_MAX_TOKENS=16000
ANTHROPIC_EFFORT=high
ANTHROPIC_FALLBACKS=default
# ANTHROPIC_BASE_URL не задавать: для сдачи нужен официальный API
```

Зависимости (`tests/p11/requirements-p11.txt`): `anthropic==2.14.0` (тянет `httpx2`, проверено 2.16.2)
и `jsonschema==4.26.0`. Проверено на Python 3.11.18 и 3.13.

```bash
python -m pip install -r tests/p11/requirements-p11.txt
```

```bash
python -m pytest tests/p11 -q
```

Не включайте `ANTHROPIC_LOG=debug` в банковских прогонах. Ключа в этом логе нет (проверено), но SDK пишет
в него полное тело запроса, то есть текст документа.

Один маленький живой вызов проверки (только в выделенном интеграционном запуске с ключом команды):

```bash
BCC_P11_LIVE=1 python -m pytest tests/p11/test_live_smoke.py -s
```

## 6. Для №12 (схемы) и №07 (опоры)

* Тестовая схема: `tests/p11/fixtures/schema_candidates.json`. Это Candidate + `hints[{block_id, quote}]` +
  `inspected_block_ids` (nullable). Сверьте с `contracts/v1.json`, когда он появится; поля проверяет
  `test_joint_contract.py`.
* Лимиты structured outputs (документация на 2026-11-26): не больше 24 необязательных полей и 16 полей
  с union-типами (`anyOf` или `type`-массив) на запрос; 400 «Schema is too complex for compilation».
  Рекомендация: все поля делать `required`, отсутствие выражать через `null`.
* Не просите в схеме поля «рассуждение / ход мысли»: это риск отказа `reasoning_extraction`.
  Лучше короткое `impact` или `explanation`.
* Citations несовместимы с `output_config.format` (400). Поэтому `block_id` и `quote` — обычные строки,
  а `block.text[start:end] == quote` проверяет №07 по первоисточнику.

## 7. Проверенные случаи (без ключа, на подставном транспорте через настоящий SDK)

Успех: данные, модель, request_id, cache read/write, `physical_calls=1`. Повторный прогон без ключа.
Форма запроса: нет sampling-параметров, wire-схема, effort, cache_control, fallbacks, beta-заголовок.
429 с Retry-After → `rate_limit`, 7 с. 429 без Retry-After → `rate_limit`, `ambiguous`. 401 → `auth`.
HTTP 200 + `max_tokens` → `truncated` с usage. Валидный JSON неверной схемы → `invalid_output`.
Нет ключа → `not_configured`, ноль запросов.

Стык с движком (`tests/p11/test_asker_path.py`): `Asker` → `AnthropicAdapter` → `ScriptedTransport`
(httpx2, синтетические ответы), заданные часы, реальный этап `individual#1` и его `response_schema()`.
Таблица «сценарий / GET / POST / пауза / тип ошибки» печатается в конце прогона pytest.
Также `minLength`, который API не проверяет, невалидный JSON, refusal, 529, 500, 504, 402, spend-cap 429,
сложная схема 400, тайм-аут клиента, ConnectError, неизвестная модель (0 вызовов messages), prefill
(0 вызовов), fallback на другую модель, нормализация регистра enum, стоимость только при явном тарифе,
настройки через окружение.

10 логических вызовов дают 10 физических. При включённых повторах SDK тоже считается каждая попытка.
Сломанный хук счётчика не превращается в сетевую ошибку.

Ключ, эхо ключа от сервера и `Bearer`-значение не появляются в `str/repr/traceback` ошибок, в журнале,
в паспорте и в логах SDK и httpx2 на уровне DEBUG.

Мутационная проверка: тесты ловят каждую из пяти внесённых поломок — повторы SDK, отключённое
редактирование секретов, отключённая проверка схемы, игнорирование max_tokens, потеря неоднозначности 429.

## 8. Памятка Max: что об одном ответе видно в report.json и trace.jsonl (срез 2821989)

Проверено в `tests/p11/test_response_metadata.py`: `Engine.make_ask → Asker → AnthropicAdapter → RecordedTransport`,
итог — из `Engine.run_individual`, `build_checks` и `build_run`. Таблица исходов печатается в конце pytest.

| исход ответа | POST | GET | `run.model` | `run.mode` | `stages[individual]` | где виден `kind` |
| :--- | :-: | :-: | :--- | :--- | :--- | :--- |
| валидный по схеме | 1 | 1 | claude-opus-5-5 | `rules_plus_llm` | `ok` | — |
| оборван по `max_tokens` | 1 | 1 | claude-opus-5-5 | `rules_only` | `failed` | `requirements[].review_reason`: «…: truncated: …» |
| ошибка схемы | 1 | 1 | claude-opus-5-5 | `rules_only` | `failed` | там же, `invalid_output` |
| отказ до генерации | 1 | 1 | claude-opus-5-5 | `rules_only` | `failed` | там же, `refusal` |
| тот же ответ из кэша | 0 | 0 | claude-opus-5-5 | `rules_plus_llm` | `ok` | — |

* `run.calls.physical` — число `invoke` (= POST при `max_retries=0`). Служебный `GET /v1/models/{id}` в отчёт
  не входит, он есть только в `adapter.passport()["physical_calls"]["models"]`.
* `run.model`, `models_seen` и `tokens` учитывают и неуспешные ответы: токены за усечение и отказ видны.
* `stages[].reason` при ошибке — общая фраза «…ошибки перехвачены модулем», без `kind`. `kind` попадает только
  в `requirements[].review_reason`. Статус `cached` из `STAGE_STATUSES` движок не ставит.
* `request_id` и `stop_reason` в report.json нет. В трассе `request_id` есть только у `call_ok`. У `call_error`
  нет ни `request_id`, ни токенов, они есть в `adapter.journal` / `adapter.last_call`.
* Кэш: `cache_hit` в трассе содержит только `stage, model, cache_key` (12 знаков). Происхождение прежнего
  ответа (`request_id`, `usage`, `requested_model`) лежит в файле `<cache>/<key[:2]>/<key>.json`, найти его
  можно по `cache_key`. В отчёте отличие видно только по `calls.physical=0`, `cache_hits=1`, `tokens=0`.
* Ошибка схемы у этого адаптера — 1 POST без повтора: схему проверяет адаптер (`invalid_output`), а этого kind
  нет в `TRANSIENT_KINDS`. Поэтому однократный повтор Asker по `call_invalid` здесь не срабатывает. Решать Max.

## 9. Открытые зависимости

1. **Закрыто:** общий `ProviderError` — `bcc_review.contracts` (срез `2821989`). Адаптер импортирует его
   напрямую, локальной копии и поиска по `bcc_review.providers.base` / `bcc_review.errors` больше нет;
   `PROVIDER_ERROR_SOURCE == "bcc_review.contracts"`.
2. **Max:** `contracts/v1.json`. Пока его нет, стыковой тест схемы пропускается.
3. **Max и №18:** живой демо-вызов с ключом команды не выполнялся: ключа в этой среде нет, отдельный
   интеграционный запуск не выделен. Результат подписать полями `res["model"]` и `passport()`.
4. **Max:** коммит с `stop_reason` проверен без настоящего SDK: пакета `anthropic` в среде не было, тесты шли поверх
   локальной заглушки вне репозитория (56 passed, 1 skipped). На `anthropic==2.14.0` нужно повторить
   `python -m pytest tests/p11 -q`.
