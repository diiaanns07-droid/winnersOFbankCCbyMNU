"""№30: полнота офлайн-режима (без модели) — новые общие правила; на чистых ТЗ не срабатывают."""
from __future__ import annotations

from pathlib import Path

from bcc_review.v2 import docview, rules

ROOT = Path(__file__).resolve().parents[2]


def _run(tmp_path: Path, text: str) -> dict:
    p = tmp_path / "doc.md"
    p.write_text(text, encoding="utf-8")
    return rules.run(docview.load(str(p)))


def _src(out: dict, prefix: str) -> list[dict]:
    return [c for c in out["candidates"] if c["source"].startswith(prefix)]


CAP = """# Напоминания об оплате

## Функциональные требования
* **ФТ-1.** Когда до даты платежа остаётся 3 дня, клиент получает SMS. Клиенту приходит не более одного SMS в сутки.
* **ФТ-2.** Если клиент изменил дату платежа, новое наступление срока вызывает SMS независимо от истории отправок.
"""


def test_period_cap_vs_regardless(tmp_path: Path) -> None:
    out = _run(tmp_path, CAP)
    c = _src(out, "rules:conflicts.event_quantity")
    assert len(c) == 1 and c[0]["severity"] == "critical"
    assert {e["line"] for e in c[0]["evidence"]} == {4, 5}


def test_period_cap_without_regardless_is_silent(tmp_path: Path) -> None:
    out = _run(tmp_path, CAP.replace(" независимо от истории отправок", ", но не чаще лимита ФТ-1"))
    assert _src(out, "rules:conflicts.event_quantity") == []
    # «независимо от» о другом предмете — не конфликт
    out = _run(tmp_path, CAP.replace("вызывает SMS независимо от истории отправок",
                                     "пересчитывает график независимо от истории изменений"))
    assert _src(out, "rules:conflicts.event_quantity") == []


def test_official_offline_finds_cap_conflict() -> None:
    out = rules.run(docview.load(str(ROOT / "release" / "input" / "requirements.md")))
    c = _src(out, "rules:conflicts.event_quantity")
    assert len(c) == 1 and c[0]["severity"] == "critical"


REPEAT = """# Начисление бонусов

## Требования к интеграции
Сервис бонусов получает от процессинга событие о покупке. Повторная доставка одного события не меняет начисленный бонус.
"""


def test_repeat_delivery_without_key(tmp_path: Path) -> None:
    c = _src(_run(tmp_path, REPEAT), "rules:ops.repeat_key")
    assert len(c) == 1 and c[0]["severity"] == "major" and c[0]["evidence"][0]["line"] == 4


def test_repeat_delivery_with_key_or_reference_is_silent(tmp_path: Path) -> None:
    for text in (
        REPEAT.replace("Повторная доставка одного события", "Повторная доставка события с тем же `eventId`"),
        REPEAT.replace("не меняет начисленный бонус", "обрабатывается по ключу идемпотентности"),
        REPEAT.replace(".\n", "; повторная доставка — по ФТ-9.\n", 1).replace(
            " Повторная доставка одного события не меняет начисленный бонус.", ""),
        "# Доставка\nЗа повторную доставку курьером банк начисляет плату 500 ₸.\n",
    ):
        assert _src(_run(tmp_path, text), "rules:ops.repeat_key") == [], text


def test_new_offline_rules_silent_on_clean_documents() -> None:
    paths = sorted((ROOT / "evaluation" / "v2" / "clean").glob("*/source.md"))
    paths += sorted((ROOT / "evaluation" / "v2" / "open2").glob("*_clean/source.md"))
    paths += sorted((ROOT / "evaluation" / "dev" / "corpus" / "cases").glob("*.base/source.md"))
    paths += sorted((ROOT / "tests" / "v2" / "fixtures" / "12_styles").glob("*clean*.md"))
    assert len(paths) >= 20
    for p in paths:
        out = rules.run(docview.load(str(p)))
        bad = [c["title"] for c in out["candidates"]
               if c["source"].startswith(("rules:ops.", "rules:conflicts.event_quantity", "rules:language.nfr_no_share"))]
        assert bad == [], (p, bad)


NFR = """# Выписка

## Нефункциональные требования
Сервис формирует выписку в течение 30 секунд после запроса клиента.
"""


def test_nfr_time_without_share(tmp_path: Path) -> None:
    c = _src(_run(tmp_path, NFR), "rules:language.nfr_no_share")
    assert len(c) == 1 and c[0]["severity"] == "major" and c[0]["evidence"][0]["line"] == 4


def test_nfr_share_anywhere_or_batch_is_silent(tmp_path: Path) -> None:
    for text in (
        NFR.replace("после запроса клиента.", "после запроса клиента для 95 % запросов."),
        NFR.replace("после запроса клиента.", "после запроса для 95 процентов запросов."),
        NFR + "Методы отвечают не дольше 1 с для 99 % запросов при нагрузке 50 в секунду.\n",  # доля задана рядом
        NFR.replace("Сервис формирует выписку", "Пакетный расчёт за месяц выполняется"),
        NFR.replace("## Нефункциональные требования", "## Функциональные требования"),
    ):
        assert _src(_run(tmp_path, text), "rules:language.nfr_no_share") == [], text
