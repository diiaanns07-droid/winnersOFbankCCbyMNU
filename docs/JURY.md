# Как проверить нас за 5 минут

Страница для жюри: каждое число ниже — это прогон, который лежит в репозитории, команда, которой его пересчитать без
модели, и коммит кода. Худшие прогоны стоят рядом с лучшими. Что не измерено — так и написано. Время — Астана, 27.11.

Числа ниже — для кода `d013c123` (голова `bcc/v2` и `release` на 21:40); заявки, поданные после 21:00, — отдельной
таблицей. Установка — [README, «Быстрый старт»](../README.md#быстрый-старт). Видео-демо на этом интерфейсе без ключа —
[`presentation/demo.mp4`](../presentation/demo.mp4).

## 1. Три команды

| # | Команда | Что покажет |
| :--- | :--- | :--- |
| 1 | **Без ключа:** `python -m bcc_review release/input/requirements.md out/mock.md --provider mock` | За 1–2 секунды весь конвейер на записанных ответах живого прогона: 40 требований, 29 замечаний (critical 5), вердикт «разработка: нельзя · тестирование: нельзя», цитат сверено 82 из 82; файлы `out/mock.md`, `.json`, `.html`. Это проверка механики и сверки цитат, **не качества модели**: ответы взяты из записи. |
| 2 | **С ключом** (бесплатный Gemini — `GEMINI_API_KEY` в `.env`, см. README): `python -m bcc_review release/input/requirements.md out/live.md --provider gemini --no-cache` | Новый живой прогон на вашем ключе: 9–11 вызовов модели, в паспорте отчёта — модель, число вызовов, время, коммит. Потом счёт: `python -m evaluation.v2.score out/live.json`. На подписке Claude — `--provider claude_cli --model sonnet`. |
| 3 | **Проверка отчёта:** `python -m bcc_review verify out/mock.json release/input/requirements.md` | `verify: OK — исходник совпадает (SHA-256 e7dae55e5453…), цитат на своих строках 82 из 82, счётчики и вердикт сходятся`. Программа заново ищет каждую цитату в исходнике, сверяет SHA-256 входа, счётчики и вердикт. |

**Попробуйте сломать.** Измените в копии ТЗ одно слово — `verify` ответит «SHA-256 исходника … не совпадает». Испортите
одну цитату в `out/mock.json` — «D-01 цитата №1: … нет в строке 29; в документе не найдена», код выхода 4. Мы так и
проверяли эту страницу.

Счёт mock (команда 1, затем `python -m evaluation.v2.score out/mock.json`): К 5/5 critical, С 17/20, ключевые 22/25,
дублей 2. Это ниже живых прогонов из таблицы ниже: mock показывает механику, а не лучший результат.

## 2. Как мы считаем

* **Эталон** — 25 ключевых дефектов официального ТЗ: 5 критичных К1–К5 и 20 существенных С1–С20
  ([`docs/task-analysis.md`](task-analysis.md), раздел 5; разметка — [`evaluation/v2/official/gold.yaml`](../evaluation/v2/official/gold.yaml)).
  В промпты он не попадает: `python -m evaluation.v2.antifit` проверяет, что слов официального ТЗ нет ни в
  промптах, ни в правилах агента.
* **Счётчик** — [`evaluation/v2/score.py`](../evaluation/v2/score.py), детерминированный: замечание засчитывается за
  пункт эталона, если его цитаты стоят на строках-опорах пункта и совпадают ключевые слова. Отдельно считаем, сколько
  К помечены в отчёте `critical`. Спорные пары может решить модель-арбитр (`--arbiter sonnet`), её решения
  кэшируются.
* **В таблице ниже — строгий счёт**, который вы получите сами: `--arbiter off` (по умолчанию), только закоммиченный
  кэш арбитра, счётчик из ветки `release`. Мы пересчитали так каждый прогон заново (№58, 21:20–21:40). Где автор
  замера записал другое число с живым арбитром — показываем оба.
* **Ложный critical** — critical, которого нет в эталоне. **Ложный запрет** — вердикт «нельзя» на чистом ТЗ, в котором
  дефектов не закладывали.

## 3. Утверждения и доказательства

Официальное ТЗ, живые прогоны без кэша (`--no-cache`), `claude_cli`. Каталог прогона хранит `report.json`, `report.md`,
журнал и ответы модели на каждом этапе (`stages/`).

| Утверждение | Прогон (каталог) | Код | К / critical | С из 20 | Ключевые 25 | Замечаний / дублей | verify |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Лучший** sonnet на коде релиза | [`reliz_w4_19_50_md_d013c12_sonnet_2`][s2] | `d013c123` | 5/5 / 5 | 20 | **25/25** | 31 / 0 | OK, 84 из 84 |
| sonnet, второй из трёх | [`reliz_w4_19_50_md_d013c12_sonnet_1`][s1] | `d013c123` | 5/5 / 5 | 19 (нет С15) | 24/25 | 31 / 2 | OK, 86 из 86 |
| **Худший** sonnet на коде релиза | [`reliz_w4_19_50_md_d013c12_sonnet_3`][s3] | `d013c123` | 5/5 / 5 | 18 (нет С8, С12) | **23/25** | 27 / 0 | OK, 76 из 76 |
| haiku (слабая модель) | [`reliz_w4_19_50_md_d013c12_haiku_1`][h1] | `d013c123` | 5/5 / 5 | 18 (нет С8, С10) | 23/25 | 32 / 5 | OK, 79 из 79 |
| Тот же ТЗ из **PDF**, sonnet | [`w5_53_base_pdf_973ce4d_sonnet_1`][pdf] | `973ce4d7` (код = `d013c123`) | 5/5 / 5 | 19 | 24/25 | — | OK, 84 из 84 |
| Тот же ТЗ из **DOCX**, sonnet | [`w5_53_base_docx_973ce4d_sonnet_1`][docx] | `973ce4d7` (код = `d013c123`) | 5/5 / 5 | 18 | **23/25** (автор с арбитром — 24) | — | OK, 78 из 78 |
| PDF и DOCX **до** исправлений, sonnet | [`reliz_w4_18_45_pdf_3e7133c_sonnet_1`][pdf0], [`…_docx_…`][docx0] | `3e7133c2` | 5/5 / 5 | 16 и 16 | **21 и 21** | 28 / 1 и 26 / 0 | OK |

Итог по официальному ТЗ на коде релиза: **К1–К5 найдены и помечены critical во всех 6 прогонах** (sonnet ×3, haiku,
PDF, DOCX), ложных critical 0, все `verify` OK. Ключевые — от 23 до 25 из 25: результат **мигает**, 25/25 — один прогон
из трёх. Мигают С8, С12, С15 (по одному разу из трёх). Время sonnet — 2,5–3,8 мин, 9 вызовов модели.

**Не только официальный документ:**

| Утверждение | Прогон | Код | Результат | Слабое место |
| :--- | :--- | :--- | :--- | :--- |
| 12 чистых ТЗ без заложенных дефектов, haiku | [`reliz_w4_19_50_cistye_d013c12_haiku`][clean] | `d013c123` | «можно» на обеих стадиях — 9 из 12; critical — 3 (по одному в repay, roundup, statement) | **ложные запреты: 3 из 12**, цель — 0 (см. ниже) |
| Корпус [`evaluation/dev`](../evaluation/dev): 24 документа с заложенными дефектами и 8 чистых, haiku | [`reliz_w4_20_00_korpus_d013c12_haiku`][corpus] | `d013c123` | полнота 0,89 (25 из 28), на чистых critical 0 из 8 | точность 0,14: лишних замечаний 151 |
| Gemini — модель жюри | [`reliz_w4_19_35_md_3e7133c_gemini_3_8_flash_2`][gem] | `3e7133c2` | **на релизной модели не измерено:** квота `gemini-3.8-flash` кончилась на первом вызове (429), цепочка ушла на 3.6-flash и 3.5-flash-lite — К 3/5 и 5/5, С 8 и 9 из 20, 10,7 мин | это потолок запасных моделей, не качество Flash; ваш прогон командой 2 — новые данные |
| Ответы владельца: прежний экзамен, 33 трудные реплики | [аудит F4][f4] | влито в 16:50 | целиком верно **17 из 33** | у лидера рейтинга — 25 из 30 на заранее зафиксированном наборе |

### Где мы слабы и почему

* **Ложные запреты на чистых ТЗ.** 3 из 12 на haiku. Ручная сверка Codex на прежнем коде `3e7133c2`: из 5 critical на
  чистых подтвердился **один** (в выписке доступ заканчивается в 12:00, а приёмка требует файл в 12:14 — настоящий
  конфликт), остальные — один major, два minor и одна ложная тревога ([разбор 42 решений][cleanrev]).
* **Мигание.** Тот же код даёт 23–25 из 25. Один прогон 25/25 — не гарантия; поэтому показываем все три.
* **Gemini.** Бесплатная квота жюри может кончиться на середине прогона; агент переходит на запасную модель и
  пишет это в паспорт, но качество запасных моделей ниже (строка выше).
* **DOCX и PDF** на `3e7133c2` давали 21 и 21 из 25 против 22–25 у md; на коде релиза — 24 и 23, но по одному
  прогону на формат: устойчивость форматов не измерена.
* **Шум.** На корпусе 151 лишнее замечание при полноте 0,89: агент лучше находит, чем молчит.

### Что уже исправлено (было → стало, те же наборы)

* С6, С9, С17 на sonnet — 2, 2 и 1 из 3 прогонов → **3 из 3** (`3e7133c2` → `d013c123`, линзы №28, судья №26).
* Чистые open2 (4 ТЗ, haiku): critical 2 → **0**, ложных запретов 2 → **0**; всего на 12 чистых critical 5 → 3.
* PDF и DOCX sonnet: ключевые 21 и 21 → **24 и 23** (по одному прогону).
* Gemini: `doctor --live` на рабочем ключе падал «deadline 8s is too short» → исправлено (`418f0884`, тест
  `tests/v2/test_31_gemini_deadline.py`).

### Заявки после 21:00 — не в релизе на момент записи

Числа автора заявки и наш строгий пересчёт тех же `report.json`. Войдёт ли заявка в релиз, решает интегратор №46 по
правилу «sonnet ×2 — оба ≥ 24/25 и К 5/5 critical, на чистых critical не больше».

| Заявка | Что меняет | Прогон | Автор | Строгий пересчёт №58 | verify |
| :--- | :--- | :--- | :--- | :--- | :--- |
| Codex / №50 (`af977b20` → `f3224f9e`) | ответы владельца, точность | [`kandidat_codex55_56d098cf_sonnet_1`, `_2`][codex] | 25/25 и 24/25 | **24/25 и 23/25** (счётчиком ветки №31 — 24 и 24): в №1 С9 засчитал живой арбитр, его решения в закоммиченном кэше нет | OK, 88 и 85 |
| №52 (`ac9d2a52`) | мигание С8, С12, С15 | [`w5_52_md_ac9d2a52_sonnet_1…3`][fl] | 25, 23, 25 | **25, 23, 25** — совпало | OK |
| №50: три контрольных конфликта ответа владельца с ТЗ | судья | [`w5_50_owner_f3224f9e`][own] | 3 из 3 подтверждены (QR — major вместо critical) | не пересчитывали | — |
| №56: экзамен ответов v3 | ответы владельца | набор, ключи и порог закоммичены до первого прогона ([`answers_exam_v3`][ex3]) | порог ≥ 27/30 | **ещё не измерено** | — |

## 4. Как повторить любой прогон

Каталоги официального ТЗ и чистых наборов лежат в ветках замеров, а не в `release` (там только код и итоговые отчёты).
Достаточно достать один каталог и пересчитать его кодом релиза — модель не вызывается:

```bash
git fetch origin v2/31-eval
D=evaluation/v2/measurements/reliz_w4_19_50_md_d013c12_sonnet_3     # любой каталог из таблицы
git restore --source=fc0393c8 -- $D
python -m evaluation.v2.score $D/report.json                          # К, С, ключевые 25, дубли
python -m bcc_review verify $D/report.json release/input/requirements.md
rm -rf $D                                                             # вернуть дерево как было
```

Для PDF и DOCX — `git fetch origin v2/53-formats`, `--source=fa2c2edf`, исходник `release/input/requirements.pdf`
(`.docx`); для №52 — `v2/52-flicker`, `--source=0f93b617`. Повторить живой прогон целиком:
`python -m bcc_review release/input/requirements.md out/s.md --provider claude_cli --model sonnet --no-cache`.

Код прогона записан в его паспорте (`run.commit`). Прогоны №31 сделаны из ветки замера: её `src/` и `pyproject.toml`
совпадают с `d013c123` (сверено `python -m evaluation.v2.final --commit d013c12`). У двух прогонов `verify`
предупреждает «отчёт построен на рабочей копии с незакоммиченными изменениями» (`run.dirty`): замер шёл в копии,
куда тем временем писались файлы замеров; какие именно файлы были изменены, паспорт не хранит.

Полные таблицы, история всех замеров дня и ворота качества — [`evaluation/v2/RESULTS.md` в ветке №31][results].
Внешний рейтинг Codex по 87 репозиториям (мы вторые) — [ветка `codex/precision-owner`][rating].

[s1]: https://github.com/diiaanns07-droid/winnersOFbankCCbyMNU/tree/fc0393c895e3fd1e39d6f0087ebb9482ba067079/evaluation/v2/measurements/reliz_w4_19_50_md_d013c12_sonnet_1
[s2]: https://github.com/diiaanns07-droid/winnersOFbankCCbyMNU/tree/fc0393c895e3fd1e39d6f0087ebb9482ba067079/evaluation/v2/measurements/reliz_w4_19_50_md_d013c12_sonnet_2
[s3]: https://github.com/diiaanns07-droid/winnersOFbankCCbyMNU/tree/fc0393c895e3fd1e39d6f0087ebb9482ba067079/evaluation/v2/measurements/reliz_w4_19_50_md_d013c12_sonnet_3
[h1]: https://github.com/diiaanns07-droid/winnersOFbankCCbyMNU/tree/fc0393c895e3fd1e39d6f0087ebb9482ba067079/evaluation/v2/measurements/reliz_w4_19_50_md_d013c12_haiku_1
[pdf]: https://github.com/diiaanns07-droid/winnersOFbankCCbyMNU/tree/fa2c2edf07eaa619434b53f93e92eae17a17b0b7/evaluation/v2/measurements/w5_53_base_pdf_973ce4d_sonnet_1
[docx]: https://github.com/diiaanns07-droid/winnersOFbankCCbyMNU/tree/fa2c2edf07eaa619434b53f93e92eae17a17b0b7/evaluation/v2/measurements/w5_53_base_docx_973ce4d_sonnet_1
[pdf0]: https://github.com/diiaanns07-droid/winnersOFbankCCbyMNU/tree/fc0393c895e3fd1e39d6f0087ebb9482ba067079/evaluation/v2/measurements/reliz_w4_18_45_pdf_3e7133c_sonnet_1
[docx0]: https://github.com/diiaanns07-droid/winnersOFbankCCbyMNU/tree/fc0393c895e3fd1e39d6f0087ebb9482ba067079/evaluation/v2/measurements/reliz_w4_18_45_docx_3e7133c_sonnet_1
[clean]: https://github.com/diiaanns07-droid/winnersOFbankCCbyMNU/tree/fc0393c895e3fd1e39d6f0087ebb9482ba067079/evaluation/v2/measurements/reliz_w4_19_50_cistye_d013c12_haiku
[corpus]: https://github.com/diiaanns07-droid/winnersOFbankCCbyMNU/tree/fc0393c895e3fd1e39d6f0087ebb9482ba067079/evaluation/v2/corpus_results/reliz_w4_20_00_korpus_d013c12_haiku
[gem]: https://github.com/diiaanns07-droid/winnersOFbankCCbyMNU/tree/fc0393c895e3fd1e39d6f0087ebb9482ba067079/evaluation/v2/measurements/reliz_w4_19_35_md_3e7133c_gemini_3_8_flash_2
[f4]: https://github.com/diiaanns07-droid/winnersOFbankCCbyMNU/blob/91f8b812c5fa2111f9f06caf2588352ed3dfd87d/docs/plan-v2/f4/INDEPENDENT_AUDIT.md
[cleanrev]: https://github.com/diiaanns07-droid/winnersOFbankCCbyMNU/blob/57c2a7d70f00a043e73fc38b818b949a20c8330a/evaluation/v2/precision_owner/clean-review.md
[codex]: https://github.com/diiaanns07-droid/winnersOFbankCCbyMNU/tree/fc0393c895e3fd1e39d6f0087ebb9482ba067079/evaluation/v2/measurements/kandidat_codex55_56d098cf_sonnet_1
[fl]: https://github.com/diiaanns07-droid/winnersOFbankCCbyMNU/tree/0f93b617b182346171b975526f3568d2d6529c06/evaluation/v2/measurements
[own]: https://github.com/diiaanns07-droid/winnersOFbankCCbyMNU/tree/fa8b770fdc34f52b9b99ec6de813972b6c973f0b/evaluation/v2/measurements/w5_50_owner_f3224f9e
[ex3]: https://github.com/diiaanns07-droid/winnersOFbankCCbyMNU/tree/28d6c8c8a13969388d716b7406d6015757dcbb8c/docs/plan-v2/f4/answers_exam_v3
[results]: https://github.com/diiaanns07-droid/winnersOFbankCCbyMNU/blob/fc0393c895e3fd1e39d6f0087ebb9482ba067079/evaluation/v2/RESULTS.md
[rating]: https://github.com/diiaanns07-droid/winnersOFbankCCbyMNU/blob/5f7a7bea769a8da4589142de9b73ce8eb573355b/reports/%D0%A1%D0%B8%D0%BB%D1%8C%D0%BD%D0%B5%D0%B9%D1%88%D0%B8%D0%B5%20%D1%80%D0%B5%D1%88%D0%B5%D0%BD%D0%B8%D1%8F%20%D0%BF%D0%B5%D1%80%D0%B5%D0%B4%20%D1%81%D0%B4%D0%B0%D1%87%D0%B5.md
