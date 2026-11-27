# Новые ТЗ №18 — кандидат codex55 чистые: чистые №20, 56d098cf, haiku

Кейсов 8, прогонов 8, не измерено 0.

**Recall —** (0/0): critical 0/0, major 0/0, minor 0/0. Вне эталона 0, дублей 0, критичных ложных 0.

Чистые версии (8): замечаний 134, из них ложных (вне фона шаблона) 134: critical 4, major 25; документов с critical 3, с > 1 замечанием 8, вердикт «нельзя» 3.

Recall по типам: .

Время 36.2 мин суммарно, вызовов 75, $1.095.

| Кейс | Версия | Статус | Найдено | Замечаний (к/с/н) | Вердикт | Мин | Вызовов |
| :--- | :--- | :--- | :--- | :--- | :--- | ---: | ---: |
| capital_v2 | clean | complete | — | 14 (0/1/13) | yes/yes | 3.1 | 8 |
| fx | clean | complete | — | 9 (0/0/9) | yes/yes | 4.6 | 9 |
| grace_v2 | clean | complete | — | 19 (0/0/19) | yes/yes | 4.5 | 8 |
| insurance_v2 | clean | complete | — | 19 (1/9/9) | no/no | 3.9 | 9 |
| qr_v2 | clean | complete | — | 17 (0/0/17) | yes/yes | 3.0 | 8 |
| repay | clean | complete | — | 22 (2/10/10) | no/no | 6.8 | 12 |
| roundup | clean | complete | — | 16 (0/1/15) | yes/yes | 4.9 | 10 |
| statement | clean | complete | — | 18 (1/4/13) | yes/no | 5.2 | 11 |

Ложные на чистых версиях:

| Кейс | Серьёзность | Тип | Замечание | Источники | Владельцы |
| :--- | :--- | :--- | :--- | :--- | :--- |
| capital_v2 | major | ambiguity | Получатель процентов при закрытии счёта не определён | lens:analyst, lens:risk, consistency | №05, №08, №09 |
| capital_v2 | minor | terminology | Одни понятия названы разными терминами, глоссария нет | consistency | №09 |
| capital_v2 | minor | traceability | Требования без ID и приоритетов | consistency | №09 |
| capital_v2 | minor | unverifiable | Цель снижения обращений без базы, срока и порога | consistency | №09 |
| capital_v2 | minor | incomplete | Экран «Проценты» не описывает состояние без карты в тенге | lens:analyst | №05 |
| capital_v2 | minor | missing_element | Метод 2 не возвращает дату вступления нового способа | lens:architect | №07 |
| capital_v2 | minor | incomplete | Источник списка карт клиента для выбора не описан | consistency | №09 |
| capital_v2 | minor | incomplete | BPMN и sequence не показывают ветку неактивной карты | consistency | №09 |
| capital_v2 | minor | incomplete | Метод 1 не проверяет, что счёт ведётся в тенге | lens:architect | №07 |
| capital_v2 | minor | ambiguity | Получатель процентов текущего месяца при смене карты неясен | lens:analyst | №05 |
| capital_v2 | minor | incomplete | Критерии приёмки не покрывают границы, закрытие и повторы | lens:qa | №06 |
| capital_v2 | minor | missing_element | Причина капитализации в push не хранится и не передаётся | lens:architect | №07 |
| capital_v2 | minor | incomplete | Закрытие счёта не отражено в процессе | consistency | №09 |
| capital_v2 | minor | incomplete | Закрытый счёт в методе 2 не описан, метод 1 отвечает 404 | lens:architect, consistency | №07, №09 |
| fx | minor | unverifiable | Доля обменов в приложении не измеряется данными АБС | consistency | №09 |
| fx | minor | terminology | «Данные счёта» и «данные счетов» названы по-разному | consistency | №09 |
| fx | minor | missing_element | Лимит Ф-3 выводится на экран без источника данных | lens:architect | №07 |
| fx | minor | contradiction | Таймер экрана и срок котировки отсчитываются от разных моментов | consistency | №09 |
| fx | minor | contradiction | Котировка остаётся ACTIVE при неподтверждённой отмене проводки | lens:architect, consistency | №07, №09 |
| fx | minor | incomplete | Повтор push при ошибке нарушает правило одного push | lens:architect | №07 |
| fx | minor | incomplete | Ответ АБС на отмену невыполненной проводки не описан | lens:architect | №07 |
| fx | minor | api_contract | Тело запроса и поле результата проводки АБС не описаны | lens:architect | №07 |
| fx | minor | missing_element | Способ отключения пункта меню не связан с интеграцией | consistency | №09 |
| grace_v2 | minor | traceability | Большинство пунктов без ID, приоритеты не указаны | consistency | №09 |
| grace_v2 | minor | unverifiable | Цель по снижению доли клиентов без числа и срока | consistency | №09 |
| grace_v2 | minor | terminology | Одни понятия названы разными терминами, глоссария нет | consistency | №09 |
| grace_v2 | minor | ambiguity | Момент утраты льготного периода до конца срока не определён | lens:analyst | №05 |
| grace_v2 | minor | incomplete | Экран: выбор карты при нескольких картах и пустое состояние | lens:analyst | №05 |
| grace_v2 | minor | incomplete | Граничные состояния блока: нулевой остаток и ошибка ответа | lens:qa | №06 |
| grace_v2 | minor | missing_element | Кнопка «Пополнить» на экране без описанного действия | consistency | №09 |
| grace_v2 | minor | contradiction | Ответ без выписки: прошедший период и daysLeft вне допустимого значения | lens:qa, consistency | №06, №09 |
| grace_v2 | minor | ambiguity | Возврат покупки: судьба процентов на возвращённую сумму не определена | lens:analyst, lens:qa | №05, №06 |
| grace_v2 | minor | incomplete | Смена переключателя напоминания в середине периода не описана | consistency | №09 |
| grace_v2 | minor | ambiguity | Счёт дней до окончания периода в день 25-го числа | lens:analyst | №05 |
| grace_v2 | minor | non_singular | Ф-5 объединяет пять правил в одном пункте | lens:analyst | №05 |
| grace_v2 | minor | missing_element | Отмена зачисленного платежа не описана | consistency | №09 |
| grace_v2 | minor | api_contract | Признак сохранения хранится иначе, чем статус ACTIVE/LOST | lens:architect | №07 |
| grace_v2 | minor | missing_element | Критерии приёмки покрывают малую часть функциональных требований | lens:qa | №06 |
| grace_v2 | minor | unit_mismatch | Критерии приёмки в тенге, API в тиынах: правила пересчёта нет | lens:architect | №07 |
| grace_v2 | minor | incomplete | Оценка ИБ отмечена «Да» по внешнему чек-листу, которого нет | lens:risk | №08 |
| grace_v2 | minor | missing_element | Прогноз процентов: метод не получает даты покупок | lens:architect | №07 |
| grace_v2 | minor | incomplete | Схема API показывает только метод 1 и компонент GraceController | consistency | №09 |
| insurance_v2 | critical | contradiction | Отказ после полного погашения: Ф-4 даёт возврат, метод 3 — 409 | lens:risk, consistency | №08, №09 |
| insurance_v2 | major | ambiguity | Отказ страховщика на первом вызове: сохраняется ли подключение | lens:analyst | №05 |
| insurance_v2 | major | missing_element | Полное досрочное погашение не имеет события для сервиса страхования | lens:architect | №07 |
| insurance_v2 | major | incomplete | Статусы страхования не перечислены, состояния после отказа не заданы | lens:architect | №07 |
| insurance_v2 | major | incomplete | Статус полиса после отказа от страхования не определён | lens:risk | №08 |
| insurance_v2 | major | api_contract | Повторный вызов с 400/422 снимает страхование без ответа и исполнителя | lens:architect | №07 |
| insurance_v2 | major | ambiguity | Повторный вызов после отказа: действующих условий не существует | lens:analyst | №05 |
| insurance_v2 | major | contradiction | Дата окончания отказа в примере метода 3 расходится с Ф-4 | lens:risk | №08 |
| insurance_v2 | major | contradiction | Повтор без согласия: особое правило и шаг 6 дают разный ответ | consistency | №09 |
| insurance_v2 | major | api_contract | Повтор подписанной заявки с теми же условиями: 200 или 409 | lens:architect | №07 |
| insurance_v2 | minor | traceability | Большинство пунктов без ID, приоритеты не указаны | consistency | №09 |
| insurance_v2 | minor | incomplete | Цель про жалобы и долю продаж не проверяется требованиями | consistency | №09 |
| insurance_v2 | minor | terminology | Одни объекты названы разными терминами, глоссария нет | consistency | №09 |
| insurance_v2 | minor | incomplete | Схема не показывает получение номера полиса от страховщика | consistency | №09 |
| insurance_v2 | minor | incomplete | Экран условий без начального состояния и текстов ошибок | lens:qa | №06 |
| insurance_v2 | minor | duplicate | Одно и то же правило записано в документе несколько раз | consistency | №09 |
| insurance_v2 | minor | incomplete | Нагрузка для показателя времени ответа 2 с не задана | lens:analyst | №05 |
| insurance_v2 | minor | missing_element | Поля, записываемые в хранилище, отсутствуют в перечне данных | lens:architect | №07 |
| insurance_v2 | minor | missing_element | Критерии приёмки покрывают 6 из 13 функциональных требований | lens:qa | №06 |
| qr_v2 | minor | incomplete | Цель снижения ошибочных переводов не имеет числа и требования | consistency | №09 |
| qr_v2 | minor | contradiction | Маршрут вызова перевода: сервис QR или прямой вызов сервиса переводов | lens:architect, consistency | №07, №09 |
| qr_v2 | minor | terminology | Одни и те же компоненты и карты названы разными терминами | consistency | №09 |
| qr_v2 | minor | incomplete | Документ не рассматривает ряд случаев | lens:analyst | №05 |
| qr_v2 | minor | incomplete | Экран «Получить по QR» не описывает список карт и ошибки | lens:analyst | №05 |
| qr_v2 | minor | incomplete | Экран создания QR не задаёт поведение при суммах вне диапазона | lens:qa | №06 |
| qr_v2 | minor | traceability | Большинство пунктов без ID и приоритетов: трассировка невозможна | consistency | №09 |
| qr_v2 | minor | ambiguity | Не сказано, относится ли отказ 400 к «ошибке» при повторной оплате | lens:qa | №06 |
| qr_v2 | minor | missing_element | Статус перевода не хранится, хотя правила оплаты и отмены от него зависят | lens:architect | №07 |
| qr_v2 | minor | ambiguity | Отмена QR во время оплаты: порядок событий не определён | lens:risk | №08 |
| qr_v2 | minor | incomplete | Два параллельных перевода по QR с суммой: момент оплаты не задан | consistency | №09 |
| qr_v2 | minor | duplicate | Срок 15 минут записан в двух местах | consistency | №09 |
| qr_v2 | minor | unverifiable | Нагрузка «выдерживает» без длительности и критерия успешности | lens:analyst | №05 |
| qr_v2 | minor | missing_element | Ключ идемпотентности и карта списания не входят в перечень данных | lens:architect | №07 |
| qr_v2 | minor | missing_element | Критерии приёмки покрывают 7 из 15 функциональных требований | lens:qa | №06 |
| qr_v2 | minor | incomplete | Место проверки повторного requestId не указано в шагах метода | lens:analyst, lens:architect | №05, №07 |
| qr_v2 | minor | api_contract | Поле status в таблице ответа без условия, но отсутствует в телах ошибок | lens:architect | №07 |
| repay | critical | contradiction | После 422 повтор с тем же ключом даёт 200 | lens:architect, consistency | №07, №09 |
| repay | critical | contradiction | UNKNOWN при «не найдена»: REJECTED против повторного проведения | lens:architect | №07 |
| repay | major | missing_element | Дата выдачи не передаётся из АБС для первого периода | lens:architect, lens:qa | №06, №07 |
| repay | major | missing_element | Ответ АБС на проведение не различает отказы по источнику и остатку | lens:architect | №07 |
| repay | major | missing_element | Флаг видимости кнопки не имеет метода получения | consistency, lens:architect | №07, №09 |
| repay | major | ambiguity | Ожидание предыдущего запроса по кредиту не определено | lens:architect | №07 |
| repay | major | contradiction | Критерий приёмки №10 расходится с правилом метода 3 | lens:qa | №06 |
| repay | major | unverifiable | Цель 50 % не имеет метрики и правила расчёта | consistency | №09 |
| repay | major | missing_element | Экран подтверждения не описывает ошибки 401, 400, 404, 409 | lens:analyst | №05 |
| repay | major | ambiguity | Неясно, какие погашения отменяют расчёт по Ф-7 | lens:analyst | №05 |
| repay | major | ops_risk | Push при повторе после 500 с проведённой операцией не определён | lens:risk | №08 |
| repay | major | missing_element | Сверка UNKNOWN не имеет выхода для статуса «в обработке» | lens:risk | №08 |
| repay | minor | other | Требования и функции не имеют приоритетов | consistency | №09 |
| repay | minor | terminology | «Мобильное приложение» и «Приложение» — один компонент, разные имена | lens:architect, consistency | №07, №09 |
| repay | minor | missing_element | Экран подтверждения: нет правил для пустого списка источников | lens:qa | №06 |
| repay | minor | incomplete | Отключение флага во время расчёта не определено | consistency | №09 |
| repay | minor | api_contract | Тело POST /notifications/push не описано | lens:architect | №07 |
| repay | minor | missing_element | Сверка UNKNOWN не показана на схемах процесса | consistency | №09 |
| repay | minor | missing_element | Ответ АБС на расчёт не описан для полей метода 3 | lens:architect | №07 |
| repay | minor | missing_element | Критерии приёмки не покрывают часть веток и ошибок | lens:qa | №06 |
| repay | minor | ambiguity | «Достаточно средств» в предусловии не задаёт сумму | lens:analyst | №05 |
| repay | minor | api_contract | Тело ошибки 400 метода 3 не описано явно | lens:architect | №07 |
| roundup | major | contradiction | Кто вправе настроить копилку: владелец или держатель карты | lens:risk, lens:analyst | №05, №08 |
| roundup | minor | contradiction | Цель обещает ежедневный перевод, правила его ограничивают | consistency | №09 |
| roundup | minor | terminology | Термины месячного предела и накопленной суммы не едины | consistency | №09 |
| roundup | minor | other | Функциональные требования не ранжированы по приоритету | consistency | №09 |
| roundup | minor | incomplete | Критерии приёмки не покрывают границы суток и месяца | lens:qa | №06 |
| roundup | minor | contradiction | Нулевая сумма к переводу: push может уйти без перевода | lens:qa | №06 |
| roundup | minor | missing_element | Момент получения события не хранится, хотя правила его используют | lens:architect | №07 |
| roundup | minor | ambiguity | Порядок учёта «полученного» события у 00:30 не однозначен | lens:risk | №08 |
| roundup | minor | missing_element | Push-вызов уведомлений описан без тела запроса | lens:architect | №07 |
| roundup | minor | duplicate | Правило применения настроек дублируется в двух местах | consistency | №09 |
| roundup | minor | missing_element | Перевод: тело запроса и признак успеха не описаны | lens:architect | №07 |
| roundup | minor | incomplete | Схема API не показывает связи с переводами и уведомлениями | consistency | №09 |
| roundup | minor | unverifiable | НФ-1: не указан период расчёта доли 99 % | lens:analyst | №05 |
| roundup | minor | unverifiable | НФ-3 не задаёт нагрузку и точку замера | lens:qa | №06 |
| roundup | minor | ambiguity | Число повторов перевода при 5xx не задано явно | lens:analyst | №05 |
| roundup | minor | ambiguity | Статусы карты «активна» не перечислены | lens:analyst | №05 |
| statement | critical | boundary_conflict | Критерий приёмки 22 отдаёт файл после fileExpiresAt по Ф-6 | consistency | №09 |
| statement | major | security | Метод 5 отдаёт файл с ФИО и IBAN без сессии клиента | lens:risk | №08 |
| statement | major | incomplete | Форма: дата начала позже даты окончания не описана | lens:analyst | №05 |
| statement | major | security | Токен файла в пути URL попадает в журналы и историю | lens:risk | №08 |
| statement | major | incomplete | Цель со снижением обращений на 30 % не проверяется требованиями | consistency | №09 |
| statement | minor | traceability | НФТ, данные и интеграционные пункты без ID и приоритетов | consistency | №09 |
| statement | minor | terminology | Один компонент и ссылка названы разными терминами | consistency | №09 |
| statement | minor | incomplete | Архитектура не показывает READY от генератора в сервис | consistency | №09 |
| statement | minor | ambiguity | Календарь: «вчерашний день» не привязан к часам сервиса | lens:analyst, consistency | №05, №09 |
| statement | minor | incomplete | Статусы счёта кроме CLOSED не разобраны явно | lens:analyst | №05 |
| statement | minor | incomplete | Закрытие счёта после создания заказа не описано | consistency | №09 |
| statement | minor | ambiguity | Вчерашний день привязан к разным моментам: отправка или получение | lens:analyst | №05 |
| statement | minor | other | Правила срока файла и периода собраны в одном пункте | lens:analyst | №05 |
| statement | minor | ambiguity | Операция ровно в 00:00:00 даты начала не отнесена | lens:analyst | №05 |
| statement | minor | incomplete | Ответ метода 4 после fileExpiresAt при READY не задан | lens:qa | №06 |
| statement | minor | duplicate | Суточный предел записан дважды: Ф-7 и шаг 6 | consistency | №09 |
| statement | minor | incomplete | Нагрузка и период перцентиля для метода 5 не заданы | lens:analyst | №05 |
| statement | minor | incomplete | Критерии приёмки не покрывают часть границ и ошибок | lens:qa | №06 |
