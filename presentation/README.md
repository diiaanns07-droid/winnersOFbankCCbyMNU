# Презентация и материалы для видео (№14)

| Файл | Что это |
| :--- | :--- |
| `title.html` | титульный слайд команды STUPITS (живой: «Далее» / → запускает ревью слоп-слайда; `title.html#final` — финальный кадр) |
| `deck.src.html` | слайды 2–12 (сцена 1600×900); числа — подстановки `{{имя}}` |
| `build.py` | сборка `deck.html` → `out/slide-NN.png` → `deck.pdf`, `deck.pptx` |
| `render.cjs` | рендер слайдов в PNG через Playwright (зовёт `build.py`) |
| `shots.cjs` | скриншоты отчёта и веб-демо для README и слайдов → `img/` |
| `demo_video.cjs` | сценарная видеозапись демо (mp4) для ролика |
| `img/` | картинки слайдов; откуда они — `img/SOURCE.md` |
| `metrics.json` | числа замеров (№15, №17) и команда — заполняется перед финальной сборкой |
| `pitch.md` | сценарий питча от №17; разделы `## Слайд N` уходят в заметки докладчика PPTX |

## Сборка слайдов

```bash
python presentation/build.py --png --pdf --pptx
```

Числа берутся из финального отчёта агента (`reports/requirements.json`: блокеры, сверка цитат, отклонённые) и
`presentation/metrics.json`. Отчёт с провайдером `mock` не используется. Чего нет — на слайде жёлтая плашка «—».
Показ: открыть `presentation/deck.html` (→ / ← / пробел, F — полный экран; первый слайд — живой титул).

Формат `metrics.json`:

```json
{"k_found": "5/5", "s_found": "16/20", "clean_fp": "0", "stability": "3/3",
 "v2_summary": "…", "metrics_source": "evaluation/v2/RESULTS.md, замер …",
 "models": [{"model": "Claude Opus (CLI)", "k": "5/5", "s": "…", "findings": "…", "time": "…", "calls": "…"}],
 "team": [{"name": "Имя Фамилия", "role": "роль"}]}
```

## Скриншоты

```bash
python -m bcc_review.v2.web --port 8014 &
node presentation/shots.cjs reports/requirements.html presentation/img http://127.0.0.1:8014/ release/input/requirements.md
```

## Видео демо

Готовые файлы (2 мин 02 с, 1440×900): `demo.mp4` — без текста, под озвучку; `demo_subtitled.mp4` — с вшитыми
субтитрами; `demo.webm` — исходная запись Playwright; `demo.srt` — субтитры (23 фразы) для монтажа.
Снято 27.11 ≈05:05 (Астана): веб-демо на `v2/14-html-web` (`bcc/v2` 7d80df8), вход `release/input/requirements.pdf`,
`claude_cli` / sonnet. Ответы модели взяты из кэша живого прогона того же PDF (4 мин 40 с, 9 вызовов, 32 дефекта:
4 критичных, 18 существенных, 10 незначительных, цитат 92 из 92) — об этом говорит субтитр, а в паспорте видно
«9 из кэша». Этапы показаны в темпе 2,6 с (`--pace`).

Сценарий: титул → загрузка PDF → этапы → вердикт и «исправить первым» → клик по блокеру подсвечивает строки
документа (обе стороны противоречия) → подробности дефекта → следующие блокеры → фильтр → вопросы владельцу с
вариантами → чек-лист банка → скачивание Word, PDF с выделениями (показана страница) и Jira CSV (показана таблица) →
паспорт → финал. Курсор нарисован оверлеем. Числа в субтитрах берутся из `report.json` этого прогона.

Пересъёмка (например, по финальной сборке):

```bash
python -m bcc_review release/input/requirements.pdf /tmp/warm/report.md --provider claude_cli --model sonnet --cache-dir /tmp/demo-cache
python -m bcc_review.v2.web --port 8014 --data-dir /tmp/demo-web --cache-dir /tmp/demo-cache --pace 2.6 &
node presentation/demo_video.cjs --base http://127.0.0.1:8014/ --file release/input/requirements.pdf --out presentation \
     --provider claude_cli --model sonnet --real "4 мин 40 с"
```

Первая команда — живой прогон, который наполняет кэш; дальше веб повторяет его без модели за секунды.
