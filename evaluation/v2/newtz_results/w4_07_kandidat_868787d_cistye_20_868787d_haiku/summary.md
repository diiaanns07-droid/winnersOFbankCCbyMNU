# Новые ТЗ №18 — W4-07 кандидат 868787d: чистые №20, 868787d, haiku

Кейсов 8, прогонов 8, не измерено 4.

**Recall —** (0/0): critical 0/0, major 0/0, minor 0/0. Вне эталона 0, дублей 0, критичных ложных 0.

Чистые версии (4): замечаний 48, из них ложных (вне фона шаблона) 48: critical 1, major 6; документов с critical 1, с > 1 замечанием 4, вердикт «нельзя» 1.

Recall по типам: .

Время 15.5 мин суммарно, вызовов 42, $0.425.

| Кейс | Версия | Статус | Найдено | Замечаний (к/с/н) | Вердикт | Мин | Вызовов |
| :--- | :--- | :--- | :--- | :--- | :--- | ---: | ---: |
| capital_v2 | clean | complete | — | 12 (0/1/11) | yes/yes | 3.3 | 8 |
| fx | clean | complete | — | 13 (1/4/8) | no/no | 5.7 | 10 |
| grace_v2 | clean | complete | — | 18 (0/1/17) | yes/yes | 3.8 | 9 |
| insurance_v2 | clean | partial | — | 5 (0/0/5) | conditional/conditional | 1.6 | 6 |
| qr_v2 | clean | failed | — | 0 (0/0/0) | none/none | 1.0 | 6 |
| repay | clean | failed | — | 0 (0/0/0) | none/none | 0.0 | 1 |
| roundup | clean | failed | — | 4 (1/2/1) | none/none | 0.0 | 1 |
| statement | clean | failed | — | 4 (0/4/0) | none/none | 0.0 | 1 |

Ложные на чистых версиях:

| Кейс | Серьёзность | Тип | Замечание | Источники | Владельцы |
| :--- | :--- | :--- | :--- | :--- | :--- |
| capital_v2 | major | incomplete | Выплата при закрытии счёта в режиме «На карту» не определена | lens:analyst, consistency | №05, №09 |
| capital_v2 | minor | traceability | Пункты документа без ID и приоритетов, трассировка по тексту | consistency | №09 |
| capital_v2 | minor | unverifiable | Цель по обращениям в контакт-центр без числового показателя | consistency | №09 |
| capital_v2 | minor | terminology | Терминология документа не едина, глоссария нет | consistency | №09 |
| capital_v2 | minor | missing_element | Экран выбора карты не обеспечен списком карт в API | consistency | №09 |
| capital_v2 | minor | incomplete | Схемы процесса и последовательности не показывают ветви Ф-5 и Ф-6 | consistency | №09 |
| capital_v2 | minor | incomplete | Метод смены способа не проверяет валюту счёта | lens:architect | №07 |
| capital_v2 | minor | event_conflict | Смена карты без смены способа: дата действия не определена | lens:analyst | №05 |
| capital_v2 | minor | missing_element | Перечень данных не различает текущий и следующий способ выплаты | lens:architect | №07 |
| capital_v2 | minor | duplicate | Правило даты смены способа продублировано в двух разделах | consistency | №09 |
| capital_v2 | minor | incomplete | Закрытие счёта с неактивной картой: получатель выплаты не задан | lens:risk | №08 |
| capital_v2 | minor | missing_element | Критерии приёмки покрывают 5 из 12 функциональных требований | lens:qa | №06 |
| fx | critical | event_conflict | Срок котировки в таймере считается от ответа, а в Ф-7 — от запроса | lens:qa, consistency | №06, №09 |
| fx | major | contradiction | Повторный обмен по котировке до подтверждения отмены проводки | lens:architect, consistency | №07, №09 |
| fx | major | incomplete | Ответ АБС на отмену невыполненной проводки не описан | lens:architect | №07 |
| fx | major | api_contract | Код 404 для счёта: пример ответа и шаг 2 расходятся | lens:architect, consistency | №07, №09 |
| fx | major | contradiction | НФ-1 по методу 2 (1 с) противоречит таймаутам И-2 | lens:analyst | №05 |
| fx | minor | incomplete | Цель 60 % не имеет требования на отчёт по обменам | consistency | №09 |
| fx | minor | terminology | Срок котировки назван тремя разными формулировками | consistency | №09 |
| fx | minor | incomplete | BPMN не показывает повтор метода 1 при таймауте 15 с | consistency | №09 |
| fx | minor | unverifiable | NF-3 «круглосуточно» не задаёт точку замера доступности | lens:qa | №06 |
| fx | minor | duplicate | Срок хранения ключа 24 часа задан в двух местах | consistency | №09 |
| fx | minor | incomplete | Повтор push без ключа — возможен дубль уведомления | lens:architect | №07 |
| fx | minor | incomplete | Приёмка не покрывает EUR, RUB→KZT и нижнюю границу KZT | lens:qa | №06 |
| fx | minor | incomplete | Откат не покрывает котировки и обмены в обработке | consistency | №09 |
| grace_v2 | major | incomplete | Период после 25-го до выписки: срок, статус и daysLeft не определены | lens:analyst, lens:risk | №05, №08 |
| grace_v2 | minor | traceability | У требований нет идентификаторов и приоритетов | consistency | №09 |
| grace_v2 | minor | unverifiable | Цель снизить долю клиентов без измеримого показателя | consistency | №09 |
| grace_v2 | minor | terminology | Компоненты и термины названы по-разному, глоссария нет | lens:architect, consistency | №07, №09 |
| grace_v2 | minor | missing_element | Кнопка «Пополнить» в блоке без описанной операции | consistency | №09 |
| grace_v2 | minor | ambiguity | 55 дней от покупки и срок 25-го числа: что определяет льготу | lens:risk | №08 |
| grace_v2 | minor | ambiguity | Состав «покупок» не определён: коммунальные и валютные платежи | lens:risk | №08 |
| grace_v2 | minor | duplicate | Правило прогноза процентов дублируется в Ф-3 и особых правилах | consistency | №09 |
| grace_v2 | minor | ambiguity | Момент проверки остатка для напоминания не задан внутри окна | lens:analyst | №05 |
| grace_v2 | minor | event_conflict | Платёж до выписки: Ф-5 учитывает, шаг 3 выборку ограничивает датой выписки | lens:analyst | №05 |
| grace_v2 | minor | missing_element | Отмена внесённого платежа не описана | consistency | №09 |
| grace_v2 | minor | event_conflict | Напоминание: отправка при запросе или однократно 22-го числа | lens:architect | №07 |
| grace_v2 | minor | incomplete | Критерии приёмки покрывают 4 из 11 функциональных требований | lens:qa | №06 |
| grace_v2 | minor | unit_mismatch | Сумма в критерии приёмки в тенге, поле API в тиынах | lens:architect | №07 |
| grace_v2 | minor | missing_element | totalDebt не включает покупки после выписки: шаг 3 их не получает | lens:architect | №07 |
| grace_v2 | minor | missing_element | Прогноз процентов не рассчитывается: нет шага и входных данных | lens:architect | №07 |
| grace_v2 | minor | contradiction | Прогноз процентов: частичное погашение или полное невнесение | lens:architect | №07 |
| grace_v2 | minor | incomplete | Метод переключения напоминания не показан на схеме | consistency | №09 |
| insurance_v2 | minor | boundary_conflict | Пример refundUntil даёт 19 марта, правило даёт 15 марта | lens:analyst | №05 |
| insurance_v2 | minor | ambiguity | Не определено, какое событие считается «кредит погашен полностью»: инициация или зачислени | lens:risk | №08 |
| insurance_v2 | minor | unverifiable | Нагрузка не задана для требования времени ответа 2 с | lens:analyst | №05 |
| insurance_v2 | minor | missing_element | Критерии приёмки проверяют 6 из 13 функциональных требований | lens:qa | №06 |
| insurance_v2 | minor | incomplete | Повторный вызов с новой суммой: исход при ошибках не задан | lens:analyst | №05 |
