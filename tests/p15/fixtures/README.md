# Фикстуры tests/p15

| Файл | Откуда | Зачем |
| :--- | :--- | :--- |
| `case_ab.md` | дословная копия `docs/requirements.md` из BCC-HUB/ai-requirements-validator-task @ `928c1aa` (SHA-256 `e7dae55e5453a250d93e335f5ff9c7f775f4457ccddd333f4a67e47b20d74381`) | вход кейса: часть A + дочерняя спецификация B |
| `demo_answers.md` | написан командой | демонстрационные ответы с подписью происхождения и правкой текста (`--demo-answers`) |
| `mock_case_web.json` | `tests/integration/fixtures/mock_bcc.json` (Max) + этап `questions` | показ на настоящем движке без ключа: `--provider mock --mock-script …` |

Суффикс имени файла `__slow`, `__no_key`, `__network`, `__parse_partial`, `__crash`
включает сценарий сбоя **только** у подставного dev-движка (`--engine dev`).
