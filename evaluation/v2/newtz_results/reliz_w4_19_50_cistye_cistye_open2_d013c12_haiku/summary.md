# Новые ТЗ №18 — релиз-w4 19:50 чистые: чистые open2, d013c12, haiku

Кейсов 4, прогонов 4, не измерено 0.

**Recall —** (0/0): critical 0/0, major 0/0, minor 0/0. Вне эталона 0, дублей 0, критичных ложных 0.

Чистые версии (4): замечаний 79, из них ложных (вне фона шаблона) 75: critical 0, major 1; документов с critical 0, с > 1 замечанием 4, вердикт «нельзя» 0.

Recall по типам: .

Время 15.7 мин суммарно, вызовов 34, $0.422.

| Кейс | Версия | Статус | Найдено | Замечаний (к/с/н) | Вердикт | Мин | Вызовов |
| :--- | :--- | :--- | :--- | :--- | :--- | ---: | ---: |
| capital_clean | clean | complete | — | 18 (0/0/18) | yes/yes | 3.6 | 9 |
| grace_clean | clean | complete | — | 19 (0/0/19) | yes/yes | 4.8 | 9 |
| insurance_clean | clean | complete | — | 22 (0/0/22) | yes/yes | 4.1 | 8 |
| qr_clean | clean | complete | — | 20 (0/1/19) | yes/yes | 3.1 | 8 |

Ложные на чистых версиях:

| Кейс | Серьёзность | Тип | Замечание | Источники | Владельцы |
| :--- | :--- | :--- | :--- | :--- | :--- |
| capital_clean | minor | traceability | Критерии приёмки и пункты API без ID, приоритетов нет | consistency | №09 |
| capital_clean | minor | unverifiable | Цель по обращениям в контакт-центр не измерима | consistency | №09 |
| capital_clean | minor | terminology | Названия сервисов, приложения и карты не едины, глоссария нет | consistency, lens:architect | №07, №09 |
| capital_clean | minor | incomplete | Экран «Проценты»: нет состояний без карт в тенге и ошибок | lens:analyst, lens:qa | №05, №06 |
| capital_clean | minor | contradiction | Сумма процентов за месяц на экране и по Ф-2 считается по-разному | lens:risk | №08 |
| capital_clean | minor | missing_element | Список карт для выбора при «На карту» не описан нигде | consistency | №09 |
| capital_clean | minor | incomplete | Схема процесса не показывает ветки Ф-4 и Ф-5 | consistency | №09 |
| capital_clean | minor | incomplete | Закрытие счёта: способ выплаты за неполный месяц не определён | lens:analyst | №05 |
| capital_clean | minor | incomplete | Проверка валюты счёта при смене способа отсутствует в логике метода | consistency | №09 |
| capital_clean | minor | missing_element | Ф-5: причина в push при блокировке карты не задана | lens:analyst | №05 |
| capital_clean | minor | ambiguity | Граница месяца в шаге 4 без часового пояса | lens:architect | №07 |
| capital_clean | minor | duplicate | Правило даты вступления способа продублировано в Ф-3 и шаге 4 | consistency | №09 |
| capital_clean | minor | unverifiable | Доступность 99,9 % без указания сервиса и признака простоя | lens:analyst | №05 |
| capital_clean | minor | incomplete | Критерии приёмки не проверяют границы, ошибки и повторы | lens:qa | №06 |
| capital_clean | minor | missing_element | Схема отката способа выплаты не описана | lens:risk | №08 |
| capital_clean | minor | contradiction | Способ из запроса записывается в период текущего месяца | lens:architect | №07 |
| capital_clean | minor | incomplete | Чтение условий закрытого счёта: код ответа метода 2 не определён | consistency | №09 |
| grace_clean | minor | traceability | Нет ID и приоритетов у пунктов требований и критериев | consistency | №09 |
| grace_clean | minor | incomplete | Карточный процессинг указан в ИС, но не в архитектуре | consistency | №09 |
| grace_clean | minor | incomplete | Цель «снизить долю потерь» без показателя и срока | consistency | №09 |
| grace_clean | minor | terminology | Термины документа не едины, глоссария нет | consistency | №09 |
| grace_clean | minor | incomplete | Не определено, получит ли клиент напоминание, включённое после 22-го | lens:analyst | №05 |
| grace_clean | minor | incomplete | Экран не задаёт выбор карты и вид блока без льготного периода | lens:analyst | №05 |
| grace_clean | minor | missing_element | Кнопка «Пополнить» на экране не связана ни с каким описанным действием | consistency | №09 |
| grace_clean | minor | boundary_conflict | Не определено, входят ли покупки 1-го числа в сумму выписки | lens:analyst | №05 |
| grace_clean | minor | non_singular | Пункты Ф-2, Ф-4 и Ф-5 объединяют несколько правил | lens:analyst | №05 |
| grace_clean | minor | ambiguity | Термин «квази-кэш» не раскрыт перечнем операций | lens:qa | №06 |
| grace_clean | minor | contradiction | Сумма для погашения: фиксирована на выписке или уменьшается возвратом | consistency | №09 |
| grace_clean | minor | duplicate | Правило прогноза процентов продублировано в особых правилах API | consistency | №09 |
| grace_clean | minor | ambiguity | Не сказано, в какой момент проверяется неоплата для напоминания | lens:analyst | №05 |
| grace_clean | minor | incomplete | Критерии приёмки покрывают 5 из 11 функциональных требований | lens:qa | №06 |
| grace_clean | minor | ambiguity | Платёж, зачисленный минуту назад, может не попасть в сведения | lens:qa | №06 |
| grace_clean | minor | unit_mismatch | Суммы в ₸ в критериях и тиыны в API без правила пересчёта | lens:architect | №07 |
| grace_clean | minor | ops_risk | Схема отката не описана, экран нельзя скрыть при ошибке | lens:risk | №08 |
| grace_clean | minor | missing_element | Метод 1 не получает покупки для прогноза и общей задолженности | lens:architect | №07 |
| insurance_clean | minor | incomplete | Требования не имеют приоритетов и признаков важности | consistency | №09 |
| insurance_clean | minor | unverifiable | Цель «без жалоб» без числа не проверяется требованиями | consistency | №09 |
| insurance_clean | minor | terminology | Одни понятия названы разными терминами, глоссария нет | consistency | №09 |
| insurance_clean | minor | contradiction | Архитектура не показывает вызов сервиса страхования из API кредитов | consistency | №09 |
| insurance_clean | minor | incomplete | Экран условий не описан в начальном состоянии и при ошибках | lens:analyst | №05 |
| insurance_clean | minor | ambiguity | Возраст на дату окончания кредита нельзя определить при вызове | lens:architect | №07 |
| insurance_clean | minor | ambiguity | Округление премии до тенге не задано при дробном результате | lens:analyst | №05 |
| insurance_clean | minor | ambiguity | Срок отказа: день выдачи и граница дня не заданы | lens:analyst | №05 |
| insurance_clean | minor | ambiguity | Срок возврата премии не привязан к начальной дате | lens:analyst | №05 |
| insurance_clean | minor | contradiction | Порядок возврата при погашении и отказе в одном периоде не задан | consistency, lens:risk, lens:analyst | №05, №08, №09 |
| insurance_clean | minor | incomplete | Значение status после отказа от страхования не задано | lens:architect | №07 |
| insurance_clean | minor | duplicate | Правило ставки 27 % после отказа записано в двух местах | consistency | №09 |
| insurance_clean | minor | missing_element | Срок кредита отсутствует в перечне хранимых данных | lens:architect | №07 |
| insurance_clean | minor | ambiguity | Момент «полного досрочного погашения» не определён: заявка или зачисление | lens:risk | №08 |
| insurance_clean | minor | incomplete | Нижняя граница 18 лет не проверяется в логике метода | consistency, lens:analyst, lens:qa, lens:architect | №05, №06, №07, №09 |
| insurance_clean | minor | missing_element | Поля согласия и статуса страхования не в перечне данных | lens:architect | №07 |
| insurance_clean | minor | missing_element | Критерии приёмки покрывают не все функциональные требования | lens:qa | №06 |
| insurance_clean | minor | ops_risk | Нет схемы отката и способа выключить функцию страхования | lens:risk | №08 |
| insurance_clean | minor | api_contract | Тела 400 и 422 не различают причины отказа | lens:architect | №07 |
| insurance_clean | minor | api_contract | Тела ответов 404 и 409 для методов 3–5 не заданы | lens:architect | №07 |
| insurance_clean | minor | status_conflict | Название кода 422 расходится с RFC 9110 | lens:architect | №07 |
| qr_clean | major | contradiction | Маршрут перевода QR: через сервис QR-кодов или напрямую в сервис переводов | lens:analyst, lens:architect, consistency | №05, №07, №09 |
| qr_clean | minor | incomplete | Цель о снижении ошибочных переводов без числа и требования | consistency | №09 |
| qr_clean | minor | incomplete | Экран получателя не описывает ошибки ввода суммы и отказ сервиса | lens:analyst | №05 |
| qr_clean | minor | incomplete | Экран отправителя не описывает ввод суммы для QR без суммы | lens:qa | №06 |
| qr_clean | minor | traceability | Функциональные требования и пункты API без ID и приоритетов | consistency | №09 |
| qr_clean | minor | ambiguity | Статус «оплачен» для QR-кода без суммы не определён | lens:analyst | №05 |
| qr_clean | minor | incomplete | Статус QR с суммой после ответа 500 не определён | consistency | №09 |
| qr_clean | minor | incomplete | Проверка и отметка оплаты QR с суммой не описаны как атомарная операция | consistency | №09 |
| qr_clean | minor | incomplete | Срок действия QR записан в двух местах | consistency | №09 |
| qr_clean | minor | ambiguity | Понятие «перевод в обработке» не выражено в статусах QR-кода | lens:analyst | №05 |
| qr_clean | minor | incomplete | Нагрузка 200 переводов в секунду без критерия успеха | lens:analyst | №05 |
| qr_clean | minor | incomplete | requestId и debit_card_id не входят в перечень хранимых данных | lens:architect | №07 |
| qr_clean | minor | terminology | Одно понятие названо по-разному, глоссария нет | consistency | №09 |
| qr_clean | minor | incomplete | Критерии приёмки покрывают 7 из 14 функциональных требований | lens:qa | №06 |
| qr_clean | minor | missing_element | Схема отката и способ скрыть функцию QR-переводов не описаны | lens:risk | №08 |
| qr_clean | minor | contradiction | Поле amount: в таблице необязательно, в логике метода обязательно | lens:architect | №07 |
| qr_clean | minor | ambiguity | «Отказ антифрода» не отделён от сбоя антифрода | lens:qa | №06 |
| qr_clean | minor | api_contract | Тела ошибок не содержат полей status, amount и recipientName | lens:architect | №07 |
| qr_clean | minor | security | Чтение данных QR-кода по qrId без проверки прав сессии | lens:risk | №08 |
