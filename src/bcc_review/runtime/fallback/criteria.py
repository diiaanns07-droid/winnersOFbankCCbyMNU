"""Резервный справочник критериев (пока не влит общий ``criteria.toml`` модуля №05)."""

from __future__ import annotations

from typing import Any

CRITERIA: dict[str, dict[str, Any]] = {
    "necessary": {"name": "Необходимость", "scope": "requirement", "standard": "ISO/IEC/IEEE 29148 5.2.5 a",
                  "question": "Без требования останется пробел; требование не дублирует другое."},
    "appropriate": {"name": "Уместность", "scope": "requirement", "standard": "ISO/IEC/IEEE 29148 5.2.5 b",
                    "question": "Говорит «что», а не «как»; нет лишних решений реализации."},
    "unambiguous": {"name": "Однозначность", "scope": "requirement", "standard": "ISO/IEC/IEEE 29148 5.2.5 c; IEEE 830 4.3.2",
                    "question": "Одно толкование; термины, единицы, часовые пояса определены."},
    "complete": {"name": "Полнота", "scope": "requirement", "standard": "ISO/IEC/IEEE 29148 5.2.5 d; IEEE 830 4.3.3",
                 "question": "Есть субъект, условие, действие, ограничения, ошибки и границы."},
    "singular": {"name": "Единичность", "scope": "requirement", "standard": "ISO/IEC/IEEE 29148 5.2.5 e",
                 "question": "Одно обязательство в пункте."},
    "feasible": {"name": "Осуществимость", "scope": "requirement", "standard": "ISO/IEC/IEEE 29148 5.2.5 f",
                 "question": "Реализуемо при описанной архитектуре и данных."},
    "verifiable": {"name": "Проверяемость", "scope": "requirement", "standard": "ISO/IEC/IEEE 29148 5.2.5 g; IEEE 830 4.3.6",
                   "question": "Выполнение можно объективно доказать тестом, анализом или инспекцией."},
    "correct": {"name": "Корректность", "scope": "requirement", "standard": "ISO/IEC/IEEE 29148 5.2.5 h; IEEE 830 4.3.1",
                "question": "Соответствует предметной области, не противоречит другим пунктам и приёмке."},
    "conforming": {"name": "Соответствие шаблону", "scope": "requirement", "standard": "ISO/IEC/IEEE 29148 5.2.5 i",
                   "question": "Есть ID, модальность, единая терминология."},
    "set_complete": {"name": "Полнота набора", "scope": "set", "standard": "ISO/IEC/IEEE 29148 5.2.6 a; IEEE 830 4.3.3",
                     "question": "Обещанные функции, данные, ошибки и интерфейсы описаны."},
    "set_consistent": {"name": "Согласованность набора", "scope": "set", "standard": "ISO/IEC/IEEE 29148 5.2.6 b; IEEE 830 4.3.4",
                       "question": "Нет требований, дающих несовместимые исходы для одного сценария."},
    "set_feasible": {"name": "Осуществимость набора", "scope": "set", "standard": "ISO/IEC/IEEE 29148 5.2.6 c",
                     "question": "Набор реализуем вместе в рамках ограничений."},
    "set_comprehensible": {"name": "Понятность набора", "scope": "set", "standard": "ISO/IEC/IEEE 29148 5.2.6 d",
                           "question": "Единая терминология, ясная структура."},
    "set_validatable": {"name": "Возможность валидации", "scope": "set", "standard": "ISO/IEC/IEEE 29148 5.2.6 e",
                        "question": "Набор покрыт критериями приёмки."},
    "ranked": {"name": "Ранжирование", "scope": "set", "standard": "IEEE 830 4.3.5",
               "question": "Указаны важность и стабильность требований."},
    "modifiable": {"name": "Модифицируемость", "scope": "set", "standard": "IEEE 830 4.3.7",
                   "question": "Нет дублирования, структура позволяет менять пункты."},
    "traceable": {"name": "Прослеживаемость", "scope": "set", "standard": "IEEE 830 4.3.8",
                  "question": "Есть ID, источник требования, связь с приёмкой."},
}


def load_criteria() -> dict[str, dict[str, Any]]:
    return {k: dict(v) for k, v in CRITERIA.items()}
