"""№43: готовые отчёты и примеры документов на главной — без сети, без ключа, модель не вызывается."""
from __future__ import annotations

import json
import os
import shutil
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from bcc_review.v2.web import gallery as G
from bcc_review.v2.web import runner as R
from bcc_review.v2.web import server as S

ROOT = Path(__file__).resolve().parents[2]
EX = ROOT / "src" / "bcc_review" / "v2" / "web" / "examples"
MOCK = EX / "mock"
SAMPLE = ROOT / "tests" / "v2" / "fixtures" / "14_report_official.json"


@pytest.fixture(autouse=True)
def no_keys(monkeypatch):
    """Без ключей и без Claude Code CLI: «Автовыбор» сводится к offline, модель не вызывается."""
    for k in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_BASE_URL"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(R, "_have_claude_cli", lambda env: False)
    monkeypatch.setattr(R, "_auto_choice", lambda env: "offline")


class _NoRun:
    def submit(self, job):  # примеры документов в тестах карточек не запускаем
        pass


def _app(tmp_path: Path) -> S.App:
    store = R.JobStore(tmp_path / "data")
    return S.App(store, _NoRun())


def _examples(tmp_path: Path, reports: list[dict], documents: list[dict] | None = None) -> Path:
    p = tmp_path / "examples.json"
    p.write_text(json.dumps({"reports": reports, "documents": documents or []}, ensure_ascii=False), encoding="utf-8")
    return p


def _serve(app: S.App):
    httpd = S.make_server(app, "127.0.0.1", 0)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, f"http://127.0.0.1:{httpd.server_address[1]}"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def _req(url: str, *, data: bytes | None = None, follow: bool = True, accept: str = "") -> tuple[int, bytes, dict]:
    opener = urllib.request.build_opener() if follow else urllib.request.build_opener(_NoRedirect)
    req = urllib.request.Request(url, data=data, method="POST" if data is not None else "GET",
                                 headers={"Accept": accept} if accept else {})
    try:
        with opener.open(req, timeout=10) as r:
            return r.status, r.read(), dict(r.headers)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(), dict(exc.headers)


def _wait(base: str, jid: str, timeout: float = 60) -> dict:
    t0 = time.time()
    while time.time() - t0 < timeout:
        st = json.loads(_req(f"{base}/api/jobs/{jid}")[1])
        if st["state"] in ("done", "failed"):
            return st
        time.sleep(0.1)
    raise AssertionError("задание не завершилось")


# ─────────────────────────────── examples.json ───────────────────────────────

def test_examples_json_paths_exist():
    raw = json.loads((EX / "examples.json").read_text(encoding="utf-8"))
    ids = [r["id"] for r in raw["reports"]] + [d["id"] for d in raw["documents"]]
    assert len(set(r["id"] for r in raw["reports"])) == len(raw["reports"])
    assert len(set(d["id"] for d in raw["documents"])) == len(raw["documents"])
    assert all(i and i.replace("-", "").isalnum() for i in ids)
    for r in raw["reports"]:
        for k in ("json", "html", "md", "docx", "pdf", "csv", "source"):
            if k in r:
                assert not Path(r[k]).is_absolute() and ".." not in Path(r[k]).parts, r[k]
        assert (ROOT / r["source"]).is_file(), r["source"]
        # отчёт либо есть целиком (json и html), либо ещё не сделан (№36) — тогда карточки нет
        assert (ROOT / r["json"]).is_file() == (ROOT / r["html"]).is_file(), r["id"]
    for d in raw["documents"]:
        assert (ROOT / d["path"]).is_file(), d["path"]
        assert d["no_key"] in ("mock", "offline")
        assert "blind" not in d["path"] and not d["path"].endswith(".key.json")
    mock = next(r for r in raw["reports"] if r["id"] == "mock")
    assert all((ROOT / mock[k]).is_file() for k in ("json", "html", "md"))
    ex = G.load_examples()
    assert sum(r["ok"] for r in ex["reports"]) >= 1 and all(d["ok"] for d in ex["documents"])


def test_mock_report_is_generated_not_handmade():
    rep = json.loads((MOCK / "requirements.json").read_text(encoding="utf-8"))
    run = rep["run"]
    assert run["provider"] == "mock" and run["status"] == "complete" and not run.get("dirty")
    assert rep["document"]["file"] == "requirements.md"
    assert rep["document"]["sha256"] == "e7dae55e5453a250d93e335f5ff9c7f775f4457ccddd333f4a67e47b20d74381"
    assert rep["verdict"]["development"] == "no"
    assert "PYTHONPATH=src python -m bcc_review release/input/requirements.md" in (EX / "README.md").read_text("utf-8")


# ─────────────────────────────── карточки ───────────────────────────────

def test_cards_only_for_existing_files(tmp_path):
    shutil.copy2(MOCK / "requirements.json", tmp_path / "r.json")
    shutil.copy2(MOCK / "requirements.html", tmp_path / "r.html")
    (tmp_path / "doc.md").write_text("# ТЗ\n", encoding="utf-8")
    reports = [
        {"id": "have", "title": "Есть отчёт", "json": "r.json", "html": "r.html", "md": "nope.md", "source": "doc.md"},
        {"id": "nojson", "title": "Нет json", "json": "missing.json", "html": "r.html", "md": "", "source": "doc.md"},
        {"id": "nohtml", "title": "Нет html", "json": "r.json", "html": "missing.html", "md": "", "source": "doc.md"},
        {"id": "nosrc", "title": "Нет документа", "json": "r.json", "html": "r.html", "md": "", "source": "x.md"},
    ]
    docs = [{"id": "d1", "title": "Пример", "path": "doc.md", "no_key": "offline"},
            {"id": "d2", "title": "Нет файла", "path": "none.md", "no_key": "offline"}]
    ex = G.load_examples(_examples(tmp_path, reports, docs), tmp_path)
    assert [r["id"] for r in ex["reports"] if r["ok"]] == ["have"]
    app = _app(tmp_path)
    html = G.reports_block(app, ex)
    assert html.count('class="b-surface g43-card"') == 1
    assert "Есть отчёт" in html and "Нет json" not in html and "Нет документа" not in html
    assert "Демо без модели · 27.11.2026" in html and "вердикт: нельзя, блокеров 5" in html
    assert 'b-badge crit' in html
    btns = G.documents_block(ex)
    assert "/examples/check/d1" in btns and "d2" not in btns and "только правила" in btns


def test_gallery_block_on_real_examples(tmp_path):
    app = _app(tmp_path)
    html = G.gallery_block(app)
    ok = [r for r in G.load_examples()["reports"] if r["ok"]]
    assert html.count('class="b-surface g43-card"') == len(ok) >= 1
    assert "Готовые отчёты" in html and "/examples/mock" in html
    assert "Проверить пример" in html and "/examples/check/official" in html
    assert "Без ключа: официальный ТЗ — демо без модели, остальные — только правила." in html
    assert "http://" not in html and "https://" not in html  # без внешних ссылок
    ready = [j for j in app.store.jobs.values() if G.is_ready(j)]
    assert len(ready) == len(ok) and all(j.state == "done" for j in ready)
    assert not G.is_ready("20261127-120000-abcdef")


def test_empty_when_nothing_to_show(tmp_path, monkeypatch):
    monkeypatch.setattr(G, "EXAMPLES", _examples(tmp_path, [{"id": "x", "json": "a", "html": "b", "md": "", "source": "c"}]))
    assert G.gallery_block(_app(tmp_path)) == ""
    monkeypatch.setattr(G, "EXAMPLES", tmp_path / "no-such.json")
    assert G.gallery_block(_app(tmp_path)) == ""


def test_ready_job_survives_restart_and_refreshes(tmp_path):
    shutil.copy2(MOCK / "requirements.json", tmp_path / "r.json")
    shutil.copy2(MOCK / "requirements.html", tmp_path / "r.html")
    shutil.copy2(ROOT / "release" / "input" / "requirements.md", tmp_path / "requirements.md")
    (tmp_path / "r.docx").write_bytes(b"PK\x03\x04")
    reports = [{"id": "m", "title": "Мок", "json": "r.json", "html": "r.html", "md": "", "docx": "r.docx",
                "pdf": "missing.pdf", "source": "requirements.md"}]
    exp = _examples(tmp_path, reports)
    app = _app(tmp_path)
    jid = G.ensure_ready(app, G.load_examples(exp, tmp_path))["m"]
    assert G.is_ready(jid) and S.JOB_PATH.match(f"/jobs/{jid}")
    job = app.store.get(jid)
    assert job.file_name == "requirements.md" and job.provider == "mock" and job.summary["critical"] == 5
    assert {"html", "json", "docx"} <= set(job.files) and "md" not in job.files and "pdf" not in job.files
    assert job.notice.startswith("Готовый отчёт")
    # «Последние проверки» — только свои проверки пользователя
    own = app.store.create("my.md", b"# x\n", "offline", "")
    assert [j.id for j in app.store.recent()] == [own.id]
    # перезапуск сервера: JobStore готовое задание не подхватывает (нет job.json), ensure_ready берёт его с диска
    app2 = _app(tmp_path)
    assert app2.store.get(jid) is None and [j.id for j in app2.store.recent()] == [own.id]
    mtime = (app2.store.dir(jid) / "ready.json").stat().st_mtime_ns
    assert G.ensure_ready(app2, G.load_examples(exp, tmp_path))["m"] == jid
    assert (app2.store.dir(jid) / "ready.json").stat().st_mtime_ns == mtime  # не пересобиралось
    assert app2.store.get(jid).state == "done" and [j.id for j in app2.store.recent()] == [own.id]
    assert app2.store.get(jid).input_path == str(app2.store.dir(jid) / "input" / "requirements.md")
    # отчёт обновился → новый номер задания, старое удалено
    rep = json.loads((tmp_path / "r.json").read_text(encoding="utf-8"))
    rep["verdict"]["development"] = "conditional"
    (tmp_path / "r.json").write_text(json.dumps(rep, ensure_ascii=False), encoding="utf-8")
    jid2 = G.ensure_ready(app2, G.load_examples(exp, tmp_path))["m"]
    assert jid2 != jid and app2.store.get(jid) is None and not app2.store.dir(jid).exists()
    assert "с условиями" in G.reports_block(app2, G.load_examples(exp, tmp_path))


def test_model_label():
    assert G.model_label({"provider": "anthropic", "models_used": ["claude-sonnet-5-5"]}) == "Claude Sonnet"
    assert G.model_label({"provider": "claude_cli", "models_used": ["sonnet"]}) == "Claude Sonnet"
    assert G.model_label({"provider": "gemini", "models_used": ["gemini-3.8-flash"]}) == "Gemini 3.8 Flash"
    assert G.model_label({"provider": "mock", "models_used": ["mock"]}) == "Демо без модели"
    assert G.model_label({"provider": "offline"}) == "Только правила"


# ─────────────────────────────── сервер ───────────────────────────────

def test_ready_report_opens_fast(tmp_path):
    app = S.build_app(tmp_path / "data", fixture=SAMPLE, step_s=0.01)
    httpd, base = _serve(app)
    try:
        t0 = time.time()
        code, _, hdr = _req(base + "/examples/mock", follow=False)
        assert code == 303 and hdr["Location"].startswith("/jobs/" + G.PREFIX)
        jid = hdr["Location"].rsplit("/", 1)[-1]
        code, page, _ = _req(base + hdr["Location"])
        assert code == 200 and f'data-job="{jid}"' in page.decode()
        st = json.loads(_req(f"{base}/api/jobs/{jid}")[1])
        assert st["state"] == "done" and {"html", "json", "md"} <= set(st["files"])
        assert st["summary"]["critical"] == 5 and st["notice"]
        code, html, hdr = _req(f"{base}/jobs/{jid}/files/report.html?inline=1")
        assert code == 200 and b"<!doctype html>" in html.lower()[:200]
        assert time.time() - t0 < 1.0  # готовый отчёт открывается меньше чем за секунду
        assert _req(base + "/examples/no-such", follow=False)[0] == 404
        assert _req(base + "/examples/check/no-such", data=b"", follow=False)[0] == 404
    finally:
        httpd.shutdown()
        httpd.server_close()


@pytest.mark.parametrize("doc_id, provider", [("transfer-limit", "offline"), ("official", "mock")])
def test_example_document_checks_without_key(tmp_path, monkeypatch, doc_id, provider):
    """Пример документа одним нажатием: настоящий pipeline, без ключа — offline или mock, отчёт открывается."""
    monkeypatch.setenv("PYTHONPATH", os.pathsep.join([str(ROOT / "src"), os.environ.get("PYTHONPATH", "")]))
    app = S.build_app(tmp_path / "data")
    httpd, base = _serve(app)
    try:
        code, body, _ = _req(f"{base}/examples/check/{doc_id}", data=b"", accept="application/json")
        assert code == 201, body
        j = json.loads(body)
        assert j["provider"] == provider
        st = _wait(base, j["id"])
        assert st["state"] == "done", st
        assert st["provider"] == provider and "html" in st["files"]
        if provider == "offline":
            assert "без модели" in st["notice"].lower()
        else:
            assert st["summary"]["critical"] == 5
        code, _, hdr = _req(f"{base}/examples/check/{doc_id}", data=b"", follow=False)
        assert code == 303 and hdr["Location"].startswith("/jobs/")
    finally:
        httpd.shutdown()
        httpd.server_close()
