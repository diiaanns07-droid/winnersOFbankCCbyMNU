# Новые ТЗ №18 — W4-07 выборка 2: чистые open2, 28fe64f, haiku

Кейсов 4, прогонов 4, не измерено 0.

**Recall —** (0/0): critical 0/0, major 0/0, minor 0/0. Вне эталона 0, дублей 0, критичных ложных 0.

Чистые версии (4): замечаний 72, из них ложных (вне фона шаблона) 67: critical 0, major 1; документов с critical 0, с > 1 замечанием 4, вердикт «нельзя» 0.

Recall по типам: .

Время 13.7 мин суммарно, вызовов 33, $0.411.

| Кейс | Версия | Статус | Найдено | Замечаний (к/с/н) | Вердикт | Мин | Вызовов |
| :--- | :--- | :--- | :--- | :--- | :--- | ---: | ---: |
| capital_clean | clean | complete | — | 14 (0/0/14) | yes/yes | 3.3 | 8 |
| grace_clean | clean | complete | — | 18 (0/0/18) | yes/yes | 3.8 | 8 |
| insurance_clean | clean | complete | — | 22 (0/1/21) | yes/yes | 3.7 | 9 |
| qr_clean | clean | complete | — | 18 (0/0/18) | yes/yes | 2.9 | 8 |

Ложные на чистых версиях:

| Кейс | Серьёзность | Тип | Замечание | Источники | Владельцы |
| :--- | :--- | :--- | :--- | :--- | :--- |
| capital_clean | minor | missing_element | Приоритет требований в карточке задачи не указан | consistency | №09 |
| capital_clean | minor | terminology | Один компонент назван разными именами в документе | lens:architect, consistency | №07, №09 |
| capital_clean | minor | missing_element | Выбор карты выплаты: список карт клиента нигде не описан | consistency | №09 |
| capital_clean | minor | ambiguity | Закрытие счёта при способе «На карту»: маршрут денег не определён | lens:analyst | №05 |
| capital_clean | minor | ambiguity | Проценты на дату запроса: включается ли день запроса, неясно | consistency | №09 |
| capital_clean | minor | duplicate | Правило переноса способа на следующий месяц записано дважды | consistency | №09 |
| capital_clean | minor | terminology | Состояние карты при выборе и выплате проверяется разными условиями | lens:analyst | №05 |
| capital_clean | minor | incomplete | Sequence-диаграмма не содержит метод истории начислений | consistency | №09 |
| capital_clean | minor | ambiguity | Округление половины тиына: «математическое правило» не уточнено | lens:analyst | №05 |
| capital_clean | minor | incomplete | Поле next_payout_mode не перечислено в требованиях к данным | lens:architect | №07 |
| capital_clean | minor | incomplete | Критерии приёмки не покрывают границы, ошибки и закрытие счёта | lens:qa | №06 |
| capital_clean | minor | ops_risk | Схема отката и скрытия выбора способа не описана | lens:risk | №08 |
| capital_clean | minor | incomplete | Закрытый счёт: метод 2 не задаёт ответ, метод 1 отвечает 404 | consistency | №09 |
| grace_clean | minor | incomplete | Документ не рассматривает ряд случаев | consistency, lens:analyst | №05, №09 |
| grace_clean | minor | incomplete | Карточный процессинг затронут, но не входит в архитектуру | consistency | №09 |
| grace_clean | minor | terminology | Одни и те же понятия названы разными терминами | consistency | №09 |
| grace_clean | minor | incomplete | Цель без числового показателя; сумма может быть устаревшей | consistency | №09 |
| grace_clean | minor | missing_element | Кнопка «Пополнить» в блоке не имеет описанного действия | consistency | №09 |
| grace_clean | minor | ambiguity | Платежи за услуги картой не отнесены к покупкам | lens:risk | №08 |
| grace_clean | minor | ambiguity | Возврат покупки неясно влияет на условие полной оплаты | lens:analyst | №05 |
| grace_clean | minor | incomplete | Не указано, до какой даты начисляются проценты | lens:analyst | №05 |
| grace_clean | minor | duplicate | Правило расчёта процентов продублировано в особых правилах API | consistency | №09 |
| grace_clean | minor | boundary_conflict | Напоминание за 3 дня и окно 10–12 дают разный исход | lens:analyst | №05 |
| grace_clean | minor | incomplete | Критерии приёмки покрывают малую часть правил | lens:qa | №06 |
| grace_clean | minor | missing_element | Возвраты покупок не входят в данные метода 1 | lens:architect | №07 |
| grace_clean | minor | contradiction | Платёж за 5 минут до запроса не учитывается вопреки Ф-5 | lens:risk | №08 |
| grace_clean | minor | missing_element | Схема отката и выключения функции не описаны | lens:risk | №08 |
| grace_clean | minor | incomplete | Ответ по прошедшему сроку платежа до выписки не задан | consistency | №09 |
| grace_clean | minor | incomplete | Ответ для карты без предыдущей выписки не определён | lens:analyst | №05 |
| grace_clean | minor | ambiguity | Не определено, считается ли текущий день в daysLeft | lens:analyst | №05 |
| insurance_clean | major | incomplete | Нижний возрастной предел 18 лет не проверяется в логике метода | lens:analyst, lens:architect, consistency | №05, №07, №09 |
| insurance_clean | minor | terminology | Одни и те же понятия названы в документе по-разному | consistency | №09 |
| insurance_clean | minor | unverifiable | Цель о жалобах не измерима и не связана с требованиями | consistency | №09 |
| insurance_clean | minor | incomplete | Вызова страховщика за номером полиса нет в последовательности | lens:architect | №07 |
| insurance_clean | minor | contradiction | Архитектура не показывает вызов сервиса страхования из API | consistency | №09 |
| insurance_clean | minor | incomplete | Последовательность не показывает ветвь отказа и возврата премии | consistency | №09 |
| insurance_clean | minor | ambiguity | Премия из суммы кредита: неясно, уменьшается ли выдача | lens:analyst | №05 |
| insurance_clean | minor | incomplete | Документ не рассматривает ряд случаев | lens:risk, lens:analyst | №05, №08 |
| insurance_clean | minor | incomplete | Округление дробной премии не задано | lens:analyst | №05 |
| insurance_clean | minor | ambiguity | Не ясно, входит ли день выдачи в 14-дневное окно | lens:analyst | №05 |
| insurance_clean | minor | incomplete | Значения status метода 5 не заданы для отказа и погашения | lens:architect | №07 |
| insurance_clean | minor | contradiction | Ф-4 и Ф-5 по-разному задают возврат при отказе после погашения | consistency | №09 |
| insurance_clean | minor | incomplete | Метод отказа не описывает кредит без страхования | lens:architect | №07 |
| insurance_clean | minor | duplicate | Возрастной предел 65 лет записан в двух местах | consistency | №09 |
| insurance_clean | minor | missing_element | Поля согласия и суммы в БД не перечислены в данных | lens:architect | №07 |
| insurance_clean | minor | incomplete | Критерии приёмки покрывают малую часть функциональных требований | lens:qa | №06 |
| insurance_clean | minor | api_contract | Код 422 для отказа страховщика содержит текст про возраст | lens:architect | №07 |
| insurance_clean | minor | api_contract | Пример тела 400 описывает только диапазон, без согласия | lens:architect | №07 |
| insurance_clean | minor | status_conflict | Код 409 означает подписание в методе 1 и срок отказа в методе 3 | lens:qa | №06 |
| insurance_clean | minor | api_contract | Тела ответов 400, 404 и 409 не заданы для методов 2–5 | lens:architect | №07 |
| qr_clean | minor | unverifiable | Цель снижения ошибочных переводов не имеет показателя | consistency | №09 |
| qr_clean | minor | incorrect | Sequence-схема минует сервис QR-кодов, расходясь с архитектурой | consistency | №09 |
| qr_clean | minor | terminology | Одни и те же карты названы разными терминами, глоссария нет | consistency | №09 |
| qr_clean | minor | incomplete | Функциональные требования не имеют приоритетов | consistency | №09 |
| qr_clean | minor | incomplete | Приостановленная карта получателя не проверяется при оплате | lens:analyst | №05 |
| qr_clean | minor | ambiguity | Срок QR: фиксированные 15 минут или настраиваемый ttl | lens:analyst | №05 |
| qr_clean | minor | missing_element | Параллельная оплата QR с суммой: исход второго запроса не описан | consistency | №09 |
| qr_clean | minor | duplicate | Срок 15 минут записан в двух местах | consistency | №09 |
| qr_clean | minor | ambiguity | Отмена QR без суммы: состояние «перевод в обработке» не введено в статусы | lens:analyst | №05 |
| qr_clean | minor | unverifiable | Нагрузка 200 переводов в секунду без условий успеха | lens:analyst | №05 |
| qr_clean | minor | missing_element | requestId и debit_card_id не входят в перечень хранимых данных | lens:architect | №07 |
| qr_clean | minor | incomplete | Критерии приёмки покрывают 6 из 14 функциональных требований | lens:qa | №06 |
| qr_clean | minor | ops_risk | Нет схемы отката и выключения QR-перевода | lens:risk | №08 |
| qr_clean | minor | security | Ключ requestId не привязан к клиенту: повтор раскрывает чужой перевод | lens:risk | №08 |
| qr_clean | minor | api_contract | Пример перевода даёт 5000 ₸ по QR с суммой 3000 ₸ | lens:architect | №07 |
| qr_clean | minor | ambiguity | Место проверки requestId в шагах метода не указано | lens:analyst, lens:architect | №05, №07 |
| qr_clean | minor | api_contract | Поле status описано для всех ответов, но в телах ошибок его нет | lens:architect | №07 |
