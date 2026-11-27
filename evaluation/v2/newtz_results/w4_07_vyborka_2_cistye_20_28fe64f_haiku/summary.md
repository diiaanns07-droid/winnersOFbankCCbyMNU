# Новые ТЗ №18 — W4-07 выборка 2: чистые №20, 28fe64f, haiku

Кейсов 8, прогонов 8, не измерено 0.

**Recall —** (0/0): critical 0/0, major 0/0, minor 0/0. Вне эталона 0, дублей 0, критичных ложных 0.

Чистые версии (8): замечаний 106, из них ложных (вне фона шаблона) 106: critical 3, major 16; документов с critical 2, с > 1 замечанием 8, вердикт «нельзя» 2.

Recall по типам: .

Время 34.8 мин суммарно, вызовов 75, $1.032.

| Кейс | Версия | Статус | Найдено | Замечаний (к/с/н) | Вердикт | Мин | Вызовов |
| :--- | :--- | :--- | :--- | :--- | :--- | ---: | ---: |
| capital_v2 | clean | complete | — | 15 (0/1/14) | yes/yes | 3.9 | 8 |
| fx | clean | complete | — | 10 (0/1/9) | yes/yes | 5.0 | 10 |
| grace_v2 | clean | complete | — | 14 (0/1/13) | yes/yes | 3.1 | 8 |
| insurance_v2 | clean | complete | — | 16 (1/6/9) | no/no | 4.1 | 9 |
| qr_v2 | clean | complete | — | 15 (0/0/15) | yes/yes | 2.8 | 8 |
| repay | clean | complete | — | 12 (2/5/5) | no/no | 5.4 | 11 |
| roundup | clean | complete | — | 12 (0/0/12) | yes/yes | 5.8 | 10 |
| statement | clean | complete | — | 12 (0/2/10) | yes/yes | 4.7 | 11 |

Ложные на чистых версиях:

| Кейс | Серьёзность | Тип | Замечание | Источники | Владельцы |
| :--- | :--- | :--- | :--- | :--- | :--- |
| capital_v2 | major | incomplete | Ф-6 не задаёт получателя и канал выплаты при закрытии счёта | lens:analyst, consistency, lens:risk | №05, №08, №09 |
| capital_v2 | minor | terminology | Одни и те же понятия названы разными терминами, глоссария нет | consistency | №09 |
| capital_v2 | minor | unverifiable | Цель про снижение обращений в контакт-центр не измерима | consistency | №09 |
| capital_v2 | minor | incomplete | Схема метода 1 не показывает вызов сервиса уведомлений | consistency | №09 |
| capital_v2 | minor | missing_element | Список карт для выбора на экране не получается ни одним методом | consistency | №09 |
| capital_v2 | minor | incomplete | Проверка валюты счёта из Ф-1 отсутствует в логике метода | consistency | №09 |
| capital_v2 | minor | other | Функциональные требования не имеют приоритетов | consistency | №09 |
| capital_v2 | minor | ambiguity | Значение «проценты на дату запроса» не определено для текущего дня | lens:analyst | №05 |
| capital_v2 | minor | ambiguity | Карта выплаты процентов текущего месяца не определена после смены карты | lens:risk | №08 |
| capital_v2 | minor | duplicate | Дата начала нового способа описана в пяти местах | consistency | №09 |
| capital_v2 | minor | missing_element | Критерии приёмки покрывают не все функциональные ветки | lens:qa | №06 |
| capital_v2 | minor | missing_element | Причина для push при неактивной карте не имеет источника данных | lens:architect | №07 |
| capital_v2 | minor | missing_element | Способ выплаты за прошлые месяцы не хранится для истории начислений | lens:architect | №07 |
| capital_v2 | minor | placeholder | ИБ-чек-лист, на который ссылается документ, не приведён | lens:risk | №08 |
| capital_v2 | minor | incomplete | Ответ сохранения способа не возвращает выбранную карту | lens:architect | №07 |
| fx | major | ops_risk | Котировка не блокируется до подтверждения отмены после таймаута АБС | lens:risk, lens:architect, consistency | №07, №08, №09 |
| fx | minor | unverifiable | Цель 60 % не измерима по описанным полям данных | consistency | №09 |
| fx | minor | terminology | Термин для сервиса счетов назван по-разному в двух местах | consistency | №09 |
| fx | minor | contradiction | Таймер экрана и срок котировки отсчитываются от разных моментов | lens:analyst | №05 |
| fx | minor | traceability | Экранные и API-правила не имеют идентификаторов | consistency | №09 |
| fx | minor | incomplete | Схема процесса не показывает отмену проводки при таймауте | consistency | №09 |
| fx | minor | incomplete | Критерии приёмки не покрывают границы, отказ АБС и часть правил | lens:qa | №06 |
| fx | minor | incomplete | Документ не рассматривает ряд случаев | lens:architect, consistency | №07, №09 |
| fx | minor | unverifiable | Доступность 99.9 % не определяет, что считается недоступностью | lens:qa | №06 |
| fx | minor | contradiction | Срок хранения ключа идемпотентности задан двумя моментами | consistency | №09 |
| grace_v2 | major | ambiguity | Период, возвращаемый при невыпущенной выписке, определён двумя способами | lens:analyst, consistency | №05, №09 |
| grace_v2 | minor | terminology | Одни и те же объекты названы разными терминами | consistency | №09 |
| grace_v2 | minor | ambiguity | Момент перехода статуса в LOST до окончания периода не определён | lens:analyst | №05 |
| grace_v2 | minor | traceability | Требования без ID и приоритетов | consistency | №09 |
| grace_v2 | minor | ambiguity | Порядок погашения платежа между покупками и наличными не задан | lens:analyst | №05 |
| grace_v2 | minor | ambiguity | Момент проверки остатка для напоминания не задан | lens:analyst | №05 |
| grace_v2 | minor | duplicate | Дата напоминания 22-го числа повторена в трёх местах | consistency | №09 |
| grace_v2 | minor | missing_element | Отмена внесённого платежа не описана | consistency | №09 |
| grace_v2 | minor | incomplete | Метод включения напоминания не показан на sequence-диаграмме | consistency | №09 |
| grace_v2 | minor | incomplete | Критерии приёмки покрывают не все функциональные требования | lens:qa | №06 |
| grace_v2 | minor | unit_mismatch | Суммы в критерии приёмки в тенге, в API в тиынах без пересчёта | lens:architect | №07 |
| grace_v2 | minor | unverifiable | Ссылки на чек-листы ИБ и архитектуры без самих чек-листов | lens:risk | №08 |
| grace_v2 | minor | missing_element | Прогноз процентов не получает покупки с датами и ставку тарифа | lens:architect | №07 |
| grace_v2 | minor | unverifiable | Округление и подсчёт дней для прогноза процентов не заданы | lens:analyst | №05 |
| insurance_v2 | critical | contradiction | Отказ после полного погашения: успех в Ф-4 и 409 в методе 3 | consistency | №09 |
| insurance_v2 | major | missing_element | Досрочное погашение не передаётся в сервис страхования и нет в BPMN | lens:architect, consistency | №07, №09 |
| insurance_v2 | major | missing_element | Обмен со страховой компанией-партнёром не описан: проверка, полис, номер | lens:architect | №07 |
| insurance_v2 | major | contradiction | Повтор подключения у подписанной заявки: условия или 409 | consistency | №09 |
| insurance_v2 | major | missing_element | Возврат премии не показан в архитектуре и последовательности | consistency | №09 |
| insurance_v2 | major | missing_element | Статусы полиса после отказа и досрочного погашения не перечислены | consistency | №09 |
| insurance_v2 | major | api_contract | Пример тела 400 описывает только диапазон, хотя код покрывает согласие | lens:architect | №07 |
| insurance_v2 | minor | incomplete | Приоритеты требований и признак стабильности не указаны | consistency | №09 |
| insurance_v2 | minor | unverifiable | Цель «без жалоб» и «доля кредитов» не имеют измеримого показателя | consistency | №09 |
| insurance_v2 | minor | terminology | Одни и те же компоненты названы разными именами; глоссария нет | consistency | №09 |
| insurance_v2 | minor | incomplete | Критерии приёмки не покрывают границы, возраст, повторы и отказ | lens:qa | №06 |
| insurance_v2 | minor | ambiguity | Не сказано, какая ставка действует в день отказа | lens:analyst | №05 |
| insurance_v2 | minor | duplicate | Ставка 27 % после отказа записана в двух местах | consistency | №09 |
| insurance_v2 | minor | unverifiable | Нагрузка и период измерения для порога 2 с не заданы | lens:analyst | №05 |
| insurance_v2 | minor | incomplete | Поля запроса не перечислены в данных; pd_consent_at неоднозначен | lens:architect | №07 |
| insurance_v2 | minor | ambiguity | Повтор запроса после снятия страхования 422: ответ не определён | lens:analyst | №05 |
| qr_v2 | minor | missing_element | Ни одно требование документа не имеет приоритета | consistency | №09 |
| qr_v2 | minor | unverifiable | Цель по снижению ошибочных переводов не имеет показателя | consistency | №09 |
| qr_v2 | minor | terminology | Термины карт, срока и компонентов не едины, глоссария нет | consistency | №09 |
| qr_v2 | minor | missing_element | Список карт и данные карт для экранов не описаны методами | consistency | №09 |
| qr_v2 | minor | ambiguity | Ф-2 не определяет, какая ошибка возвращает QR к оплате | lens:analyst | №05 |
| qr_v2 | minor | missing_element | Состояние «перевод в обработке» не описано в статусах | lens:architect | №07 |
| qr_v2 | minor | ambiguity | Параллельные запросы по QR с суммой могут дать двойной перевод | consistency | №09 |
| qr_v2 | minor | contradiction | Вызов перевода в последовательности минует сервис QR-кодов | lens:architect | №07 |
| qr_v2 | minor | incomplete | Схема API не показывает сервис уведомлений и создание QR | consistency | №09 |
| qr_v2 | minor | unverifiable | Нагрузочное требование не связано с временем ответа и долей | lens:analyst | №05 |
| qr_v2 | minor | missing_element | Ключ идемпотентности и результат перевода не в перечне данных | lens:architect | №07 |
| qr_v2 | minor | duplicate | Правило повтора requestId записано в двух местах | consistency | №09 |
| qr_v2 | minor | incomplete | Критерии приёмки покрывают не все функциональные требования | lens:qa | №06 |
| qr_v2 | minor | missing_element | Чек-лист ИБ упомянут, но в документе не приложен | lens:risk | №08 |
| qr_v2 | minor | ambiguity | Порядок проверки requestId относительно шагов 2–8 не задан | lens:analyst, lens:architect, consistency | №05, №07, №09 |
| repay | critical | contradiction | Статус «не найдена» после 500: отказ или повторная проводка | lens:qa, lens:architect, consistency | №06, №07, №09 |
| repay | critical | contradiction | Повтор с тем же ключом после 422 даёт и отказ, и успех | consistency, lens:architect | №07, №09 |
| repay | major | contradiction | Платёж считается по i = ставка/12, проценты графика по Ф-3 | lens:analyst | №05 |
| repay | major | missing_element | Дата выдачи не входит в ответ АБС, нужна для процентов | lens:analyst, lens:architect | №05, №07 |
| repay | major | ops_risk | Операция «в обработке» сверяется без предела по времени | lens:risk | №08 |
| repay | major | contradiction | Повтор после 500 с истёкшим расчётом: проведение или 422 | consistency | №09 |
| repay | major | traceability | Цель 50 % погашений в приложении без учёта канала | consistency | №09 |
| repay | minor | traceability | Пункты требований без ID и приоритетов | consistency | №09 |
| repay | minor | terminology | Одни и те же понятия названы разными терминами | lens:architect, consistency | №07, №09 |
| repay | minor | incomplete | Метод 1 не проверяет флаг, выключенный флаг скрывает кнопку | consistency | №09 |
| repay | minor | missing_element | Критерии приёмки не покрывают часть ветвей ошибок | lens:qa | №06 |
| repay | minor | incomplete | Сбой доставки push в сервис уведомлений не описан | lens:architect | №07 |
| roundup | minor | other | Требования Ф-1–Ф-9 не имеют приоритета | consistency | №09 |
| roundup | minor | contradiction | Цель обещает ежедневный перевод без предела и отказов | consistency | №09 |
| roundup | minor | terminology | Одни понятия названы разными терминами без глоссария | consistency | №09 |
| roundup | minor | ambiguity | Доступность «Сохранить» при выключенном переключателе не определена | lens:analyst | №05 |
| roundup | minor | security | Дополнительная карта: владелец или держатель настраивает копилку | lens:risk | №08 |
| roundup | minor | event_conflict | Фиксация 00:30 и 60-секундная задержка начисления расходятся | lens:analyst | №05 |
| roundup | minor | duplicate | Правило вступления месячного предела продублировано в двух местах | consistency | №09 |
| roundup | minor | unverifiable | Срок переводов 02:00 нельзя измерить: нет доли и нагрузки | lens:qa | №06 |
| roundup | minor | api_contract | Вызов перевода в сервис переводов: тело и ответ успеха не описаны | lens:architect | №07 |
| roundup | minor | incomplete | Документ не рассматривает ряд случаев | lens:architect | №07 |
| roundup | minor | ambiguity | Перечень кодов отказа закрыт словами «и другие» | rules:language.open_list | №12 |
| roundup | minor | missing_element | Критерии приёмки не покрывают границы и ошибки из плана тестов | lens:qa | №06 |
| statement | major | missing_element | Коды 200 и 410 используются, но не входят в перечень статусов | rules:api.status_410, consistency, rules:api.status_200 | №09, №12 |
| statement | major | ambiguity | Критерий приёмки №22 не задаёт дату выдачи ссылки | lens:qa | №06 |
| statement | minor | contradiction | Канал передачи READY/FAILED от генератора PDF не описан в архитектуре | lens:architect | №07 |
| statement | minor | terminology | Одни и те же роли и компоненты названы разными терминами | consistency | №09 |
| statement | minor | contradiction | Схема метода показывает прямой вызов мимо шлюза и без скачивания | consistency | №09 |
| statement | minor | missing_element | Флаг statement_pdf для отката обещан, но не описан | consistency | №09 |
| statement | minor | incomplete | Документ не рассматривает ряд случаев | consistency, lens:analyst | №05, №09 |
| statement | minor | incomplete | Ф-1 требует физлицо, но логика метода 1 этого не проверяет | lens:architect | №07 |
| statement | minor | missing_element | Требования не имеют приоритетов | consistency | №09 |
| statement | minor | missing_element | Обороты по дебету и кредиту не выводятся из ответа АБС | lens:architect | №07 |
| statement | minor | duplicate | Срок ссылки 15 минут продублирован в Ф-6 и в API | consistency | №09 |
| statement | minor | incomplete | Критерии приёмки не покрывают часть границ и ошибок | lens:qa | №06 |
