# Корпус evaluation/dev — W4-07 кандидат 868787d: 868787d, haiku

Кейсов 33 (не запускались 0), не измерено 23 (пропусков в счётчике 23).

| TP | FP | FN | Дубли | Precision | Recall | F1 |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 7 | 59 | 0 | 0 | 0.106 | 1.000 | 0.192 |

Чистые документы (3/8 измерено): замечаний 20, critical 0, major 0; документов с critical 0, с > 1 major 0, вердикт «нельзя» 0; документов с > 1 замечанием 3, максимум на одном 8. Ложных тревог по счётчику: 20.

Recall по типам: boundary_conflict 1/1, event_conflict 1/1, missing_element 2/2, status_conflict 1/1, unit_mismatch 2/2.

Время 22.7 мин суммарно, вызовов 106, $0.544.

Кандидаты этапов до судьи (верхняя граница): TP 27/28, recall 0.964; по типам: boundary_conflict 5/5, event_conflict 5/5, missing_element 5/6, status_conflict 6/6, unit_mismatch 6/6.

Вклад источников (замечание с несколькими источниками считается каждому):

| Источник | TP | FP | из них на чистых |
| :--- | ---: | ---: | ---: |
| consistency (№09) | 7 | 41 | 16 |
| lens:analyst (№05) | 3 | 0 | 0 |
| lens:architect (№07) | 0 | 7 | 1 |
| lens:qa (№06) | 5 | 9 | 3 |
| lens:risk (№08) | 0 | 2 | 0 |
| rules (№12) | 7 | 0 | 0 |

Ложные находки:

| Кейс | Чистый | Серьёзность | Тип | Замечание | Источники | Владельцы |
| :--- | :---: | :--- | :--- | :--- | :--- | :--- |
| autopay.base | да | minor | terminology | Оператор связи и автопополнение названы разными терминами, глоссария нет | consistency | №09 |
| autopay.base | да | minor | incomplete | Критерии приёмки не покрывают границы, повторы и ошибки | lens:qa | №06 |
| autopay.base | да | minor | contradiction | Цель без числа расходится с ограничениями лимита и уведомлений | consistency | №09 |
| autopay.base | да | minor | incomplete | Нет метода изменения порога и суммы настройки | consistency | №09 |
| autopay.base | да | minor | ambiguity | Порядок проверок при 404 и 400 не задан в таблице кодов | consistency | №09 |
| autopay.base | да | minor | incomplete | У требований, данных и методов API нет ID и приоритетов | consistency | №09 |
| autopay.paraphrase.nfr | да | minor | ambiguity | Повтор события после отказа по средствам не определён | consistency | №09 |
| autopay.paraphrase.nfr | да | minor | incomplete | Логика createAutopay не описывает обработку уведомления | consistency | №09 |
| autopay.paraphrase.nfr | да | minor | incomplete | Проверка карты в KZT отсутствует в логике createAutopay | lens:architect | №07 |
| autopay.paraphrase.nfr | да | minor | terminology | Одни и те же компоненты и понятия названы по-разному | consistency | №09 |
| autopay.paraphrase.nfr | да | minor | missing_element | Не описаны изменение настройки и повторное подключение | consistency | №09 |
| autopay.paraphrase.nfr | да | minor | other | Приоритеты требований и признак важности не указаны | consistency | №09 |
| autopay.paraphrase.nfr | да | minor | missing_element | Критерии приёмки не покрывают границы, повторы и отключение | lens:qa | №06 |
| autopay.paraphrase.nfr | да | minor | ambiguity | Учёт отклонённой попытки в суточном лимите не определён | consistency | №09 |
| cardblock.base | да | minor | ambiguity | Авторизация в окне 10 секунд: момент вступления блокировки не определён | consistency | №09 |
| cardblock.base | да | minor | incomplete | Функциональные требования БК-1…БК-7 не имеют приоритетов | consistency | №09 |
| cardblock.base | да | minor | contradiction | Цель «временная блокировка» не совпадает с бессрочной блокировкой | consistency | №09 |
| cardblock.base | да | minor | missing_element | Критерии приёмки покрывают 4 из 7 функциональных требований | lens:qa | №06 |
| cardblock.base | да | minor | api_contract | При неверном days на заблокированной карте два разных кода ответа | consistency | №09 |
| cardblock.base | да | minor | terminology | Приложение назван в документе двумя разными терминами | consistency | №09 |
| autopay.combo.unit_change-limit_per_hour+drop_promised-no_409_status |  | major | missing_element | Проверка карты KZT из АП-1 не отражена в логике createAutopay | lens:architect | №07 |
| autopay.combo.unit_change-limit_per_hour+drop_promised-no_409_status |  | minor | incomplete | Критерии приёмки не покрывают границы, повторы и ошибки | lens:qa | №06 |
| autopay.combo.unit_change-limit_per_hour+drop_promised-no_409_status |  | minor | ambiguity | Порядок проверок номера и принадлежности карты не задан | consistency | №09 |
| autopay.combo.unit_change-limit_per_hour+drop_promised-no_409_status |  | minor | incomplete | Изменение действующей настройки не описано | consistency | №09 |
| autopay.combo.unit_change-limit_per_hour+drop_promised-no_409_status |  | minor | terminology | Термины «оператор связи» и «настройка автопополнения» названы по-разному | consistency | №09 |
| autopay.combo.unit_change-limit_per_hour+drop_promised-no_409_status |  | minor | other | Функциональные требования и НФ-1 не имеют приоритетов | consistency | №09 |
| autopay.combo.unit_change-limit_per_hour+drop_promised-no_409_status |  | minor | contradiction | Цель «не опускается ниже порога» противоречит АП-6 и АП-5 | consistency | №09 |
| autopay.drop_promised.no_409_status |  | major | incomplete | Условие KZT-карты из АП-1 не проверяется в createAutopay | lens:architect | №07 |
| autopay.drop_promised.no_409_status |  | critical | contradiction | АП-4 и АП-6 дают разные исходы при нехватке средств на карте | consistency | №09 |
| autopay.drop_promised.no_409_status |  | minor | other | Требования не имеют приоритетов для защиты при нехватке времени | consistency | №09 |
| autopay.drop_promised.no_409_status |  | minor | incomplete | Судьба счётчика при повторном подключении в те же сутки не описана | consistency | №09 |
| autopay.drop_promised.no_409_status |  | minor | terminology | Одни понятия названы разными терминами: оператор, настройка | consistency | №09 |
| autopay.drop_promised.no_409_status |  | minor | incomplete | Критерии приёмки не покрывают границы, ошибки и повторы | lens:qa | №06 |
| autopay.event_conflict.insufficient_funds_credit |  | minor | other | Требования не имеют приоритетов, ранжирования нет | consistency | №09 |
| autopay.event_conflict.insufficient_funds_credit |  | minor | terminology | Одни понятия названы разными терминами в разных разделах | consistency | №09 |
| autopay.event_conflict.insufficient_funds_credit |  | major | missing_element | Для кредитного пополнения нет хранимого признака и суммы долга | lens:architect | №07 |
| autopay.event_conflict.insufficient_funds_credit |  | major | missing_element | Тело успешного ответа createAutopay нигде не описано | lens:architect | №07 |
| autopay.event_conflict.insufficient_funds_credit |  | minor | incomplete | Не сказано, сбрасывается ли счётчик при пересоздании настройки | consistency | №09 |
| autopay.event_conflict.insufficient_funds_credit |  | minor | missing_element | Критерии приёмки не проверяют границы, повторы и коды ошибок | lens:qa | №06 |
| autopay.event_conflict.insufficient_funds_credit |  | major | ambiguity | Неясно, засчитывается ли отказ по нехватке средств в лимит трёх | lens:risk | №08 |
| autopay.range_boundary.trigger_at_threshold |  | major | ambiguity | Две настройки на один номер: неясно число пополнений за уведомление | lens:risk | №08 |
| autopay.range_boundary.trigger_at_threshold |  | minor | missing_element | Критерии приёмки покрывают 5 из 11 функциональных требований | lens:qa | №06 |
| autopay.range_boundary.trigger_at_threshold |  | minor | contradiction | Цель не опускать баланс ниже порога не гарантирована требованиями | consistency | №09 |
| autopay.range_boundary.trigger_at_threshold |  | minor | incomplete | Счётчик трёх пополнений в сутки не связан с отключением настройки | consistency | №09 |
| autopay.range_boundary.trigger_at_threshold |  | minor | other | Требования не имеют приоритетов выполнения | consistency | №09 |
| autopay.range_boundary.trigger_at_threshold |  | minor | terminology | Одни понятия названы разными терминами, глоссария нет | consistency | №09 |
| autopay.range_boundary.trigger_at_threshold |  | minor | incomplete | Порядок проверок задан, но код при двух ошибках не определён | consistency | №09 |
| autopay.two_statuses.range_422 |  | minor | api_contract | Тело успешного ответа createAutopay не описано | lens:architect | №07 |
| autopay.two_statuses.range_422 |  | minor | terminology | Одни понятия названы разными терминами, глоссария нет | consistency | №09 |
| autopay.two_statuses.range_422 |  | minor | missing_element | Приоритетов у требований АП и НФ нет | consistency | №09 |
| autopay.two_statuses.range_422 |  | minor | contradiction | Цель о пороге баланса исключена лимитом и нехваткой средств | consistency | №09 |
| autopay.two_statuses.range_422 |  | minor | incomplete | Повторное создание после удаления: счётчик суток не описан | consistency | №09 |
| autopay.two_statuses.range_422 |  | minor | incomplete | Критерии приёмки не покрывают границы, повторы, отключение и коды ошибок | lens:qa | №06 |
| autopay.unit_change.limit_per_hour |  | minor | contradiction | Цель обещает баланс не ниже порога, требования это допускают | consistency | №09 |
| autopay.unit_change.limit_per_hour |  | major | api_contract | createAutopay: тело ответа 200 не описано в разделе метода | lens:architect | №07 |
| autopay.unit_change.limit_per_hour |  | minor | incomplete | Повторное подключение после отключения не описано | consistency | №09 |
| autopay.unit_change.limit_per_hour |  | minor | incomplete | Критерии приёмки не покрывают границы, повторы и отключение | lens:qa | №06 |
| autopay.unit_change.limit_per_hour |  | minor | terminology | Подключение автопополнения назван по-разному: «подключает» и «создаёт настройку» | consistency | №09 |
| autopay.unit_change.limit_per_hour |  | minor | missing_element | У требований нет ID и приоритетов при конфликтующих правилах | consistency | №09 |

| Кейс | Ожидание | Статус | Замечаний (к/с/н) | Вердикт |
| :--- | :--- | :--- | :--- | :--- |
| autopay.base | clean | complete | 6 (0/0/6) | yes/yes |
| autopay.combo.unit_change-limit_per_hour+drop_promised-no_409_status | defects | complete | 9 (1/2/6) | no/no |
| autopay.drop_promised.no_409_status | defects | complete | 7 (1/2/4) | no/no |
| autopay.event_conflict.insufficient_funds_credit | defects | complete | 8 (1/3/4) | no/no |
| autopay.paraphrase.nfr | clean | complete | 8 (0/0/8) | yes/yes |
| autopay.range_boundary.trigger_at_threshold | defects | complete | 8 (1/1/6) | no/no |
| autopay.two_statuses.range_422 | defects | complete | 7 (0/1/6) | yes/yes |
| autopay.unit_change.limit_per_hour | defects | partial | 7 (1/1/5) | no/no |
| cardblock.base | clean | complete | 6 (0/0/6) | yes/yes |
| cardblock.combo.unit_change-blocked_at_utc+two_statuses-reblock_200 | defects | failed | 2 (0/2/0) | none/none |
| cardblock.drop_promised.no_last_digits | defects | failed | 0 (0/0/0) | none/none |
| cardblock.event_conflict.unblock_daily_limit | defects | failed | 1 (1/0/0) | none/none |
| cardblock.paraphrase.keep_authorizations | clean | failed | 0 (0/0/0) | none/none |
| cardblock.range_boundary.days_400_at_30 | defects | failed | 1 (0/1/0) | none/none |
| cardblock.two_statuses.reblock_200 | defects | failed | 1 (0/1/0) | none/none |
| cardblock.unit_change.blocked_at_utc | defects | failed | 1 (0/1/0) | none/none |
| cashback.base | clean | failed | 0 (0/0/0) | none/none |
| cashback.combo.event_conflict-category_effective_now+range_boundary-cap_strict | defects | failed | 2 (1/1/0) | none/none |
| cashback.drop_promised.no_read_method | defects | failed | 1 (1/0/0) | none/none |
| cashback.event_conflict.category_effective_now | defects | failed | 1 (1/0/0) | none/none |
| cashback.paraphrase.rate | clean | failed | 0 (0/0/0) | none/none |
| cashback.range_boundary.cap_strict | defects | failed | 1 (0/1/0) | none/none |
| cashback.two_statuses.bad_category_200 | defects | failed | 1 (0/1/0) | none/none |
| cashback.unit_change.accrued_in_tiyn | defects | failed | 1 (0/1/0) | none/none |
| edge.empty | clean | complete | 0 (0/0/0) | undetermined/undetermined |
| transfer_limit.base | clean | failed | 0 (0/0/0) | none/none |
| transfer_limit.combo.two_statuses-range_200_error+drop_promised-no_read_method | defects | failed | 2 (1/1/0) | none/none |
| transfer_limit.drop_promised.no_read_method | defects | failed | 1 (1/0/0) | none/none |
| transfer_limit.event_conflict.cancel_no_restore | defects | failed | 1 (1/0/0) | none/none |
| transfer_limit.paraphrase.new_limit | clean | failed | 0 (0/0/0) | none/none |
| transfer_limit.range_boundary.reaching_rejects | defects | failed | 1 (0/1/0) | none/none |
| transfer_limit.two_statuses.range_200_error | defects | failed | 1 (0/1/0) | none/none |
| transfer_limit.unit_change.api_limit_in_tiyn | defects | failed | 1 (0/1/0) | none/none |
