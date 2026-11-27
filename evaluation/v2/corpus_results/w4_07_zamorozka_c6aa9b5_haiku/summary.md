# Корпус evaluation/dev — W4-07 заморозка: c6aa9b5, haiku

Кейсов 33 (не запускались 0), не измерено 0 (пропусков в счётчике 0).

| TP | FP | FN | Дубли | Precision | Recall | F1 |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 27 | 192 | 1 | 0 | 0.123 | 0.964 | 0.219 |

Чистые документы (8/8 измерено): замечаний 58, critical 0, major 3; документов с critical 0, с > 1 major 0, вердикт «нельзя» 0; документов с > 1 замечанием 8, максимум на одном 9. Ложных тревог по счётчику: 58.

Recall по типам: boundary_conflict 5/5, event_conflict 5/5, missing_element 6/6, status_conflict 5/6, unit_mismatch 6/6.

Время 68.6 мин суммарно, вызовов 278, $1.813.

Кандидаты этапов до судьи (верхняя граница): TP 28/28, recall 1.000; по типам: boundary_conflict 5/5, event_conflict 5/5, missing_element 6/6, status_conflict 6/6, unit_mismatch 6/6.

Вклад источников (замечание с несколькими источниками считается каждому):

| Источник | TP | FP | из них на чистых |
| :--- | ---: | ---: | ---: |
| consistency (№09) | 26 | 132 | 41 |
| lens:analyst (№05) | 14 | 2 | 1 |
| lens:architect (№07) | 15 | 26 | 9 |
| lens:qa (№06) | 17 | 33 | 7 |
| lens:risk (№08) | 4 | 14 | 6 |
| rules (№12) | 26 | 1 | 0 |

Ложные находки:

| Кейс | Чистый | Серьёзность | Тип | Замечание | Источники | Владельцы |
| :--- | :---: | :--- | :--- | :--- | :--- | :--- |
| autopay.base | да | minor | api_contract | Успешный ответ createAutopay не описан, хотя обещан разделом метода | lens:architect | №07 |
| autopay.base | да | minor | terminology | Одни и те же понятия названы в документе по-разному, глоссария нет | consistency | №09 |
| autopay.base | да | minor | traceability | Требования без идентификаторов и приоритетов, трассировка неполна | consistency | №09 |
| autopay.base | да | minor | ambiguity | Не определено, засчитывается ли отклонённая попытка в лимит трёх пополнений | consistency | №09 |
| autopay.base | да | minor | incomplete | Критерии приёмки покрывают не все функциональные требования и границы | lens:qa | №06 |
| autopay.paraphrase.nfr | да | minor | ambiguity | Неясно, учитываются ли неуспешные попытки в лимит трёх пополнений | consistency | №09 |
| autopay.paraphrase.nfr | да | minor | incomplete | АП-1 требует карту KZT, но логика createAutopay эту проверку не делает | consistency, lens:architect | №07, №09 |
| autopay.paraphrase.nfr | да | minor | terminology | Один термин называется по-разному: уведомление, настройка, автопополнение | consistency | №09 |
| autopay.paraphrase.nfr | да | minor | incomplete | Приоритеты функциональных требований и НФ-1 не заданы | consistency | №09 |
| autopay.paraphrase.nfr | да | minor | incomplete | Критерии приёмки покрывают не все функциональные требования и границы | lens:qa | №06 |
| autopay.paraphrase.nfr | да | minor | incomplete | Изменение порога или суммы действующей настройки не описано | consistency | №09 |
| cardblock.base | да | minor | contradiction | Цель «временная блокировка» не покрывает бессрочную блокировку | consistency | №09 |
| cardblock.base | да | minor | terminology | Срок блокировки назван по-разному: «срок блокировки» и «days» | consistency | №09 |
| cardblock.base | да | minor | incomplete | Авторизация в окне до вступления блокировки не определена | consistency | №09 |
| cardblock.base | да | minor | ambiguity | Порядок проверок days и статуса при blockCard не задан | consistency | №09 |
| cardblock.base | да | minor | incomplete | Изменение срока действующей блокировки не описано | consistency | №09 |
| cardblock.base | да | minor | ambiguity | Момент окончания срока блокировки определён двумя способами | lens:risk | №08 |
| cardblock.base | да | minor | api_contract | Тело запроса blockCard для бессрочной блокировки не определено | lens:architect | №07 |
| cardblock.base | да | minor | incomplete | Поле days в getCardStatus не определено для бессрочной блокировки | lens:architect | №07 |
| cardblock.base | да | minor | other | Приоритеты пунктов БК-1…БК-7 не указаны | consistency | №09 |
| cardblock.paraphrase.keep_authorizations | да | minor | incomplete | Судьба клиринга одобренной до блокировки авторизации не описана | lens:risk | №08 |
| cardblock.paraphrase.keep_authorizations | да | minor | contradiction | Цель «временно» расходится с бессрочной блокировкой | consistency | №09 |
| cardblock.paraphrase.keep_authorizations | да | minor | contradiction | Порядок проверок срока и статуса в blockCard не задан | consistency | №09 |
| cardblock.paraphrase.keep_authorizations | да | minor | ambiguity | Момент начала отсчёта срока блокировки не задан | lens:risk | №08 |
| cardblock.paraphrase.keep_authorizations | да | minor | terminology | Одни и те же понятия названы разными терминами, глоссария нет | consistency | №09 |
| cardblock.paraphrase.keep_authorizations | да | minor | incomplete | Авторизация, запрошенная до блокировки и одобренная после, не описана | consistency | №09 |
| cardblock.paraphrase.keep_authorizations | да | minor | incomplete | Поле days в getCardStatus для бессрочной блокировки не задано | lens:architect, consistency | №07, №09 |
| cardblock.paraphrase.keep_authorizations | да | minor | incomplete | Приоритеты требований БК-1…БК-7 не указаны | consistency | №09 |
| cardblock.paraphrase.keep_authorizations | да | minor | incomplete | Критерии приёмки покрывают 4 из 7 требований, границ нет | lens:qa | №06 |
| cashback.base | да | minor | incomplete | Критерии приёмки покрывают не все функциональные требования | lens:qa | №06 |
| cashback.base | да | minor | incomplete | Возврат после зачисления при нулевом следующем зачислении не определён | consistency | №09 |
| cashback.base | да | minor | incomplete | Не описано начисление, если категория не выбрана до конца месяца | consistency | №09 |
| cashback.base | да | minor | missing_element | Требования не имеют приоритетов и идентификаторов | consistency | №09 |
| cashback.base | да | minor | terminology | Одни понятия названы разными терминами, глоссария нет | consistency | №09 |
| cashback.base | да | minor | missing_element | Тело успешного ответа saveCategory нигде не описано | lens:architect | №07 |
| cashback.base | да | minor | ambiguity | Категория в ответе getCashback в середине месяца не определена | consistency | №09 |
| cashback.base | да | minor | duplicate | Ставка 5 % повторена в КБ-3 и КБ-6 | consistency | №09 |
| cashback.paraphrase.rate | да | minor | missing_element | Успешный ответ saveCategory сослан на отсутствующее описание | consistency | №09 |
| cashback.paraphrase.rate | да | minor | missing_element | Метод getCashback не описывает ответы 401 и 404 | consistency | №09 |
| cashback.paraphrase.rate | да | major | contradiction | Возврат покупки ниже 500 ₸ даёт неопределённое уменьшение кэшбэка | lens:analyst, consistency | №05, №09 |
| cashback.paraphrase.rate | да | minor | incomplete | Приоритеты требований КБ-1…КБ-7 не указаны | consistency | №09 |
| cashback.paraphrase.rate | да | minor | ambiguity | Категория в ответе getCashback: сохранённая или действующая | consistency | №09 |
| cashback.paraphrase.rate | да | minor | missing_element | Срок выбора категории не проверяется в методе saveCategory | lens:architect | №07 |
| cashback.paraphrase.rate | да | minor | incomplete | Критерии приёмки покрывают 3 из 7 функциональных требований | lens:qa | №06 |
| cashback.paraphrase.rate | да | minor | terminology | Сумма кэшбэка месяца названа по-разному: тиыны, тенге, accrued | consistency | №09 |
| transfer_limit.base | да | minor | terminology | «Использовано» и «использованная сумма» — разные названия одного понятия | consistency | №09 |
| transfer_limit.base | да | minor | contradiction | Ключ учёта лимита: номер телефона или клиент | lens:architect | №07 |
| transfer_limit.base | да | minor | api_contract | Поле limit: строка в ответе и целое в запросе | consistency | №09 |
| transfer_limit.base | да | minor | other | Не у всех требований есть ID и приоритет | consistency | №09 |
| transfer_limit.base | да | minor | incomplete | Приёмка покрывает не все требования: границы, отмена, ошибки | lens:qa, consistency | №06, №09 |
| transfer_limit.base | да | major | ambiguity | Отмена перевода прошлых суток не меняет видимый лимит | lens:risk, consistency | №08, №09 |
| transfer_limit.base | да | minor | ops_risk | Повтор события отмены может уменьшить сумму дважды | lens:risk | №08 |
| transfer_limit.paraphrase.new_limit | да | minor | ambiguity | Входящие переводы в «Использовано» учитываются неоднозначно | lens:risk | №08 |
| transfer_limit.paraphrase.new_limit | да | minor | incomplete | Остаток лимита при снижении ниже использованной суммы не определён | consistency | №09 |
| transfer_limit.paraphrase.new_limit | да | minor | incomplete | Приоритеты требований и нумерация не указаны в документе | consistency | №09 |
| transfer_limit.paraphrase.new_limit | да | major | api_contract | Поле limit: string в ответе GET и integer в запросе PUT | lens:architect, consistency | №07, №09 |
| transfer_limit.paraphrase.new_limit | да | minor | terminology | Одна величина названа «Использовано», «использованная сумма», «used» | consistency | №09 |
| transfer_limit.paraphrase.new_limit | да | minor | missing_element | Приёмка покрывает 3 из 6 функциональных требований | lens:qa | №06 |
| autopay.combo.unit_change-limit_per_hour+drop_promised-no_409_status |  | minor | incomplete | Критерии приёмки покрывают малую часть требований | lens:qa | №06 |
| autopay.combo.unit_change-limit_per_hour+drop_promised-no_409_status |  | minor | incomplete | Не описано повторное подключение после удаления настройки | consistency | №09 |
| autopay.combo.unit_change-limit_per_hour+drop_promised-no_409_status |  | major | security | Номер телефона не привязан к клиенту: деньги уходят на чужой номер | lens:risk | №08 |
| autopay.combo.unit_change-limit_per_hour+drop_promised-no_409_status |  | minor | contradiction | Цель о неснижении баланса не совпадает с отказом по АП-6 | consistency | №09 |
| autopay.combo.unit_change-limit_per_hour+drop_promised-no_409_status |  | minor | terminology | Один объект называется разными терминами, глоссария нет | consistency | №09 |
| autopay.combo.unit_change-limit_per_hour+drop_promised-no_409_status |  | major | incomplete | Условие карты KZT из АП-1 не проверяется в createAutopay | lens:architect | №07 |
| autopay.combo.unit_change-limit_per_hour+drop_promised-no_409_status |  | minor | incomplete | Приоритеты требований в документе не указаны | consistency | №09 |
| autopay.combo.unit_change-limit_per_hour+drop_promised-no_409_status |  | major | incomplete | АП-4 пополняет после отключения, которое запрещает АП-7 | consistency | №09 |
| autopay.combo.unit_change-limit_per_hour+drop_promised-no_409_status |  | major | incomplete | Критерий приёмки 3 не выводится из правил без времени пополнений | lens:qa | №06 |
| autopay.combo.unit_change-limit_per_hour+drop_promised-no_409_status |  | major | incomplete | Тело успешного ответа createAutopay не описано | lens:architect | №07 |
| autopay.drop_promised.no_409_status |  | minor | incomplete | Повторное включение после отключения не описано, счётчик суток неясен | consistency | №09 |
| autopay.drop_promised.no_409_status |  | minor | incomplete | Критерии приёмки не покрывают границы, ошибки, отключение и повторы | lens:qa | №06 |
| autopay.drop_promised.no_409_status |  | minor | other | У требований АП-1.АП-7 и НФ-1 нет приоритетов | consistency | №09 |
| autopay.drop_promised.no_409_status |  | minor | contradiction | Цель об отсутствии падения баланса противоречит АП-5 и АП-6 | consistency | №09 |
| autopay.drop_promised.no_409_status |  | minor | ambiguity | Момент отнесения пополнения к суткам для лимита не назван | consistency | №09 |
| autopay.drop_promised.no_409_status |  | minor | terminology | Оператор связи и настройка названы разными терминами | consistency | №09 |
| autopay.drop_promised.no_409_status |  | minor | missing_element | Тело ответа 200 createAutopay обещано, но не описано | consistency | №09 |
| autopay.event_conflict.insufficient_funds_credit |  | minor | contradiction | Цель не выполняется при лимите и нехватке средств | consistency | №09 |
| autopay.event_conflict.insufficient_funds_credit |  | major | ambiguity | Неясно, можно ли подключить второй номер на одну карту | consistency | №09 |
| autopay.event_conflict.insufficient_funds_credit |  | minor | terminology | Одни понятия названы разными терминами, глоссария нет | consistency | №09 |
| autopay.event_conflict.insufficient_funds_credit |  | major | api_contract | Тело успешного ответа createAutopay не описано | lens:architect | №07 |
| autopay.event_conflict.insufficient_funds_credit |  | minor | incomplete | Приоритеты функциональных требований не указаны | consistency | №09 |
| autopay.event_conflict.insufficient_funds_credit |  | minor | missing_element | Критерии приёмки не покрывают границы, ошибки и повторы | lens:qa | №06 |
| autopay.range_boundary.trigger_at_threshold |  | minor | other | ID и приоритеты не заданы у большинства пунктов документа | consistency | №09 |
| autopay.range_boundary.trigger_at_threshold |  | major | missing_element | createAutopay: тело ответа 200 нигде не описано | lens:architect | №07 |
| autopay.range_boundary.trigger_at_threshold |  | minor | missing_element | Критерии приёмки покрывают малую часть требований | lens:qa | №06 |
| autopay.range_boundary.trigger_at_threshold |  | minor | terminology | Одни и те же понятия названы по-разному в разных разделах | consistency | №09 |
| autopay.range_boundary.trigger_at_threshold |  | minor | incomplete | Изменение порога или суммы настройки документом не описано | consistency | №09 |
| autopay.range_boundary.trigger_at_threshold |  | minor | contradiction | Цель баланса без порога противоречит лимиту трёх пополнений | consistency | №09 |
| autopay.two_statuses.range_422 |  | minor | missing_element | Критерии приёмки не покрывают повторы, отключение и ошибки | lens:qa | №06 |
| autopay.two_statuses.range_422 |  | minor | incomplete | Требования АП-1…АП-7 без приоритетов и признака обязательности | consistency | №09 |
| autopay.two_statuses.range_422 |  | minor | incomplete | Изменение порога или суммы активной настройки не описано | consistency | №09 |
| autopay.two_statuses.range_422 |  | minor | contradiction | Цель «не опускается ниже порога» несовместима с лимитом и отказом | consistency | №09 |
| autopay.two_statuses.range_422 |  | minor | terminology | Названия приложения и настройки в документе не едины | consistency | №09 |
| autopay.unit_change.limit_per_hour |  | minor | contradiction | Цель обещает неснижение баланса ниже порога, требования это допускают | consistency | №09 |
| autopay.unit_change.limit_per_hour |  | minor | incomplete | Функциональные требования АП-1–АП-7 не имеют приоритета | consistency | №09 |
| autopay.unit_change.limit_per_hour |  | minor | incomplete | Критерии приёмки покрывают три из одиннадцати функциональных требований | lens:qa | №06 |
| autopay.unit_change.limit_per_hour |  | major | incomplete | Логика createAutopay не проверяет валюту KZT карты из АП-1 | lens:architect | №07 |
| cardblock.combo.unit_change-blocked_at_utc+two_statuses-reblock_200 |  | minor | missing_element | Приёмка покрывает 4 из 7 функциональных требований | lens:qa | №06 |
| cardblock.combo.unit_change-blocked_at_utc+two_statuses-reblock_200 |  | minor | incomplete | Срок блокировки в ответе getCardStatus не задан для бессрочной | lens:architect | №07 |
| cardblock.combo.unit_change-blocked_at_utc+two_statuses-reblock_200 |  | minor | traceability | Строки приёмки, API и требования без ID и приоритетов | consistency | №09 |
| cardblock.combo.unit_change-blocked_at_utc+two_statuses-reblock_200 |  | minor | ambiguity | Повторная блокировка без days: «без изменений» не говорит о сроке | consistency | №09 |
| cardblock.combo.unit_change-blocked_at_utc+two_statuses-reblock_200 |  | minor | ambiguity | Строка 409 не исключает повторную блокировку из строки 92 | lens:qa, lens:architect, lens:risk, consistency, rules:api.same_case.200-409 | №06, №07, №08, №09, №12 |
| cardblock.drop_promised.no_last_digits |  | minor | terminology | Продукт и приложение названы разными терминами | consistency | №09 |
| cardblock.drop_promised.no_last_digits |  | minor | traceability | Пункты требований и критериев без ID и приоритетов | consistency | №09 |
| cardblock.drop_promised.no_last_digits |  | minor | missing_element | Продление и смена срока активной блокировки не описаны | consistency | №09 |
| cardblock.drop_promised.no_last_digits |  | minor | incomplete | Критерии приёмки покрывают не все функциональные требования | lens:qa | №06 |
| cardblock.drop_promised.no_last_digits |  | minor | contradiction | Цель «временно» не согласована с бессрочной блокировкой | consistency | №09 |
| cardblock.drop_promised.no_last_digits |  | major | ambiguity | Авторизации в 10-секундном окне до вступления блокировки не определены | lens:analyst, lens:risk, consistency | №05, №08, №09 |
| cardblock.event_conflict.unblock_daily_limit |  | minor | terminology | Для одного приложения использованы разные названия в разных разделах | consistency | №09 |
| cardblock.event_conflict.unblock_daily_limit |  | major | missing_element | Для лимита разблокировки не хранится время последней разблокировки | lens:architect | №07 |
| cardblock.event_conflict.unblock_daily_limit |  | minor | missing_element | Критерии приёмки покрывают только часть функциональных требований | lens:qa | №06 |
| cardblock.event_conflict.unblock_daily_limit |  | major | missing_element | Превышение лимита разблокировки по БК-8 не имеет кода ответа | lens:architect | №07 |
| cardblock.event_conflict.unblock_daily_limit |  | minor | other | Пункты API и приоритеты требований не имеют идентификаторов и приоритета | consistency | №09 |
| cardblock.range_boundary.days_400_at_30 |  | minor | incomplete | Критерии приёмки покрывают не все функциональные требования | lens:qa | №06 |
| cardblock.range_boundary.days_400_at_30 |  | minor | terminology | Одни понятия названы по-разному, глоссария нет | consistency | №09 |
| cardblock.range_boundary.days_400_at_30 |  | major | incomplete | Поле days для бессрочной блокировки в ответе не описано | consistency | №09 |
| cardblock.range_boundary.days_400_at_30 |  | minor | incomplete | Требования БК-1…БК-7 не имеют приоритета | consistency | №09 |
| cardblock.two_statuses.reblock_200 |  | minor | incomplete | Функциональные требования БК-1…БК-7 не имеют приоритетов | consistency | №09 |
| cardblock.two_statuses.reblock_200 |  | minor | terminology | Термин «статус карты» назван в документе по-разному | consistency | №09 |
| cardblock.two_statuses.reblock_200 |  | minor | incomplete | Критерии приёмки покрывают не все функциональные требования | lens:qa | №06 |
| cardblock.two_statuses.reblock_200 |  | major | ambiguity | Момент окончания срока блокировки не определён в документе | consistency | №09 |
| cardblock.unit_change.blocked_at_utc |  | minor | contradiction | Цель «временно» противоречит бессрочной блокировке БК-2 | consistency | №09 |
| cardblock.unit_change.blocked_at_utc |  | minor | incomplete | У функциональных требований БК-1…БК-7 нет приоритетов | consistency | №09 |
| cardblock.unit_change.blocked_at_utc |  | minor | terminology | Одни понятия названы по-разному: процессинг, приложение, Мобильный банк | consistency | №09 |
| cardblock.unit_change.blocked_at_utc |  | minor | missing_element | Критерии приёмки покрывают не все функциональные требования | lens:qa | №06 |
| cardblock.unit_change.blocked_at_utc |  | minor | incomplete | Поле days при бессрочной блокировке в getCardStatus не определено | consistency, lens:architect | №07, №09 |
| cardblock.unit_change.blocked_at_utc |  | minor | ambiguity | Момент окончания срока блокировки в сутках не определён | consistency | №09 |
| cashback.combo.event_conflict-category_effective_now+range_boundary-cap_strict |  | major | incomplete | Возврат больше следующего зачисления: итог не определён | consistency | №09 |
| cashback.combo.event_conflict-category_effective_now+range_boundary-cap_strict |  | minor | terminology | Одни понятия названы по-разному, глоссария нет | consistency | №09 |
| cashback.combo.event_conflict-category_effective_now+range_boundary-cap_strict |  | minor | missing_element | Критерии приёмки покрывают три из восьми требований | lens:qa | №06 |
| cashback.combo.event_conflict-category_effective_now+range_boundary-cap_strict |  | minor | other | Приоритеты и важность КБ-1…КБ-8 не указаны | consistency | №09 |
| cashback.combo.event_conflict-category_effective_now+range_boundary-cap_strict |  | minor | contradiction | Цель «одна категория в месяц» расходится с КБ-8 | consistency | №09 |
| cashback.combo.event_conflict-category_effective_now+range_boundary-cap_strict |  | major | incomplete | saveCategory не проверяет срок выбора КБ-1 и не имеет кода | lens:architect | №07 |
| cashback.drop_promised.no_read_method |  | minor | incomplete | В документе не указаны приоритеты требований КБ и НФ | consistency | №09 |
| cashback.drop_promised.no_read_method |  | major | ambiguity | Возврат покупки ниже 500 ₸ может увести кэшбэк в минус | consistency | №09 |
| cashback.drop_promised.no_read_method |  | minor | missing_element | Повторное событие «проведена» не отсекается, идентификатора покупки нет | lens:risk | №08 |
| cashback.drop_promised.no_read_method |  | major | incomplete | Срок выбора категории не реализован в saveCategory | consistency, lens:architect | №07, №09 |
| cashback.drop_promised.no_read_method |  | major | incomplete | Не определено поведение без выбранной категории в месяце | consistency | №09 |
| cashback.drop_promised.no_read_method |  | minor | terminology | Одни и те же понятия названы по-разному, глоссария нет | consistency | №09 |
| cashback.drop_promised.no_read_method |  | minor | missing_element | Критерии приёмки покрывают три из семи функциональных требований | lens:qa | №06 |
| cashback.event_conflict.category_effective_now |  | major | missing_element | Тело ответа 200 метода saveCategory указано, но не описано | lens:architect, consistency | №07, №09 |
| cashback.event_conflict.category_effective_now |  | minor | contradiction | Цель «одна категория на месяц» не закреплена правилом смены | consistency | №09 |
| cashback.event_conflict.category_effective_now |  | minor | terminology | Один и тот же продукт назван двумя разными именами | consistency | №09 |
| cashback.event_conflict.category_effective_now |  | major | ambiguity | Не задано, по какой дате покупки сравнивать с моментом сохранения | lens:risk | №08 |
| cashback.event_conflict.category_effective_now |  | minor | incomplete | Критерии приёмки покрывают 3 из 8 функциональных требований | lens:qa | №06 |
| cashback.event_conflict.category_effective_now |  | minor | other | Пункты КБ-1…КБ-8 не имеют приоритета | consistency | №09 |
| cashback.event_conflict.category_effective_now |  | major | ambiguity | Возврат покупки ниже порога 500 ₸: уменьшать кэшбэк или нет | consistency | №09 |
| cashback.range_boundary.cap_strict |  | minor | incomplete | Критерии приёмки покрывают не все функциональные требования | lens:qa | №06 |
| cashback.range_boundary.cap_strict |  | major | contradiction | КБ-2 и КБ-1 по-разному определяют категорию покупки в месяце выбора | consistency | №09 |
| cashback.range_boundary.cap_strict |  | major | missing_element | Тело успешного ответа saveCategory не описано, ссылка ведёт в пустоту | lens:architect | №07 |
| cashback.range_boundary.cap_strict |  | minor | terminology | Понятия «начисление» и «зачисление» названы по-разному, глоссария нет | consistency | №09 |
| cashback.range_boundary.cap_strict |  | major | api_contract | Коды отказа getCashback не описаны, таблица относится к saveCategory | lens:architect | №07 |
| cashback.range_boundary.cap_strict |  | major | ambiguity | Возврат в день зачисления: момент относительно зачисления не задан | consistency | №09 |
| cashback.range_boundary.cap_strict |  | major | ambiguity | Смена категории в том же месяце: не определено, что считается | lens:risk | №08 |
| cashback.range_boundary.cap_strict |  | minor | traceability | У требований нет приоритетов, у данных и интеграции нет ID | consistency | №09 |
| cashback.two_statuses.bad_category_200 |  | minor | ambiguity | Возврат в день зачисления 5-го числа: порядок не определён | consistency | №09 |
| cashback.two_statuses.bad_category_200 |  | minor | traceability | Требования и критерии без ID и приоритетов | consistency | №09 |
| cashback.two_statuses.bad_category_200 |  | minor | missing_element | Критерии приёмки покрывают малую часть функциональных требований | lens:qa | №06 |
| cashback.two_statuses.bad_category_200 |  | minor | terminology | Сумма кэшбэка месяца называется по-разному в разных разделах | consistency | №09 |
| cashback.unit_change.accrued_in_tiyn |  | minor | duplicate | Ставка 5 % записана в двух требованиях | consistency | №09 |
| cashback.unit_change.accrued_in_tiyn |  | major | missing_element | Код 200 saveCategory ссылается на отсутствующее тело ответа | lens:architect, consistency | №07, №09 |
| cashback.unit_change.accrued_in_tiyn |  | critical | ambiguity | Месяц покупки не определён: дата оплаты или статус «проведена» | consistency | №09 |
| cashback.unit_change.accrued_in_tiyn |  | major | ambiguity | Возврат в день зачисления: до или после зачисления | consistency | №09 |
| cashback.unit_change.accrued_in_tiyn |  | minor | incomplete | Функциональные требования КБ-1…КБ-7 без приоритетов | consistency | №09 |
| cashback.unit_change.accrued_in_tiyn |  | minor | missing_element | Приёмка проверяет 3 из 7 функциональных требований | lens:qa | №06 |
| cashback.unit_change.accrued_in_tiyn |  | major | incomplete | Повторный выбор категории в месяце не описан | consistency | №09 |
| cashback.unit_change.accrued_in_tiyn |  | minor | terminology | Одни понятия в документе названы разными терминами | consistency | №09 |
| transfer_limit.combo.two_statuses-range_200_error+drop_promised-no_read_method |  | minor | incomplete | Критерии приёмки покрывают 3 из 6 функциональных требований | lens:qa | №06 |
| transfer_limit.combo.two_statuses-range_200_error+drop_promised-no_read_method |  | minor | terminology | Одни понятия названы разными терминами, глоссария нет | consistency | №09 |
| transfer_limit.combo.two_statuses-range_200_error+drop_promised-no_read_method |  | minor | other | Функциональные требования ЛП-1…ЛП-6 без приоритетов | consistency | №09 |
| transfer_limit.drop_promised.no_read_method |  | minor | api_contract | Content-Type application/json задан для пустого ответа 200 | lens:architect | №07 |
| transfer_limit.drop_promised.no_read_method |  | minor | other | Приоритеты функциональных требований ЛП-1…ЛП-6 не указаны | consistency | №09 |
| transfer_limit.drop_promised.no_read_method |  | minor | incomplete | Критерии приёмки покрывают три из шести функциональных требований | lens:qa | №06 |
| transfer_limit.drop_promised.no_read_method |  | major | security | Чтение лимита не проверяет принадлежность клиенту сессии | lens:risk | №08 |
| transfer_limit.drop_promised.no_read_method |  | minor | terminology | Одни понятия названы разными терминами: «Мобильный банк», «Приложение» | consistency | №09 |
| transfer_limit.event_conflict.cancel_no_restore |  | minor | missing_element | Критерии приёмки покрывают 2 из 7 функциональных требований | lens:qa | №06 |
| transfer_limit.event_conflict.cancel_no_restore |  | minor | terminology | Одни понятия названы разными терминами, глоссария отсутствует | consistency | №09 |
| transfer_limit.event_conflict.cancel_no_restore |  | minor | incomplete | Функциональные требования ЛП-1…ЛП-7 без приоритетов | consistency | №09 |
| transfer_limit.range_boundary.reaching_rejects |  | minor | missing_element | Критерии приёмки покрывают только 2 из 6 требований | lens:qa | №06 |
| transfer_limit.range_boundary.reaching_rejects |  | minor | other | Функциональные требования ЛП-1…ЛП-6 без приоритетов | consistency | №09 |
| transfer_limit.range_boundary.reaching_rejects |  | major | ambiguity | ЛП-5 и ЛП-6: лимит до первого перевода не определён | consistency | №09 |
| transfer_limit.range_boundary.reaching_rejects |  | minor | terminology | Одни понятия названы разными терминами в разных разделах | consistency | №09 |
| transfer_limit.range_boundary.reaching_rejects |  | minor | ambiguity | Ответ used не поясняет отмену перевода за прошлые сутки | consistency | №09 |
| transfer_limit.two_statuses.range_200_error |  | minor | terminology | Одни и те же понятия названы разными терминами, глоссария нет | consistency | №09 |
| transfer_limit.two_statuses.range_200_error |  | minor | other | Приоритеты функциональных требований ЛП-1…ЛП-6 не указаны | consistency | №09 |
| transfer_limit.two_statuses.range_200_error |  | minor | missing_element | Критерии приёмки покрывают только 3 из 6 функциональных требований | lens:qa | №06 |
| transfer_limit.two_statuses.range_200_error |  | major | ambiguity | Экран лимита: старый или новый лимит после изменения не определён | consistency | №09 |
| transfer_limit.unit_change.api_limit_in_tiyn |  | minor | incomplete | Приёмка проверяет лишь два из шести функциональных требований | lens:qa | №06 |
| transfer_limit.unit_change.api_limit_in_tiyn |  | minor | missing_element | Функциональные требования не имеют приоритетов | consistency | №09 |
| transfer_limit.unit_change.api_limit_in_tiyn |  | minor | incomplete | Снижение лимита ниже использованной суммы не описано | consistency | №09 |
| transfer_limit.unit_change.api_limit_in_tiyn |  | minor | incomplete | Отмена перевода прошлых суток: эффект на остаток не описан | lens:risk | №08 |
| transfer_limit.unit_change.api_limit_in_tiyn |  | minor | terminology | Одна величина «использовано» названа четырьмя способами | consistency | №09 |
| transfer_limit.unit_change.api_limit_in_tiyn |  | major | api_contract | Тип поля limit: строка в GET, integer в PUT | consistency | №09 |

Пропуски:

| Кейс | Тип дефекта | Близкая находка (не засчитана) | Владельцы |
| :--- | :--- | :--- | :--- |
| cardblock.combo.unit_change-blocked_at_utc+two_statuses-reblock_200 | status_conflict | D-05 Повторная блокировка без days: «без изменений» не говорит о  (consistency); D-06 Строка 409 не исключает повторную блокировку из строки 92 (lens:qa, lens:architect, lens:risk, consistency, rules:api.same_case.200-409) | №09, №07 |

| Кейс | Ожидание | Статус | Замечаний (к/с/н) | Вердикт |
| :--- | :--- | :--- | :--- | :--- |
| autopay.base | clean | complete | 5 (0/0/5) | yes/yes |
| autopay.combo.unit_change-limit_per_hour+drop_promised-no_409_status | defects | complete | 12 (1/6/5) | no/no |
| autopay.drop_promised.no_409_status | defects | complete | 8 (0/1/7) | yes/yes |
| autopay.event_conflict.insufficient_funds_credit | defects | complete | 7 (1/2/4) | no/no |
| autopay.paraphrase.nfr | clean | complete | 6 (0/0/6) | yes/yes |
| autopay.range_boundary.trigger_at_threshold | defects | complete | 7 (1/1/5) | no/no |
| autopay.two_statuses.range_422 | defects | complete | 6 (0/1/5) | yes/yes |
| autopay.unit_change.limit_per_hour | defects | complete | 5 (1/1/3) | no/no |
| cardblock.base | clean | complete | 9 (0/0/9) | yes/yes |
| cardblock.combo.unit_change-blocked_at_utc+two_statuses-reblock_200 | defects | complete | 6 (0/1/5) | yes/yes |
| cardblock.drop_promised.no_last_digits | defects | complete | 7 (0/1/6) | yes/yes |
| cardblock.event_conflict.unblock_daily_limit | defects | complete | 6 (1/2/3) | no/no |
| cardblock.paraphrase.keep_authorizations | clean | complete | 9 (0/0/9) | yes/yes |
| cardblock.range_boundary.days_400_at_30 | defects | complete | 5 (1/1/3) | no/no |
| cardblock.two_statuses.reblock_200 | defects | complete | 5 (1/1/3) | no/no |
| cardblock.unit_change.blocked_at_utc | defects | complete | 7 (0/1/6) | yes/yes |
| cashback.base | clean | complete | 8 (0/0/8) | yes/yes |
| cashback.combo.event_conflict-category_effective_now+range_boundary-cap_strict | defects | complete | 8 (2/2/4) | no/no |
| cashback.drop_promised.no_read_method | defects | complete | 8 (1/3/4) | no/no |
| cashback.event_conflict.category_effective_now | defects | complete | 8 (1/3/4) | no/no |
| cashback.paraphrase.rate | clean | complete | 8 (0/1/7) | yes/yes |
| cashback.range_boundary.cap_strict | defects | complete | 9 (1/5/3) | no/no |
| cashback.two_statuses.bad_category_200 | defects | complete | 5 (1/0/4) | no/no |
| cashback.unit_change.accrued_in_tiyn | defects | complete | 9 (1/4/4) | no/no |
| edge.empty | clean | complete | 0 (0/0/0) | undetermined/undetermined |
| transfer_limit.base | clean | complete | 7 (0/1/6) | yes/yes |
| transfer_limit.combo.two_statuses-range_200_error+drop_promised-no_read_method | defects | complete | 5 (2/0/3) | no/no |
| transfer_limit.drop_promised.no_read_method | defects | complete | 6 (1/1/4) | no/no |
| transfer_limit.event_conflict.cancel_no_restore | defects | complete | 4 (1/0/3) | no/no |
| transfer_limit.paraphrase.new_limit | clean | complete | 6 (0/1/5) | yes/yes |
| transfer_limit.range_boundary.reaching_rejects | defects | complete | 6 (1/1/4) | no/no |
| transfer_limit.two_statuses.range_200_error | defects | complete | 5 (1/1/3) | no/no |
| transfer_limit.unit_change.api_limit_in_tiyn | defects | complete | 7 (1/1/5) | no/no |
