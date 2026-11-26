# HANDOFF №14 — PDF с настоящими выделениями и записками

Ветка `bcc/p14-annotated-pdf` от `bcc/integration` @ `091e504`. Мои файлы:
`src/bcc_review/exports/pdf.py`, `src/bcc_review/exports/pdf_assets/`, `tests/p14/`.

## Что делает `write_pdf(report, input_path, output_path) -> Path`

| Вход | Выход |
| --- | --- |
| PDF | **аннотированная копия**: исходные байты + инкрементальное сохранение. Исходник остаётся байтовым префиксом копии, content streams не меняются, чужие аннотации сохраняются |
| Markdown / TXT | **производная PDF-копия** (Noto Sans, ₸, таблицы с переносами и повтором шапки). Слева номера строк Markdown, внизу «Страница экспорта N из M», метки страниц `Экспорт-N`, плашка о происхождении с SHA-256 источника |

Нативные аннотации в обоих режимах:

* **Highlight** + Popup на каждой опоре. Многострочная цитата — одна аннотация с несколькими
  quads, цитата на двух страницах — по аннотации на страницу. `/Contents` в UTF-16BE: ID,
  `[!!!] КРИТИЧНО`, статус, суть, критерий, требования, последствие, блокируемое решение,
  вопрос (`prompt` + `options` из `report.questions`), цитата, блок и символы.
* **FreeText-подпись** «ID · серьёзность». Вид отрисован нашим Noto Sans (Type0) с векторным
  значком ▲/◆/●, поэтому цвет всегда продублирован словом и формой. Подпись ставится в свободное
  поле рядом и не перекрывает текст (тест `test_labels_do_not_cover_source_text`).
* **Противоречие**: обе стороны выделены, каждая заметка называет вторую сторону (страница и
  цитата), подписи связаны Link-переходами в обе стороны.
* **Text-заметка** «БЕЗ ТОЧНОЙ ПРИВЯЗКИ: причина» на подтверждённой странице: скан, нет
  координат, неоднозначность, fragment не содержит текста. Пропуск ставится у
  `inspected_block_ids`.
* **Сводка** на стр. 1 и вложение `bcc_review_pdf_export.json`: каждое размещение с
  прямоугольниками или причиной; для Markdown — ещё карта строк и блоков.

Привязка: SHA-256 входа = `document.id` = `run.source_sha256`, иначе `SourceMismatchError`.
`block.text[start:end] == quote` проверяется заново. PDF ищет только внутри `rect` своего
fragment на `loc.page`. Markdown использует `loc.map` (точная колонка), а без неё выравнивает
текст внутри строк блока. Похожая фраза в другом месте не используется никогда (тест F-07).

## Проверенные особенности PyMuPDF (2.2 и 1.24.14)

1. `get_text()` и `add_*_annot()` работают в неповёрнутом пространстве от левого верхнего угла
   CropBox. Сверено пикселями в MuPDF, poppler и PDFium на 0/90/180/270° и смещённом CropBox.
2. `page.transformation_matrix` **неверна** на странице с /Rotate и смещённым CropBox. Матрица
   «страница → PDF» снимается пробной аннотацией (`_unrot_to_pdf`). Та же ошибка есть в
   `insert_link`: `/Rect` и `/Dest` ссылок переписываются.
3. `get_links()` сразу после `insert_link` возвращает устаревший список, а `annot_xrefs()` —
   актуальный.
4. PyMuPDF 1.24 пишет кириллический префикс `/PageLabels` как UTF-8 без BOM и не читает
   UTF-16. Метки пишутся напрямую (`get_pdf_str`), читаются через `page_label()`.
5. MuPDF включает текст FreeText в `get_text()`. Поэтому «текст исходника сохранён»
   проверяется равенством content streams и наличием каждого исходного слова на месте.

## Команды и результаты (выполнено в этой среде)

```bash
python -m pip install -e ".[dev,pdf]" fonttools pypdfium2 pillow
python -m pytest tests/contract tests/p14
```
→ `86 passed` (PyMuPDF 2.2, Python 3.13); `tests/p14` на PyMuPDF 1.24.14 → `57 passed`.
`ruff check --select E,F,W,B` — чисто.

Стык с движком (входит в `tests/p14/test_p14_junction.py`): `run_review(..., provider="mock",
mock_script=mock_bcc.json, exports=["pdf"])` на `tests/integration/fixtures/bcc_requirements.{md,pdf}`.
Движок сам вызывает `write_pdf` и пишет `report.annotated.pdf`. Отчёт проходит `validate`,
`evidence_errors == []` и `verify_export`. F-001 (конфликт, обе стороны) и F-002 выделены.
В PDF все quads лежат внутри `rect` своих fragments, в Markdown метод — `loc_map`.

Демо для №18 на официальном кейсе (К1–К5 из `docs/task-analysis.md`, блоки — ридеры движка):

```bash
curl -sSfLo /tmp/requirements.md https://raw.githubusercontent.com/BCC-HUB/ai-requirements-validator-task/928c1aa364265426105b69ba7a3444eac11b22db/docs/requirements.md
python tests/p14/demo_p14_case.py /tmp/requirements.md /tmp/p14-demo
```
→ `{"markdown": {"ok": true, "highlights": 11, ...}, "pdf": {"ok": true, "highlights": 11, ...}}`.

Отдельная проверка экспорта и отрисовка:

```bash
python -m bcc_review.exports.pdf REPORT.json SOURCE OUT.pdf --render 2
```
Печатает сводку и `verify`, код выхода 0 или 1.

Проверено в просмотрщике pdf.js 4.10.38 (движок Firefox, Playwright + Chromium): по щелчку на
выделении открывается заметка с кириллицей и ₸, ссылка с подписи на повёрнутой стр. 3 переводит
на стр. 4. Акробат, Preview и встроенный просмотрщик Chrome руками не проверялись.
Всплывающие заметки в разных программах показываются по-разному (PDFium в Chrome — ограниченно),
а выделения и подписи видны везде.

## Проверенные случаи (tests/p14)

Контрольные слова и quads; одинаковая фраза на двух страницах (PDF и MD); многострочная цитата;
страницы 90° и 270° + CropBox; fragment в пространстве PDF; обе стороны противоречия и ссылки;
скан → заметка; ложная привязка не переезжает на похожую фразу; неподтверждённая опора →
причина в сводке; пропуск у осмотренного блока; хеш исходника неизменен, байтовый префикс;
чужие аннотации целы; Unicode в `/Contents` (повторное чтение MuPDF и PDFium); подписи нашим
шрифтом, видимые пиксели и без наложения на текст; рендер в MuPDF, PDFium и poppler. Markdown:
₸ и казахские буквы, метки «Экспорт-N» (и в PDFium), номера строк, длинная таблица с повтором
шапки, длинный URL внутри колонки, `loc.map`, TXT, отказ для DOCX. Глифы: `漢` выявляется
(strict → `MissingGlyphError`), `→ ≤` набираются закреплённым Noto Sans Math, хеши и лицензии
шрифтов.

## Что нужно от других

* **Max (pyproject, integration):**
  1. `[tool.setuptools.package-data] "bcc_review.exports" = ["pdf_assets/*"]` — иначе `*.ttf` и
     `*.pb` не попадут в обычную установку (в editable всё работает).
  2. В extra `pdf` добавить `fonttools>=4.47` (подмножество и Bold). Без него экспорт работает, но
     полужирный совпадает с обычным, а шрифт встраивается целиком, о чём пишется предупреждение.
  3. `tests/integration/test_engine.py:422` ждёт «экспорт pdf недоступен». После слияния №14
     заменить на `assert Path(rep["exports"]["pdf"]).name == "report.annotated.pdf"`.
* **№02:** формат совпадает с резервным ридером (`loc.page` + `fragments[{start,end,rect}]`,
  неповёрнутые пункты). Если появится fragment на другой странице, допустим ключ `page` у
  fragment. Ключ `space: "pdf" | "display"` распознаётся, если координаты не в пространстве
  PyMuPDF. Стыковой тест с настоящим `bcc_review.readers.pdf` запустить после публикации
  `bcc/p02-pdf-reader`: `pytest tests/p14/test_p14_junction.py`.
* **№07:** опоры перепроверяются здесь же. `anchor_status=incomplete` и `meaning_status`
  `uncertain/unchecked` попадают в текст заметки.
* **№15:** ссылка на файл — `report["exports"]["pdf"]` (`OUTPUT.annotated.pdf` и для PDF, и для MD).
* **№18:** приёмка — `verify_export(out, source, report)["ok"]` и демо-команда выше.

## Открыто

* `bcc/p02-pdf-reader` ещё не опубликован: стык проверен на резервном ридере движка.
* Для DOCX и HTML на входе `write_pdf` поднимает `UnsupportedFormatError` (движок пишет
  предупреждение). DOCX-аннотации — зона №03.
