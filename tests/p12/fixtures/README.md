# Фикстуры №12 (Gemini)

Каждый файл `gemini/*.json` описывает один HTTP-ответ `generateContent` (или `models.list`) в формате
`{"http_status", "headers", "body"}`. `tests/p12/p12_support.py` отдаёт его через `MockTransport`, поэтому
разбор идёт через настоящий код google-genai.

| Происхождение | Файлы |
| :--- | :--- |
| **Сняты с живого API** 2026-11-26 из этой среды (`generativelanguage.googleapis.com/v1beta`) | `err_400_api_key_invalid.json` (заголовок `x-goog-api-key` с заведомо фальшивым ключом), `err_403_no_key.json` (запрос без ключа) |
| Реконструированы по публично известной форме ошибок Gemini (`google.rpc.QuotaFailure`, `RetryInfo`, `ErrorInfo`), в этой сессии вживую не наблюдались | `err_429_*.json`, `err_503_overloaded.json`, `err_500_internal.json`, `err_504_deadline.json`, `err_404_model.json`, `err_400_schema_too_complex.json`, `err_400_location.json` |
| Синтетические успешные и неполные ответы в REST-форме `GenerateContentResponse` | `ok_*.json`, `max_tokens_*.json`, `empty_*.json`, `prompt_blocked.json`, `safety_finish.json`, `schema_violation.json`, `not_json.json`, `models_list.json` |

Значения квот (`quotaValue` 10 / 250 / 0) и задержки (`39s`, `12s`, `7s`) условные: они проверяют разбор, а не
реальные лимиты. Реальные лимиты зависят от модели и аккаунта.

`synthetic_schema.json` — общая синтетическая схема этапа (форма `Candidate` по контракту v1) для №11 и №12.
В ней специально есть ключевые слова, которых нет в подмножестве Gemini (`$ref`, `const`, `pattern`,
`minLength`, `uniqueItems`, `type: [..., "null"]`). Копия встроена в `gemini.DOCTOR_SCHEMA`, их равенство
проверяет тест. Когда опубликуют `contracts/v1.json`, её заменит схема из контракта.

Чтобы №11 мог переиспользовать сценарии, достаточно положить ответы Anthropic в `fixtures/anthropic/` в
том же формате `{"http_status", "headers", "body"}`.
