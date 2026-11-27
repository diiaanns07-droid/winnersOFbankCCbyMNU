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

Готовые файлы (2 мин 15 с, 1440×900): `demo.mp4` — без текста, под озвучку; `demo_subtitled.mp4` — с вшитыми
субтитрами; `demo.webm` — исходная запись Playwright; `demo.srt` — субтитры (25 фраз) для монтажа.
Снято 27.11 ≈06:30 (Астана) на сборке `0d09654` (`v2/14-html-web` = `bcc/v2` 4bbb299 + №14), `claude_cli` / sonnet:
* `release/input/requirements.pdf` — живой прогон 5 мин 24 с, 9 вызовов, 33 дефекта (5 критичных, 18 существенных,
  10 незначительных), цитат 96 из 96;
* `release/input/requirements.docx` — живой прогон 4 мин 30 с, 9 вызовов, 31 дефект (5/14/12), цитат 85 из 85,
  в Word 81 комментарий (31 замечание на 80 местах + сводный).

При съёмке веб повторил эти прогоны из кэша ответов модели (об этом говорит субтитр, в паспорте видно «9 из кэша»);
этапы показаны в темпе 2,6 с (`--pace`). Word с комментариями отрисован LibreOffice (комментарии на полях).

Сценарий: титул → загрузка PDF → этапы → вердикт и «исправить первым» → клик по блокеру подсвечивает строки
документа (обе стороны противоречия) → подробности дефекта → следующие блокеры → фильтр → вопросы владельцу с
вариантами → чек-лист банка → скачивание Word, PDF с выделениями (показана страница) и Jira CSV (показана таблица) →
тот же ТЗ в DOCX: Word с комментариями на полях → паспорт → финал. Курсор нарисован оверлеем; числа в субтитрах
берутся из `report.json` этих прогонов.

Пересъёмка (например, по финальной сборке):

```bash
python -m bcc_review release/input/requirements.pdf /tmp/warm/report.md --provider claude_cli --model sonnet --cache-dir /tmp/demo-cache
python -m bcc_review release/input/requirements.docx /tmp/warm2/report.md --provider claude_cli --model sonnet --cache-dir /tmp/demo-cache
python -m bcc_review.v2.web --port 8014 --data-dir /tmp/demo-web --cache-dir /tmp/demo-cache --pace 2.6 --workers 2 &
node presentation/demo_video.cjs --base http://127.0.0.1:8014/ --file release/input/requirements.pdf \
     --docx release/input/requirements.docx --out presentation --provider claude_cli --model sonnet --real "5 мин 24 с"
```

Первые две команды — живые прогоны, которые наполняют кэш (после смены промптов кэш устаревает — прогнать заново); дальше веб повторяет их без модели за секунды.
