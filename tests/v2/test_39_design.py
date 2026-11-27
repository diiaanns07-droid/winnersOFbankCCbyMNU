"""№39: дизайн-система BCC и главный экран — главная отдаётся, tokens.css подключён, без внешних ссылок."""
from __future__ import annotations

import re
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from bcc_review.v2.web import server as S

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / "release" / "input" / "requirements.md"
FIX = ROOT / "tests" / "v2" / "fixtures" / "14_report_official.json"
ASSETS = ROOT / "src" / "bcc_review" / "v2" / "web" / "assets"
KEY_LINK = "https://aistudio.google.com/apikey"  # единственная разрешённая внешняя ссылка — получить ключ
EXTERNAL = re.compile(r"https?://(?!127\.0\.0\.1|localhost)[^\s\"'<>)]+")


@pytest.fixture()
def srv(tmp_path, monkeypatch):
    for k in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_BASE_URL"):
        monkeypatch.delenv(k, raising=False)
    app = S.build_app(tmp_path / "data", fixture=FIX, step_s=0.01, sample=DOC)
    httpd = S.make_server(app, "127.0.0.1", 0)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}", app
    httpd.shutdown()
    httpd.server_close()


def _get(url: str) -> tuple[int, str, dict]:
    try:
        with urllib.request.urlopen(url) as r:
            return r.status, r.read().decode("utf-8"), dict(r.headers)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace"), dict(exc.headers)


def _external(text: str) -> list[str]:
    return [u for u in EXTERNAL.findall(text) if not u.startswith(KEY_LINK)]


def test_index_served_with_tokens(srv):
    base, _ = srv
    code, html, _ = _get(base + "/")
    assert code == 200
    assert '<link rel="stylesheet" href="/assets/tokens.css">' in html
    assert html.index("/assets/tokens.css") < html.index("/assets/app.css")
    assert 'class="b-root"' in html and "b-glass" in html
    assert "data-bcc-agent" in html and 'data-size="40"' in html and 'data-mood="idle"' in html
    assert "BCC Review" in html and "Проверка ТЗ до разработки" in html
    assert "Как это работает" in html and "<details" in html
    assert "<select" not in html  # провайдер — сегмент, не голый select
    assert 'name="provider"' in html and 'name="file"' in html


def test_exactly_one_primary_on_index(srv):
    base, _ = srv
    html = _get(base + "/")[1]
    assert len(re.findall(r'class="[^"]*\bprimary\b', html)) == 1


def test_tokens_css_served(srv):
    base, _ = srv
    code, css, h = _get(base + "/assets/tokens.css")
    assert code == 200 and h["Content-Type"].startswith("text/css")
    for tok in ("--b-ink:#0F2841", "--b-green:#00B975", "--b-gold:#DCA262", "--b-green-strong:#008556",
                "--b-ease:cubic-bezier(.2,.8,.2,1)", "--b-h:46px"):
        assert tok in css
    for cls in (".b-root", ".b-surface", ".b-glass", ".b-button", ".primary", ".quiet", ".small", ".b-segment",
                ".b-status", ".stale", ".error", ".b-strip", ".b-metric", ".b-list", ".b-row", ".b-badge",
                ".crit", ".major", ".minor", ".ok", ".plain", ".b-field", ".b-rise"):
        assert cls in css, cls
    assert "prefers-reduced-motion" in css


def test_no_external_links_in_html_and_css(srv):
    base, app = srv
    pages = [_get(base + "/")[1], _get(base + "/nope")[1]]
    job = app.start("t.md", DOC.read_bytes(), "mock", "")
    for _ in range(300):
        if app.store.get(job.id).state in ("done", "failed"):
            break
        time.sleep(0.02)
    pages.append(_get(f"{base}/jobs/{job.id}")[1])
    pages.append(_get(base + "/")[1])  # с блоком «Последние проверки»
    for p in pages:
        assert _external(p) == [], _external(p)
    for name in ("tokens.css", "app.css", "app.js"):
        assert _external((ASSETS / name).read_text("utf-8")) == [], name


def test_index_lists_recent_and_error_state(srv):
    base, app = srv
    app.start("Моё ТЗ.md", DOC.read_bytes(), "mock", "")
    html = _get(base + "/")[1]
    assert "Последние проверки" in html and "Моё ТЗ.md" in html
    code, html, _ = _get(base + "/")
    assert code == 200


def test_gallery_absent_is_harmless(monkeypatch, srv):
    _, app = srv
    import builtins
    real = builtins.__import__

    def boom(name, *a, **k):
        if name.endswith("gallery") or (a and a[2] and "gallery" in (a[2] or ())):
            raise ImportError("нет модуля")
        return real(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", boom)
    assert S._gallery(app) == ""
