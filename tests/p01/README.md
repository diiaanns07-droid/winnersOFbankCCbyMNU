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
| вложенные блоки | `parent` — ID пункта списка у таблицы (`table_header` и каждой `table_row`), fenced-кода, цитаты и HTML-комментария, если блок начинается с отступом пункта; список после такого блока продолжается |
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

Пример со вложенной таблицей (`fixtures/nested_tables.md`, строка 23, часть B, пункт «1. Комиссия»):

```python
from bcc_review.analysis.evidence import locate, resolve_hint  # №07
from bcc_review.readers.text import read_text, span_to_source

doc = read_text("tests/p01/fixtures/nested_tables.md")
row = next(b for b in doc.blocks if b.loc["line_start"] == 23)
row.text   # 'Перевод на карту | 💳 не более 10 000 ₸ | карта | счёт'
row.loc["map"]  # [[0, 23, 5], [21, 23, 28], [38, 23, 47], [47, 23, 57]]
q = "💳 не более 10 000 ₸ | карта | счёт"
s = row.text.index(q)                      # 19
span_to_source(row, s, s + len(q))         # [(23, 24, 63)]
# сырая строка 23 [24:63] == '💳 **не более 10 000 ₸** | карта \\| счёт'

ev = resolve_hint(doc.to_dict(), {"block_id": row.id, "quote": q})["evidence"]
locate(doc.to_dict(), ev)                  # line 23, col 24, col_end 63, раздел «Часть B. Кредитные карты»
```

Формула `locate` по `loc.map` и `span_to_source` по `loc.spans` дают один и тот же диапазон: якорь
`[21, 23, 28]` перешагивает `**`, якорь `[38, 23, 47]` перешагивает `**`, `[47, 23, 57]` — `\`.
Без `block_id` фраза «не более 10 000 ₸ в сутки» неоднозначна (строки 9 и 22, обе под «1. Комиссия»):
№07 возвращает `ambiguous`, с `block_id` — нужное место.

`to_source`, `span_to_source`, `from_source` работают и по блоку, у которого есть только контрактный
`loc.map` (без `spans`). `verify_document(document, data)` перепроверяет SHA, карту и байтовые смещения
без модели; её можно вызвать из `verify REPORT.json SOURCE`. `block_at_line(document, n)` находит блок,
содержащий строку `n`; это помогает, когда модель ссылается на номер строки.

### Строки таблиц как факты (для №04 и №06)

`table_records(document)` выдаёт по записи на `table_row`: `block_id`, `header_id`, `row`, `line`,
`section`, `parent` (пункт списка, под которым лежит таблица, или `None`), `direction`
(`request`/`response`/`None` по ближайшему заголовку: «запрос», «Query»,
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
| Таблица под «1. Комиссия» в двух разделах: раздел, строка, ячейка, `parent`, `map` по символам файла | `test_rows_under_numbered_rule_keep_section_line_cells_and_parent` |
| Одинаковая фраза «не более 10 000 ₸» в ячейках обоих разделов: отдельные записи | `test_same_phrase_in_two_sections_gives_two_distinct_records` |
| Цитата из части B с эмодзи, `**` и `\|`: точные символы и байты сырого файла на LF и BOM+CRLF | `test_quote_in_second_section_restores_exact_raw_chars_and_bytes` |
| Тот же рисунок таблицы в fenced-коде остаётся кодом | `test_table_drawing_inside_fenced_code_stays_code` |
| Список продолжается после вложенной таблицы; таблица без отступа пункта завершает список | `test_list_continues_after_nested_table`, `test_table_outdented_from_item_is_top_level_and_ends_the_list` |
| Варианты вложения: без пустой строки, отступ 4 у «10.», вложенный пункт, табуляция | `test_nested_table_variants_attach_to_their_item` |
| ID прежних фикстур совпадают с reader `d9742fb` | `test_ids_of_unchanged_fixtures_match_previous_reader` (`fixtures/ids_d9742fb.json`) |
| Стык с опубликованным №07: `resolve_hint` + `locate` на вложенной таблице (пропуск, если №07 нет в checkout) | `test_p01_p07_junction.py` |

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
* Таблица внутри пункта распознаётся, если её отступ не больше отступа текста пункта + 3; при большем
  отступе (код с отступом по CommonMark) её строки остаются текстом абзаца с `parent`.
* Reference-ссылки `[text][ref]` и сноски остаются буквальным текстом.
* В TXT нет заголовков: `section == []`, заголовок документа — первая строка.
* «Часть A» и «Часть B» в официальном файле набраны латиницей. Если модель вернёт кириллическую «А»,
  №07 стоит сравнивать цитаты с учётом похожих символов.
