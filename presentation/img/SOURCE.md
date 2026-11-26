# Откуда картинки

* `title_final.png` — финальный кадр титульного слайда STUPITS (`presentation/title.html#final`).
* `report_*.png`, `web_*.png` — скриншоты настоящего прогона агента, не макет: веб-демо
  `python -m bcc_review.v2.web`, провайдер `claude_cli`, модель sonnet (claude-sonnet-5-5), официальный документ
  `release/input/requirements.md`, 27.11 02:51 (Астана), сборка v2 на `bcc/v2` 09f0dfb + веб №14 f864da8:
  5 мин, 9 вызовов модели, 32 дефекта (5 критичных, 16 существенных, 11 незначительных), цитат сверено 93 из 93.
  Сняты `node presentation/shots.cjs report.html presentation/img` (Chromium, 1440×900, масштаб 2).
  Перед сдачей переснимаются по финальному отчёту `reports/requirements.json`.
