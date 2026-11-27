# Корпус evaluation/dev — релиз-w4 20:00 корпус: d013c12, haiku

Кейсов 33 (не запускались 0), не измерено 0 (пропусков в счётчике 0).

| TP | FP | FN | Дубли | Precision | Recall | F1 |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 25 | 151 | 3 | 0 | 0.142 | 0.893 | 0.245 |

Чистые документы (8/8 измерено): замечаний 41, critical 0, major 0; документов с critical 0, с > 1 major 0, вердикт «нельзя» 0; документов с > 1 замечанием 8, максимум на одном 8. Ложных тревог по счётчику: 41.

Recall по типам: boundary_conflict 5/5, event_conflict 5/5, missing_element 5/6, status_conflict 4/6, unit_mismatch 6/6.

Время 67.0 мин суммарно, вызовов 274, $1.831.

Кандидаты этапов до судьи (верхняя граница): TP 27/28, recall 0.964; по типам: boundary_conflict 5/5, event_conflict 5/5, missing_element 5/6, status_conflict 6/6, unit_mismatch 6/6.

Вклад источников (замечание с несколькими источниками считается каждому):

| Источник | TP | FP | из них на чистых |
| :--- | ---: | ---: | ---: |
| consistency (№09) | 25 | 124 | 34 |
| lens:analyst (№05) | 13 | 2 | 0 |
| lens:architect (№07) | 12 | 20 | 4 |
| lens:qa (№06) | 17 | 1 | 1 |
| lens:risk (№08) | 6 | 8 | 2 |
| rules (№12) | 25 | 0 | 0 |

Ложные находки:

| Кейс | Чистый | Серьёзность | Тип | Замечание | Источники | Владельцы |
| :--- | :---: | :--- | :--- | :--- | :--- | :--- |
| autopay.base | да | minor | terminology | Оператор связи и настройка названы разными терминами | consistency | №09 |
| autopay.base | да | minor | contradiction | Второй номер на той же карте: отказ 409 или успех 200 | lens:qa | №06 |
| autopay.base | да | minor | incomplete | Учёт неуспешной попытки в лимите трёх в сутки не определён | consistency | №09 |
| autopay.base | да | minor | incomplete | Нет изменения порога и суммы существующей настройки | consistency | №09 |
| autopay.base | да | minor | other | Не у всех требований есть ID и приоритет | consistency | №09 |
| autopay.paraphrase.nfr | да | minor | missing_element | Функциональные требования не имеют приоритетов | consistency | №09 |
| autopay.paraphrase.nfr | да | minor | incomplete | Смена порога и суммы настройки не описана | consistency | №09 |
| autopay.paraphrase.nfr | да | minor | terminology | Термин «настройка автопополнения» назван по-разному | consistency | №09 |
| autopay.paraphrase.nfr | да | minor | ambiguity | Входят ли отказы по средствам в лимит трёх пополнений | consistency | №09 |
| autopay.paraphrase.nfr | да | minor | incomplete | Тело ответа createAutopay обещано, но не описано | lens:architect | №07 |
| cardblock.base | да | minor | incomplete | Авторизации в окне до вступления блокировки не описаны | consistency | №09 |
| cardblock.base | да | minor | contradiction | Цель говорит о временной блокировке, БК-2 — о бессрочной | consistency | №09 |
| cardblock.base | да | minor | terminology | Одно понятие названо «Мобильный банк» и «Приложение» | consistency | №09 |
| cardblock.base | да | minor | missing_element | У требований БК-1…БК-7 нет приоритетов | consistency | №09 |
| cardblock.base | да | minor | ambiguity | Повторная разблокировка ACTIVE-карты: БК-6 и код 409 расходятся | consistency | №09 |
| cardblock.paraphrase.keep_authorizations | да | minor | ambiguity | Момент окончания срока блокировки не определён: сутки или полночь | lens:risk | №08 |
| cardblock.paraphrase.keep_authorizations | да | minor | incomplete | Пункты БК-1…БК-7 не имеют приоритетов | consistency | №09 |
| cardblock.paraphrase.keep_authorizations | да | minor | incomplete | Ответ getCardStatus при бессрочной блокировке не описан | consistency | №09 |
| cardblock.paraphrase.keep_authorizations | да | minor | api_contract | blockCard: Content-Type application/json при пустом теле | lens:architect | №07 |
| cashback.base | да | minor | api_contract | Тело ответа 200 saveCategory отсылает к разделу без него | consistency | №09 |
| cashback.base | да | minor | terminology | Одни и те же понятия названы по-разному в разных местах | consistency | №09 |
| cashback.base | да | minor | incomplete | Срок выбора категории не проверяется и не имеет кода ответа | lens:architect | №07 |
| cashback.base | да | minor | incomplete | Возврат покупки вне категории или ниже 500 ₸ не определён | consistency | №09 |
| cashback.base | да | minor | incomplete | Требования не имеют приоритетов и идентификаторов в разделах | consistency | №09 |
| cashback.base | да | minor | ambiguity | Неясно, какую категорию показывать до вступления выбора в силу | consistency | №09 |
| cashback.paraphrase.rate | да | minor | incomplete | Возврат после зачисления без покупок в следующем месяце не описан | consistency | №09 |
| cashback.paraphrase.rate | да | minor | missing_element | Ответ 200 saveCategory отсылает к описанию, которого нет | consistency | №09 |
| cashback.paraphrase.rate | да | minor | ambiguity | Дата, по которой покупка относится к месяцу, не названа | consistency | №09 |
| cashback.paraphrase.rate | да | minor | terminology | Одни и те же понятия названы разными терминами | consistency | №09 |
| cashback.paraphrase.rate | да | minor | incomplete | saveCategory не проверяет срок выбора категории из КБ-1 | lens:architect | №07 |
| cashback.paraphrase.rate | да | minor | ambiguity | Категория текущего месяца после смены: действующая или выбранная | consistency | №09 |
| cashback.paraphrase.rate | да | minor | incomplete | Приоритеты требований не указаны | consistency | №09 |
| cashback.paraphrase.rate | да | minor | security | getCashback не описывает ответ на запрос чужой карты | lens:risk | №08 |
| transfer_limit.base | да | minor | other | Функциональные требования ЛП-1…ЛП-6 без приоритетов | consistency | №09 |
| transfer_limit.base | да | minor | ambiguity | ЛП-5 и ЛП-6 не определяют показанный до перевода лимит | consistency | №09 |
| transfer_limit.base | да | minor | api_contract | Тип поля limit: строка в ответе и целое число в запросе | consistency | №09 |
| transfer_limit.base | да | minor | terminology | Продукт и приложение названы разными именами | consistency | №09 |
| transfer_limit.paraphrase.new_limit | да | minor | incomplete | Остаток лимита не определён, если использовано больше нового лимита | consistency | №09 |
| transfer_limit.paraphrase.new_limit | да | minor | unit_mismatch | Тип лимита в ответе getTransferLimit и в запросе setTransferLimit различается | consistency | №09 |
| transfer_limit.paraphrase.new_limit | да | minor | terminology | Одни и те же понятия названы по-разному, глоссария нет | consistency | №09 |
| transfer_limit.paraphrase.new_limit | да | minor | incomplete | Функциональные требования ЛП-1…ЛП-6 не имеют приоритетов | consistency | №09 |
| autopay.combo.unit_change-limit_per_hour+drop_promised-no_409_status |  | minor | ambiguity | Неуспешная попытка пополнения не учтена в лимите трёх за час | consistency | №09 |
| autopay.combo.unit_change-limit_per_hour+drop_promised-no_409_status |  | minor | terminology | Одни понятия названы разными терминами: отключение, удаление, настройка | consistency | №09 |
| autopay.combo.unit_change-limit_per_hour+drop_promised-no_409_status |  | minor | incomplete | Не описано повторное создание настройки после удаления | consistency | №09 |
| autopay.combo.unit_change-limit_per_hour+drop_promised-no_409_status |  | minor | traceability | Нет ID у пунктов API и критериев, нет приоритетов у требований | consistency | №09 |
| autopay.combo.unit_change-limit_per_hour+drop_promised-no_409_status |  | major | api_contract | Тело успешного ответа createAutopay не описано, хотя ссылка есть | lens:architect | №07 |
| autopay.drop_promised.no_409_status |  | minor | incomplete | Счётчик суток при удалении и повторном создании не указан | consistency | №09 |
| autopay.drop_promised.no_409_status |  | minor | api_contract | Тело успешного ответа createAutopay не описано | lens:architect | №07 |
| autopay.drop_promised.no_409_status |  | minor | incomplete | Приоритеты и признак стабильности требований не указаны | consistency | №09 |
| autopay.drop_promised.no_409_status |  | minor | event_conflict | Не определено событие «пополнение» для лимита и срока | lens:analyst | №05 |
| autopay.drop_promised.no_409_status |  | minor | terminology | Термины «оператор связи» и «настройка» не едины, глоссария нет | consistency | №09 |
| autopay.event_conflict.insufficient_funds_credit |  | minor | contradiction | Цель о балансе без падения ниже порога не выполняется по правилам | consistency | №09 |
| autopay.event_conflict.insufficient_funds_credit |  | minor | terminology | Термины «настройка» и «уведомление о балансе» названы по-разному | consistency | №09 |
| autopay.event_conflict.insufficient_funds_credit |  | major | missing_element | Кредитное пополнение не хранит данных для списания долга | lens:architect | №07 |
| autopay.event_conflict.insufficient_funds_credit |  | major | ambiguity | Не определено, какое поступление на карту запускает списание кредита | lens:risk | №08 |
| autopay.event_conflict.insufficient_funds_credit |  | minor | other | Нет приоритетов у правил и ID у строк приёмки | consistency | №09 |
| autopay.range_boundary.trigger_at_threshold |  | minor | terminology | Одно понятие «настройка» названо тремя разными фразами | consistency | №09 |
| autopay.range_boundary.trigger_at_threshold |  | minor | other | Функциональные требования АП-1…АП-7 не имеют приоритета | consistency | №09 |
| autopay.range_boundary.trigger_at_threshold |  | minor | incomplete | Поведение лимита на стыке суток не описано | consistency | №09 |
| autopay.range_boundary.trigger_at_threshold |  | major | incomplete | Учёт отказанной по средствам попытки в лимите трёх не определён | consistency | №09 |
| autopay.two_statuses.range_422 |  | minor | terminology | Один компонент и одна настройка названы разными терминами | consistency | №09 |
| autopay.two_statuses.range_422 |  | minor | incomplete | Пункты требований и приоритеты не пронумерованы | consistency | №09 |
| autopay.two_statuses.range_422 |  | minor | incomplete | createAutopay: тело успешного ответа 200 не описано | lens:architect | №07 |
| autopay.two_statuses.range_422 |  | minor | infeasible | Цель «не опускается ниже порога» не соответствует правилам лимита | consistency | №09 |
| autopay.two_statuses.range_422 |  | minor | incomplete | После отключения не описаны повторное подключение и изменение | consistency | №09 |
| autopay.unit_change.limit_per_hour |  | major | event_conflict | Не определено, входят ли отказанные попытки в лимит АП-5 | lens:analyst, consistency | №05, №09 |
| autopay.unit_change.limit_per_hour |  | major | ambiguity | Карта для списания по уведомлению оператора не определена | lens:risk | №08 |
| autopay.unit_change.limit_per_hour |  | minor | incomplete | Счётчик и сброс при удалении и повторном создании настройки | consistency | №09 |
| autopay.unit_change.limit_per_hour |  | minor | terminology | Термины оператора и клиента называются по-разному | consistency | №09 |
| autopay.unit_change.limit_per_hour |  | minor | other | Приоритеты и ID требований не указаны | consistency | №09 |
| autopay.unit_change.limit_per_hour |  | major | missing_element | Валюта карты KZT из АП-1 не проверяется в логике метода | lens:architect | №07 |
| cardblock.combo.unit_change-blocked_at_utc+two_statuses-reblock_200 |  | minor | terminology | Одни понятия названы разными терминами без глоссария | consistency | №09 |
| cardblock.combo.unit_change-blocked_at_utc+two_statuses-reblock_200 |  | minor | incomplete | Функциональные требования БК-1…БК-7 без приоритетов | consistency | №09 |
| cardblock.combo.unit_change-blocked_at_utc+two_statuses-reblock_200 |  | minor | missing_element | Push-уведомление обещано, но канал и формат не описаны | consistency | №09 |
| cardblock.combo.unit_change-blocked_at_utc+two_statuses-reblock_200 |  | minor | incomplete | Срок блокировки: не определено, от какого момента он отсчитывается | lens:risk | №08 |
| cardblock.drop_promised.no_last_digits |  | minor | contradiction | Код 400 и код 409 при одном запросе: порядок не задан | consistency | №09 |
| cardblock.drop_promised.no_last_digits |  | minor | ambiguity | Срок блокировки в сутках: не задан момент его окончания | lens:risk, consistency | №08, №09 |
| cardblock.drop_promised.no_last_digits |  | minor | contradiction | Повторная разблокировка в ACTIVE: без ограничения или ошибка 409 | consistency | №09 |
| cardblock.drop_promised.no_last_digits |  | minor | incomplete | Досрочная разблокировка и прежний срок блокировки не описаны | consistency | №09 |
| cardblock.drop_promised.no_last_digits |  | minor | terminology | Одни понятия названы разными терминами: процессинг, приложение | consistency | №09 |
| cardblock.drop_promised.no_last_digits |  | minor | other | Приоритет функциональных требований БК-1…БК-7 не указан | consistency | №09 |
| cardblock.event_conflict.unblock_daily_limit |  | major | incomplete | Поле days в статусе для бессрочной блокировки не задано | consistency, lens:architect | №07, №09 |
| cardblock.event_conflict.unblock_daily_limit |  | minor | ambiguity | Момент «до блокировки» не привязан к ответу или вступлению в силу | lens:risk, consistency | №08, №09 |
| cardblock.event_conflict.unblock_daily_limit |  | minor | other | Функциональные требования БК-1…БК-8 без приоритетов | consistency | №09 |
| cardblock.event_conflict.unblock_daily_limit |  | major | incomplete | Отказ при повторной разблокировке за сутки без кода ответа | lens:architect | №07 |
| cardblock.range_boundary.days_400_at_30 |  | major | incomplete | Ответ getCardStatus для бессрочной блокировки не определён | consistency | №09 |
| cardblock.range_boundary.days_400_at_30 |  | minor | other | Функциональные требования БК-1…БК-7 без приоритетов | consistency | №09 |
| cardblock.range_boundary.days_400_at_30 |  | minor | terminology | Одна система названа «Мобильный банк» и «Приложение» | consistency | №09 |
| cardblock.two_statuses.reblock_200 |  | minor | contradiction | Цель «временно» не покрывает бессрочную блокировку | consistency | №09 |
| cardblock.two_statuses.reblock_200 |  | minor | incomplete | Приоритеты требований БК-1…БК-7 не указаны | consistency | №09 |
| cardblock.two_statuses.reblock_200 |  | minor | api_contract | Поле days в getCardStatus не описано для бессрочной блокировки | lens:architect | №07 |
| cardblock.two_statuses.reblock_200 |  | minor | terminology | Исполнитель блокировки назван по-разному: клиент и приложение | consistency | №09 |
| cardblock.unit_change.blocked_at_utc |  | minor | incomplete | Поле days для бессрочной блокировки в getCardStatus не определено | consistency | №09 |
| cardblock.unit_change.blocked_at_utc |  | minor | ambiguity | Авторизация в обработке во время блокировки: исход не описан | consistency | №09 |
| cardblock.unit_change.blocked_at_utc |  | minor | incomplete | Приоритеты и важность пунктов БК-1…БК-7 не указаны | consistency | №09 |
| cardblock.unit_change.blocked_at_utc |  | minor | ambiguity | Момент начала блокировки: ответ 200 или вступление в силу | lens:risk | №08 |
| cashback.combo.event_conflict-category_effective_now+range_boundary-cap_strict |  | major | incomplete | Не задано начисление за покупки в месяце без выбранной категории | consistency | №09 |
| cashback.combo.event_conflict-category_effective_now+range_boundary-cap_strict |  | minor | ambiguity | Месяц покупки: по времени операции или времени передачи | consistency | №09 |
| cashback.combo.event_conflict-category_effective_now+range_boundary-cap_strict |  | minor | incomplete | Приоритеты требований не заданы, порядок реализации не определён | consistency | №09 |
| cashback.combo.event_conflict-category_effective_now+range_boundary-cap_strict |  | minor | terminology | Одни и те же понятия названы в документе разными терминами | consistency | №09 |
| cashback.combo.event_conflict-category_effective_now+range_boundary-cap_strict |  | major | missing_element | Возвраты покупок не описаны как данные и события для КБ-6 | lens:architect | №07 |
| cashback.combo.event_conflict-category_effective_now+range_boundary-cap_strict |  | major | api_contract | Ответ 200 saveCategory: тело отсылает к разделу без описания | consistency | №09 |
| cashback.combo.event_conflict-category_effective_now+range_boundary-cap_strict |  | minor | ambiguity | Возврат ниже порога 500 ₸: порядок проверок КБ-6 и КБ-2 не задан | consistency | №09 |
| cashback.combo.event_conflict-category_effective_now+range_boundary-cap_strict |  | minor | duplicate | Ставка 5 % записана в двух правилах: КБ-3 и КБ-6 | consistency | №09 |
| cashback.drop_promised.no_read_method |  | major | ambiguity | Экран: «выбранная категория» — новая или действующая в месяце | consistency | №09 |
| cashback.drop_promised.no_read_method |  | minor | terminology | Один объект назван «Мобильный банк» и «Приложение» | consistency | №09 |
| cashback.drop_promised.no_read_method |  | minor | ambiguity | Граница месяца: момент отнесения покупки к месяцу не задан | consistency | №09 |
| cashback.drop_promised.no_read_method |  | minor | other | Приоритеты и важность функциональных требований не указаны | consistency | №09 |
| cashback.drop_promised.no_read_method |  | major | incomplete | Проверка срока выбора категории не отражена в saveCategory | lens:architect | №07 |
| cashback.event_conflict.category_effective_now |  | minor | terminology | Выбор и сохранение категории называются разными словами | consistency | №09 |
| cashback.event_conflict.category_effective_now |  | minor | traceability | Пункты документа без ID и приоритетов | consistency | №09 |
| cashback.event_conflict.category_effective_now |  | major | missing_element | Данные для КБ-6 не содержат признака зачисления и связи возврата | lens:architect | №07 |
| cashback.event_conflict.category_effective_now |  | major | incomplete | Возврат после зачисления без следующего зачисления не описан | consistency | №09 |
| cashback.range_boundary.cap_strict |  | major | ambiguity | Категория в ответе getCashback не привязана к периоду смены | consistency | №09 |
| cashback.range_boundary.cap_strict |  | minor | incomplete | Приоритеты требований КБ и НФ не заданы | consistency | №09 |
| cashback.range_boundary.cap_strict |  | minor | terminology | Терминология не едина: «Мобильный банк» и «Приложение», «кэшбэк месяца» | consistency | №09 |
| cashback.range_boundary.cap_strict |  | major | incomplete | КБ-6 не определяет возврат покупки ниже порога 500 ₸ | consistency | №09 |
| cashback.range_boundary.cap_strict |  | major | missing_element | Тело ответа 200 метода saveCategory обещано, но не описано | consistency | №09 |
| cashback.range_boundary.cap_strict |  | major | missing_element | Срок выбора категории КБ-1 не отражён в контракте saveCategory | lens:architect | №07 |
| cashback.two_statuses.bad_category_200 |  | minor | terminology | Одни понятия названы по-разному, глоссария нет | consistency | №09 |
| cashback.two_statuses.bad_category_200 |  | major | incomplete | Возврат после зачисления: отрицательный перенос не описан | consistency | №09 |
| cashback.two_statuses.bad_category_200 |  | major | incomplete | Срок выбора категории не проверяется методом saveCategory | lens:architect | №07 |
| cashback.two_statuses.bad_category_200 |  | minor | incomplete | Функциональные требования КБ-1…КБ-7 без приоритета | consistency | №09 |
| cashback.two_statuses.bad_category_200 |  | major | incomplete | Возврат покупки ниже порога 500 ₸: вычет не определён | consistency | №09 |
| cashback.two_statuses.bad_category_200 |  | major | ambiguity | Категория, показываемая после смены в середине месяца, не определена | consistency | №09 |
| cashback.unit_change.accrued_in_tiyn |  | minor | other | Функциональные требования КБ-1…КБ-7 без приоритета | consistency | №09 |
| cashback.unit_change.accrued_in_tiyn |  | major | missing_element | Тело ответа 200 saveCategory отсылает к несуществующему разделу | consistency | №09 |
| cashback.unit_change.accrued_in_tiyn |  | minor | terminology | Одни понятия названы по-разному: категория, кэшбэк месяца, карта | consistency | №09 |
| cashback.unit_change.accrued_in_tiyn |  | major | ambiguity | Ответ getCashback: категория текущего или следующего месяца | consistency | №09 |
| cashback.unit_change.accrued_in_tiyn |  | minor | ambiguity | Граничная покупка на стыке месяцев: момент отнесения не задан | consistency | №09 |
| cashback.unit_change.accrued_in_tiyn |  | major | missing_element | getCashback не описывает коды ошибок 401, 404 и 500 | consistency | №09 |
| cashback.unit_change.accrued_in_tiyn |  | major | incomplete | Выбор категории после конца месяца не описан в saveCategory | lens:architect | №07 |
| transfer_limit.combo.two_statuses-range_200_error+drop_promised-no_read_method |  | major | contradiction | Лимит задан по номеру телефона, но запрос и данные его не содержат | lens:architect | №07 |
| transfer_limit.combo.two_statuses-range_200_error+drop_promised-no_read_method |  | minor | terminology | Одна величина названа «Использовано» и «использованная сумма» | consistency | №09 |
| transfer_limit.combo.two_statuses-range_200_error+drop_promised-no_read_method |  | minor | incomplete | У функциональных требований ЛП-1…ЛП-6 нет приоритетов | consistency | №09 |
| transfer_limit.drop_promised.no_read_method |  | minor | terminology | Один объект назван разными терминами; глоссария нет | consistency | №09 |
| transfer_limit.drop_promised.no_read_method |  | major | incomplete | Область лимита по номеру телефона не отражена в контракте | lens:architect | №07 |
| transfer_limit.drop_promised.no_read_method |  | major | incomplete | Параллельные переводы не покрыты правилом учёта суммы | consistency | №09 |
| transfer_limit.drop_promised.no_read_method |  | minor | other | Функциональные требования ЛП-1…ЛП-6 без приоритета | consistency | №09 |
| transfer_limit.event_conflict.cancel_no_restore |  | minor | terminology | Понятия «Остаток лимита» и «Использованная сумма» названы по-разному | consistency | №09 |
| transfer_limit.event_conflict.cancel_no_restore |  | minor | incomplete | Отмена перевода не покрыта критериями приёмки | consistency | №09 |
| transfer_limit.event_conflict.cancel_no_restore |  | minor | incomplete | Требования ЛП-1…ЛП-7 не имеют приоритета | consistency | №09 |
| transfer_limit.range_boundary.reaching_rejects |  | minor | missing_element | Приоритеты требований и признаки важности не указаны | consistency | №09 |
| transfer_limit.range_boundary.reaching_rejects |  | minor | terminology | Одни и те же понятия названы разными терминами в документе | consistency | №09 |
| transfer_limit.range_boundary.reaching_rejects |  | major | ambiguity | Показ лимита сразу после его изменения не определён | consistency | №09 |
| transfer_limit.range_boundary.reaching_rejects |  | major | api_contract | Тип лимита в ответе string, в запросе integer | consistency | №09 |
| transfer_limit.two_statuses.range_200_error |  | minor | other | Функциональные требования ЛП-1…ЛП-6 без приоритетов | consistency | №09 |
| transfer_limit.two_statuses.range_200_error |  | minor | terminology | Термин «остаток лимита» назван по-разному в разделах | consistency | №09 |
| transfer_limit.unit_change.api_limit_in_tiyn |  | minor | incomplete | В документе не указаны приоритеты требований | consistency | №09 |
| transfer_limit.unit_change.api_limit_in_tiyn |  | minor | incomplete | Критерии приёмки не проверяют отмену перевода | consistency | №09 |
| transfer_limit.unit_change.api_limit_in_tiyn |  | minor | terminology | Одни и те же понятия названы по-разному, глоссария нет | consistency | №09 |

Пропуски:

| Кейс | Тип дефекта | Близкая находка (не засчитана) | Владельцы |
| :--- | :--- | :--- | :--- |
| cardblock.combo.unit_change-blocked_at_utc+two_statuses-reblock_200 | status_conflict | — | №09, №07 |
| cardblock.drop_promised.no_last_digits | missing_element | — | №05, №12 |
| cardblock.two_statuses.reblock_200 | status_conflict | — | №09, №07 |

| Кейс | Ожидание | Статус | Замечаний (к/с/н) | Вердикт |
| :--- | :--- | :--- | :--- | :--- |
| autopay.base | clean | complete | 5 (0/0/5) | yes/yes |
| autopay.combo.unit_change-limit_per_hour+drop_promised-no_409_status | defects | complete | 7 (1/2/4) | no/no |
| autopay.drop_promised.no_409_status | defects | complete | 6 (0/1/5) | yes/yes |
| autopay.event_conflict.insufficient_funds_credit | defects | complete | 6 (1/2/3) | no/no |
| autopay.paraphrase.nfr | clean | complete | 5 (0/0/5) | yes/yes |
| autopay.range_boundary.trigger_at_threshold | defects | complete | 5 (1/1/3) | no/no |
| autopay.two_statuses.range_422 | defects | complete | 6 (0/1/5) | yes/yes |
| autopay.unit_change.limit_per_hour | defects | complete | 7 (1/3/3) | no/no |
| cardblock.base | clean | complete | 5 (0/0/5) | yes/yes |
| cardblock.combo.unit_change-blocked_at_utc+two_statuses-reblock_200 | defects | complete | 5 (0/1/4) | yes/yes |
| cardblock.drop_promised.no_last_digits | defects | complete | 6 (0/0/6) | yes/yes |
| cardblock.event_conflict.unblock_daily_limit | defects | complete | 5 (1/2/2) | no/no |
| cardblock.paraphrase.keep_authorizations | clean | complete | 4 (0/0/4) | yes/yes |
| cardblock.range_boundary.days_400_at_30 | defects | complete | 4 (1/1/2) | no/no |
| cardblock.two_statuses.reblock_200 | defects | complete | 4 (0/0/4) | yes/yes |
| cardblock.unit_change.blocked_at_utc | defects | complete | 5 (0/1/4) | yes/yes |
| cashback.base | clean | complete | 6 (0/0/6) | yes/yes |
| cashback.combo.event_conflict-category_effective_now+range_boundary-cap_strict | defects | complete | 10 (2/3/5) | no/no |
| cashback.drop_promised.no_read_method | defects | complete | 6 (1/2/3) | no/no |
| cashback.event_conflict.category_effective_now | defects | complete | 5 (1/2/2) | no/no |
| cashback.paraphrase.rate | clean | complete | 8 (0/0/8) | yes/yes |
| cashback.range_boundary.cap_strict | defects | complete | 7 (1/4/2) | no/no |
| cashback.two_statuses.bad_category_200 | defects | complete | 7 (1/4/2) | no/no |
| cashback.unit_change.accrued_in_tiyn | defects | complete | 8 (1/4/3) | no/no |
| edge.empty | clean | complete | 0 (0/0/0) | undetermined/undetermined |
| transfer_limit.base | clean | complete | 4 (0/0/4) | yes/yes |
| transfer_limit.combo.two_statuses-range_200_error+drop_promised-no_read_method | defects | complete | 5 (2/1/2) | no/no |
| transfer_limit.drop_promised.no_read_method | defects | complete | 5 (1/2/2) | no/no |
| transfer_limit.event_conflict.cancel_no_restore | defects | complete | 4 (1/0/3) | no/no |
| transfer_limit.paraphrase.new_limit | clean | complete | 4 (0/0/4) | yes/yes |
| transfer_limit.range_boundary.reaching_rejects | defects | complete | 5 (1/2/2) | no/no |
| transfer_limit.two_statuses.range_200_error | defects | complete | 3 (1/0/2) | no/no |
| transfer_limit.unit_change.api_limit_in_tiyn | defects | complete | 4 (1/0/3) | no/no |
