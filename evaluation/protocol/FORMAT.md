# Формат передачи №16

UTF-8, LF. Одна запись JSON на строку. Поля case_id, family, source_sha256 (байты канонического MD), label_id, defect_id, issue_type, criterion, severity, anchors, expected_outcome, explanation обязательны в передаче. У clean тип и серьёзность равны null, anchors пуст. Для present опора содержит role, quote, locator, line, start и end. Для конфликта используются роли a и b. Для пропуска promise и boundary. Для контрольной совместимой пары есть дополнительная строка absent с ролями control. anchor_policy=all. Поля root_id, preconditions, outcomes, impact, expected_question и options задают смысл. defect_id уникален для версии, root_id устойчив в редакциях. Роль разметчика хранится в annotator, решение человека — в human_review.

Manifest связывает case_id с одним primary_render и представлениями, для каждого указывает format, render_id, path, sha256. Соседние файлы inputs находятся у хранителя. Система координат MD использует номера строк с 1 и символьные смещения с 0 внутри строки. Первичные файлы исходов сохраняют run, findings, questions, diff и checklist без переписывания. В реестре каждой измеренной строки есть case_id, corpus_version, agent_sha, source_sha256, requested_mode, actual_mode, actual_model и ссылка на отчёт. Неполученные модель, оценка и длительность равны null.

## Контрольный расчёт

В учебном примере агент дважды описал одну причину, нашёл вторую, пропустил третью и объявил тревогу на чистом документе. До исполнения зафиксированы TP 2, FP 1, FN 1, D 1, P = R = F1 = 2/3, строгая P = 2/4. На единственном чистом документе одна ложная тревога. Для чистого документа без прогнозов P, R и F1 имеют значение null. Сравнение только по типу ошибочно засчитало бы нерелевантную цитату о расписании. Полное строковое равенство теряет опору, процитированную внутри более длинной строки. Используем совместимость типов и привязку к опорам в пределах одного документа, затем проверяем смысл.

Из корня ветки:

```text
python -m evaluation.harness --gold evaluation/protocol/example/labels.jsonl --pred evaluation/protocol/example/predictions.jsonl --manifest evaluation/protocol/example/manifest.json --out out/ie-hand.json
```
