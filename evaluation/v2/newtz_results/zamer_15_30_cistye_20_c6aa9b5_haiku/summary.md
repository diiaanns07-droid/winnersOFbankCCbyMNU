# Новые ТЗ №18 — замер 15:30: чистые №20, c6aa9b5, haiku

Кейсов 8, прогонов 8, не измерено 0.

**Recall —** (0/0): critical 0/0, major 0/0, minor 0/0. Вне эталона 0, дублей 0, критичных ложных 0.

Чистые версии (8): замечаний 95, из них ложных (вне фона шаблона) 95: critical 2, major 11; документов с critical 2, с > 1 замечанием 8, вердикт «нельзя» 2.

Recall по типам: .

Время 35.3 мин суммарно, вызовов 70, $1.013.

| Кейс | Версия | Статус | Найдено | Замечаний (к/с/н) | Вердикт | Мин | Вызовов |
| :--- | :--- | :--- | :--- | :--- | :--- | ---: | ---: |
| capital_v2 | clean | complete | — | 10 (0/1/9) | yes/yes | 2.8 | 7 |
| fx | clean | complete | — | 10 (0/2/8) | yes/yes | 5.4 | 9 |
| grace_v2 | clean | complete | — | 16 (0/1/15) | yes/yes | 3.5 | 8 |
| insurance_v2 | clean | complete | — | 13 (1/3/9) | no/no | 4.0 | 9 |
| qr_v2 | clean | complete | — | 10 (0/0/10) | yes/yes | 2.6 | 7 |
| repay | clean | complete | — | 10 (1/3/6) | no/no | 6.3 | 10 |
| roundup | clean | complete | — | 10 (0/0/10) | yes/yes | 5.7 | 9 |
| statement | clean | complete | — | 16 (0/1/15) | yes/yes | 4.9 | 11 |

Ложные на чистых версиях:

| Кейс | Серьёзность | Тип | Замечание | Источники | Владельцы |
| :--- | :--- | :--- | :--- | :--- | :--- |
| capital_v2 | major | ambiguity | Закрытие счёта при способе «На карту» не имеет определённого получателя выплаты | lens:analyst, lens:risk, consistency | №05, №08, №09 |
| capital_v2 | minor | terminology | Одни и те же понятия названы в документе по-разному | consistency | №09 |
| capital_v2 | minor | other | Не у всех требований есть ID и приоритет | consistency | №09 |
| capital_v2 | minor | missing_element | Экран выбора карты не имеет источника списка карт клиента | consistency | №09 |
| capital_v2 | minor | incomplete | Схема процесса линейна и не показывает карту и закрытие | consistency | №09 |
| capital_v2 | minor | incomplete | Метод смены способа не проверяет валюту счёта из Ф-1 | lens:architect | №07 |
| capital_v2 | minor | duplicate | Дата вступления нового способа записана в двух местах | consistency | №09 |
| capital_v2 | minor | unverifiable | НФТ по времени ответа не задаёт нагрузку для проверки | lens:analyst | №05 |
| capital_v2 | minor | ambiguity | Повтор способа CARD с другой картой в месяце описан двояко | lens:architect | №07 |
| capital_v2 | minor | status_conflict | Закрытая карта даёт разные коды ответа в таблице статусов | lens:qa | №06 |
| fx | major | incomplete | Повтор после 500 может создать вторую проводку по котировке | lens:risk, lens:architect, consistency | №07, №08, №09 |
| fx | major | contradiction | НФ-3 и НФ-4: приёмка до релиза против проверки после запуска | lens:qa | №06 |
| fx | minor | unverifiable | Цель 60 % не измерима: нет признака канала обмена | consistency | №09 |
| fx | minor | terminology | Одни понятия названы по-разному: сервис обмена, сервис счетов | consistency | №09 |
| fx | minor | traceability | Схемы процесса, UI и последовательности без идентификаторов | consistency | №09 |
| fx | minor | incomplete | Строки приёмки не покрывают часть ветвей и границ | lens:qa | №06 |
| fx | minor | incomplete | Нерабочие курсы EUR и RUB не заданы в условиях приёмки | lens:qa | №06 |
| fx | minor | ambiguity | Параметр currency запроса курса не определён | lens:architect | №07 |
| fx | minor | boundary_conflict | Срок 24 ч ключа идемпотентности отсчитывается от двух точек | lens:qa, consistency | №06, №09 |
| fx | minor | missing_element | Состояние отмены проводки не хранится в модели данных | lens:architect | №07 |
| grace_v2 | major | incomplete | Ответ при неготовой выписке: период, статус и daysLeft не определены | lens:analyst, consistency | №05, №09 |
| grace_v2 | minor | ambiguity | Цель снижения потерь без показателя и без гарантии напоминанием | consistency | №09 |
| grace_v2 | minor | terminology | Одни понятия названы разными терминами, глоссария нет | consistency | №09 |
| grace_v2 | minor | contradiction | Схема метода 1 не совпадает с архитектурой по компонентам | consistency | №09 |
| grace_v2 | minor | ambiguity | Момент перехода льготного периода в статус утрачен не определён | lens:analyst | №05 |
| grace_v2 | minor | ambiguity | Выбор карты на экране при нескольких кредитных картах не описан | lens:analyst | №05 |
| grace_v2 | minor | missing_element | Кнопка «Пополнить» на экране не имеет описанного действия | consistency | №09 |
| grace_v2 | minor | traceability | Пункты документа без идентификаторов, приоритетов и источника | consistency | №09 |
| grace_v2 | minor | ambiguity | Платежи до даты выписки не определены для суммы погашения | lens:analyst | №05 |
| grace_v2 | minor | non_singular | Пункт Ф-5 объединяет пять самостоятельных правил | lens:analyst | №05 |
| grace_v2 | minor | incomplete | Срок окончания начисления процентов не задан | lens:analyst | №05 |
| grace_v2 | minor | duplicate | Правило прогноза процентов продублировано в особых правилах | consistency | №09 |
| grace_v2 | minor | incomplete | Переключение напоминания после передачи не описано | consistency | №09 |
| grace_v2 | minor | unit_mismatch | Суммы в тенге и тиынах без правила пересчёта | lens:analyst | №05 |
| grace_v2 | minor | missing_element | Прогноз процентов не имеет входных данных по покупкам | lens:architect | №07 |
| grace_v2 | minor | incomplete | Критерии приёмки покрывают малую часть функциональных требований | lens:qa | №06 |
| insurance_v2 | critical | contradiction | Отказ после полного погашения: Ф-4 разрешает, метод 3 отвечает 409 | consistency | №09 |
| insurance_v2 | major | incomplete | Метод 5 не описывает статус страхования после отказа | consistency | №09 |
| insurance_v2 | major | incomplete | Критерий приёмки №4 требует показа причины, которого нет в экране | lens:qa | №06 |
| insurance_v2 | major | api_contract | Код 400 покрывает два случая, а текст ответа описан для одного | lens:architect | №07 |
| insurance_v2 | minor | terminology | Одни и те же понятия названы разными терминами | consistency | №09 |
| insurance_v2 | minor | incomplete | Схема процесса не показывает полное досрочное погашение | consistency | №09 |
| insurance_v2 | minor | other | Не у всех требований есть ID и приоритет | consistency | №09 |
| insurance_v2 | minor | missing_element | Критерии приёмки покрывают 4 нормальных входа из 15 требований | lens:qa | №06 |
| insurance_v2 | minor | ambiguity | Метод 3 не задаёт момент отсчёта 14 дней и часовой пояс | consistency | №09 |
| insurance_v2 | minor | duplicate | Ставка после отказа описана в Ф-4 и в особых правилах | consistency | №09 |
| insurance_v2 | minor | incomplete | Схема не показывает получение номера полиса от страховщика | consistency | №09 |
| insurance_v2 | minor | unverifiable | Нагрузка для 95 % запросов в нефункциональном требовании не задана | lens:analyst | №05 |
| insurance_v2 | minor | missing_element | Согласие на ПД не перечислено в данных, тип boolean против даты | lens:architect | №07 |
| qr_v2 | minor | unverifiable | Цель по ошибочным реквизитам без показателя и требования | consistency | №09 |
| qr_v2 | minor | terminology | Одни и те же понятия названы разными терминами | consistency, lens:analyst | №05, №09 |
| qr_v2 | minor | contradiction | Маршрут перевода по QR: sequence обходит сервис QR-кодов | consistency | №09 |
| qr_v2 | minor | missing_element | Функциональные требования не имеют приоритетов | consistency | №09 |
| qr_v2 | minor | incomplete | Переход статуса QR-кода после REJECTED не описан в данных | consistency | №09 |
| qr_v2 | minor | duplicate | Срок 15 минут продублирован в функциональном и API-правилах | consistency | №09 |
| qr_v2 | minor | unverifiable | Нагрузочное требование без доли успешных ответов и длительности | lens:analyst | №05 |
| qr_v2 | minor | missing_element | Поля идемпотентности и суммы отсутствуют в перечне хранимых данных | lens:architect | №07 |
| qr_v2 | minor | missing_element | Критерии приёмки покрывают малую часть функциональных правил | lens:qa | №06 |
| qr_v2 | minor | api_contract | Поля успешного ответа без условия отсутствуют в телах ошибок | lens:architect | №07 |
| repay | critical | contradiction | Повтор после 422 даёт 200 вопреки отказу по документу | consistency, lens:qa, lens:architect | №06, №07, №09 |
| repay | major | ambiguity | Состав погашений для сброса расчёта Ф-7 не определён | lens:analyst | №05 |
| repay | major | status_conflict | Сверка «не найдена» ставит REJECTED, повтор проводит ту же операцию | lens:qa, consistency | №06, №09 |
| repay | major | unverifiable | Цель 50 % по каналу не имеет признака учёта в данных | consistency | №09 |
| repay | minor | incomplete | Документ не рассматривает ряд случаев | consistency, lens:architect, lens:qa | №06, №07, №09 |
| repay | minor | terminology | Названия мобильного приложения и суммы погашения не едины | lens:architect, consistency | №07, №09 |
| repay | minor | incomplete | Кнопка погашения при просрочке: показ не описан | lens:analyst | №05 |
| repay | minor | missing_element | Флаг кнопки не имеет операции чтения в API | lens:architect | №07 |
| repay | minor | incomplete | BPMN не содержит ветки сбоя 500 и повтора | consistency | №09 |
| repay | minor | incomplete | Схема последовательности без графика и сверки | consistency | №09 |
| roundup | minor | contradiction | Цель обещает ежедневный перевод без условий предела и остатка | consistency | №09 |
| roundup | minor | terminology | Одни понятия в документе названы разными терминами, глоссария нет | consistency | №09 |
| roundup | minor | ambiguity | Статусы «активной» карты не перечислены, проверка статуса неоднозначна | lens:analyst | №05 |
| roundup | minor | incomplete | Требования не имеют приоритетов, нельзя отсечь состав поставки | consistency | №09 |
| roundup | minor | boundary_conflict | Покупка, полученная до 00:30, может выпасть из фиксации из-за задержки начисления | lens:risk | №08 |
| roundup | minor | duplicate | Правило момента применения шага описано дважды: Ф-8 и API | consistency | №09 |
| roundup | minor | api_contract | Тело вызова push не описано: получатель и текст не заданы | lens:architect | №07 |
| roundup | minor | unverifiable | Срок push «не позже 5 минут» без условий и точки измерения | lens:qa | №06 |
| roundup | minor | missing_element | Ответ переводов не описан: идентификатор и код отказа без поля | lens:architect | №07 |
| roundup | minor | missing_element | Критерии приёмки не покрывают ошибки 401, 500 и таймаут 30 с | lens:qa | №06 |
| statement | major | contradiction | Критерий строки 79 расходится с правилом срока ссылки при fileExpiresAt 12:00 | lens:qa, lens:architect | №06, №07 |
| statement | minor | unverifiable | Цель −30 % обращений без метрики и периода измерения | consistency | №09 |
| statement | minor | terminology | «StatementOrderController» и «сервис выписок» названы по-разному | consistency | №09 |
| statement | minor | contradiction | Схема вызова метода 1 минует API-шлюз, вопреки обещанию | consistency | №09 |
| statement | minor | ambiguity | Смена счёта после ввода дат не описана | consistency | №09 |
| statement | minor | security | Файл выписки с ФИО и IBAN отдаётся без сессии и многократно | lens:risk | №08 |
| statement | minor | api_contract | Коды 200 и 410 используются, но не описаны в перечне статусов | rules:api.status_410, rules:api.status_200 | №12 |
| statement | minor | ambiguity | BPMN: срок хранения «после формирования» у Ф-6 — «с READY» | lens:analyst | №05 |
| statement | minor | incomplete | Условие «физическое лицо» из Ф-1 не проверяется логикой метода 1 | lens:architect | №07 |
| statement | minor | incomplete | Критерии приёмки не покрывают часть функциональных требований | lens:qa | №06 |
| statement | minor | ambiguity | Запрос АБС с датами: правило границ остатков не согласовано | lens:architect | №07 |
| statement | minor | ambiguity | Граница ровно 30 суток для заказа и метода 3 не определена | consistency | №09 |
| statement | minor | unverifiable | Нагрузочный тест не охватывает норматив метода 5 из L042 | lens:qa | №06 |
| statement | minor | api_contract | Метод 5 с GET записывает аудит «файл скачан» при каждом запросе | lens:architect | №07 |
| statement | minor | incomplete | Флаг statement_pdf назван, но судьба заказов при выключении не описана | consistency | №09 |
| statement | minor | security | Токен файла в пути GET-адреса попадает в журналы | lens:risk | №08 |
