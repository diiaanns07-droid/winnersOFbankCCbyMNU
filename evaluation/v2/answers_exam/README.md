# Экзамен ответов владельца

Код серии `7ccc74a60c350dad8b2a5f9183bbad6912f32c5b`. Основа `bcc/v2` на `fda4d7ca35afa4eda4a769fdd20722749d34d4d1`. [Входы, опубликованные исходные отчёты для official и qr, команды запуска](../../../docs/plan-v2/f4/answers_exam/README.md).

Параметры каждого модельного прогона — `--provider claude_cli --model sonnet --no-cache --no-html`. Для этапа answered также `--answers … --revise`.

Первый отчёт по автокредиту передан в [коммите 695671ad](https://github.com/diiaanns07-droid/winnersOFbankCCbyMNU/blob/695671adfab22c6a2c10c4a6d8b712c947418044/evaluation/v2/answers_exam/car-loan/baseline.md). [Ответы F4](https://github.com/diiaanns07-droid/winnersOFbankCCbyMNU/blob/1ed82f346d53ae519cddf116311e1e1f82f32eab/docs/plan-v2/f4/answers_exam/car-loan/answers.md) поступили после этого прогона.

| ТЗ | Отчёт | Статус агента | Фактическая модель | Этапы прогона | Проверка артефактов |
|---|---|---|---|---|---|
| car-loan | [answered](car-loan/answered.md) | complete | claude-sonnet-5-5 | [20261127-153058-37ff](car-loan/runs/20261127-153058-37ff/stages/) | [OK](car-loan/answered.verify.txt) |
| car-loan | [baseline](car-loan/baseline.md) | complete | claude-sonnet-5-5 | [20261127-151203-084f](car-loan/runs/20261127-151203-084f/stages/) | [OK](car-loan/baseline.verify.txt) |
| car-loan | [reread](car-loan/reread.md) | complete | claude-sonnet-5-5 | [20261127-153530-b252](car-loan/runs/20261127-153530-b252/stages/) | [OK](car-loan/reread.verify.txt) |
| official | [answered](official/answered.md) | complete | claude-sonnet-5-5 | [20261127-151551-bf95](official/runs/20261127-151551-bf95/stages/) | [OK](official/answered.verify.txt) |
| official | [reread](official/reread.md) | complete | claude-sonnet-5-5 | [20261127-152128-e743](official/runs/20261127-152128-e743/stages/) | [OK](official/reread.verify.txt) |
| qr | [answered](qr/answered.md) | complete | claude-sonnet-5-5 | [20261127-152353-783d](qr/runs/20261127-152353-783d/stages/) | [OK](qr/answered.verify.txt) |
| qr | [reread](qr/reread.md) | complete | claude-sonnet-5-5 | [20261127-152810-495d](qr/runs/20261127-152810-495d/stages/) | [OK](qr/reread.verify.txt) |

27.11.2026 15:38:12 по Астане. Серия завершена. Для каждой редакции выполнена команда verify с соответствующим входным файлом.

Исправленные ТЗ — [official](official/answered.revised.md), [qr](qr/answered.revised.md), [car-loan](car-loan/answered.revised.md). Данные обработки ответов и правки находятся в `runs/<id>/stages/recheck.json` каждого прогона answered.
