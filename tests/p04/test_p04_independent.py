"""Набор 4. Независимый документ другой темы и структуры.

Число требований, исключения и замечания определяются только текущим входом: другой документ
даёт свои числа, повторный прогон кейса после него даёт тот же результат, а в коде модуля
нет констант конкретного кейса.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import bcc_review.analysis.inventory as inventory_module
from bcc_review.analysis.inventory import build_inventory
from p04_support import QuoteModel, assert_invariants, fixture_document

MEETING_SPEC = {
    "items": [
        {"kind": "functional", "source_id": "REQ-BK-01", "text": "Минимальная длительность брони — 15 минут", "quotes": ["от 15"]},
        {"kind": "functional", "source_id": "REQ-BK-01", "text": "Максимальная длительность брони — 240 минут", "quotes": ["до 240 минут"]},
        {"kind": "functional", "source_id": "REQ-BK-01", "text": "Длительность брони кратна 15 минутам", "quotes": ["Интервал кратен 15 минутам"]},
        {"kind": "functional", "source_id": "REQ-BK-02", "text": "Бронь в прошлом запрещена", "quotes": ["Бронирование в прошлом запрещено"]},
        {"kind": "functional", "source_id": "1", "text": "Пересекающиеся брони одной комнаты отклоняются", "quotes": ["Пересекающиеся бронирования одной комнаты отклоняются"]},
        {"kind": "functional", "source_id": "2", "text": "Отмена брони владельцем — не позднее 10 минут до начала", "quotes": ["Владелец брони может отменить её не позднее 10 минут до начала"]},
        {"kind": "functional", "source_id": "1", "text": "Напоминание участникам за 15 минут до начала", "quotes": ["За 15 минут до начала участники получают напоминание"]},
        {"kind": "functional", "source_id": "2", "text": "При отмене участники получают сообщение", "quotes": ["При отмене брони участники получают сообщение об отмене"]},
        {"kind": "nonfunctional", "source_id": "NFR-01", "text": "Поиск свободной комнаты не дольше 2 секунд для 95% запросов", "quotes": ["| NFR-01 | Поиск свободной комнаты | не более 2 секунд для 95% запросов |"]},
        {"kind": "nonfunctional", "source_id": "NFR-02", "text": "Доступность сервиса 99,5% в рабочие часы", "quotes": ["Доступность сервиса | 99,5% в рабочие часы"]},
        {"kind": "acceptance", "source_id": None, "text": "Свободная комната бронируется на 10:00–10:30", "quotes": ["Дано: комната свободна с 10:00 до 11:00"]},
        {"kind": "acceptance", "source_id": None, "text": "Пересекающаяся бронь отклоняется", "quotes": ["Дано: бронь 10:00–11:00"]},
    ],
    "excluded": [
        {"category": "metadata", "reason": "Версия документа", "contains": ["| 0.3 |"]},
        {"category": "goal", "reason": "Назначение сервиса", "contains": ["Сотрудники бронируют переговорные"]},
    ],
    "facts": [
        {"subject": "бронь", "field": "длительность", "direction": "business", "type": "duration", "value": None,
         "unit": "минута", "range": {"min": 15, "max": 240, "min_inclusive": None, "max_inclusive": None},
         "condition": None, "quotes": ["от 15 до 240 минут"]},
    ],
}


def _summary(inv):
    return {
        "requirements": [(r["id"], r["source_id"], r["kind"], r["block_ids"]) for r in inv["requirements"]],
        "excluded": {g["category"]: g["block_ids"] for g in inv["excluded"]},
        "unprocessed": inv["unprocessed_block_ids"],
    }


def test_independent_document_counts_come_from_its_own_structure():
    doc = fixture_document("meeting_rooms.md")
    inv = build_inventory(doc)
    assert_invariants(doc, inv)
    reqs = inv["requirements"]
    assert len(reqs) == 11 and inv["block_coverage"]["source_units"] == 10
    assert [r["source_id"] for r in reqs] == [
        "REQ-BK-01", "REQ-BK-01", "REQ-BK-02", "1", "2", "1", "2", "NFR-01", "NFR-02", "3", "3"]
    assert [r["id"] for r in reqs][:3] == ["R-001.1", "R-001.2", "R-002"]
    assert inv["block_coverage"]["by_kind"] == {"functional": 7, "nonfunctional": 2, "acceptance": 2}
    # сценарии приёмки — каждый своим пунктом (номер раздела «3» не склеивает их)
    acc = [r for r in reqs if r["kind"] == "acceptance"]
    assert acc[0]["group"] != acc[1]["group"]
    cats = {g["category"]: len(g["block_ids"]) for g in inv["excluded"]}
    assert cats["approval"] == 3 and cats["metadata"] == 1 and cats["goal"] == 1
    assert inv["unprocessed_block_ids"] == [] and inv["warnings"] == []
    units = {f["unit"] for f in inv["fact_hints"]}
    assert units == {"минута", "секунда"}


def test_independent_document_with_model():
    doc = fixture_document("meeting_rooms.md")
    model = QuoteModel(MEETING_SPEC, doc)
    inv = build_inventory(doc, model)
    assert_invariants(doc, inv)
    assert len(model.calls) == 1 and inv["block_coverage"]["level"] == "complete"
    bk1 = [r for r in inv["requirements"] if r["source_id"] == "REQ-BK-01"]
    assert [r["id"] for r in bk1] == ["R-001.1", "R-001.2", "R-001.3"]
    assert len(inv["requirements"]) == 12
    assert {r["origin"] for r in inv["requirements"]} == {"llm"}


def test_results_depend_only_on_current_input():
    case = fixture_document("case_requirements.md")
    other = fixture_document("meeting_rooms.md")
    first = build_inventory(case)
    middle = build_inventory(other)
    again = build_inventory(case)
    assert first == again
    case_texts = {b["text"] for b in case["blocks"]}
    for r in middle["requirements"]:
        assert not any(h["quote"] in case_texts for h in r["hints"])
    assert _summary(first) != _summary(middle)
    assert len(first["requirements"]) != len(middle["requirements"])


def test_module_has_no_case_specific_constants():
    source = Path(inventory_module.__file__).read_text(encoding="utf-8")
    for token in ("saveLimit", "AlertsController", "limit_kzt", "cardId", "Алматы", "Ф-1", "Ф-2", "48 500",
                  "50 000", "REQ-BK", "переговорн", "Заявка на отпуск"):
        assert token not in source, token


def test_cli_entry_point_reads_document_json(tmp_path):
    doc = fixture_document("meeting_rooms.md")
    src = tmp_path / "doc.json"
    out = tmp_path / "inv.json"
    src.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    root = Path(__file__).resolve().parents[2]
    env = {"PYTHONPATH": str(root / "src"), "PATH": "/usr/bin:/bin"}
    proc = subprocess.run([sys.executable, "-m", "bcc_review.analysis.inventory", str(src), "-o", str(out)],
                          capture_output=True, text=True, env=env, cwd=tmp_path, check=False)
    assert proc.returncode == 0, proc.stderr
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data == json.loads(json.dumps(build_inventory(doc), ensure_ascii=False))
    proc = subprocess.run([sys.executable, "-m", "bcc_review.analysis.inventory", str(src), "--payload"],
                          capture_output=True, text=True, env=env, cwd=tmp_path, check=False)
    payloads = json.loads(proc.stdout)
    assert len(payloads) == 1 and payloads[0]["input"]["window"]["count"] == 1


def test_flat_pdf_without_headings_keeps_unknown_prose_as_residue():
    """Плоский PDF: без заголовков правила не угадывают судьбу абзаца — он остаётся явным остатком."""
    flat = {"id": hashlib.sha256(b"flat").hexdigest(), "title": "flat", "format": "pdf", "warnings": [], "blocks": [
        {"id": "p1#1", "kind": "paragraph", "section": [], "text": "Охранник регистрирует посетителя по\nдокументу.",
         "loc": {"page": 1}},
        {"id": "p1#2", "kind": "paragraph", "section": [],
         "text": "1.1 Система должна печатать пропуск за 5 секунд.\n1.2 Пропуск действует до конца дня.",
         "loc": {"page": 1}},
        {"id": "p2#1", "kind": "other", "section": [],  # PDF-парсер не разделил таблицу на строки
         "text": "| ID | Требование |\n| --- | --- |\n| T-1 | Журнал выгружается в CSV |\n| T-2 | Доступ только у охраны |",
         "loc": {"page": 2}},
        {"id": "p2#2", "kind": "paragraph", "section": [],
         "text": "The system shall lock the account after 3 failed attempts.", "loc": {"page": 2}},
    ]}
    inv = build_inventory(flat)
    assert_invariants(flat, inv)
    assert [(r["id"], r["source_id"]) for r in inv["requirements"]] == [
        ("R-001", "1.1"), ("R-002", "1.2"), ("R-003", "T-1"), ("R-004", "T-2"), ("R-005", None)]
    assert [r["block_ids"] for r in inv["requirements"][2:4]] == [["p2#1"], ["p2#1"]]  # таблица одним блоком
    assert inv["requirements"][2]["text"] == "Требование: Журнал выгружается в CSV"
    assert inv["unprocessed_block_ids"] == ["p1#1"]
    # «за 5 секунд» правила не толкуют (ср. «за 15 минут до начала» — момент, а не предел): это работа модели
    assert inv["fact_hints"] == []
