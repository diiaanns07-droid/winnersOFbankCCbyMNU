# Проверка тяжести на 12 исправленных ТЗ

Релизный код `3e7133c2`, свежий прогон Haiku 27 ноября. Вручную сопоставлены все critical и major с исходной редакцией каждого документа. Хеши SHA-256 двенадцати входов совпали с паспортами. Классификация F4 ниже — экспертная оценка. Цитаты, полный текст карточек и позиция агента доступны в отчётах.

Из двенадцати ТЗ на пяти агент запретил старт. В выписке обнаружено реальное противоречие о доступе к файлу. В четырёх других случаях изложенная критичная причина не обосновывает запрет всей работы. Метка корпуса описывает ожидаемый результат проверки. Для оценки точности нужна сверка со строками ТЗ.

Из 5 исходных critical экспертная оценка сохранила 1 critical, оставила 1 major и 2 minor, сняла 1. Из 37 исходных major сохранились 10, понижены до minor 12, сняты 15. На четырёх ТЗ без карточек этих уровней (`capital_v2`, `grace_v2`, `capital_clean`, `grace_clean`) такой разбор не потребовался.

### fx

[Исходное ТЗ](https://github.com/diiaanns07-droid/winnersOFbankCCbyMNU/blob/05306ab55f5d08b0306e62ae283277e527881202/evaluation/v2/clean/fx/source.md) · [Карточки агента](https://github.com/diiaanns07-droid/winnersOFbankCCbyMNU/blob/05306ab55f5d08b0306e62ae283277e527881202/evaluation/v2/measurements/reliz_w4_18_55_cistye_3e7133c_haiku/clean20/fx__clean/report.md)

| ID и уровень агента | Оценка | Строки ТЗ | Основание |
| --- | --- | --- | --- |
| D-01 critical | снять | [28, 41, 141, 178](https://github.com/diiaanns07-droid/winnersOFbankCCbyMNU/blob/05306ab55f5d08b0306e62ae283277e527881202/evaluation/v2/clean/fx/source.md#L28) | Экран запускает отображение при получении ответа. Ф-7 задаёт единую серверную границу, API возвращает expiresAt. |
| D-02 major | снять | [16, 56, 145](https://github.com/diiaanns07-droid/winnersOFbankCCbyMNU/blob/05306ab55f5d08b0306e62ae283277e527881202/evaluation/v2/clean/fx/source.md#L16) | ТЗ само фиксирует контракт уже существующих методов проводки и отмены. Из отсутствия доработки несовместимость не следует. |
| D-03 major | major | [43, 76, 135, 145](https://github.com/diiaanns07-droid/winnersOFbankCCbyMNU/blob/05306ab55f5d08b0306e62ae283277e527881202/evaluation/v2/clean/fx/source.md#L43) | Между первым запросом отмены и её подтверждением возможен повтор при активной котировке. Нужен проверяемый исход для временного повторного списания. Окончательная двойная проводка не доказана. |
| D-04 major | снять | [76, 145](https://github.com/diiaanns07-droid/winnersOFbankCCbyMNU/blob/05306ab55f5d08b0306e62ae283277e527881202/evaluation/v2/clean/fx/source.md#L76) | 500 выдаётся после отправки отмены, исходные остатки требуются после подтверждения. Оба пункта согласуются. |
| D-05 major | minor | [53, 145](https://github.com/diiaanns07-droid/winnersOFbankCCbyMNU/blob/05306ab55f5d08b0306e62ae283277e527881202/evaluation/v2/clean/fx/source.md#L53) | Условие окончания повторов задано. Полезно указать, когда оператора предупреждают о длительном ожидании. |
| D-06 major | снять | [56, 145](https://github.com/diiaanns07-droid/winnersOFbankCCbyMNU/blob/05306ab55f5d08b0306e62ae283277e527881202/evaluation/v2/clean/fx/source.md#L56) | И-2 именует результат отмены. Неполнота примера транспорта сама по себе не делает поведение неопределённым. |
| D-07 major | minor | [22, 53, 56](https://github.com/diiaanns07-droid/winnersOFbankCCbyMNU/blob/05306ab55f5d08b0306e62ae283277e527881202/evaluation/v2/clean/fx/source.md#L22) | Доля и источник данных АБС заданы. Для аналитика пригодилась бы ссылка на отчёт или способ выделить канал. |
| D-08 major | снять | [41, 88, 145](https://github.com/diiaanns07-droid/winnersOFbankCCbyMNU/blob/05306ab55f5d08b0306e62ae283277e527881202/evaluation/v2/clean/fx/source.md#L41) | Откат явно скрывает вход в меню. Документ уже задаёт срок котировки и завершение начатой проводки. |

### insurance_v2

[Исходное ТЗ](https://github.com/diiaanns07-droid/winnersOFbankCCbyMNU/blob/05306ab55f5d08b0306e62ae283277e527881202/evaluation/v2/clean/insurance_v2/source.md) · [Карточки агента](https://github.com/diiaanns07-droid/winnersOFbankCCbyMNU/blob/05306ab55f5d08b0306e62ae283277e527881202/evaluation/v2/measurements/reliz_w4_18_55_cistye_3e7133c_haiku/clean20/insurance_v2__clean/report.md)

| ID и уровень агента | Оценка | Строки ТЗ | Основание |
| --- | --- | --- | --- |
| D-01 critical | minor | [124, 131, 172](https://github.com/diiaanns07-droid/winnersOFbankCCbyMNU/blob/05306ab55f5d08b0306e62ae283277e527881202/evaluation/v2/clean/insurance_v2/source.md#L124) | Проверка подписания и код 409 явны. В правиле повтора полезно повторить область применения, чтобы его не читали как исключение. |
| D-02 major | major | [45, 54, 226](https://github.com/diiaanns07-droid/winnersOFbankCCbyMNU/blob/05306ab55f5d08b0306e62ae283277e527881202/evaluation/v2/clean/insurance_v2/source.md#L45) | Сервис должен получить номер у партнёра после выдачи. Спецификация описывает предварительную проверку и входящую команду от конвейера, но не обмен, который возвращает номер. |
| D-03 major | снять | [13, 111, 124](https://github.com/diiaanns07-droid/winnersOFbankCCbyMNU/blob/05306ab55f5d08b0306e62ae283277e527881202/evaluation/v2/clean/insurance_v2/source.md#L13) | Для действия определены сессия и принадлежность заявки. Разные слова для клиента на двух стадиях сами по себе не вводят вторую роль. |
| D-04 major | major | [29, 224, 225, 226](https://github.com/diiaanns07-droid/winnersOFbankCCbyMNU/blob/05306ab55f5d08b0306e62ae283277e527881202/evaluation/v2/clean/insurance_v2/source.md#L29) | Экран запрашивает состояние полиса. Для прекращённого договора значение status в публичном ответе GET не задано. |
| D-05 major | minor | [124, 132, 172, 175](https://github.com/diiaanns07-droid/winnersOFbankCCbyMNU/blob/05306ab55f5d08b0306e62ae283277e527881202/evaluation/v2/clean/insurance_v2/source.md#L124) | Два исключения явно снимают подключение. Для временного сбоя можно уточнить, что увидит клиент до повторной проверки. |
| D-06 major | снять | [169, 173, 184, 204](https://github.com/diiaanns07-droid/winnersOFbankCCbyMNU/blob/05306ab55f5d08b0306e62ae283277e527881202/evaluation/v2/clean/insurance_v2/source.md#L169) | У статусов перечислено несколько причин. Один пример для каждой группы не исключает остальные причины. |
| D-07 major | minor | [41, 68](https://github.com/diiaanns07-droid/winnersOFbankCCbyMNU/blob/05306ab55f5d08b0306e62ae283277e527881202/evaluation/v2/clean/insurance_v2/source.md#L41) | Бизнес-событие полного погашения названо. Для пограничного расчёта полезна ссылка на дату проведения в системе. |

### qr_v2

[Исходное ТЗ](https://github.com/diiaanns07-droid/winnersOFbankCCbyMNU/blob/05306ab55f5d08b0306e62ae283277e527881202/evaluation/v2/clean/qr_v2/source.md) · [Карточки агента](https://github.com/diiaanns07-droid/winnersOFbankCCbyMNU/blob/05306ab55f5d08b0306e62ae283277e527881202/evaluation/v2/measurements/reliz_w4_18_55_cistye_3e7133c_haiku/clean20/qr_v2__clean/report.md)

| ID и уровень агента | Оценка | Строки ТЗ | Основание |
| --- | --- | --- | --- |
| D-01 major | major | [25, 45, 139](https://github.com/diiaanns07-droid/winnersOFbankCCbyMNU/blob/05306ab55f5d08b0306e62ae283277e527881202/evaluation/v2/clean/qr_v2/source.md#L25) | Две схемы одного вызова ведут отправителя через разные сервисы. Владельцу интерфейса нужен согласованный маршрут. |

### repay

[Исходное ТЗ](https://github.com/diiaanns07-droid/winnersOFbankCCbyMNU/blob/05306ab55f5d08b0306e62ae283277e527881202/evaluation/v2/clean/repay/source.md) · [Карточки агента](https://github.com/diiaanns07-droid/winnersOFbankCCbyMNU/blob/05306ab55f5d08b0306e62ae283277e527881202/evaluation/v2/measurements/reliz_w4_18_55_cistye_3e7133c_haiku/clean20/repay__clean/report.md)

| ID и уровень агента | Оценка | Строки ТЗ | Основание |
| --- | --- | --- | --- |
| D-01 major | снять | [34, 50](https://github.com/diiaanns07-droid/winnersOFbankCCbyMNU/blob/05306ab55f5d08b0306e62ae283277e527881202/evaluation/v2/clean/repay/source.md#L34) | Расчёт выполняет специальный метод АБС. Мобильному сервису для этого не нужно получить дату выдачи через GET. |

### roundup

[Исходное ТЗ](https://github.com/diiaanns07-droid/winnersOFbankCCbyMNU/blob/05306ab55f5d08b0306e62ae283277e527881202/evaluation/v2/clean/roundup/source.md) · [Карточки агента](https://github.com/diiaanns07-droid/winnersOFbankCCbyMNU/blob/05306ab55f5d08b0306e62ae283277e527881202/evaluation/v2/measurements/reliz_w4_18_55_cistye_3e7133c_haiku/clean20/roundup__clean/report.md)

| ID и уровень агента | Оценка | Строки ТЗ | Основание |
| --- | --- | --- | --- |
| D-01 major | снять | [34, 134, 148](https://github.com/diiaanns07-droid/winnersOFbankCCbyMNU/blob/05306ab55f5d08b0306e62ae283277e527881202/evaluation/v2/clean/roundup/source.md#L34) | Принадлежность карты проверяется в процессинге. Документ не вводит второе право на настройку для дополнительной карты. |

### statement

[Исходное ТЗ](https://github.com/diiaanns07-droid/winnersOFbankCCbyMNU/blob/05306ab55f5d08b0306e62ae283277e527881202/evaluation/v2/clean/statement/source.md) · [Карточки агента](https://github.com/diiaanns07-droid/winnersOFbankCCbyMNU/blob/05306ab55f5d08b0306e62ae283277e527881202/evaluation/v2/measurements/reliz_w4_18_55_cistye_3e7133c_haiku/clean20/statement__clean/report.md)

| ID и уровень агента | Оценка | Строки ТЗ | Основание |
| --- | --- | --- | --- |
| D-01 critical | critical | [36, 79, 80](https://github.com/diiaanns07-droid/winnersOFbankCCbyMNU/blob/05306ab55f5d08b0306e62ae283277e527881202/evaluation/v2/clean/statement/source.md#L36) | В строке 79 fileExpiresAt равен 12:00, а приёмка требует выдать файл в 12:14. Ф-6 запрещает и выдачу ссылки в 12:00, и позднее скачивание. Проверка доступа получает два несовместимых результата. |
| D-02 major | снять | [36, 192, 198, 199](https://github.com/diiaanns07-droid/winnersOFbankCCbyMNU/blob/05306ab55f5d08b0306e62ae283277e527881202/evaluation/v2/clean/statement/source.md#L36) | Ссылка выдаётся через авторизованный метод, подпись и срок определены. Запрет такого способа авторизации в этом ТЗ не установлен. |
| D-03 major | minor | [20, 40, 146](https://github.com/diiaanns07-droid/winnersOFbankCCbyMNU/blob/05306ab55f5d08b0306e62ae283277e527881202/evaluation/v2/clean/statement/source.md#L20) | Подробный обмен READY/FAILED описан. Обзорная схема могла бы показывать обратное уведомление. |
| D-04 major | снять | [20, 40, 146](https://github.com/diiaanns07-droid/winnersOFbankCCbyMNU/blob/05306ab55f5d08b0306e62ae283277e527881202/evaluation/v2/clean/statement/source.md#L20) | Общее правило пропускает все вызовы приложения через шлюз. Внутренняя схема контроллера его не отменяет. |
| D-05 major | minor | [32, 141](https://github.com/diiaanns07-droid/winnersOFbankCCbyMNU/blob/05306ab55f5d08b0306e62ae283277e527881202/evaluation/v2/clean/statement/source.md#L32) | Сервисные часы и часовой пояс заданы. Можно уточнить обработку заказа, отправленного и полученного по разные стороны полуночи. |
| D-06 major | minor | [18](https://github.com/diiaanns07-droid/winnersOFbankCCbyMNU/blob/05306ab55f5d08b0306e62ae283277e527881202/evaluation/v2/clean/statement/source.md#L18) | База сравнения и период заданы. Стоит назвать владельца показателя и источник факта для отделений и контакт-центра. |

### insurance_clean

[Исходное ТЗ](https://github.com/diiaanns07-droid/winnersOFbankCCbyMNU/blob/05306ab55f5d08b0306e62ae283277e527881202/evaluation/v2/open2/insurance_clean/source.md) · [Карточки агента](https://github.com/diiaanns07-droid/winnersOFbankCCbyMNU/blob/05306ab55f5d08b0306e62ae283277e527881202/evaluation/v2/measurements/reliz_w4_18_55_cistye_3e7133c_haiku/clean_open2/insurance_clean__clean/report.md)

| ID и уровень агента | Оценка | Строки ТЗ | Основание |
| --- | --- | --- | --- |
| D-01 critical | major | [40, 41, 221](https://github.com/diiaanns07-droid/winnersOFbankCCbyMNU/blob/05306ab55f5d08b0306e62ae283277e527881202/evaluation/v2/open2/insurance_clean/source.md#L40) | API отказа не оговаривает уже прекращённый полис при погашении в первые 14 дней. Финансовое пересечение реально, из текста не следует обязательная двойная выплата. |
| D-02 major | major | [40, 41, 221, 223](https://github.com/diiaanns07-droid/winnersOFbankCCbyMNU/blob/05306ab55f5d08b0306e62ae283277e527881202/evaluation/v2/open2/insurance_clean/source.md#L40) | Метод сведений не определяет состояние после прекращения договора. Клиенту нельзя сформировать однозначную проверку ответа. |
| D-03 major | major | [25, 45](https://github.com/diiaanns07-droid/winnersOFbankCCbyMNU/blob/05306ab55f5d08b0306e62ae283277e527881202/evaluation/v2/open2/insurance_clean/source.md#L25) | Архитектура и последовательность называют разных отправителей запроса к страховому сервису. |
| D-04 major | major | [42, 123](https://github.com/diiaanns07-droid/winnersOFbankCCbyMNU/blob/05306ab55f5d08b0306e62ae283277e527881202/evaluation/v2/open2/insurance_clean/source.md#L42) | Правило требует нижнюю границу 18 лет, а алгоритм описывает только верхнюю. Исполнитель не может выбрать исход для 17-летнего клиента по одному методу. |
| D-05 major | major | [45, 54](https://github.com/diiaanns07-droid/winnersOFbankCCbyMNU/blob/05306ab55f5d08b0306e62ae283277e527881202/evaluation/v2/open2/insurance_clean/source.md#L45) | Для номера выданного полиса требуется ответ партнёра. В последовательности взаимодействий показана только предварительная проверка у партнёра. |
| D-06 major | снять | [34, 38, 125, 222](https://github.com/diiaanns07-droid/winnersOFbankCCbyMNU/blob/05306ab55f5d08b0306e62ae283277e527881202/evaluation/v2/open2/insurance_clean/source.md#L34) | До выдачи полис не выпускается и премия не оплачивается. Сам по себе отказ в выдаче не создаёт описанную карточкой потерю денег. |
| D-07 major | major | [38, 160](https://github.com/diiaanns07-droid/winnersOFbankCCbyMNU/blob/05306ab55f5d08b0306e62ae283277e527881202/evaluation/v2/open2/insurance_clean/source.md#L38) | Формула допускает дробную сумму, API возвращает целые тенге. Нужен один способ округления, иначе разойдутся ответы. |
| D-08 major | minor | [121, 128, 169](https://github.com/diiaanns07-droid/winnersOFbankCCbyMNU/blob/05306ab55f5d08b0306e62ae283277e527881202/evaluation/v2/open2/insurance_clean/source.md#L121) | У метода есть проверка подписания и ответ 409. Явная оговорка в правиле повтора упростит чтение. |
| D-09 major | снять | [166, 170, 181, 201](https://github.com/diiaanns07-droid/winnersOFbankCCbyMNU/blob/05306ab55f5d08b0306e62ae283277e527881202/evaluation/v2/open2/insurance_clean/source.md#L166) | Разрешены несколько причин для одного HTTP-кода. Один пример тела не является требованием использовать его текст для всех причин. |

### qr_clean

[Исходное ТЗ](https://github.com/diiaanns07-droid/winnersOFbankCCbyMNU/blob/05306ab55f5d08b0306e62ae283277e527881202/evaluation/v2/open2/qr_clean/source.md) · [Карточки агента](https://github.com/diiaanns07-droid/winnersOFbankCCbyMNU/blob/05306ab55f5d08b0306e62ae283277e527881202/evaluation/v2/measurements/reliz_w4_18_55_cistye_3e7133c_haiku/clean_open2/qr_clean__clean/report.md)

| ID и уровень агента | Оценка | Строки ТЗ | Основание |
| --- | --- | --- | --- |
| D-01 critical | minor | [113, 125, 176, 210, 211](https://github.com/diiaanns07-droid/winnersOFbankCCbyMNU/blob/05306ab55f5d08b0306e62ae283277e527881202/evaluation/v2/open2/qr_clean/source.md#L113) | У примера GET в строке 211 путь шаблонный, qrId в самом ответе отсутствует. Равенство двух экземпляров QR не доказано. Общий пример с указанным ID упростил бы приёмку. |
| D-02 major | снять | [29, 39, 45, 211](https://github.com/diiaanns07-droid/winnersOFbankCCbyMNU/blob/05306ab55f5d08b0306e62ae283277e527881202/evaluation/v2/open2/qr_clean/source.md#L29) | Отправитель должен прочитать маскированное имя и сумму из чужого QR. Владение кодом требуется для отмены, а не для экрана оплаты. |
| D-03 major | major | [25, 45, 136](https://github.com/diiaanns07-droid/winnersOFbankCCbyMNU/blob/05306ab55f5d08b0306e62ae283277e527881202/evaluation/v2/open2/qr_clean/source.md#L25) | Маршрут команды оплаты в последовательности и схеме API расходится. Это влияет на интеграционный тест. |
| D-04 major | minor | [38, 41, 51, 212](https://github.com/diiaanns07-droid/winnersOFbankCCbyMNU/blob/05306ab55f5d08b0306e62ae283277e527881202/evaluation/v2/open2/qr_clean/source.md#L38) | Условие запрета отмены уже определено. Для интеграции полезно назвать источник состояния перевода в обработке. |
| D-05 major | снять | [38, 51, 124, 131](https://github.com/diiaanns07-droid/winnersOFbankCCbyMNU/blob/05306ab55f5d08b0306e62ae283277e527881202/evaluation/v2/open2/qr_clean/source.md#L38) | Поле ttl хранит срок. Ф-2 и особое правило задают его значение в 15 минут. |
| D-06 major | снять | [38, 126, 127](https://github.com/diiaanns07-droid/winnersOFbankCCbyMNU/blob/05306ab55f5d08b0306e62ae283277e527881202/evaluation/v2/open2/qr_clean/source.md#L38) | Ф-2 прямо разрешает повтор после REJECTED. Алгоритм проверки уже оплаченного кода это правило не отменяет. |
| D-07 major | minor | [121, 126, 132](https://github.com/diiaanns07-droid/winnersOFbankCCbyMNU/blob/05306ab55f5d08b0306e62ae283277e527881202/evaluation/v2/open2/qr_clean/source.md#L121) | Идемпотентность задана. Порядок проверки ключа полезно уточнить при пересечении повтора и истечения срока. |
| D-08 major | minor | [28, 37](https://github.com/diiaanns07-droid/winnersOFbankCCbyMNU/blob/05306ab55f5d08b0306e62ae283277e527881202/evaluation/v2/open2/qr_clean/source.md#L28) | Пустое состояние экрана остаётся на усмотрение UX. Ограничение по типу карты определено. |
| D-09 major | minor | [38, 126](https://github.com/diiaanns07-droid/winnersOFbankCCbyMNU/blob/05306ab55f5d08b0306e62ae283277e527881202/evaluation/v2/open2/qr_clean/source.md#L38) | Однократность оплаты задана. Стоит добавить приёмку двух одновременных запросов и код для второго результата. |
