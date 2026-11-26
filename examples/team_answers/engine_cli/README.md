# Штатный путь `--answers`: экспорт №13 → CLI → файл редакции

Пара входов и выходов для №09 (сравнение версий) и №18 (выпуск). Всё запускается без
ключа: модель имитирует mock-провайдер движка.

## Входы (`tests/p08/fixtures/`)

| Файл | Что это |
| :--- | :--- |
| `transfer_tz.md` | короткое ТЗ «Перевод между своими счетами», SHA-256 `21286a1f…c3eb`. В нём два независимых разногласия: комиссия (ПС-1 ↔ «Тарифы») и исполнение после 18:00 (ПС-2 ↔ критерий приёмки) |
| `mock_transfer.json` | сценарий модели для первого прогона: оба конфликта (`cross`), критик всё подтверждает, `clarify` даёт варианты с правками |
| `mock_transfer_after.json` | сценарий модели для второго прогона: на редакции остаётся только конфликт о комиссии |
| `answers13_Q01_A.md` | ответ владельца ровно в формате экспорта №13 (`format: bcc-review-answers/1`). Сгенерирован кодом №13 `exports/html.py:answers_markdown` @ `540c310` по отчёту первого прогона. Выбор один: `Q-01 → A` |
| `answers13_collision.md` | Q-01 = A, Q-02 правит ту же ячейку, Q-03 — независимая правка |
| `answers13_other_sha.md` | тот же ответ, но с `source_sha256` из нулей |

## Команды (из корня репозитория)

Этап набора идёт через резерв Max `llm_stages:review_set`: сценарий командного №06
(`cross.pairs`) — отдельная тема. Переменную задаёт сам штатный CLI-переключатель
движка:

```bash
export BCC_FORCE_FALLBACK=review_set
```

```bash
python -m bcc_review tests/p08/fixtures/transfer_tz.md out/r1.md --provider mock --mock-script tests/p08/fixtures/mock_transfer.json --no-cache --run-id p08-transfer-r1
```

```bash
python -m bcc_review tests/p08/fixtures/transfer_tz.md out/r2.md --provider mock --mock-script tests/p08/fixtures/mock_transfer_after.json --no-cache --run-id p08-transfer-r2 --answers tests/p08/fixtures/answers13_Q01_A.md --compare out/r1.json
```

```bash
diff tests/p08/fixtures/transfer_tz.md out/transfer_tz.rev-p08-transfer-r2.md
```

Ожидаемый результат:

* `out/transfer_tz.rev-p08-transfer-r2.md`, SHA-256 `a09da5508614c94a366e37bfc2b72831801b4dbab417153b62ccd9cd2706a839`, байт-в-байт равен файлу в этой папке;
* исходник не меняется: `21286a1fb07ef65c640dcc181bcdf19e04ccc6c9c726a510b6a5341601a9c3eb`;
* `diff` показывает одну строку — `agreed_edit.diff`:

```diff
-| Перевод 10 000 ₸ создан в 19:00 в пятницу | Исполнить перевод | Перевод исполнен в пятницу |
+| Перевод 10 000 ₸ создан в 19:00 в пятницу | Исполнить перевод | Перевод исполнен в следующий рабочий день |
```

* в `out/r2.json`: `document.id` = `run.source_sha256` = SHA редакции,
  `run.revision_of` = SHA исходника, `run.source_name` = имя файла редакции.
  Второй прогон читает именно записанный файл;
* `decisions[0]`: `answer: "A"`, `decision_status: "accepted"`, правка `b0009 [64:90]`.
  «Внесено, ожидает проверки» записано в манифесте `*.revision.json`: там
  `status: "applied_not_verified"` и SHA редакции. Движок `@2821989` снимает решение
  до `propose_patch` и оставляет у правок только поля контракта;
* `diff` (№09): `resolved` = F-002 (исполнение после 18:00); `persisting` = F-001
  (комиссия, независимый конфликт) и две `minor`.

Файлы `r1.*`, `r2.*`, редакция и её манифест в этой папке получены ровно этими командами в `out/`
и скопированы сюда. При повторе меняются только время прогона, длительности этапов и `agent_commit`;
файл редакции совпадает байт-в-байт (это проверяет тест).

## Что реально выполнилось

`run.modules` в `r2.json`:

| Слот | Реализация |
| :--- | :--- |
| `read_text` | `team:bcc_review.readers.text` (№01) |
| `build_inventory`, `review_individual`, `resolve_*`, `reconcile_facts`, `load_criteria` | командные модули №04, №05, №07 |
| `review_set` | **резерв** `fallback:…llm_stages:review_set` (принудительно) |
| `build_questions`, `parse_answers`, `propose_patch`, `write_revision` | `team:bcc_review.decisions.*` (№08) |
| `compare_reports`, `build_bank_pack` | резерв движка (№09, №10 ещё не влиты) |
| `provider` | `runtime.mock:MockAdapter`, транспорт — подставные ответы, сеть не используется |

## Отказы (тест `tests/p08/test_engine_answers.py`)

* **Повторный прогон на созданной редакции с тем же ответом** → этап `answers` =
  `partial`, предупреждение «ответы относятся к другой редакции
  (source_sha256 21286a1fb07e…, документ a09da5508614…): правки не применены».
  Новых файлов нет, анализируется сама редакция.
* **Другой SHA** (`answers13_other_sha.md`) → то же предупреждение; исходник не
  изменён, файлов редакции нет.
* **Две правки одного диапазона** (`answers13_collision.md`) → Q-01 и Q-02
  получают `patch_state: "collision"` и пустые `edits`, в `note` — обе правки и место:
  «Правки Q-01 и Q-02 меняют пересекающиеся фрагменты (строка 16 · блок b0009 …)».
  Независимая Q-03 применена; в редакции изменена только строка 6, строка 16 не
  тронута.

## Diff для Max (`max_engine_apply_answers.diff`)

Для Markdown/TXT он не нужен — путь выше работает на текущем движке `bcc/integration` @ `2821989`.

Для PDF/DOCX нужен. Писатель №08 пишет явную текстовую редакцию `*.rev-….md` и
возвращает её путь, а `engine.apply_answers` возвращаемое значение игнорирует и
читает `*.rev-….pdf` → `FileNotFoundError`. Diff:

1. читает редакцию по пути, который вернул писатель (`_call_flex` возвращает его);
2. ловит `ValueError` писателя (`PatchError` №08 и ошибки резерва — его
   наследники): предупреждение и анализ исходника вместо трассировки.

Проверка — `test_max_engine_diff_reads_revision_path_returned_by_writer`. Он
накладывает diff на копию `src/` через `git apply`, а после слияния у Max
проверяет уже сам движок.

```bash
git apply examples/team_answers/engine_cli/max_engine_apply_answers.diff
```
