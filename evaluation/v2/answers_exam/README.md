# Экзамен ответов владельца

Код серии `7ccc74a60c350dad8b2a5f9183bbad6912f32c5b`. Основа `bcc/v2` на `fda4d7ca35afa4eda4a769fdd20722749d34d4d1`. [Входы, опубликованные исходные отчёты для official и qr, команды запуска](../../../docs/plan-v2/f4/answers_exam/README.md).

Параметры каждого модельного прогона — `--provider claude_cli --model sonnet --no-cache --no-html`. Для этапа answered также `--answers … --revise`.

| ТЗ | Отчёт | Статус агента | Фактическая модель | Этапы прогона | Проверка артефактов |
|---|---|---|---|---|---|
| car-loan | [baseline](car-loan/baseline.md) | complete | claude-sonnet-5-5 | [20261127-151203-084f](car-loan/runs/20261127-151203-084f/stages/) | [OK](car-loan/baseline.verify.txt) |

27.11.2026 15:21:05 по Астане. Выполняется official/answered.
