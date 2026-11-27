# №64 — подстраховка сдачи: интеграция, отчёты, свежий клон (27.11, 21:30–23:59 Астаны; половина лимита)

Ты — сессия Claude Code команды STUPITS, роль №64. Репозиторий https://github.com/diiaanns07-droid/winnersOFbankCCbyMNU.
Всё по-русски. Общие правила — `git fetch origin v2/11-clarify && git show
origin/v2/11-clarify:docs/plan-v2/wave5/50-common.md`. Свой статус — `docs/plan-v2/status/64.md` в ветке `v2/64-backup`.

Релиз ведёт интегратор №46 (`docs/plan-v2/status/46.md` в `bcc/v2`), отчёты сдачи — №36 (`docs/plan-v2/status/36.md` в
`v2/36-submission`). Владелец не может найти часть чатов: если кто-то из них замолчит, сдача сорвётся. Ты — страховка
и ничего не делаешь за живого. Экономь лимит: жди через Monitor или until-loop по `git ls-remote`, не держи сон в ходе.

## 1. Раз в 10 минут — кто жив
Время последних коммитов `origin/bcc/v2` (№46) и `origin/v2/36-submission` (№36) — строкой в свой статус.

## 2. №46 не объявил финальную голову к 22:20 Астаны — бери интеграцию
Строка «Интеграция релиза — у №64 с ЧЧ:ММ (№46 молчит с ЧЧ:ММ)» в `docs/plan-v2/INTEGRATION.md`. Порядок и проверки —
`docs/plan-v2/wave5/46-release-integrator.md` (ветка `v2/11-clarify`), «Как вливать», пункты 1–4. Вливай только
«Готово к вливанию» с пройденным правилом:
- №50 `f3224f9e` (№46 уже проверил: 2330 passed, mock 29 / К 5/5 / С 17/20; sonnet 25 и 24 из 25);
- №52 `733cd87d` (поверх ветки Codex; sonnet 24 и 25 из 25, С8, С12, С15 — в 5 из 5);
- интерфейс — голова `v2/54-ui-light` и вместе с ней `claude/project-thread-24yvec` (`c2897123`, `8d5ddb31`: одна
  верхняя панель отчёта, просьба владельца);
- №53, №56, №57 — если в их статусах «Готово к вливанию» (их доделывают №61–№63).
После каждого — `git push origin HEAD:bcc/v2` и тот же SHA в `release`, без force; `git ls-remote` — проверить обе.

## 3. №36 не написал «Готово к сдаче: SHA» к 22:50 — собери отчёты по его плану
Worktree на финальной голове; `SECOND_DOC=evaluation/dev/corpus/cases/cashback.base/source.md
SECOND_NAME=other_topic_cashback ANSWERS= scripts/final_reports.sh claude_cli sonnet` → `reports/` →
`python scripts/reports_table.py reports --write` → `python scripts/check_links.py` (0 битых) → числа замера в README и
SUBMISSION. Влить — как в п. 2, только `reports/`, README и SUBMISSION. Отчёты руками не править.

## 4. В любом случае после финальной головы — свежий клон глазами жюри
`git clone -b release https://github.com/diiaanns07-droid/winnersOFbankCCbyMNU.git` в новую папку, `./start.sh --check`,
затем без ключа: знакомство → «Без ключа» → готовые отчёты → пример → отчёт; ссылки README открываются. Всё сломанное —
строкой в статус и на доску (`docs/plan-v2/wave4/BOARD.md` в `v2/11-clarify`, перед push — fetch и merge) до 23:15.

## 5. Тег
`v2.0.0` ставит №46 (или ты, если интеграция у тебя) только после «да» владельца.
