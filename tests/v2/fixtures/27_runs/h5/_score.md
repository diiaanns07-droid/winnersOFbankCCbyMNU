| Кейс | с | cr/maj/min | конфл. | найдено (! — critical) | промах |
| :--- | ---: | :--- | ---: | :--- | :--- |
| autopay.base | 105.8 | 0/0/6 | 0 |  |  |
| autopay.paraphrase.nfr | 104.3 | 0/0/5 | 0 |  |  |
| cardblock.base | 46.3 | 0/0/4 | 0 |  |  |
| cardblock.paraphrase.keep_authorizations | 82.3 | 0/0/5 | 0 |  |  |
| cashback.base | 83.5 | 0/0/6 | 0 |  |  |
| cashback.paraphrase.rate | 92.2 | 0/0/4 | 0 |  |  |
| clean20.capital_v2 | 117.3 | 0/0/10 | 0 |  |  |
| clean20.fx | 196.7 | 0/0/8 | 0 |  |  |
| clean20.grace_v2 | 135.4 | 0/1/6 | 0 |  |  |
| clean20.insurance_v2 | 142.1 | 0/1/9 | 0 |  |  |
| clean20.qr_v2 | 125.9 | 0/1/7 | 1 |  |  |
| clean20.repay | 157.3 | 0/1/8 | 1 |  |  |
| clean20.roundup | 197.6 | 0/0/6 | 0 |  |  |
| clean20.statement | 160.5 | 0/0/8 | 0 |  |  |
| open2.capital_clean | 156.0 | 0/0/8 | 0 |  |  |
| open2.grace_clean | 114.7 | 0/0/9 | 0 |  |  |
| open2.insurance_clean | 120.0 | 0/0/9 | 0 |  |  |
| open2.qr_clean | 92.6 | 0/0/7 | 0 |  |  |
| transfer_limit.base | 64.5 | 0/0/4 | 0 |  |  |
| transfer_limit.paraphrase.new_limit | 68.7 | 0/1/4 | 0 |  |  |

* open2.capital_clean: К 0/5 (cr 0), С 0/20, найдено: 
* open2.grace_clean: К 0/5 (cr 0), С 0/20, найдено: 
* open2.insurance_clean: К 0/5 (cr 0), С 0/20, найдено: 
* open2.qr_clean: К 0/5 (cr 0), С 0/20, найдено: 
Чистых 20: critical 0, major 5, документов с major > 1: 0. Противоречия корпуса и open2: 0/0.

## Замечания critical и major на чистых

* **clean20.grace_v2** major missing_element [model] Откат флагом обещан в чек-листе, но не описан в требованиях — L77«Откат — выключение функционала флагом в мобильном банке» ↔ L30«Требования к изменениям»
* **clean20.insurance_v2** major terminology [glossary] Разные названия участника: «заёмщика», «заявителя по кредиту» — L13«заёмщика» ↔ L111«заявителя по кредиту»
* **clean20.qr_v2** major status_conflict [pair_check] amount без суммы в QR: обязательно или нет — L128«Если суммы нет, поле amount обязательно: от 100 до 500 000 ₸» ↔ L154«amount | integer | 32 bit | Нет | 100–500 000»
* **clean20.repay** major unit_mismatch [pair_check] Ф-5 берёт ставку/12, Ф-3 — ставку/360 для тех же процентов — L36«i — годовая ставка / 12» ↔ L34«из расчёта «годовая ставка / 360»»
* **transfer_limit.paraphrase.new_limit** major missing_element [model] Остаток лимита обещан, но метод его не отдаёт — L29«Приложение показывает лимит и остаток лимита на текущие сутк» ↔ L60«used | string | Использовано за текущие сутки»
