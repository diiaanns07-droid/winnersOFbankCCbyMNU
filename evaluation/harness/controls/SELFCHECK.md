# Контрольная арифметика счётчика

Счётчик 0.1.2 (bcc-eval-policy/1), sha256 `7b54d224c8115c5ec18c71ade817df4e53911ed53324c1e3f131c06bc0dc4660`.
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
| открытый корпус, hierarchy | TP | 2 | 2 | да |
| открытый корпус, hierarchy | FP | 2 | 2 | да |
| открытый корпус, hierarchy | FN | 1 | 1 | да |
| открытый корпус, hierarchy | дубли | 1 | 1 | да |
| открытый корпус, hierarchy | на разборе | 1 | 1 | да |
| открытый корпус, hierarchy | тревоги на чистом | 1 | 1 | да |
| открытый корпус, hierarchy | TP уровня parent | 1 | 1 | да |
| открытый корпус, hierarchy | precision | 2/4 = 0.5000 | 0.5000 | да |
| открытый корпус, hierarchy | recall | 2/3 = 0.6667 | 0.6667 | да |
| открытый корпус, hierarchy | f1 | 4/7 = 0.5714 | 0.5714 | да |
| открытый корпус, hierarchy | precision_strict | 2/5 = 0.4000 | 0.4000 | да |
| открытый корпус, hierarchy | матрица TP/FP/FN/DUP (строк) | 6 | 6 | да |
| открытый корпус, кейс cardblock | precision | 1/2 = 0.5000 | 0.5000 | да |
| открытый корпус, кейс cardblock | recall | 1/2 = 0.5000 | 0.5000 | да |
| открытый корпус, кейс transfer_limit | precision | 1/1 = 1.0000 | 1.0000 | да |
| открытый корпус, кейс transfer_limit | recall | 1/1 = 1.0000 | 1.0000 | да |
| открытый корпус, кейс transfer_limit | precision_strict | 1/2 = 0.5000 | 0.5000 | да |
| открытый корпус, кейс cashback | precision | 0/1 = 0.0000 | 0.0000 | да |
| открытый корпус, кейс cashback | recall | null | null | да |
| открытый корпус, кейс cashback | f1 | 0/1 = 0.0000 | 0.0000 | да |
| открытый корпус, hierarchy | разных результатов на 120 перестановках находок | 1 | 1 | да |
| открытый корпус, exact | TP | 1 | 1 | да |
| открытый корпус, exact | FP | 4 | 4 | да |
| открытый корпус, exact | FN | 2 | 2 | да |
| открытый корпус, exact | дубли | 0 | 0 | да |
| открытый корпус, exact | на разборе | 3 | 3 | да |
| открытый корпус, exact | тревоги на чистом | 1 | 1 | да |
| открытый корпус, exact | TP уровня parent | 0 | 0 | да |
| открытый корпус, exact | precision | 1/5 = 0.2000 | 0.2000 | да |
| открытый корпус, exact | recall | 1/3 = 0.3333 | 0.3333 | да |
| открытый корпус, exact | f1 | 2/8 = 0.2500 | 0.2500 | да |
| открытый корпус, exact | precision_strict | 1/5 = 0.2000 | 0.2000 | да |
| открытый корпус, exact | разных результатов на 120 перестановках находок | 1 | 1 | да |
| открытый корпус, без находок | precision | null | null | да |
| открытый корпус, без находок | recall | 0/3 = 0.0000 | 0.0000 | да |
| открытый корпус, без находок | f1 | 0/3 = 0.0000 | 0.0000 | да |
| открытый корпус, без находок, cashback | precision | null | null | да |
| открытый корпус, без находок, cashback | recall | null | null | да |
| открытый корпус, без находок, cashback | f1 | null | null | да |
| открытый корпус, без находок, cardblock | precision | null | null | да |
| открытый корпус, без находок, cardblock | recall | 0/2 = 0.0000 | 0.0000 | да |

Строк: 98, расхождений: 0.
