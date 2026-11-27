| Кейс | с | cr/maj/min | конфл. | найдено (! — critical) | промах |
| :--- | ---: | :--- | ---: | :--- | :--- |
| autopay.base | 100.5 | 0/0/5 | 0 |  |  |
| autopay.paraphrase.nfr | 92.7 | 0/0/4 | 0 |  |  |
| cardblock.base | 53.3 | 0/0/4 | 0 |  |  |
| cardblock.paraphrase.keep_authorizations | 57.3 | 0/0/4 | 0 |  |  |
| cashback.base | 79.6 | 0/0/6 | 0 |  |  |
| cashback.paraphrase.rate | 83.2 | 0/0/7 | 0 |  |  |
| clean20.capital_v2 | 139.4 | 0/0/9 | 0 |  |  |
| clean20.fx | 231.8 | 2/0/8 | 2 |  |  |
| clean20.grace_v2 | 209.3 | 0/0/9 | 0 |  |  |
| clean20.insurance_v2 | 135.9 | 0/0/9 | 0 |  |  |
| clean20.qr_v2 | 95.2 | 0/0/7 | 0 |  |  |
| clean20.repay | 123.2 | 1/0/6 | 1 |  |  |
| clean20.roundup | 177.3 | 0/1/7 | 0 |  |  |
| clean20.statement | 127.5 | 1/0/7 | 1 |  |  |
| open2.capital_clean | 149.5 | 0/1/9 | 0 |  |  |
| open2.grace_clean | 109.2 | 0/0/7 | 0 |  |  |
| open2.insurance_clean | 137.2 | 0/0/10 | 0 |  |  |
| open2.qr_clean | 117.8 | 0/0/9 | 0 |  |  |
| transfer_limit.base | 89.4 | 0/0/5 | 0 |  |  |
| transfer_limit.paraphrase.new_limit | 65.6 | 0/1/3 | 1 |  |  |

* open2.capital_clean: К 0/5 (cr 0), С 0/20, найдено: 
* open2.grace_clean: К 0/5 (cr 0), С 0/20, найдено: 
* open2.insurance_clean: К 0/5 (cr 0), С 0/20, найдено: 
* open2.qr_clean: К 0/5 (cr 0), С 0/20, найдено: 
Чистых 20: critical 4, major 3, документов с major > 1: 0. Противоречия корпуса и open2: 0/0.

## Замечания critical и major на чистых

* **clean20.fx** critical event_conflict [pair_check] Ф-10 обязывает push, И-4 отменяет его после ошибок — L44«После выполненного обмена клиент получает один push» ↔ L56«после чего push не отправляется»
* **clean20.fx** critical status_conflict [pair_check] Для счёта в методе 2 назван ACCOUNT_NOT_FOUND, а в примере QUOTE_NOT_FOUND — L140«404 ACCOUNT_NOT_FOUND» ↔ L187«"errorCode":"QUOTE_NOT_FOUND"»
* **clean20.repay** critical status_conflict [pair_check] 422 «не проведено» против 200 после повтора (п. 2 особых правил) — L158«При кодах 400, 401, 404, 409 и 422 погашение по этому запрос» ↔ L139««проведена» — 200 с результатом этой операции»
* **clean20.roundup** major terminology [glossary] Разные названия участника: «Клиент», «держателя карты» — L34«Клиент» ↔ L134«держателя карты»
* **clean20.statement** critical event_conflict [pair_check] Пункты 24 и 40: опрос при закрытом экране разрешён и запрещён — L24«Пока экран заказа открыт, приложение запрашивает статус кажд» ↔ L40«статус заказа (метод 3) каждые 5 секунд, пока IN_PROGRESS»
* **open2.capital_clean** major missing_element [model] Выбор карты в приложении без списка карт в API — L28«выбор карты для выплаты (виден при выборе «На карту»)» ↔ L53«Приложение получает ставку, проценты за текущий месяц и исто» ↔ L201«"payoutCardId":null»
* **transfer_limit.paraphrase.new_limit** major unit_mismatch [pair_check] Лимит: строка в ответе GET, целое число в запросе PUT — L59«limit | string | Лимит в тенге, целое число» ↔ L77«limit | integer | Да | от 10 000 до 3 000 000 включительно |»
