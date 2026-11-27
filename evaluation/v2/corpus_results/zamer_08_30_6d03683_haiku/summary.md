# Корпус evaluation/dev — замер 08:30: 6d03683, haiku

Кейсов 33 (не запускались 0), не измерено 20 (пропусков в счётчике 20).

| TP | FP | FN | Дубли | Precision | Recall | F1 |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 10 | 100 | 1 | 2 | 0.091 | 0.909 | 0.165 |

Чистые документы (8/8 измерено): замечаний 31, critical 0, major 18; документов с critical 0, с > 1 major 4, вердикт «нельзя» 0; документов с > 1 замечанием 4, максимум на одном 10. Ложных тревог по счётчику: 31.

Recall по типам: boundary_conflict 1/1, event_conflict 2/2, missing_element 3/3, status_conflict 2/2, unit_mismatch 2/3.

Время 36.9 мин суммарно, вызовов 131, $0.724.

Кандидаты этапов до судьи (верхняя граница): TP 28/28, recall 1.000; по типам: boundary_conflict 5/5, event_conflict 5/5, missing_element 6/6, status_conflict 6/6, unit_mismatch 6/6.

Ложные на мутантах (69) по происхождению: та же жалоба, что на чистой базе семейства — 19 (28 %; №09 11, №06 6, №07 2), то же место с другой жалобой — 33, только у мутанта — 17; строгий фон счётчика — 8. Ложная жалоба чистой базы повторяется на мутантах: убрать её на чистых — уйдут и эти.

Вклад источников (замечание с несколькими источниками считается каждому):

| Источник | TP | FP | из них на чистых |
| :--- | ---: | ---: | ---: |
| consistency (№09) | 9 | 64 | 18 |
| lens:analyst (№05) | 4 | 3 | 1 |
| lens:architect (№07) | 7 | 12 | 4 |
| lens:qa (№06) | 6 | 17 | 5 |
| lens:risk (№08) | 2 | 13 | 5 |
| rules (№12) | 9 | 1 | 0 |

Ложные находки:

| Кейс | Чистый | Серьёзность | Тип | Замечание | Источники | Владельцы |
| :--- | :---: | :--- | :--- | :--- | :--- | :--- |
| autopay.base | да | major | unverifiable | НФ-1: не определён конец измерения срока и период для 99 % | lens:qa | №06 |
| autopay.base | да | minor | contradiction | Цель «не опускается ниже порога» шире срока НФ-1 и не совпадает с ним | consistency | №09 |
| autopay.base | да | minor | incomplete | Критерии приёмки не покрывают границы, повтор события, отключение и ошибки 401, 404, 409 | lens:qa | №06 |
| autopay.base | да | major | incomplete | createAutopay не проверяет карту KZT, хотя АП-1 это требует | lens:architect | №07 |
| autopay.base | да | minor | terminology | Три ключевых понятия названы в разных частях разными словами, глоссария нет | consistency | №09 |
| autopay.base | да | major | missing_element | Тело ответа 200 createAutopay обещано в методе, но не описано | consistency | №09 |
| autopay.base | да | major | ambiguity | Неясно, что делать с списанным, но не зачисленным пополнением при deleteAutopay | lens:risk | №08 |
| autopay.base | да | major | ambiguity | АП-5 и АП-6 не определяют, учитывается ли неуспешная попытка в лимите трёх | consistency | №09 |
| autopay.base | да | major | incomplete | Не описано, как отключение и повторное подключение влияют на счётчик за сутки | consistency | №09 |
| autopay.base | да | minor | other | Требования не имеют приоритетов и признака важности | consistency | №09 |
| autopay.paraphrase.nfr | да | minor | missing_element | Критерии приёмки не покрывают границы, повторы, отключение, 404 и 409 | lens:qa | №06 |
| autopay.paraphrase.nfr | да | major | incomplete | Проверка валюты карты KZT из АП-1 отсутствует в логике createAutopay | lens:architect | №07 |
| autopay.paraphrase.nfr | да | major | ambiguity | Неясно, входят ли отказы при нехватке средств в лимит трёх пополнений за сутки | consistency | №09 |
| autopay.paraphrase.nfr | да | minor | terminology | Один объект назван разными терминами, глоссария нет | consistency | №09 |
| autopay.paraphrase.nfr | да | minor | other | Приоритет требований не задан ни для одного пункта | consistency | №09 |
| autopay.paraphrase.nfr | да | major | contradiction | Цель обещает неизменный порог баланса, который АП-5, АП-6 и НФ-1 не гарантируют | lens:analyst, consistency | №05, №09 |
| autopay.paraphrase.nfr | да | major | unverifiable | НФ-1: не заданы выборка для 99 % и момент завершения пополнения | lens:qa | №06 |
| autopay.paraphrase.nfr | да | major | security | Не проверяется, что номер телефона принадлежит клиенту, подключающему автопополнение | lens:risk | №08 |
| cardblock.base | да | minor | missing_element | Приоритеты функциональных требований БК-1…БК-7 не заданы | consistency | №09 |
| cardblock.base | да | minor | missing_element | Приёмка не покрывает граничные значения, отказы API, разблокировку и push | lens:qa | №06 |
| cardblock.base | да | minor | terminology | Одно приложение названо «Мобильный банк» и «Приложение» | consistency | №09 |
| cardblock.base | да | major | incomplete | Значение days в ответе getCardStatus не задано для бессрочной блокировки | lens:architect | №07 |
| cardblock.base | да | major | ambiguity | Момент блокировки для авторизаций в окне до 10 секунд не определён | lens:risk | №08 |
| cardblock.base | да | major | ambiguity | Момент начала отсчёта срока блокировки и возврата в ACTIVE не задан | lens:risk, consistency | №08, №09 |
| cardblock.paraphrase.keep_authorizations | да | minor | api_contract | Тело запроса blockCard для бессрочной блокировки не определено | lens:architect | №07 |
| cardblock.paraphrase.keep_authorizations | да | minor | traceability | Идентификаторы есть только у БК-требований | consistency | №09 |
| cardblock.paraphrase.keep_authorizations | да | major | ambiguity | Не определено, в какой момент истекает срок блокировки и карта возвращается в ACTIVE | lens:risk | №08 |
| cardblock.paraphrase.keep_authorizations | да | major | ambiguity | Порядок проверок: 400 за days и 409 за статус по одному запросу (п. L086, L089) | consistency | №09 |
| cardblock.paraphrase.keep_authorizations | да | minor | other | Приоритет и важность требований не указаны | consistency | №09 |
| cardblock.paraphrase.keep_authorizations | да | major | missing_element | Инициатор изменения хранится, но не передаётся ни в одном ответе API | consistency | №09 |
| cardblock.paraphrase.keep_authorizations | да | major | incomplete | Ответ getCardStatus для бессрочной блокировки не определён (L061, L079) | consistency | №09 |
| autopay.combo.unit_change-limit_per_hour+drop_promised-no_409_status |  | minor | incomplete | Функциональные и нефункциональные требования не имеют приоритетов | consistency | №09 |
| autopay.combo.unit_change-limit_per_hour+drop_promised-no_409_status |  | major | event_conflict | Не определено, по какому времени пополнение относится к суткам и часу | lens:analyst | №05 |
| autopay.combo.unit_change-limit_per_hour+drop_promised-no_409_status |  | major | contradiction | Цель обещает неснижение баланса ниже порога, требования этого не гарантируют | consistency | №09 |
| autopay.combo.unit_change-limit_per_hour+drop_promised-no_409_status |  | minor | terminology | Отключение и удаление настройки названы разными терминами без определения | consistency | №09 |
| autopay.combo.unit_change-limit_per_hour+drop_promised-no_409_status |  | major | unverifiable | НФ-1: не заданы начало и конец измерения срока 5 минут | lens:qa | №06 |
| autopay.combo.unit_change-limit_per_hour+drop_promised-no_409_status |  | major | incomplete | Не описано, сохраняется ли счётчик лимита после удаления и повторного создания | consistency | №09 |
| autopay.drop_promised.no_409_status |  | minor | terminology | Одни понятия названы по-разному, глоссарий не описывает их | consistency | №09 |
| autopay.drop_promised.no_409_status |  | minor | incomplete | Функциональные и нефункциональные требования без приоритетов | consistency | №09 |
| autopay.drop_promised.no_409_status |  | minor | incomplete | Не описаны гонка уведомления и удаления и повторное создание настройки | consistency | №09 |
| autopay.drop_promised.no_409_status |  | major | ambiguity | Не определено, с какой карты списывать при подключении одного номера двумя картами | lens:risk | №08 |
| autopay.drop_promised.no_409_status |  | major | incomplete | Не сказано, входит ли неуспешная попытка в лимит трёх пополнений за сутки | consistency | №09 |
| autopay.drop_promised.no_409_status |  | minor | missing_element | Критерии приёмки не покрывают границы, повтор события и отключение | lens:qa | №06 |
| autopay.drop_promised.no_409_status |  | major | contradiction | Цель гарантирует порог баланса, который требования не обеспечивают | consistency | №09 |
| autopay.event_conflict.insufficient_funds_credit |  | minor | terminology | Исполнитель пополнения назван «Приложение» и «банк» | consistency | №09 |
| autopay.event_conflict.insufficient_funds_credit |  | minor | missing_element | Функциональным и нефункциональным требованиям не назначены приоритеты | consistency | №09 |
| autopay.event_conflict.insufficient_funds_credit |  | major | ambiguity | Не определено, входят ли отказы по средствам в лимит трёх пополнений в сутки | consistency | №09 |
| autopay.event_conflict.insufficient_funds_credit |  | minor | terminology | Оператор связи и настройка автопополнения названы разными терминами, глоссария нет | consistency | №09 |
| autopay.event_conflict.insufficient_funds_credit |  | minor | incomplete | Приёмка не покрывает границы, повтор события, отключение и коды 401/404/409 | lens:qa | №06 |
| autopay.event_conflict.insufficient_funds_credit |  | major | ambiguity | Момент отключения относительно пополнения в окне до 5 минут не определён | lens:risk, consistency | №08, №09 |
| autopay.range_boundary.trigger_at_threshold |  | minor | other | Требования не имеют приоритетов и идентификаторов пунктов | consistency | №09 |
| autopay.range_boundary.trigger_at_threshold |  | minor | terminology | Понятие «настройка автопополнения» названо по-разному, в терминах нет | consistency | №09 |
| autopay.range_boundary.trigger_at_threshold |  | minor | incomplete | Критерии приёмки не покрывают границы, отключение, повтор и коды ошибок | lens:qa | №06 |
| autopay.range_boundary.trigger_at_threshold |  | major | terminology | Исполнитель операций назван тремя разными словами в разных местах | consistency | №09 |
| autopay.range_boundary.trigger_at_threshold |  | major | incomplete | Требование карты KZT не проверяется в логике createAutopay и не имеет кода | lens:architect | №07 |
| autopay.range_boundary.trigger_at_threshold |  | major | contradiction | Цель «баланс не ниже порога» нарушается отказами по лимиту и средствам | consistency | №09 |
| autopay.range_boundary.trigger_at_threshold |  | minor | missing_element | Время пополнения и идентификатор события хранятся, но не возвращаются | consistency | №09 |
| autopay.range_boundary.trigger_at_threshold |  | major | incomplete | Лимит АП-5 считается по номеру, проверка 409 — по карте | consistency | №09 |
| autopay.two_statuses.range_422 |  | major | unverifiable | НФ-1: не заданы конец отсчёта и период измерения доли 99 % | lens:qa | №06 |
| autopay.two_statuses.range_422 |  | minor | terminology | Одни понятия названы разными терминами, глоссария нет | consistency | №09 |
| autopay.two_statuses.range_422 |  | minor | missing_element | Функциональные требования АП-1…АП-7 не имеют приоритетов | consistency | №09 |
| autopay.two_statuses.range_422 |  | major | contradiction | Цель обещает баланс не ниже порога, требования АП-6 и НФ-1 этого не гарантируют | consistency | №09 |
| autopay.two_statuses.range_422 |  | major | ambiguity | Пополнение, начатое до отключения: АП-7 и срок НФ-1 не согласованы | lens:risk | №08 |
| autopay.two_statuses.range_422 |  | major | missing_element | Тело успешного ответа createAutopay не описано, хотя таблица на него ссылается | lens:architect | №07 |
| autopay.two_statuses.range_422 |  | minor | missing_element | Изменение порога или суммы без удаления настройки не описано | consistency | №09 |
| autopay.two_statuses.range_422 |  | minor | missing_element | Критерии приёмки не покрывают границы, повтор, отключение и 409 | lens:qa | №06 |
| autopay.two_statuses.range_422 |  | major | ambiguity | Отнесение пополнения к суткам лимита: по уведомлению или по проведению | consistency | №09 |
| autopay.unit_change.limit_per_hour |  | minor | traceability | Пункты требований, шаги логики и коды без ID и трассировки | consistency | №09 |
| autopay.unit_change.limit_per_hour |  | minor | incomplete | Документ не рассматривает ряд случаев | lens:qa, lens:risk, consistency | №06, №08, №09 |
| autopay.unit_change.limit_per_hour |  | critical | contradiction | Лимит часа (АП-5) и лимит суток (строка приёмки 47) дают разный исход для одного входа | lens:qa, lens:analyst, lens:architect, consistency, rules:units.period_mix | №05, №06, №07, №09, №12 |
| autopay.unit_change.limit_per_hour |  | major | contradiction | Цель гарантирует отсутствие просадки баланса, требования этого не обеспечивают | consistency | №09 |
| autopay.unit_change.limit_per_hour |  | minor | other | Требования не ранжированы по приоритету | consistency | №09 |
| autopay.unit_change.limit_per_hour |  | major | ambiguity | АП-1 не задаёт, допустимы ли две настройки одного номера с разными картами | consistency | №09 |
| autopay.unit_change.limit_per_hour |  | major | ambiguity | «Недостаточно средств» не определено: остаток по учёту или доступный остаток с холдами | lens:risk | №08 |
| autopay.unit_change.limit_per_hour |  | major | unverifiable | НФ-1: не задан период и выборка для показателя 99 % | lens:qa | №06 |
| autopay.unit_change.limit_per_hour |  | major | ambiguity | Порядок проверок createAutopay: 404 или 400 при двух ошибках одновременно | consistency | №09 |
| autopay.unit_change.limit_per_hour |  | major | missing_element | Проверка валюты карты KZT в createAutopay не описана | lens:architect | №07 |
| autopay.unit_change.limit_per_hour |  | minor | terminology | Одни понятия названы по-разному, глоссария нет | consistency | №09 |
| cardblock.combo.unit_change-blocked_at_utc+two_statuses-reblock_200 |  | major | incomplete | Проведение авторизации, одобренной до блокировки, не описано | lens:risk | №08 |
| cardblock.combo.unit_change-blocked_at_utc+two_statuses-reblock_200 |  | minor | other | Пункты БК-1…БК-7 не имеют приоритета; ID и приоритеты отсутствуют | consistency | №09 |
| cardblock.combo.unit_change-blocked_at_utc+two_statuses-reblock_200 |  | minor | missing_element | Критерии приёмки покрывают три случая: нет границ days, разблокировки, кодов 400–500 | lens:qa | №06 |
| cardblock.combo.unit_change-blocked_at_utc+two_statuses-reblock_200 |  | major | ambiguity | «Сутки» срока блокировки: не определён момент начала и возврата в ACTIVE | lens:risk | №08 |
| cardblock.drop_promised.no_last_digits |  | major | api_contract | Срок бессрочной блокировки в ответе getCardStatus не описан | lens:architect | №07 |
| cardblock.drop_promised.no_last_digits |  | minor | incomplete | Критерии приёмки покрывают три сценария из многих правил | lens:qa | №06 |
| cardblock.drop_promised.no_last_digits |  | major | incomplete | Авторизация в окне 10 секунд между ответом 200 и блокировкой не отнесена | consistency | №09 |
| cardblock.drop_promised.no_last_digits |  | minor | other | Приоритет и идентификаторы требований не указаны ни у одного пункта | consistency | №09 |
| cardblock.drop_promised.no_last_digits |  | major | ambiguity | Момент окончания срока блокировки не определён: сутки календарные или 24-часовые | consistency | №09 |
| cardblock.drop_promised.no_last_digits |  | major | ambiguity | Цель «временная блокировка» не покрывает бессрочную блокировку из БК-2 | consistency | №09 |
| cardblock.drop_promised.no_last_digits |  | minor | terminology | Канал клиента назван «Приложение» и «Мобильный банк» | consistency | №09 |
| cardblock.drop_promised.no_last_digits |  | minor | ambiguity | «Доступна» в БК-6 допускает ответ 200 при повторной разблокировке ACTIVE | consistency | №09 |
| cardblock.event_conflict.unblock_daily_limit |  | major | incomplete | unblockCard: отказ при разблокировке чаще раза в сутки не имеет кода ответа | lens:architect, consistency | №07, №09 |
| cardblock.event_conflict.unblock_daily_limit |  | minor | ops_risk | После ответа 500 на blockCard не определено, применилась ли блокировка; повтор даст 409 бе | lens:risk | №08 |
| cardblock.event_conflict.unblock_daily_limit |  | major | incomplete | Значение days в ответе getCardStatus для бессрочной блокировки не описано (п.1 и ответ) | consistency | №09 |
| cardblock.event_conflict.unblock_daily_limit |  | minor | other | Приоритеты БК-1…БК-8 не заданы | consistency | №09 |
| cardblock.event_conflict.unblock_daily_limit |  | minor | contradiction | Цель обещает временную блокировку, БК-2 разрешает бессрочную | consistency | №09 |
| cardblock.event_conflict.unblock_daily_limit |  | minor | ambiguity | Поле days в getCardStatus: неясно, исходный срок или остаток | lens:architect | №07 |
| cardblock.event_conflict.unblock_daily_limit |  | major | missing_element | Приёмка не покрывает граничные, негативные и служебные ветки | lens:qa | №06 |
| cardblock.event_conflict.unblock_daily_limit |  | major | missing_element | Push-уведомление БК-7 обещано, но не описано в части B | consistency | №09 |
| cardblock.event_conflict.unblock_daily_limit |  | major | incomplete | Досрочная разблокировка и срок блокировки не согласованы | consistency | №09 |
| cardblock.event_conflict.unblock_daily_limit |  | major | missing_element | Для проверки БК-8 не хранится время последней разблокировки | lens:architect | №07 |

Пропуски:

| Кейс | Тип дефекта | Близкая находка (не засчитана) | Владельцы |
| :--- | :--- | :--- | :--- |
| autopay.unit_change.limit_per_hour | unit_mismatch | D-01 Лимит часа (АП-5) и лимит суток (строка приёмки 47) дают раз (lens:qa, lens:analyst, lens:architect, consistency, rules:units.period_mix) | №09, №12 |

| Кейс | Ожидание | Статус | Замечаний (к/с/н) | Вердикт |
| :--- | :--- | :--- | :--- | :--- |
| autopay.base | clean | complete | 10 (0/6/4) | conditional/yes |
| autopay.combo.unit_change-limit_per_hour+drop_promised-no_409_status | defects | complete | 9 (1/5/3) | no/no |
| autopay.drop_promised.no_409_status | defects | complete | 8 (0/4/4) | yes/conditional |
| autopay.event_conflict.insufficient_funds_credit | defects | complete | 7 (1/2/4) | no/no |
| autopay.paraphrase.nfr | clean | complete | 8 (0/5/3) | conditional/conditional |
| autopay.range_boundary.trigger_at_threshold | defects | complete | 9 (1/4/4) | no/no |
| autopay.two_statuses.range_422 | defects | complete | 10 (0/6/4) | conditional/conditional |
| autopay.unit_change.limit_per_hour | defects | complete | 11 (1/6/4) | no/no |
| cardblock.base | clean | complete | 6 (0/3/3) | yes/conditional |
| cardblock.combo.unit_change-blocked_at_utc+two_statuses-reblock_200 | defects | complete | 6 (1/3/2) | no/no |
| cardblock.drop_promised.no_last_digits | defects | complete | 9 (0/5/4) | conditional/conditional |
| cardblock.event_conflict.unblock_daily_limit | defects | partial | 12 (1/7/4) | no/no |
| cardblock.paraphrase.keep_authorizations | clean | partial | 7 (0/4/3) | conditional/conditional |
| cardblock.range_boundary.days_400_at_30 | defects | failed | 1 (0/1/0) | none/none |
| cardblock.two_statuses.reblock_200 | defects | failed | 1 (0/1/0) | none/none |
| cardblock.unit_change.blocked_at_utc | defects | failed | 1 (0/1/0) | none/none |
| cashback.base | clean | failed | 0 (0/0/0) | none/none |
| cashback.combo.event_conflict-category_effective_now+range_boundary-cap_strict | defects | failed | 2 (0/2/0) | none/none |
| cashback.drop_promised.no_read_method | defects | failed | 1 (1/0/0) | none/none |
| cashback.event_conflict.category_effective_now | defects | failed | 1 (0/1/0) | none/none |
| cashback.paraphrase.rate | clean | failed | 0 (0/0/0) | none/none |
| cashback.range_boundary.cap_strict | defects | failed | 1 (0/1/0) | none/none |
| cashback.two_statuses.bad_category_200 | defects | failed | 1 (0/1/0) | none/none |
| cashback.unit_change.accrued_in_tiyn | defects | failed | 1 (0/1/0) | none/none |
| edge.empty | clean | failed | 0 (0/0/0) | none/none |
| transfer_limit.base | clean | failed | 0 (0/0/0) | none/none |
| transfer_limit.combo.two_statuses-range_200_error+drop_promised-no_read_method | defects | failed | 2 (1/1/0) | none/none |
| transfer_limit.drop_promised.no_read_method | defects | failed | 1 (1/0/0) | none/none |
| transfer_limit.event_conflict.cancel_no_restore | defects | failed | 1 (0/1/0) | none/none |
| transfer_limit.paraphrase.new_limit | clean | failed | 0 (0/0/0) | none/none |
| transfer_limit.range_boundary.reaching_rejects | defects | failed | 1 (0/1/0) | none/none |
| transfer_limit.two_statuses.range_200_error | defects | failed | 1 (0/1/0) | none/none |
| transfer_limit.unit_change.api_limit_in_tiyn | defects | failed | 1 (0/1/0) | none/none |
