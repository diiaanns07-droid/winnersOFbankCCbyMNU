# Корпус evaluation/dev — v2 haiku, 0f3d9dd (22 кейса) + 7d80df8 (11)

Кейсов 33 (не запускались 0), не измерено 0 (пропусков в счётчике 0).

| TP | FP | FN | Дубли | Precision | Recall | F1 |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 26 | 478 | 2 | 0 | 0.052 | 0.929 | 0.098 |

Чистые документы (8/8 измерено): замечаний 128, critical 4, major 61; документов с critical 4, с > 1 major 8, вердикт «нельзя» 4; документов с > 1 замечанием 8, максимум на одном 21. Ложных тревог по счётчику: 128.

Recall по типам: boundary_conflict 4/5, event_conflict 5/5, missing_element 6/6, status_conflict 6/6, unit_mismatch 5/6.

Время 292.1 мин суммарно, вызовов 289, $3.585.

Кандидаты этапов до судьи (верхняя граница): TP 27/28, recall 0.964; по типам: boundary_conflict 4/5, event_conflict 5/5, missing_element 6/6, status_conflict 6/6, unit_mismatch 6/6.

Ложные на мутантах (350) по происхождению: та же жалоба, что на чистой базе семейства — 126 (36 %; №08 50, №05 41, №07 41, №06 22, №09 20), то же место с другой жалобой — 203, только у мутанта — 21; строгий фон счётчика — 48. Ложная жалоба чистой базы повторяется на мутантах: убрать её на чистых — уйдут и эти.

Вклад источников (замечание с несколькими источниками считается каждому):

| Источник | TP | FP | из них на чистых |
| :--- | ---: | ---: | ---: |
| consistency (№09) | 14 | 95 | 20 |
| lens:analyst (№05) | 11 | 166 | 55 |
| lens:architect (№07) | 18 | 115 | 33 |
| lens:qa (№06) | 20 | 62 | 17 |
| lens:risk (№08) | 12 | 156 | 35 |
| rules (№12) | 14 | 1 | 0 |

Ложные находки:

| Кейс | Чистый | Серьёзность | Тип | Замечание | Источники | Владельцы |
| :--- | :---: | :--- | :--- | :--- | :--- | :--- |
| autopay.base | да | minor | other | Пункты АП-1, АП-4 и требования интеграции объединяют несколько независимых правил | lens:analyst | №05 |
| autopay.base | да | minor | api_contract | Отсутствие обязательного поля или неверный тип не имеют описанного кода ответа | lens:architect | №07 |
| autopay.base | да | major | incomplete | Проверка валюты карты KZT из АП-1 не описана в логике createAutopay и в кодах | lens:analyst, lens:risk | №05, №08 |
| autopay.base | да | minor | incomplete | Блокировка и перевыпуск карты не описаны для действующей настройки автопополнения | lens:risk | №08 |
| autopay.base | да | major | security | Номер телефона в createAutopay не проверяется на принадлежность клиенту | lens:risk | №08 |
| autopay.base | да | major | api_contract | Тело успешного ответа createAutopay не описано, хотя статусы отсылают к разделу метода | lens:qa, lens:architect | №06, №07 |
| autopay.base | да | minor | missing_element | Канал получения уведомления о балансе и подлинность отправителя не описаны | lens:risk | №08 |
| autopay.base | да | minor | unverifiable | Выполнение критерия push описано как доставка, а не отправка | lens:risk | №08 |
| autopay.base | да | minor | ambiguity | Определение суток оставляет промежуток между 23:59:59 и 00:00:00 | lens:analyst | №05 |
| autopay.base | да | minor | incomplete | Сбой оператора после списания с карты не описан: возврат или повтор не определены | lens:risk | №08 |
| autopay.base | да | major | ambiguity | Один номер может иметь несколько настроек с разными картами: карта списания не определена | lens:analyst, lens:architect | №05, №07 |
| autopay.base | да | minor | ambiguity | Не определено, по времени уведомления или списания относить пополнение к суткам | lens:analyst | №05 |
| autopay.base | да | minor | ambiguity | Порядок проверок в логике createAutopay не задан: 404 или 400 при двух ошибках | lens:architect | №07 |
| autopay.base | да | major | incomplete | Критерии приёмки не покрывают границы, 409, 401/404, getAutopay, deleteAutopay и повтор со | lens:qa | №06 |
| autopay.base | да | major | ambiguity | Неуспешные попытки пополнения: учитываются ли они в лимите трёх в сутки | lens:analyst, lens:qa | №05, №06 |
| autopay.base | да | major | ambiguity | НФ-1: не определено, какое событие считается выполнением пополнения и период для 99 % | lens:analyst, lens:qa | №05, №06 |
| autopay.paraphrase.nfr | да | minor | ops_risk | Не описано, что делать с уведомлением, обрабатываемым во время deleteAutopay | lens:risk | №08 |
| autopay.paraphrase.nfr | да | minor | ops_risk | Не описан исход, если списание выполнено, а пополнение не подтверждено | lens:risk | №08 |
| autopay.paraphrase.nfr | да | major | ambiguity | Неясно, засчитываются ли отказанные по АП-6 попытки в лимит трёх за сутки | lens:qa, lens:analyst | №05, №06 |
| autopay.paraphrase.nfr | да | minor | ambiguity | Не указано, по какому моменту пополнение относится к суткам | lens:analyst | №05 |
| autopay.paraphrase.nfr | да | major | ambiguity | Не определено, какое событие завершает срок 5 минут в НФ-1 | lens:analyst | №05 |
| autopay.paraphrase.nfr | да | major | contradiction | Цель «баланс не опускается ниже порога» не выполняется требованиями при отказах | lens:analyst | №05 |
| autopay.paraphrase.nfr | да | major | ambiguity | Не определено, один ли номер может иметь несколько настроек с разными картами | lens:analyst | №05 |
| autopay.paraphrase.nfr | да | major | incomplete | Проверка валюты карты KZT из АП-1 отсутствует в логике createAutopay | lens:risk, lens:architect | №07, №08 |
| autopay.paraphrase.nfr | да | major | incomplete | Критерии приёмки не покрывают границы, повтор уведомления, отключение и API-коды | lens:qa | №06 |
| autopay.paraphrase.nfr | да | major | unverifiable | НФ-1 не задаёт период выборки для доли 99 % | lens:qa | №06 |
| autopay.paraphrase.nfr | да | minor | incomplete | Не сказано, учитывается ли комиссия при проверке достаточности средств | lens:analyst | №05 |
| autopay.paraphrase.nfr | да | minor | ops_risk | Гонка двух уведомлений на границе лимита трёх пополнений не описана | lens:risk | №08 |
| autopay.paraphrase.nfr | да | major | api_contract | Нет кода ответа для отсутствующего обязательного поля и неверного типа | lens:architect | №07 |
| autopay.paraphrase.nfr | да | minor | missing_element | Не описано поведение настройки при блокировке или перевыпуске карты | lens:risk | №08 |
| autopay.paraphrase.nfr | да | major | incomplete | Тело успешного ответа createAutopay не описано, хотя таблица на него ссылается | lens:architect | №07 |
| cardblock.base | да | minor | incomplete | Для интеграции не заданы время ответа и доступность методов | lens:architect | №07 |
| cardblock.base | да | minor | api_contract | Параметр пути cardId не описан | lens:architect | №07 |
| cardblock.base | да | major | incomplete | После ответа 500 на blockCard состояние блокировки неизвестно, повтор даёт 409 | lens:risk | №08 |
| cardblock.base | да | major | ambiguity | Не определено, кто вправе блокировать карту: держатель или владелец счёта | lens:risk | №08 |
| cardblock.base | да | minor | incomplete | Ответ getCardStatus для статуса ACTIVE не описан | lens:architect | №07 |
| cardblock.base | да | major | incomplete | Значение срока при бессрочной блокировке не задано ни в данных, ни в ответе getCardStatus | lens:qa, lens:analyst, consistency | №05, №06, №09 |
| cardblock.base | да | minor | ops_risk | Push: сбой доставки и уведомление об окончании срока не описаны | lens:risk | №08 |
| cardblock.base | да | major | incomplete | Не определено, проводится ли списание по авторизации, одобренной до блокировки | lens:analyst, lens:risk | №05, №08 |
| cardblock.base | да | major | contradiction | Код ответа при days вне диапазона на заблокированной карте: 400 или 409 | consistency, lens:architect | №07, №09 |
| cardblock.base | да | major | missing_element | Push-уведомление обещано в БК-7, но не описано в интеграции | consistency | №09 |
| cardblock.base | да | minor | unverifiable | Push-уведомление не имеет проверяемого критерия прохождения | lens:qa | №06 |
| cardblock.base | да | major | ambiguity | Исход авторизаций в 10-секундном окне после ответа 200 blockCard не определён | consistency, lens:risk | №08, №09 |
| cardblock.base | да | minor | other | Пункты БК-2, БК-7 и данных объединяют несколько независимых правил | lens:analyst | №05 |
| cardblock.base | да | major | missing_element | Приёмка покрывает три сценария, границы, отказы и возврат в ACTIVE не проверяются | lens:qa | №06 |
| cardblock.base | да | minor | incomplete | Приоритеты требований в документе не указаны | consistency | №09 |
| cardblock.base | да | minor | ambiguity | Не определены значения поля инициатора изменения | lens:analyst | №05 |
| cardblock.base | да | minor | unverifiable | БК-5 не задаёт долю запросов и нагрузку для срока 10 секунд | lens:analyst | №05 |
| cardblock.base | да | critical | ambiguity | Момент окончания срока блокировки в сутках не определён | lens:analyst, lens:qa, lens:risk, consistency | №05, №06, №08, №09 |
| cardblock.paraphrase.keep_authorizations | да | major | contradiction | Повторная разблокировка: БК-6 разрешает, код 409 запрещает | lens:architect | №07 |
| cardblock.paraphrase.keep_authorizations | да | major | terminology | Кто вправе блокировать дополнительную карту: клиент или держатель | lens:analyst, lens:risk | №05, №08 |
| cardblock.paraphrase.keep_authorizations | да | minor | missing_element | Тип и формат cardId не описаны ни в одном методе | lens:architect | №07 |
| cardblock.paraphrase.keep_authorizations | да | major | missing_element | Для days не описан код ответа при нецелом значении | lens:architect | №07 |
| cardblock.paraphrase.keep_authorizations | да | minor | ops_risk | Повторный blockCard после успеха возвращает 409 без признака успеха | lens:risk | №08 |
| cardblock.paraphrase.keep_authorizations | да | minor | ops_risk | Доставка push о блокировке не гарантирована и не проверяема | lens:risk | №08 |
| cardblock.paraphrase.keep_authorizations | да | major | incomplete | Срок бессрочной блокировки и тело getCardStatus не описаны | lens:analyst, lens:qa, lens:architect | №05, №06, №07 |
| cardblock.paraphrase.keep_authorizations | да | major | incomplete | Проведение и отмена авторизации после блокировки не описаны | lens:analyst, lens:risk | №05, №08 |
| cardblock.paraphrase.keep_authorizations | да | major | incomplete | Ответ 500 на blockCard: неизвестно, применилась ли блокировка | lens:risk | №08 |
| cardblock.paraphrase.keep_authorizations | да | minor | incomplete | Нет нефункциональных требований к вызовам интеграции | lens:architect | №07 |
| cardblock.paraphrase.keep_authorizations | да | minor | ambiguity | Момент блокировки для БК-4 не совпадает с БК-5 | lens:analyst | №05 |
| cardblock.paraphrase.keep_authorizations | да | critical | ambiguity | Момент окончания срока блокировки и часовой пояс не определены | lens:analyst, lens:qa, lens:risk | №05, №06, №08 |
| cardblock.paraphrase.keep_authorizations | да | minor | other | БК-2, БК-7 объединяют несколько самостоятельных правил | lens:analyst | №05 |
| cardblock.paraphrase.keep_authorizations | да | major | missing_element | Критерии приёмки покрывают три ветки из десятков условий | lens:qa | №06 |
| cashback.base | да | minor | incomplete | Не определено, освобождает ли возврат место под лимитом 10 000 ₸ | lens:analyst | №05 |
| cashback.base | да | major | missing_element | Тело успешного ответа saveCategory не описано, хотя статус 200 отсылает к разделу метода | lens:architect | №07 |
| cashback.base | да | major | ambiguity | Не определено, какой из нескольких выборов категории в месяце действует | lens:analyst | №05 |
| cashback.base | да | major | ambiguity | Не определено, сохранённую или действующую категорию возвращает getCashback | lens:analyst | №05 |
| cashback.base | да | major | missing_element | Для getCashback не описаны коды ошибок, хотя метод требует сессию владельца карты | lens:architect | №07 |
| cashback.base | да | minor | incomplete | Ошибка отсутствующего или пустого поля category в saveCategory не описана | lens:architect | №07 |
| cashback.base | да | major | terminology | Термин «возврат» и событие его учёта не определены в разделе Термины | lens:analyst | №05 |
| cashback.base | да | minor | terminology | В интеграции getCashback назван чтением «настроек», хотя возвращает кэшбэк и категорию | lens:analyst | №05 |
| cashback.base | да | major | api_contract | Ответ getCashback не определён, если категория не выбрана или выбрана в текущем месяце | lens:architect | №07 |
| cashback.base | да | minor | ambiguity | Округление до тиына: не указано, по каждой покупке или по сумме месяца | lens:analyst | №05 |
| cashback.base | да | major | unverifiable | Точка замера времени ответа НФ-1 (сервер или приложение) не определена | lens:analyst | №05 |
| cashback.base | да | minor | missing_element | Данные не содержат ссылки на исходную покупку и признака операции для возврата | lens:architect | №07 |
| cashback.base | да | major | incomplete | КБ-6 не описывает уменьшение зачисления, если следующего начисления нет или оно меньше | lens:analyst | №05 |
| cashback.base | да | minor | non_singular | Несколько правил в одном пункте: срок выбора, вступление, два вида возврата, данные | lens:analyst | №05 |
| cashback.base | да | critical | ambiguity | Не определено, выбор категории и лимит 10 000 ₸ действуют на клиента или на карту | lens:analyst | №05 |
| cashback.paraphrase.rate | да | major | ambiguity | Термин «возврат» в КБ-6 не определён, в отличие от «покупки» | lens:analyst | №05 |
| cashback.paraphrase.rate | да | minor | other | КБ-1, КБ-6 и блок данных объединяют несколько правил в одном пункте | lens:analyst | №05 |
| cashback.paraphrase.rate | да | major | ambiguity | КБ-6 не ограничивает уменьшение покупками, по которым кэшбэк начислялся | lens:analyst | №05 |
| cashback.paraphrase.rate | да | minor | unverifiable | НФ-1 не задаёт точку замера времени ответа и способ расчёта 95 % | lens:architect, lens:analyst | №05, №07 |
| cashback.paraphrase.rate | да | major | missing_element | Возврат покупки не связан с исходной покупкой и признаком зачисления | lens:architect | №07 |
| cashback.paraphrase.rate | да | major | ambiguity | «Выбранная категория» в getCashback и КБ-7: текущая или следующая | lens:analyst, lens:architect | №05, №07 |
| cashback.paraphrase.rate | да | major | incomplete | Возврат после зачисления: нет правила, если уменьшение больше следующего зачисления | lens:analyst | №05 |
| cashback.paraphrase.rate | да | minor | ambiguity | Округление кэшбэка: не сказано, по покупке или по сумме месяца | lens:analyst | №05 |
| cashback.paraphrase.rate | да | major | incomplete | Состояние «категория не выбрана» не описано ни в КБ-1, ни в ответе | lens:analyst, lens:architect | №05, №07 |
| cashback.paraphrase.rate | да | major | missing_element | Тело успешного ответа saveCategory обещано, но не описано | lens:architect | №07 |
| transfer_limit.base | да | minor | ops_risk | Не описано, что делать с переводом при недоступном учёте использованной суммы | lens:risk | №08 |
| transfer_limit.base | да | minor | incomplete | Требования к интеграции не задают время ответа и доступность | lens:architect | №07 |
| transfer_limit.base | да | major | ambiguity | Не определено, входит ли в использованную сумму перевод, отказанный банком после списания | lens:risk | №08 |
| transfer_limit.base | да | major | api_contract | Поле limit: строка в ответе GET и integer в теле PUT, поведение round-trip не описано | consistency, lens:architect | №07, №09 |
| transfer_limit.base | да | minor | traceability | Требования без ID и приоритетов, кроме ЛП-1…ЛП-6 | consistency | №09 |
| transfer_limit.base | да | major | ambiguity | Не определено, какой лимит показывает приложение до следующего перевода | lens:analyst | №05 |
| transfer_limit.base | да | minor | boundary_conflict | Интервал суток «до 23:59:59» не покрывает доли секунды до полуночи | lens:analyst | №05 |
| transfer_limit.base | да | minor | ambiguity | ЛП-6 не определяет остаток, если использовано больше нового лимита | lens:analyst | №05 |
| transfer_limit.base | да | major | contradiction | Лимит привязан к номеру телефона в цели и к клиенту в данных; PUT не задаёт номер | lens:risk | №08 |
| transfer_limit.base | да | major | api_contract | Значение limit в GET после PUT не определено: действующий или новый лимит | lens:architect | №07 |
| transfer_limit.base | да | major | missing_element | Событие отмены перевода не описано ни в интеграции, ни в критериях приёмки | consistency | №09 |
| transfer_limit.base | да | major | terminology | Термин «Использовано» не задаёт направление переводов: входящие учитываются или нет | lens:analyst | №05 |
| transfer_limit.base | да | minor | ambiguity | Не указан источник времени перевода: устройство или сервер | lens:risk | №08 |
| transfer_limit.base | да | major | incomplete | Критерии приёмки не покрывают границы лимита, отмену, смену лимита и коды 401 и 500 | lens:qa | №06 |
| transfer_limit.base | да | minor | incomplete | Не указано, как учитывать перевод по номеру телефона в иностранной валюте | lens:analyst | №05 |
| transfer_limit.base | да | minor | incomplete | Остаток лимита показывается, но не сказано, как он вычисляется из ответа API | consistency | №09 |
| transfer_limit.base | да | minor | terminology | Одни и те же понятия названы по-разному, глоссарий не ведётся | consistency | №09 |
| transfer_limit.base | да | minor | other | ЛП-1 объединяет три правила, L032 объединяет четыре величины с одной точностью | lens:analyst | №05 |
| transfer_limit.base | да | minor | incomplete | Коды ответа GET не описаны: таблица статусов стоит только под setTransferLimit | consistency | №09 |
| transfer_limit.base | да | major | missing_element | Отмена перевода не уменьшает сумму суток выполнения: данных для связи нет | lens:risk, lens:architect | №07, №08 |
| transfer_limit.base | да | minor | ops_risk | Параллельные переводы у границы лимита могут вместе его превысить | lens:risk | №08 |
| transfer_limit.paraphrase.new_limit | да | minor | incomplete | Не сказано, входит ли комиссия в использованную сумму | lens:analyst | №05 |
| transfer_limit.paraphrase.new_limit | да | minor | incomplete | Сбой сервиса лимита во время проверки перевода не описан | consistency | №09 |
| transfer_limit.paraphrase.new_limit | да | minor | incomplete | Для методов лимита не заданы время ответа и доступность | lens:architect | №07 |
| transfer_limit.paraphrase.new_limit | да | minor | security | Изменение лимита сессией без подтверждения или уведомления клиента | lens:risk | №08 |
| transfer_limit.paraphrase.new_limit | да | minor | unit_mismatch | Точность лимита: тиыны в L032 и целое число в L024 | lens:analyst | №05 |
| transfer_limit.paraphrase.new_limit | да | minor | incomplete | Таблица статусов не указывает, к каким методам относятся коды | consistency | №09 |
| transfer_limit.paraphrase.new_limit | да | major | contradiction | Отмена перевода через полночь: возврат в остаток текущих суток не определён | lens:risk, consistency | №08, №09 |
| transfer_limit.paraphrase.new_limit | да | critical | ambiguity | «По номеру телефона» не определено: общий лимит клиента или лимит на номер | lens:analyst, lens:risk | №05, №08 |
| transfer_limit.paraphrase.new_limit | да | major | missing_element | Критерии приёмки не покрывают границы, отмену, смену лимита и коды ответов | lens:qa | №06 |
| transfer_limit.paraphrase.new_limit | да | minor | boundary_conflict | Определение суток до 23:59:59 не покрывает доли секунды | lens:analyst, lens:risk | №05, №08 |
| transfer_limit.paraphrase.new_limit | да | major | api_contract | Поле limit: string в ответе GET и integer в теле PUT | lens:architect, consistency | №07, №09 |
| transfer_limit.paraphrase.new_limit | да | minor | ambiguity | Момент учёта перевода в использованной сумме: начало или завершение | lens:risk | №08 |
| transfer_limit.paraphrase.new_limit | да | minor | terminology | Одно понятие названо тремя именами: Использовано, использованная сумма, used | consistency | №09 |
| transfer_limit.paraphrase.new_limit | да | major | ambiguity | Остаток лимита при снижении ниже использованной суммы не определён | lens:analyst, lens:qa | №05, №06 |
| transfer_limit.paraphrase.new_limit | да | minor | other | Функциональные требования ЛП-1–ЛП-6 без приоритетов | consistency | №09 |
| transfer_limit.paraphrase.new_limit | да | major | missing_element | Источник учёта использованной суммы не описан: нет механизма её увеличения | consistency | №09 |
| transfer_limit.paraphrase.new_limit | да | major | incomplete | Запрос setTransferLimit без поля limit не отнесён ни к одному коду | lens:architect, consistency | №07, №09 |
| transfer_limit.paraphrase.new_limit | да | minor | ops_risk | Параллельные переводы у границы лимита могут пройти вместе | lens:risk | №08 |
| transfer_limit.paraphrase.new_limit | да | minor | other | ЛП-1, ЛП-3 и ЛП-6 объединяют несколько независимых правил | lens:analyst | №05 |
| autopay.combo.unit_change-limit_per_hour+drop_promised-no_409_status |  | minor | non_singular | АП-1 и АП-4 объединяют несколько независимых правил в одном пункте | lens:analyst | №05 |
| autopay.combo.unit_change-limit_per_hour+drop_promised-no_409_status |  | minor | ops_risk | Откат списания при неудачном пополнении номера не описан | lens:risk | №08 |
| autopay.combo.unit_change-limit_per_hour+drop_promised-no_409_status |  | major | missing_element | Критерии приёмки не покрывают границы, отключение, повтор события и ошибки API | lens:qa | №06 |
| autopay.combo.unit_change-limit_per_hour+drop_promised-no_409_status |  | minor | incomplete | Поведение настройки при блокировке и перевыпуске карты не описано | lens:risk | №08 |
| autopay.combo.unit_change-limit_per_hour+drop_promised-no_409_status |  | minor | incomplete | Тело успешного ответа createAutopay не описано | lens:architect | №07 |
| autopay.combo.unit_change-limit_per_hour+drop_promised-no_409_status |  | major | incomplete | Условие карты KZT из АП-1 не проверяется в логике createAutopay | lens:risk, lens:architect | №07, №08 |
| autopay.combo.unit_change-limit_per_hour+drop_promised-no_409_status |  | major | security | Источник и подлинность уведомления о балансе не описаны, от него идут списания | lens:risk | №08 |
| autopay.combo.unit_change-limit_per_hour+drop_promised-no_409_status |  | major | ambiguity | Счётчик лимита АП-5: окно и состав попыток не определены | lens:qa, lens:risk, lens:analyst | №05, №06, №08 |
| autopay.combo.unit_change-limit_per_hour+drop_promised-no_409_status |  | major | unverifiable | НФ-1: начало, конец и доля 99 % не определены, срок не проверяем | lens:qa, lens:analyst | №05, №06 |
| autopay.drop_promised.no_409_status |  | major | ambiguity | НФ-1: не названо конечное событие пополнения — списание или зачисление | lens:analyst | №05 |
| autopay.drop_promised.no_409_status |  | minor | unverifiable | НФ-1: не задано окно измерения доли 99 % | lens:qa | №06 |
| autopay.drop_promised.no_409_status |  | minor | security | cardId в адресе запроса: не указано, что это не номер карты | lens:risk | №08 |
| autopay.drop_promised.no_409_status |  | minor | other | Два уведомления у границы лимита трёх пополнений в сутки | lens:risk | №08 |
| autopay.drop_promised.no_409_status |  | major | contradiction | Объект настройки и лимита: номер или карта, документ противоречив | lens:analyst, lens:risk | №05, №08 |
| autopay.drop_promised.no_409_status |  | minor | incomplete | Сбой оператора после списания: деньги списаны, пополнения нет — не описано | lens:risk | №08 |
| autopay.drop_promised.no_409_status |  | minor | ambiguity | Отключение во время обработки уведомления не определено | lens:risk | №08 |
| autopay.drop_promised.no_409_status |  | minor | incomplete | Интеграционные НФТ для трёх API-методов не заданы | lens:architect | №07 |
| autopay.drop_promised.no_409_status |  | minor | incomplete | Критерии приёмки покрывают четыре сценария из множества веток | lens:qa | №06 |
| autopay.drop_promised.no_409_status |  | major | missing_element | Проверка валюты карты KZT из АП-1 отсутствует в логике createAutopay | lens:risk, lens:qa, lens:architect | №06, №07, №08 |
| autopay.drop_promised.no_409_status |  | major | contradiction | Цель «баланс не ниже порога» противоречит лимиту АП-5 и отказу АП-6 | lens:analyst | №05 |
| autopay.drop_promised.no_409_status |  | minor | unit_mismatch | Тип баланса в уведомлении не задан: дробные значения и правило сравнения | lens:analyst | №05 |
| autopay.drop_promised.no_409_status |  | minor | security | Канал и подлинность уведомлений оператора не описаны | lens:risk | №08 |
| autopay.drop_promised.no_409_status |  | minor | incomplete | Тело успешного ответа createAutopay не описано | lens:architect | №07 |
| autopay.drop_promised.no_409_status |  | minor | terminology | «Отключение» в АП-7 не связано с deleteAutopay и не определено | lens:analyst | №05 |
| autopay.drop_promised.no_409_status |  | minor | ambiguity | Сутки для лимита: не определено, по какому событию относится пополнение | lens:analyst | №05 |
| autopay.drop_promised.no_409_status |  | minor | ambiguity | Лимит трёх пополнений за сутки: учитываются ли отказы по недостатку средств | lens:analyst, lens:qa | №05, №06 |
| autopay.event_conflict.insufficient_funds_credit |  | major | ambiguity | Понятие «недостаточно средств» не определено: общий или доступный баланс | lens:analyst | №05 |
| autopay.event_conflict.insufficient_funds_credit |  | major | ambiguity | АП-8: не определено, какое поступление погашает кредит и в каком объёме | lens:risk, lens:analyst | №05, №08 |
| autopay.event_conflict.insufficient_funds_credit |  | minor | non_singular | Несколько требований объединены в одних пунктах L024 и L040 | lens:analyst | №05 |
| autopay.event_conflict.insufficient_funds_credit |  | minor | security | Неясно, является ли cardId номером карты: он попадает в адрес GET и DELETE | lens:risk | №08 |
| autopay.event_conflict.insufficient_funds_credit |  | minor | terminology | Терминология не едина, глоссария для «настройки автопополнения» нет | consistency | №09 |
| autopay.event_conflict.insufficient_funds_credit |  | minor | ambiguity | Определение суток оставляет без периода доли секунды между 23:59:59 и 00:00:00 | lens:risk | №08 |
| autopay.event_conflict.insufficient_funds_credit |  | minor | ambiguity | «Клиент получает push» нельзя проверить: система гарантирует только отправку | lens:risk | №08 |
| autopay.event_conflict.insufficient_funds_credit |  | minor | incomplete | Сбой оператора после списания с карты не описан: порядок и возврат денег не заданы | consistency, lens:risk | №08, №09 |
| autopay.event_conflict.insufficient_funds_credit |  | minor | incomplete | Не указано, удерживается ли комиссия при пополнении | lens:analyst | №05 |
| autopay.event_conflict.insufficient_funds_credit |  | major | ambiguity | Не определено, может ли один номер иметь настройки на нескольких картах | lens:analyst | №05 |
| autopay.event_conflict.insufficient_funds_credit |  | minor | incomplete | Статус карты (блокировка, перевыпуск, закрытие) не учитывается в настройке | lens:risk | №08 |
| autopay.event_conflict.insufficient_funds_credit |  | major | ambiguity | АП-5: не определено, какие попытки входят в лимит трёх пополнений за сутки | lens:analyst, lens:risk | №05, №08 |
| autopay.event_conflict.insufficient_funds_credit |  | minor | incomplete | Не сказано, сбрасывается ли счётчик АП-5 при удалении и повторном создании настройки | consistency | №09 |
| autopay.event_conflict.insufficient_funds_credit |  | major | contradiction | Не сказано, выполняется ли пополнение, начатое до отключения автопополнения | consistency | №09 |
| autopay.event_conflict.insufficient_funds_credit |  | minor | security | Источник уведомлений оператора не описан и не аутентифицирован, а по ним списываются деньг | lens:risk | №08 |
| autopay.event_conflict.insufficient_funds_credit |  | major | ambiguity | НФ-1: не определено, с какого и до какого события измеряется срок 5 минут | lens:analyst, lens:risk | №05, №08 |
| autopay.event_conflict.insufficient_funds_credit |  | major | incomplete | Требование карты в KZT не проверяется в createAutopay и не имеет кода ответа | lens:risk, lens:architect, lens:analyst | №05, №07, №08 |
| autopay.event_conflict.insufficient_funds_credit |  | minor | incomplete | НФ-1: не указано, за какой период и при какой нагрузке измеряется доля 99 % | lens:analyst | №05 |
| autopay.event_conflict.insufficient_funds_credit |  | minor | ops_risk | Параллельные уведомления у границы лимита трёх пополнений могут дать четыре | lens:risk | №08 |
| autopay.event_conflict.insufficient_funds_credit |  | minor | other | Функциональные требования и НФ-1 не имеют приоритетов | consistency | №09 |
| autopay.event_conflict.insufficient_funds_credit |  | major | contradiction | Цель гарантирует, что баланс не опустится ниже порога, но правила это не обеспечивают | consistency | №09 |
| autopay.event_conflict.insufficient_funds_credit |  | major | missing_element | Тело успешного ответа createAutopay (200) не описано, хотя таблица отсылает к разделу мето | lens:architect, consistency | №07, №09 |
| autopay.range_boundary.trigger_at_threshold |  | major | missing_element | Способ получения уведомления о балансе от оператора не описан | lens:analyst | №05 |
| autopay.range_boundary.trigger_at_threshold |  | major | contradiction | Лимит АП-5 задан на номер, а настройка и проверка дубля — на карту | lens:risk | №08 |
| autopay.range_boundary.trigger_at_threshold |  | major | incomplete | Требование «карта KZT» из АП-1 не проверяется логикой createAutopay | lens:analyst, lens:architect, lens:risk | №05, №07, №08 |
| autopay.range_boundary.trigger_at_threshold |  | major | ambiguity | Не определено, что считается выполненным пополнением для лимита и срока | lens:analyst, lens:qa | №05, №06 |
| autopay.range_boundary.trigger_at_threshold |  | minor | other | Несколько независимых правил объединены в одном пункте АП-1 и в строке интеграции | lens:analyst | №05 |
| autopay.range_boundary.trigger_at_threshold |  | minor | security | Идентификатор карты в адресе GET и DELETE может быть номером карты | lens:risk | №08 |
| autopay.range_boundary.trigger_at_threshold |  | minor | other | Уведомление, пришедшее до удаления настройки, не имеет определённого исхода | lens:risk | №08 |
| autopay.range_boundary.trigger_at_threshold |  | minor | unverifiable | «Клиент получает push» не задаёт, что проверяется: отправка или доставка | lens:risk | №08 |
| autopay.range_boundary.trigger_at_threshold |  | minor | security | Подлинность уведомления оператора, по которому идёт списание, не проверяется | lens:risk | №08 |
| autopay.range_boundary.trigger_at_threshold |  | major | incomplete | Тело успешного ответа createAutopay не описано, хотя таблица отсылает к разделу | lens:architect, lens:qa | №06, №07 |
| autopay.range_boundary.trigger_at_threshold |  | minor | incomplete | Сбой оператора после списания с карты не описан: нет возврата и повтора | lens:risk | №08 |
| autopay.range_boundary.trigger_at_threshold |  | minor | unverifiable | НФ-1 не задаёт период, за который считается доля 99 % | lens:analyst | №05 |
| autopay.range_boundary.trigger_at_threshold |  | major | terminology | «Отключение» в АП-7 и «удаление» в deleteAutopay: состояние не определено | lens:analyst | №05 |
| autopay.range_boundary.trigger_at_threshold |  | minor | incomplete | Блокировка и закрытие карты при действующей настройке не описаны | lens:risk | №08 |
| autopay.two_statuses.range_422 |  | major | contradiction | Цель «баланс не опускается ниже порога» противоречит отказу при нехватке средств | lens:analyst | №05 |
| autopay.two_statuses.range_422 |  | minor | non_singular | АП-1 и пункт интеграции объединяют несколько независимых условий | lens:analyst | №05 |
| autopay.two_statuses.range_422 |  | major | missing_element | Тело успешного ответа createAutopay не описано, хотя L100 отсылает к разделу метода | lens:architect | №07 |
| autopay.two_statuses.range_422 |  | minor | incomplete | Не сказано, есть ли комиссия при списании с карты помимо суммы пополнения | lens:analyst | №05 |
| autopay.two_statuses.range_422 |  | major | ambiguity | Лимит и время пополнения: не сказано, списание или зачисление считается пополнением | lens:analyst | №05 |
| autopay.two_statuses.range_422 |  | major | incomplete | Попытки без пополнения из-за нехватки средств: входят ли в лимит трёх за сутки | lens:analyst | №05 |
| autopay.two_statuses.range_422 |  | major | missing_element | Критерии приёмки не покрывают границы, дедупликацию, отключение, 409, 401 и 404 | lens:qa | №06 |
| autopay.two_statuses.range_422 |  | major | ambiguity | Лимит трёх пополнений в сутки: не определено, по номеру или по настройке (карте) | lens:analyst | №05 |
| autopay.two_statuses.range_422 |  | major | unverifiable | НФ-1 не измеряется: нет старта, конца, знаменателя доли и периода выборки | lens:analyst, lens:qa | №05, №06 |
| autopay.two_statuses.range_422 |  | major | ambiguity | Повтор уведомления с тем же ID после отказа по средствам: выполнять пополнение или нет | lens:qa | №06 |
| autopay.two_statuses.range_422 |  | major | missing_element | Условие карты KZT из АП-1 не проверяется в логике createAutopay и не имеет кода ответа | lens:analyst, lens:architect | №05, №07 |
| autopay.two_statuses.range_422 |  | minor | incomplete | Для REST-методов интеграции не заданы время ответа и доступность | lens:architect | №07 |
| autopay.unit_change.limit_per_hour |  | major | ambiguity | Окно «за один час» в АП-5 не определено: скользящее или календарное | lens:qa, lens:analyst | №05, №06 |
| autopay.unit_change.limit_per_hour |  | minor | non_singular | АП-1, АП-4 и АП-6 объединяют несколько независимых правил | lens:analyst | №05 |
| autopay.unit_change.limit_per_hour |  | major | incomplete | Код ответа для отсутствующего обязательного поля createAutopay не описан | lens:architect | №07 |
| autopay.unit_change.limit_per_hour |  | minor | ops_risk | Судьба принятого уведомления при отключении автопополнения не описана | lens:risk | №08 |
| autopay.unit_change.limit_per_hour |  | minor | ambiguity | Неясно, входят ли попытки с отказом по нехватке средств в лимит | lens:analyst, lens:risk | №05, №08 |
| autopay.unit_change.limit_per_hour |  | major | incomplete | Не определено, может ли один номер быть подключён к нескольким картам | lens:analyst | №05 |
| autopay.unit_change.limit_per_hour |  | minor | ops_risk | Параллельные уведомления могут обойти лимит трёх пополнений в час | lens:risk | №08 |
| autopay.unit_change.limit_per_hour |  | minor | security | getAutopay и deleteAutopay не описывают проверку принадлежности карты | lens:architect | №07 |
| autopay.unit_change.limit_per_hour |  | major | incomplete | createAutopay не проверяет валюту KZT карты из АП-1 | lens:architect, lens:risk | №07, №08 |
| autopay.unit_change.limit_per_hour |  | major | incomplete | Критерии приёмки не покрывают границы, отключение, повторы и коды ошибок | lens:qa | №06 |
| autopay.unit_change.limit_per_hour |  | major | api_contract | Тело успешного ответа createAutopay не описано, хотя отсылка есть | lens:architect | №07 |
| autopay.unit_change.limit_per_hour |  | minor | missing_element | Поведение настройки при блокировке, закрытии и перевыпуске карты не описано | lens:risk | №08 |
| autopay.unit_change.limit_per_hour |  | minor | ops_risk | После списания при ошибке оператора порядок возврата суммы не описан | lens:risk | №08 |
| autopay.unit_change.limit_per_hour |  | major | unverifiable | НФ-1: не определены конечное событие и место измерения пятиминутного срока | lens:analyst, lens:risk | №05, №08 |
| autopay.unit_change.limit_per_hour |  | minor | security | Канал и проверка подлинности уведомления о балансе не описаны | lens:risk | №08 |
| cardblock.combo.unit_change-blocked_at_utc+two_statuses-reblock_200 |  | major | missing_element | Инициатор изменения статуса обещан в данных, но не описан | consistency | №09 |
| cardblock.combo.unit_change-blocked_at_utc+two_statuses-reblock_200 |  | major | ambiguity | Срок блокировки в сутках: момент возврата в ACTIVE не определён | lens:analyst, lens:qa, lens:risk | №05, №06, №08 |
| cardblock.combo.unit_change-blocked_at_utc+two_statuses-reblock_200 |  | minor | api_contract | Тип поля days не определён: нецелое или строковое значение | lens:architect | №07 |
| cardblock.combo.unit_change-blocked_at_utc+two_statuses-reblock_200 |  | minor | api_contract | Повторная блокировка с недопустимым days: порядок проверок не задан | lens:architect | №07 |
| cardblock.combo.unit_change-blocked_at_utc+two_statuses-reblock_200 |  | minor | unverifiable | Срок 10 секунд без доли запросов и нагрузки | lens:analyst | №05 |
| cardblock.combo.unit_change-blocked_at_utc+two_statuses-reblock_200 |  | major | incomplete | Ответ 500 на blockCard: не описано, применилась ли блокировка | consistency | №09 |
| cardblock.combo.unit_change-blocked_at_utc+two_statuses-reblock_200 |  | minor | ops_risk | Автоматический возврат в ACTIVE без механизма и без описания сбоя | lens:risk | №08 |
| cardblock.combo.unit_change-blocked_at_utc+two_statuses-reblock_200 |  | major | unverifiable | Push о блокировке без срока отправки и критерия выполнения | lens:qa | №06 |
| cardblock.combo.unit_change-blocked_at_utc+two_statuses-reblock_200 |  | major | ambiguity | Авторизация «новая» или «до блокировки»: момент поступления или одобрения не определён | lens:analyst | №05 |
| cardblock.combo.unit_change-blocked_at_utc+two_statuses-reblock_200 |  | minor | incomplete | Финансовое проведение авторизации, одобренной до блокировки, не описано | lens:risk | №08 |
| cardblock.combo.unit_change-blocked_at_utc+two_statuses-reblock_200 |  | minor | incomplete | Требования без приоритетов и с ID только у БК-пунктов | consistency | №09 |
| cardblock.combo.unit_change-blocked_at_utc+two_statuses-reblock_200 |  | major | incomplete | Значение days для бессрочной блокировки и ответ getCardStatus не описаны | lens:analyst, lens:architect, consistency | №05, №07, №09 |
| cardblock.combo.unit_change-blocked_at_utc+two_statuses-reblock_200 |  | minor | other | Пункты БК-2, БК-3 и БК-7 объединяют несколько независимых правил | lens:analyst | №05 |
| cardblock.combo.unit_change-blocked_at_utc+two_statuses-reblock_200 |  | major | ambiguity | Авторизация в окне до вступления блокировки: одобрить или отклонить не определено | consistency | №09 |
| cardblock.combo.unit_change-blocked_at_utc+two_statuses-reblock_200 |  | major | incomplete | Критерии приёмки не покрывают ветки ошибок, разблокировку и истечение срока | lens:qa | №06 |
| cardblock.combo.unit_change-blocked_at_utc+two_statuses-reblock_200 |  | major | incomplete | Возврат покупки на карту в статусе BLOCKED_BY_CLIENT не описан | lens:risk | №08 |
| cardblock.drop_promised.no_last_digits |  | major | incomplete | Окно 10 секунд: статус карты и граница «до блокировки» не определены | consistency, lens:risk | №08, №09 |
| cardblock.drop_promised.no_last_digits |  | minor | unverifiable | Срок вступления блокировки в силу не измерим по доле запросов | lens:analyst, lens:risk | №05, №08 |
| cardblock.drop_promised.no_last_digits |  | minor | terminology | Один компонент назван «Мобильный банк» и «Приложение» | consistency | №09 |
| cardblock.drop_promised.no_last_digits |  | major | api_contract | Неверный тип поля days не покрыт кодами ответа | lens:architect | №07 |
| cardblock.drop_promised.no_last_digits |  | major | ambiguity | Право блокировки держателя дополнительной карты не определено | lens:analyst, lens:risk | №05, №08 |
| cardblock.drop_promised.no_last_digits |  | major | ambiguity | Повторная блокировка после разблокировки: срок предыдущей блокировки не определён | lens:analyst | №05 |
| cardblock.drop_promised.no_last_digits |  | minor | other | Функциональные требования не приоритизированы | consistency | №09 |
| cardblock.drop_promised.no_last_digits |  | minor | incomplete | Для методов интеграции не заданы время ответа и доступность | lens:architect | №07 |
| cardblock.drop_promised.no_last_digits |  | major | incomplete | Тело getCardStatus для бессрочной блокировки и статуса ACTIVE не определено | lens:qa, lens:architect, consistency | №06, №07, №09 |
| cardblock.drop_promised.no_last_digits |  | minor | non_singular | Пункты БК-2, БК-5 и БК-7 объединяют несколько правил | lens:analyst | №05 |
| cardblock.drop_promised.no_last_digits |  | minor | ops_risk | Повтор blockCard после успешной блокировки получает 409 | lens:risk | №08 |
| cardblock.drop_promised.no_last_digits |  | major | incomplete | Критерии приёмки не покрывают отказы, граничные сроки и разблокировку | lens:qa | №06 |
| cardblock.drop_promised.no_last_digits |  | major | missing_element | Инициатор изменения и срок бессрочной блокировки в данных не определены | consistency, lens:architect, lens:analyst | №05, №07, №09 |
| cardblock.drop_promised.no_last_digits |  | major | incomplete | Возвраты и зачисления на карту в статусе BLOCKED_BY_CLIENT не описаны | lens:analyst, lens:risk | №05, №08 |
| cardblock.drop_promised.no_last_digits |  | major | ambiguity | Проведение авторизации, одобренной до блокировки, не определено | lens:risk | №08 |
| cardblock.drop_promised.no_last_digits |  | critical | ambiguity | Срок блокировки: момент возврата в ACTIVE и граница суток не определены | lens:risk, lens:qa, consistency, lens:analyst | №05, №06, №08, №09 |
| cardblock.event_conflict.unblock_daily_limit |  | major | missing_element | Время последней разблокировки не хранится, хотя нужно для БК-8 | lens:architect | №07 |
| cardblock.event_conflict.unblock_daily_limit |  | major | incomplete | Интервал до 10 секунд после ответа 200 blockCard: исход авторизации не задан | consistency | №09 |
| cardblock.event_conflict.unblock_daily_limit |  | minor | other | Функциональные требования БК-1…БК-8 без приоритета | consistency | №09 |
| cardblock.event_conflict.unblock_daily_limit |  | major | ambiguity | Понятие «сутки» в БК-8 не определено: календарные или скользящие 24 часа | lens:analyst, lens:qa | №05, №06 |
| cardblock.event_conflict.unblock_daily_limit |  | major | missing_element | Критерии приёмки не покрывают разблокировку, границы срока и коды ответов | lens:qa | №06 |
| cardblock.event_conflict.unblock_daily_limit |  | minor | ops_risk | Сбой отправки push после блокировки не обработан | lens:risk | №08 |
| cardblock.event_conflict.unblock_daily_limit |  | major | api_contract | Код ответа на разблокировку сверх лимита БК-8 не определён | lens:architect | №07 |
| cardblock.event_conflict.unblock_daily_limit |  | major | ambiguity | Понятие «новые авторизации» в БК-3 не определено; повтор и рост суммы неясны | lens:risk | №08 |
| cardblock.event_conflict.unblock_daily_limit |  | major | incomplete | Исход blockCard при ответе 500 или обрыве не определён | consistency, lens:risk | №08, №09 |
| cardblock.event_conflict.unblock_daily_limit |  | minor | unverifiable | БК-5 не задаёт точку и долю измерения 10-секундного срока | lens:analyst, lens:risk | №05, №08 |
| cardblock.event_conflict.unblock_daily_limit |  | minor | incomplete | Ответ getCardStatus не описан для статуса ACTIVE | lens:architect | №07 |
| cardblock.event_conflict.unblock_daily_limit |  | minor | terminology | Названия приложения и срока блокировки не едины, глоссария нет | consistency | №09 |
| cardblock.event_conflict.unblock_daily_limit |  | major | api_contract | Порядок проверок days и статуса карты не задан: 400 или 409 | lens:architect | №07 |
| cardblock.event_conflict.unblock_daily_limit |  | major | ambiguity | Момент окончания срока блокировки и возврат в ACTIVE не определены | lens:analyst, lens:risk, consistency | №05, №08, №09 |
| cardblock.event_conflict.unblock_daily_limit |  | major | missing_element | Push-уведомление по БК-7 не описано в части B и не назначен отправитель | consistency | №09 |
| cardblock.event_conflict.unblock_daily_limit |  | major | api_contract | days с неверным типом или пустым значением: ошибка и риск бессрочной блокировки | lens:architect, lens:risk | №07, №08 |
| cardblock.event_conflict.unblock_daily_limit |  | minor | missing_element | Инициатор изменения хранится, но не описан в модели и в ответе | consistency | №09 |
| cardblock.event_conflict.unblock_daily_limit |  | minor | unverifiable | Push по БК-7 не имеет проверяемого признака отправки | lens:qa | №06 |
| cardblock.event_conflict.unblock_daily_limit |  | minor | other | Пункты БК-1, БК-2 и БК-7 объединяют несколько правил | lens:analyst | №05 |
| cardblock.event_conflict.unblock_daily_limit |  | major | incomplete | Списание по авторизации, одобренной до блокировки, не описано | lens:analyst | №05 |
| cardblock.event_conflict.unblock_daily_limit |  | major | missing_element | Значение срока для бессрочной блокировки не определено в данных и в ответе getCardStatus | lens:analyst, lens:qa | №05, №06 |
| cardblock.range_boundary.days_400_at_30 |  | major | ambiguity | Момент отсчёта и окончания срока блокировки и единица «сутки» не определены | lens:analyst, lens:qa, lens:risk, consistency | №05, №06, №08, №09 |
| cardblock.range_boundary.days_400_at_30 |  | major | ambiguity | Смысл поля days в getCardStatus не задан: исходный срок или остаток | lens:analyst | №05 |
| cardblock.range_boundary.days_400_at_30 |  | minor | incomplete | Несколько правил собраны в одном пункте БК-2 и БК-7 | lens:analyst | №05 |
| cardblock.range_boundary.days_400_at_30 |  | minor | terminology | Одни и те же понятия названы по-разному, глоссария нет | consistency | №09 |
| cardblock.range_boundary.days_400_at_30 |  | major | incomplete | Тело getCardStatus не описано для статуса ACTIVE и бессрочной блокировки | lens:qa, lens:architect | №06, №07 |
| cardblock.range_boundary.days_400_at_30 |  | minor | incomplete | Код 400 не описан для неверного типа поля days | lens:architect | №07 |
| cardblock.range_boundary.days_400_at_30 |  | major | incomplete | Исход авторизации в окне до вступления блокировки в силу не определён | lens:analyst, consistency | №05, №09 |
| cardblock.range_boundary.days_400_at_30 |  | major | ambiguity | Проведение по авторизации, одобренной до блокировки, не описано | lens:risk | №08 |
| cardblock.range_boundary.days_400_at_30 |  | major | incomplete | Порядок проверок 404 и 409 при blockCard не задан | consistency | №09 |
| cardblock.range_boundary.days_400_at_30 |  | major | ops_risk | После ответа 500 на blockCard неизвестно, применилась ли блокировка | lens:risk | №08 |
| cardblock.range_boundary.days_400_at_30 |  | minor | ops_risk | Не описано поведение при сбое доставки push | lens:risk | №08 |
| cardblock.range_boundary.days_400_at_30 |  | major | incomplete | Порядок проверок 400 и 409 при blockCard не задан | lens:architect | №07 |
| cardblock.range_boundary.days_400_at_30 |  | minor | other | Приоритет и важность функциональных требований не указаны | consistency | №09 |
| cardblock.range_boundary.days_400_at_30 |  | minor | incomplete | Срок «не позднее 10 секунд» не привязан к месту измерения и доле запросов | lens:risk | №08 |
| cardblock.range_boundary.days_400_at_30 |  | major | missing_element | Приёмка покрывает три сценария; границы, отказы и разблокировка не покрыты | lens:qa | №06 |
| cardblock.range_boundary.days_400_at_30 |  | minor | ambiguity | Право блокировки для держателя дополнительной карты не определено | lens:analyst | №05 |
| cardblock.range_boundary.days_400_at_30 |  | major | missing_element | Push-уведомление БК-7 обещано, но отправитель и событие не описаны | consistency | №09 |
| cardblock.two_statuses.reblock_200 |  | major | incomplete | Проведение авторизации, одобренной до блокировки, не описано | lens:analyst, lens:risk | №05, №08 |
| cardblock.two_statuses.reblock_200 |  | minor | unverifiable | Срок вступления блокировки в силу 10 секунд: нет доли случаев, нагрузки и места замера | lens:analyst, lens:risk | №05, №08 |
| cardblock.two_statuses.reblock_200 |  | major | incomplete | Авторизация в окне до вступления блокировки в силу (до 10 секунд) не определена | consistency | №09 |
| cardblock.two_statuses.reblock_200 |  | minor | other | Функциональные требования БК-1…БК-7 не имеют приоритетов | consistency | №09 |
| cardblock.two_statuses.reblock_200 |  | major | incomplete | Неверный тип поля days не имеет определённого кода ответа | lens:architect | №07 |
| cardblock.two_statuses.reblock_200 |  | major | api_contract | Ответ getCardStatus не описан для бессрочной блокировки и для статуса ACTIVE | lens:qa, lens:architect | №06, №07 |
| cardblock.two_statuses.reblock_200 |  | minor | terminology | Один объект назван тремя разными словами: «Мобильный банк», «приложении», «Приложение» | consistency | №09 |
| cardblock.two_statuses.reblock_200 |  | major | ambiguity | Повторная блокировка с другим days: срок меняется или остаётся прежним | consistency | №09 |
| cardblock.two_statuses.reblock_200 |  | minor | unverifiable | Срок доставки push о блокировке не задан | lens:qa | №06 |
| cardblock.two_statuses.reblock_200 |  | major | missing_element | Приёмка не покрывает границы, ошибки, разблокировку и getCardStatus | lens:qa | №06 |
| cardblock.two_statuses.reblock_200 |  | major | incomplete | Повторная блокировка: не определено, отправляется ли повторный push | lens:analyst | №05 |
| cardblock.two_statuses.reblock_200 |  | minor | non_singular | БК-2 и поля данных объединяют несколько независимых правил в одной фразе | lens:analyst | №05 |
| cardblock.two_statuses.reblock_200 |  | minor | terminology | Допустимые значения инициатора изменения статуса не заданы | lens:analyst | №05 |
| cardblock.two_statuses.reblock_200 |  | minor | ops_risk | Push о блокировке: сбой отправки и повтор не описаны | lens:risk | №08 |
| cardblock.two_statuses.reblock_200 |  | major | ambiguity | Срок блокировки: не определены точка отсчёта и момент возврата в ACTIVE | lens:analyst, lens:qa, lens:risk | №05, №06, №08 |
| cardblock.two_statuses.reblock_200 |  | major | missing_element | Переход карты в ACTIVE по истечении срока не описан механизмом и не имеет отказоустойчивос | consistency, lens:risk | №08, №09 |
| cardblock.two_statuses.reblock_200 |  | major | contradiction | Цель «временно блокирует» противоречит бессрочной блокировке из БК-2 | consistency | №09 |
| cardblock.two_statuses.reblock_200 |  | minor | missing_element | Параметр пути cardId не описан ни в одном методе | lens:architect | №07 |
| cardblock.unit_change.blocked_at_utc |  | major | incomplete | Порядок проверок 400 и 409 при одновременном нарушении срока и статуса | lens:architect | №07 |
| cardblock.unit_change.blocked_at_utc |  | major | missing_element | Критерии приёмки не покрывают разблокировку, срок, ошибки и push | lens:qa | №06 |
| cardblock.unit_change.blocked_at_utc |  | major | ops_risk | Результат blockCard при ответе 500 не определён: блокировка могла примениться | lens:risk | №08 |
| cardblock.unit_change.blocked_at_utc |  | major | ambiguity | Момент окончания срока блокировки не определён: сутки и точка отсчёта | lens:analyst, lens:qa, lens:risk | №05, №06, №08 |
| cardblock.unit_change.blocked_at_utc |  | minor | incomplete | Параметр пути {cardId} не описан: тип, формат и источник не указаны | lens:architect | №07 |
| cardblock.unit_change.blocked_at_utc |  | minor | incomplete | Срок вступления блокировки в силу: не назван доля запросов и место измерения | lens:risk | №08 |
| cardblock.unit_change.blocked_at_utc |  | minor | ops_risk | Доставка push о блокировке не гарантирована и не описан повтор | lens:risk | №08 |
| cardblock.unit_change.blocked_at_utc |  | major | incomplete | Поведение при days=null, дробном или строковом значении не описано | lens:architect | №07 |
| cardblock.unit_change.blocked_at_utc |  | minor | non_singular | Несколько независимых правил в пунктах БК-2, БК-7 и требованиях к данным | lens:analyst | №05 |
| cardblock.unit_change.blocked_at_utc |  | minor | ambiguity | Право блокировки держателя дополнительной карты не определено | lens:risk | №08 |
| cardblock.unit_change.blocked_at_utc |  | minor | incomplete | Статусы карты кроме ACTIVE и BLOCKED_BY_CLIENT не описаны | lens:risk | №08 |
| cardblock.unit_change.blocked_at_utc |  | minor | terminology | Значения поля «инициатор изменения» не перечислены | lens:analyst | №05 |
| cardblock.unit_change.blocked_at_utc |  | minor | ambiguity | Проведение авторизации, одобренной до блокировки, не описано | lens:risk | №08 |
| cardblock.unit_change.blocked_at_utc |  | major | ambiguity | Момент блокировки не определён: ответ 200 или вступление в силу | lens:analyst | №05 |
| cardblock.unit_change.blocked_at_utc |  | major | incomplete | Ответ getCardStatus для ACTIVE и бессрочной блокировки не описан | lens:qa, lens:architect | №06, №07 |
| cashback.combo.event_conflict-category_effective_now+range_boundary-cap_strict |  | major | incomplete | Для getCashback не описаны ошибки 401, 404 и 500 | lens:qa | №06 |
| cashback.combo.event_conflict-category_effective_now+range_boundary-cap_strict |  | major | incomplete | Срок выбора категории не имеет кода ответа при нарушении | lens:architect | №07 |
| cashback.combo.event_conflict-category_effective_now+range_boundary-cap_strict |  | major | incomplete | Тело успешного ответа saveCategory не описано | lens:architect | №07 |
| cashback.combo.event_conflict-category_effective_now+range_boundary-cap_strict |  | major | ambiguity | Округление кэшбэка: по покупке или за месяц — разный результат | lens:qa | №06 |
| cashback.combo.event_conflict-category_effective_now+range_boundary-cap_strict |  | major | missing_element | Большинство требований и веток не покрыты критериями приёмки | lens:qa | №06 |
| cashback.combo.event_conflict-category_effective_now+range_boundary-cap_strict |  | major | missing_element | Для возврата не хранятся признаки, нужные для выбора ветки КБ-6 | lens:architect | №07 |
| cashback.combo.event_conflict-category_effective_now+range_boundary-cap_strict |  | major | ambiguity | Возврат после зачисления без следующего зачисления не определён | lens:qa | №06 |
| cashback.drop_promised.no_read_method |  | minor | incomplete | Месяц, к которому относится выбор категории, не задан в saveCategory | lens:architect | №07 |
| cashback.drop_promised.no_read_method |  | minor | incomplete | Тело успешного ответа saveCategory не описано, хотя ссылка есть | lens:architect | №07 |
| cashback.drop_promised.no_read_method |  | major | missing_element | Для КБ-6 не хранятся тип операции и ссылка на исходную покупку | lens:architect | №07 |
| cashback.drop_promised.no_read_method |  | major | incomplete | Срок выбора по КБ-1 не проверяется в saveCategory и не имеет кода ответа | lens:architect | №07 |
| cashback.event_conflict.category_effective_now |  | major | incomplete | Ответ getCashback для клиента без выбранной категории не описан | lens:architect | №07 |
| cashback.event_conflict.category_effective_now |  | major | ambiguity | Поле category в getCashback: не определено, сохранённая или действующая категория | lens:architect | №07 |
| cashback.event_conflict.category_effective_now |  | major | incomplete | Срок выбора категории из КБ-1 не проверяется в логике saveCategory | lens:architect | №07 |
| cashback.event_conflict.category_effective_now |  | major | incomplete | Тело успешного ответа saveCategory не описано, хотя статус 200 отсылает к нему | lens:architect | №07 |
| cashback.event_conflict.category_effective_now |  | major | ambiguity | Точка округления кэшбэка не указана: за покупку или за месяц | consistency | №09 |
| cashback.event_conflict.category_effective_now |  | minor | missing_element | Приоритеты функциональных и нефункциональных требований не указаны | consistency | №09 |
| cashback.event_conflict.category_effective_now |  | minor | unverifiable | НФ-1: не указано, от какого момента до какого отсчитываются 500 мс | lens:architect | №07 |
| cashback.event_conflict.category_effective_now |  | minor | terminology | Одни и те же понятия названы по-разному, глоссарий не охватывает их | consistency | №09 |
| cashback.event_conflict.category_effective_now |  | major | incomplete | Возврат после зачисления не описан, если следующего зачисления не будет | consistency | №09 |
| cashback.range_boundary.cap_strict |  | major | incomplete | saveCategory не описывает отказ при выборе категории после конца месяца | lens:architect | №07 |
| cashback.range_boundary.cap_strict |  | minor | incomplete | Сбой зачисления кэшбэка 5-го числа не описан: нет повтора и статуса | lens:risk | №08 |
| cashback.range_boundary.cap_strict |  | minor | missing_element | Статус карты, блокировка и перевыпуск не описаны; судьба категории и кэшбэка неизвестна | lens:risk | №08 |
| cashback.range_boundary.cap_strict |  | minor | ops_risk | Повторная передача покупки процессингом учитывается дважды: нет ключа распознавания | lens:risk | №08 |
| cashback.range_boundary.cap_strict |  | major | missing_element | Модель данных не связывает возврат с покупкой: нет идентификатора покупки и суммы возврата | lens:architect | №07 |
| cashback.range_boundary.cap_strict |  | major | missing_element | Тело успешного ответа saveCategory не описано, хотя таблица статусов на него ссылается | lens:architect | №07 |
| cashback.range_boundary.cap_strict |  | major | incomplete | Возврат после зачисления: исход не определён, если следующего зачисления нет или оно меньш | lens:risk | №08 |
| cashback.range_boundary.cap_strict |  | major | ambiguity | getCashback: неясно, какая категория возвращается до смены на следующий месяц | lens:architect | №07 |
| cashback.range_boundary.cap_strict |  | minor | incomplete | cardId в путях обоих методов не описан по типу и формату | lens:architect | №07 |
| cashback.two_statuses.bad_category_200 |  | major | ambiguity | Момент зачисления 5-го числа не задан: граница возврата неопределена | lens:risk | №08 |
| cashback.two_statuses.bad_category_200 |  | major | missing_element | Тело успешного ответа saveCategory не описано, хотя раздел на него ссылается | lens:architect | №07 |
| cashback.two_statuses.bad_category_200 |  | major | incomplete | Возврат после зачисления без следующего зачисления: результат не определён | lens:risk | №08 |
| cashback.two_statuses.bad_category_200 |  | minor | incomplete | Покупка в иностранной валюте не описана: пересчёт и курс не заданы | lens:risk | №08 |
| cashback.two_statuses.bad_category_200 |  | major | incomplete | Выбор категории после конца месяца: saveCategory не проверяет срок | lens:architect | №07 |
| cashback.two_statuses.bad_category_200 |  | minor | missing_element | Для возврата нет признака зачисления кэшбэка в хранимых данных | lens:architect | №07 |
| cashback.two_statuses.bad_category_200 |  | major | ambiguity | Дата, по которой покупка относится к месяцу кэшбэка, не определена | lens:risk | №08 |
| cashback.two_statuses.bad_category_200 |  | major | missing_element | Возврат не связан с исходной покупкой: месяц покупки не определить | lens:risk | №08 |
| cashback.two_statuses.bad_category_200 |  | major | ambiguity | Повторный выбор категории в месяце: не определено, какой выбор действует | lens:risk | №08 |
| cashback.two_statuses.bad_category_200 |  | minor | incomplete | Ответ getCashback не описан для клиента без выбранной категории | lens:architect | №07 |
| cashback.two_statuses.bad_category_200 |  | minor | ops_risk | Сбой зачисления кэшбэка 5-го числа не описан: повтор и итог неизвестны | lens:risk | №08 |
| cashback.two_statuses.bad_category_200 |  | major | ambiguity | Неясно, какую категорию возвращает getCashback после выбора на следующий месяц | lens:architect | №07 |
| cashback.two_statuses.bad_category_200 |  | major | missing_element | Не описано, по какому признаку покупка относится к категории | lens:risk | №08 |
| cashback.unit_change.accrued_in_tiyn |  | minor | non_singular | В одних пунктах КБ-1, КБ-6 и НФ-1 объединено несколько независимых правил | lens:analyst | №05 |
| cashback.unit_change.accrued_in_tiyn |  | major | missing_element | Запрос saveCategory без поля category или с пустым значением не имеет кода ответа | lens:architect | №07 |
| cashback.unit_change.accrued_in_tiyn |  | major | ambiguity | КБ-7: неясно, показывается категория текущего или следующего месяца | lens:analyst | №05 |
| cashback.unit_change.accrued_in_tiyn |  | major | terminology | Кто выбирает категорию и получает кэшбэк по дополнительной карте | lens:analyst | №05 |
| cashback.unit_change.accrued_in_tiyn |  | critical | unit_mismatch | Единица поля accrued: тиыны в описании, 100.00 в примере и критерии в тенге | lens:analyst, lens:architect, rules:units.minor_fraction | №05, №07, №12 |
| cashback.unit_change.accrued_in_tiyn |  | major | incomplete | Перенос уменьшения после возврата не определён при отсутствии или малом следующем зачислен | lens:analyst | №05 |
| cashback.unit_change.accrued_in_tiyn |  | major | incomplete | Поведение при сохранении категории после срока и при отсутствии выбора не описано | lens:analyst, lens:architect | №05, №07 |
| cashback.unit_change.accrued_in_tiyn |  | major | ambiguity | КБ-6 уменьшает кэшбэк при возврате покупки ниже порога или вне категории | lens:analyst | №05 |
| cashback.unit_change.accrued_in_tiyn |  | minor | incomplete | Не определено, как учитывать покупку не в тенге при пороге 500 ₸ | lens:analyst | №05 |
| cashback.unit_change.accrued_in_tiyn |  | major | missing_element | Для возврата нет идентификатора покупки и суммы возврата в перечне данных | lens:architect | №07 |
| cashback.unit_change.accrued_in_tiyn |  | major | ambiguity | НФ-1: не определены начало и конец замера времени ответа 500 мс | lens:analyst | №05 |
| cashback.unit_change.accrued_in_tiyn |  | major | missing_element | Тело успешного ответа saveCategory отсылает к разделу, где его нет | lens:architect | №07 |
| cashback.unit_change.accrued_in_tiyn |  | major | api_contract | Поле category в getCashback: неясно, текущая или выбранная на следующий месяц категория | lens:architect | №07 |
| transfer_limit.combo.two_statuses-range_200_error+drop_promised-no_read_method |  | major | incomplete | Поведение при использованной сумме выше нового лимита не описано | lens:risk, lens:analyst | №05, №08 |
| transfer_limit.combo.two_statuses-range_200_error+drop_promised-no_read_method |  | minor | incomplete | Правило пересчёта в тенге для переводов в другой валюте не описано | lens:risk | №08 |
| transfer_limit.combo.two_statuses-range_200_error+drop_promised-no_read_method |  | minor | terminology | Термины не едины: «Использовано» и «использованная сумма», «Мобильный банк» и «Приложение» | consistency | №09 |
| transfer_limit.combo.two_statuses-range_200_error+drop_promised-no_read_method |  | major | missing_element | Отмена не связана с исходным переводом: в данных нет его идентификатора и даты | lens:architect, lens:risk | №07, №08 |
| transfer_limit.combo.two_statuses-range_200_error+drop_promised-no_read_method |  | major | incomplete | Критерии приёмки не покрывают отмену, смену лимита, показ, границы и коды 401/500 | lens:qa | №06 |
| transfer_limit.combo.two_statuses-range_200_error+drop_promised-no_read_method |  | minor | incomplete | Отмена за закрытые сутки не меняет остаток текущих суток, это не описано | lens:risk | №08 |
| transfer_limit.combo.two_statuses-range_200_error+drop_promised-no_read_method |  | minor | ambiguity | Граница суток оставляет без отнесения доли секунды после 23:59:59 | lens:analyst | №05 |
| transfer_limit.combo.two_statuses-range_200_error+drop_promised-no_read_method |  | minor | unverifiable | Для операций лимита в интеграции нет времени ответа и доступности | lens:architect | №07 |
| transfer_limit.combo.two_statuses-range_200_error+drop_promised-no_read_method |  | major | ambiguity | Какой лимит показывать после смены и до следующего перевода не определено | lens:analyst, consistency | №05, №09 |
| transfer_limit.combo.two_statuses-range_200_error+drop_promised-no_read_method |  | critical | ambiguity | Объект лимита не определён: клиент или номер телефона получателя | lens:risk, lens:analyst | №05, №08 |
| transfer_limit.combo.two_statuses-range_200_error+drop_promised-no_read_method |  | critical | contradiction | Входящие переводы: цель учитывает только исходящие, «Использовано» — все переводы | lens:analyst | №05 |
| transfer_limit.combo.two_statuses-range_200_error+drop_promised-no_read_method |  | major | ambiguity | Отметка времени перевода для отнесения к суткам не определена | lens:risk | №08 |
| transfer_limit.combo.two_statuses-range_200_error+drop_promised-no_read_method |  | minor | incomplete | Типы переводов, входящих в лимит, не перечислены | lens:risk | №08 |
| transfer_limit.combo.two_statuses-range_200_error+drop_promised-no_read_method |  | critical | ambiguity | Не определено, с какого этапа перевод увеличивает использованную сумму | lens:risk | №08 |
| transfer_limit.combo.two_statuses-range_200_error+drop_promised-no_read_method |  | minor | other | Пункты ЛП-1, ЛП-6 и интеграция объединяют несколько правил | lens:analyst | №05 |
| transfer_limit.combo.two_statuses-range_200_error+drop_promised-no_read_method |  | minor | incomplete | Одновременные переводы по одному номеру не покрыты правилом проверки лимита | consistency | №09 |
| transfer_limit.combo.two_statuses-range_200_error+drop_promised-no_read_method |  | minor | incomplete | У функциональных требований ЛП-1…ЛП-6 нет приоритета | consistency | №09 |
| transfer_limit.combo.two_statuses-range_200_error+drop_promised-no_read_method |  | major | incomplete | Отмена перевода введена без источника, события и срока отмены | consistency | №09 |
| transfer_limit.combo.two_statuses-range_200_error+drop_promised-no_read_method |  | minor | ops_risk | Повтор того же перевода и сбой после списания не описаны | lens:risk | №08 |
| transfer_limit.drop_promised.no_read_method |  | major | terminology | Учётный ключ и счётчик названы разными терминами в разных местах | consistency | №09 |
| transfer_limit.drop_promised.no_read_method |  | minor | incomplete | Не сказано, учитываются ли переводы из других каналов | lens:analyst | №05 |
| transfer_limit.drop_promised.no_read_method |  | minor | other | Приоритет требований ЛП-1…ЛП-6 не задан | consistency | №09 |
| transfer_limit.drop_promised.no_read_method |  | major | ambiguity | Состав учитываемых переводов не определён: направление по номеру и типы переводов | lens:risk | №08 |
| transfer_limit.drop_promised.no_read_method |  | minor | security | Изменение лимита не журналируется и не сообщается клиенту | lens:risk | №08 |
| transfer_limit.drop_promised.no_read_method |  | major | incomplete | Отмена не определена для частичного возврата и отмены после закрытия суток | lens:analyst | №05 |
| transfer_limit.drop_promised.no_read_method |  | minor | other | Параллельные переводы у границы лимита могут пройти вместе | lens:risk | №08 |
| transfer_limit.drop_promised.no_read_method |  | major | missing_element | Операция отмены перевода не описана: нет инициатора, метода и срока | consistency | №09 |
| transfer_limit.drop_promised.no_read_method |  | major | missing_element | Критерии приёмки не покрывают границы, отмену, смену лимита, остаток и ошибки API | lens:qa | №06 |
| transfer_limit.drop_promised.no_read_method |  | minor | other | Требования к интеграции не задают время ответа и доступность | lens:architect | №07 |
| transfer_limit.drop_promised.no_read_method |  | major | missing_element | ЛП-4 требует уменьшить сумму суток исходного перевода, но данные не хранят перевод | lens:risk, lens:architect | №07, №08 |
| transfer_limit.drop_promised.no_read_method |  | minor | other | Сбой после списания: не сказано, учитывается ли перевод | lens:risk | №08 |
| transfer_limit.drop_promised.no_read_method |  | major | ambiguity | Момент, с которого перевод учитывается в использованной сумме, не определён | lens:risk | №08 |
| transfer_limit.drop_promised.no_read_method |  | minor | boundary_conflict | Граница суток 23:59:59 не покрывает доли секунды | lens:analyst, lens:risk | №05, №08 |
| transfer_limit.drop_promised.no_read_method |  | minor | other | ЛП-1 и ЛП-6 объединяют независимые правила в один пункт | lens:analyst | №05 |
| transfer_limit.drop_promised.no_read_method |  | minor | traceability | Критерии приёмки, данные, интеграция и строки API без ID | consistency | №09 |
| transfer_limit.drop_promised.no_read_method |  | major | ambiguity | Лимит, показываемый сразу после изменения, не определён и противоречит ЛП-5 и ЛП-6 | lens:analyst, consistency | №05, №09 |
| transfer_limit.drop_promised.no_read_method |  | critical | contradiction | Учётный ключ лимита: номер телефона в цели и термине, клиент в данных и API | lens:risk, consistency, lens:analyst | №05, №08, №09 |
| transfer_limit.event_conflict.cancel_no_restore |  | minor | other | ЛП-1 объединяет диапазон, значение по умолчанию и момент применения | lens:analyst | №05 |
| transfer_limit.event_conflict.cancel_no_restore |  | major | incomplete | Запрос PUT без поля limit не имеет описанного кода ответа | lens:architect | №07 |
| transfer_limit.event_conflict.cancel_no_restore |  | minor | security | Повышение лимита до 3 000 000 ₸ вступает в силу сразу по одной сессии | lens:risk | №08 |
| transfer_limit.event_conflict.cancel_no_restore |  | minor | ambiguity | Интервал суток до секунды не покрывает доли секунды у границы | lens:analyst | №05 |
| transfer_limit.event_conflict.cancel_no_restore |  | major | missing_element | Операция перевода и отказ по лимиту не описаны в части B | consistency | №09 |
| transfer_limit.event_conflict.cancel_no_restore |  | major | ambiguity | Состав учитываемых переводов по фразе «по номеру телефона» не определён | lens:risk | №08 |
| transfer_limit.event_conflict.cancel_no_restore |  | minor | ambiguity | Для границы суток не назван источник времени перевода | lens:risk | №08 |
| transfer_limit.event_conflict.cancel_no_restore |  | minor | incomplete | Нет времени ответа и доступности для getTransferLimit и setTransferLimit | lens:architect | №07 |
| transfer_limit.event_conflict.cancel_no_restore |  | minor | other | Требования ЛП-1…ЛП-7 и интеграции не имеют приоритета | consistency | №09 |
| transfer_limit.event_conflict.cancel_no_restore |  | major | ambiguity | Этап перевода, с которого он учитывается в использованной сумме, не определён | lens:risk | №08 |
| transfer_limit.event_conflict.cancel_no_restore |  | major | incomplete | Остаток при снижении лимита ниже использованной суммы не определён | lens:analyst | №05 |
| transfer_limit.event_conflict.cancel_no_restore |  | major | incomplete | Отмена перевода не описана: нет операции, инициатора, правила после полуночи и связи с пер | consistency, lens:architect | №07, №09 |
| transfer_limit.event_conflict.cancel_no_restore |  | major | missing_element | Критерии приёмки покрывают три перевода и не проверяют границы, отмену, API и ошибки | lens:qa | №06 |
| transfer_limit.event_conflict.cancel_no_restore |  | major | incomplete | Лимит и остаток между setTransferLimit и следующим переводом показываются по-разному | consistency | №09 |
| transfer_limit.event_conflict.cancel_no_restore |  | major | ambiguity | Не определено, к какому объекту относится лимит: клиенту или номеру получателя | lens:analyst | №05 |
| transfer_limit.event_conflict.cancel_no_restore |  | minor | incomplete | Параллельные переводы у границы лимита не описаны | lens:risk | №08 |
| transfer_limit.range_boundary.reaching_rejects |  | major | missing_element | Отмена перевода, введённая ЛП-4, не описана ни операцией, ни инициатором, ни в приёмке | consistency, lens:analyst | №05, №09 |
| transfer_limit.range_boundary.reaching_rejects |  | major | ambiguity | Не определено, учитывается ли перевод в использованной сумме при создании или после выполн | lens:risk | №08 |
| transfer_limit.range_boundary.reaching_rejects |  | major | incomplete | Снижение лимита ниже уже использованной суммы не описано ни в ЛП-5, ни в setTransferLimit | consistency, lens:analyst | №05, №09 |
| transfer_limit.range_boundary.reaching_rejects |  | minor | ambiguity | Не сказано, входит ли комиссия за перевод в сумму «Использовано» | lens:analyst | №05 |
| transfer_limit.range_boundary.reaching_rejects |  | minor | unverifiable | В разделе интеграции нет времени ответа и доступности методов | lens:architect | №07 |
| transfer_limit.range_boundary.reaching_rejects |  | minor | incomplete | Не сказано, какие отмены уменьшают использованную сумму: клиентские, банковские, при сбое | lens:risk | №08 |
| transfer_limit.range_boundary.reaching_rejects |  | critical | ambiguity | Не определено, по какому объекту считается лимит: клиент в целом или каждый номер получате | lens:analyst | №05 |
| transfer_limit.range_boundary.reaching_rejects |  | major | api_contract | Поле limit описано как string в ответе и как integer в теле запроса | consistency, lens:architect | №07, №09 |
| transfer_limit.range_boundary.reaching_rejects |  | major | incomplete | Запрос PUT без обязательного поля limit не имеет кода ответа | lens:architect | №07 |
| transfer_limit.range_boundary.reaching_rejects |  | major | missing_element | Приёмка покрывает три сценария; границы лимита и коды 400, 401, 500 не проверяются | lens:qa | №06 |
| transfer_limit.range_boundary.reaching_rejects |  | minor | other | ЛП-1, ЛП-3 и ЛП-6 объединяют несколько самостоятельных правил | lens:analyst | №05 |
| transfer_limit.range_boundary.reaching_rejects |  | minor | other | Функциональные требования ЛП-1…ЛП-6 не имеют приоритета первой поставки | consistency | №09 |
| transfer_limit.range_boundary.reaching_rejects |  | minor | boundary_conflict | Граница суток не покрывает интервал 23:59:59–00:00:00 и доли секунды | lens:analyst, lens:risk | №05, №08 |
| transfer_limit.range_boundary.reaching_rejects |  | minor | terminology | Один показатель «использованная сумма» назван в трёх формулировках | consistency | №09 |
| transfer_limit.range_boundary.reaching_rejects |  | minor | ambiguity | ЛП-4 и определение «Использовано» по-разному описывают отмену после полуночи | consistency | №09 |
| transfer_limit.range_boundary.reaching_rejects |  | minor | ops_risk | Параллельные переводы у границы лимита без правила согласованности | lens:risk | №08 |
| transfer_limit.two_statuses.range_200_error |  | major | ambiguity | Показ лимита сразу после смены: прежний или новый (L028 против L029) | consistency | №09 |
| transfer_limit.two_statuses.range_200_error |  | minor | non_singular | ЛП-1 объединяет диапазон, целочисленность и значение по умолчанию | lens:analyst | №05 |
| transfer_limit.two_statuses.range_200_error |  | major | missing_element | Для отмены перевода (ЛП-4) не описаны данные исходного перевода | lens:architect | №07 |
| transfer_limit.two_statuses.range_200_error |  | minor | traceability | Нет ID и приоритетов у большинства пунктов документа | consistency | №09 |
| transfer_limit.two_statuses.range_200_error |  | major | missing_element | Критерии приёмки не покрывают границы, умолчание, отмену, новый лимит, показ и 401/500 | lens:qa | №06 |
| transfer_limit.two_statuses.range_200_error |  | minor | incomplete | Не определено, входят ли комиссия, переводы в иной валюте и на карту в «Использовано» | lens:analyst | №05 |
| transfer_limit.two_statuses.range_200_error |  | major | ambiguity | Момент, определяющий сутки перевода (создание, проведение, зачисление), не задан | lens:qa | №06 |
| transfer_limit.two_statuses.range_200_error |  | minor | boundary_conflict | Граница суток 23:59:59 не покрывает доли секунды в последней секунде дня | lens:analyst, lens:risk | №05, №08 |
| transfer_limit.two_statuses.range_200_error |  | minor | other | Параллельные переводы у границы лимита: проверка и учёт не заданы как атомарные | lens:risk | №08 |
| transfer_limit.two_statuses.range_200_error |  | minor | missing_element | Для getTransferLimit и setTransferLimit нет измеримых интеграционных показателей | lens:architect | №07 |
| transfer_limit.two_statuses.range_200_error |  | major | ambiguity | Отклонённая попытка после смены лимита: считается ли «переводом» (L028 против L026) | consistency | №09 |
| transfer_limit.two_statuses.range_200_error |  | minor | terminology | Термины расходятся: «Использовано», «Мобильный банк» и «Приложение» названы по-разному | consistency | №09 |
| transfer_limit.two_statuses.range_200_error |  | major | missing_element | Компонент проверки лимита при переводе и учёта суммы не назван | consistency | №09 |
| transfer_limit.two_statuses.range_200_error |  | major | api_contract | Тип поля limit: строка в ответе GET и integer в теле PUT | consistency, lens:architect | №07, №09 |
| transfer_limit.two_statuses.range_200_error |  | major | incomplete | Отсутствие обязательного поля limit: код ответа не назван | consistency | №09 |
| transfer_limit.two_statuses.range_200_error |  | critical | ambiguity | Лимит «по номеру телефона»: не определено, общий на клиента или на каждый номер | lens:analyst, lens:risk | №05, №08 |
| transfer_limit.two_statuses.range_200_error |  | major | incomplete | Снижение лимита ниже использованной суммы: остаток и доступность переводов не описаны | lens:analyst, lens:risk | №05, №08 |
| transfer_limit.unit_change.api_limit_in_tiyn |  | major | incomplete | Термин «Отменённый перевод» не определён: кто отменяет и считается ли возврат получателя | lens:analyst | №05 |
| transfer_limit.unit_change.api_limit_in_tiyn |  | major | missing_element | Отмена перевода (ЛП-4) без критерия приёмки и без описания операции отмены | consistency | №09 |
| transfer_limit.unit_change.api_limit_in_tiyn |  | minor | ops_risk | Параллельные переводы могут превысить лимит: атомарность проверки не описана | lens:risk | №08 |
| transfer_limit.unit_change.api_limit_in_tiyn |  | minor | terminology | Одни понятия названы разными терминами, глоссария нет | consistency | №09 |
| transfer_limit.unit_change.api_limit_in_tiyn |  | minor | other | Приоритеты функциональных требований не указаны | consistency | №09 |
| transfer_limit.unit_change.api_limit_in_tiyn |  | major | api_contract | Поле limit: строка в ответе GET и integer в теле PUT, round-trip не определён | consistency, lens:architect | №07, №09 |
| transfer_limit.unit_change.api_limit_in_tiyn |  | major | ambiguity | Момент, с которого перевод считается выполненным, не задан; ошибка 500 после списания | lens:risk | №08 |
| transfer_limit.unit_change.api_limit_in_tiyn |  | minor | ambiguity | Сутки до 23:59:59 не покрывают дробные секунды и момент отнесения перевода | lens:risk, lens:analyst | №05, №08 |
| transfer_limit.unit_change.api_limit_in_tiyn |  | major | ambiguity | Экран лимита: какой лимит и остаток показывать после смены лимита до перевода | consistency | №09 |
| transfer_limit.unit_change.api_limit_in_tiyn |  | minor | non_singular | ЛП-1 и пункты данных и интеграции объединяют несколько независимых правил | lens:analyst | №05 |
| transfer_limit.unit_change.api_limit_in_tiyn |  | major | security | Смена лимита одной сессией без подтверждения: повышение до максимума и сразу перевод | lens:risk | №08 |
| transfer_limit.unit_change.api_limit_in_tiyn |  | critical | ambiguity | Область учёта лимита не определена: по клиенту или по каждому номеру телефона | lens:risk, lens:analyst | №05, №08 |
| transfer_limit.unit_change.api_limit_in_tiyn |  | major | missing_element | Отмена перевода требует данных исходного перевода, которых модель не хранит | lens:architect | №07 |
| transfer_limit.unit_change.api_limit_in_tiyn |  | minor | incomplete | Для getTransferLimit и setTransferLimit не заданы время ответа и доступность | lens:architect | №07 |
| transfer_limit.unit_change.api_limit_in_tiyn |  | minor | incomplete | Отмена прошлых суток не возвращает видимый остаток текущих суток | lens:risk | №08 |
| transfer_limit.unit_change.api_limit_in_tiyn |  | major | missing_element | Критерии приёмки не покрывают границы, смену лимита, остаток, API и коды ошибок | lens:qa | №06 |
| transfer_limit.unit_change.api_limit_in_tiyn |  | major | incomplete | Отсутствие обязательного поля limit не покрыто ни одним кодом ответа | consistency | №09 |

Пропуски:

| Кейс | Тип дефекта | Близкая находка (не засчитана) | Владельцы |
| :--- | :--- | :--- | :--- |
| cashback.range_boundary.cap_strict | boundary_conflict | — | №12, №06 |
| cashback.unit_change.accrued_in_tiyn | unit_mismatch | D-01 Единица поля accrued: тиыны в описании, 100.00 в примере и к (lens:analyst, lens:architect, rules:units.minor_fraction); D-07 КБ-7: неясно, показывается категория текущего или следующего (lens:analyst) | №09, №12 |

| Кейс | Ожидание | Статус | Замечаний (к/с/н) | Вердикт |
| :--- | :--- | :--- | :--- | :--- |
| autopay.base | clean | partial | 16 (0/7/9) | conditional/conditional |
| autopay.combo.unit_change-limit_per_hour+drop_promised-no_409_status | defects | partial | 11 (1/6/4) | no/no |
| autopay.drop_promised.no_409_status | defects | partial | 18 (0/5/13) | conditional/conditional |
| autopay.event_conflict.insufficient_funds_credit | defects | partial | 23 (1/9/13) | no/no |
| autopay.paraphrase.nfr | clean | partial | 15 (0/9/6) | conditional/conditional |
| autopay.range_boundary.trigger_at_threshold | defects | partial | 15 (1/6/8) | no/no |
| autopay.two_statuses.range_422 | defects | partial | 13 (0/10/3) | conditional/conditional |
| autopay.unit_change.limit_per_hour | defects | partial | 16 (1/7/8) | no/no |
| cardblock.base | clean | complete | 18 (1/8/9) | no/no |
| cardblock.combo.unit_change-blocked_at_utc+two_statuses-reblock_200 | defects | complete | 18 (1/10/7) | no/no |
| cardblock.drop_promised.no_last_digits | defects | complete | 17 (1/10/6) | no/no |
| cardblock.event_conflict.unblock_daily_limit | defects | complete | 22 (1/13/8) | no/no |
| cardblock.paraphrase.keep_authorizations | clean | partial | 14 (1/7/6) | no/no |
| cardblock.range_boundary.days_400_at_30 | defects | complete | 18 (1/10/7) | no/no |
| cardblock.two_statuses.reblock_200 | defects | complete | 19 (1/10/8) | no/no |
| cardblock.unit_change.blocked_at_utc | defects | partial | 16 (0/8/8) | conditional/conditional |
| cashback.base | clean | partial | 15 (1/8/6) | no/conditional |
| cashback.combo.event_conflict-category_effective_now+range_boundary-cap_strict | defects | partial | 9 (2/7/0) | no/no |
| cashback.drop_promised.no_read_method | defects | partial | 5 (1/2/2) | no/no |
| cashback.event_conflict.category_effective_now | defects | partial | 10 (1/6/3) | no/no |
| cashback.paraphrase.rate | clean | partial | 10 (0/7/3) | conditional/conditional |
| cashback.range_boundary.cap_strict | defects | partial | 9 (0/5/4) | conditional/conditional |
| cashback.two_statuses.bad_category_200 | defects | partial | 14 (1/9/4) | no/no |
| cashback.unit_change.accrued_in_tiyn | defects | partial | 13 (1/10/2) | no/no |
| edge.empty | clean | complete | 0 (0/0/0) | yes/yes |
| transfer_limit.base | clean | complete | 21 (0/9/12) | conditional/conditional |
| transfer_limit.combo.two_statuses-range_200_error+drop_promised-no_read_method | defects | complete | 21 (5/6/10) | no/no |
| transfer_limit.drop_promised.no_read_method | defects | complete | 19 (2/8/9) | no/no |
| transfer_limit.event_conflict.cancel_no_restore | defects | complete | 17 (1/9/7) | no/no |
| transfer_limit.paraphrase.new_limit | clean | complete | 19 (1/6/12) | no/no |
| transfer_limit.range_boundary.reaching_rejects | defects | complete | 17 (2/6/9) | no/no |
| transfer_limit.two_statuses.range_200_error | defects | complete | 18 (2/9/7) | no/no |
| transfer_limit.unit_change.api_limit_in_tiyn | defects | complete | 18 (1/10/7) | no/no |
