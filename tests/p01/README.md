# №01. Чтение Markdown и текста

Точка входа: `bcc_review.readers.text:read_text(path) -> Document` для `.md`, `.markdown` и `.txt`
(контракт v1, `bcc/integration` @ `431f76d`). Код: `src/bcc_review/readers/text.py`, тесты: `tests/p01/`.

```bash
python -m pytest tests/contract tests/p01
```

```bash
python -m bcc_review.readers.text tests/p01/fixtures/spec_ab.md
```

```bash
python -m bcc_review.readers.text tests/p01/fixtures/official_requirements.md --records
```

Пересборка образца для соседей (тест `test_sample_document_json_is_current` следит за актуальностью):

```bash
PYTHONPATH=src python -m bcc_review.readers.text tests/p01/fixtures/spec_ab.md > tests/p01/fixtures/sample_document.json
```

## Что выдаёт reader

| Поле | Значение |
| :--- | :--- |
| `Document.id` | SHA-256 исходных байтов, считается до декодирования |
| `format` | `markdown` или `text` |
| `source_name` | имя файла без каталога |
| `Block.id` | `b0001`, `b0002`… в порядке чтения; каждый блок начинается со своей строки |
| `kind` | `heading`, `paragraph`, `list_item`, `table_header`, `table_row`, `code`, `quote`, `other` |
| `section` | заголовки от корня; у заголовка путь из его родителей (как в примере контракта) |
| `text` | видимый текст без разметки Markdown |
| `warnings` | `{code, message, stage: "read", block_ids?}` |

### Разделители в `block.text`

* `"\n"` между физическими строками одного блока (абзац, пункт списка, код, цитата);
* `" | "` между ячейками строки таблицы. В каноническом GFM (`| a | b |`) он совпадает с исходником,
  и вся строка таблицы становится одним дословным отрезком;
* `<br>` превращается в `"\n"`, `&amp;` — в `&`.

Снимаются `#`, маркеры списков и `[ ]`, `**`, `*`, `_`, `~~`, обратные кавычки кода, `\`-экранирование,
крайние `|` и хвостовые пробелы жёсткого переноса. Тело fenced-блока и `кода` копируется дословно,
ничего не исполняется, `|` и `#` внутри не создают таблиц и заголовков.

### Поля `loc`

Строки нумеруются с 1, столбцы — кодовые точки Unicode с 0 внутри строки без окончания. Строку
завершает только CRLF, LF или CR; U+2028/U+2029/NEL/VT/FF её не завершают, поэтому номера совпадают
с GitHub и `grep -n`.

| Поле | Смысл |
| :--- | :--- |
| `line_start`, `line_end` | строки блока включительно, вместе с разметкой (ограждения кода, `\| --- \|` у заголовка таблицы) |
| `byte_start`, `byte_end` | `[начало line_start; конец содержимого line_end)` в байтах файла, BOM учтён; `null` при декодировании с заменой |
| `lines` | `[[строка, t0, t1]]`: какой отрезок `block.text` дала каждая строка |
| `map` | формат контракта `[[text_start, строка, столбец]]`: с `text_start` символы идут подряд с этой позиции |
| `spans` | точная форма той же карты `[[t0, t1, строка, c0, c1, "v"\|"s"]]`: `"v"` — `text[t0:t1] == строка[c0:c1]`, `"s"` — синтетический разделитель вместо `строка[c0:c1]` |
| `section_ids` | ID заголовков из `section` |
| `heading` | `level`, `style` (`atx`/`setext`), `section_end`, `empty` |
| `list_item` | `list = {id, ordered, marker, number, depth, item}`; у пункта чек-листа `- [ ]` ещё `checklist: true`, `checked` |
| `table_header` | `table = {index, columns, align, delimiter_line, line_end, rows}`, `cells` |
| `table_row` | `table = {index, header_id, columns}`, `row` (с 1), `cells = [{index, column, start, end}]`, `empty`, `template_choices` (ячейки вида «Да / Нет / Не требуется») |
| `code` | `fence = {marker, info, open_line, close_line, closed}` или `null` (отступ), `language` |
| `paragraph` | `parent` — ID пункта списка, если абзац его продолжает |
| `other` | `subtype`: `html_comment`, `front_matter` |
| ссылки | `links = [{start, end, url}]` |

### Восстановить строку и текст цитаты (для №07)

```python
from bcc_review.readers.text import source_lines, span_to_source

lines = source_lines(source_bytes)  # та же нумерация, что у reader
block = ...                         # Block по evidence.block_id
assert block.text[ev["start"]:ev["end"]] == ev["quote"]
for line, c0, c1 in span_to_source(block, ev["start"], ev["end"]):
    print(line, lines[line - 1][c0:c1])  # внутри одной строки без снятой разметки == quote
```

`to_source`, `span_to_source`, `from_source` работают и по блоку, у которого есть только контрактный
`loc.map` (без `spans`). `verify_document(document, data)` перепроверяет SHA, карту и байтовые смещения
без модели; её можно вызвать из `verify REPORT.json SOURCE`. `block_at_line(document, n)` находит блок,
содержащий строку `n`; это помогает, когда модель ссылается на номер строки.

### Строки таблиц как факты (для №04 и №06)

`table_records(document)` выдаёт по записи на `table_row`: `block_id`, `header_id`, `row`, `line`,
`section`, `direction` (`request`/`response`/`None` по ближайшему заголовку: «запрос», «Query»,
«Request body» → `request`; «Ответ» → `response`), `key` (первая ячейка) и `cells`. В каждой ячейке
есть `column`, `value`, смещения, `line`, `col_start`, `col_end` и `numbers`. Числа ищутся только внутри
своей ячейки, разделитель тысяч — пробел, NBSP или узкий NBSP, перенос строки им не считается.
Поэтому `1 000` в конце одной строки и `500` в начале следующей не склеиваются в `1 000 500`.

## Проверенные случаи

| Случай | Тест |
| :--- | :--- |
| Цитата из середины 2-й строки таблицы критериев приёмки → строка 64 и точный текст по JSON документа и по одному `loc.map` | `test_quote_from_middle_of_second_table_row_restores_its_line_and_exact_text` |
| 2-я строка API-таблицы; таблица с неровными отступами | `test_quote_inside_second_api_row_and_in_padded_table` |
| Одинаковый заголовок и предложение в частях A и B: разные ID, верные пути | `test_repeated_heading_and_sentence_in_parts_a_and_b_have_distinct_ids_and_paths` |
| UTF-8 с BOM, CRLF, CR, BOM+CRLF на трёх фикстурах: те же ID, тексты, карты; байтовые смещения точны | `test_bom_and_line_endings_keep_ids_texts_and_coordinates` (15 вариантов) |
| Повторный запуск на тех же байтах: побайтно тот же JSON | `test_same_bytes_give_same_ids_and_identical_json` |
| fenced JSON с `\|`, текстовый блок с `\| … \|` и `#`; незакрытый fence | `test_fenced_json_with_vertical_bars_is_inert`, `test_unclosed_fence_runs_to_end_with_warning` |
| Пустая секция, вложенная пустая секция | `test_empty_section_is_marked_and_reported` |
| TXT без номеров, повтор фразы, маркеры и перенос пункта; cp1251; битые байты → `decode_error` | `test_txt_*`, `test_cp1251_*`, `test_undecodable_*` |
| Чек-лист `- [ ]` и строки бланка «Да / Нет» отличаются от требований | `test_checklist_items_are_distinguished_from_requirements` |
| Критерий приёмки: «условия / действие / результат», отдельный ID строки | `test_acceptance_rows_keep_given_when_then_and_own_ids` |
| Число соседней строки не попадает в факт | `test_number_from_neighbouring_row_does_not_join_the_fact` |
| API-параметр: колонка, направление, тип, значение, место | `test_api_table_rows_keep_column_direction_type_value_and_place` |
| Каждый дословный символ ↔ символ источника (туда и обратно) | `test_every_visible_character_maps_back_to_its_source_character` |
| Ложные срабатывания: `#хештег`, `2 * 3`, `snake_case`, `2024.` внутри абзаца, `\|` без разделителя | `test_setext_thematic_break_and_false_positives`, `test_inline_*` |
| Стык с контрактом: `validate(…, "Document")`, совпадение с `minimal_report.json`, `evidence_errors` | `test_p01_contract_junction.py` |

Сверх тестов прогнан фаззинг: 8000 случайных документов (md и txt; LF, CRLF и CR; BOM) без падений,
без потерянных строк и с полным покрытием `spans`, плюс 1200 документов через `contracts.validate`.

## Решения и сравнения

* **Видимый текст + карта, а не сырой Markdown.** На официальном документе 9,1% 24-символьных цитат
  из видимого текста не находятся дословно в сыром Markdown (мешают `**`, обратные кавычки, маркеры).
  В обратную сторону 22,4% окон сырого текста не находятся в видимом. Поэтому модели нужно показывать
  `block.text` с `[b0012]`, а место в источнике восстанавливать по `spans`/`map`.
* **Повторяющаяся фраза.** «Признак включения», «Порог в тенге», «Учебный контур» встречаются дважды.
  `text.find` всегда возвращает первое место, а опора `{block_id, start}` указывает на нужное.
* **`plain_chunks` из RAG** (`diiaanns07-droid/RAG@ba64cc7`, `ingestion/text_chunks.py`) режет текст
  без потерь на куски до 4000 символов, но не хранит ни строк, ни смещения куска (`page_number=1`).
  Внутри он использует `str.splitlines`, который считает U+2028, U+2029, NEL, VT и FF переводами
  строки: на примере `"… …\n…\x0c…\r\n…\x85…\n"` это 6 строк вместо 3. Сам нарезчик не
  переиспользован. Взято правило закрытия fence из `_complete_fences` (тот же символ, длина не меньше
  открывающей, без info-строки, тело не разбирается), дополненное отступом до 3 пробелов по CommonMark
  и предупреждением о незакрытом блоке.

## Ограничения (упрощённый CommonMark)

* Внутри цитат `>` списки и заголовки не разбираются, содержимое идёт текстом блока `quote`.
* Таблицы внутри пунктов списка не распознаются, строка остаётся текстом пункта.
* Reference-ссылки `[text][ref]` и сноски остаются буквальным текстом.
* В TXT нет заголовков: `section == []`, заголовок документа — первая строка.
* «Часть A» и «Часть B» в официальном файле набраны латиницей. Если модель вернёт кириллическую «А»,
  №07 стоит сравнивать цитаты с учётом похожих символов.
