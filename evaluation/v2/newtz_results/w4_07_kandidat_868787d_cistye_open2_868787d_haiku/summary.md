# Новые ТЗ №18 — W4-07 кандидат 868787d: чистые open2, 868787d, haiku

Кейсов 4, прогонов 4, не измерено 0.

**Recall —** (0/0): critical 0/0, major 0/0, minor 0/0. Вне эталона 0, дублей 0, критичных ложных 0.

Чистые версии (4): замечаний 60, из них ложных (вне фона шаблона) 55: critical 0, major 0; документов с critical 0, с > 1 замечанием 4, вердикт «нельзя» 0.

Recall по типам: .

Время 15.1 мин суммарно, вызовов 31, $0.36.

| Кейс | Версия | Статус | Найдено | Замечаний (к/с/н) | Вердикт | Мин | Вызовов |
| :--- | :--- | :--- | :--- | :--- | :--- | ---: | ---: |
| capital_clean | clean | complete | — | 13 (0/0/13) | yes/yes | 4.9 | 8 |
| grace_clean | clean | complete | — | 15 (0/0/15) | yes/yes | 4.0 | 8 |
| insurance_clean | clean | partial | — | 16 (0/0/16) | conditional/conditional | 3.2 | 6 |
| qr_clean | clean | partial | — | 16 (0/0/16) | conditional/conditional | 3.0 | 9 |

Ложные на чистых версиях:

| Кейс | Серьёзность | Тип | Замечание | Источники | Владельцы |
| :--- | :--- | :--- | :--- | :--- | :--- |
| capital_clean | minor | traceability | У требований нет приоритетов, у пунктов части B нет ID | consistency | №09 |
| capital_clean | minor | terminology | Одни и те же состояния и компоненты названы по-разному | consistency | №09 |
| capital_clean | minor | missing_element | Выбор карты на экране без метода получения списка карт | consistency | №09 |
| capital_clean | minor | incomplete | BPMN и схема вызовов без ветвей Ф-5 и Ф-6 | consistency | №09 |
| capital_clean | minor | ambiguity | Получатель выплаты при закрытии счёта на карту не определён | lens:analyst | №05 |
| capital_clean | minor | incomplete | Требование счёта в тенге (Ф-1) не проверяется логикой метода PUT | lens:architect | №07 |
| capital_clean | minor | duplicate | Правило даты смены способа продублировано в Ф-3 и шаге 4 | consistency | №09 |
| capital_clean | minor | missing_element | Критерии приёмки не покрывают границы, повторы и ошибки | lens:qa | №06 |
| capital_clean | minor | missing_element | Причина отказа от выплаты на карту для push нигде не хранится | lens:architect | №07 |
| capital_clean | minor | missing_element | Схема отката и выключения способа выплаты не описана | lens:risk | №08 |
| capital_clean | minor | ambiguity | Понятие «уже выбранного» в особом правиле 1 допускает два толкования | consistency | №09 |
| capital_clean | minor | status_conflict | Чужой cardId при CAPITALIZATION: игнорирование или 404 не определено | consistency | №09 |
| grace_clean | minor | traceability | Пункты требований без ID, приоритетов и трассировки | consistency | №09 |
| grace_clean | minor | terminology | Одни понятия названы разными терминами по разделам | consistency | №09 |
| grace_clean | minor | missing_element | Кнопка «Пополнить» не связана ни с одной операцией оплаты | consistency | №09 |
| grace_clean | minor | ambiguity | Возврат, обнуливший остаток, не определяет статус периода | lens:analyst | №05 |
| grace_clean | minor | duplicate | Правило о прогнозе процентов повторено в особых правилах API | consistency | №09 |
| grace_clean | minor | event_conflict | Напоминание, включённое после 12:00 22-го, не имеет исхода | lens:analyst | №05 |
| grace_clean | minor | incomplete | Критерии приёмки не покрывают границы и переключатель напоминания | lens:qa, consistency | №06, №09 |
| grace_clean | minor | contradiction | Платёж, зачисленный за 5 минут до запроса, не имеет исхода | lens:risk | №08 |
| grace_clean | minor | incomplete | Метод PUT включения напоминания не показан на схеме | consistency | №09 |
| grace_clean | minor | missing_element | Признак отправки напоминания за период не хранится | lens:architect | №07 |
| grace_clean | minor | api_contract | Статус льготы в API строкой, в данных признаком | lens:architect | №07 |
| grace_clean | minor | unit_mismatch | Суммы в критериях приёмки в ₸, в API в тиынах | lens:architect | №07 |
| grace_clean | minor | ops_risk | Схема отката и выключения блока не описана | lens:risk | №08 |
| grace_clean | minor | contradiction | Прогноз процентов описан для двух разных состояний | lens:architect | №07 |
| insurance_clean | minor | terminology | Терминология не едина, глоссария нет: «Страховая компания», «Компонент API кредитов», «Ста | consistency | №09 |
| insurance_clean | minor | unverifiable | Цель про долю и жалобы не имеет требования | consistency | №09 |
| insurance_clean | minor | incorrect | Архитектура и последовательность расходятся по связям | consistency | №09 |
| insurance_clean | minor | incomplete | BPMN не содержит ветки снятия страхования до подписания | consistency | №09 |
| insurance_clean | minor | other | Требованиям не назначены приоритет и стабильность | consistency | №09 |
| insurance_clean | minor | incomplete | Округление премии до тенге не задано при дробном расчёте | lens:analyst | №05 |
| insurance_clean | minor | ambiguity | Срок отказа в 14 дней: не определено, входит ли день выдачи | lens:analyst | №05 |
| insurance_clean | minor | contradiction | Не определено, можно ли оформить отказ от страхования после полного досрочного погашения и | lens:risk | №08 |
| insurance_clean | minor | duplicate | Правило повышения ставки записано дважды | consistency | №09 |
| insurance_clean | minor | boundary_conflict | Нижняя граница возраста 18 лет не проверяется в логике метода | lens:analyst | №05 |
| insurance_clean | minor | incomplete | Нижний предел 18 лет не проверяется в логике метода | consistency | №09 |
| insurance_clean | minor | missing_element | Показ причины недоступности не обеспечен API | consistency | №09 |
| insurance_clean | minor | ops_risk | Шаблон ревью требует схему отката, а в документе её нет | lens:risk | №08 |
| insurance_clean | minor | ambiguity | Порядок пп. 4 и 6 не задан при двух ошибках | consistency | №09 |
| qr_clean | minor | traceability | Требования без приоритетов и без ID в нетабличных пунктах | consistency | №09 |
| qr_clean | minor | incomplete | Цель по снижению ошибочных переводов не имеет показателя | consistency | №09 |
| qr_clean | minor | terminology | Одни и те же роли и карты названы разными терминами | consistency | №09 |
| qr_clean | minor | contradiction | Путь вызова отправителя расходится между архитектурой, sequence и API | consistency | №09 |
| qr_clean | minor | incomplete | Критерии приёмки не покрывают границы, повторы и ошибки | lens:qa | №06 |
| qr_clean | minor | incomplete | Параллельная оплата QR с суммой: исход второго перевода не определён | consistency | №09 |
| qr_clean | minor | duplicate | Срок 15 минут записан дважды в бизнес-части и API | consistency | №09 |
| qr_clean | minor | unverifiable | Нагрузка 200 переводов в секунду без периода измерения | lens:analyst | №05 |
| qr_clean | minor | incomplete | Ключ requestId и результат перевода не перечислены в хранимых данных | lens:architect | №07 |
| qr_clean | minor | incomplete | Схема отката и способа выключить QR-переводы не описаны | lens:risk | №08 |
| qr_clean | minor | incomplete | Проверка requestId не размещена в шагах логики метода | lens:analyst, lens:architect | №05, №07 |
| qr_clean | minor | incomplete | Закрытая карта получателя: метод данных QR не описывает ошибку | consistency | №09 |
| qr_clean | minor | contradiction | Пример успешного ответа показывает сумму запроса, а не QR-кода | lens:architect | №07 |
| qr_clean | minor | api_contract | Тело ошибки метода 1 не отделено от успешного ответа | lens:architect | №07 |
| qr_clean | minor | api_contract | Методы 2–4 не описывают тело ответов 400, 404 и 410 | lens:architect | №07 |
