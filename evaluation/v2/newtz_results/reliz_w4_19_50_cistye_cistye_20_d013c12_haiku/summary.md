# Новые ТЗ №18 — релиз-w4 19:50 чистые: чистые №20, d013c12, haiku

Кейсов 8, прогонов 8, не измерено 0.

**Recall —** (0/0): critical 0/0, major 0/0, minor 0/0. Вне эталона 0, дублей 0, критичных ложных 0.

Чистые версии (8): замечаний 124, из них ложных (вне фона шаблона) 124: critical 3, major 18; документов с critical 3, с > 1 замечанием 8, вердикт «нельзя» 3.

Recall по типам: .

Время 37.7 мин суммарно, вызовов 75, $1.06.

| Кейс | Версия | Статус | Найдено | Замечаний (к/с/н) | Вердикт | Мин | Вызовов |
| :--- | :--- | :--- | :--- | :--- | :--- | ---: | ---: |
| capital_v2 | clean | complete | — | 17 (0/1/16) | yes/yes | 4.4 | 8 |
| fx | clean | complete | — | 11 (0/2/9) | yes/yes | 5.2 | 10 |
| grace_v2 | clean | complete | — | 17 (0/0/17) | yes/yes | 5.2 | 8 |
| insurance_v2 | clean | complete | — | 19 (0/0/19) | yes/yes | 3.2 | 8 |
| qr_v2 | clean | complete | — | 17 (0/0/17) | yes/yes | 3.0 | 8 |
| repay | clean | complete | — | 14 (1/6/7) | no/no | 5.9 | 11 |
| roundup | clean | complete | — | 14 (1/4/9) | no/yes | 5.8 | 11 |
| statement | clean | complete | — | 15 (1/5/9) | conditional/no | 5.0 | 11 |

Ложные на чистых версиях:

| Кейс | Серьёзность | Тип | Замечание | Источники | Владельцы |
| :--- | :--- | :--- | :--- | :--- | :--- |
| capital_v2 | major | incomplete | Ф-6 не задаёт получателя и способ выплаты при закрытии счёта | consistency, lens:analyst, lens:qa | №05, №06, №09 |
| capital_v2 | minor | terminology | Одни и те же понятия названы разными терминами | consistency, lens:architect | №07, №09 |
| capital_v2 | minor | traceability | Требования и методы API без ID и приоритетов | consistency | №09 |
| capital_v2 | minor | incomplete | Экран «Проценты» без состояний для отсутствия карт и ошибок | lens:analyst | №05 |
| capital_v2 | minor | missing_element | Список карт клиента для экрана нигде не получается | consistency | №09 |
| capital_v2 | minor | incomplete | Метод 2 не отдаёт дату вступления следующего способа | consistency | №09 |
| capital_v2 | minor | incomplete | Проверка счёта в тенге из Ф-1 отсутствует в логике метода | lens:architect | №07 |
| capital_v2 | minor | ambiguity | Карта выплаты за месяц не определена при смене карты в месяце | lens:analyst | №05 |
| capital_v2 | minor | duplicate | Правило даты вступления записано в двух местах | consistency | №09 |
| capital_v2 | minor | ambiguity | Ф-4 не описывает остаток ровно 1 000 ₸ | lens:analyst | №05 |
| capital_v2 | minor | incomplete | Критерии приёмки покрывают 5 из 12 функциональных требований | lens:qa | №06 |
| capital_v2 | minor | incomplete | Схема вызова не показывает методы чтения 2 и 3 | consistency | №09 |
| capital_v2 | minor | unverifiable | Нагрузка не задана для требования времени ответа API | lens:analyst | №05 |
| capital_v2 | minor | incomplete | Метод истории отдаёт способ по месяцам, которого нет в данных | lens:architect | №07 |
| capital_v2 | minor | incomplete | Несуществующая карта: код ответа не задан, тело ошибки 404 | lens:architect | №07 |
| capital_v2 | minor | ambiguity | Порядок проверок при повторе способа и неактивной карте | consistency | №09 |
| capital_v2 | minor | incomplete | Для закрытого счёта методы чтения не задают ответ 404 | lens:architect | №07 |
| fx | major | contradiction | Параллельные запросы метода 1 по одной котировке дают две проводки | lens:architect, consistency | №07, №09 |
| fx | major | ops_risk | Неподтверждённая отмена проводки не имеет исхода и статуса | lens:risk, lens:architect | №07, №08 |
| fx | minor | terminology | Название приложения и сервиса счетов не едины по документу | consistency | №09 |
| fx | minor | other | Все требования с одним приоритетом без очерёдности внутри релиза | consistency | №09 |
| fx | minor | unverifiable | Цель 60 % по данным АБС без требования их формировать | consistency | №09 |
| fx | minor | event_conflict | Таймер котировки стартует от ответа приложения, а не от expiresAt | lens:analyst | №05 |
| fx | minor | incomplete | Выключение пункта меню не отключает методы и активные котировки | consistency | №09 |
| fx | minor | duplicate | Правило отмены проводки продублировано в трёх местах | consistency | №09 |
| fx | minor | unverifiable | НФ-3: «круглосуточно» и точка замера доступности не заданы | lens:qa | №06 |
| fx | minor | traceability | НФ-2–НФ-5 и Д-2–Д-4 нет в таблице требований | consistency | №09 |
| fx | minor | api_contract | Пример тела 404 не совпадает с errorCode счёта в методе 2 | lens:architect | №07 |
| grace_v2 | minor | unverifiable | Цель без измеримого показателя и срока | consistency | №09 |
| grace_v2 | minor | terminology | Одни и те же объекты названы по-разному | consistency | №09 |
| grace_v2 | minor | incomplete | Экран льготного периода без начальных и пустых состояний | lens:analyst, lens:qa | №05, №06 |
| grace_v2 | minor | ambiguity | Счёт дней до окончания периода не определён | lens:analyst | №05 |
| grace_v2 | minor | missing_element | Кнопка «Пополнить» без описанного действия | consistency | №09 |
| grace_v2 | minor | non_singular | Пункты Ф-1 и Ф-5 объединяют несколько независимых правил | lens:analyst | №05 |
| grace_v2 | minor | ambiguity | Предыдущий период без выписки определён неоднозначно | consistency | №09 |
| grace_v2 | minor | other | Функциональные требования Ф-1–Ф-5 без приоритета | consistency | №09 |
| grace_v2 | minor | duplicate | Правило начисления процентов повторено в нескольких местах | consistency | №09 |
| grace_v2 | minor | unit_mismatch | Единица суммы в push-напоминании не задана | lens:analyst | №05 |
| grace_v2 | minor | ambiguity | Момент проверки остатка в окне напоминания не задан | lens:analyst | №05 |
| grace_v2 | minor | incomplete | Включение напоминания после 22-го числа не описано | consistency | №09 |
| grace_v2 | minor | missing_element | Прогноз процентов нельзя рассчитать из получаемых данных | lens:architect | №07 |
| grace_v2 | minor | incomplete | Критерии приёмки покрывают малую часть правил | lens:qa | №06 |
| grace_v2 | minor | ambiguity | Значения в промежутке без выписки не определены | lens:analyst | №05 |
| grace_v2 | minor | incomplete | Схема API не показывает метод отключения напоминания | consistency | №09 |
| grace_v2 | minor | status_conflict | Код 400 метода 2 не отнесён к успеху или отказу | lens:qa | №06 |
| insurance_v2 | minor | terminology | Одни и те же понятия названы по-разному, глоссария нет | consistency | №09 |
| insurance_v2 | minor | other | Не у всех требований есть ID и приоритет | consistency | №09 |
| insurance_v2 | minor | unverifiable | Цель про жалобы и долю кредитов не измерима требованием | consistency | №09 |
| insurance_v2 | minor | incomplete | Схема вызова API не показывает конвейер и уведомления | consistency | №09 |
| insurance_v2 | minor | incomplete | Экран условий не описывает пустой ввод и ошибки | lens:qa | №06 |
| insurance_v2 | minor | incomplete | Ошибка выдачи после подписания не описана | consistency | №09 |
| insurance_v2 | minor | ops_risk | Повторная доставка события «кредит выдан» не определена | lens:risk | №08 |
| insurance_v2 | minor | missing_element | Для отказа и возврата нет данных о досрочном погашении | lens:architect | №07 |
| insurance_v2 | minor | duplicate | Возрастное правило Ф-6 продублировано в логике метода | consistency | №09 |
| insurance_v2 | minor | incomplete | Поля согласия, статуса и суммы не перечислены в данных | lens:architect | №07 |
| insurance_v2 | minor | incomplete | Критерии приёмки покрывают четыре строки из многих правил | lens:qa | №06 |
| insurance_v2 | minor | missing_element | Сведения о страховании не показывают состояние после возврата | lens:architect | №07 |
| insurance_v2 | minor | contradiction | Повторный вызов на подписанной заявке: 200 или 409 | lens:qa | №06 |
| insurance_v2 | minor | missing_element | Снятие страхования при ошибке повтора не записано в логике метода | lens:architect | №07 |
| insurance_v2 | minor | ambiguity | Порядок проверок возраста и согласия задан только шагами | consistency | №09 |
| insurance_v2 | minor | incomplete | Состояние заявки после 502 на первом вызове не задано | lens:qa | №06 |
| insurance_v2 | minor | api_contract | Тексты ошибок 400 и 422 не отражают все условия | lens:architect | №07 |
| insurance_v2 | minor | incomplete | Повтор после отказа: ставка и наличие страхования не заданы | lens:architect | №07 |
| insurance_v2 | minor | incomplete | Код 502 при повторном вызове не имеет исхода | consistency | №09 |
| qr_v2 | minor | unverifiable | Цель снижения ошибочных переводов не имеет показателя | consistency | №09 |
| qr_v2 | minor | contradiction | Схема последовательности обходит сервис QR-кодов при переводе | consistency | №09 |
| qr_v2 | minor | missing_element | Схема API не показывает вызов сервиса уведомлений | consistency | №09 |
| qr_v2 | minor | incomplete | Экран получателя не описывает ошибки поля суммы | lens:analyst | №05 |
| qr_v2 | minor | other | Функциональные требования без приоритетов и идентификаторов | consistency | №09 |
| qr_v2 | minor | ambiguity | Момент «принял в обработку» для статуса оплаты не определён | lens:analyst | №05 |
| qr_v2 | minor | ambiguity | Повторная оплата QR с суммой после отказа по недостатку средств | consistency, lens:qa | №06, №09 |
| qr_v2 | minor | incomplete | Параллельные оплаты QR с суммой не защищены от двойной оплаты | consistency | №09 |
| qr_v2 | minor | duplicate | Срок 15 минут продублирован в Ф-2 и особых правилах | consistency | №09 |
| qr_v2 | minor | terminology | Одни понятия названы разными терминами без глоссария | consistency | №09 |
| qr_v2 | minor | unverifiable | Нагрузка 200 переводов/с без критерия успешности | lens:analyst | №05 |
| qr_v2 | minor | missing_element | Ключ requestId и результат первого перевода не в перечне данных | lens:architect | №07 |
| qr_v2 | minor | missing_element | Критерии приёмки не покрывают ветки ошибок и границы | lens:qa | №06 |
| qr_v2 | minor | incomplete | Порядок проверки requestId не назван в шагах логики метода | lens:analyst, lens:architect | №05, №07 |
| qr_v2 | minor | contradiction | Поле amount: необязательно в таблице и обязательно в логике | lens:architect | №07 |
| qr_v2 | minor | security | GET данных QR-кода не проверяет владельца, раскрывает данные | lens:qa | №06 |
| qr_v2 | minor | api_contract | Поля status и amount отсутствуют в примерах тел ошибок | lens:architect | №07 |
| repay | critical | status_conflict | Статус «не найдена» после 500: REJECTED против проведения погашения | consistency | №09 |
| repay | major | ambiguity | Ф-2 и Ф-5 дают разное число платежей при уменьшении срока | lens:qa | №06 |
| repay | major | incomplete | Поведение приложения при 401 и 400 не описано | lens:analyst | №05 |
| repay | major | incomplete | Сверка UNKNOWN не имеет исхода при статусе «в обработке» | lens:risk, lens:qa | №06, №08 |
| repay | major | incomplete | Выключение флага при начатом подтверждении не описано | consistency | №09 |
| repay | major | contradiction | Повтор после 422 с тем же ключом может вернуть 200 | lens:architect | №07 |
| repay | major | unverifiable | Цель 50 % по каналу не подкреплена учётом канала | consistency | №09 |
| repay | minor | traceability | У большинства требований нет ID и приоритетов | consistency | №09 |
| repay | minor | terminology | Один клиентский компонент назван тремя разными терминами | lens:architect, consistency | №07, №09 |
| repay | minor | duplicate | Правило повтора с ключом продублировано в двух разделах | consistency | №09 |
| repay | minor | incomplete | Схемы процесса и вызова без ветви ответа 500 и сверки | consistency | №09 |
| repay | minor | incomplete | Критерии приёмки не покрывают часть требований | lens:qa | №06 |
| repay | minor | incomplete | Сбой отправки push после 200 не описан | lens:architect | №07 |
| repay | minor | incomplete | Повтор с ключом во время обработки не описан явно | lens:architect | №07 |
| roundup | critical | contradiction | Сохранение настроек при выключении: Ф-8 и правило 2 противоречат | lens:analyst, consistency | №05, №09 |
| roundup | major | security | Не определено, кто вправе настраивать копилку: держатель или владелец | lens:risk | №08 |
| roundup | major | incomplete | Несколько частичных возвратов по покупке не описаны в данных | lens:architect | №07 |
| roundup | major | incomplete | Экран «Копилка» не описывает ответы 401 и 404 | lens:analyst | №05 |
| roundup | major | unverifiable | Цель 30 000 карт не обеспечена ни одним требованием | consistency | №09 |
| roundup | minor | terminology | Одни и те же понятия названы разными терминами | consistency, lens:analyst | №05, №09 |
| roundup | minor | incomplete | Момент обновления показателей экрана «Копилка» не описан | lens:qa | №06 |
| roundup | minor | incomplete | Схемы процесса и взаимодействий не показывают повтор и возврат | consistency | №09 |
| roundup | minor | traceability | Требования, строки приёмки и пункты логики без ID и приоритетов | consistency | №09 |
| roundup | minor | incomplete | Критерии приёмки не покрывают границы, предел и повторы | lens:qa | №06 |
| roundup | minor | ambiguity | Покупка до полуночи, событие после 00:30: судьба не определена | lens:risk | №08 |
| roundup | minor | ambiguity | Фиксация 00:30 и срок начисления по НФ-1 не согласованы | lens:qa | №06 |
| roundup | minor | api_contract | Ответ и повтор push-уведомления не описаны | lens:architect | №07 |
| roundup | minor | unverifiable | Срок переводов по НФ-3 не измерим без точки замера и доли | lens:qa | №06 |
| statement | critical | boundary_conflict | Срок ссылки при fileExpiresAt: Ф-6 и строка приёмки 22 расходятся | consistency, lens:qa | №06, №09 |
| statement | major | ambiguity | Отсчёт 7 суток до EXPIRED: от формирования или от READY | consistency | №09 |
| statement | major | missing_element | Ответ АБС без признака дебета и кредита: знак списаний неясен | lens:architect | №07 |
| statement | major | incomplete | Не определено скачивание выписки после закрытия счёта | consistency | №09 |
| statement | major | security | Метод 5 отдаёт ПДн клиента по ссылке без сессии | lens:risk | №08 |
| statement | major | unverifiable | Цель снизить обращения на 30 % не измеряется требованиями | consistency | №09 |
| statement | minor | terminology | Один компонент и одно приложение названы разными терминами | consistency | №09 |
| statement | minor | incomplete | Схема вызова метода 1 не показывает файловое хранилище и метод 5 | consistency | №09 |
| statement | minor | incomplete | Критерии приёмки покрывают не все функциональные ветки | lens:qa | №06 |
| statement | minor | incomplete | Тип клиента (физлицо) не проверяется логикой метода 1 | lens:architect | №07 |
| statement | minor | incomplete | Функциональные требования Ф-1–Ф-8 не имеют приоритетов | consistency | №09 |
| statement | minor | ambiguity | Граница 23:59:59 без доли секунды оставляет зазор | lens:analyst | №05 |
| statement | minor | ambiguity | Часовой пояс времени операций в ответе АБС не указан | lens:architect | №07 |
| statement | minor | duplicate | Срок хранения 168 часов повторён в двух разделах | consistency | №09 |
| statement | minor | incomplete | Срок 60 секунд не привязан к нагрузке очереди и объёму | lens:analyst | №05 |
