# HANDOFF №03 — чтение DOCX и нативные комментарии Word

Ветка `bcc/p03-word` от `bcc/integration` @ `3e6b569` (контракт v1 `431f76d`).
Файлы: `src/bcc_review/readers/docx.py`, `src/bcc_review/exports/word.py`, `tests/p03/`.
Пустые `readers/__init__.py` и `exports/__init__.py` нужны как пакеты: при слиянии с
№01/№02/№13/№14/№17 одинаковые пустые файлы конфликта не дают.

## Третий проход: сумма в тексте и две такие же в таблице (после `b399dcc`)

Вход — `p03_fixtures.amounts_doc` (пример: `tests/p03/evidence/amounts/`): заголовок
«3. Уведомление о расходах», автонумерованный список 1–3, «50 000 ₸» в пункте 2 и дважды в
таблице; в строке 2 сумма разбита на жирный «50 000» и курсивный « ₸»; вариант
`user_comment=True` — на сумме в строке 3 уже комментарий пользователя.

* Диапазоны и тела комментариев на двух одинаковых суммах уже были верны на `b399dcc`
  (`test_p03_amounts.py::test_two_amounts_ranges_match_their_comment_bodies`, оба варианта).
* Не хватало счётчика пропусков: сводка писала «отмечено в тексте: 2» без «из N», а через
  движок в `report.json` о пропусках не попадало ничего (`write_docx` отдаёт только путь).
  Правка: `AnnotationResult.counts` (`findings`, `findings_anchored`, `evidence`,
  `evidence_anchored`, `comments_added`, `skipped`), в сводке «Отмечено в тексте: X из N
  замечаний (опор Y из M)» и причина по каждому пропуску, предупреждение
  `docx_export_unanchored`. Если `report` — dict, `write_docx` дописывает предупреждения
  экспорта в `report["warnings"]`; у движка это `self.warnings`, и он пишет их в
  `report.json` после экспорта — правка движка не нужна.
* Сквозной путь (`test_p03_stitch.py`, после слияния с интеграцией): `--offline-lint`
  (правила без модели) и mock с записанными ответами; каждая опора — ровно один
  комментарий своего замечания на том же диапазоне.

**Max.** (1) В интеграции №03 стоит на `d2e8f30`; второй и третий проходы — в `bcc/p03-word`.
(2) Движок отсекает кандидатов без опоры до экспорта (`engine.py`, этап evidence), поэтому
DOCX-счётчик в реальном пути показывает «N из N», а пропуск виден в `report.rejected` и
`run.evidence_audit`. Кандидат без единой цитаты (пропуск требования без `quotes`) в
`evidence_audit` не считается: `checked/rejected` растут только по подсказкам.

## Второй проход: комментарий на точном вхождении (после `d2e8f30`)

Вход: фраза «порог от 1 000 до 1 000 000 ₸» в обычном абзаце (на ней комментарий
автора) и в ячейке, где она разрезана между жирным run и внешней гиперссылкой, а перед
ней удалённое при рецензировании «порог от 500 » (`p03_fixtures.twin_phrase_doc`).
Воспроизведено на `d2e8f30`:

1. сводный комментарий по умолчанию выделял весь первый блок — абзац с копией фразы;
2. маркеры `commentRange` без записи в `comments.xml` (`orphan_markers=True`):
   python-docx выдаёт номер `max(comments.xml)+1` и не видит маркеры — две пары границ
   на один `w:id`, а экспорт отвечал `written / exact`, хотя его же проверка
   `new_ranges_paired` была `False`.

Правка (`exports/word.py`):

* номер комментария выбирается вне номеров маркеров всех частей (тело, колонтитулы,
  сноски); при совпадении свои три маркера перенумеровываются;
* сводка: на заголовке, если он первый блок, иначе точкой (пустой диапазон) в начале;
* после записи диапазон каждого комментария перечитывается из копии
  (`comment_spans`) и сверяется с планом; `Anchor.covered = {block_id, start, end, text}` —
  фактически охваченные слова. При расхождении копия удаляется, статус
  `verification_failed`, `write_docx` поднимает `WordExportError` (движок пишет
  предупреждение `export`);
* при приблизительной привязке в комментарии добавлена строка «Точные слова: «…»».

Тесты: `test_p03_exact_copy.py` (независимая проверка по OOXML: `p03_ooxml.py` без кода
экспортёра), `test_p03_case.py::test_libreoffice_puts_twin_comment_into_the_cell`,
`test_p03_stitch.py` (движок + mock, пропускается до слияния с интеграцией).
Новые тесты на прежнем коде: 5 failed, 3 passed; на текущем — все зелёные.
Деталь, не изменённая намеренно: `w:commentReference` после последнего run гиперссылки
python-docx ставит внутрь `w:hyperlink`; адрес (`r:id` → Target) и текст ссылки не меняются.

**Max — зависимость.** `Document.add_comment` есть только с python-docx 1.2.0; в
`pyproject.toml` интеграции стоит `>=1.1`. Проверено в venv с 1.1.2: `read_docx` работает,
`write_docx` отказывает `WordExportError` и копию не создаёт. Строка изменения:

```diff
-docx = ["python-docx>=1.1"]
-all = ["anthropic>=2.0", "pymupdf>=1.24", "python-docx>=1.1"]
+docx = ["python-docx>=1.2"]
+all = ["anthropic>=2.0", "pymupdf>=1.24", "python-docx>=1.2"]
```

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
python -m pytest tests/contract tests/p03 -o addopts=""   # 65 passed, 1 skipped (стык без движка); 3.13 и 3.11
python tests/p03/evidence/make_amounts_evidence.py         # пример «сумма в тексте и две в таблице»
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
