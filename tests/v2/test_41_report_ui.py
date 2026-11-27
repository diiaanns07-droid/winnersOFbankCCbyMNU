"""№41: прогресс и отчёт в новом дизайне — страница задания и вид HTML-отчёта (bcc-ui.md, разделы 3, 8.3, 8.4).

Проверяем содержание, а не пиксели: вердикт, полоса из четырёх чисел и блокеры берутся из того же report.json,
что и отчёт; слот BCC AI на месте; report.css без внешних ссылок; цвета критичности — как в разделе 3.
Без сети и без ключа (FixtureRunner).
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


def _metrics(html: str) -> list[tuple[str, str]]:
    return re.findall(r'<div class="b-metric[^"]*"><b>([^<]+)</b><span>([^<]+)</span></div>', html)


def test_job_page_shows_verdict_strip_and_mascot_slot(srv):
    base, _ = srv
    jid = _done_job(base)
    code, page = _get(f"{base}/jobs/{jid}")
    assert code == 200 and f'data-job="{jid}"' in page
    exp = _expected()
    # вердикт крупно, теми же словами, что в отчёте
    v = re.search(r'<h1 class="jb-verdict"[^>]*>(.*?)</h1>', page, re.S)
    assert v, "нет вердикта"
    words = re.sub(r"<[^>]+>", "", v.group(1))
    assert "Разработка: " + H.VERDICT_LABEL[exp["verdict"]["development"]].lower() in words
    assert "Тестирование: " + H.VERDICT_LABEL[exp["verdict"]["testing"]].lower() in words
    assert 'class="v v-no"' in v.group(1)  # «нельзя» — красным (смысл, раздел 3)
    # полоса — ровно четыре числа: блокеры, существенные, вопросы, «цитат сверено N из N»
    strip = re.search(r'<div class="b-strip[^"]*"[^>]*>(.*?)</div></div>', page, re.S)
    assert strip
    m = _metrics(strip.group(0))
    assert len(m) == 4, m
    assert m[0] == (str(len(exp["crit"])), "блокеров")
    assert m[1] == (str(exp["major"]), "существенных")
    assert m[2][0] == str(exp["questions"]) and "вопрос" in m[2][1]
    assert m[3] == (f'{exp["ok"]} из {exp["total"]}', "цитат сверено кодом")
    # блокеры списком: номер, суть, где в документе
    assert re.findall(r'<span class="jb-id">(D-\d+)</span>', page) == exp["crit"]
    assert "строка " in re.search(r'<span class="jb-where">([^<]+)</span>', page).group(1)
    # слот маскота 96 px (BCC AI, №40) и вкладки-капсулы
    assert re.search(r'<div data-bcc-agent data-size="96" data-mood="(alert|verified)"', page)
    for tab in ("Замечания", "Вопросы", "Документ", "Исправленная редакция", "Выгрузки"):
        assert f">{tab}" in page, tab
    res = page[page.index('id="result"'):]
    assert res.count("b-button primary") <= 2  # «Скачать ответы» и «К вопросам» — в разных видах, не вместе
    assert f'data-src="/jobs/{jid}/files/report.html?inline=1"' in page


def test_result_fragment_for_live_page(srv):
    """Прогон закончился при открытой странице: отчёт над рамкой приходит фрагментом, маскот переезжает сам."""
    base, _ = srv
    jid = _done_job(base)
    code, frag = _get(f"{base}/jobs/{jid}?part=result")
    assert code == 200 and "<html" not in frag
    assert 'id="agent-slot"></div>' in frag and "data-bcc-agent" not in frag
    assert len(_metrics(frag)) == 4


def test_progress_page_has_agent_and_stage_list(tmp_path):
    store = R.JobStore(tmp_path)
    job = store.create("tz.md", b"# x\n", "mock", "")
    page = S.job_page(job)
    assert '<div data-bcc-agent data-size="96" data-mood="scanning" id="agent"></div>' in page
    assert 'id="stages"' in page and 'id="result" hidden' in page
    assert 'class="b-status error"' in page and "Что сделать" in (ROOT / "src/bcc_review/v2/web/assets/app.js").read_text(encoding="utf-8")
    assert "/assets/tokens.css" in page and 'class="b-root"' in page


def test_api_reports_model_calls_from_log(tmp_path):
    store = R.JobStore(tmp_path)
    job = store.create("tz.md", b"# x\n", "gemini", "")
    job.log = ["  segment: готово за 3 с, вызовов 1", "  lens_qa: готово за 9 с, вызовов 2, кандидатов 5",
               "  judge: запуск", "  rules: готово за 0 с, вызовов 0, кандидатов 15"]
    assert S.job_calls(job) == 3


def test_css_has_no_external_links():
    for p in (REPORT_CSS, JOB_CSS):
        css = p.read_text(encoding="utf-8")
        assert not re.search(r"https?://|//[a-z0-9.-]+\.[a-z]{2,}/|@import|url\(", css, re.I), p.name


def _tokens() -> dict[str, str]:
    md = DESIGN.read_text(encoding="utf-8")
    return {k: v.upper() for k, v in re.findall(r"--(b-[a-z0-9-]+):(#[0-9A-Fa-f]{6})", md)}


def _root_vars(css: str) -> dict[str, str]:
    root = css[css.index(":root {"):css.index("}", css.index(":root {"))]
    return {k: v.upper() for k, v in re.findall(r"--([a-z0-9-]+):\s*(#[0-9A-Fa-f]{6})", root)}


def test_severity_colors_match_design_section_3():
    """Красный — блокер, золотой — существенное, синий — незначительное, зелёный — можно/сверено."""
    t = _tokens()
    v = _root_vars(REPORT_CSS.read_text(encoding="utf-8"))
    assert v["crit"] == v["crit-acc"] == t["b-red"]
    assert v["major-acc"] == t["b-gold"] and v["major"] == t["b-gold-ink"]  # золото — заливки, текст — gold-ink
    assert v["minor"] == v["minor-acc"] == t["b-blue"]
    assert v["ok"] == v["link"] == t["b-green-ink"] and v["accent"] == t["b-green"] and v["brand"] == t["b-green-strong"]
    assert v["ink"] == t["b-ink"] and v["bg"] == t["b-canvas"]
    # страница задания — те же смыслы через токены №39
    job = JOB_CSS.read_text(encoding="utf-8")
    assert ".jb-verdict .v-no b{color:var(--b-red)}" in job
    assert ".jb-verdict .v-cond b{color:var(--b-gold-ink)}" in job
    assert ".jb-verdict .v-yes b{color:var(--b-green-ink)}" in job


def test_html_report_embeds_new_css_and_keeps_dark_theme():
    rep = json.loads(FIXTURE.read_text(encoding="utf-8"))
    html = H.render_html(rep, H.load_view(DOC))
    assert "--crit-acc: #C2362B" in html and ":root[data-embed]" in html
    assert ':root[data-theme="dark"]' in html and "@media (prefers-color-scheme: dark)" in html
    assert 'id="report-data"' in html and "Исправить первым" in html


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
    assert "Блокеров нет" in html and 'data-ready="1"' in html and 'data-rtab="clarify"' in html
