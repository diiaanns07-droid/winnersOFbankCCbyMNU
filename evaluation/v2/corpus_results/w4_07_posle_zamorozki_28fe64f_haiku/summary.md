# Корпус evaluation/dev — W4-07 после заморозки: 28fe64f, haiku

Кейсов 33 (не запускались 0), не измерено 0 (пропусков в счётчике 0).

| TP | FP | FN | Дубли | Precision | Recall | F1 |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 27 | 202 | 1 | 0 | 0.118 | 0.964 | 0.210 |

Чистые документы (8/8 измерено): замечаний 50, critical 0, major 4; документов с critical 0, с > 1 major 1, вердикт «нельзя» 0; документов с > 1 замечанием 8, максимум на одном 9. Ложных тревог по счётчику: 50.

Recall по типам: boundary_conflict 5/5, event_conflict 5/5, missing_element 6/6, status_conflict 5/6, unit_mismatch 6/6.

Время 62.5 мин суммарно, вызовов 244, $1.643.

Кандидаты этапов до судьи (верхняя граница): TP 28/28, recall 1.000; по типам: boundary_conflict 5/5, event_conflict 5/5, missing_element 6/6, status_conflict 6/6, unit_mismatch 6/6.

Вклад источников (замечание с несколькими источниками считается каждому):

| Источник | TP | FP | из них на чистых |
| :--- | ---: | ---: | ---: |
| consistency (№09) | 26 | 133 | 36 |
| lens:analyst (№05) | 12 | 4 | 1 |
| lens:architect (№07) | 16 | 32 | 8 |
| lens:qa (№06) | 18 | 33 | 8 |
| lens:risk (№08) | 7 | 14 | 1 |
| rules (№12) | 26 | 0 | 0 |

Ложные находки:

| Кейс | Чистый | Серьёзность | Тип | Замечание | Источники | Владельцы |
| :--- | :---: | :--- | :--- | :--- | :--- | :--- |
| autopay.base | да | minor | terminology | Одни и те же понятия названы по-разному, глоссария не задан | consistency | №09 |
| autopay.base | да | minor | ambiguity | АП-5 и АП-6: неясно, входит ли отклонённая попытка в лимит трёх | lens:risk | №08 |
| autopay.base | да | minor | incomplete | Функциональные требования АП-1…АП-7 и НФ-1 не имеют приоритетов | consistency | №09 |
| autopay.base | да | minor | missing_element | Критерии приёмки покрывают малую часть функциональных требований | lens:qa | №06 |
| autopay.base | да | minor | contradiction | Цель «не опускается ниже порога» не согласуется с лимитом и НФ-1 | consistency | №09 |
| autopay.base | да | minor | incomplete | Сброс суточного счётчика при пересоздании настройки не описан | consistency | №09 |
| autopay.paraphrase.nfr | да | minor | incomplete | Критерии приёмки не покрывают границы, ошибки и повторы | lens:qa | №06 |
| autopay.paraphrase.nfr | да | minor | ambiguity | АП-1 и логика п. 3 расходятся по повторной настройке номера | consistency | №09 |
| autopay.paraphrase.nfr | да | minor | missing_element | Изменение порога и суммы настройки не описано | consistency | №09 |
| autopay.paraphrase.nfr | да | minor | missing_element | Пункты требований не имеют приоритетов | consistency | №09 |
| autopay.paraphrase.nfr | да | minor | ambiguity | Неудачная попытка не учтена: считается ли она в лимите АП-5 | consistency | №09 |
| autopay.paraphrase.nfr | да | minor | terminology | Одни понятия названы разными терминами, глоссария нет | consistency | №09 |
| cardblock.base | да | minor | api_contract | Пустое тело blockCard при Content-Type application/json не определено | lens:architect | №07 |
| cardblock.base | да | minor | other | Приоритеты функциональных требований БК-1…БК-7 не указаны | consistency | №09 |
| cardblock.base | да | minor | incomplete | Критерии приёмки не покрывают разблокировку, push и ошибки 400–409 | lens:qa | №06 |
| cardblock.base | да | major | event_conflict | Момент вступления блокировки не задан: исход авторизации в окне 10 с | lens:analyst, consistency | №05, №09 |
| cardblock.base | да | minor | terminology | Один объект назван по-разному: «Мобильный банк» и «Приложение» | consistency | №09 |
| cardblock.base | да | major | api_contract | Ответ getCardStatus для ACTIVE и бессрочной блокировки не задан | lens:architect, consistency | №07, №09 |
| cardblock.paraphrase.keep_authorizations | да | minor | missing_element | Функциональные требования БК-1…БК-7 не имеют приоритетов | consistency | №09 |
| cardblock.paraphrase.keep_authorizations | да | minor | incomplete | Критерии приёмки покрывают три из семи функциональных требований | lens:qa | №06 |
| cardblock.paraphrase.keep_authorizations | да | minor | contradiction | Цель «временно» не совпадает с бессрочной блокировкой | consistency | №09 |
| cardblock.paraphrase.keep_authorizations | да | minor | ambiguity | Поле days в ответе getCardStatus: исходный срок или остаток | lens:architect | №07 |
| cardblock.paraphrase.keep_authorizations | да | minor | ambiguity | Авторизация в окне до 10 секунд после блокировки не определена | consistency | №09 |
| cardblock.paraphrase.keep_authorizations | да | minor | incomplete | Ответ getCardStatus для бессрочной блокировки: значение days не задано | consistency | №09 |
| cashback.base | да | minor | ambiguity | Возврат в день зачисления 5-го числа: порядок с зачислением не задан | consistency | №09 |
| cashback.base | да | minor | duplicate | Список кодов категории повторён в четырёх местах документа | consistency | №09 |
| cashback.base | да | minor | missing_element | Возврат после зачисления: нет данных для корректировки следующего зачисления | lens:architect | №07 |
| cashback.base | да | minor | api_contract | saveCategory после конца месяца: отказ не описан, статус не определён | lens:architect | №07 |
| cashback.base | да | minor | terminology | Термины не едины: кэшбэк месяца, приложение, клиент названы по-разному | consistency | №09 |
| cashback.base | да | minor | missing_element | Критерии приёмки не покрывают порог, возвраты, даты, ошибки | lens:qa | №06 |
| cashback.base | да | minor | other | Функциональные требования КБ-1…КБ-7 не имеют приоритетов | consistency | №09 |
| cashback.base | да | minor | missing_element | Статус 200 saveCategory отсылает к описанию, которого нет | consistency | №09 |
| cashback.base | да | major | ambiguity | getCashback: непонятно, какая категория показывается в месяце смены выбора | lens:architect, consistency | №07, №09 |
| cashback.paraphrase.rate | да | minor | incomplete | Критерии приёмки покрывают 4 из 7 функциональных требований | lens:qa | №06 |
| cashback.paraphrase.rate | да | minor | other | Требования не имеют приоритетов и идентификаторов | consistency | №09 |
| cashback.paraphrase.rate | да | minor | ambiguity | Возврат в день зачисления кэшбэка: до или после начисления | consistency | №09 |
| cashback.paraphrase.rate | да | minor | incomplete | Сохранение категории после конца месяца не имеет проверки и кода | lens:architect | №07 |
| cashback.paraphrase.rate | да | minor | incomplete | Повторный выбор категории в том же месяце не описан | consistency | №09 |
| cashback.paraphrase.rate | да | minor | ambiguity | Категория в месяце выбора: прежняя или новая для показа | consistency | №09 |
| cashback.paraphrase.rate | да | major | missing_element | Ответ 200 saveCategory обещан разделом метода, но не описан | lens:architect, consistency | №07, №09 |
| cashback.paraphrase.rate | да | minor | terminology | Одни и те же понятия названы в документе по-разному | consistency | №09 |
| transfer_limit.base | да | minor | ambiguity | После смены лимита неясно, какой лимит показывать | consistency | №09 |
| transfer_limit.base | да | minor | incomplete | Критерии приёмки покрывают 3 из 5 функциональных требований | lens:qa | №06 |
| transfer_limit.base | да | minor | terminology | Одна величина названа тремя разными терминами | consistency | №09 |
| transfer_limit.base | да | minor | api_contract | Тип лимита: строка в ответе и целое число в запросе | consistency | №09 |
| transfer_limit.base | да | minor | other | Приоритеты функциональных требований ЛП-1…ЛП-6 не указаны | consistency | №09 |
| transfer_limit.paraphrase.new_limit | да | minor | other | ЛП-1…ЛП-6 не имеют приоритета и признака важности | consistency | №09 |
| transfer_limit.paraphrase.new_limit | да | minor | incomplete | Критерии приёмки покрывают три из шести функциональных требований | lens:qa | №06 |
| transfer_limit.paraphrase.new_limit | да | minor | ambiguity | Тип limit в GET-ответе и PUT-запросе расходится | consistency | №09 |
| transfer_limit.paraphrase.new_limit | да | minor | terminology | Одни понятия названы разными терминами по всему документу | consistency | №09 |
| autopay.combo.unit_change-limit_per_hour+drop_promised-no_409_status |  | major | incomplete | Проверка валюты карты KZT отсутствует в логике createAutopay | lens:architect | №07 |
| autopay.combo.unit_change-limit_per_hour+drop_promised-no_409_status |  | minor | incomplete | Критерии приёмки покрывают малую часть требований | lens:qa | №06 |
| autopay.combo.unit_change-limit_per_hour+drop_promised-no_409_status |  | major | ambiguity | Повтор события после отказа по нехватке средств не определён | consistency | №09 |
| autopay.combo.unit_change-limit_per_hour+drop_promised-no_409_status |  | minor | contradiction | Цель обещает неснижение баланса, которое требования не гарантируют | consistency | №09 |
| autopay.combo.unit_change-limit_per_hour+drop_promised-no_409_status |  | minor | other | Функциональные и нефункциональные требования без приоритета | consistency | №09 |
| autopay.combo.unit_change-limit_per_hour+drop_promised-no_409_status |  | minor | incomplete | Изменение порога или суммы настройки не описано | consistency | №09 |
| autopay.combo.unit_change-limit_per_hour+drop_promised-no_409_status |  | minor | terminology | Одни и те же понятия названы разными словами | consistency | №09 |
| autopay.drop_promised.no_409_status |  | minor | missing_element | Проверка карты KZT из АП-1 отсутствует в логике createAutopay | lens:architect | №07 |
| autopay.drop_promised.no_409_status |  | minor | terminology | Один и тот же объект назван разными терминами; глоссария нет | consistency | №09 |
| autopay.drop_promised.no_409_status |  | minor | ambiguity | Учёт отказанных по нехватке средств попыток в лимит трёх неясен | consistency | №09 |
| autopay.drop_promised.no_409_status |  | minor | traceability | Требования и пункты документа без ID и приоритетов | consistency | №09 |
| autopay.drop_promised.no_409_status |  | minor | incomplete | Критерии приёмки покрывают не все функциональные требования | lens:qa | №06 |
| autopay.drop_promised.no_409_status |  | minor | contradiction | Цель обещает порог без исключений, которые допускают правила | consistency | №09 |
| autopay.event_conflict.insufficient_funds_credit |  | minor | other | Приоритеты требований АП-1…АП-8 и НФ-1 не указаны | consistency | №09 |
| autopay.event_conflict.insufficient_funds_credit |  | major | missing_element | Тело успешного ответа createAutopay не описано, хотя таблица ссылается | lens:architect | №07 |
| autopay.event_conflict.insufficient_funds_credit |  | minor | terminology | Одни понятия названы разными терминами, глоссария нет | consistency | №09 |
| autopay.event_conflict.insufficient_funds_credit |  | minor | ambiguity | Не определено, к какому времени относить лимит: уведомление или пополнение | lens:risk | №08 |
| autopay.event_conflict.insufficient_funds_credit |  | minor | contradiction | Цель «баланс не ниже порога» расходится с правилами АП-6, АП-5 | consistency | №09 |
| autopay.event_conflict.insufficient_funds_credit |  | major | missing_element | АП-8: долг по кредитному пополнению не входит в перечень данных | lens:architect | №07 |
| autopay.event_conflict.insufficient_funds_credit |  | major | incomplete | Лимит трёх пополнений в сутки: счётчик по номеру или карте | consistency | №09 |
| autopay.event_conflict.insufficient_funds_credit |  | major | incomplete | Проверка карты в KZT из АП-1 отсутствует в логике createAutopay | lens:architect | №07 |
| autopay.event_conflict.insufficient_funds_credit |  | minor | missing_element | Приёмка проверяет 3 из 9 функциональных требований, границы не покрыты | lens:qa | №06 |
| autopay.range_boundary.trigger_at_threshold |  | major | api_contract | Тело успешного ответа createAutopay не описано, хотя таблица отсылает к методу | lens:architect | №07 |
| autopay.range_boundary.trigger_at_threshold |  | minor | incomplete | Пункты требований без ID и приоритетов | consistency | №09 |
| autopay.range_boundary.trigger_at_threshold |  | minor | missing_element | Критерии приёмки покрывают малую часть требований и кодов | lens:qa | №06 |
| autopay.range_boundary.trigger_at_threshold |  | minor | contradiction | Цель «баланс не ниже порога» не достижима по АП-5 и АП-6 | consistency | №09 |
| autopay.range_boundary.trigger_at_threshold |  | minor | terminology | Одна и та же сущность названа разными терминами, глоссария нет | consistency | №09 |
| autopay.range_boundary.trigger_at_threshold |  | minor | incomplete | Изменение порога и судьба счётчика за сутки не описаны | consistency | №09 |
| autopay.two_statuses.range_422 |  | minor | incomplete | Счётчик пополнений при удалении и повторном создании не описан | consistency | №09 |
| autopay.two_statuses.range_422 |  | minor | contradiction | Цель о неизменном балансе расходится с лимитом и отказами | consistency | №09 |
| autopay.two_statuses.range_422 |  | minor | terminology | Одни и те же понятия названы в документе разными терминами | consistency | №09 |
| autopay.two_statuses.range_422 |  | minor | incomplete | Проверка валюты карты KZT не описана в логике createAutopay | lens:architect | №07 |
| autopay.two_statuses.range_422 |  | minor | incomplete | Критерии приёмки покрывают 2 из 8 функциональных требований | lens:qa | №06 |
| autopay.two_statuses.range_422 |  | minor | other | Требования не имеют приоритетов | consistency | №09 |
| autopay.two_statuses.range_422 |  | minor | ambiguity | Отказ при нехватке средств: засчитывается ли в лимит трёх пополнений | lens:risk | №08 |
| autopay.two_statuses.range_422 |  | minor | ambiguity | Недостаточно средств: не определено, учитываются ли холды карты | lens:risk | №08 |
| autopay.two_statuses.range_422 |  | minor | api_contract | Тело успешного ответа createAutopay не описано, хотя обещано | lens:architect | №07 |
| autopay.unit_change.limit_per_hour |  | minor | incomplete | Критерии приёмки покрывают три из одиннадцати функциональных требований | lens:qa | №06 |
| autopay.unit_change.limit_per_hour |  | minor | terminology | Одни и те же понятия названы по-разному, глоссария нет | consistency | №09 |
| autopay.unit_change.limit_per_hour |  | minor | missing_element | У пунктов требований нет ID и приоритетов | consistency | №09 |
| autopay.unit_change.limit_per_hour |  | minor | ambiguity | Не определено, может ли номер иметь настройки по нескольким картам | consistency | №09 |
| autopay.unit_change.limit_per_hour |  | major | missing_element | Проверка валюты карты KZT отсутствует в логике createAutopay | lens:architect | №07 |
| autopay.unit_change.limit_per_hour |  | minor | contradiction | Цель «не опускается ниже порога» не достигается правилами АП-5, АП-6 | consistency | №09 |
| autopay.unit_change.limit_per_hour |  | major | missing_element | Тело успешного ответа createAutopay не описано | consistency, lens:architect | №07, №09 |
| cardblock.combo.unit_change-blocked_at_utc+two_statuses-reblock_200 |  | minor | terminology | Один продукт назван «Мобильный банк» и «приложение» | consistency | №09 |
| cardblock.combo.unit_change-blocked_at_utc+two_statuses-reblock_200 |  | minor | incomplete | Таблица кодов 409 не отражает исключение для повторной блокировки | lens:analyst | №05 |
| cardblock.combo.unit_change-blocked_at_utc+two_statuses-reblock_200 |  | minor | incomplete | Критерии приёмки не покрывают разблокировку, ошибки и повторы | lens:qa | №06 |
| cardblock.combo.unit_change-blocked_at_utc+two_statuses-reblock_200 |  | minor | incomplete | Требования БК-1…БК-7 и критерии без приоритетов | consistency | №09 |
| cardblock.drop_promised.no_last_digits |  | minor | terminology | Одни понятия названы в документе разными терминами | consistency | №09 |
| cardblock.drop_promised.no_last_digits |  | minor | missing_element | Функциональные требования БК-1…БК-7 без приоритетов | consistency | №09 |
| cardblock.drop_promised.no_last_digits |  | major | ambiguity | Момент вступления блокировки не определён: авторизации в окне 10 с | lens:analyst, lens:risk, consistency | №05, №08, №09 |
| cardblock.drop_promised.no_last_digits |  | minor | incomplete | Значение days в getCardStatus для бессрочной блокировки не задано | lens:architect | №07 |
| cardblock.drop_promised.no_last_digits |  | minor | api_contract | Коды 400 и 409 для одного запроса без порядка проверок | consistency | №09 |
| cardblock.drop_promised.no_last_digits |  | minor | ambiguity | Срок блокировки в сутках не привязан к началу и концу отсчёта | lens:risk | №08 |
| cardblock.drop_promised.no_last_digits |  | minor | incomplete | Критерии приёмки покрывают три строки из семи требований | lens:qa | №06 |
| cardblock.event_conflict.unblock_daily_limit |  | minor | incomplete | Тело getCardStatus для статуса ACTIVE не описано | lens:architect | №07 |
| cardblock.event_conflict.unblock_daily_limit |  | minor | unverifiable | БК-5 не измерим: нет доли событий и нагрузки | lens:qa | №06 |
| cardblock.event_conflict.unblock_daily_limit |  | minor | missing_element | Критерии приёмки покрывают 3 из 7 функциональных требований | lens:qa | №06 |
| cardblock.event_conflict.unblock_daily_limit |  | minor | contradiction | Цель «временно» расходится с бессрочной блокировкой БК-2 | consistency | №09 |
| cardblock.event_conflict.unblock_daily_limit |  | major | incomplete | Поле days в getCardStatus не определено для бессрочной блокировки | lens:architect | №07 |
| cardblock.event_conflict.unblock_daily_limit |  | minor | other | Приоритеты требований БК-1…БК-8 не указаны | consistency | №09 |
| cardblock.event_conflict.unblock_daily_limit |  | minor | terminology | Продукт назван «Мобильный банк» и «Приложение» | consistency | №09 |
| cardblock.event_conflict.unblock_daily_limit |  | major | api_contract | Код отказа при второй разблокировке в сутки не задан | lens:architect, consistency | №07, №09 |
| cardblock.range_boundary.days_400_at_30 |  | minor | other | Нет ID у пунктов и приоритетов у требований БК | consistency | №09 |
| cardblock.range_boundary.days_400_at_30 |  | major | incomplete | Бессрочная блокировка: значение days в статусе не описано | consistency | №09 |
| cardblock.range_boundary.days_400_at_30 |  | minor | incomplete | Критерии приёмки покрывают не все функциональные требования | lens:qa | №06 |
| cardblock.range_boundary.days_400_at_30 |  | major | security | Право блокировки: клиент или владелец карты не определено | lens:risk | №08 |
| cardblock.range_boundary.days_400_at_30 |  | minor | terminology | Одно понятие назван тремя разными терминами в документе | consistency | №09 |
| cardblock.two_statuses.reblock_200 |  | minor | contradiction | Цель «временно» не совпадает с бессрочной блокировкой | consistency | №09 |
| cardblock.two_statuses.reblock_200 |  | minor | incomplete | Механизм истечения срока блокировки не описан | consistency | №09 |
| cardblock.two_statuses.reblock_200 |  | minor | traceability | Нет ID у требований и приоритетов в документе | consistency | №09 |
| cardblock.two_statuses.reblock_200 |  | minor | incomplete | Критерии приёмки покрывают 4 из 8 требований | lens:qa | №06 |
| cardblock.two_statuses.reblock_200 |  | minor | incomplete | Поле days в getCardStatus для бессрочной блокировки не задано | lens:architect, consistency | №07, №09 |
| cardblock.unit_change.blocked_at_utc |  | minor | terminology | Один канал назван разными терминами, глоссария нет | consistency | №09 |
| cardblock.unit_change.blocked_at_utc |  | minor | missing_element | Приоритеты функциональных требований БК-1…БК-7 не указаны | consistency | №09 |
| cardblock.unit_change.blocked_at_utc |  | minor | missing_element | Критерии приёмки покрывают 4 из 7 функциональных требований | lens:qa | №06 |
| cardblock.unit_change.blocked_at_utc |  | major | incomplete | Поле days в getCardStatus не описано для бессрочной блокировки | lens:architect, consistency | №07, №09 |
| cardblock.unit_change.blocked_at_utc |  | minor | contradiction | Цель «временно» не покрывает бессрочную блокировку (БК-2) | consistency | №09 |
| cashback.combo.event_conflict-category_effective_now+range_boundary-cap_strict |  | minor | ambiguity | Порядок проверок 400 и 404 в saveCategory не задан | consistency | №09 |
| cashback.combo.event_conflict-category_effective_now+range_boundary-cap_strict |  | major | api_contract | Тело успешного ответа saveCategory не описано: ссылка на пустой раздел | consistency | №09 |
| cashback.combo.event_conflict-category_effective_now+range_boundary-cap_strict |  | minor | ambiguity | КБ-5 и КБ-6: возврат в день зачисления без определённого исхода | consistency | №09 |
| cashback.combo.event_conflict-category_effective_now+range_boundary-cap_strict |  | major | missing_element | Порядок ограничения кэшбэка сверх 10 000 ₸ не описан | lens:analyst | №05 |
| cashback.combo.event_conflict-category_effective_now+range_boundary-cap_strict |  | minor | terminology | Терминология не единая: начисление, сумма кэшбэка, название продукта | consistency | №09 |
| cashback.combo.event_conflict-category_effective_now+range_boundary-cap_strict |  | major | security | Держатель дополнительной карты: «клиент» и «владелец карты» расходятся | lens:risk | №08 |
| cashback.combo.event_conflict-category_effective_now+range_boundary-cap_strict |  | major | missing_element | Выбор категории после конца месяца не проверяется в saveCategory | lens:architect | №07 |
| cashback.combo.event_conflict-category_effective_now+range_boundary-cap_strict |  | minor | missing_element | Приоритеты функциональных требований не заданы | consistency | №09 |
| cashback.combo.event_conflict-category_effective_now+range_boundary-cap_strict |  | minor | duplicate | Ставка 5 % повторена в КБ-3 и КБ-6 | consistency | №09 |
| cashback.combo.event_conflict-category_effective_now+range_boundary-cap_strict |  | minor | incomplete | Критерии приёмки покрывают 4 из 7 функциональных требований | lens:qa | №06 |
| cashback.drop_promised.no_read_method |  | major | ambiguity | КБ-1 и КБ-7 по-разному связывают показ категории в месяце смены | consistency | №09 |
| cashback.drop_promised.no_read_method |  | minor | contradiction | Цель про кэшбэк месяца неясно соотнесена с отложенным выбором | consistency | №09 |
| cashback.drop_promised.no_read_method |  | major | incomplete | КБ-6 не определяет удержание без следующего зачисления | consistency | №09 |
| cashback.drop_promised.no_read_method |  | minor | incomplete | Критерии приёмки не покрывают ошибки и часть правил | lens:qa | №06 |
| cashback.drop_promised.no_read_method |  | major | incomplete | Повторный выбор категории в одном месяце не описан | consistency | №09 |
| cashback.drop_promised.no_read_method |  | minor | missing_element | Приоритеты и признаки важности требований не указаны | consistency | №09 |
| cashback.drop_promised.no_read_method |  | minor | terminology | Термины «Кэшбэк месяца» и «Категория» названы по-разному | consistency | №09 |
| cashback.drop_promised.no_read_method |  | major | incomplete | Не описан ответ saveCategory на выбор категории после срока | lens:risk | №08 |
| cashback.event_conflict.category_effective_now |  | major | incomplete | Метод getCashback не описывает ошибки сессии, карты и сервиса | lens:architect | №07 |
| cashback.event_conflict.category_effective_now |  | major | contradiction | Возврат покупки вне категории уменьшает кэшбэк по КБ-6 | lens:risk | №08 |
| cashback.event_conflict.category_effective_now |  | minor | terminology | Одни понятия названы в документе разными терминами | consistency | №09 |
| cashback.event_conflict.category_effective_now |  | minor | incomplete | Критерии приёмки не покрывают пороги, возвраты и ошибки | lens:qa | №06 |
| cashback.event_conflict.category_effective_now |  | minor | ambiguity | Возврат в день зачисления: до или после зачисления неясно | consistency | №09 |
| cashback.event_conflict.category_effective_now |  | minor | other | Приоритеты требований не заданы ни для одного пункта | consistency | №09 |
| cashback.range_boundary.cap_strict |  | major | incomplete | Срок выбора категории не проверяется в saveCategory | lens:architect | №07 |
| cashback.range_boundary.cap_strict |  | major | ambiguity | Категория в getCashback: текущая или выбранная на следующий месяц | lens:architect, consistency | №07, №09 |
| cashback.range_boundary.cap_strict |  | major | missing_element | Данные для возврата покупки (КБ-6) не входят в хранимые данные | lens:architect | №07 |
| cashback.range_boundary.cap_strict |  | minor | terminology | Один и тот же объект назван в документе разными терминами | consistency | №09 |
| cashback.range_boundary.cap_strict |  | minor | other | Требования не имеют приоритетов и признака стабильности | consistency | №09 |
| cashback.range_boundary.cap_strict |  | major | missing_element | Тело ответа 200 saveCategory отсылает к несуществующему описанию | lens:architect, consistency | №07, №09 |
| cashback.range_boundary.cap_strict |  | minor | missing_element | Критерии приёмки покрывают не все функциональные требования | lens:qa | №06 |
| cashback.two_statuses.bad_category_200 |  | major | incomplete | Повторный выбор категории в том же месяце не описан | consistency | №09 |
| cashback.two_statuses.bad_category_200 |  | minor | ambiguity | Момент покупки для отнесения к месяцу не определён | consistency | №09 |
| cashback.two_statuses.bad_category_200 |  | minor | terminology | Термины «приложение», «продукт», «категория», «кэшбэк месяца» расходятся | consistency | №09 |
| cashback.two_statuses.bad_category_200 |  | minor | incomplete | Функциональные требования КБ-1…КБ-7 не имеют приоритета | consistency | №09 |
| cashback.two_statuses.bad_category_200 |  | major | missing_element | Тело успешного ответа saveCategory не описано | lens:architect | №07 |
| cashback.two_statuses.bad_category_200 |  | minor | incomplete | Критерии приёмки покрывают не все функциональные требования | lens:qa | №06 |
| cashback.two_statuses.bad_category_200 |  | major | ambiguity | Категория в текущем месяце после выбора: новая или действующая | consistency | №09 |
| cashback.unit_change.accrued_in_tiyn |  | major | incomplete | Поздний saveCategory после конца месяца: проверки и кода нет | lens:architect | №07 |
| cashback.unit_change.accrued_in_tiyn |  | major | incomplete | Возврат больше следующего зачисления: минус или перенос не описан | consistency | №09 |
| cashback.unit_change.accrued_in_tiyn |  | minor | other | Приоритеты требований КБ-1…КБ-7 и НФ-1 не указаны | consistency | №09 |
| cashback.unit_change.accrued_in_tiyn |  | major | incomplete | Повторный выбор категории в одном месяце не описан | consistency | №09 |
| cashback.unit_change.accrued_in_tiyn |  | minor | duplicate | Ставка 5 % повторена в КБ-3 и КБ-6 | consistency | №09 |
| cashback.unit_change.accrued_in_tiyn |  | major | ambiguity | Смена категории в середине месяца: что показывает приложение | consistency | №09 |
| cashback.unit_change.accrued_in_tiyn |  | major | missing_element | Ответ 200 saveCategory отсылает к описанию, которого нет | consistency | №09 |
| cashback.unit_change.accrued_in_tiyn |  | minor | terminology | Термины приложения, кэшбэка и карты названы по-разному | consistency | №09 |
| cashback.unit_change.accrued_in_tiyn |  | minor | missing_element | Критерии приёмки покрывают 2 из 5 функциональных требований | lens:qa | №06 |
| transfer_limit.combo.two_statuses-range_200_error+drop_promised-no_read_method |  | minor | terminology | Одни понятия названы разными терминами, глоссария нет | consistency | №09 |
| transfer_limit.combo.two_statuses-range_200_error+drop_promised-no_read_method |  | minor | incomplete | Функциональные требования ЛП-1…ЛП-6 без приоритета | consistency | №09 |
| transfer_limit.combo.two_statuses-range_200_error+drop_promised-no_read_method |  | minor | missing_element | Критерии приёмки не покрывают отмену, границы, авторизацию | lens:qa, consistency | №06, №09 |
| transfer_limit.combo.two_statuses-range_200_error+drop_promised-no_read_method |  | major | ambiguity | Не определено, какие переводы входят в учёт суточного лимита | lens:risk | №08 |
| transfer_limit.drop_promised.no_read_method |  | minor | incomplete | Приёмка не покрывает границы, отмену, остаток и коды ответа | lens:qa, consistency | №06, №09 |
| transfer_limit.drop_promised.no_read_method |  | minor | missing_element | Требования ЛП-1…ЛП-6 без приоритетов и обязательности | consistency | №09 |
| transfer_limit.drop_promised.no_read_method |  | minor | terminology | Одна величина названа «Использовано» и «использованная сумма» | consistency | №09 |
| transfer_limit.drop_promised.no_read_method |  | major | missing_element | Не определено, как система узнаёт об отмене перевода | lens:risk | №08 |
| transfer_limit.event_conflict.cancel_no_restore |  | minor | incomplete | Функциональные требования ЛП-1…ЛП-7 без приоритетов | consistency | №09 |
| transfer_limit.event_conflict.cancel_no_restore |  | major | incomplete | Понижение лимита ниже использованной суммы не определено | consistency | №09 |
| transfer_limit.event_conflict.cancel_no_restore |  | minor | terminology | Одна сумма называется «Использовано» и «использованная сумма» | consistency | №09 |
| transfer_limit.event_conflict.cancel_no_restore |  | minor | missing_element | Приёмка покрывает 3 из 7 функциональных требований | lens:qa | №06 |
| transfer_limit.range_boundary.reaching_rejects |  | minor | terminology | Терминология не едина, глоссария нет | consistency | №09 |
| transfer_limit.range_boundary.reaching_rejects |  | minor | other | Приоритет требований ЛП-1…ЛП-6 не указан | consistency | №09 |
| transfer_limit.range_boundary.reaching_rejects |  | major | ambiguity | Показ лимита после смены не определён до следующего перевода | consistency | №09 |
| transfer_limit.range_boundary.reaching_rejects |  | minor | missing_element | Критерии приёмки покрывают 2 из 6 функциональных требований | lens:qa | №06 |
| transfer_limit.two_statuses.range_200_error |  | minor | terminology | Одни и те же понятия названы в документе по-разному | consistency | №09 |
| transfer_limit.two_statuses.range_200_error |  | minor | other | Пункты документа без ID и приоритетов | consistency | №09 |
| transfer_limit.two_statuses.range_200_error |  | major | ambiguity | Показанный лимит после смены до следующего перевода не определён | consistency | №09 |
| transfer_limit.two_statuses.range_200_error |  | minor | incomplete | Критерии приёмки покрывают лишь 2 из 7 функциональных требований | lens:qa | №06 |
| transfer_limit.two_statuses.range_200_error |  | major | missing_element | Отмена перевода не описана: инициатор и событие не заданы | lens:risk | №08 |
| transfer_limit.unit_change.api_limit_in_tiyn |  | minor | incomplete | Параллельные переводы по одному номеру не покрыты правилом лимита | consistency | №09 |
| transfer_limit.unit_change.api_limit_in_tiyn |  | minor | incomplete | Критерии приёмки покрывают 2 из 4 функциональных требований | lens:qa | №06 |
| transfer_limit.unit_change.api_limit_in_tiyn |  | major | ambiguity | Что входит в «Использовано»: исходящие или все переводы | lens:risk | №08 |
| transfer_limit.unit_change.api_limit_in_tiyn |  | minor | other | Пункты требований и приёмки без ID и приоритетов | consistency | №09 |
| transfer_limit.unit_change.api_limit_in_tiyn |  | major | incomplete | После смены лимита не определено, какой лимит показывать | consistency | №09 |
| transfer_limit.unit_change.api_limit_in_tiyn |  | minor | terminology | Термин использованной суммы назван тремя разными способами | consistency | №09 |

Пропуски:

| Кейс | Тип дефекта | Близкая находка (не засчитана) | Владельцы |
| :--- | :--- | :--- | :--- |
| cardblock.combo.unit_change-blocked_at_utc+two_statuses-reblock_200 | status_conflict | — | №09, №07 |

| Кейс | Ожидание | Статус | Замечаний (к/с/н) | Вердикт |
| :--- | :--- | :--- | :--- | :--- |
| autopay.base | clean | complete | 6 (0/0/6) | yes/yes |
| autopay.combo.unit_change-limit_per_hour+drop_promised-no_409_status | defects | complete | 9 (1/3/5) | no/no |
| autopay.drop_promised.no_409_status | defects | complete | 7 (0/1/6) | yes/yes |
| autopay.event_conflict.insufficient_funds_credit | defects | complete | 10 (1/4/5) | no/no |
| autopay.paraphrase.nfr | clean | complete | 6 (0/0/6) | yes/yes |
| autopay.range_boundary.trigger_at_threshold | defects | complete | 7 (1/1/5) | no/no |
| autopay.two_statuses.range_422 | defects | complete | 10 (0/1/9) | yes/yes |
| autopay.unit_change.limit_per_hour | defects | complete | 8 (1/2/5) | no/no |
| cardblock.base | clean | complete | 6 (0/2/4) | yes/yes |
| cardblock.combo.unit_change-blocked_at_utc+two_statuses-reblock_200 | defects | complete | 5 (0/1/4) | yes/yes |
| cardblock.drop_promised.no_last_digits | defects | complete | 8 (0/1/7) | yes/yes |
| cardblock.event_conflict.unblock_daily_limit | defects | complete | 9 (1/2/6) | no/no |
| cardblock.paraphrase.keep_authorizations | clean | complete | 6 (0/0/6) | yes/yes |
| cardblock.range_boundary.days_400_at_30 | defects | complete | 6 (1/2/3) | no/no |
| cardblock.two_statuses.reblock_200 | defects | complete | 6 (0/1/5) | yes/yes |
| cardblock.unit_change.blocked_at_utc | defects | complete | 6 (0/2/4) | yes/yes |
| cashback.base | clean | complete | 9 (0/1/8) | yes/yes |
| cashback.combo.event_conflict-category_effective_now+range_boundary-cap_strict | defects | complete | 12 (1/5/6) | no/no |
| cashback.drop_promised.no_read_method | defects | complete | 9 (1/4/4) | no/yes |
| cashback.event_conflict.category_effective_now | defects | complete | 7 (1/2/4) | no/no |
| cashback.paraphrase.rate | clean | complete | 8 (0/1/7) | yes/yes |
| cashback.range_boundary.cap_strict | defects | complete | 8 (1/4/3) | no/no |
| cashback.two_statuses.bad_category_200 | defects | complete | 8 (1/3/4) | no/no |
| cashback.unit_change.accrued_in_tiyn | defects | complete | 10 (1/5/4) | no/no |
| edge.empty | clean | complete | 0 (0/0/0) | undetermined/undetermined |
| transfer_limit.base | clean | complete | 5 (0/0/5) | yes/yes |
| transfer_limit.combo.two_statuses-range_200_error+drop_promised-no_read_method | defects | complete | 6 (2/1/3) | no/no |
| transfer_limit.drop_promised.no_read_method | defects | complete | 5 (1/1/3) | no/no |
| transfer_limit.event_conflict.cancel_no_restore | defects | complete | 5 (1/1/3) | no/no |
| transfer_limit.paraphrase.new_limit | clean | complete | 4 (0/0/4) | yes/yes |
| transfer_limit.range_boundary.reaching_rejects | defects | complete | 5 (1/1/3) | no/no |
| transfer_limit.two_statuses.range_200_error | defects | complete | 6 (1/2/3) | no/no |
| transfer_limit.unit_change.api_limit_in_tiyn | defects | complete | 7 (1/2/4) | no/no |
