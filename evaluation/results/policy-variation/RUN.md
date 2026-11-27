# Запуск закрытой панели PV-1

Max, для передачи результата нужны SHA кандидата, точная команда и автоматически полученные отчёты. По официальному банковскому кейсу в релизе указан Anthropic. Закрытые восемь документов предусмотрены для отдельного сравнения с Gemini на сборке `8e8e95f`. Для №16 остаётся доступным [формат JSONL](../../protocol/FORMAT.md). [Официальный запуск Max](https://github.com/diiaanns07-droid/winnersOFbankCCbyMNU/blob/08d3af55446ef37d8d61d077848e63c292a47207/release/reports/live/README.md)

После согласования бюджета исполнитель получает `PV1-eight-inputs.zip`. Ниже команды PowerShell из корня checkout этой ветки. Архив лежит рядом. Ключ Gemini исполнитель задаёт в своём окружении. Процессы используют чистый checkout продукта, штатный адаптер и фиксированную модель запроса. Одна попытка допускает до 12 обращений и 180 секунд на документ, до 96 обращений на панель. Это технический потолок. Он не является выделенным бюджетом.

```powershell
git fetch origin bcc/integration
git worktree add --detach ../pv-product-8e8e95f 8e8e95f4bb8a65bdd10d7e4599dd4747ffe8c803
py -3.12 -m venv ../pv-venv
$py = (Resolve-Path ../pv-venv/Scripts/python.exe).Path
& $py -m pip install -e "../pv-product-8e8e95f[all]"
Expand-Archive ./PV1-eight-inputs.zip ../pv-inputs
& $py evaluation/protocol/run.py --product ../pv-product-8e8e95f --input-pack ../pv-inputs --input-seal evaluation/protocol/policy-variation/8e8e95f/live.seal.json --out ../pv-gemini-return --mode rules_plus_llm --suite panel
```

Исполнитель передаёт хранителю каталог `pv-gemini-return` через согласованный канал. В нём должны быть исходные `execution.json`, `completed.json`, `measurements.jsonl`, `reports/<ID>-md/report.md`, `report.json` и `wire.jsonl`. Лог транспорта фиксирует код HTTP и фактическую версию модели из ответа. Восемь соответствующих офлайн-паспортов уже собраны из основной формы. Отдельный повтор в том же режиме записывается в новый каталог.

Хранитель распаковывает собственный архив в `../pv-private`. Расчёт выполняется из корня ветки оценки.

```powershell
git worktree add --detach ../pv-scorer-a79a47d a79a47d887bf5265c946019c004ca8d3e4f2b988
& $py evaluation/protocol/policy-variation/score.py --product ../pv-product-8e8e95f --scorer ../pv-scorer-a79a47d --inputs ../pv-private/inputs/live --gold ../pv-private/reference/live.labels.jsonl --reports ../pv-gemini-return --out ../pv-score-live --presentation live --mode rules_plus_llm --input-seal evaluation/protocol/policy-variation/8e8e95f/live.seal.json
```

По каждому совпавшему ID проверяются источник, SHA агента, фактическая модель из успешного ответа, отсутствие кэша и статус. Затем применяются критерии смысла и дублей исходного протокола. Хранитель записывает свои решения в отдельный файл и сохраняет исходный отчёт. Паспорта failed показываются как пропуски измерения.
