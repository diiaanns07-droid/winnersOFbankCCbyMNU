"""№30: точные правила не дают critical/major на действительно чистых ТЗ (набор №20 `evaluation/v2/clean`)
и правильно читают приёмы оформления, на которых раньше ошибались."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from bcc_review.v2 import docview, rules

ROOT = Path(__file__).resolve().parents[2]
CLEAN = sorted((ROOT / "evaluation" / "v2" / "clean").glob("*/source.*"))
HAS_PDF = importlib.util.find_spec("fitz") is not None or importlib.util.find_spec("pymupdf") is not None


def _run_text(tmp_path: Path, text: str) -> dict:
    p = tmp_path / "doc.md"
    p.write_text(text, encoding="utf-8")
    return rules.run(docview.load(str(p)))


def _serious(out: dict) -> list[str]:
    return [f"{c['severity']} {c['source']}: {c['title']}" for c in out["candidates"]
            if c["severity"] in ("critical", "major")]


@pytest.mark.parametrize("path", CLEAN, ids=lambda p: f"{p.parent.name}/{p.name}")
def test_clean_set_has_no_serious_rule_candidates(path: Path) -> None:
    if path.suffix == ".pdf" and not HAS_PDF:
        pytest.skip("нет pymupdf")
    if path.suffix not in (".md", ".docx", ".pdf"):
        pytest.skip("не документ")
    out = rules.run(docview.load(str(path)))
    assert _serious(out) == []
    assert not out.get("warnings")


def test_clean_set_is_present() -> None:
    assert len({p.parent.name for p in CLEAN}) >= 8


TWO_COLUMN_METHODS = """# Заявки

## Требования
Приложение создаёт черновик и отправляет заявку через дочерний документ «REST API» (методы 1 и 2).
При любом ответе с ошибкой приложение показывает текст поля `message` под кнопкой.

## Часть B. REST API

| Поле | Метод 1 | Метод 2 |
| :--- | :--- | :--- |
| **Description** | Отправка заявки на рассмотрение | Создание черновика заявки |
| **REST type** | POST | POST |
| **Request URL** | `https://api.example.local/req/v1/submit` | `https://api.example.local/req/v1/drafts` |
"""


def test_methods_in_table_columns_are_two_methods(tmp_path: Path) -> None:
    from bcc_review.v2.rules._text import build_doc
    from bcc_review.v2.rules.api import find_methods

    p = tmp_path / "doc.md"
    p.write_text(TWO_COLUMN_METHODS, encoding="utf-8")
    ms = find_methods(build_doc(docview.load(str(p))))
    assert sorted(m.url for m in ms) == ["/req/v1/drafts", "/req/v1/submit"]
    out = _run_text(tmp_path, TWO_COLUMN_METHODS)
    # «создаёт черновик» описан методом 2; показ поля ответа — не обещание отдельного чтения
    assert _serious(out) == []


def test_numbered_method_line_is_a_method(tmp_path: Path) -> None:
    text = """# Настройки

## Требования
Экран показывает сохранённые значения настроек клиента.

## API

| Поле | Значение |
| :--- | :--- |
| **Description** | Метод 1. Сохранение настроек |
| **REST type** | PUT |
| **Request URL** | `https://api.example.local/s/v1/settings` |

### Метод чтения
**Метод 2.** GET `/s/v1/settings` — возвращает сохранённые настройки.
"""
    out = _run_text(tmp_path, text)
    assert not [c for c in out["candidates"] if c["source"] == "rules:promises.read_operation"]


def test_still_flags_read_promise_without_read_method(tmp_path: Path) -> None:
    text = """# Настройки

## Требования
Экран показывает сохранённые значения настроек клиента.

## API

| Поле | Значение |
| :--- | :--- |
| **Description** | Сохранение настроек |
| **REST type** | PUT |
| **Request URL** | `https://api.example.local/s/v1/settings` |
"""
    out = _run_text(tmp_path, text)
    assert [c for c in out["candidates"] if c["source"] == "rules:promises.read_operation"]


STATUSES = """# Сервис

## API

| Поле | Значение |
| :--- | :--- |
| **REST type** | POST |
| **Request URL** | `https://api.example.local/x/v1/items` |

### Статусы
**200.** Готово.
**400.** Нарушен формат запроса.
**500.** Внутренняя ошибка.

## Критерии приемки
| Условие | Действие | Результат |
| :--- | :--- | :--- |
| Покупка 1 250,00 ₸ | Частичный возврат 250,00 ₸ | Сумма уменьшилась |
| Сервис платежей недоступен | Попытка платежа завершилась ответом 503 | Повтор через 5 минут |
"""


def test_amount_and_upstream_code_are_not_statuses(tmp_path: Path) -> None:
    out = _run_text(tmp_path, STATUSES)
    assert not [c for c in out["candidates"] if c["source"].startswith("rules:api.status_")]


def test_undeclared_code_still_flagged(tmp_path: Path) -> None:
    out = _run_text(tmp_path, STATUSES + "\nЕсли элемент уже существует, метод возвращает 409.\n")
    assert [c for c in out["candidates"] if c["source"] == "rules:api.status_409"]
    out = _run_text(tmp_path, STATUSES + "\nПри перегрузке метод возвращает 503.\n")
    assert [c for c in out["candidates"] if c["source"] == "rules:api.status_503"]


def test_method_summary_table_declares_statuses(tmp_path: Path) -> None:
    text = STATUSES + """
### Остальные методы
| Метод | REST type и URL | Ответ 201 | Ошибки |
| :--- | :--- | :--- | :--- |
| 2. Ссылка | POST `/x/v1/items/{id}/link` | Ссылка | 404 `ITEM_NOT_FOUND`; 410 `ITEM_EXPIRED` — срок истёк |

Если метод 2 вернул 410, показывается «Срок истёк»; ответ 201 содержит ссылку.
"""
    out = _run_text(tmp_path, text)
    assert not [c for c in out["candidates"] if c["source"] in ("rules:api.status_410", "rules:api.status_201")]


def test_same_case_with_different_error_names_is_not_a_conflict(tmp_path: Path) -> None:
    text = """# Сервис

## API

| Поле | Значение |
| :--- | :--- |
| **REST type** | POST |
| **Request URL** | `https://api.example.local/o/v1/orders` |

### Логика работы метода
1. Проверить суточный предел: если у клиента уже 10 заказов за сутки, вернуть 422 `DAILY_LIMIT_EXCEEDED`.

### Статусы
**200.** Заказ создан.
**409.** Ключ уже использован клиентом для заказа с другими параметрами: `KEY_CONFLICT`.
**422.** Нарушено бизнес-правило.
"""
    out = _run_text(tmp_path, text)
    assert not [c for c in out["candidates"] if c["source"].startswith("rules:api.same_case")]
