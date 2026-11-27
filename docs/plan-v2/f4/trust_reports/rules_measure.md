# Изолированная проверка восьми правил F4

Сравнивается сборка 15:30 `c6aa9b5` и копия `90b98dbd` с одной вставкой в `src/bcc_review/v2/prompts/judge.md`. Перед фразой «### Шаг 5. Тексты дефекта» вставлены первые два столбца восьми строк утренней шкалы. Третий столбец с примерами исключён. Никакие сведения из эталонов open2 и blind3 в текст добавки не переносились. Исторический вариант №01 замерялся на другой базе. [Точная вставка](rules-only.txt) · [Исходные правила](https://github.com/diiaanns07-droid/winnersOFbankCCbyMNU/blob/45e62d2/docs/plan-v2/f4/calibration.md) · [Немодифицированный судья](https://github.com/diiaanns07-droid/winnersOFbankCCbyMNU/blob/c6aa9b5/src/bcc_review/v2/prompts/judge.md).

До просмотра выходов определены те же показатели, что в дневном контроле. На четырёх исправленных ТЗ считаются все critical и major, оценка каждой по шкале F4 и вердикты по двум направлениям. На четырёх дефектных парах сравниваются найденные К и С, уровень каждой и все потери. Стабильное улучшение нельзя выводить из одного повтора. Замер дополнительно отвечает, что происходит, когда к фактически выбранной сборке добавлены ровно эти общие правила. [Базовый разбор](integration_review.md) · [Паспорта контроля](integration/) · [Входы рецензентов](reviewer-inputs.zip).

Чтобы собрать тот же текст промпта, выполните команду Python из чистой рабочей копии `c6aa9b5`, предварительно задав в `F4_AUDIT` путь к папке `docs/plan-v2/f4` аудиторской ветки. Затем выполните команды попарного замера из основного отчёта на четырёх исправленных и четырёх исходных ТЗ. [Команды запуска судьи и оценщика](../trust_after.md).

```python
from pathlib import Path
import os

prompt = Path("src/bcc_review/v2/prompts/judge.md")
original = prompt.read_text(encoding="utf-8")
rules = (Path(os.environ["F4_AUDIT"]) / "trust_reports/rules-only.txt").read_text(encoding="utf-8")
anchor = "### Шаг 5. Тексты дефекта"
assert original.count(anchor) == 1 and rules not in original
prompt.write_text(original.replace(anchor, rules + chr(10) + anchor), encoding="utf-8", newline="\n")
```
