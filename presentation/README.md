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

Нужен запущенный веб (`python -m bcc_review.v2.web`). Сценарий: загрузка → этапы → отчёт → клики по трём
критичным дефектам (документ подсвечивает цитаты) → фильтр «только критичные» → вопросы → чек-лист → тест-кейсы →
паспорт. Курсор нарисован оверлеем.

```bash
node presentation/demo_video.cjs http://127.0.0.1:8014/ release/input/requirements.md presentation/out/video claude_cli sonnet
```

С `mock` запись идёт ≈ 50 с (mock воспроизводит записанные ответы живого прогона sonnet, в паспорте видно
«mock»); с `claude_cli` между загрузкой и отчётом ≈ 5 минут этапов — этот кусок в монтаже ускоряется.
