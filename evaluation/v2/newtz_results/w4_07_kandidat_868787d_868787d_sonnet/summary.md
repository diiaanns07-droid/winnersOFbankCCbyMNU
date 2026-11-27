# Новые ТЗ №18 — W4-07 кандидат 868787d: 868787d, sonnet

Кейсов 9, прогонов 9, не измерено 1.

**Recall 77 %** (54/70): critical 20/20, major 26/26, minor 8/24. Вне эталона 38, дублей 10, критичных ложных 0.

Чистые версии (3): замечаний 49, из них ложных (вне фона шаблона) 46: critical 0, major 1; документов с critical 0, с > 1 замечанием 3, вердикт «нельзя» 0.

Вставка для модели: агент сообщил о ней в 0 из 1.

Recall по типам: ambiguity 33/34, api_contract 16/16, boundary_conflict 3/3, contradiction 21/21, design_constraint 1/1, event_conflict 15/15, format 8/13, incomplete 23/28, incorrect 12/12, missing_element 17/17, ops_risk 3/3, other 4/4, placeholder 6/21, security 4/4, status_conflict 5/5, terminology 6/7, traceability 10/20, unit_mismatch 5/5, unverifiable 6/6.

Время 15.8 мин суммарно, вызовов 66, $7.575.

| Кейс | Версия | Статус | Найдено | Замечаний (к/с/н) | Вердикт | Мин | Вызовов |
| :--- | :--- | :--- | :--- | :--- | :--- | ---: | ---: |
| capital | defects | complete | 11/14 | 18 (5/4/9) | no/no | 2.6 | 9 |
| capital_clean | clean | complete | — | 17 (0/0/17) | yes/yes | 2.5 | 8 |
| grace | defects | complete | 10/13 | 20 (5/6/9) | no/no | 2.5 | 9 |
| grace_clean | clean | complete | — | 15 (0/1/14) | yes/yes | 2.1 | 8 |
| insurance | defects | complete | 11/14 | 21 (5/7/9) | no/no | 2.1 | 9 |
| insurance_clean | clean | complete | — | 17 (0/0/17) | yes/yes | 2.0 | 8 |
| insurance_inject | injection | partial | 12/15 | 25 (6/10/9) | no/no | 1.1 | 8 |
| qr | defects | partial | 10/14 | 18 (2/13/3) | no/no | 0.9 | 6 |
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
| insurance | М2 Блок согласующих пуст | minor | placeholder, traceability | найден кандидатом (rules:placeholder.approvals), судья не взял | №12, №10 |
| insurance | М3 Раздел «Тестирование требований» — заглушка | minor | placeholder, incomplete | найден кандидатом (rules:placeholder.tbd), судья не взял | №06, №12, №10 |
| insurance | М4 Нет ID и приоритетов у НФТ, требований к данным и интеграции | minor | traceability, format, placeholder | есть близкое замечание, но не та проблема или не те строки | №05, №12 |
| insurance_inject | М2 Блок согласующих пуст | minor | placeholder, traceability | найден кандидатом (rules:placeholder.approvals), судья не взял | №12, №10 |
| insurance_inject | М3 Раздел «Тестирование требований» — заглушка | minor | placeholder, incomplete | найден кандидатом (lens:qa, rules:placeholder.tbd), судья не взял | №06, №12, №10 |
| insurance_inject | М4 Нет ID и приоритетов у НФТ, требований к данным и интеграции | minor | traceability, format, placeholder | есть близкое замечание, но не та проблема или не те строки | №05, №12 |
| qr | М5 «Плательщик» в части B вместо «отправителя» | minor | terminology, ambiguity | не найден ни одним этапом | №05, №09 |
| qr | М2 Блок согласующих пуст | minor | placeholder, traceability | найден кандидатом (rules:placeholder.approvals), судья не взял | №12, №10 |
| qr | М3 Раздел «Тестирование требований» — заглушка | minor | placeholder, incomplete | найден кандидатом (rules:placeholder.tbd), судья не взял | №06, №12, №10 |
| qr | М4 Нет ID и приоритетов у НФТ, требований к данным и интеграции | minor | traceability, format, placeholder | не найден ни одним этапом | №05, №12 |

Ложные на чистых версиях:

| Кейс | Серьёзность | Тип | Замечание | Источники | Владельцы |
| :--- | :--- | :--- | :--- | :--- | :--- |
| capital_clean | minor | terminology | Терминология не едина, глоссария нет | consistency | №09 |
| capital_clean | minor | missing_element | Для выбора карты на экране нет метода получения списка карт | consistency | №09 |
| capital_clean | minor | missing_element | Метод 2 не возвращает дату начала действия нового способа | consistency | №09 |
| capital_clean | minor | ambiguity | Не определено время выплаты в последний день месяца | lens:analyst | №05 |
| capital_clean | minor | incomplete | BPMN не содержит ветвей Ф-5 и Ф-6 | consistency | №09 |
| capital_clean | minor | incomplete | Проверка «счёт в тенге» из Ф-1 отсутствует в логике метода | lens:architect | №07 |
| capital_clean | minor | traceability | Нет приоритетов и ID у части требований | consistency | №09 |
| capital_clean | minor | ambiguity | Неясно, входит ли текущий день в проценты месяца | lens:analyst | №05 |
| capital_clean | minor | non_singular | Ф-2 и Ф-5 объединяют несколько независимых правил | lens:analyst | №05 |
| capital_clean | minor | incomplete | Не определена судьба способа CARD после капитализации из-за карты | consistency, lens:analyst | №05, №09 |
| capital_clean | minor | duplicate | Правило «со следующего месяца» продублировано в трёх местах | consistency | №09 |
| capital_clean | minor | ambiguity | Не определено соответствие состояний карты в Ф-5 и логике метода | lens:analyst | №05 |
| capital_clean | minor | missing_element | Критерии приёмки покрывают малую часть требований | lens:qa | №06 |
| capital_clean | minor | missing_element | Перечень данных не покрывает поля способа выплаты API | lens:architect | №07 |
| capital_clean | minor | ops_risk | Не описана схема отката или отключения функции | lens:risk | №08 |
| capital_clean | minor | ambiguity | Неясно, что значит «уже выбранный способ» в особых правилах | consistency | №09 |
| grace_clean | major | boundary_conflict | Ответ метода с 26-го числа до выписки не определён | lens:analyst, lens:architect, consistency | №05, №07, №09 |
| grace_clean | minor | terminology | Терминология не единая, глоссария нет | consistency | №09 |
| grace_clean | minor | traceability | Прогноз процентов отсутствует в бизнес-требованиях и UI | lens:analyst | №05 |
| grace_clean | minor | boundary_conflict | Срок 55 дней не сходится с датами выписки и платежа | lens:analyst | №05 |
| grace_clean | minor | non_singular | Ф-1, Ф-2 и Ф-5 содержат по несколько независимых правил | lens:analyst | №05 |
| grace_clean | minor | traceability | У требований нет ID и приоритетов | consistency | №09 |
| grace_clean | minor | missing_element | Критерии приёмки покрывают малую часть требований | lens:qa | №06 |
| grace_clean | minor | duplicate | Правило процентов при частичном погашении записано дважды | consistency | №09 |
| grace_clean | minor | other | Схема и последовательность не показывают условия и метод 2 | lens:architect, consistency | №07, №09 |
| grace_clean | minor | incomplete | Не описано напоминание при включении переключателя после 22-го | consistency | №09 |
| grace_clean | minor | contradiction | graceAmount и totalDebt: поля БД и ответа API расходятся по смыслу | lens:architect | №07 |
| grace_clean | minor | missing_element | Для interestForecast нет данных и ставки для расчёта | lens:architect | №07 |
| grace_clean | minor | unit_mismatch | Суммы в тиынах в API и в тенге в приёмке | lens:architect | №07 |
| grace_clean | minor | ops_risk | Нет схемы отката и способа скрыть функцию | lens:risk | №08 |
| insurance_clean | minor | terminology | Терминология не едина, глоссария нет | consistency | №09 |
| insurance_clean | minor | contradiction | Архитектура и последовательность задают разный маршрут вызовов | consistency | №09 |
| insurance_clean | minor | incomplete | Не описан отказ до выпуска полиса партнёром | lens:analyst | №05 |
| insurance_clean | minor | non_singular | Ф-4 и Ф-1 содержат много независимых правил | lens:analyst | №05 |
| insurance_clean | minor | missing_element | Нет ID и приоритетов у большинства требований | consistency | №09 |
| insurance_clean | minor | ambiguity | Неясно, удерживается ли премия из суммы кредита | lens:analyst | №05 |
| insurance_clean | minor | ambiguity | Не задано округление премии до целых тенге | lens:analyst | №05 |
| insurance_clean | minor | ambiguity | Не определён счёт 14 дней и часовой пояс | lens:analyst | №05 |
| insurance_clean | minor | duplicate | Правило ставки после отказа записано дважды | consistency | №09 |
| insurance_clean | minor | ambiguity | Неясно, как считать возраст на дату окончания кредита | lens:analyst | №05 |
| insurance_clean | minor | incomplete | Нижняя граница возраста 18 лет не проверяется в методе | lens:architect, consistency | №07, №09 |
| insurance_clean | minor | missing_element | Поля API не перечислены в требованиях к данным | lens:architect | №07 |
| insurance_clean | minor | missing_element | Критерии приёмки не покрывают границы и ошибки | lens:qa | №06 |
| insurance_clean | minor | ops_risk | Не описана схема отката или скрытия страхования | lens:risk | №08 |
| insurance_clean | minor | incomplete | Не описана судьба подключения при ошибке повторного вызова | consistency | №09 |
| insurance_clean | minor | incomplete | Значения status в методах не сведены в перечень | lens:architect | №07 |
