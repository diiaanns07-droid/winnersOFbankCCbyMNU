# HANDOFF №03 — чтение DOCX и нативные комментарии Word

Ветка `bcc/p03-word` от `bcc/integration` @ `3e6b569` (контракт v1 `431f76d`).
Файлы: `src/bcc_review/readers/docx.py`, `src/bcc_review/exports/word.py`, `tests/p03/`.
Пустые `readers/__init__.py` и `exports/__init__.py` нужны как пакеты: при слиянии с
№01/№02/№13/№14/№17 одинаковые пустые файлы конфликта не дают.

## Точки входа (как в таблице HANDOFF Max)

```python
from bcc_review.readers.docx import read_docx, locate          # Document контракта v1
from bcc_review.exports.word import write_docx, annotate_docx, default_output_path
from bcc_review.exports.word import SourceMismatchError, UnsupportedSourceError

doc = read_docx(path)                  # dataclass; doc.to_dict() проходит validate(..., "Document")
out = write_docx(report, input_path, default_output_path(report_md))   # -> Path *.annotated.docx
res = annotate_docx(report, input_path, out_path)   # то же без исключений, подробный результат
```

Подключение в движок (зона Max), `--export docx`:

```python
if "docx" in options.exports and document["format"] == "docx":
    try:
        res = annotate_docx(report, input_path, default_output_path(report_md))
        report["warnings"] += res.warnings()          # {code, message, stage: "export_docx", block_ids}
    except DocxReadError as e:                         # битый пакет
        report["warnings"].append({"code": "docx_export_failed", "message": str(e), "stage": "export_docx"})
```

`report` можно передать как dict, pydantic-модель или dataclass. Версия документа
проверяется по `document.id` и `run.source_sha256`: при расхождении копия не
пишется, статус `source_mismatch` и объяснение на русском (`res.message`).

## Что читает ридер (№07: DOCX-путь к тексту)

* ID блоков — `b0001…` в порядке чтения; структурная ссылка — `loc.ref`:
  `p16` (16-й `w:p` тела), `t2.r3` (строка), `t2.r3.c3` (ячейка), `t3.r1.c2.t1.r1`
  (вложенная таблица), `fn1` (сноска), `p9.tb1` (текстовое поле).
* `kind`: `heading | paragraph | list_item | table_header | table_row`.
  **Таблица — блок на строку** (как в Markdown): текст ячеек через `" | "`, абзацы
  внутри ячейки через `"\n"`. Ячейки видны в `loc.cells[]`: `ref, col, col_span,
  row_span, vmerge, merged_into, path, start, end, column_header, label`.
* Текст абзаца: `w:t` как есть; `w:tab` → `\t`; `w:br`/`w:cr` → `\n`;
  `w:noBreakHyphen` → `-`; формула OMML → её `m:t`; код поля (`w:instrText`) и
  удалённое при рецензировании (`w:del`) не входят; результат поля и `w:ins` входят.
  Координаты — кодовые точки Unicode (`str` в Python), правая граница не входит.
* Подсказку `{block_id, quote}` №07 разрешает как обычно по `block.text`. Цитата,
  которая пересекает жирный и обычный run, работает: run видны в `loc.runs[]`
  (`path` до `w:r`, `start`, `end`, `fmt`, флаги `field`, `atomic`, `math`).
* `section` — заголовки по стилям `Heading N`/`Заголовок N`/`Title`, `outlineLvl`
  и жирным нумерованным строкам (`heading_source`). Автонумерация списков считается
  в `loc.list.label` (`1.`, `2.3`, `•`), в `block.text` её нет, как и в Word XML.

## Формат ссылки для №15 (веб) и №17 (отчёт)

Артефакт: **`<имя отчёта>.annotated.docx`** рядом с `OUTPUT.md`
(`reports/report.md` → `reports/report.annotated.docx`, функция `default_output_path`).

Ссылка на место — `locate(block, start, end)` (принимает и dict из `report.json`):

```json
{"ref": "t2.r3.c3", "anchor": "cell", "part": "word/document.xml",
 "path": "/w:document/w:body/w:tbl[2]/w:tr[3]/w:tc[3]",
 "label": "Таблица 2, строка 3, столбец 3 «Ожидаемый результат»", "cell": {...}}
```

Предлагаемая строка в отчёте: `Таблица 2, строка 3, столбец 3 «Ожидаемый результат» (b0041 · t2.r3.c3)`
и для DOCX-входа — `Комментарий [K1] в report.annotated.docx`. Перейти в Word по
ссылке к абзацу нельзя (Word не открывает URL-фрагменты абзацев), поэтому ищем по
ID замечания в панели примечаний.

Для показа точности в вебе — `res.to_dict()["anchors"][]`:
`finding_id, block_id, comment_id, precision, start, end, quote, ref, label, path, part, note`.
`precision`: `exact` (точно по цитате) · `run` (до границ неделимого run) ·
`paragraph` (абзац целиком) · `cell` (ячейка целиком). Пример: `tests/p03/evidence/report.annotated.result.json`.

## Текст комментария (автор `BCC Review`, инициалы `BCC`)

```text
[K1] Критичный · подтверждено
Критерий приёмки №2 противоречит Ф-2
Критерий: Согласованность набора (ISO/IEC/IEEE 29148:2018, 5.2.6)
Последствие: …
Блокирует решение: …
Сценарий: покупка 31.01 23:58, проведение 01.02 00:03 → по одному месту: январь; по другому: февраль
Вопрос автору: <questions[].prompt по finding_ids> Варианты: …
Исправление: <recommendation>
Требования: R-F2, R-AC2
Связанное место: Абзац 16 (пункт списка)
Привязка: точная, по цитате
```

Первым блоком документа идёт общий комментарий «Сводка ревью ТЗ»: готовность
разработки и тестирования, первые действия, замечания без места в тексте
(отключается `summary=False`).

## Проверенные типы элементов

| Элемент | Чтение | Комментарий |
| :--- | :--- | :--- |
| абзац, заголовок, пункт списка, `w:sdt` | да | точно по цитате |
| цитата через жирный и обычный run | да | точно: run режется, `w:rPr` копируется |
| гиперссылка `w:hyperlink`, `w:ins` | да | точно |
| ячейка таблицы, несколько абзацев в ячейке, цитата через 2 ячейки | да | точно |
| объединение `gridSpan`, `vMerge`, вложенная таблица, `tblHeader` | да | точно |
| уже имеющиеся комментарии, 2+ комментария в одном абзаце, пересечение диапазонов | да | сохраняются |
| поле Word (`fldChar`, `fldSimple`) | результат поля | абзац целиком; ячейка, если поле занимает её всю |
| run с `w:sym` или рисунком | да (без символа) | до границ run |
| формула OMML | текст `m:t` | абзац целиком |
| сноска / концевая сноска | блок после абзаца со знаком | на абзац со знаком сноски |
| текстовое поле (`w:txbxContent`, без дубля `mc:Fallback`) | блок после абзаца-хозяина | на абзац-хозяин |
| колонтитулы | нет, предупреждение `docx_header_footer` | Word не комментирует колонтитулы |
| `altChunk`, SmartArt, таблица внутри текстового поля | нет, `partial_read` | — |
| старый `.doc`, DOCX под паролем, не-ZIP | `DocxReadError` на русском | — |

Конкретный пример неподдерживаемого места: в `tests/p03/p03_fixtures.py::rich_doc` текст
«Конфиденциально» в верхнем колонтитуле не попадает в блоки (предупреждение
`docx_header_footer`), а замечание к тексту «Текст в рамке» ставится на абзац-хозяин
«Перед рамкой» с точностью `paragraph` и пояснением в комментарии.

## Команды и результаты (выполнено в этой среде)

```bash
python -m pip install -e ".[dev]" "python-docx>=1.2"
python -m pytest tests/contract tests/p03          # 54 passed (Python 3.13.18 и 3.11.18)
python tests/p03/evidence/make_evidence.py         # пересобрать доказательства
python tests/p03/fixtures/build_case_docx.py requirements.md tests/p03/fixtures/case_requirements.docx
```

Доказательства готовности → тесты:

1. Цитата через жирный и обычный run, comments part, пара границ, повторное открытие —
   `test_p03_word.py::test_proof1_quote_through_bold_and_normal_run`.
2. Повторяющаяся фраза в абзаце и ячейке, комментарий в выбранной ячейке, хеш входа,
   старый комментарий и обе фразы целы — `test_proof2_repeated_phrase_comment_goes_to_selected_cell`.
3. Кириллица и символ вне BMP, существующий комментарий, две аннотации в одном абзаце —
   `test_proof3_cyrillic_existing_comment_and_two_annotations_in_one_paragraph`.

LibreOffice 24.2: `test_p03_case.py::test_libreoffice_reopens_annotated_case_and_shows_comments`
открывает копию кейса, конвертирует в ODT: все 6 комментариев на месте, у каждого тот же
диапазон текста. PDF с примечаниями на полях содержит `[K1]`, `[K3]`, `[C1]` — комментарии
видны в области примечаний (рендер: `tests/p03/evidence/libreoffice_page2.png`).
**Microsoft Word в среде нет** — открыть `tests/p03/evidence/report.annotated.docx` в Word
и проверить панель «Примечания» предстоит человеку с Word.

## Открытые зависимости

* **Max / pyproject**: комментарии требуют `python-docx>=1.2` (`Document.add_comment`
  появился в 1.2.0), сейчас в extras `docx` стоит `>=1.1`. Без 1.2 ридер работает,
  экспорт поднимает `WordExportError` с понятным текстом.
* **Max / контракт**: ячейки DOCX лежат в `loc.cells` (Loc допускает доп. поля);
  если нужно, внесите `cells`, `ref`, `anchor` в схему `Loc`.
* №07: `resolve_hint` для DOCX работает по `block.text` без изменений; для подписи
  места используйте `locate()`.
* №15, №17: имя артефакта и формат ссылки — выше.
