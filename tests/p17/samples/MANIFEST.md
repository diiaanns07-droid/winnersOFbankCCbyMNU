# Образцы отчётов p17: проверяемый перечень

Сгенерировано `python tests/p17/p17_make_samples.py`. Синтетический Report контракта v1 (режим mock), нейтральный документ «Бронирование переговорных комнат». Не является прогоном модели. Каждый `report.json` проходит `bcc_review.contracts.validate` и `evidence_errors`.

Проверка любого образца: `python -m bcc_review.exports.markdown --check <report.md> <report.json>`.

| Образец | Сценарий | Статус прогона | Требований (полностью / частично / нет) | Дефектов уникальных (🔴/🟠/🟡) | Записей Jira | Сверка MD↔JSON | SHA-256 входа |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `complete-numbered` | Полный прогон, документ с нумерацией ТР-1…ТР-5 | `complete` | 9 (9 / 0 / 0) | 5 (2/2/1) | 5 | совпадает | `7f9248a5c594…` |
| `complete-unnumbered` | Полный прогон, документ без нумерации: ID присвоены агентом | `complete` | 9 (9 / 0 / 0) | 5 (2/2/1) | 5 | совпадает | `fe7e7be10691…` |
| `partial-numbered` | Частичный прогон: R-06 частично, R-07 не проверено; verdict ошибочно «ready» | `partial` | 9 (7 / 1 / 1) | 5 (2/2/1) | 5 | совпадает | `7f9248a5c594…` |
| `failed-numbered` | Прогон упал после нарезки: проверок и находок нет | `failed` | 9 (0 / 0 / 9) | 0 (0/0/0) | 0 | совпадает | `7f9248a5c594…` |

## Контрольные суммы файлов

| Файл | SHA-256 |
| :--- | :--- |
| `complete-numbered/report.jira.csv` | `70c20b8c14b2cfde121c0fbc97ee8a8b7ce5634bb88698b1a3c0cb44593d9d86` |
| `complete-numbered/report.json` | `2430809f0dc1995be158bdd156bc3bc3278272abb67195f38f11c93a1f61a941` |
| `complete-numbered/report.md` | `b1c551b95d97857cbec1239672f9d48627317d9f14a88a25fbd5240caae84252` |
| `complete-unnumbered/report.jira.csv` | `71d890e8aaa228a59f72479faef04c2067eaa36c5421ea112516e841677509c0` |
| `complete-unnumbered/report.json` | `2376afe47f53beedc6d36ec0cc47b3d1d9acb65451c28683f1351e115814ad98` |
| `complete-unnumbered/report.md` | `683ccf696b8cf893cf11207aa85e71f4b5698973e73be3f05639381b25596e98` |
| `failed-numbered/report.jira.csv` | `f1590723a7a500e25d038792c8f54eb046fb0d2c3b3bf40e0191e07d8ba9ad4b` |
| `failed-numbered/report.json` | `25aa80279eb95fcbabe9d7ca120b3ad916974a974d81200a294e4e553cf29ac5` |
| `failed-numbered/report.md` | `d0c5179ed16061ba6ab68f26929d88aec552f73af8c1db7b7aee3b0a219268f3` |
| `partial-numbered/report.jira.csv` | `ebca12cfa2c0829999d8cebd2d9ff54e823990824cdfad5ae38523b1f70a881e` |
| `partial-numbered/report.json` | `d43a8b700fd1e7d5e316031ecd2be4a1c7e10cf75b929af72d9467870acf02fb` |
| `partial-numbered/report.md` | `dfb9904f5f081ad8299b2b09d2c7d44880a8eb7a7297b6eb354f5bfa44f52aeb` |
| `source-numbered.md` | `7f9248a5c59473781eb02d42436d955631ad5d1a4568894b81271b63c82b6457` |
| `source-unnumbered.md` | `fe7e7be106913db484c370cf1887407536e3ce90bc231743d27cda23b8829619` |
