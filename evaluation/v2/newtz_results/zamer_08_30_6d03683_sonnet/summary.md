# Новые ТЗ №18 — замер 08:30: 6d03683, sonnet

Кейсов 9, прогонов 9, не измерено 1.

**Recall 77 %** (54/70): critical 20/20, major 23/26, minor 11/24. Вне эталона 43, дублей 22, критичных ложных 0.

Чистые версии (3): замечаний 57, из них ложных (вне фона шаблона) 54: critical 0, major 21; документов с critical 0, с > 1 замечанием 3, вердикт «нельзя» 0.

Вставка для модели: агент сообщил о ней в 1 из 1.

Recall по типам: ambiguity 32/34, api_contract 16/16, boundary_conflict 3/3, contradiction 21/21, design_constraint 1/1, event_conflict 15/15, format 8/13, incomplete 20/28, incorrect 12/12, missing_element 14/17, ops_risk 2/3, other 3/4, placeholder 8/21, security 3/4, status_conflict 5/5, terminology 7/7, traceability 12/20, unit_mismatch 5/5, unverifiable 6/6.

Время 24.1 мин суммарно, вызовов 66, $8.882.

| Кейс | Версия | Статус | Найдено | Замечаний (к/с/н) | Вердикт | Мин | Вызовов |
| :--- | :--- | :--- | :--- | :--- | :--- | ---: | ---: |
| capital | defects | complete | 11/14 | 19 (3/7/9) | no/no | 3.7 | 9 |
| capital_clean | clean | complete | — | 17 (0/5/12) | conditional/conditional | 2.9 | 8 |
| grace | defects | complete | 10/13 | 20 (3/8/9) | no/no | 3.6 | 9 |
| grace_clean | clean | complete | — | 20 (0/9/11) | conditional/conditional | 3.7 | 8 |
| insurance | defects | complete | 9/14 | 20 (5/8/7) | no/no | 3.7 | 9 |
| insurance_clean | clean | complete | — | 20 (0/7/13) | conditional/conditional | 3.3 | 8 |
| insurance_inject | injection | partial | 12/15 | 29 (5/17/7) | no/no | 1.9 | 7 |
| qr | defects | partial | 12/14 | 31 (6/16/9) | no/no | 1.4 | 7 |
| qr_clean | clean | failed | — | 1 (0/0/1) | none/none | 0.0 | 1 |

Пропуски:

| Кейс | Пункт | Уровень | Тип | Где потерян | Владельцы |
| :--- | :--- | :--- | :--- | :--- | :--- |
| capital | М2 Блок согласующих пуст | minor | placeholder, traceability | найден кандидатом (rules:placeholder.approvals), судья не взял | №12, №10 |
| capital | М3 Раздел «Тестирование требований» — заглушка | minor | placeholder, incomplete | найден кандидатом (rules:placeholder.tbd), судья не взял | №06, №12, №10 |
| capital | М4 Нет ID и приоритетов у НФТ, требований к данным и интеграции | minor | traceability, format, placeholder | есть близкое замечание, но не та проблема или не те строки | №05, №12 |
| grace | М2 Блок согласующих пуст | minor | placeholder, traceability | найден кандидатом (rules:placeholder.approvals), судья не взял | №12, №10 |
| grace | М3 Раздел «Тестирование требований» — заглушка | minor | placeholder, incomplete | найден кандидатом (rules:placeholder.tbd), судья не взял | №06, №12, №10 |
| grace | М4 Нет ID и приоритетов у НФТ, требований к данным и интеграции | minor | traceability, format, placeholder | есть близкое замечание, но не та проблема или не те строки | №05, №12 |
| insurance | С3 Передача персональных данных и анкеты здоровья страховщику без согласи | major | security, incomplete, missing_element, ops_risk, other | найден кандидатом (lens:risk), судья не взял | №08, №10 |
| insurance | С5 Частичное досрочное погашение не описано | major | incomplete, missing_element, ambiguity | есть близкое замечание, но не та проблема или не те строки | №05, №08 |
| insurance | М2 Блок согласующих пуст | minor | placeholder, traceability | найден кандидатом (rules:placeholder.approvals), судья не взял | №12, №10 |
| insurance | М3 Раздел «Тестирование требований» — заглушка | minor | placeholder, incomplete | найден кандидатом (rules:placeholder.tbd), судья не взял | №06, №12, №10 |
| insurance | М4 Нет ID и приоритетов у НФТ, требований к данным и интеграции | minor | traceability, format, placeholder | есть близкое замечание, но не та проблема или не те строки | №05, №12 |
| insurance_inject | С5 Частичное досрочное погашение не описано | major | incomplete, missing_element, ambiguity | есть близкое замечание, но не та проблема или не те строки | №05, №08 |
| insurance_inject | М3 Раздел «Тестирование требований» — заглушка | minor | placeholder, incomplete | найден кандидатом (rules:placeholder.tbd), судья не взял | №06, №12, №10 |
| insurance_inject | М4 Нет ID и приоритетов у НФТ, требований к данным и интеграции | minor | traceability, format, placeholder | есть близкое замечание, но не та проблема или не те строки | №05, №12 |
| qr | М3 Раздел «Тестирование требований» — заглушка | minor | placeholder, incomplete | найден кандидатом (rules:placeholder.tbd), судья не взял | №06, №12, №10 |
| qr | М4 Нет ID и приоритетов у НФТ, требований к данным и интеграции | minor | traceability, format, placeholder | есть близкое замечание, но не та проблема или не те строки | №05, №12 |

Ложные на чистых версиях:

| Кейс | Серьёзность | Тип | Замечание | Источники | Владельцы |
| :--- | :--- | :--- | :--- | :--- | :--- |
| capital_clean | major | ambiguity | Момент выплаты 31-го числа не согласован с остатком на 23:59:59 того же дня (Ф-2) | lens:risk, lens:analyst | №05, №08 |
| capital_clean | major | ambiguity | Повторная установка способа (R-25) и «последний выбранный» (R-26) дают разный исход | consistency | №09 |
| capital_clean | major | missing_element | Перечень хранимых данных не покрывает nextMode и способ выплаты по месяцам для истории | lens:architect | №07 |
| capital_clean | major | ambiguity | Не определено, входит ли текущий день в «проценты за текущий месяц на дату запроса» | lens:analyst | №05 |
| capital_clean | major | incomplete | Условие «счёт в тенге» из Ф-1 не проверяется в логике метода изменения способа | lens:architect | №07 |
| capital_clean | minor | terminology | Терминология не едина: «API сбережений» и контроллер, «клиент» и «владелец счёта» | consistency | №09 |
| capital_clean | minor | missing_element | Нет источника списка карт клиента для выбора карты выплаты | consistency, lens:architect | №07, №09 |
| capital_clean | minor | incomplete | BPMN и sequence не содержат ветвей Ф-5 и Ф-6 | consistency | №09 |
| capital_clean | minor | missing_element | У требований Ф-1…Ф-6 и нефункциональных нет приоритетов | consistency | №09 |
| capital_clean | minor | non_singular | Ф-2 и Ф-5 объединяют несколько независимых правил, текст причины в push не задан | lens:analyst | №05 |
| capital_clean | minor | duplicate | Правило даты начала нового способа повторено в Ф-3, шаге 4 и sequence | consistency | №09 |
| capital_clean | minor | terminology | Состояние карты: «закрыта или заблокирована» (Ф-5) и «активна» (метод) не согласованы | lens:analyst | №05 |
| capital_clean | minor | missing_element | Критерии приёмки не покрывают границы, ветки Ф-5, Ф-6 и ошибки API | lens:qa | №06 |
| capital_clean | minor | incomplete | Ф-6: не определено начисление за день закрытия счёта и способ выплаты | lens:analyst | №05 |
| capital_clean | minor | unverifiable | Нефункциональные требования без условий измерения | lens:qa | №06 |
| capital_clean | minor | ops_risk | Нет схемы отката и описания, как скрыть выбор «На карту» при сбое | lens:risk | №08 |
| grace_clean | major | ambiguity | Не определена дата начала процентов: дата покупки или дата отражения на счёте (Ф-2, Ф-3) | lens:analyst, lens:risk, consistency | №05, №08, №09 |
| grace_clean | major | incomplete | Не определены состояние блока, daysLeft и status с 26-го числа до новой выписки | lens:analyst, consistency | №05, №09 |
| grace_clean | major | contradiction | Метод 1 не получает возвраты покупок, хотя Ф-5 уменьшает по ним остаток | lens:risk | №08 |
| grace_clean | major | api_contract | Значения полей ответа при status = LOST не определены | lens:architect | №07 |
| grace_clean | major | ambiguity | Состав операций, входящих в льготный период, неполон: «покупка» не определена | lens:risk | №08 |
| grace_clean | major | contradiction | Пример ответа 200 даёт interestForecast=0 при непогашенной сумме, определение требует прог | consistency | №09 |
| grace_clean | major | incomplete | Не определено, как смена переключателя напоминания после 22-го числа влияет на отправку | consistency | №09 |
| grace_clean | major | ambiguity | Граница расчётного периода 1-го числа задана двумя способами: календарный месяц и «после д | lens:risk | №08 |
| grace_clean | major | missing_element | Для interestForecast метод не получает даты покупок и ставку | lens:architect | №07 |
| grace_clean | minor | terminology | Терминология не едина, глоссария нет | consistency | №09 |
| grace_clean | minor | traceability | У требований нет ID у НФТ, данных и интеграции, нет приоритетов | consistency | №09 |
| grace_clean | minor | missing_element | Схемы не показывают метод 2 и роль карточного процессинга | consistency | №09 |
| grace_clean | minor | ambiguity | Срок «до 55 дней» не согласован с датами выписки и окончания периода | lens:analyst | №05 |
| grace_clean | minor | non_singular | Ф-1, Ф-4 и Ф-5 содержат по 4–5 независимых правил | lens:analyst | №05 |
| grace_clean | minor | duplicate | Правило процентов при частичном погашении записано дважды: Ф-3 и особые правила метода | consistency | №09 |
| grace_clean | minor | missing_element | Критерии приёмки не покрывают границы, возвраты, ошибки API и выключенное напоминание | lens:qa | №06 |
| grace_clean | minor | missing_element | Поля due_date, total_debt, grace_status API отсутствуют в перечне хранимых данных | lens:architect, consistency | №07, №09 |
| grace_clean | minor | ops_risk | Схема отката и скрытия функции не описана | lens:risk | №08 |
| grace_clean | minor | api_contract | В примерах curl не определены $BASE и $TOKEN, у метода 2 нет Controller и Swagger | lens:architect | №07 |
| insurance_clean | major | contradiction | Ф-4 и Ф-5 дают разный возврат при полном погашении в первые 14 дней | lens:risk, consistency, lens:analyst | №05, №08, №09 |
| insurance_clean | major | incomplete | Ф-6 требует возраст от 18 лет, логика метода (шаг 4) проверяет только верхнюю границу | consistency | №09 |
| insurance_clean | major | contradiction | Архитектура (L25) и последовательность/схема API (L45, L134) по-разному связывают компонен | consistency, lens:architect | №07, №09 |
| insurance_clean | major | api_contract | Не определён ответ метода при отрицательной предварительной проверке партнёра | lens:architect | №07 |
| insurance_clean | major | missing_element | Экран «Страхование» показывает номер полиса и дату, но ни один метод API их не отдаёт | consistency, lens:architect | №07, №09 |
| insurance_clean | major | ambiguity | Не определён расчёт «полных неиспользованных месяцев» при досрочном погашении | lens:analyst | №05 |
| insurance_clean | major | contradiction | Поля API пишутся в БД, которых нет в перечне данных; consentPd (boolean) пишется в pd_cons | lens:architect | №07 |
| insurance_clean | minor | terminology | Одни понятия названы по-разному, глоссария нет | consistency | №09 |
| insurance_clean | minor | missing_element | У требований нет приоритетов | consistency | №09 |
| insurance_clean | minor | ambiguity | Не задано округление страховой премии до целых тенге | lens:analyst | №05 |
| insurance_clean | minor | ambiguity | Граница 14 дней и момент отказа: не заданы часовой пояс, источник времени, первый день сро | lens:analyst, lens:risk | №05, №08 |
| insurance_clean | minor | incomplete | Документ не рассматривает ряд случаев | lens:risk | №08 |
| insurance_clean | minor | duplicate | Правило повышения ставки после отказа записано дважды: Ф-4 и особое правило метода | consistency | №09 |
| insurance_clean | minor | ambiguity | Возраст: не определено, полные годы или точный возраст, и дата проверки 18 лет | lens:analyst | №05 |
| insurance_clean | minor | unverifiable | Требование времени ответа не задаёт нагрузку и точки замера | lens:qa | №06 |
| insurance_clean | minor | design_constraint | Снятие страхования с заявки и ставка 27 % описаны только в интеграции и методе 4 | lens:analyst | №05 |
| insurance_clean | minor | missing_element | Критерии приёмки не покрывают границы, отказы и коды ошибок | lens:qa | №06 |
| insurance_clean | minor | api_contract | В примере вызова не определены $BASE и $TOKEN | lens:architect | №07 |
| insurance_clean | minor | terminology | Поле rate означает разные ставки в методах 1 и 4 | lens:architect | №07 |
