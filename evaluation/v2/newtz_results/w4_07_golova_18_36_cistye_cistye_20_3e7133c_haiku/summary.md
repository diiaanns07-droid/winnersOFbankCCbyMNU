# Новые ТЗ №18 — W4-07 голова 18:36 чистые: чистые №20, 3e7133c, haiku

Кейсов 8, прогонов 8, не измерено 0.

**Recall —** (0/0): critical 0/0, major 0/0, minor 0/0. Вне эталона 0, дублей 0, критичных ложных 0.

Чистые версии (8): замечаний 115, из них ложных (вне фона шаблона) 115: critical 3, major 22; документов с critical 3, с > 1 замечанием 8, вердикт «нельзя» 3.

Recall по типам: .

Время 39.4 мин суммарно, вызовов 75, $1.064.

| Кейс | Версия | Статус | Найдено | Замечаний (к/с/н) | Вердикт | Мин | Вызовов |
| :--- | :--- | :--- | :--- | :--- | :--- | ---: | ---: |
| capital_v2 | clean | complete | — | 15 (0/0/15) | yes/yes | 5.3 | 8 |
| fx | clean | complete | — | 13 (0/1/12) | yes/yes | 5.7 | 9 |
| grace_v2 | clean | complete | — | 18 (1/7/10) | no/no | 3.9 | 9 |
| insurance_v2 | clean | complete | — | 19 (0/1/18) | yes/yes | 4.0 | 8 |
| qr_v2 | clean | complete | — | 14 (0/1/13) | yes/yes | 3.1 | 8 |
| repay | clean | complete | — | 15 (1/8/6) | no/no | 6.5 | 11 |
| roundup | clean | complete | — | 11 (0/0/11) | yes/yes | 5.9 | 10 |
| statement | clean | complete | — | 10 (1/4/5) | no/no | 5.2 | 12 |

Ложные на чистых версиях:

| Кейс | Серьёзность | Тип | Замечание | Источники | Владельцы |
| :--- | :--- | :--- | :--- | :--- | :--- |
| capital_v2 | minor | traceability | Пункты требований без ID и приоритетов | consistency | №09 |
| capital_v2 | minor | unverifiable | Цель снизить обращения в контакт-центр не измерима | consistency | №09 |
| capital_v2 | minor | incomplete | Документ не рассматривает ряд случаев | consistency, lens:analyst | №05, №09 |
| capital_v2 | minor | terminology | Одни и те же компоненты и карта названы разными терминами | consistency | №09 |
| capital_v2 | minor | incomplete | Проверка валюты счёта из Ф-1 отсутствует в логике метода | lens:architect | №07 |
| capital_v2 | minor | incomplete | Получатель процентов при закрытии счёта на способе «На карту» не задан | lens:analyst | №05 |
| capital_v2 | minor | ambiguity | Карта выплаты при смене способа в середине месяца не определена | consistency | №09 |
| capital_v2 | minor | duplicate | Правило даты 1-го числа продублировано в логике метода | consistency | №09 |
| capital_v2 | minor | missing_element | Причина замены выплаты на карту не передаётся в push | lens:architect | №07 |
| capital_v2 | minor | missing_element | Режим выплаты по прошедшим месяцам не хранится | lens:architect | №07 |
| capital_v2 | minor | missing_element | Критерии приёмки покрывают 4 из 12 функциональных требований | lens:qa | №06 |
| capital_v2 | minor | unverifiable | Отметка ИБ «Да» без доступной проверки в комплекте | lens:risk | №08 |
| capital_v2 | minor | contradiction | Повторный выбор CARD с заблокированной картой: 200 или 400 | lens:qa | №06 |
| capital_v2 | minor | contradiction | Чужая карта при CAPITALIZATION: особое правило и статус 404 расходятся | consistency | №09 |
| capital_v2 | minor | incomplete | Закрытый счёт в методе 2: ответ 404 не описан | consistency | №09 |
| fx | major | missing_element | Неподтверждённая отмена проводки не имеет состояния и выхода | lens:risk, lens:architect | №07, №08 |
| fx | minor | other | Все требования с одинаковым приоритетом без порядка отсечения | consistency | №09 |
| fx | minor | unverifiable | Цель 60 % не имеет признака канала для измерения | consistency | №09 |
| fx | minor | terminology | Название сервиса счетов в данных расходится: «данные счёта» и «данные счетов» | consistency | №09 |
| fx | minor | incomplete | BPMN не показывает ветвь отмены проводки при таймауте | consistency | №09 |
| fx | minor | missing_element | Критерии приёмки не покрывают ряд веток и курсов | lens:qa | №06 |
| fx | minor | ambiguity | Повтор push после ошибки уведомлений не согласован с «один push» | consistency | №09 |
| fx | minor | unverifiable | Недоступность методов не определена и не измеряется | lens:qa | №06 |
| fx | minor | other | Срок хранения ключа 24 часа записан в двух местах | consistency | №09 |
| fx | minor | api_contract | Формат параметра даты календаря АБС не задан | lens:architect | №07 |
| fx | minor | incomplete | Выключение пункта меню не определяет судьбу активных котировок | consistency | №09 |
| fx | minor | traceability | Шаги логики и строки кодов ответа без идентификаторов | consistency | №09 |
| fx | minor | api_contract | Пример тела 404 задаёт код метода 1 для метода 2 | lens:architect, consistency | №07, №09 |
| grace_v2 | critical | event_conflict | Платежи до выписки: сумма погашения считается по-разному | lens:analyst | №05 |
| grace_v2 | major | ambiguity | Возврат до выписки может уменьшить сумму погашения дважды | consistency | №09 |
| grace_v2 | major | ambiguity | Переплата: Ф-3 не задаёт проценты при отрицательной сумме | lens:analyst | №05 |
| grace_v2 | major | contradiction | Прогноз процентов: разные условия в логике и в описании поля | lens:architect | №07 |
| grace_v2 | major | incomplete | Значения после 25-го числа до новой выписки не определены | lens:analyst | №05 |
| grace_v2 | major | missing_element | Прогноз процентов: ставка и покупки не входят в данные метода | lens:architect | №07 |
| grace_v2 | major | status_conflict | Коды ответа методов 1 и 2 различаются по ошибке параметра | lens:qa | №06 |
| grace_v2 | major | incomplete | Судьба процентов по возврату после утраты периода не задана | lens:analyst | №05 |
| grace_v2 | minor | unverifiable | Цель не имеет числового показателя и базового значения | consistency | №09 |
| grace_v2 | minor | terminology | Терминология не едина: компонент API и названия сумм и признака | lens:architect, consistency | №07, №09 |
| grace_v2 | minor | incomplete | Документ не рассматривает ряд случаев | lens:analyst, consistency | №05, №09 |
| grace_v2 | minor | other | Приоритеты функциональных требований не указаны | consistency | №09 |
| grace_v2 | minor | duplicate | Правило процентов повторено в Ф-3 и особом правиле API | consistency | №09 |
| grace_v2 | minor | ambiguity | Проверка остатка и окно отправки напоминания не совпадают | lens:analyst | №05 |
| grace_v2 | minor | non_singular | Ф-5 объединяет пять независимых правил в одном пункте | lens:analyst | №05 |
| grace_v2 | minor | missing_element | Отметка ИБ опирается на чек-лист, которого нет в документе | lens:risk | №08 |
| grace_v2 | minor | missing_element | Приёмка покрывает 4 из 11 функциональных требований | lens:qa | №06 |
| grace_v2 | minor | incomplete | Схема вызовов не показывает метод переключения напоминания | consistency | №09 |
| insurance_v2 | major | incomplete | Статусы метода 5 не заданы для отказа, погашения и без страхования | lens:architect, consistency | №07, №09 |
| insurance_v2 | minor | terminology | Одни и те же компоненты и статусы названы по-разному | consistency | №09 |
| insurance_v2 | minor | incomplete | Архитектура связывает API с конвейером, схема вызова этого не показывает | consistency | №09 |
| insurance_v2 | minor | incomplete | Экран полиса не описывает вид до выпуска полиса | lens:analyst | №05 |
| insurance_v2 | minor | incomplete | Нет ветки, если полис не выпущен после списания премии | lens:risk | №08 |
| insurance_v2 | minor | other | Функциональные требования не имеют приоритетов | consistency | №09 |
| insurance_v2 | minor | ambiguity | Не определено, уменьшает ли премия сумму выдачи или входит в долг | lens:analyst | №05 |
| insurance_v2 | minor | api_contract | Поле refundUntil в ответе отказа не описано | lens:architect | №07 |
| insurance_v2 | minor | duplicate | Правило ставки 27 % после отказа продублировано | consistency | №09 |
| insurance_v2 | minor | missing_element | Поля срока и согласия не перечислены в требованиях к данным | lens:architect | №07 |
| insurance_v2 | minor | security | Отметка ИБ «Да» не согласуется с передачей ПДн партнёру | lens:risk | №08 |
| insurance_v2 | minor | incomplete | Критерии приёмки не покрывают границы, ошибки и повторы | lens:qa | №06 |
| insurance_v2 | minor | missing_element | Сумма возврата при досрочном погашении не отдаётся ни одним методом | lens:architect | №07 |
| insurance_v2 | minor | contradiction | Повтор вызова после подписания: условия или ошибка 409 | lens:analyst, lens:architect | №05, №07 |
| insurance_v2 | minor | ambiguity | Состояние заявки при отказе страховщика на первом вызове неоднозначно | lens:qa | №06 |
| insurance_v2 | minor | incomplete | Ответы 400 и 422 не сообщают, что страхование снято | lens:architect | №07 |
| insurance_v2 | minor | incomplete | Особое правило п. 2 не задаёт исход при ошибке 502 на повторе | consistency | №09 |
| insurance_v2 | minor | api_contract | Код 422 описан только текстом возраста, отказ страховщика не отражён | lens:architect | №07 |
| insurance_v2 | minor | status_conflict | Тело 409 для отказа от страхования говорит о подписании заявки | lens:architect | №07 |
| qr_v2 | major | contradiction | Путь вызова перевода по QR расходится в трёх местах | lens:architect, consistency | №07, №09 |
| qr_v2 | minor | traceability | У требований нет ID и приоритетов | consistency | №09 |
| qr_v2 | minor | unverifiable | Цель по снижению ошибочных переводов не измерима | consistency | №09 |
| qr_v2 | minor | terminology | Одни и те же понятия названы разными терминами | consistency, lens:analyst | №05, №09 |
| qr_v2 | minor | incomplete | Критерии приёмки покрывают 7 из 15 функциональных требований | lens:qa | №06 |
| qr_v2 | minor | ambiguity | Параллельные оплаты QR с суммой не имеют определённого исхода | consistency | №09 |
| qr_v2 | minor | duplicate | Срок действия QR описан в двух местах | consistency | №09 |
| qr_v2 | minor | missing_element | Состояние «перевод в обработке» отсутствует в статусах QR-кода | lens:architect | №07 |
| qr_v2 | minor | incomplete | Отмена QR-кода не показана на схеме последовательности | consistency | №09 |
| qr_v2 | minor | missing_element | requestId не входит в перечень хранимых данных | lens:architect | №07 |
| qr_v2 | minor | ops_risk | requestId не привязан к отправителю и параметрам запроса | lens:risk | №08 |
| qr_v2 | minor | ambiguity | Порядок проверок при повторе requestId не задан | lens:analyst | №05 |
| qr_v2 | minor | api_contract | Тела ошибок в примерах не совпадают с таблицей ответа | lens:architect | №07 |
| qr_v2 | minor | security | Данные QR-кода доступны любому клиенту без проверки владельца | lens:risk | №08 |
| repay | critical | contradiction | Повтор после 422 при «проведена» — 200 или отказ | lens:qa, lens:architect, lens:risk | №06, №07, №08 |
| repay | major | contradiction | Сверка каждые 5 минут противоречит сроку DONE 5 минут | consistency | №09 |
| repay | major | missing_element | Флаг показа кнопки не читается ни одним методом | lens:architect, consistency | №07, №09 |
| repay | major | incomplete | Повтор ключа в статусе PROCESSING не описан | consistency | №09 |
| repay | major | ambiguity | База процентов в графике: 360 дней или 12 месяцев | consistency | №09 |
| repay | major | api_contract | Ответы АБС на расчёт, проведение и статус не описаны | lens:architect | №07 |
| repay | major | ambiguity | Дата платежа на выходной: перенос срока не описан | lens:risk | №08 |
| repay | major | unverifiable | Цель 50 % мобильных погашений нельзя измерить по данным | consistency | №09 |
| repay | major | incomplete | Коды 400, 401, 404, 409: поведение приложения не описано | lens:architect | №07 |
| repay | minor | traceability | Нет приоритетов и ID у НФТ, данных и интеграции | consistency | №09 |
| repay | minor | terminology | Клиентский компонент назван тремя разными именами | lens:architect, consistency | №07, №09 |
| repay | minor | incomplete | Область действия флага кнопки не определена | lens:analyst | №05 |
| repay | minor | incomplete | Схемы не показывают методы 2–3 и ветку UNKNOWN | consistency | №09 |
| repay | minor | ambiguity | Предусловие «достаточно средств» не задано числом | lens:analyst | №05 |
| repay | minor | missing_element | Приёмка покрывает 15 из 19 функциональных требований | lens:qa | №06 |
| roundup | minor | terminology | Термины компонентов, счёта и копилки не едины, глоссария нет | consistency | №09 |
| roundup | minor | contradiction | Цель «ежедневно переводится» расходится с месячным пределом и отказами | consistency | №09 |
| roundup | minor | contradiction | Архитектура не показывает контроллер и хранилище из схемы API | consistency | №09 |
| roundup | minor | ambiguity | Кнопка «Сохранить» при выключенном переключателе не определена | lens:analyst | №05 |
| roundup | minor | other | Пункты требований без ID и приоритетов | consistency | №09 |
| roundup | minor | security | Владелец и держатель карты не различены: кто вправе подключить копилку | lens:risk | №08 |
| roundup | minor | ambiguity | Сумма покупки в иностранной валюте: курсовая наценка не отнесена | lens:analyst | №05 |
| roundup | minor | duplicate | Правило о смене счёта и предела продублировано в двух разделах | consistency | №09 |
| roundup | minor | api_contract | Тела вызовов переводов и push не описаны в И-4 и на схеме | lens:architect | №07 |
| roundup | minor | unverifiable | Норматив push «не позже 5 минут» без доли случаев и нагрузки | lens:qa | №06 |
| roundup | minor | incomplete | Критерии приёмки не покрывают границы, ошибки и повторы | lens:qa | №06 |
| statement | critical | boundary_conflict | Критерий приёмки L079 противоречит Ф-6 по сроку ссылки | lens:analyst, lens:qa, lens:architect | №05, №06, №07 |
| statement | major | incomplete | Файл, сохранённый после 30 минут: порядок READY и FAILED не задан | consistency | №09 |
| statement | major | security | Токен скачивания передаётся в пути URL без сессии клиента | lens:risk | №08 |
| statement | major | incomplete | Архитектура не содержит возврата статуса от генератора PDF | consistency | №09 |
| statement | major | unverifiable | Цель снизить обращения на 30 % не измеряется данными системы | consistency | №09 |
| statement | minor | other | Пункты без ID и приоритетов; порядок отсечения не задан | consistency | №09 |
| statement | minor | terminology | Одни понятия названы разными терминами без глоссария | consistency | №09 |
| statement | minor | incomplete | Судьба READY-выписки при закрытии счёта не описана | consistency | №09 |
| statement | minor | duplicate | Лимит 366 дней задан в Ф-2 и в особых правилах API | consistency | №09 |
| statement | minor | incomplete | Критерии приёмки не покрывают часть правил Ф-1 — Ф-8 | lens:qa | №06 |
