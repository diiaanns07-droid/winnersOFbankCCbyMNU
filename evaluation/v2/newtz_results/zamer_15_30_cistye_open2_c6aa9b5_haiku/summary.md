# Новые ТЗ №18 — замер 15:30: чистые open2, c6aa9b5, haiku

Кейсов 4, прогонов 4, не измерено 0.

**Recall —** (0/0): critical 0/0, major 0/0, minor 0/0. Вне эталона 0, дублей 0, критичных ложных 0.

Чистые версии (4): замечаний 68, из них ложных (вне фона шаблона) 63: critical 1, major 11; документов с critical 1, с > 1 замечанием 4, вердикт «нельзя» 1.

Recall по типам: .

Время 16.2 мин суммарно, вызовов 29, $0.447.

| Кейс | Версия | Статус | Найдено | Замечаний (к/с/н) | Вердикт | Мин | Вызовов |
| :--- | :--- | :--- | :--- | :--- | :--- | ---: | ---: |
| capital_clean | clean | complete | — | 19 (0/1/18) | yes/yes | 4.2 | 7 |
| grace_clean | clean | complete | — | 15 (0/1/14) | yes/yes | 4.0 | 7 |
| insurance_clean | clean | complete | — | 20 (1/8/11) | no/no | 4.9 | 8 |
| qr_clean | clean | complete | — | 14 (0/1/13) | yes/yes | 3.1 | 7 |

Ложные на чистых версиях:

| Кейс | Серьёзность | Тип | Замечание | Источники | Владельцы |
| :--- | :--- | :--- | :--- | :--- | :--- |
| capital_clean | major | incomplete | Закрытие счёта в режиме «На карту»: получатель процентов не определён | lens:risk, lens:analyst, consistency | №05, №08, №09 |
| capital_clean | minor | terminology | Одни и те же понятия названы разными терминами | consistency, lens:architect | №07, №09 |
| capital_clean | minor | other | Требования, методы и НФТ без идентификаторов и приоритетов | consistency | №09 |
| capital_clean | minor | unverifiable | Цель по обращениям в контакт-центр не привязана к требованию | consistency | №09 |
| capital_clean | minor | missing_element | Нет метода получения списка карт для выбора выплаты | consistency | №09 |
| capital_clean | minor | incomplete | Схема процесса линейна: нет ветвей блокировки, порога и закрытия | consistency, lens:architect | №07, №09 |
| capital_clean | minor | missing_element | Проверка счёта в тенге из Ф-1 отсутствует в логике метода | lens:architect | №07 |
| capital_clean | minor | ambiguity | Проценты «на дату запроса»: входит ли текущий незавершённый день | lens:analyst | №05 |
| capital_clean | minor | ambiguity | Момент выплаты за последний день не согласован с начислением | lens:risk | №08 |
| capital_clean | minor | duplicate | Правило даты вступления нового способа продублировано в методе | consistency | №09 |
| capital_clean | minor | incomplete | Критерии приёмки не покрывают границы, ошибки и повторы | lens:qa | №06 |
| capital_clean | minor | incomplete | Карта неактивна, но не закрыта и не заблокирована: выплата не описана | lens:analyst | №05 |
| capital_clean | minor | missing_element | Событие выплаты не содержит суммы, способа и причины для push | lens:architect | №07 |
| capital_clean | minor | unverifiable | Не задана нагрузка для норматива времени ответа API | lens:analyst | №05 |
| capital_clean | minor | missing_element | История начислений не хранит способ выплаты прошлых месяцев | lens:architect | №07 |
| capital_clean | minor | missing_element | Нет схемы отката и способа выключить выплату по способу | lens:risk | №08 |
| capital_clean | minor | ambiguity | Смена карты при повторной установке способа CARD не определена | lens:analyst | №05 |
| capital_clean | minor | ambiguity | Чужая неактивная карта: ответ 400 или 404 не определён | consistency | №09 |
| grace_clean | major | ambiguity | Напоминание, включённое после окна 22-го, не описано | lens:analyst, consistency | №05, №09 |
| grace_clean | minor | incomplete | Документ не рассматривает ряд случаев | consistency, lens:analyst | №05, №09 |
| grace_clean | minor | unverifiable | Цель без числа: снижение потерь льготного периода не измеряется | consistency | №09 |
| grace_clean | minor | terminology | Одни и те же понятия названы разными терминами | consistency, lens:analyst | №05, №09 |
| grace_clean | minor | missing_element | Кнопка «Пополнить» на экране без описанного действия | consistency | №09 |
| grace_clean | minor | ambiguity | Ответ до выписки: прошедший период и daysLeft не согласованы | lens:analyst | №05 |
| grace_clean | minor | duplicate | Дата окончания платёжного периода задана в Ф-1 и Ф-5 | consistency | №09 |
| grace_clean | minor | missing_element | Прогноз процентов нельзя рассчитать: данных о покупках нет | lens:architect | №07 |
| grace_clean | minor | non_singular | Ф-5 объединяет несколько независимо проверяемых правил | lens:analyst | №05 |
| grace_clean | minor | missing_element | Приёмка покрывает четыре сценария, границы и ошибки пропущены | lens:qa | №06 |
| grace_clean | minor | unit_mismatch | Суммы в приёмке в тенге, в API в тиынах без пересчёта | lens:architect | №07 |
| grace_clean | minor | ops_risk | Нет схемы отката и способа скрыть блок и напоминания | lens:risk | №08 |
| grace_clean | minor | ambiguity | Порядок проверок 404 и 422 для чужой некредитной карты не задан | consistency | №09 |
| insurance_clean | critical | contradiction | Двойной возврат премии при отказе после полного погашения | lens:risk, consistency | №08, №09 |
| insurance_clean | major | contradiction | Маршрут вызова сервиса страхования различается в схемах | consistency | №09 |
| insurance_clean | major | incomplete | Нижний возрастной предел 18 лет не проверяется в логике метода | lens:analyst, consistency | №05, №09 |
| insurance_clean | major | missing_element | Событие полного досрочного погашения не описано в интеграции | lens:architect | №07 |
| insurance_clean | major | incomplete | Не описан возврат премии, если полис не выпущен | lens:risk | №08 |
| insurance_clean | major | contradiction | Расчёт премии передаёт ПДн страховщику без согласия | lens:architect | №07 |
| insurance_clean | major | terminology | Участник страхования назван тремя разными терминами | consistency | №09 |
| insurance_clean | major | missing_element | Расчёт стоимости не описывает отказ по возрасту или страховщику | lens:architect | №07 |
| insurance_clean | major | status_conflict | Код 409 в методе отказа имеет другой смысл, чем в общей таблице | lens:architect | №07 |
| insurance_clean | minor | traceability | Приоритеты и ID требований в документе не заданы | consistency | №09 |
| insurance_clean | minor | terminology | Названия компонентов и периода отказа не едины | consistency | №09 |
| insurance_clean | minor | unverifiable | Цель по доле страхования и жалобам не измеряется | consistency | №09 |
| insurance_clean | minor | ambiguity | Не задано правило округления премии до тенге | lens:analyst | №05 |
| insurance_clean | minor | ambiguity | Не сказано, входит ли 14-й день в срок отказа | lens:analyst | №05 |
| insurance_clean | minor | duplicate | Правило повышения ставки записано в двух местах | consistency | №09 |
| insurance_clean | minor | incomplete | Событие выдачи кредита не содержит идентификатор и дату | lens:architect | №07 |
| insurance_clean | minor | missing_element | Поля согласия, суммы и срока не перечислены в данных | lens:architect | №07 |
| insurance_clean | minor | incomplete | Критерии приёмки покрывают 6 из 14 функциональных требований | lens:qa | №06 |
| insurance_clean | minor | incomplete | Повторный вызов после снятия страхования не определён | lens:analyst, consistency | №05, №09 |
| qr_clean | major | contradiction | Маршрут вызова перевода: напрямую или через сервис QR-кодов | lens:architect, consistency | №07, №09 |
| qr_clean | minor | unverifiable | Цель без измеримого показателя не связана с требованием | consistency | №09 |
| qr_clean | minor | terminology | Одни понятия названы разными терминами в документе | consistency | №09 |
| qr_clean | minor | incomplete | Функциональные требования Ф-1…Ф-6 без приоритетов | consistency | №09 |
| qr_clean | minor | missing_element | Параллельная оплата QR-кода с суммой не описана | consistency | №09 |
| qr_clean | minor | duplicate | Срок действия 15 минут задан в двух местах | consistency | №09 |
| qr_clean | minor | unverifiable | Нагрузка 200 переводов в секунду без условия успеха | lens:analyst | №05 |
| qr_clean | minor | missing_element | Поля requestId и cardId не перечислены в данных QR-кода | lens:architect | №07 |
| qr_clean | minor | missing_element | Состояние «в обработке» не входит в статусы QR-кода | consistency | №09 |
| qr_clean | minor | incomplete | Критерии приёмки покрывают малую часть ошибочных веток | lens:qa | №06 |
| qr_clean | minor | incomplete | Нет схемы отката и способа выключить QR-переводы | lens:risk | №08 |
| qr_clean | minor | contradiction | Поле amount без суммы в QR: необязательно или обязательно | consistency | №09 |
| qr_clean | minor | api_contract | Тело ответа ошибки не содержит обещанных полей status | lens:architect | №07 |
