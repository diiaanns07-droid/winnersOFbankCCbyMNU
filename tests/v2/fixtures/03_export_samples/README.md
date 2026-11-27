# Образцы экспорта для демо (№03 → №14)

Официальный документ, ответы этапов живого прогона sonnet (mock-фикстуры `tests/v2/fixtures/official`), прогон без
модели — результат воспроизводится командой:

```bash
python tests/v2/fixtures/03_export_samples/make_samples.py
```

| Файл | Что показывает | Как открыть |
| :--- | :--- | :--- |
| `official.annotated.docx` | копия `release/input/requirements.docx` с комментариями ревью Word на местах цитат (82 места, все 32 дефекта) и сводным комментарием на заголовке: вердикт, первые действия, счётчики | Word: «Рецензирование → Примечания» |
| `official.annotated.pdf` | копия `release/input/requirements.pdf` с выделениями цитат (красный — критичный, оранжевый — существенный, жёлтый — незначительный; 87 выделений) и всплывающими примечаниями: суть, сценарий, последствия, что сделать, вопрос, критерий; сводная заметка на с. 1 | Acrobat, браузер, PyMuPDF |
| `official.jira.csv` | 32 задачи Jira: Summary, Description (места с цитатами, сценарий, вопрос с вариантами), Priority, Labels | Jira → System → External System Import → CSV; Excel (UTF-8 с BOM) |
| `official.report.docx` | Word-версия отчёта (для входа Markdown): тот же отчёт, что `report.md` | Word |
| `png/pdf_highlights_p2.png`, `_p5.png`, `_p6.png` | кадры PDF с выделениями: функциональные требования и критерии приёмки; таблицы API; статусы ответа | для видео и слайдов |
| `png/word_comments_p1.png`, `_p2.png`, `_p4.png` | кадры Word с комментариями на полях (рендер LibreOffice; значки привязки поверх текста рисует LibreOffice, в Word их нет) | для видео и слайдов |

Команда агента, которая даёт те же файлы на живой модели:

```bash
python -m bcc_review release/input/requirements.docx out/report.md --export jira,docx
python -m bcc_review release/input/requirements.pdf out/report.md --export jira,pdf
```
