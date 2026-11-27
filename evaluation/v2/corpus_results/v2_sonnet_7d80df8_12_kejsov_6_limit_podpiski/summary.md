# Корпус evaluation/dev — v2 sonnet, 7d80df8, 12 кейсов (6 — лимит подписки)

Кейсов 12 (не запускались 21), не измерено 6 (пропусков в счётчике 6).

| TP | FP | FN | Дубли | Precision | Recall | F1 |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 4 | 82 | 0 | 1 | 0.047 | 1.000 | 0.089 |

Чистые документы (2/4 измерено): замечаний 29, critical 0, major 12; документов с critical 0, с > 1 major 2, вердикт «нельзя» 0; документов с > 1 замечанием 2, максимум на одном 15. Ложных тревог по счётчику: 29.

Recall по типам: boundary_conflict 1/1, event_conflict 1/1, status_conflict 1/1, unit_mismatch 1/1.

Время 14.4 мин суммарно, вызовов 76, $3.056.

Кандидаты этапов до судьи (верхняя граница): TP 6/8, recall 0.750; по типам: boundary_conflict 1/2, event_conflict 1/2, missing_element 1/1, status_conflict 2/2, unit_mismatch 1/1.

Ложные на мутантах (53) по происхождению: та же жалоба, что на чистой базе семейства — 30 (57 %; №05 12, №06 10, №08 8, №09 7, №07 7), то же место с другой жалобой — 19, только у мутанта — 4; строгий фон счётчика — 13. Ложная жалоба чистой базы повторяется на мутантах: убрать её на чистых — уйдут и эти.

Вклад источников (замечание с несколькими источниками считается каждому):

| Источник | TP | FP | из них на чистых |
| :--- | ---: | ---: | ---: |
| consistency (№09) | 4 | 34 | 14 |
| lens:analyst (№05) | 2 | 24 | 9 |
| lens:architect (№07) | 3 | 13 | 5 |
| lens:qa (№06) | 3 | 19 | 7 |
| lens:risk (№08) | 0 | 21 | 7 |
| rules (№12) | 2 | 0 | 0 |

Ложные находки:

| Кейс | Чистый | Серьёзность | Тип | Замечание | Источники | Владельцы |
| :--- | :---: | :--- | :--- | :--- | :--- | :--- |
| autopay.base | да | minor | ops_risk | Гонка параллельных уведомлений у лимита трёх пополнений и при отключении | lens:risk | №08 |
| autopay.base | да | minor | missing_element | Критерии приёмки не покрывают границы, повторы, отключение и коды ошибок | lens:qa | №06 |
| autopay.base | да | major | api_contract | Тело успешного ответа createAutopay не описано, хотя таблица отсылает к методу | lens:architect | №07 |
| autopay.base | да | minor | missing_element | Приём уведомления оператора и способ пополнения номера не описаны | consistency | №09 |
| autopay.base | да | minor | api_contract | Шаги 1–2 createAutopay не называют коды отказа и порядок проверок | lens:architect | №07 |
| autopay.base | да | minor | contradiction | Цель «баланс не опускается ниже порога» не обеспечивается требованиями | consistency | №09 |
| autopay.base | да | minor | security | Подлинность уведомления оператора, запускающего списание, не определена | lens:risk | №08 |
| autopay.base | да | minor | missing_element | Не описан сбой пополнения номера после списания с карты | lens:risk, consistency | №08, №09 |
| autopay.base | да | major | ambiguity | АП-5: не определено, к каким суткам и какие попытки считаются в лимите | lens:qa, lens:analyst, consistency | №05, №06, №09 |
| autopay.base | да | minor | missing_element | У требований нет идентификаторов приоритета | consistency | №09 |
| autopay.base | да | minor | terminology | Разные термины: «отключение» и «удаляет», «автопополнение» и «настройка» | lens:analyst, consistency | №05, №09 |
| autopay.base | да | major | ambiguity | АП-1 и шаг 3 createAutopay: уникальность по номеру или по карте не определена | lens:analyst, lens:qa, consistency, lens:architect | №05, №06, №07, №09 |
| autopay.base | да | major | incomplete | Валюта карты KZT из АП-1 не проверяется в логике createAutopay | lens:risk, consistency | №08, №09 |
| autopay.base | да | minor | unverifiable | НФ-1: не определены конец интервала, нагрузка и период расчёта 99 % | lens:analyst, lens:qa | №05, №06 |
| autopay.base | да | minor | non_singular | Пункты АП-1, АП-6 и интеграции содержат несколько независимых правил | lens:analyst | №05 |
| cardblock.base | да | minor | non_singular | Несколько независимых правил в одном пункте БК-2 | lens:analyst | №05 |
| cardblock.base | да | minor | incomplete | Ответ getCardStatus описан только для BLOCKED_BY_CLIENT; смысл days и бессрочной блокировк | lens:architect | №07 |
| cardblock.base | да | minor | missing_element | У требований нет приоритетов и признаков важности | consistency | №09 |
| cardblock.base | да | minor | terminology | Терминология не едина, глоссария нет: «Владелец карты, который блокирует карту», «Срок бло | consistency | №09 |
| cardblock.base | да | major | incomplete | Автоматическое снятие блокировки по сроку не описано | lens:analyst, consistency | №05, №09 |
| cardblock.base | да | major | ambiguity | Не определён момент блокировки: запрос, ответ 200 или конец окна в 10 секунд | lens:analyst, lens:risk, consistency | №05, №08, №09 |
| cardblock.base | да | major | ambiguity | Не определено, как отсчитываются сутки срока блокировки и когда он заканчивается | lens:analyst, lens:qa | №05, №06 |
| cardblock.base | да | minor | ambiguity | Момент окончания срока блокировки в сутках не определён: от времени блокировки или до конц | lens:risk | №08 |
| cardblock.base | да | major | missing_element | Push о блокировке обещан, но канал и событие отправки нигде не описаны | consistency | №09 |
| cardblock.base | да | minor | incomplete | Автоматический возврат в ACTIVE по окончании срока не учитывает другие состояния карты (пе | lens:risk | №08 |
| cardblock.base | да | major | unverifiable | Push БК-7 не проверяем: нет срока и фиксации | lens:qa | №06 |
| cardblock.base | да | major | missing_element | Приёмка не покрывает границы days, ошибки и разблокировку | lens:qa | №06 |
| cardblock.base | да | major | contradiction | Окно до 10 с после ответа 200 противоречит правилу отклонения при статусе BLOCKED | lens:architect | №07 |
| cardblock.base | да | major | ambiguity | R-22 и R-25: порядок проверок параметра и статуса не определён | consistency | №09 |
| autopay.event_conflict.insufficient_funds_credit |  | minor | missing_element | Приём уведомления оператора, запускающего автопополнение, не описан | consistency, lens:analyst | №05, №09 |
| autopay.event_conflict.insufficient_funds_credit |  | minor | ops_risk | Не определён сбой пополнения после списания и изменение настройки | lens:risk, consistency | №08, №09 |
| autopay.event_conflict.insufficient_funds_credit |  | minor | unverifiable | НФ-1: не определены конец замера 5 минут и условия измерения | lens:qa, lens:analyst | №05, №06 |
| autopay.event_conflict.insufficient_funds_credit |  | major | ambiguity | Не определено, к каким суткам относится пополнение для лимита АП-5 | lens:qa, lens:analyst, lens:risk | №05, №06, №08 |
| autopay.event_conflict.insufficient_funds_credit |  | major | incomplete | Тело ответа createAutopay и логика deleteAutopay не описаны | lens:architect | №07 |
| autopay.event_conflict.insufficient_funds_credit |  | major | missing_element | Ограничение «карта KZT» из АП-1 не проверяется в логике createAutopay | lens:risk, lens:architect | №07, №08 |
| autopay.event_conflict.insufficient_funds_credit |  | minor | terminology | Терминология не едина: отключение и удаление, автопополнение и настройка | consistency | №09 |
| autopay.event_conflict.insufficient_funds_credit |  | minor | contradiction | Цель обещает баланс выше порога, требования этого не гарантируют | consistency | №09 |
| autopay.event_conflict.insufficient_funds_credit |  | major | contradiction | Уникальность настройки: АП-1 про «один номер», createAutopay проверяет только карту | lens:architect, consistency, lens:risk | №07, №08, №09 |
| autopay.event_conflict.insufficient_funds_credit |  | minor | missing_element | Критерии приёмки не покрывают границы, ошибки API, повторы и отключение | lens:qa | №06 |
| autopay.event_conflict.insufficient_funds_credit |  | minor | other | У требований нет приоритетов и признаков стабильности | consistency | №09 |
| autopay.two_statuses.range_422 |  | major | unverifiable | НФ-1: не определён конец 5-минутного срока и условия измерения | lens:analyst, lens:qa | №05, №06 |
| autopay.two_statuses.range_422 |  | major | incomplete | Ограничение «один номер» из АП-1 не проверяется: уникальность только по карте | lens:architect, lens:analyst | №05, №07 |
| autopay.two_statuses.range_422 |  | minor | other | У требований АП-1…АП-7 и НФ-1 нет приоритетов | consistency | №09 |
| autopay.two_statuses.range_422 |  | major | api_contract | Тело успешного ответа createAutopay не описано | lens:architect | №07 |
| autopay.two_statuses.range_422 |  | major | ambiguity | Не определено, к каким суткам относится пополнение в лимите АП-5 | lens:analyst, lens:qa | №05, №06 |
| autopay.two_statuses.range_422 |  | minor | missing_element | Нет изменения настройки и правил учёта суток при повторном создании | consistency | №09 |
| autopay.two_statuses.range_422 |  | minor | missing_element | Приёмка не покрывает границы, ошибки API и повторные уведомления | lens:qa | №06 |
| autopay.two_statuses.range_422 |  | minor | ops_risk | Не описан итог при списании без успешного пополнения номера | lens:risk | №08 |
| autopay.two_statuses.range_422 |  | major | missing_element | Условие «карты KZT» из АП-1 не проверяется в логике createAutopay | lens:risk, lens:analyst | №05, №08 |
| autopay.two_statuses.range_422 |  | minor | missing_element | Приём уведомления оператора и вызов пополнения у оператора не описаны | consistency | №09 |
| autopay.two_statuses.range_422 |  | minor | terminology | Терминология не едина: автопополнение/настройка, порог/threshold | consistency | №09 |
| autopay.two_statuses.range_422 |  | minor | ops_risk | Гонка уведомлений с разными идентификаторами событий не покрыта | lens:risk | №08 |
| autopay.two_statuses.range_422 |  | minor | contradiction | Цель «не ниже порога» не обеспечивается лимитом, задержкой и отказом по средствам | consistency | №09 |
| autopay.two_statuses.range_422 |  | minor | terminology | «Отключение» не сопоставлено с deleteAutopay, момент прекращения не задан | lens:analyst | №05 |
| cardblock.range_boundary.days_400_at_30 |  | major | incomplete | Ответ getCardStatus для ACTIVE и бессрочной блокировки не описан | lens:qa | №06 |
| cardblock.range_boundary.days_400_at_30 |  | minor | incomplete | Судьба клиринга ранее одобренных авторизаций и возвратов на заблокированную карту не опред | lens:risk | №08 |
| cardblock.range_boundary.days_400_at_30 |  | major | missing_element | Нет описания взаимодействия с процессингом, который должен отклонять авторизации | consistency | №09 |
| cardblock.range_boundary.days_400_at_30 |  | minor | incomplete | Не определено хранение и значение срока для бессрочной блокировки и значения инициатора | lens:analyst | №05 |
| cardblock.range_boundary.days_400_at_30 |  | major | missing_element | Push из БК-7 не обеспечен ни одним методом, данными или интеграцией | consistency | №09 |
| cardblock.range_boundary.days_400_at_30 |  | minor | non_singular | Пункты БК-1 и БК-2 объединяют несколько независимых правил | lens:analyst | №05 |
| cardblock.range_boundary.days_400_at_30 |  | minor | api_contract | Пример ответа getCardStatus дан только для состояния BLOCKED_BY_CLIENT | lens:architect | №07 |
| cardblock.range_boundary.days_400_at_30 |  | major | missing_element | Приёмка не покрывает границы, ошибки, разблокировку, срок и push | lens:qa | №06 |
| cardblock.range_boundary.days_400_at_30 |  | major | ambiguity | Не определён момент окончания срока блокировки и кто возвращает ACTIVE | lens:analyst, lens:qa | №05, №06 |
| cardblock.range_boundary.days_400_at_30 |  | minor | missing_element | У требований нет приоритета и признака стабильности | consistency | №09 |
| cardblock.range_boundary.days_400_at_30 |  | minor | terminology | Терминология не едина, глоссария нет: «Срок блокировки» | consistency | №09 |
| cardblock.range_boundary.days_400_at_30 |  | minor | ambiguity | Не определено, какое событие запускает push: ответ 200 или вступление блокировки в силу | lens:analyst, lens:risk | №05, №08 |
| cardblock.range_boundary.days_400_at_30 |  | critical | status_conflict | Код 400 отклоняет days=30, хотя 30 суток допустимо | lens:architect | №07 |
| cardblock.range_boundary.days_400_at_30 |  | minor | ops_risk | Повтор blockCard после потери ответа или 500 даёт 409 и не показывает клиенту результат пе | lens:risk | №08 |
| cardblock.range_boundary.days_400_at_30 |  | minor | incomplete | Окончание срока блокировки не имеет описанного механизма и сценариев | consistency | №09 |
| cardblock.range_boundary.days_400_at_30 |  | minor | incomplete | Срок блокировки истекает без заданного механизма: автоматический возврат в ACTIVE не учиты | lens:risk | №08 |
| cardblock.unit_change.blocked_at_utc |  | minor | unverifiable | Требование БК-5 «не позднее 10 секунд»: не названы место измерения и доля случаев | lens:risk | №08 |
| cardblock.unit_change.blocked_at_utc |  | minor | incomplete | Ответ getCardStatus описан одним примером для BLOCKED_BY_CLIENT | lens:architect | №07 |
| cardblock.unit_change.blocked_at_utc |  | major | ambiguity | Не определено, как считаются сутки срока блокировки и от какого момента | lens:analyst, lens:qa, lens:risk | №05, №06, №08 |
| cardblock.unit_change.blocked_at_utc |  | minor | terminology | Терминология не едина, глоссария нет: «Срок блокировки» | consistency | №09 |
| cardblock.unit_change.blocked_at_utc |  | major | unverifiable | Push о блокировке не проверяем системно | lens:qa | №06 |
| cardblock.unit_change.blocked_at_utc |  | major | missing_element | Приёмка не покрывает границы, ошибки и разблокировку | lens:qa | №06 |
| cardblock.unit_change.blocked_at_utc |  | major | missing_element | Процессинг и push обещаны, но не описаны в интеграции | consistency | №09 |
| cardblock.unit_change.blocked_at_utc |  | minor | incomplete | Судьба операций по ранее одобренной авторизации и возвратов на заблокированную карту не оп | lens:risk | №08 |
| cardblock.unit_change.blocked_at_utc |  | minor | non_singular | Несколько независимых правил в одном пункте | lens:analyst | №05 |
| cardblock.unit_change.blocked_at_utc |  | minor | missing_element | Push из БК-7 не описан: механизм, сбой доставки и разблокировка | consistency | №09 |
| cardblock.unit_change.blocked_at_utc |  | minor | other | Нет приоритетов и признаков важности требований | consistency | №09 |
| cardblock.unit_change.blocked_at_utc |  | major | ambiguity | Не определён момент «до блокировки» для сохранения одобренных авторизаций | lens:analyst | №05 |

| Кейс | Ожидание | Статус | Замечаний (к/с/н) | Вердикт |
| :--- | :--- | :--- | :--- | :--- |
| autopay.base | clean | complete | 15 (0/4/11) | conditional/conditional |
| autopay.event_conflict.insufficient_funds_credit | defects | complete | 12 (1/4/7) | no/no |
| autopay.two_statuses.range_422 | defects | complete | 15 (0/6/9) | conditional/conditional |
| cardblock.base | clean | complete | 14 (0/8/6) | conditional/conditional |
| cardblock.range_boundary.days_400_at_30 | defects | complete | 17 (2/5/10) | no/no |
| cardblock.unit_change.blocked_at_utc | defects | complete | 14 (0/7/7) | conditional/conditional |
| cashback.base | clean | failed | 0 (0/0/0) | none/none |
| cashback.drop_promised.no_read_method | defects | failed | 1 (1/0/0) | none/none |
| cashback.event_conflict.category_effective_now | defects | failed | 0 (0/0/0) | none/none |
| transfer_limit.base | clean | failed | 0 (0/0/0) | none/none |
| transfer_limit.range_boundary.reaching_rejects | defects | failed | 0 (0/0/0) | none/none |
| transfer_limit.two_statuses.range_200_error | defects | failed | 1 (0/1/0) | none/none |
