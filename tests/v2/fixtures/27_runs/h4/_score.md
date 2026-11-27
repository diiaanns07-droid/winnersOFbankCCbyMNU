| Кейс | с | cr/maj/min | конфл. | найдено (! — critical) | промах |
| :--- | ---: | :--- | ---: | :--- | :--- |
| autopay.base | 89.6 | 0/1/5 | 0 |  |  |
| autopay.paraphrase.nfr | 77.9 | 0/0/6 | 0 |  |  |
| cardblock.base | 70.0 | 0/0/5 | 0 |  |  |
| cardblock.paraphrase.keep_authorizations | 47.8 | 0/0/2 | 0 |  |  |
| cashback.base | 71.6 | 0/0/5 | 0 |  |  |
| cashback.paraphrase.rate | 92.6 | 0/0/6 | 0 |  |  |
| clean20.capital_v2 | 122.1 | 0/1/8 | 0 |  |  |
| clean20.fx | 172.4 | 0/0/6 | 0 |  |  |
| clean20.grace_v2 | 145.0 | 0/0/8 | 0 |  |  |
| clean20.insurance_v2 | 94.7 | 0/0/8 | 0 |  |  |
| clean20.qr_v2 | 127.0 | 1/0/10 | 1 |  |  |
| clean20.repay | 152.2 | 1/0/8 | 1 |  |  |
| clean20.roundup | 153.0 | 0/0/6 | 0 |  |  |
| clean20.statement | 166.9 | 0/0/7 | 0 |  |  |
| open2.capital_clean | 134.4 | 0/1/8 | 0 |  |  |
| open2.grace_clean | 87.0 | 0/0/9 | 0 |  |  |
| open2.insurance_clean | 122.8 | 0/0/10 | 0 |  |  |
| open2.qr_clean | 87.9 | 0/0/9 | 0 |  |  |
| transfer_limit.base | 49.5 | 0/0/4 | 0 |  |  |
| transfer_limit.paraphrase.new_limit | 76.5 | 0/1/4 | 1 |  |  |

* open2.capital_clean: К 0/5 (cr 0), С 0/20, найдено: 
* open2.grace_clean: К 0/5 (cr 0), С 0/20, найдено: 
* open2.insurance_clean: К 0/5 (cr 0), С 0/20, найдено: 
* open2.qr_clean: К 0/5 (cr 0), С 0/20, найдено: 
Чистых 20: critical 2, major 4, документов с major > 1: 0. Противоречия корпуса и open2: 0/0.

## Замечания critical и major на чистых

* **autopay.base** major missing_element [model] Тело ответа 200 у createAutopay обещано в разделе метода, но не описано — L98«Описано в разделе метода; для deleteAutopay тело пустое» ↔ L74«4. Сохранить настройку и вернуть 200.»
* **clean20.capital_v2** major missing_element [model] Выбор карты в UI без операции списка карт — L28«выбор карты для выплаты (виден при выборе «На карту»)» ↔ L53«Приложение получает ставку, проценты за текущий месяц и исто»
* **clean20.qr_v2** critical status_conflict [pair_check] Чужая карта: 400 в переводе и 404 в создании QR — L125«если нет, вернуть 400» ↔ L213«404 — карта не найдена или принадлежит другому клиенту»
* **clean20.repay** critical event_conflict [pair_check] Ключ после 30 дней: «не создаёт второе» против «как новый» — L48«Повторный запрос проведения с тем же ключом идемпотентности » ↔ L139«действует 30 дней (затем запрос с ним обрабатывается как нов»
* **open2.capital_clean** major missing_element [model] Выбор карты в UI без метода, отдающего список карт клиента — L28«выбор карты для выплаты (виден при выборе «На карту»)» ↔ L53«Приложение получает ставку, проценты за текущий месяц и исто»
* **transfer_limit.paraphrase.new_limit** major unit_mismatch [pair_check] Лимит: строка в ответе и целое число в запросе — L59«limit | string | Лимит в тенге, целое число» ↔ L77«limit | integer | Да | от 10 000 до 3 000 000 включительно |»
