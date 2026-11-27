"""№39: «Белый лист на тёмном столе» — стол, лист с номерами строк, правка, печать, карта, панель; без внешних ссылок."""
from __future__ import annotations

import json
import re
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from bcc_review.v2.web import server as S
from bcc_review.v2.web import sheet as SH

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / "release" / "input" / "requirements.md"
FIX = ROOT / "tests" / "v2" / "fixtures" / "14_report_official.json"
ASSETS = ROOT / "src" / "bcc_review" / "v2" / "web" / "assets"
KEY_LINK = "https://aistudio.google.com/apikey"  # единственная разрешённая внешняя ссылка — получить ключ
EXTERNAL = re.compile(r"https?://(?!127\.0\.0\.1|localhost)[^\s\"'<>)]+")
FONTS = ("pt-serif-400.woff2", "pt-serif-700.woff2", "jetbrains-mono-400.woff2")


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


def _get(url: str) -> tuple[int, bytes, dict]:
    try:
        with urllib.request.urlopen(url) as r:
            return r.status, r.read(), dict(r.headers)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(), dict(exc.headers)


def _text(url: str) -> str:
    return _get(url)[1].decode("utf-8", "replace")


def _external(text: str) -> list[str]:
    return [u for u in EXTERNAL.findall(text) if not u.startswith(KEY_LINK)]


def _done_job(app):
    job = app.start("requirements.md", DOC.read_bytes(), "mock", "")
    for _ in range(500):
        if app.store.get(job.id).state in ("done", "failed"):
            break
        time.sleep(0.02)
    assert app.store.get(job.id).state == "done"
    return job


def test_desk_shell(srv):
    base, _ = srv
    code, body, _ = _get(base + "/")
    html = body.decode()
    assert code == 200
    assert '<link rel="stylesheet" href="/assets/tokens.css">' in html
    assert html.index("/assets/tokens.css") < html.index("/assets/app.css")
    assert 'class="b-desk"' in html and 'class="b-bar"' in html and 'class="b-dock"' in html
    assert re.search(r'data-bcc-agent data-size="24" data-mood="idle"', html)
    assert 'id="b-ink"' in html and "feTurbulence" in html  # чернила печати — фильтр, без картинок
    assert "BCC Review" in html and "Свой документ" in html
    assert "<select" not in html  # модель — в меню панели, не голый select и не таблетки на экране
    assert 'name="provider"' in html and 'name="file"' in html


def test_exactly_one_primary_on_desk(srv):
    base, app = srv
    for _ in range(2):
        html = _text(base + "/")
        assert len(re.findall(r'class="[^"]*\bprimary\b', html)) == 1
        _done_job(app)


def test_tokens_and_fonts_served(srv):
    base, _ = srv
    code, css, h = _get(base + "/assets/tokens.css")
    css = css.decode()
    assert code == 200 and h["Content-Type"].startswith("text/css")
    for tok in ("--b-desk:#0B1220", "--b-green:#00B975", "--b-gold:#DCA262", "--b-red:#C2362B", "--b-sheet-w:760px",
                '"PT Serif",Georgia,"Times New Roman",serif', '"JetBrains Mono",ui-monospace,Consolas',
                "--b-ease:cubic-bezier(.2,.8,.2,1)"):
        assert tok in css, tok
    for cls in (".b-desk", ".b-bar", ".b-sheet", ".b-line", ".b-ln", ".b-hl.crit", ".b-hl.major", ".b-hl.minor",
                ".b-note", ".is-focus", ".b-stamp", ".b-stamp.ok", ".b-map", ".b-dock", ".b-menu", ".b-stack",
                ".b-leaf", ".b-button", ".primary", ".b-badge", ".b-field", ".b-rise", "wavy"):
        assert cls in css, cls
    assert "prefers-reduced-motion" in css
    total = 0
    for name in FONTS:
        code, data, h = _get(f"{base}/assets/{name}")
        assert code == 200 and h["Content-Type"] == "font/woff2" and data[:4] == b"wOF2"
        total += len(data)
    assert total <= 400 * 1024
    assert "Open Font License" in (ASSETS / "fonts-OFL.txt").read_text("utf-8")
    assert _get(base + "/assets/secret.py")[0] == 404


def test_desk_opens_last_report_as_sheet(srv):
    base, app = srv
    job = _done_job(app)
    html = _text(base + "/")
    assert 'id="sheet"' in html and "b-stamp crit" in html and "Нельзя в разработку" in html and "5 блокеров" in html
    assert "цитат сверено 39 из 39" in html
    assert f'href="/jobs/{job.id}#questions"' in html and f'href="/jobs/{job.id}#revised"' in html
    assert html.count('class="b-note ') == 20 and html.count('data-line="') == 20  # заметки и засечки карты
    assert "Выгрузить" in html and f"/jobs/{job.id}/files/report.html" in html


def test_sheet_marks_quotes_on_their_lines():
    rep = json.loads(FIX.read_text("utf-8"))
    sh = SH.build_sheet(rep, SH.read_source(DOC), file_name="requirements.md")
    assert sh.lines == 198 and sh.blockers == 5 and sh.notes == 20
    line39 = re.search(r'<div class="b-line[^"]*" id="L39".*?</div>', sh.html).group(0)
    assert " ok" in line39.split('"')[1]  # цитата сверена — галочка в поле номеров
    marked = "".join(re.findall(r'<span class="b-hl crit"[^>]*>([^<]*)</span>', line39))
    assert "На карту приходится максимум один такой push за календарный месяц" in marked
    assert 'class="b-line h1"' in sh.html and "Уведомление о расходах по карте" in sh.html
    assert "**" not in sh.html and "| ---" not in sh.html  # разметка Markdown не видна на листе
    # исходник не текстовый — лист собирается из цитат, номера строк те же
    sh2 = SH.build_sheet(rep, None, file_name="requirements.pdf")
    assert 'id="L39"' in sh2.html and "На карту приходится" in sh2.html


def test_plural_and_stamp_variants():
    assert [SH.plural(n, "блокер", "блокера", "блокеров") for n in (1, 2, 5, 11, 21, 22)] == \
        ["блокер", "блокера", "блокеров", "блокеров", "блокер", "блокера"]
    ok = SH.stamp_html({"verdict": {"development": "yes"}, "findings": [], "run": {"provider": "mock"}})
    assert "b-stamp ok" in ok and "Можно в разработку" in ok and "блокеров нет" in ok


def test_empty_desk_shows_sample_sheet(srv):
    base, _ = srv
    html = _text(base + "/")
    assert 'id="sheet"' in html and "пример, ещё не проверен" in html and "Проверить пример" in html
    assert "b-stamp " not in html  # не проверен — печати нет


def test_no_external_links_in_html_css_js(srv):
    base, app = srv
    job = _done_job(app)
    pages = [_text(base + "/"), _text(base + "/nope"), _text(f"{base}/jobs/{job.id}")]
    for p in pages:
        assert _external(p) == [], _external(p)
    for name in ("tokens.css", "app.css", "app.js"):
        assert _external((ASSETS / name).read_text("utf-8")) == [], name


def test_gallery_absent_is_harmless(monkeypatch, srv):
    _, app = srv
    import builtins
    real = builtins.__import__

    def boom(name, globals=None, locals=None, fromlist=(), level=0):
        if "gallery" in name or (fromlist and "gallery" in fromlist):
            raise ImportError("нет модуля")
        return real(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", boom)
    assert S._gallery(app) == ""
    assert S._top_sheet(app) is None
