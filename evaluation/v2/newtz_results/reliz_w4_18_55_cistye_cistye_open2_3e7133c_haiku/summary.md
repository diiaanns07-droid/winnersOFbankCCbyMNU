# Новые ТЗ №18 — релиз-w4 18:55 чистые: чистые open2, 3e7133c, haiku

Кейсов 4, прогонов 4, не измерено 0.

**Recall —** (0/0): critical 0/0, major 0/0, minor 0/0. Вне эталона 0, дублей 0, критичных ложных 0.

Чистые версии (4): замечаний 72, из них ложных (вне фона шаблона) 68: critical 2, major 16; документов с critical 2, с > 1 замечанием 4, вердикт «нельзя» 2.

Recall по типам: .

Время 15.8 мин суммарно, вызовов 35, $0.426.

| Кейс | Версия | Статус | Найдено | Замечаний (к/с/н) | Вердикт | Мин | Вызовов |
| :--- | :--- | :--- | :--- | :--- | :--- | ---: | ---: |
| capital_clean | clean | complete | — | 15 (0/0/15) | yes/yes | 3.1 | 8 |
| grace_clean | clean | complete | — | 17 (0/0/17) | yes/yes | 4.3 | 8 |
| insurance_clean | clean | complete | — | 20 (1/8/11) | no/no | 4.3 | 9 |
| qr_clean | clean | complete | — | 20 (1/8/11) | no/no | 4.1 | 10 |

Ложные на чистых версиях:

| Кейс | Серьёзность | Тип | Замечание | Источники | Владельцы |
| :--- | :--- | :--- | :--- | :--- | :--- |
| capital_clean | minor | incomplete | Пункты требований без ID, приоритетов и трассировки | consistency | №09 |
| capital_clean | minor | terminology | Одни понятия названы разными терминами, глоссария нет | consistency | №09 |
| capital_clean | minor | incomplete | Схема API не показывает сервис уведомлений из архитектуры | consistency | №09 |
| capital_clean | minor | missing_element | GET условий не возвращает дату начала нового способа | lens:architect | №07 |
| capital_clean | minor | missing_element | Экран выбора карты не имеет метода получения списка карт | consistency | №09 |
| capital_clean | minor | incomplete | Проверка счёта в тенге отсутствует в логике метода | lens:architect | №07 |
| capital_clean | minor | ambiguity | Неясно, входит ли текущий день в проценты за месяц | lens:analyst | №05 |
| capital_clean | minor | incomplete | Одно поле карты не хранит карту текущего месяца отдельно | lens:architect | №07 |
| capital_clean | minor | missing_element | Критерии приёмки не покрывают границы, ошибки и повторы | lens:qa | №06 |
| capital_clean | minor | incomplete | Закрытие счёта на способе «На карту»: получатель остатка не указан | lens:analyst | №05 |
| capital_clean | minor | contradiction | Закрытие счёта и заблокированная карта дают противоречивые выплаты | consistency | №09 |
| capital_clean | minor | ops_risk | Нет схемы отката и варианта скрытия функционала | lens:risk | №08 |
| capital_clean | minor | api_contract | Поле payoutCardId в ответе метода 2 не описано | lens:architect | №07 |
| capital_clean | minor | contradiction | Чужая неактивная карта: порядок проверок не задан, код 400 или 404 | consistency | №09 |
| grace_clean | minor | missing_element | Карточный процессинг указан как затронутый, но не в архитектуре | consistency | №09 |
| grace_clean | minor | unverifiable | Цель снизить долю без числа, периода и базы | consistency | №09 |
| grace_clean | minor | terminology | Одни понятия названы по-разному в разных разделах, глоссария нет | consistency | №09 |
| grace_clean | minor | missing_element | Кнопка «Пополнить» на экране не имеет описанного действия | consistency | №09 |
| grace_clean | minor | traceability | Нет ID у нефункциональных, данных и интеграционных пунктов и приоритетов | consistency | №09 |
| grace_clean | minor | incomplete | Документ не рассматривает ряд случаев | lens:analyst, consistency | №05, №09 |
| grace_clean | minor | incomplete | Интеграция не задаёт условие отправки при выключенном переключателе | consistency | №09 |
| grace_clean | minor | duplicate | Дата напоминания задана дважды: днями и фиксированным 22-м | consistency | №09 |
| grace_clean | minor | incomplete | Судьба переплаты после возврата покупки не описана | lens:analyst | №05 |
| grace_clean | minor | other | Ф-5 объединяет пять независимых правил в одном пункте | lens:analyst | №05 |
| grace_clean | minor | api_contract | Статус льготного периода: признак в данных и строка в API | lens:architect | №07 |
| grace_clean | minor | incomplete | Критерии приёмки покрывают основной путь, без границ и ошибок | lens:qa | №06 |
| grace_clean | minor | missing_element | Схема отката и скрытия функционала не описана | lens:risk | №08 |
| grace_clean | minor | incomplete | Выписка не сформирована: статус и daysLeft для истёкшего периода не заданы | lens:analyst | №05 |
| grace_clean | minor | missing_element | Прогноз процентов без ставки и даты окончания начисления | lens:analyst | №05 |
| grace_clean | minor | contradiction | interestForecast: два разных условия в логике и описании поля | lens:architect | №07 |
| insurance_clean | critical | contradiction | Возврат премии при досрочном погашении и отказе | lens:risk, consistency | №08, №09 |
| insurance_clean | major | missing_element | Статус полиса после отказа и погашения в API не описан | lens:architect, consistency | №07, №09 |
| insurance_clean | major | contradiction | Маршрут вызова страхования: архитектура и последовательность расходятся | consistency | №09 |
| insurance_clean | major | incomplete | Минимальный возраст 18 лет не проверяется в логике метода | lens:analyst, lens:architect | №05, №07 |
| insurance_clean | major | missing_element | Выпуск полиса и номер от партнёра не отражены в последовательности | lens:architect | №07 |
| insurance_clean | major | incomplete | Ошибка выдачи после подписания не описана, снятие страхования невозможно | consistency | №09 |
| insurance_clean | major | ambiguity | Округление премии до тенге не задано | lens:analyst | №05 |
| insurance_clean | major | contradiction | Повторный вызов для подписанной заявки: успех или 409 | lens:architect | №07 |
| insurance_clean | major | api_contract | Тела ответов 400 и 422 не совпадают с перечнем причин кодов | lens:architect | №07 |
| insurance_clean | minor | terminology | Одни и те же объекты названы разными терминами | consistency | №09 |
| insurance_clean | minor | missing_element | Функциональные требования Ф-1…Ф-6 без приоритета | consistency | №09 |
| insurance_clean | minor | unverifiable | Цель «без жалоб» не имеет показателя и требования | consistency | №09 |
| insurance_clean | minor | ambiguity | Не сказано, входит ли день выдачи в 14-дневный срок отказа | lens:analyst | №05 |
| insurance_clean | minor | incomplete | Полное погашение в первые 14 дней без заявления: сумма не задана | lens:analyst | №05 |
| insurance_clean | minor | non_singular | Ф-4 объединяет пять самостоятельных правил в одном пункте | lens:analyst | №05 |
| insurance_clean | minor | duplicate | Ставка после отказа записана в двух местах | consistency | №09 |
| insurance_clean | minor | missing_element | Сумма, срок и согласие не перечислены в хранимых данных | lens:architect | №07 |
| insurance_clean | minor | missing_element | Критерии приёмки покрывают малую часть правил и границ | lens:qa | №06 |
| insurance_clean | minor | missing_element | Схема отката и выключения функции не описана | lens:risk | №08 |
| qr_clean | critical | contradiction | Пример ответа возвращает сумму 5000 при QR с суммой 3000 | lens:qa | №06 |
| qr_clean | major | security | Чужой QR-код читается по короткому qrId без проверки владельца | lens:risk | №08 |
| qr_clean | major | contradiction | Схемы вызова перевода по QR расходятся в трёх местах | consistency | №09 |
| qr_clean | major | missing_element | Состояние перевода «в обработке» не хранится, но проверяется при отмене | lens:architect | №07 |
| qr_clean | major | contradiction | Срок QR: поле ttl в данных против фиксированных 15 минут | consistency | №09 |
| qr_clean | major | incomplete | Статус «оплачен» после REJECTED не снимается, шаг 6 блокирует повтор | lens:analyst | №05 |
| qr_clean | major | missing_element | Проверка requestId отсутствует в шагах логики метода перевода | lens:architect | №07 |
| qr_clean | major | incomplete | Экран получателя без активной карты KZT не описан | lens:analyst | №05 |
| qr_clean | major | incomplete | Одновременная оплата QR с суммой не описана | consistency | №09 |
| qr_clean | minor | incomplete | Функциональные требования и правила API без приоритетов и ID | consistency | №09 |
| qr_clean | minor | incomplete | Цель снижения ошибочных переводов не измеряется требованиями | consistency | №09 |
| qr_clean | minor | incomplete | Критерии приёмки не покрывают повтор, отказ и границы | lens:qa | №06 |
| qr_clean | minor | unverifiable | Нагрузка 200 переводов в секунду без порога времени и ошибок | lens:analyst | №05 |
| qr_clean | minor | missing_element | Перечень хранимых данных не содержит request_id и debit_card_id | lens:architect | №07 |
| qr_clean | minor | terminology | Названия карт зачисления и списания не едины | consistency | №09 |
| qr_clean | minor | ops_risk | Схема отката или выключения QR-переводов не описана | lens:risk | №08 |
| qr_clean | minor | ambiguity | Граница срока в 10:15:00 не согласована между методами | consistency | №09 |
| qr_clean | minor | duplicate | Срок 15 минут продублирован в особых правилах API | consistency | №09 |
| qr_clean | minor | api_contract | Поле status описано для всех ответов, в примерах ошибок его нет | lens:architect | №07 |
