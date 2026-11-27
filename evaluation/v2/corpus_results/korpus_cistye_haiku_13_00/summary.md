# Корпус evaluation/dev — корпус чистые, haiku 13:00

Кейсов 8 (не запускались 25), не измерено 0 (пропусков в счётчике 0).

| TP | FP | FN | Дубли | Precision | Recall | F1 |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0 | 55 | 0 | 0 | 0.000 | — | 0.000 |

Чистые документы (8/8 измерено): замечаний 55, critical 1, major 25; документов с critical 1, с > 1 major 7, вердикт «нельзя» 1; документов с > 1 замечанием 8, максимум на одном 9. Ложных тревог по счётчику: 55.

Recall по типам: .

Время 17.2 мин суммарно, вызовов 67, $0.434.

Вклад источников (замечание с несколькими источниками считается каждому):

| Источник | TP | FP | из них на чистых |
| :--- | ---: | ---: | ---: |
| consistency (№09) | 0 | 40 | 40 |
| lens:analyst (№05) | 0 | 1 | 1 |
| lens:architect (№07) | 0 | 2 | 2 |
| lens:qa (№06) | 0 | 11 | 11 |
| lens:risk (№08) | 0 | 2 | 2 |

Ложные находки:

| Кейс | Чистый | Серьёзность | Тип | Замечание | Источники | Владельцы |
| :--- | :---: | :--- | :--- | :--- | :--- | :--- |
| autopay.base | да | major | api_contract | Тело ответа 200 для createAutopay не описано, хотя таблица ссылается на раздел метода | lens:architect | №07 |
| autopay.base | да | major | ambiguity | Отказ по нехватке средств: входит ли он в лимит трёх пополнений в сутки | consistency | №09 |
| autopay.base | да | minor | other | Функциональные и нефункциональные требования без приоритета | consistency | №09 |
| autopay.base | да | major | ambiguity | Повтор уведомления после отказа по средствам: выполнится ли пополнение | consistency | №09 |
| autopay.base | да | major | missing_element | Время пополнения и идентификатор события не выведены в ответах API | consistency | №09 |
| autopay.base | да | major | incomplete | Исход при списании без подтверждённого пополнения не определён | lens:risk | №08 |
| autopay.base | да | minor | incomplete | Критерии приёмки покрывают 3 из 11 функциональных требований | lens:qa | №06 |
| autopay.base | да | minor | terminology | Одни и те же понятия названы по-разному в разных разделах | consistency | №09 |
| autopay.paraphrase.nfr | да | minor | terminology | Одни и те же понятия названы в документе разными терминами | consistency | №09 |
| autopay.paraphrase.nfr | да | minor | incomplete | Функциональные требования АП-1…АП-7 не имеют приоритета | consistency | №09 |
| autopay.paraphrase.nfr | да | major | contradiction | Цель L017 «не опускается ниже порога» противоречит лимиту, нехватке средств и задержке | consistency | №09 |
| autopay.paraphrase.nfr | да | major | contradiction | Вторая настройка на ту же карту: АП-1 и п. 3 createAutopay дают разный исход | lens:analyst | №05 |
| autopay.paraphrase.nfr | да | minor | incomplete | Изменение порога или суммы активной настройки не описано | consistency | №09 |
| autopay.paraphrase.nfr | да | minor | missing_element | Критерии приёмки покрывают 3 из 11 функциональных требований | lens:qa | №06 |
| cardblock.base | да | major | incomplete | Тело ответа getCardStatus для бессрочной блокировки не описано | consistency | №09 |
| cardblock.base | да | major | incomplete | Возврат в ACTIVE по окончании срока не проверен приёмкой и не привязан к моменту отсчёта | consistency | №09 |
| cardblock.base | да | major | contradiction | Цель «временно блокирует» расходится с бессрочной блокировкой из БК-2 | consistency | №09 |
| cardblock.base | да | minor | terminology | Названия «Мобильный банк» и «Приложение» используются без пояснения связи | consistency | №09 |
| cardblock.base | да | minor | unverifiable | БК-5 не содержит условий замера для проверки под нагрузкой | lens:qa | №06 |
| cardblock.base | да | major | ambiguity | Авторизация, запрошенная до и одобренная после блокировки: поведение не определено | consistency | №09 |
| cardblock.base | да | minor | incomplete | Критерии приёмки не покрывают большинство функциональных требований и ветки ошибок | lens:qa | №06 |
| cardblock.base | да | minor | incomplete | Требования БК-1…БК-7 не имеют приоритетов и идентификаторов по документу | consistency | №09 |
| cardblock.paraphrase.keep_authorizations | да | minor | terminology | Одно действие клиента названо по-разному: клиент и приложение | consistency | №09 |
| cardblock.paraphrase.keep_authorizations | да | minor | other | Функциональные требования БК-1…БК-7 без приоритетов | consistency | №09 |
| cardblock.paraphrase.keep_authorizations | да | minor | unverifiable | Срок вступления блокировки в силу не измерим: нет доли событий и нагрузки | lens:qa | №06 |
| cardblock.paraphrase.keep_authorizations | да | major | contradiction | Цель задаёт временную блокировку, а БК-2 допускает бессрочную | consistency | №09 |
| cardblock.paraphrase.keep_authorizations | да | minor | missing_element | Критерии приёмки не покрывают границы, отказы и часть требований | lens:qa | №06 |
| cardblock.paraphrase.keep_authorizations | да | minor | incomplete | Возврат в ACTIVE по сроку не проверяется приёмкой и не привязан к старту | consistency | №09 |
| cardblock.paraphrase.keep_authorizations | да | major | incomplete | БК-2 допускает бессрочную блокировку, но ответ getCardStatus для неё не описан | consistency | №09 |
| cashback.base | да | minor | other | Требования не имеют ID, приоритетов и признака стабильности | consistency | №09 |
| cashback.base | да | major | ambiguity | Категория в ответе в месяце до вступления выбора в силу не определена | consistency | №09 |
| cashback.base | да | major | incomplete | Возврат больше следующего зачисления: перенос остатка удержания не описан | consistency | №09 |
| cashback.base | да | major | incomplete | Повторный выбор категории в одном месяце не описан | consistency | №09 |
| cashback.base | да | critical | contradiction | Возврат покупки вне выбранной категории: КБ-2 даёт 0 ₸, КБ-6 даёт −100 ₸ | lens:qa | №06 |
| cashback.base | да | minor | duplicate | Ставка 5 % повторена в правиле возврата отдельно от КБ-3 | consistency | №09 |
| cashback.base | да | minor | terminology | Сумма кэшбэка месяца названа тремя разными терминами | consistency | №09 |
| cashback.base | да | major | api_contract | Статус 200 saveCategory отсылает к описанию тела ответа, которого нет | consistency | №09 |
| cashback.base | да | minor | missing_element | Критерии приёмки не покрывают возвраты, зачисление 5-го числа и ошибки API | lens:qa | №06 |
| cashback.paraphrase.rate | да | major | missing_element | Ответ 200 saveCategory: раздел метода не описывает тело успешного ответа | consistency | №09 |
| cashback.paraphrase.rate | да | major | ambiguity | Повторный выбор категории в месяце: какой выбор действует и какой показывается | consistency | №09 |
| cashback.paraphrase.rate | да | minor | terminology | Один объект назван разными терминами; глоссария нет | consistency | №09 |
| cashback.paraphrase.rate | да | minor | missing_element | Критерии приёмки не покрывают часть функциональных требований и ошибок | lens:qa | №06 |
| cashback.paraphrase.rate | да | major | ambiguity | Модель данных: код категории не привязан ни к выбору клиента, ни к покупке | lens:architect | №07 |
| cashback.paraphrase.rate | да | major | ambiguity | Возврат: не определено, инициация или проведение процессингом считается возвратом | lens:risk | №08 |
| cashback.paraphrase.rate | да | major | ambiguity | Месяц покупки: дата операции или момент статуса процессинга не определены | consistency | №09 |
| cashback.paraphrase.rate | да | minor | incomplete | Функциональные требования КБ-1…КБ-7 без приоритета и признака первого релиза | consistency | №09 |
| transfer_limit.base | да | minor | missing_element | Критерии приёмки покрывают 3 из 6 функциональных требований | lens:qa, consistency | №06, №09 |
| transfer_limit.base | да | major | ambiguity | ЛП-5 и ЛП-6: неясно, какой лимит показывается до перевода после смены | consistency | №09 |
| transfer_limit.base | да | minor | incomplete | Функциональные требования ЛП-1…ЛП-6 без приоритета | consistency | №09 |
| transfer_limit.base | да | minor | terminology | Один продукт и одно понятие названы разными словами; глоссария нет | consistency | №09 |
| transfer_limit.paraphrase.new_limit | да | minor | terminology | Термины «Использовано» и «остаток» названы в документе по-разному | consistency | №09 |
| transfer_limit.paraphrase.new_limit | да | major | contradiction | Область учёта «Использовано»: по номеру телефона (L021) или по клиенту (L032) | consistency | №09 |
| transfer_limit.paraphrase.new_limit | да | major | api_contract | Тип поля limit: строка в ответе getTransferLimit и integer в запросе setTransferLimit | consistency | №09 |
| transfer_limit.paraphrase.new_limit | да | minor | missing_element | Приоритеты требований не указаны; раздел L023 без поля приоритета | consistency | №09 |
| transfer_limit.paraphrase.new_limit | да | minor | incomplete | Критерии приёмки покрывают 3 из 6 функциональных требований | lens:qa | №06 |

| Кейс | Ожидание | Статус | Замечаний (к/с/н) | Вердикт |
| :--- | :--- | :--- | :--- | :--- |
| autopay.base | clean | complete | 8 (0/5/3) | yes/conditional |
| autopay.paraphrase.nfr | clean | complete | 6 (0/2/4) | yes/yes |
| cardblock.base | clean | complete | 8 (0/4/4) | conditional/conditional |
| cardblock.paraphrase.keep_authorizations | clean | complete | 7 (0/2/5) | yes/yes |
| cashback.base | clean | complete | 9 (1/4/4) | no/no |
| cashback.paraphrase.rate | clean | complete | 8 (0/5/3) | conditional/conditional |
| transfer_limit.base | clean | complete | 4 (0/1/3) | yes/yes |
| transfer_limit.paraphrase.new_limit | clean | complete | 5 (0/2/3) | yes/yes |
