# №61 — доделать №53: PDF и DOCX как md (27.11, 21:30 Астаны; у тебя около 30 минут и половина лимита)

Ты — сессия Claude Code команды STUPITS, роль №61: продолжаешь работу №53, он упёрся в лимит. Репозиторий
https://github.com/diiaanns07-droid/winnersOFbankCCbyMNU. Всё по-русски. Общие правила, проверки и сроки —
`git fetch origin v2/11-clarify && git show origin/v2/11-clarify:docs/plan-v2/wave5/50-common.md`; сама задача —
`git show origin/v2/11-clarify:docs/plan-v2/wave5/53-pdf-docx.md`. Экономь лимит: не перечитывай лишнего.

## Где №53 остановился
Ветка `v2/53-formats` (голова `bc47c640`, код `8207ec88`): правки чтения PDF и DOCX внесены и покрыты тестами, живые
прогоны sonnet на `ec2418f` и `c7ca0cd` сохранены, шли подтверждающие DOCX ×2 и PDF ×1 на `8207ec8`. Таблицы — в
`docs/plan-v2/status/53.md`.

## Что сделать
1. Та же ветка: `git checkout -B v2/53-formats origin/v2/53-formats`; первой строкой статуса — «№61 ведёт за №53 с ЧЧ:ММ».
2. Дошли ли подтверждающие прогоны (каталоги `evaluation/v2/measurements/w5_53_*`)? Нет — запусти DOCX ×1 и PDF ×1:
   `python -m bcc_review release/input/requirements.docx out/docx.md --provider claude_cli --model sonnet --no-cache`
   (то же для `.pdf`), счёт — `python -m evaluation.v2.score out/docx.json`.
3. Весь `tests/v2` — 0 failed; mock, `verify` для PDF и для DOCX, `antifit` — по общим правилам.
4. PDF и DOCX ≥ 24/25 и К 5/5 critical, md не хуже → **«Готово к вливанию: SHA»** в статусе до 22:00 Астаны. Хуже —
   честно «не предлагаю» с числами. Commit + push каждые 5 минут.
