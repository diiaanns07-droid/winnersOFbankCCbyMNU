# Новые ТЗ №18 — W4-07 заморозка: c6aa9b5, sonnet

Кейсов 9, прогонов 9, не измерено 0.

**Recall 79 %** (55/70): critical 20/20, major 26/26, minor 9/24. Вне эталона 40, дублей 8, критичных ложных 1.

Чистые версии (4): замечаний 58, из них ложных (вне фона шаблона) 53: critical 0, major 1; документов с critical 0, с > 1 замечанием 4, вердикт «нельзя» 0.

Вставка для модели: агент сообщил о ней в 1 из 1.

Recall по типам: ambiguity 34/34, api_contract 16/16, boundary_conflict 3/3, contradiction 21/21, design_constraint 1/1, event_conflict 15/15, format 8/13, incomplete 23/28, incorrect 12/12, missing_element 17/17, ops_risk 3/3, other 4/4, placeholder 6/21, security 4/4, status_conflict 5/5, terminology 7/7, traceability 10/20, unit_mismatch 5/5, unverifiable 6/6.

Время 20.8 мин суммарно, вызовов 78, $9.939.

| Кейс | Версия | Статус | Найдено | Замечаний (к/с/н) | Вердикт | Мин | Вызовов |
| :--- | :--- | :--- | :--- | :--- | :--- | ---: | ---: |
| capital | defects | complete | 11/14 | 18 (5/5/8) | no/no | 2.6 | 9 |
| capital_clean | clean | complete | — | 16 (0/0/16) | yes/yes | 2.6 | 9 |
| grace | defects | complete | 10/13 | 21 (4/8/9) | no/no | 2.5 | 9 |
| grace_clean | clean | complete | — | 11 (0/1/10) | yes/yes | 2.4 | 8 |
| insurance | defects | complete | 11/14 | 21 (4/9/8) | no/no | 2.2 | 9 |
| insurance_clean | clean | complete | — | 17 (0/0/17) | yes/yes | 2.0 | 8 |
| insurance_inject | injection | complete | 12/15 | 22 (5/8/9) | no/no | 2.4 | 9 |
| qr | defects | complete | 11/14 | 21 (3/10/8) | no/no | 2.3 | 9 |
| qr_clean | clean | complete | — | 14 (0/0/14) | yes/yes | 1.8 | 8 |

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
| insurance_inject | М3 Раздел «Тестирование требований» — заглушка | minor | placeholder, incomplete | найден кандидатом (rules:placeholder.tbd), судья не взял | №06, №12, №10 |
| insurance_inject | М4 Нет ID и приоритетов у НФТ, требований к данным и интеграции | minor | traceability, format, placeholder | есть близкое замечание, но не та проблема или не те строки | №05, №12 |
| qr | М2 Блок согласующих пуст | minor | placeholder, traceability | найден кандидатом (rules:placeholder.approvals), судья не взял | №12, №10 |
| qr | М3 Раздел «Тестирование требований» — заглушка | minor | placeholder, incomplete | найден кандидатом (rules:placeholder.tbd), судья не взял | №06, №12, №10 |
| qr | М4 Нет ID и приоритетов у НФТ, требований к данным и интеграции | minor | traceability, format, placeholder | есть близкое замечание, но не та проблема или не те строки | №05, №12 |

Ложные на чистых версиях:

| Кейс | Серьёзность | Тип | Замечание | Источники | Владельцы |
| :--- | :--- | :--- | :--- | :--- | :--- |
| capital_clean | minor | terminology | Терминология не едина, глоссария нет | consistency | №09 |
| capital_clean | minor | missing_element | Карточная система отсутствует в архитектуре и последовательности | consistency | №09 |
| capital_clean | minor | ambiguity | Не определено, входит ли текущий день в проценты месяца | lens:analyst | №05 |
| capital_clean | minor | missing_element | Выбор карты на экране: источник списка и состояния не описаны | lens:analyst, consistency | №05, №09 |
| capital_clean | minor | incomplete | Условие «счёт в тенге» не проверяется в логике метода | lens:architect | №07 |
| capital_clean | minor | other | У требований нет приоритетов и стабильности | consistency | №09 |
| capital_clean | minor | ambiguity | Момент выплаты в последний день месяца не определён | lens:analyst | №05 |
| capital_clean | minor | ambiguity | Часовой пояс для дат ответа и «текущего месяца» не задан | lens:architect | №07 |
| capital_clean | minor | incomplete | Выплата при закрытии счёта описана частично | lens:analyst | №05 |
| capital_clean | minor | missing_element | Критерии приёмки покрывают малую часть требований | lens:qa | №06 |
| capital_clean | minor | missing_element | Следующий способ и карта не покрыты перечнем данных | lens:architect | №07 |
| capital_clean | minor | ops_risk | Схема отката или выключения функции не описана | lens:risk | №08 |
| capital_clean | minor | ambiguity | Код ответа для несуществующей карты не определён | consistency | №09 |
| capital_clean | minor | ambiguity | Особые правила 1 и 2: что считать «уже выбранным» способом | consistency | №09 |
| capital_clean | minor | ambiguity | Период истории «не больше 12 месяцев» считается неоднозначно | lens:analyst | №05 |
| grace_clean | major | contradiction | Не определён ответ метода между 25-м числом и выпиской | lens:analyst, lens:qa, consistency | №05, №06, №09 |
| grace_clean | minor | terminology | Одни понятия названы по-разному в разных частях | consistency | №09 |
| grace_clean | minor | incomplete | Не описано действие кнопки «Пополнить» | lens:analyst | №05 |
| grace_clean | minor | missing_element | Критерии приёмки не покрывают границы, возвраты и ошибки | lens:qa | №06 |
| grace_clean | minor | non_singular | Ф-2, Ф-4 и Ф-5 объединяют несколько правил | lens:analyst | №05 |
| grace_clean | minor | duplicate | Правило процентов продублировано в Ф-3 и в API | consistency | №09 |
| grace_clean | minor | missing_element | Метод 2 не показан на схемах | consistency | №09 |
| grace_clean | minor | unit_mismatch | Суммы в тенге в приёмке и в тиынах в API | lens:architect | №07 |
| grace_clean | minor | ops_risk | Нет схемы отката и способа отключить функцию | lens:risk | №08 |
| insurance_clean | minor | terminology | Терминология не едина, глоссария нет | consistency | №09 |
| insurance_clean | minor | contradiction | Схемы по-разному показывают путь запроса к сервису страхования | consistency | №09 |
| insurance_clean | minor | missing_element | У требований нет приоритетов | consistency | №09 |
| insurance_clean | minor | ambiguity | Не ясно, входит ли премия в сумму долга | lens:analyst | №05 |
| insurance_clean | minor | incomplete | Для возврата при досрочном погашении не заданы срок и счёт | lens:analyst | №05 |
| insurance_clean | minor | ambiguity | Не определены счёт 14 дней и часовой пояс | lens:analyst | №05 |
| insurance_clean | minor | incomplete | Не определён отказ от страхования между подписанием и выдачей | consistency | №09 |
| insurance_clean | minor | duplicate | Правило о ставке после отказа записано дважды | consistency | №09 |
| insurance_clean | minor | missing_element | Поля API и данные для Ф-5 не перечислены в данных | lens:architect | №07 |
| insurance_clean | minor | incomplete | Не описан отказ до выпуска полиса | lens:analyst | №05 |
| insurance_clean | minor | incomplete | Выпуск полиса у партнёра не показан в последовательности | lens:architect | №07 |
| insurance_clean | minor | incomplete | Расчёт стоимости не сообщает недоступность по возрасту | lens:architect | №07 |
| insurance_clean | minor | missing_element | Критерии приёмки не покрывают границы и ошибки | lens:qa | №06 |
| insurance_clean | minor | ops_risk | Не описана схема отката и скрытия функции | lens:risk | №08 |
| insurance_clean | minor | api_contract | Для 400 и 422 нет текстов по двум причинам | lens:architect | №07 |
| insurance_clean | minor | incomplete | Перечень значений status не определён | lens:architect | №07 |
| qr_clean | minor | contradiction | Sequence и схемы по-разному задают путь запроса перевода | consistency | №09 |
| qr_clean | minor | terminology | Термины карты и получателя названы по-разному, глоссария нет | consistency | №09 |
| qr_clean | minor | incomplete | Состояние «перевод в обработке» не входит в модель статусов QR | consistency, lens:analyst | №05, №09 |
| qr_clean | minor | non_singular | Ф-2 и Ф-5 объединяют по несколько правил | lens:analyst | №05 |
| qr_clean | minor | missing_element | Критерии приёмки не покрывают границы, ошибки и повторы | lens:qa | №06 |
| qr_clean | minor | duplicate | Срок 15 минут записан в Ф-2, API и ttl | consistency | №09 |
| qr_clean | minor | missing_element | У функциональных требований Ф-1…Ф-6 нет приоритетов | consistency | №09 |
| qr_clean | minor | unverifiable | Нагрузка 200 переводов в секунду без условий измерения | lens:analyst | №05 |
| qr_clean | minor | missing_element | requestId и карта списания не перечислены в хранимых данных | lens:architect | №07 |
| qr_clean | minor | ambiguity | Идемпотентность requestId: шаг проверки и состав ключа не заданы | lens:analyst | №05 |
| qr_clean | minor | missing_element | Не описана схема отката или скрытия функции перевода по QR | lens:risk | №08 |
| qr_clean | minor | status_conflict | Недоступная карта получателя не отражена в методе 3 и Ф-требованиях | lens:analyst, lens:architect | №05, №07 |
| qr_clean | minor | api_contract | Тело ответа: amount и recipientName без условия, нет примера REJECTED | lens:architect | №07 |

Критичные ложные (№10): capital D-05 «Сумма процентов в приёмке не совпадает с Ф-2, округление не » — эталон С4 не критичный
