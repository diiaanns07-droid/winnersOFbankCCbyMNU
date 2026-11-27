# Откуда картинки

* `title_final.png` — финальный кадр титульного слайда STUPITS (`presentation/title.html#final`).
* `report_*.png`, `web_*.png` — скриншоты настоящего прогона агента, не макет (Chromium, 1440×900, масштаб 2):
  веб-демо `python -m bcc_review.v2.web` (сборка `0d09654` = `bcc/v2` 4bbb299 + №14), вход
  `release/input/requirements.pdf`, провайдер `claude_cli`, модель sonnet. Ответы модели — из кэша живого прогона
  того же PDF 27.11 ≈06:20 (Астана): 5 мин 24 с, 9 вызовов, 33 дефекта (5 критичных, 18 существенных,
  10 незначительных), цитат сверено 96 из 96. Те же прогоны — в видео `presentation/demo.mp4`. Сняты 27.11 ≈06:35:
  `node presentation/shots.cjs report.html presentation/img http://127.0.0.1:8014/ release/input/requirements.pdf claude_cli sonnet`.
  * `report_first.png` — первый экран HTML-отчёта: вердикт, числа, «исправить первым»;
  * `report_card.png` — карточка критичного дефекта, документ прокручен к цитатам (режим фокуса);
  * `report_checklist.png`, `report_questions.png` — вкладки «Чек-лист банка» и «Вопросы»;
  * `report_dark.png` — тёмная тема;
  * `web_upload.png`, `web_progress.png`, `web_report.png` — веб-демо: загрузка, этапы, готовый отчёт.
  Перед сдачей переснимаются по финальному отчёту, если он заметно изменится.
