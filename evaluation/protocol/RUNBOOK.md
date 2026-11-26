# Передача хранителю, Max и №18

Для официальной сборки Max `8e8e95f` используются [команда и квитанция от 27 ноября](../results/ie-release/README.md#передача-исполнителю). Ниже воспроизводится прежняя сборка `f91d3b6`. В первой операторской упаковке поле `stratum` раскрывало тип проверки. Для передачи исполнителю подготовлена версия 2 с нейтральными именами, без типов и ролей. Ранее опубликованные хеши исходников позволяют сопоставить документы с разбором. Эта шестёрка служит для повторного сравнения.

Замороженный продукт — `f91d3b6f485e883d316c94fc5e032f1a8d6c2553`. Командный комплект релиза на `bcc/integration@2821989` ссылается на этот SHA. В исходных ветках №18 указан как владелец исполнения. Опубликованного согласия на определённую квоту и отдельной удалённой ветки №18 при проверке не было. Для оценки выбрана встроенная резервная реализация Gemini того же релиза. Основной конструктор версии f91d3b6 не подхватывает ключ из окружения. Оба режима закреплены за одним checkout. [Запись Max](../../contracts/HANDOFF.md) · [Комплект релиза](../../release/README.md)

## Подготовка

PowerShell, из корня публичной ветки bcc/eval-independent. Для владельца модели подготовлен архив IE-six-inputs-v2.zip. В нём шесть MD и нейтральный манифест. Ответы и исходные суждения остаются у хранителя. Папки с результатами должны быть новыми для каждой попытки. Продуктовый checkout остаётся чистым. При первой установке используйте Python 3.11 или новее.

```powershell
git fetch origin
git worktree add --detach ../product-f91d3b6 f91d3b6f485e883d316c94fc5e032f1a8d6c2553
py -3.12 -m venv ../ie-venv
$py = (Resolve-Path ../ie-venv/Scripts/python.exe).Path
& $py -m pip install -e '../product-f91d3b6[pdf,docx,gemini]'
Expand-Archive -LiteralPath ../IE-six-inputs-v2.zip -DestinationPath ../ie-inputs
```

## №18 и владелец ключа

Выполнять после подтверждения командного бюджета. На стороне владельца GEMINI_API_KEY уже задан в окружении. В командной строке выше и в артефактах его значение отсутствует. Фиксированный режим использует gemini-2.5-flash, temperature 0, кэш выключен, до 12 учтённых вызовов на один документ, до 180 с и без повторов движка. Во встроенном адаптере есть один дополнительный HTTP-запрос при несовместимости поля схемы. Шесть входов допускают до 72 вызовов счётчика и не более 144 отправок на транспорт. Это верхние границы плана. Фактические значения берутся из файлов исполнения. Доступность модели и разрешённую квоту проверяет владелец своей учётной записи.

```powershell
& $py evaluation/protocol/run.py --product ../product-f91d3b6 --input-pack ../ie-inputs --input-seal evaluation/protocol/ie-release/operator-f91d3b6.json --out ../gemini-return-01 --mode rules_plus_llm --suite panel
```

Передать хранителю весь каталог gemini-return-01 с execution.json, measurements.jsonl, predictions.jsonl, reports и completed.json, если прогон дошёл до конца. Для каждого case_id сохраняются исходный report.json, report.md, трасса, stdout/stderr, verify и wire.jsonl. В wire.jsonl пишутся только HTTP-статус и фактический modelVersion ответа. Если часть попыток сорвалась, вернуть имеющиеся файлы и сохранить причину. Один плановый случай без результата остаётся пропуском измерения. Передача ответов внешней модели выполняется только на синтетических входных ТЗ.

## Хранитель

Распакуйте закрытый комплект в ../ie-vault. В корне должны находиться corpus, sealed-files.json и offline. Проверка возврата сверяет байты входов, отчётов, режим и SHA агента, проверяет ссылки и реальное имя модели, после чего заново строит предсказания по исходным отчётам.

```powershell
& $py evaluation/protocol/score_return.py --product ../product-f91d3b6 --vault ../ie-vault --returned ../gemini-return-01 --operator-manifest ../ie-inputs/panel.manifest.json --operator-seal evaluation/protocol/ie-release/operator-f91d3b6.json --out ../gemini-score-01 --mode rules_plus_llm
& $py -m evaluation.harness compare --metrics rules_only=../ie-vault/offline/panel/confirmed.json --metrics rules_plus_llm=../gemini-score-01/confirmed.json --out ../paired-comparison.md
```

Проверить фактический охват обоих режимов. При разном составе завершённых документов отдельно вычислить парные результаты на пересечении и показать все пропуски. Отсутствие полного ответа на все шесть не даёт основания подставлять нули в пустую строку Gemini. Для реальных карточек перепроверить смысл кандидатов TP, применить правила вопросов, заполнить реестр разбора и независимую человеческую колонку при наличии рецензента.

Оценку по вторичному эталону 1.1 хранитель считает отдельной командой на тех же полученных предсказаниях. Первичное число по исходному эталону остаётся в confirmed.json.

```powershell
& $py -m evaluation.harness --gold ../ie-vault/amendment-1.1/panel.labels.jsonl --manifest ../ie-vault/corpus/panel.manifest.json --pred ../gemini-score-01/predictions.jsonl --render-format md --status confirmed --out ../gemini-score-01/confirmed-1.1.json
```

Хеш новой операторской упаковки приведён в [квитанции v2](ie-release/operator-f91d3b6.json). Контрольная сумма исходного архива хранителя указана в [квитанции v1](../results/delivery.json).

Повторить доступное офлайн-испытание на всём исходном наборе:

```powershell
& $py evaluation/protocol/run.py --product ../product-f91d3b6 --vault ../ie-vault --out ../ie-offline-repeat --mode rules_only --suite all
```

Проверить передачу без ключа можно с тем же входным архивом и `--mode rules_only --suite panel`. Такой возврат и его независимый повторный подсчёт проверены на 6/6 документах. Для полностью воспроизводимого выбора примеров используется исходный набор predictions без модификаций. Хеш журнала разметки после разбора сохранён рядом с первичным в [итогах](../results/summary.json).
