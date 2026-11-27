# Новые ТЗ №18 — релиз-w4 18:55 чистые: чистые №20, 3e7133c, haiku

Кейсов 8, прогонов 8, не измерено 0.

**Recall —** (0/0): critical 0/0, major 0/0, minor 0/0. Вне эталона 0, дублей 0, критичных ложных 0.

Чистые версии (8): замечаний 114, из них ложных (вне фона шаблона) 114: critical 3, major 21; документов с critical 3, с > 1 замечанием 8, вердикт «нельзя» 3.

Recall по типам: .

Время 34.5 мин суммарно, вызовов 75, $0.993.

| Кейс | Версия | Статус | Найдено | Замечаний (к/с/н) | Вердикт | Мин | Вызовов |
| :--- | :--- | :--- | :--- | :--- | :--- | ---: | ---: |
| capital_v2 | clean | complete | — | 15 (0/0/15) | yes/yes | 2.9 | 8 |
| fx | clean | complete | — | 15 (1/7/7) | no/no | 5.6 | 11 |
| grace_v2 | clean | complete | — | 17 (0/0/17) | yes/yes | 3.7 | 8 |
| insurance_v2 | clean | complete | — | 19 (1/6/12) | no/no | 4.0 | 9 |
| qr_v2 | clean | complete | — | 12 (0/1/11) | yes/yes | 2.7 | 8 |
| repay | clean | complete | — | 14 (0/1/13) | yes/yes | 5.9 | 10 |
| roundup | clean | complete | — | 10 (0/1/9) | yes/yes | 5.2 | 10 |
| statement | clean | complete | — | 12 (1/5/6) | no/no | 4.4 | 11 |

Ложные на чистых версиях:

| Кейс | Серьёзность | Тип | Замечание | Источники | Владельцы |
| :--- | :--- | :--- | :--- | :--- | :--- |
| capital_v2 | minor | incomplete | Цель снижения обращений не имеет числа и метрики | consistency | №09 |
| capital_v2 | minor | terminology | Терминология не единообразна: три понятия названы по-разному | consistency | №09 |
| capital_v2 | minor | missing_element | Выбор карты в UI без метода получения списка карт | consistency | №09 |
| capital_v2 | minor | incomplete | Счёт в тенге: Ф-1 не проверяется логикой метода | lens:architect | №07 |
| capital_v2 | minor | ambiguity | Смена карты в середине месяца: неясно, на какую карту выплата | lens:analyst | №05 |
| capital_v2 | minor | other | Правило даты начала действия продублировано в двух местах | consistency | №09 |
| capital_v2 | minor | incomplete | Критерии приёмки покрывают 5 из 12 функциональных требований | lens:qa | №06 |
| capital_v2 | minor | missing_element | Push при неактивной карте: причины нет в данных и событии | lens:architect | №07 |
| capital_v2 | minor | contradiction | Закрытие счёта с неактивной картой: Ф-5 и Ф-6 расходятся | lens:risk | №08 |
| capital_v2 | minor | incomplete | Закрытие счёта в режиме «На карту»: способ выплаты не назван | lens:analyst | №05 |
| capital_v2 | minor | unverifiable | Нефункциональное требование не задаёт нагрузку и объект доступности | lens:analyst | №05 |
| capital_v2 | minor | other | Приоритеты требований в документе не указаны и не ранжированы | consistency | №09 |
| capital_v2 | minor | incomplete | Чек-лист ИБ отмечен «Да», но в документе отсутствует | lens:risk | №08 |
| capital_v2 | minor | incomplete | Условие 404 не называет несуществующую карту | lens:architect | №07 |
| capital_v2 | minor | incomplete | Закрытый счёт: метод 2 не описывает код 404 как метод 1 | consistency | №09 |
| fx | critical | contradiction | Момент истечения котировки: экран по ответу и Ф-7 по запросу | consistency | №09 |
| fx | major | infeasible | АБС не доработана, но требуется поведение отмены и ключа | consistency | №09 |
| fx | major | ops_risk | Котировка ACTIVE после таймаута допускает второй обмен | lens:risk | №08 |
| fx | major | contradiction | Отмена проводки: 500 до или после подтверждения отмены | lens:architect | №07 |
| fx | major | incomplete | Повтор отмены проводки без предела и итогового статуса | lens:risk | №08 |
| fx | major | incomplete | Ответы АБС на отмену проводки описаны только как «отменено» | lens:architect | №07 |
| fx | major | unverifiable | Цель 60 % в приложении не измеряется полями требований | consistency | №09 |
| fx | major | incomplete | Откат не описывает активные котировки и обмены в обработке | consistency | №09 |
| fx | minor | incomplete | Схема процесса не показывает ветку ошибки метода 2 | consistency | №09 |
| fx | minor | incomplete | Критерии приёмки не покрывают границы и ветки отказа | lens:qa | №06 |
| fx | minor | ambiguity | Параметр currency курса: иностранная или счётная валюта | lens:architect | №07 |
| fx | minor | terminology | «Проводка в АБС» названа по-разному в разных разделах | consistency | №09 |
| fx | minor | unverifiable | Доступность методов 1 и 2 не определена для измерения | lens:qa | №06 |
| fx | minor | duplicate | Срок хранения ключа: created_at и момент ответа | consistency | №09 |
| fx | minor | incomplete | Документ не рассматривает ряд случаев | lens:architect | №07 |
| grace_v2 | minor | incomplete | Цель раннего показа срока не достигается до формирования выписки | consistency | №09 |
| grace_v2 | minor | terminology | Одни и те же компоненты и понятия названы по-разному, глоссария нет | lens:architect, consistency | №07, №09 |
| grace_v2 | minor | ambiguity | Порядок подсчёта дней до окончания платёжного периода не задан | lens:analyst | №05 |
| grace_v2 | minor | missing_element | Кнопка «Пополнить» показана в UI без описания операции | consistency | №09 |
| grace_v2 | minor | incomplete | Схемы процесса и последовательности не содержат выключения напоминания | consistency | №09 |
| grace_v2 | minor | non_singular | Пункт Ф-5 объединяет пять самостоятельных правил | lens:analyst | №05 |
| grace_v2 | minor | contradiction | Срок 55 дней в Ф-1 расходится с окончанием периода 25-го числа | lens:risk | №08 |
| grace_v2 | minor | other | Требования не имеют приоритетов | consistency | №09 |
| grace_v2 | minor | incomplete | Перечень квази-кэш-операций не назван | lens:analyst | №05 |
| grace_v2 | minor | other | Правило расчёта процентов продублировано в Ф-3 и особых правилах API | consistency | №09 |
| grace_v2 | minor | incomplete | Не сказано, что происходит с процентами при возврате после 25-го | lens:analyst | №05 |
| grace_v2 | minor | incomplete | Судьба переплаты сверх задолженности не определена | lens:analyst | №05 |
| grace_v2 | minor | incomplete | Критерии приёмки покрывают малую часть функциональных требований | lens:qa | №06 |
| grace_v2 | minor | unit_mismatch | Суммы в API в тиынах, в критериях приёмки в тенге без пересчёта | lens:architect | №07 |
| grace_v2 | minor | ambiguity | Не определено, что возвращает метод при отсутствии выписки | lens:analyst | №05 |
| grace_v2 | minor | incomplete | Ставка для прогноза процентов не привязана к периоду при смене | consistency | №09 |
| grace_v2 | minor | contradiction | daysLeft не определён для прошедшего платёжного периода | consistency | №09 |
| insurance_v2 | critical | contradiction | Повтор подключения после подписания: условия или отказ 409 | consistency | №09 |
| insurance_v2 | major | missing_element | Номер полиса: обмен со страховщиком на выпуск не описан | lens:architect | №07 |
| insurance_v2 | major | terminology | Один участник назван «заявителем» и «заёмщиком» | consistency | №09 |
| insurance_v2 | major | missing_element | Статусы страхования после отказа и погашения не заданы | lens:architect, consistency | №07, №09 |
| insurance_v2 | major | incomplete | Повтор с изменённой суммой: исход при других ошибках не задан | lens:analyst, lens:architect | №05, №07 |
| insurance_v2 | major | api_contract | Тела ошибок 400 и 422 называют только одну из двух причин | lens:architect | №07 |
| insurance_v2 | major | ambiguity | Момент «полного погашения» для возврата не определён | lens:risk | №08 |
| insurance_v2 | minor | traceability | Требования без ID и приоритетов | consistency | №09 |
| insurance_v2 | minor | terminology | Страховщик назван «страховая компания» и «страховая компания-партнёр» | consistency | №09 |
| insurance_v2 | minor | unverifiable | Цель «без жалоб» не имеет числа и требования | consistency | №09 |
| insurance_v2 | minor | incomplete | Схема последовательности не показывает отказ и возврат премии | consistency | №09 |
| insurance_v2 | minor | missing_element | Критерии приёмки не покрывают границы, ошибки и повторы | lens:qa | №06 |
| insurance_v2 | minor | duplicate | Правило повышения ставки записано в Ф-4 и в особом правиле | consistency | №09 |
| insurance_v2 | minor | ambiguity | Формула возврата премии при досрочном погашении не записана | lens:analyst | №05 |
| insurance_v2 | minor | ambiguity | Нижняя граница возраста 18 лет без привязки к дате | lens:analyst | №05 |
| insurance_v2 | minor | unverifiable | Нагрузка и период замера не заданы для требования 2 с | lens:analyst | №05 |
| insurance_v2 | minor | incomplete | Поля pd_consent_at, loan_amount, loan_term нет в данных | lens:architect | №07 |
| insurance_v2 | minor | ambiguity | Порядок проверок возраста (п.4) и согласия (п.6) не задан | consistency | №09 |
| insurance_v2 | minor | non_singular | Пункт 6 логики метода объединяет шесть отдельных правил | lens:analyst | №05 |
| qr_v2 | major | contradiction | Sequence-диаграмма минует сервис QR-кодов при переводе | lens:architect, consistency | №07, №09 |
| qr_v2 | minor | traceability | Требования без ID и приоритетов, ранжирования нет | consistency | №09 |
| qr_v2 | minor | unverifiable | Цель снизить ошибочные переводы без числа и метрики | consistency | №09 |
| qr_v2 | minor | terminology | Одни и те же роли и карты названы разными терминами | consistency | №09 |
| qr_v2 | minor | ambiguity | Слово «ошибка» в Ф-2 не связано с кодами отказа | lens:analyst | №05 |
| qr_v2 | minor | incomplete | Критерии приёмки покрывают 8 из 15 функциональных требований | lens:qa | №06 |
| qr_v2 | minor | incomplete | Одновременная оплата QR с суммой двумя запросами не описана | consistency | №09 |
| qr_v2 | minor | duplicate | Срок 15 минут записан в Ф-2 и в особых правилах API | consistency | №09 |
| qr_v2 | minor | missing_element | Признак «перевод в обработке» для QR без суммы не выводится | lens:architect | №07 |
| qr_v2 | minor | unverifiable | Нагрузка 200 переводов в секунду без условия выполнения | lens:analyst | №05 |
| qr_v2 | minor | missing_element | Поля requestId и cardId не перечислены в данных | lens:architect | №07 |
| qr_v2 | minor | api_contract | Поле status без условия, но в примере 400 его нет | lens:architect | №07 |
| repay | major | missing_element | Дата выдачи кредита нужна для Ф-3, но не передаётся из АБС | lens:analyst, lens:architect, consistency | №05, №07, №09 |
| repay | minor | traceability | У пунктов нет ID и приоритетов | consistency | №09 |
| repay | minor | unverifiable | Цель 50 % в мобильном банке не подкреплена требованиями измерения | consistency | №09 |
| repay | minor | terminology | Одни и те же понятия названы разными терминами | lens:architect, consistency | №07, №09 |
| repay | minor | incomplete | BPMN не показывает ветвь 500 и сверки UNKNOWN | consistency | №09 |
| repay | minor | incomplete | Дата очередного платежа на выходной или праздник не определена | lens:risk, lens:analyst | №05, №08 |
| repay | minor | incorrect | Граница остатка 9 999 ₸ после частичного погашения недостижима | lens:qa | №06 |
| repay | minor | ambiguity | Доля процентов в платежах нового графика выведена неявно | lens:analyst | №05 |
| repay | minor | missing_element | Тела обменов с АБС для расчёта, проведения и статуса не описаны | lens:architect | №07 |
| repay | minor | ambiguity | Переходы статуса REJECTED при повторе не описаны | lens:analyst, lens:architect | №05, №07 |
| repay | minor | contradiction | Срок действия ключа 30 дней противоречит гарантии без второго погашения | lens:architect | №07 |
| repay | minor | ops_risk | Статус «в обработке» не имеет предела ожидания сверки | lens:risk | №08 |
| repay | minor | api_contract | Формат ставки из АБС (процент или доля) не задан | lens:architect | №07 |
| repay | minor | incomplete | Критерии приёмки не покрывают 401, 400 заголовка, 409 и др. | lens:qa | №06 |
| roundup | major | terminology | Не определено, кто вправе настраивать копилку по дополнительной карте | lens:analyst, lens:risk | №05, №08 |
| roundup | minor | contradiction | Цель обещает перевод всей разницы, Ф-5 ограничивает перевод | consistency | №09 |
| roundup | minor | unverifiable | Цель в 30 000 карт не привязана к данным для подсчёта | consistency | №09 |
| roundup | minor | terminology | Одни и те же понятия названы в документе разными терминами | consistency | №09 |
| roundup | minor | incomplete | Порядок вызовов процессинга и счетов расходится между разделами | consistency | №09 |
| roundup | minor | incomplete | Экран не описывает показ ошибок 400, 401 и 404 метода 1 | lens:architect | №07 |
| roundup | minor | other | Функциональные требования Ф-1–Ф-9 не имеют приоритета | consistency | №09 |
| roundup | minor | other | Правило срока смены счёта и предела продублировано в двух местах | consistency | №09 |
| roundup | minor | contradiction | Неясно, какие значения сохраняются при выключении копилки | lens:qa | №06 |
| roundup | minor | incomplete | Критерии приёмки не покрывают границы суток, ошибки и повтор | lens:qa | №06 |
| statement | critical | boundary_conflict | Ф-6 и критерий приёмки строки 22 расходятся по доступности файла | consistency | №09 |
| statement | major | security | Файл выписки отдаётся по токен-ссылке без сессии клиента | lens:risk | №08 |
| statement | major | contradiction | Канал READY/FAILED от генератора не показан в архитектуре | lens:architect | №07 |
| statement | major | contradiction | Схема части B обходит API-шлюз, часть A требует вызовов через него | consistency | №09 |
| statement | major | ambiguity | Вчерашний день: момент отправки или часы сервиса — не сказано | lens:analyst | №05 |
| statement | major | unverifiable | Цель −30 % обращений не измеряется ни одним требованием | consistency | №09 |
| statement | minor | incomplete | Требования, НФТ и интеграция без ID и приоритетов | consistency | №09 |
| statement | minor | terminology | Один компонент и одна ссылка названы разными терминами | consistency | №09 |
| statement | minor | duplicate | Правило 366 дней повторено в трёх местах без общей ссылки | consistency | №09 |
| statement | minor | unverifiable | Порог 60 секунд для 5 000 операций не привязан к нагрузке | lens:analyst | №05 |
| statement | minor | incomplete | Критерии приёмки не покрывают язык вне списка и пустой список | lens:qa | №06 |
| statement | minor | incomplete | Откат флагом не описывает заказы в статусах IN_PROGRESS и READY | consistency | №09 |
