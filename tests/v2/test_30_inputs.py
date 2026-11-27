"""№30: правила и офлайн-отчёт не падают на трудных входах и не выдумывают шапку документа из таблицы полей."""
from __future__ import annotations

from pathlib import Path

import pytest

from bcc_review.v2 import docview, rules
from bcc_review.v2.rules import offline

HARD = {
    "empty.md": "",
    "spaces.md": "   \n\n\t\n",
    "only_heading.md": "# Заголовок\n",
    "only_code.md": "```\nGET /x\n200. ok\n```\n",
    "open_fence.md": "# Т\n```\nPOST /a\n| a | b |\n",
    "ragged_table.md": "| A | B | C |\n|---|\n| 1 |\n| 1 | 2 | 3 | 4 | 5 |\n|||\n",
    "pipes.md": "| Поле | Тип |\n| --- | --- |\n| a \\| b | string \\| null |\n",
    "long_line.md": "Требование: " + ("сумма 100 ₸ и код 404 " * 4000) + "\n",
    "many_lines.md": "\n".join(f"{i}. Система возвращает 200, если сумма {i} ₸." for i in range(3000)),
    "deep_headings.md": "\n".join("#" * (i % 6 + 1) + f" Раздел {i}" for i in range(500)),
    "rtl_emoji.md": "# Тест 🚀\nمرحبا ‏‎ Клиент 👍 получает ответ 200.\n\u0000\u0007\n",
    "only_numbers.md": "200\n400\n404\n500\n201.\n",
    "status_noise.md": "200. \n404 —\n**500.**\nОтвет 999\nвернуть 1000\n",
    "html_comments.md": "<!-- \n# Требования\n<!-- вложенный -->\nТекст --> хвост\n",
    "weird_methods.md": "| Поле | Метод 1 | Метод 2 | Метод 3 |\n|---|---|---|---|\n| REST type | GET | POST |\n"
                        "| Request URL | /a |\n**Метод 9.** DELETE `/`\n",
}


@pytest.mark.parametrize("name", sorted(HARD))
def test_rules_and_offline_survive_hard_inputs(tmp_path: Path, name: str) -> None:
    p = tmp_path / name
    p.write_text(HARD[name], encoding="utf-8")
    view = docview.load(str(p))
    out = rules.run(view)
    assert not out.get("warnings"), out.get("warnings")
    for c in out["candidates"]:
        for e in c["evidence"]:
            assert isinstance(e["line"], int)
    rep = offline.build(view)
    assert isinstance(rep, dict)
    assert offline.render_brief(rep)


def test_binary_garbage_txt(tmp_path: Path) -> None:
    p = tmp_path / "garbage.txt"
    p.write_bytes(bytes(range(256)) * 20)
    try:
        view = docview.load(str(p))
    except Exception:  # noqa: BLE001 — нечитаемый файл отвергает читатель, правил это не касается
        return
    out = rules.run(view)
    assert not out.get("warnings")


def _versions(tmp_path: Path, text: str) -> list[dict]:
    p = tmp_path / "doc.md"
    p.write_text(text, encoding="utf-8")
    out = rules.run(docview.load(str(p)))
    return [c for c in out["candidates"] if c["source"] == "rules:placeholder.version"]


def test_field_table_is_not_document_passport(tmp_path: Path) -> None:
    text = """# Перевыпуск карты: поля API

Поле | Обязательность
--- | ---
cardId | да
reason | да
"""
    assert _versions(tmp_path, text) == []
    text = "ПЕРЕВЫПУСК\n\n3. Параметры\nСрок выпуска\t5 рабочих дней\nСтоимость\t1 500 тг\n"
    assert _versions(tmp_path, text) == []


def test_passport_without_version_is_flagged(tmp_path: Path) -> None:
    text = """# Доработка

| Параметр | Значение |
| --- | --- |
| Наименование задачи | Перевыпуск карты |
| Аналитик | Команда карт |

## Требования
Система показывает стоимость.
"""
    assert len(_versions(tmp_path, text)) == 1
    assert _versions(tmp_path, text.replace("| Аналитик | Команда карт |",
                                            "| Аналитик | Команда карт |\n| Версия | 1.2 от 01.10.2026 |")) == []
