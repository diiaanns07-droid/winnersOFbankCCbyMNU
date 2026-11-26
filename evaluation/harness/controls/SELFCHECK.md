# Контрольная арифметика счётчика

Счётчик 0.1.1 (bcc-eval-policy/1), sha256 `e1a4d18b5be80a466f6762e0975d8e96cc9099f82ee56e3731bbecb0ce4bfe1f`.
Ручной ответ — `evaluation/harness/controls/*/expected.json`.

| Контроль | Показатель | Ручной ответ | Счётчик | Совпадает |
| :--- | :--- | :--- | :--- | :---: |
| hand_2tp | TP | 2 | 2 | да |
| hand_2tp | FP | 1 | 1 | да |
| hand_2tp | FN | 1 | 1 | да |
| hand_2tp | дубли | 0 | 0 | да |
| hand_2tp | precision | 2/3 = 0.6667 | 0.6667 | да |
| hand_2tp | recall | 2/3 = 0.6667 | 0.6667 | да |
| hand_2tp | precision_strict | 2/3 = 0.6667 | 0.6667 | да |
| hand_2tp + повтор F-2 | TP | 2 | 2 | да |
| hand_2tp + повтор F-2 | FP | 1 | 1 | да |
| hand_2tp + повтор F-2 | FN | 1 | 1 | да |
| hand_2tp + повтор F-2 | дубли | 1 | 1 | да |
| hand_2tp + повтор F-2 | precision | 2/3 = 0.6667 | 0.6667 | да |
| hand_2tp + повтор F-2 | recall | 2/3 = 0.6667 | 0.6667 | да |
| hand_2tp + повтор F-2 | precision_strict | 2/4 = 0.5000 | 0.5000 | да |
| граф A/B, hierarchy | TP | 2 | 2 | да |
| граф A/B, hierarchy | FP | 2 | 2 | да |
| граф A/B, hierarchy | FN | 0 | 0 | да |
| граф A/B, hierarchy | дубли | 1 | 1 | да |
| граф A/B, hierarchy | на разборе | 1 | 1 | да |
| граф A/B, hierarchy | тревоги на чистом | 1 | 1 | да |
| граф A/B, hierarchy | TP уровня parent | 1 | 1 | да |
| граф A/B, hierarchy | precision | 2/4 = 0.5000 | 0.5000 | да |
| граф A/B, hierarchy | recall | 2/2 = 1.0000 | 1.0000 | да |
| граф A/B, hierarchy | f1 | 4/6 = 0.6667 | 0.6667 | да |
| граф A/B, hierarchy | precision_strict | 2/5 = 0.4000 | 0.4000 | да |
| граф A/B, hierarchy | пары TP | {"rb.conflict#A": "Y-event", "rb.conflict#B": "X-group"} | {"rb.conflict#A": "Y-event", "rb.conflict#B": "X-group"} | да |
| граф A/B, hierarchy | дубль | {"Z-event-repeat": "rb.conflict#A"} | {"Z-event-repeat": "rb.conflict#A"} | да |
| граф A/B, hierarchy | спорные пары | 1 | 1 | да |
| граф A/B, hierarchy | разных результатов на 120 перестановках находок | 1 | 1 | да |
| граф A/B, exact | TP | 1 | 1 | да |
| граф A/B, exact | FP | 3 | 3 | да |
| граф A/B, exact | FN | 1 | 1 | да |
| граф A/B, exact | дубли | 1 | 1 | да |
| граф A/B, exact | на разборе | 2 | 2 | да |
| граф A/B, exact | тревоги на чистом | 1 | 1 | да |
| граф A/B, exact | TP уровня parent | 0 | 0 | да |
| граф A/B, exact | precision | 1/4 = 0.2500 | 0.2500 | да |
| граф A/B, exact | recall | 1/2 = 0.5000 | 0.5000 | да |
| граф A/B, exact | f1 | 2/6 = 0.3333 | 0.3333 | да |
| граф A/B, exact | precision_strict | 1/5 = 0.2000 | 0.2000 | да |
| граф A/B, exact | пары TP | {"rb.conflict#A": "Y-event"} | {"rb.conflict#A": "Y-event"} | да |
| граф A/B, exact | дубль | {"Z-event-repeat": "rb.conflict#A"} | {"Z-event-repeat": "rb.conflict#A"} | да |
| граф A/B, exact | спорные пары | 3 | 3 | да |
| граф A/B, exact | разных результатов на 120 перестановках находок | 1 | 1 | да |
| граф A/B, hierarchy | разных результатов на 24 перестановках эталона | 1 | 1 | да |
| граф A/B, кейс rb.conflict | precision | 2/3 = 0.6667 | 0.6667 | да |
| граф A/B, кейс rb.conflict | recall | 2/2 = 1.0000 | 1.0000 | да |
| граф A/B, кейс rb.conflict | precision_strict | 2/4 = 0.5000 | 0.5000 | да |
| граф A/B, кейс rb.clean | precision | 0/1 = 0.0000 | 0.0000 | да |
| граф A/B, кейс rb.clean | recall | null | null | да |
| граф A/B, кейс rb.clean | f1 | 0/1 = 0.0000 | 0.0000 | да |
| граф A/B, кейс rb.clean_empty | precision | null | null | да |
| граф A/B, кейс rb.clean_empty | recall | null | null | да |
| граф A/B, кейс rb.clean_empty | f1 | null | null | да |
| повтор формата MD+DOCX | независимых кейсов | 3 | 3 | да |
| повтор формата MD+DOCX | micro как у одного MD | True | True | да |
| повтор формата MD+DOCX | кейсов в per_format.docx | 1 | 1 | да |

Строк: 57, расхождений: 0.
