"""Шрифт в pdf_assets: конкретный файл, версия, хеши, лицензия OFL, покрытие кириллицы и ₸."""

from __future__ import annotations

import hashlib
import json

import pymupdf

from bcc_review.exports import pdf as P


def _lock() -> dict:
    return json.loads(P.FONT_LOCK.read_text(encoding="utf-8"))


def test_font_file_is_pinned():
    lock = _lock()
    data = P.FONT_FILE.read_bytes()
    assert hashlib.sha256(data).hexdigest() == lock["sha256"] and len(data) == lock["size"]
    assert lock["source"]["commit"] == "5026800714d07231937d92eb4cceabf06e05d74e"
    f = pymupdf.Font(fontbuffer=data)
    assert f.name == "Noto Sans Regular"
    from fontTools.ttLib import TTFont

    names = TTFont(P.FONT_FILE)["name"]
    assert names.getDebugName(5) == f"Version {lock['font_version']}"


def test_license_is_ofl_and_shipped_alongside():
    lock = _lock()
    ofl = (P.ASSETS_DIR / "OFL.txt").read_bytes()
    assert hashlib.sha256(ofl).hexdigest() == lock["license"]["sha256"]
    text = ofl.decode("utf-8")
    assert "SIL OPEN FONT LICENSE Version 1.1 - 26 February 2007" in text
    first = text.splitlines()[0]
    assert first == lock["license"]["copyright"]
    assert "Reserved Font Name" not in first and lock["license"]["reserved_font_names"] == []
    meta = (P.ASSETS_DIR / "METADATA.pb").read_bytes()
    assert hashlib.sha256(meta).hexdigest() == lock["license"]["metadata_sha256"]
    assert b'license: "OFL"' in meta and b"NotoSans[wdth,wght].ttf" in meta


def test_fallback_font_pinned_and_licensed():
    fb = _lock()["fallback"]
    data = P.FALLBACK_FILE.read_bytes()
    assert hashlib.sha256(data).hexdigest() == fb["sha256"] and len(data) == fb["size"]
    lic = (P.ASSETS_DIR / fb["license"]["file"]).read_bytes()
    assert hashlib.sha256(lic).hexdigest() == fb["license"]["sha256"]
    text = lic.decode("utf-8")
    assert text.splitlines()[0] == fb["license"]["copyright"] and "Reserved Font Name" not in text.splitlines()[0]
    assert "SIL OPEN FONT LICENSE Version 1.1 - 26 February 2007" in text
    meta = (P.ASSETS_DIR / fb["license"]["metadata_file"]).read_bytes()
    assert hashlib.sha256(meta).hexdigest() == fb["license"]["metadata_sha256"] and b'license: "OFL"' in meta
    rep = P.glyph_report("→ ← ↔ ⇒ ≤ ≥ ≠ ± × ▲ ◆ ● ₸ ✗ 漢")
    # ± и × есть в самом Noto Sans (Latin-1), в резерв они не попадают
    assert rep["missing"] == list("→←↔⇒≤≥≠▲◆●✗漢")
    assert rep["fallback"] == list("→←↔⇒≤≥≠▲◆●") and rep["unrendered"] == ["✗", "漢"]


def test_required_glyphs_present_and_known_missing_detected():
    req = _lock()["required_glyphs"].replace("А-Я", "АБВГДЕЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ").replace(
        "а-я", "абвгдежзийклмнопрстуфхцчшщъыьэюя"
    )
    assert P.missing_glyphs(req) == []
    assert P.missing_glyphs("▲◆●→✓") == list("▲◆●→✓")


def test_bold_instance_is_real_bold():
    reg = pymupdf.Font(fontbuffer=P._build_font("Ж", 400))
    bold = pymupdf.Font(fontbuffer=P._build_font("Ж", 700))
    assert bold.text_length("ЖЖЖ", 10) > reg.text_length("ЖЖЖ", 10)
    assert "Bold" in bold.name
    assert bold.has_glyph(0x20B8) and reg.has_glyph(0x20B8)
