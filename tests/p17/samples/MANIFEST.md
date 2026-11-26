# Образцы отчётов p17: проверяемый перечень

Сгенерировано `python tests/p17/p17_make_samples.py`. Синтетический Report контракта v1 (режим mock), нейтральный документ «Бронирование переговорных комнат» и выдержка учебного кейса банка для проверки группировки (`rootcause`). Не является прогоном модели. Каждый `report.json` проходит `bcc_review.contracts.validate` и `evidence_errors`.

Проверка любого образца: `python -m bcc_review.exports.markdown --check <report.md> <report.json>`.

| Образец | Сценарий | Статус прогона | Требований (полностью / частично / нет) | Дефектов уникальных (🔴/🟠/🟡) | Записей Jira | Сверка MD↔JSON | SHA-256 входа |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `complete-numbered` | Полный прогон, документ с нумерацией ТР-1…ТР-5 | `complete` | 9 (9 / 0 / 0) | 5 (2/2/1) | 5 | совпадает | `7f9248a5c594…` |
| `complete-unnumbered` | Полный прогон, документ без нумерации: ID присвоены агентом | `complete` | 9 (9 / 0 / 0) | 5 (2/2/1) | 5 | совпадает | `fe7e7be10691…` |
| `partial-numbered` | Частичный прогон: R-06 частично, R-07 не проверено; verdict ошибочно «ready» | `partial` | 9 (7 / 1 / 1) | 5 (2/2/1) | 5 | совпадает | `7f9248a5c594…` |
| `failed-numbered` | Прогон упал после нарезки: проверок и находок нет | `failed` | 9 (0 / 0 / 9) | 0 (0/0/0) | 0 | совпадает | `7f9248a5c594…` |
| `rootcause` | Две разные проблемы с одинаковыми cause.object и cause.condition: F-1 (+ дубль F-3) и F-2; F-4 на проверке | `complete` | 6 (6 / 0 / 0) | 2 (2/0/0) | 2 | совпадает | `2951793f2364…` |

## Контрольные суммы файлов

| Файл | SHA-256 |
| :--- | :--- |
| `complete-numbered/report.jira.csv` | `5da0884e84ccb375a573e9be321d65ca29fbd119ba94ffbc89996073946fb754` |
| `complete-numbered/report.json` | `719575e98ee55986e2dcf03c387188a0b9cb0267963a7d695a166922e62045a4` |
| `complete-numbered/report.md` | `064d4b380aca9fbad2d80e549bced65ec724a8ef2d12b510d55a73d3def5536c` |
| `complete-unnumbered/report.jira.csv` | `904a326246b803a719fa837773faa5f534cc0d2a3e9582bffb4fd1a7b8622943` |
| `complete-unnumbered/report.json` | `e8b5ae83614c8c226e75a6d83ba3b6855750da35e11cfbcad40ef2b91a9faed1` |
| `complete-unnumbered/report.md` | `a4d8a5323242a382ed1062b7711f5e55177cec342b7c9fe1f71528ca7b919290` |
| `failed-numbered/report.jira.csv` | `f1590723a7a500e25d038792c8f54eb046fb0d2c3b3bf40e0191e07d8ba9ad4b` |
| `failed-numbered/report.json` | `25aa80279eb95fcbabe9d7ca120b3ad916974a974d81200a294e4e553cf29ac5` |
| `failed-numbered/report.md` | `853628cff34536b9e1a814157220b1e550e6839eac8cb2e08ceb955c199ac1d1` |
| `partial-numbered/report.jira.csv` | `4153e6dd1afe15a719090c4acfef3f6562339a440b2f3d2cb747fe5f45c20968` |
| `partial-numbered/report.json` | `46464f669d5ee473658ab69d231e1cbc91914fad5ea09c56d01a2cd82879a6d2` |
| `partial-numbered/report.md` | `4d035c58ba5039e8404ab67db6944a866395bb81394e621d36396ebfe4fbe1db` |
| `rootcause/report.jira.csv` | `0a861c9387c4b0d5e51b4c101fd540dfc4048b708eddcf8c169252a4d8a6e97f` |
| `rootcause/report.json` | `45799017ee5f00ae4d142906246fb94effb1c13dd1b9affa578cb315070dbdc7` |
| `rootcause/report.md` | `39393775454e8eef42826b1e78307fc3aa6cfc3b7928fc6149fe36bdb5680823` |
| `source-numbered.md` | `7f9248a5c59473781eb02d42436d955631ad5d1a4568894b81271b63c82b6457` |
| `source-rootcause.md` | `2951793f2364ff782e20e9e582360fb9e2033ac4f46988fd830c334674fba7ef` |
| `source-unnumbered.md` | `fe7e7be106913db484c370cf1887407536e3ce90bc231743d27cda23b8829619` |
