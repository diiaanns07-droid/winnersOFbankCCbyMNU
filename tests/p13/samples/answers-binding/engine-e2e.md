# Ответ аналитика через движок: answers.md → `--answers` → report.json → HTML

Тестовая копия: `bcc/integration@6be9e97` с влитой веткой №13 (локальная ветка, не публиковалась).
Слоты движка в паспорте прогона:

* `parse_answers` → `fallback:bcc_review.runtime.fallback.decisions:parse_answers` (№08 не влит);
* `build_questions` → `fallback:bcc_review.runtime.fallback.decisions:build_questions`;
* `write_html` → `team:bcc_review.exports.html:write_html` (модуль №13).

Транспорт: `--provider mock` (синтетические ответы, без сети) и `--offline-lint` (без модели).
Вход — исходный файл синтетического документа (`fixture_builder.source_text(20)`), его SHA-256
`d9bb5752…39f8` совпадает с `source_sha256` в answers.md, выгруженном браузером из отчёта r2.

```bash
python -m bcc_review input.md mock/report.md --provider mock --answers answers.md --export html --no-cache -q
```

```bash
python -m bcc_review input.md offline/report.md --offline-lint --answers answers.md --export html --no-cache -q
```

| Прогон | Вопросы нового прогона | `report.decisions` | HTML до правки | HTML после правки |
| :--- | :--- | :--- | :--- | :--- |
| mock | нет | Q-01 «Да: после смены порога…», Q-02 «Авторизация (холд)…» | ответов не видно, сводка «Учтено ответов на вопросы: 2» | блок «Ответы из --answers без вопроса в этом прогоне»: 2; привязано: 0 |
| offline-lint | Q-001, Q-002, Q-003 | те же Q-01, Q-02 | то же | то же; к Q-001…Q-003 ответы не приписаны |

Итог: решение аналитика доходит до `report.decisions`, но с Q-ID прошлого прогона. Новый прогон
нумерует вопросы заново (`Q-001…`), поэтому без сопоставления по отпечатку вопроса ответ ни к какому
вопросу не привязывается. В HTML это теперь видно явно. Сопоставление по `Отпечаток вопроса`
(или по тексту вопроса из answers.md) — задача движка и №08: см. передачу.

Браузерная проверка обоих HTML (Chromium, file://, офлайн): блок `#ans-unattached` виден, в нём
2 ответа; самопроверка подсветки — 248 из 248 опор; ошибок JS нет.
