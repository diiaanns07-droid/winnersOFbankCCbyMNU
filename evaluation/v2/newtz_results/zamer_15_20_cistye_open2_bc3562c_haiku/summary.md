# Новые ТЗ №18 — замер 15:20: чистые open2, bc3562c, haiku

Кейсов 4, прогонов 4, не измерено 0.

**Recall —** (0/0): critical 0/0, major 0/0, minor 0/0. Вне эталона 0, дублей 0, критичных ложных 0.

Чистые версии (4): замечаний 61, из них ложных (вне фона шаблона) 56: critical 0, major 10; документов с critical 0, с > 1 замечанием 4, вердикт «нельзя» 0.

Recall по типам: .

Время 15.4 мин суммарно, вызовов 34, $0.413.

| Кейс | Версия | Статус | Найдено | Замечаний (к/с/н) | Вердикт | Мин | Вызовов |
| :--- | :--- | :--- | :--- | :--- | :--- | ---: | ---: |
| capital_clean | clean | complete | — | 16 (0/0/16) | yes/yes | 2.6 | 9 |
| grace_clean | clean | complete | — | 15 (0/3/12) | conditional/yes | 5.5 | 8 |
| insurance_clean | clean | complete | — | 16 (0/5/11) | conditional/yes | 3.4 | 8 |
| qr_clean | clean | complete | — | 14 (0/2/12) | yes/yes | 3.9 | 9 |

Ложные на чистых версиях:

| Кейс | Серьёзность | Тип | Замечание | Источники | Владельцы |
| :--- | :--- | :--- | :--- | :--- | :--- |
| capital_clean | minor | incomplete | Цель по обращениям в контакт-центр не измерима и не подкреплена | consistency | №09 |
| capital_clean | minor | missing_element | Схема отката и скрытия функции в документе отсутствует | lens:risk | №08 |
| capital_clean | minor | incomplete | Документ не рассматривает ряд случаев | lens:analyst | №05 |
| capital_clean | minor | terminology | Ключевые термины в документе называются по-разному | consistency | №09 |
| capital_clean | minor | missing_element | Выбор карты на экране без источника списка карт | consistency | №09 |
| capital_clean | minor | incomplete | BPMN-схема процесса не показывает ветви Ф-4, Ф-5 и Ф-6 | consistency | №09 |
| capital_clean | minor | other | Функциональные требования Ф-1…Ф-6 не имеют приоритетов | consistency | №09 |
| capital_clean | minor | ambiguity | accruedInterest на дату запроса расходится с Ф-2 по текущему дню | consistency | №09 |
| capital_clean | minor | contradiction | Режим выплаты записывается в текущий месяц, а не в следующий | lens:architect | №07 |
| capital_clean | minor | incomplete | Критерии приёмки покрывают 6 из 11 функциональных требований | lens:qa | №06 |
| capital_clean | minor | ambiguity | Карта «неактивна» при выплате не покрыта правилом Ф-5 | lens:analyst | №05 |
| capital_clean | minor | missing_element | Не определено, куда уходит остаток при закрытии счёта | lens:analyst | №05 |
| capital_clean | minor | ambiguity | Правило округления ровно половины тиына не определено | lens:analyst | №05 |
| capital_clean | minor | missing_element | next_payout_mode не включён в перечень хранимых данных | lens:architect | №07 |
| capital_clean | minor | api_contract | Тип и условия payoutCardId в ответе метода 2 не описаны | lens:architect | №07 |
| grace_clean | major | ambiguity | Момент формирования выписки 1-го числа не задан | lens:analyst, consistency | №05, №09 |
| grace_clean | major | incomplete | Прогноз процентов не задан ставкой и датой расчёта | lens:analyst | №05 |
| grace_clean | major | incomplete | Состав блока при утраченном льготном периоде не описан | lens:analyst | №05 |
| grace_clean | minor | incomplete | Цель обещает сумму к внесению, НФТ исключает 5 минут | consistency | №09 |
| grace_clean | minor | terminology | Термины компонентов и сумм называются по-разному | lens:architect, consistency | №07, №09 |
| grace_clean | minor | missing_element | Кнопка «Пополнить» без описания действия | consistency | №09 |
| grace_clean | minor | other | Функциональные требования не имеют приоритетов | consistency | №09 |
| grace_clean | minor | duplicate | Правило прогноза процентов продублировано в особых правилах | consistency | №09 |
| grace_clean | minor | ambiguity | Момент проверки оплаты для напоминания не назван | lens:analyst | №05 |
| grace_clean | minor | incomplete | Критерии приёмки покрывают только основной путь | lens:qa | №06 |
| grace_clean | minor | unit_mismatch | Суммы в ₸ в приёмке и тиыны в API не сопоставлены | lens:architect | №07 |
| grace_clean | minor | ops_risk | Нет схемы отката и способа скрыть блок льготного периода | lens:risk | №08 |
| grace_clean | minor | ambiguity | Счёт дней до окончания не задан на день 25-го | lens:analyst | №05 |
| grace_clean | minor | missing_element | Метод 2 отсутствует на схеме API и в sequence-диаграмме | consistency | №09 |
| insurance_clean | major | incomplete | Нижняя граница 18 лет из Ф-6 не проверяется в методе | lens:architect, consistency, lens:analyst | №05, №07, №09 |
| insurance_clean | major | missing_element | Ф-5: нет события погашения и суммы возврата для сервиса страхования | lens:architect | №07 |
| insurance_clean | major | incomplete | Ф-5: не указаны счёт и срок возврата премии при погашении | lens:analyst | №05 |
| insurance_clean | major | ambiguity | Ф-5: «полное досрочное погашение» — не определён момент события | lens:risk | №08 |
| insurance_clean | major | contradiction | Повторный вызов после подписания: 200 или 409 не определено | consistency, lens:analyst | №05, №09 |
| insurance_clean | minor | incomplete | Цель про жалобы и долю кредитов не имеет измеримого показателя | consistency | №09 |
| insurance_clean | minor | terminology | Терминология не единая: клиентский канал, партнёр, номер полиса | consistency | №09 |
| insurance_clean | minor | incomplete | Схемы процесса и API не показывают снятие и методы 2–5 | consistency | №09 |
| insurance_clean | minor | incomplete | Нет ID у нефункциональных пунктов и приоритетов у Ф-1…Ф-6 | consistency | №09 |
| insurance_clean | minor | unit_mismatch | Премия: дробное значение по Ф-2 и целочисленный тип без округления | lens:analyst | №05 |
| insurance_clean | minor | ambiguity | Срок 14 дней: не сказано, входит ли день выдачи | lens:analyst | №05 |
| insurance_clean | minor | duplicate | Правило повышения ставки продублировано в Ф-4 и особых правилах | consistency | №09 |
| insurance_clean | minor | incomplete | Поля loan_amount, loan_term, pd_consent_at не в перечне данных | lens:architect | №07 |
| insurance_clean | minor | incomplete | Критерии приёмки покрывают 6 из 12 функциональных требований | lens:qa | №06 |
| insurance_clean | minor | missing_element | Схема отката или выключения функции в документе отсутствует | lens:risk | №08 |
| qr_clean | major | contradiction | Повтор requestId и проверка оплаты QR дают разный ответ | lens:analyst, lens:architect | №05, №07 |
| qr_clean | major | incomplete | Модель данных не содержит состояния «в обработке» и возврата после REJECTED | consistency, lens:architect | №07, №09 |
| qr_clean | minor | incomplete | Цель по снижению ошибочных переводов не измерима | consistency | №09 |
| qr_clean | minor | terminology | Один компонент и одна роль названы разными терминами | consistency | №09 |
| qr_clean | minor | contradiction | Маршрут перевода: через сервис QR-кодов или напрямую | consistency | №09 |
| qr_clean | minor | incomplete | Параллельная оплата QR с суммой не защищена от двойного списания | consistency | №09 |
| qr_clean | minor | duplicate | Срок 15 минут задан в двух местах | consistency | №09 |
| qr_clean | minor | missing_element | Push получателю не содержит источника имени отправителя | lens:architect | №07 |
| qr_clean | minor | unverifiable | Нагрузка 200 переводов в секунду без периода и доли ответов | lens:analyst | №05 |
| qr_clean | minor | ambiguity | Момент перехода QR в статус «истёк» не задан | lens:analyst | №05 |
| qr_clean | minor | incomplete | Приёмка не проверяет границы сумм, срок 10:15 и отказ антифрода | lens:qa | №06 |
| qr_clean | minor | missing_element | Схема отката и способ выключить функцию не описаны | lens:risk | №08 |
