# Новые ТЗ №18 — чистые №20, haiku 13:00

Кейсов 8, прогонов 8, не измерено 0.

**Recall —** (0/0): critical 0/0, major 0/0, minor 0/0. Вне эталона 0, дублей 0, критичных ложных 0.

Чистые версии (8): замечаний 117, из них ложных (вне фона шаблона) 117: critical 6, major 57; документов с critical 5, с > 1 замечанием 8, вердикт «нельзя» 5.

Recall по типам: .

Время 36.2 мин суммарно, вызовов 77, $1.078.

| Кейс | Версия | Статус | Найдено | Замечаний (к/с/н) | Вердикт | Мин | Вызовов |
| :--- | :--- | :--- | :--- | :--- | :--- | ---: | ---: |
| capital_v2 | clean | complete | — | 17 (0/9/8) | conditional/conditional | 4.1 | 8 |
| fx | clean | complete | — | 13 (1/5/7) | no/no | 5.2 | 10 |
| grace_v2 | clean | complete | — | 16 (1/9/6) | no/no | 4.0 | 9 |
| insurance_v2 | clean | complete | — | 16 (1/7/8) | no/no | 3.5 | 9 |
| qr_v2 | clean | complete | — | 12 (1/6/5) | no/no | 3.2 | 10 |
| repay | clean | complete | — | 21 (2/11/8) | no/no | 6.0 | 11 |
| roundup | clean | complete | — | 11 (0/4/7) | conditional/yes | 5.0 | 10 |
| statement | clean | complete | — | 11 (0/6/5) | conditional/yes | 5.2 | 10 |

Ложные на чистых версиях:

| Кейс | Серьёзность | Тип | Замечание | Источники | Владельцы |
| :--- | :--- | :--- | :--- | :--- | :--- |
| capital_v2 | major | missing_element | Выбор карты на экране без метода получения списка карт клиента | consistency | №09 |
| capital_v2 | major | incomplete | Метод 1 не проверяет, что накопительный счёт в тенге | lens:architect | №07 |
| capital_v2 | major | missing_element | История начислений: способ выплаты прошлых месяцев не хранится | lens:architect | №07 |
| capital_v2 | major | incomplete | Не определено, куда выплачиваются проценты при закрытии счёта в режиме «На карту» | lens:analyst | №05 |
| capital_v2 | major | ambiguity | Карта для процентов текущего месяца после смены карты не определена | lens:analyst, consistency | №05, №09 |
| capital_v2 | major | ambiguity | Не сказано, входит ли текущий день в проценты «на дату запроса» | lens:analyst | №05 |
| capital_v2 | major | ambiguity | Не задано, как округлять половину тиына в «математическом правиле» | lens:analyst | №05 |
| capital_v2 | major | incomplete | Закрытие счёта: не сказано, начисляется ли день закрытия, и нет критерия приёмки | consistency | №09 |
| capital_v2 | major | incomplete | Закрытый счёт: метод 1 возвращает 404, метод 2 об этом не говорит | consistency | №09 |
| capital_v2 | minor | other | Правила Ф-1…Ф-6 не ранжированы по приоритету | consistency | №09 |
| capital_v2 | minor | terminology | Одни и те же компоненты названы разными терминами, глоссария нет | consistency | №09 |
| capital_v2 | minor | incomplete | Экран «Проценты» не описан до первого сохранения и выбор карты из нескольких | lens:analyst | №05 |
| capital_v2 | minor | duplicate | Дата начала нового способа записана в Ф-3 и в п.4 логики | consistency | №09 |
| capital_v2 | minor | unverifiable | Норматив времени ответа без нагрузки и периода измерения | lens:analyst | №05 |
| capital_v2 | minor | traceability | NFR, требования к данным и параметры API без идентификаторов | consistency | №09 |
| capital_v2 | minor | missing_element | Таблица приёмки не покрывает большую часть функциональных веток | lens:qa | №06 |
| capital_v2 | minor | unverifiable | Пункт ИБ отмечен «Да», а ссылаемого чек-листа ИБ нет | lens:risk | №08 |
| fx | critical | event_conflict | Таймер экрана идёт от ответа, срок котировки — от createdAt | consistency | №09 |
| fx | major | contradiction | Повтор обмена с тем же ключом после expiresAt: 200 или 422 | lens:qa | №06 |
| fx | major | contradiction | 500 при таймауте проводки отдаётся до подтверждения отмены | lens:architect, lens:risk | №07, №08 |
| fx | major | boundary_conflict | На границе expiresAt экран блокирует подтверждение, сервер принимает | consistency | №09 |
| fx | major | incomplete | Ответ АБС на отмену проводки описан только как «отменено» | lens:architect | №07 |
| fx | major | unverifiable | Цель «60 % обменов в приложении» не измеряется данными документа | consistency | №09 |
| fx | minor | missing_element | Выключение пункта «Обменять валюту» нигде не описано требованием | consistency | №09 |
| fx | minor | incomplete | BPMN не показывает ветку 500 метода 2 | consistency | №09 |
| fx | minor | incomplete | Строки приёмки не покрывают часть веток требований | lens:qa | №06 |
| fx | minor | terminology | Курс продажи назван по-разному в частях документа | consistency | №09 |
| fx | minor | unverifiable | НФ-1: понятие «доступность» не определено для измерения | lens:qa | №06 |
| fx | minor | duplicate | Срок идемпотентности 24 часа задан в двух местах | consistency | №09 |
| fx | minor | api_contract | Формат {date} календаря и тип курса сервиса курсов не описаны | lens:architect | №07 |
| grace_v2 | critical | contradiction | Льготный период 55 дней расходится с окончанием платёжного периода 25-го числа | lens:risk, consistency | №08, №09 |
| grace_v2 | major | contradiction | Платёж до выписки: Ф-5 учитывает, шаг 3 метода не учитывает | lens:qa | №06 |
| grace_v2 | major | missing_element | Покупки расчётного периода не получаются методом, хотя нужны для прогноза | lens:architect | №07 |
| grace_v2 | major | ambiguity | Момент перехода в статус LOST до окончания платёжного периода не определён | lens:analyst | №05 |
| grace_v2 | major | ambiguity | База процентов при возврате до окончания периода не определена | lens:analyst | №05 |
| grace_v2 | major | unit_mismatch | Суммы в критериях приёмки в тенге, в API в тиынах без правила пересчёта | lens:analyst, lens:architect | №05, №07 |
| grace_v2 | major | api_contract | Прогноз процентов: «частичное погашение» или «отсутствие платежа» | lens:architect | №07 |
| grace_v2 | major | missing_element | Кнопка «Пополнить» в блоке льготного периода не описана требованием | consistency | №09 |
| grace_v2 | major | ambiguity | Правило запроса до выписки: неясно, какой платёжный период вернуть | lens:analyst | №05 |
| grace_v2 | major | incomplete | Метод 2 (PUT напоминания) отсутствует в схемах и не связан с сервисом уведомлений | consistency | №09 |
| grace_v2 | minor | contradiction | Цель обещает актуальную сумму, NFR допускает отставание учёта до 5 минут | consistency | №09 |
| grace_v2 | minor | terminology | Компонент и ключевые понятия называются по-разному, глоссария нет | lens:architect, consistency | №07, №09 |
| grace_v2 | minor | duplicate | Дата окончания платёжного периода описана в Ф-1 и Ф-5 по-разному | consistency | №09 |
| grace_v2 | minor | other | Функциональные требования Ф-1…Ф-5 без приоритета | consistency | №09 |
| grace_v2 | minor | incomplete | Поведение при включении напоминания после 22-го числа не описано | lens:analyst, consistency | №05, №09 |
| grace_v2 | minor | incomplete | Критерии приёмки покрывают 4 из 11 функциональных требований | lens:qa | №06 |
| insurance_v2 | critical | event_conflict | Отказ в 14 дней после полного погашения: Ф-4 разрешает, метод 3 отвечает 409 | consistency | №09 |
| insurance_v2 | major | status_conflict | Повторный вызов метода 1 для подписанной заявки: 200 по особому правилу или 409 | lens:architect | №07 |
| insurance_v2 | major | ambiguity | Не сказано, сохраняется ли подключение страхования при 422 страховой компании | lens:analyst | №05 |
| insurance_v2 | major | missing_element | Последовательность не содержит вызова страховщика за номером полиса после выдачи | lens:architect | №07 |
| insurance_v2 | major | missing_element | Схема процесса (строка 34) не содержит снятия страхования и досрочного погашения | consistency | №09 |
| insurance_v2 | major | ambiguity | Неполный месяц при возврате премии за досрочное погашение не определён | lens:analyst | №05 |
| insurance_v2 | major | incomplete | Судьба страхования при 409 на повторном вызове метода 1 не описана | consistency | №09 |
| insurance_v2 | major | contradiction | Пример refundUntil 2026-03-19 расходится с окном отказа 15 марта по Ф-4 | lens:architect, lens:qa | №06, №07 |
| insurance_v2 | minor | terminology | Одни и те же понятия названы разными терминами, глоссария нет | consistency | №09 |
| insurance_v2 | minor | other | Приоритеты требований не указаны | consistency | №09 |
| insurance_v2 | minor | ambiguity | Срок возврата 7 рабочих дней не привязан к событию и календарю | lens:analyst | №05 |
| insurance_v2 | minor | duplicate | Ставка 27 % после отказа продублирована в правиле Ф-4 и особом правиле 3 | consistency | №09 |
| insurance_v2 | minor | unverifiable | Нагрузка для срока ответа 2 с не указана | lens:analyst | №05 |
| insurance_v2 | minor | incomplete | Поля согласия и суммы/срока в БД не попали в перечень хранимых данных | lens:architect | №07 |
| insurance_v2 | minor | missing_element | Критерии приёмки покрывают 6 из 13 функциональных требований | lens:qa | №06 |
| insurance_v2 | minor | incomplete | Повторный вызов после отказа от страхования не описан | consistency | №09 |
| qr_v2 | critical | contradiction | Повтор запроса с тем же requestId: шаг 6 даёт 410, особое правило 2 даёт результат первого | lens:analyst, lens:architect | №05, №07 |
| qr_v2 | major | ambiguity | Ф-2 и шаг 8 не определяют, оплачен ли QR после отказа по недостатку средств | consistency | №09 |
| qr_v2 | major | missing_element | Событие «перевод зачислен» не содержит имя отправителя для push получателю | lens:architect | №07 |
| qr_v2 | major | missing_element | Поля request_id и debit_card_id есть в контракте, но не в перечне хранимых данных | lens:architect | №07 |
| qr_v2 | major | security | GET /qr/{qrId} отдаёт данные QR любому клиенту при коротком предсказуемом qrId | lens:risk | №08 |
| qr_v2 | major | api_contract | Поля status, amount, recipientName обязательны по таблице, но не в примерах тел ошибок | lens:architect | №07 |
| qr_v2 | major | incomplete | BPMN и Sequence не показывают отмену получателем и ветку отказа | consistency | №09 |
| qr_v2 | minor | terminology | Одни понятия названы по-разному, глоссария нет | consistency | №09 |
| qr_v2 | minor | other | Требования Ф-1…Ф-6 и ID не имеют приоритетов | consistency | №09 |
| qr_v2 | minor | duplicate | Срок 15 минут записан в Ф-2 и особых правилах | consistency | №09 |
| qr_v2 | minor | incomplete | Не описаны параллельные оплата и отмена QR с суммой | consistency | №09 |
| qr_v2 | minor | incomplete | Критерии приёмки покрывают 7 из 15 функциональных требований | lens:qa | №06 |
| repay | critical | contradiction | Ключ идемпотентности после 30 дней: гарантия «не создаёт второе погашение» против «обрабат | consistency | №09 |
| repay | critical | status_conflict | Повтор с тем же ключом после 422: «не проведено» (L158, L140) против 200 DONE (L139) | lens:architect, lens:qa, consistency | №06, №07, №09 |
| repay | major | security | Источник списания не проверяется на принадлежность клиенту сессии | lens:risk | №08 |
| repay | major | ambiguity | Не определено, потребляет ли операция в UNKNOWN расчёт (проведено или нет) | lens:analyst | №05 |
| repay | major | incomplete | Отправка push при повторе, получившем «проведена», не определена | lens:architect | №07 |
| repay | major | missing_element | Дата выдачи для расчёта процентов не передаётся из АБС | lens:analyst | №05 |
| repay | major | missing_element | Поля ответов АБС для расчёта и проведения не описаны | lens:architect | №07 |
| repay | major | unverifiable | Цель «не менее 50 % в мобильном банке» не измеряется: в данных нет канала | consistency | №09 |
| repay | major | missing_element | Флаг включения кнопки не имеет метода получения приложением | lens:architect, consistency | №07, №09 |
| repay | major | ambiguity | Источник списания по умолчанию и экран без источников не описаны | lens:analyst | №05 |
| repay | major | ambiguity | Статус операции при повторной обработке после REJECTED не определён | consistency, lens:analyst | №05, №09 |
| repay | major | ops_risk | Операция в статусе UNKNOWN не имеет предела ожидания сверки | lens:risk | №08 |
| repay | major | incomplete | Выключение флага не описано для операций в статусе UNKNOWN | consistency | №09 |
| repay | minor | terminology | Одни и те же компоненты и статусы названы по-разному | consistency, lens:architect | №07, №09 |
| repay | minor | other | Приоритеты требований не заданы | consistency | №09 |
| repay | minor | incomplete | Сверка UNKNOWN не показана в sequence и схеме метода | consistency | №09 |
| repay | minor | ambiguity | Нагрузка «в секунду одновременно» — частота или параллельность | lens:analyst | №05 |
| repay | minor | non_singular | Нефункциональный пункт объединяет восемь независимых правил | lens:analyst | №05 |
| repay | minor | missing_element | Дата погашения из расчёта не хранится и не возвращается | lens:architect | №07 |
| repay | minor | incomplete | Не указано, что сервис берёт список кредитов и вид из GET /loans | lens:architect | №07 |
| repay | minor | incomplete | Критерии приёмки не покрывают часть функциональных веток | lens:qa | №06 |
| roundup | major | ambiguity | Граница 00:30: событие учитывается по получению или по начислению | lens:analyst | №05 |
| roundup | major | api_contract | И-4: тело запроса и ответ POST /transfers/v1/internal не описаны | lens:architect | №07 |
| roundup | major | api_contract | Push-уведомление: тело запроса и адресат не описаны | lens:architect | №07 |
| roundup | major | ambiguity | limitRemaining до фиксации: какой месячный предел показывать | consistency | №09 |
| roundup | minor | terminology | Одно понятие названо тремя терминами: шаг округления и его варианты | consistency | №09 |
| roundup | minor | incomplete | BPMN не содержит ветки возврата, которую задают Ф-6 и sequence | consistency | №09 |
| roundup | minor | other | Функциональные требования Ф-1–Ф-9 без приоритетов и признака стабильности | consistency | №09 |
| roundup | minor | missing_element | Критерии приёмки не покрывают граничное время и служебные ошибки | lens:qa | №06 |
| roundup | minor | duplicate | Правило времени сохранения повторено в Ф-8 и особых правилах API | consistency | №09 |
| roundup | minor | unverifiable | НФ-3: срок переводов без доли событий и условий замера | lens:qa | №06 |
| roundup | minor | ambiguity | Перечень кодов причин отказа в И-4 завершается словами «и другие» | rules:language.open_list | №12 |
| statement | major | contradiction | Схема вызова метода 1 минует API-шлюз, что противоречит L040 | consistency | №09 |
| statement | major | missing_element | Журнал аудита обещан в L044, но ни один компонент его не пишет | consistency | №09 |
| statement | major | missing_element | Дата открытия счёта для текста 422 не входит в тело ответа | lens:architect | №07 |
| statement | major | security | Метод скачивания отдаёт PDF по токену в пути URL без сессии клиента | lens:risk | №08 |
| statement | major | missing_element | Переводы текстов интерфейса на kk и en обещаны, но не приведены | lens:analyst | №05 |
| statement | major | ambiguity | «Вчера» отсчитывается от момента отправки, а не от часов сервиса | lens:analyst | №05 |
| statement | minor | terminology | Один компонент и один клиент названы разными именами | consistency | №09 |
| statement | minor | incomplete | Исход закрытия счёта после создания заказа не описан | consistency | №09 |
| statement | minor | incomplete | Нет ID и приоритетов у функциональных требований и пунктов | consistency | №09 |
| statement | minor | duplicate | Срок ссылки 15 минут повторён в двух местах документа | consistency | №09 |
| statement | minor | incomplete | Таблица приёмки не покрывает служебные ветки методов 1–4 | lens:qa | №06 |
