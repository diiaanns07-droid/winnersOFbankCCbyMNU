"""№30: маскирование персональных данных (`rules.redact`) — карты, ИИН/БИН, телефоны, почта, IBAN.

Модуль — здесь; запись `runs/`, кэша и флаг `--redact` — врезка в ядро (просьба №22, патч
`tests/v2/fixtures/30_redact/core.patch`). Сквозные проверки до врезки — xfail.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from bcc_review.v2.rules import redact

ROOT = Path(__file__).resolve().parents[2]
FX = ROOT / "tests" / "v2" / "fixtures" / "30_redact"
PD = json.loads((FX / "pd_values.json").read_text(encoding="utf-8"))
RAW = [PD["card"], PD["card_spaced"], PD["iin"], PD["phone"], PD["email"]]


def _card(prefix: str, n: int = 16) -> str:
    body = prefix.ljust(n - 1, "7")[: n - 1]
    return next(body + str(d) for d in range(10) if redact.luhn(body + str(d)))


@pytest.mark.parametrize("text,kind,shown", [
    (f"карта {PD['card_spaced']}", "card", "6789"),
    (f"номер карты {PD['card']}", "card", "6789"),
    ("Amex 3714-496353-98431", None, None),  # не 4-4-4-4 — не наш формат (банк выпускает 16 цифр)
    (f"ИИН {PD['iin']}", "iin", "26"),
    (f"клиент {PD['iin']} обратился", "iin", "26"),  # контрольный разряд и дата
    ("+7 (701) 234-56-78", "phone", "78"),
    ("8 701 234 56 78", "phone", "78"),
    ("asel.nurlanovna@mail.kz", "email", "@mail.kz"),
    ("KZ12 3456 7890 1234 5678", "iban", "5678"),
])
def test_find_and_mask(text: str, kind: str | None, shown: str | None) -> None:
    hits = redact.find(text)
    if kind is None:
        assert hits == []
        return
    assert [h["kind"] for h in hits] == [kind]
    m = redact.mask(text)
    assert len(m) == len(text)  # длина строки сохраняется — номера позиций и цитаты не съезжают
    assert hits[0]["value"] not in m and shown in m and redact.DOT in m


@pytest.mark.parametrize("text", [
    "сумма 1 000 000 ₸ за 30 дней", "код ответа 4000", "дата 2026-11-27 12:00", "orderId 1234567890123456",
    "timestamp 20261127120000", "4400 43** **** 1234", "•••• •••• •••• 6789", "support@bank.kz",
    "user@example.com", "ИНН 7707083893", "лимит 100000000000 тиын", "+7 700", "версия 1.2.3.4",
    "строки 123456789012 и далее",  # 12 цифр без контрольного разряда и без слова «ИИН»
])
def test_no_false_positives(text: str) -> None:
    assert redact.find(text) == [], redact.find(text)
    assert redact.mask(text) == text


def test_luhn_and_iin_checksum() -> None:
    assert redact.luhn(PD["card"]) and not redact.luhn(PD["card"][:-1] + str((int(PD["card"][-1]) + 1) % 10))
    assert redact.iin_checksum(PD["iin"])
    assert not redact.iin_checksum(PD["iin"][:-1] + str((int(PD["iin"][-1]) + 1) % 10))
    assert redact.luhn(_card("5169"))


def test_mask_obj_and_view() -> None:
    obj = {"quote": f"карта {PD['card_spaced']}", "nested": [{"t": PD["email"]}], "n": 5, PD["iin"]: "ключ не трогаем"}
    m = redact.mask_obj(obj)
    blob = json.dumps(m, ensure_ascii=False)
    assert PD["card_spaced"] not in blob and PD["email"] not in blob and m["n"] == 5 and PD["iin"] in m
    view = {"lines": [{"n": 1, "text": f"Клиент с ИИН {PD['iin']}"}, {"n": 2, "text": "без данных"}]}
    v2, stats = redact.mask_view(view)
    assert stats == {"iin": 1} and v2["lines"][1] is view["lines"][1] and PD["iin"] not in v2["lines"][0]["text"]
    assert len(v2["lines"][0]["text"]) == len(view["lines"][0]["text"])
    assert "ИИН/БИН — 1" in redact.summary(stats)


def test_no_pd_in_repository_documents() -> None:
    """По документам репозитория (официальный, корпус, open2, чистые №20) ложных карт и ИИН нет."""
    files = subprocess.run(["git", "ls-files", "release/input", "evaluation/v2/clean", "evaluation/v2/open2",
                            "evaluation/dev/corpus/cases"], cwd=ROOT, capture_output=True, text=True).stdout.split()
    kinds = set()
    for f in files:
        if f.endswith(".md"):
            kinds |= {h["kind"] for h in redact.find((ROOT / f).read_text(encoding="utf-8"))}
    assert kinds <= {"phone"}  # условные телефоны «+7 700 000 0001» в корпусе — маскировать их не вредно


def test_check_cli(tmp_path: Path) -> None:
    (tmp_path / "ok.json").write_text('{"a": "ничего личного"}', encoding="utf-8")
    assert redact.main(["--check", str(tmp_path)]) == 0
    (tmp_path / "bad.jsonl").write_text(json.dumps({"q": f"карта {PD['card_spaced']}"}, ensure_ascii=False),
                                        encoding="utf-8")
    assert redact.main(["--check", str(tmp_path)]) == 1


def _review(tmp_path: Path, *extra: str) -> tuple[Path, dict]:
    out = tmp_path / "out" / "r.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, "-m", "bcc_review", str(FX / "pd_doc.md"), str(out), "--provider", "mock", "--mock-dir",
           str(FX / "mock"), "--runs-dir", str(tmp_path / "runs"), "--no-html", "-q", *extra]
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=300)
    assert r.returncode in (0, 1, 2), r.stderr[-2000:]
    return out, json.loads(out.with_suffix(".json").read_text(encoding="utf-8"))


def _core_integrated() -> bool:
    src = (ROOT / "src" / "bcc_review" / "v2" / "runs.py").read_text(encoding="utf-8")
    return "redact" in src


needs_core = pytest.mark.xfail(not _core_integrated(), reason="врезка в ядро — просьба №22 (fixtures/30_redact/core.patch)",
                               strict=False)


@needs_core
def test_runs_dir_has_no_open_pd(tmp_path: Path) -> None:
    _review(tmp_path)
    assert redact.scan_paths([tmp_path / "runs"]) == []


@needs_core
def test_redact_flag_hides_pd_in_report(tmp_path: Path) -> None:
    out, rep = _review(tmp_path, "--redact")
    text = out.read_text(encoding="utf-8") + json.dumps(rep, ensure_ascii=False)
    for v in RAW:
        assert v not in text, v
    assert any("Скрыто персональных данных" in w for w in rep["run"].get("warnings") or [])
    assert redact.scan_paths([tmp_path / "runs", out.parent]) == []
