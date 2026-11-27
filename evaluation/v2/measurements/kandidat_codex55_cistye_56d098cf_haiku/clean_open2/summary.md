# Новые ТЗ №18 — кандидат codex55 чистые: чистые open2, 56d098cf, haiku

Кейсов 4, прогонов 4, не измерено 0.

**Recall —** (0/0): critical 0/0, major 0/0, minor 0/0. Вне эталона 0, дублей 0, критичных ложных 0.

Чистые версии (4): замечаний 66, из них ложных (вне фона шаблона) 62: critical 1, major 6; документов с critical 1, с > 1 замечанием 4, вердикт «нельзя» 1.

Recall по типам: .

Время 13.7 мин суммарно, вызовов 33, $0.38.

| Кейс | Версия | Статус | Найдено | Замечаний (к/с/н) | Вердикт | Мин | Вызовов |
| :--- | :--- | :--- | :--- | :--- | :--- | ---: | ---: |
| capital_clean | clean | complete | — | 17 (0/1/16) | yes/yes | 3.0 | 8 |
| grace_clean | clean | complete | — | 14 (0/0/14) | yes/yes | 3.6 | 8 |
| insurance_clean | clean | complete | — | 17 (1/5/11) | no/no | 3.9 | 9 |
| qr_clean | clean | complete | — | 18 (0/0/18) | yes/yes | 3.2 | 8 |

Ложные на чистых версиях:

| Кейс | Серьёзность | Тип | Замечание | Источники | Владельцы |
| :--- | :--- | :--- | :--- | :--- | :--- |
| capital_clean | major | ambiguity | Закрытие счёта: способ и карта выплаты процентов не определены | lens:analyst, lens:risk, consistency | №05, №08, №09 |
| capital_clean | minor | traceability | Пункты требований без ID и приоритетов | consistency | №09 |
| capital_clean | minor | terminology | Одни понятия названы разными терминами в разных разделах | consistency | №09 |
| capital_clean | minor | unverifiable | Цель по снижению обращений без порога и периода | consistency | №09 |
| capital_clean | minor | incomplete | Схема API не показывает сервис уведомлений из архитектуры | consistency | №09 |
| capital_clean | minor | incomplete | Экран «Проценты»: нет правила при «На карту» без выбранной карты | lens:analyst, lens:qa | №05, №06 |
| capital_clean | minor | missing_element | Экран выбора карты без описанного источника списка карт | consistency | №09 |
| capital_clean | minor | incomplete | Проверка валюты счёта из Ф-1 отсутствует в логике метода | lens:architect | №07 |
| capital_clean | minor | ambiguity | «Клиент» для карты: владелец счёта или держатель карты не определён | lens:risk | №08 |
| capital_clean | minor | ambiguity | Момент выплаты последнего дня месяца не привязан к начислению | lens:analyst | №05 |
| capital_clean | minor | ambiguity | Дата effectiveFrom без часового пояса при смене в конце месяца | lens:architect | №07 |
| capital_clean | minor | incomplete | Причины закрытия карты в push не перечислены | lens:analyst | №05 |
| capital_clean | minor | missing_element | Критерии приёмки покрывают не все функциональные требования | lens:qa | №06 |
| capital_clean | minor | missing_element | Схема отката или выключения функции не описана | lens:risk | №08 |
| capital_clean | minor | missing_element | Смена карты для выплаты: какая карта действует в текущем месяце | lens:architect | №07 |
| capital_clean | minor | api_contract | Ответ метода условий для закрытого счёта не описан | lens:architect, consistency | №07, №09 |
| grace_clean | minor | traceability | Требования без ID и приоритетов | consistency | №09 |
| grace_clean | minor | ops_risk | Схема отката или скрытия функции не описана | lens:risk | №08 |
| grace_clean | minor | unverifiable | Цель снизить долю потерь без числа и порога | consistency | №09 |
| grace_clean | minor | terminology | Одни и те же понятия названы по-разному, глоссария нет | consistency | №09 |
| grace_clean | minor | ambiguity | Момент перехода льготного периода в LOST не определён | lens:analyst, lens:qa | №05, №06 |
| grace_clean | minor | missing_element | Кнопка «Пополнить» на экране не связана с операцией | consistency | №09 |
| grace_clean | minor | incomplete | Время формирования выписки 1-го числа не задано | lens:analyst | №05 |
| grace_clean | minor | ambiguity | Возврат, полностью закрывший долг, не определяет статус периода | lens:analyst | №05 |
| grace_clean | minor | missing_element | Прогноз процентов нельзя вычислить из данных метода 1 | lens:architect | №07 |
| grace_clean | minor | ambiguity | Момент проверки оплаты в окне напоминания не задан | lens:analyst | №05 |
| grace_clean | minor | incomplete | Критерии приёмки покрывают не все правила и ветки | lens:qa, consistency | №06, №09 |
| grace_clean | minor | incomplete | Судьба излишка при переплате не описана | lens:analyst | №05 |
| grace_clean | minor | incomplete | Схема вызова не показывает метод отключения напоминания | consistency | №09 |
| insurance_clean | critical | contradiction | Возврат премии при погашении и отказе в 14 дней не определён | lens:risk, consistency | №08, №09 |
| insurance_clean | major | contradiction | Повторный вызов для подписанной заявки: 200 или 409 | lens:analyst | №05 |
| insurance_clean | major | missing_element | Нижний возрастной порог 18 лет не проверяется логикой метода | lens:analyst, lens:qa, lens:architect, consistency | №05, №06, №07, №09 |
| insurance_clean | major | contradiction | Архитектура расходится с sequence и схемой метода по вызову страхования | consistency | №09 |
| insurance_clean | major | ambiguity | Правило округления премии до тенге не задано | lens:analyst | №05 |
| insurance_clean | major | incomplete | Счёт и срок возврата части премии при погашении не заданы | lens:analyst | №05 |
| insurance_clean | minor | missing_element | Нет ID и приоритетов у требований и пунктов API | consistency | №09 |
| insurance_clean | minor | terminology | Названия страховой компании и приложения не едины | consistency | №09 |
| insurance_clean | minor | unverifiable | Цель про отсутствие жалоб не измеряется требованиями | consistency | №09 |
| insurance_clean | minor | incomplete | Экраны условий и «Страхование» без ошибок, границ и пустых состояний | lens:analyst | №05 |
| insurance_clean | minor | non_singular | Пункты Ф-1, Ф-4 и шага 6 объединяют несколько правил | lens:analyst | №05 |
| insurance_clean | minor | duplicate | Ставка после отказа описана в Ф-4 и в особых правилах | consistency | №09 |
| insurance_clean | minor | unverifiable | НФТ 2 с не привязан к нагрузке и периоду измерения | lens:analyst | №05 |
| insurance_clean | minor | missing_element | Дата согласия pd_consent_at не входит в перечень хранимых данных | lens:architect | №07 |
| insurance_clean | minor | incomplete | Критерии приёмки покрывают 6 из 12 функциональных требований | lens:qa | №06 |
| insurance_clean | minor | missing_element | Схема отката и способ скрыть функцию не описаны | lens:risk | №08 |
| qr_clean | minor | unverifiable | Цель перевода по QR без числового показателя | consistency | №09 |
| qr_clean | minor | contradiction | Последовательность вызывает сервис переводов в обход QR-контроллера | lens:architect, consistency | №07, №09 |
| qr_clean | minor | terminology | Одни понятия названы разными терминами, глоссария нет | consistency | №09 |
| qr_clean | minor | incomplete | Экран подтверждения не описывает ошибку ввода суммы | lens:qa | №06 |
| qr_clean | minor | incomplete | Функциональные требования Ф-1…Ф-6 без приоритетов | consistency | №09 |
| qr_clean | minor | ambiguity | Статус QR с суммой после REJECTED не определён, шаг 6 блокирует повтор | lens:analyst | №05 |
| qr_clean | minor | ambiguity | Состояние QR с суммой после ответа 500 не определено | lens:qa | №06 |
| qr_clean | minor | incomplete | Одновременная оплата QR с суммой не защищена от гонки | consistency | №09 |
| qr_clean | minor | duplicate | Срок 15 минут записан в двух местах | consistency | №09 |
| qr_clean | minor | unverifiable | Нагрузка 200 переводов в секунду без критерия успеха | lens:analyst | №05 |
| qr_clean | minor | missing_element | Ключ requestId и результат первого перевода не хранятся | lens:architect | №07 |
| qr_clean | minor | incomplete | Критерии приёмки покрывают малую часть требований | lens:qa | №06 |
| qr_clean | minor | ops_risk | Схема отката функции перевода по QR-коду не описана | lens:risk | №08 |
| qr_clean | minor | security | Данные QR-кода отдаются без проверки владения | lens:risk | №08 |
| qr_clean | minor | incomplete | Шаг проверки requestId не включён в логику метода | lens:architect | №07 |
| qr_clean | minor | contradiction | Чужая карта: код 400 в переводе и 404 при создании QR | consistency | №09 |
| qr_clean | minor | ambiguity | Состояние карты получателя при переводе не покрыто | lens:analyst | №05 |
