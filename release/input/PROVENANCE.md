# Происхождение входов

| Файл | Происхождение | SHA-256 |
| :--- | :--- | :--- |
| `requirements.md` | Официальный документ организаторов: `docs/requirements.md` из BCC-HUB/ai-requirements-validator-task, коммит `928c1aa364265426105b69ba7a3444eac11b22db`, скопирован байт в байт. **Вход официального прогона.** | `e7dae55e5453a250d93e335f5ff9c7f775f4457ccddd333f4a67e47b20d74381` |
| `requirements.pdf` | **Не выдан организаторами.** Собран командой из `requirements.md` (PyMuPDF Story, шрифт с кириллицей), чтобы проверить PDF-вход. Текст тот же, вёрстка и номера блоков другие. | `fbca9c8282f440754d43c2ec689a27a9ccc32ac07a1c4b30a7ca22c21d7e4de2` |
| `other_topic_cashback.md` | Документ команды другой тематики (кэшбэк) с засеянными дефектами; ключ — `tests/integration/fixtures/other_topic_cashback.expected.md`. | `dba611718f649983b808d5f502e79fea4f8abe64b29b10da325bc0581ecd0b4b` |

Отдельно выданного организаторами PDF в комплекте нет. Если он появится, его прогоняют как отдельный вход
и записывают сюда источник и SHA-256.
