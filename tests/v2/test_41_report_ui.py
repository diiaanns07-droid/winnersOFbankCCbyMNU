"""№41: правка на листе — светлый лист с правкой агента (страница задания и HTML-отчёт CLI).

Проверяем содержание, а не пиксели: лист документа со сканером во время проверки, правка на листе и одна
стеклянная панель после; числа и блокеры — те же, что в Markdown; report.css/report.js без внешних ссылок;
цвета пометок — по смыслу (раздел 3 bcc-ui.md). Без сети и без ключа (FixtureRunner).
"""
from __future__ import annotations

import json
import re
import threading
import time
import urllib.request
from pathlib import Path

import pytest

from bcc_review.v2.render import html as H
from bcc_review.v2.render import jsonout as J
from bcc_review.v2.render import markdown as M
from bcc_review.v2.web import runner as R
from bcc_review.v2.web import server as S

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / "release" / "input" / "requirements.md"
FIXTURE = ROOT / "tests" / "v2" / "fixtures" / "14_report_official.json"
REPORT_CSS = ROOT / "src" / "bcc_review" / "v2" / "render" / "html_assets" / "report.css"
REPORT_JS = ROOT / "src" / "bcc_review" / "v2" / "render" / "html_assets" / "report.js"
JOB_CSS = ROOT / "src" / "bcc_review" / "v2" / "web" / "assets" / "job.css"
DESIGN = ROOT / "docs" / "design" / "bcc-ui.md"


@pytest.fixture()
def srv(tmp_path, monkeypatch):
    for k in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_BASE_URL"):
        monkeypatch.delenv(k, raising=False)
    app = S.build_app(tmp_path / "data", fixture=FIXTURE, step_s=0.01, sample=DOC)
    httpd = S.make_server(app, "127.0.0.1", 0)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}", app
    httpd.shutdown()
    httpd.server_close()


def _get(url: str) -> tuple[int, str]:
    try:
        with urllib.request.urlopen(url) as r:
            return r.status, r.read().decode("utf-8")
    except urllib.error.HTTPError as exc:  # type: ignore[attr-defined]
        return exc.code, exc.read().decode("utf-8")


def _done_job(base: str) -> str:
    b = "x41x"
    body = (f'--{b}\r\nContent-Disposition: form-data; name="provider"\r\n\r\nmock\r\n'
            f'--{b}\r\nContent-Disposition: form-data; name="sample"\r\n\r\n1\r\n--{b}--\r\n').encode()
    req = urllib.request.Request(base + "/api/jobs", data=body, method="POST",
                                 headers={"Content-Type": f"multipart/form-data; boundary={b}", "Accept": "application/json"})
    with urllib.request.urlopen(req) as r:
        jid = json.loads(r.read())["id"]
    for _ in range(400):
        st = json.loads(_get(f"{base}/api/jobs/{jid}")[1])
        if st["state"] in ("done", "failed"):
            assert st["state"] == "done", st
            return jid
        time.sleep(0.02)
    raise AssertionError("задание не завершилось")


def _expected(path: Path = FIXTURE) -> dict:
    """Числа — как в Markdown-отчёте и итоге терминала: блокеры — markdown._blockers, счётчики — summary."""
    rep = json.loads(path.read_text(encoding="utf-8"))
    ctx = M._Ctx(rep)
    bl = M._blockers(ctx)
    order = M._first_screen_fix(ctx, bl)
    s = rep.get("summary") or J.compute_summary(rep)
    ok, total = H._quotes_verified(rep)
    if isinstance(s.get("quotes_verified"), int) and isinstance(s.get("quotes_total"), int):
        ok, total = s["quotes_verified"], s["quotes_total"]
    return {"crit": [f["id"] for f in order if f in bl] + [f["id"] for f in bl if f not in order],
            "major": (s.get("findings") or {}).get("major"),
            "questions": len(rep.get("questions") or []), "ok": ok, "total": total, "verdict": rep["verdict"]}


def test_job_page_is_the_sheet_with_glass_dock(srv):
    """Готовая правка: лист-отчёт на весь стол и одна стеклянная панель; числа — как в Markdown."""
    base, _ = srv
    jid = _done_job(base)
    code, page = _get(f"{base}/jobs/{jid}")
    assert code == 200 and f'data-job="{jid}"' in page and 'class="jb done"' in page
    exp = _expected()
    # лист с правкой — HTML-отчёт этого прогона в режиме встраивания
    assert f'data-src="/jobs/{jid}/files/report.html?inline=1"' in page
    # BCC AI (AIshka) стоит на краю листа: режим и реплика — по блокерам, как в Markdown
    assert 'data-mood="speak"' in page if exp["crit"] else 'data-mood="happy"' in page
    say = re.search(r'data-say="([^"]+)"', page).group(1)
    assert str(len(exp["crit"])) in say and exp["crit"][0] in say
    # стеклянная панель: свой документ · правка · вопросы · исправленная редакция · выгрузить
    dock = page[page.index('id="dock"'):]
    for label in ("Свой документ", "Правка", 'Вопросы<span class="long"> владельцу</span>', "Исправленная редакция",
                  "Выгрузить"):  # №54: на телефоне — короткие подписи «Вопросы», «Редакция»
        assert label in dock, label
    n_findings = len(json.loads(FIXTURE.read_text(encoding="utf-8"))["findings"])
    assert f'Правка <span class="jb-n">{n_findings}</span>' in dock
    assert f'Вопросы<span class="long"> владельцу</span> <span class="jb-n">{exp["questions"]}</span>' in dock
    # выгрузки — в меню панели, ровно те файлы, что есть у прогона
    st = json.loads(_get(f"{base}/api/jobs/{jid}")[1])
    for name in ("report.html", "report.json"):
        assert f'href="/jobs/{jid}/files/{name}" download' in page, name
    assert set(st["files"]) >= {"html", "json"}
    assert page.count('class="b-dock jb-dock"') == 1  # одно стекло внизу — .b-dock №39


def test_result_fragment_for_live_page(srv):
    """Прогон закончился при открытой странице: правка приходит фрагментом — лист и панель."""
    base, _ = srv
    jid = _done_job(base)
    code, frag = _get(f"{base}/jobs/{jid}?part=result")
    assert code == 200 and "<html" not in frag
    assert 'id="rframe"' in frag and 'id="dock"' in frag


def test_progress_is_the_document_sheet_with_scanner(tmp_path):
    """Во время проверки на экране сам документ: строки с номерами, бледно-зелёный луч и BCC AI 96 px у листа."""
    store = R.JobStore(tmp_path)
    job = store.create("tz.md", "# Заголовок\n\nПервая строка требований\n".encode("utf-8"), "mock", "")
    page = S.job_page(job)
    assert 'id="sheet"' in page and 'id="beam"' in page and 'id="pilot"' in page
    assert '<span class="no">3</span><span class="tx">Первая строка требований</span>' in page
    assert '<div data-bcc-agent data-size="96" data-mood="work" id="agent"></div>' in page
    assert 'id="errtext"' in page and "Что сделать" in (ROOT / "src/bcc_review/v2/web/assets/app.js").read_text(encoding="utf-8")
    assert "/assets/tokens.css" in page and re.search(r'<body class="b-(root|desk)"', page)


def test_api_reports_model_calls_from_log(tmp_path):
    store = R.JobStore(tmp_path)
    job = store.create("tz.md", b"# x\n", "gemini", "")
    job.log = ["  segment: готово за 3 с, вызовов 1", "  lens_qa: готово за 9 с, вызовов 2, кандидатов 5",
               "  judge: запуск", "  rules: готово за 0 с, вызовов 0, кандидатов 15"]
    assert S.job_calls(job) == 3


def test_css_has_no_external_links():
    for p in (REPORT_CSS, JOB_CSS, REPORT_JS):
        text = p.read_text(encoding="utf-8")
        assert not re.search(r"https?://(?!www\.w3\.org/2000/svg)|@import", text, re.I), p.name
        if p.suffix == ".css":  # в стилях — только ссылки на свой SVG-фильтр (url(#…)), без файлов и сети
            assert not re.search(r"url\((?!#)", text), p.name


def _tokens() -> dict[str, str]:
    md = DESIGN.read_text(encoding="utf-8")
    return {k: v.upper() for k, v in re.findall(r"--(b-[a-z0-9-]+):(#[0-9A-Fa-f]{6})", md)}


def _root_vars(css: str) -> dict[str, str]:
    root = css[css.index(":root {"):css.index("}", css.index(":root {"))]
    return {k: v.upper() for k, v in re.findall(r"--([a-z0-9-]+):\s*(#[0-9A-Fa-f]{6})", root)}


BLUES = ("#1C446C", "#8DB6E2", "#9CC2EA", "#E8EFF6", "#0B1220")  # синий BCC и тёмный стол — больше не на экране


def test_marks_on_the_sheet_follow_the_meaning_of_colour():
    """Светло и мягко: фон BCC, белый лист; один акцент — зелёный. Критичное — тонкая красная черта без заливки,
    существенное — бледный золотой маркер #FBE1BA, незначительное — серый пунктир; синего и тёмного стола нет."""
    t = _tokens()
    css = REPORT_CSS.read_text(encoding="utf-8")
    v = _root_vars(css)
    assert v["canvas"] == t["b-canvas"] and v["paper"] == "#FFFFFF" and v["ink"] == t["b-ink"]
    assert v["crit"] == t["b-red"] and v["major-mark"] == t["b-gold-soft"] and v["accent"] == t["b-green"]
    assert re.search(r"mark\.q\.sev-critical \{[^}]*text-decoration-style: solid[^}]*var\(--crit\)", css)
    assert re.search(r"mark\.q\.sev-major \{[^}]*var\(--major-mark\)", css)
    assert re.search(r"mark\.q\.sev-minor \{[^}]*text-decoration-style: dashed[^}]*var\(--minor-acc\)", css)
    assert re.search(r"\.ln\.hl \.no::after \{[^}]*var\(--accent\)", css)  # галочка «сверено» — зелёная
    job = JOB_CSS.read_text(encoding="utf-8")
    for text, name in ((css, "report.css"), (job, "job.css")):
        assert not any(b.lower() in text.lower() for b in BLUES), name
    js = REPORT_JS.read_text(encoding="utf-8")
    assert "verdict-line" in js and "feTurbulence" not in js  # вердикт — строкой, без печати


def test_html_report_embeds_sheet_css_and_js():
    rep = json.loads(FIXTURE.read_text(encoding="utf-8"))
    html = H.render_html(rep, H.load_view(DOC))
    assert "--canvas: #F3F6F5" in html and ":root[data-embed]" in html and "verdict-line" in html
    assert 'id="report-data"' in html and 'class="docpane"' in html and "Исправить первым" in html


def test_facts_follow_markdown_after_owner_answers(tmp_path):
    """После ответов владельца снятое критичное замечание — не блокер (как в Markdown и терминале)."""
    src = ROOT / "reports" / "demo_answers" / "qr" / "qr.round2.json"
    store = R.JobStore(tmp_path)
    job = store.create("qr.md", b"# x\n", "mock", "")
    out = store.dir(job.id) / "out"
    out.mkdir()
    (out / "report.json").write_bytes(src.read_bytes())
    job.state = "done"
    app = S.App(store, None)  # type: ignore[arg-type]
    f = S.report_facts(app, job)
    exp = _expected(src)
    assert [b["id"] for b in f["blockers"]] == exp["crit"]
    assert (f["critical"], f["major"], f["questions"]) == (len(exp["crit"]), exp["major"], exp["questions"])
    assert (f["quotes_ok"], f["quotes_total"]) == (exp["ok"], exp["total"])
    assert f["has"]["rewrites"] and f["has"]["clarify"]
    html = S.result_html(job, f)
    assert "Блокеров нет" in html and 'data-mood="happy"' in html
    assert 'data-rt="rewrites"' in html and 'data-rtab="clarify"' in html
