"""№40: BCC AI — маскот и знакомство с ключом. Без сети: проверка ключа подменена."""
from __future__ import annotations

import json
import logging
import os
import stat
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from bcc_review.v2.web import onboarding as O
from bcc_review.v2.web import runner as R
from bcc_review.v2.web import server as S

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / "src" / "bcc_review" / "v2" / "web" / "assets"
KEY = "AIzaSyTEST0123456789abcdefghijklmn3f9Q"
KEYS = ("GEMINI_API_KEY", "GOOGLE_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_BASE_URL")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):  # noqa: D401
        return None


_opener = urllib.request.build_opener(_NoRedirect)


def _req(url: str, *, data: bytes | None = None, headers: dict | None = None, method: str | None = None):
    req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    try:
        with _opener.open(req) as r:
            return r.status, r.read(), dict(r.headers)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(), dict(exc.headers)


@pytest.fixture()
def calls(monkeypatch, tmp_path):
    """Нет ключей и Claude CLI; проверка ключа подменена; .env — во временной папке."""
    for k in KEYS:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(R, "_have_claude_cli", lambda env: False)
    monkeypatch.setattr(R, "_auto_choice", lambda env: "offline")
    monkeypatch.setattr(O, "ENV_FILE", tmp_path / ".env")
    monkeypatch.setattr(O, "_verified", set())
    seen: list[tuple[str, str]] = []

    def fake(provider, key):
        seen.append((provider, key))
        if key == KEY:
            return True, "Ключ работает"
        return False, "Ключ не подошёл: Google ответил 400. Скопируйте ключ целиком."

    monkeypatch.setattr(O, "verify_key", fake)
    yield seen
    for k in ("GEMINI_API_KEY", "ANTHROPIC_API_KEY"):   # handle_key пишет в os.environ сервера
        os.environ.pop(k, None)


@pytest.fixture()
def base(calls, tmp_path):
    app = S.build_app(tmp_path / "data", provider="auto")
    httpd = S.make_server(app, "127.0.0.1", 0)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    httpd.server_close()


def _post_key(base: str, body: dict, origin: str | None = "same") -> tuple[int, dict, bytes]:
    h = {"Content-Type": "application/json"}
    if origin == "same":
        h["Origin"] = base
    elif origin:
        h["Origin"] = origin
    code, raw, _ = _req(base + "/api/key", data=json.dumps(body).encode(), headers=h, method="POST")
    return code, json.loads(raw), raw


def test_fresh_start_without_keys_goes_to_welcome(base):
    code, _, h = _req(base + "/")
    assert code == 303 and h["Location"] == "/welcome"
    code, body, _ = _req(base + "/welcome")
    text = body.decode()
    assert code == 200
    for s in ("Ключ Gemini", "бесплатно", "Ключ Claude", "Без ключа", "https://aistudio.google.com/apikey",
              "получить за минуту", 'type="password"', "показать", "Проверить ключ",
              "Запомнить на этом компьютере (файл .env)", "Открыть систему", "/assets/agent.js", "Здравствуйте"):
        assert s in text, s


def test_with_key_or_cli_opens_system(base, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "x" * 20)
    assert _req(base + "/")[0] == 200
    monkeypatch.delenv("GEMINI_API_KEY")
    monkeypatch.setattr(R, "_have_claude_cli", lambda env: True)
    assert _req(base + "/")[0] == 200


def test_no_key_choice_sets_cookie_and_opens_system(base):
    code, _, h = _req(base + "/welcome/skip")
    assert code == 303 and h["Location"] == "/"
    cookie = h["Set-Cookie"].split(";")[0]
    assert cookie == "bcc_nokey=1"
    assert _req(base + "/", headers={"Cookie": cookie})[0] == 200
    assert O.status_line(cookie) == "Без ключа: только правила и готовые отчёты"


def test_fixture_and_explicit_provider_skip_welcome(calls, tmp_path):
    sample = ROOT / "tests" / "v2" / "fixtures" / "14_report_official.json"
    assert not O.needs_welcome(S.build_app(tmp_path / "a", fixture=sample), None)
    assert not O.needs_welcome(S.build_app(tmp_path / "b", provider="mock"), None)
    assert O.needs_welcome(S.build_app(tmp_path / "c"), None)


@pytest.mark.parametrize("origin", ["http://evil.example", "http://127.0.0.1:1", "null", "https://localhost"])
def test_foreign_origin_is_403(base, calls, origin):
    code, out, _ = _post_key(base, {"provider": "gemini", "key": KEY, "remember": True}, origin=origin)
    assert code == 403 and not out["ok"]
    assert calls == [] and not O.ENV_FILE.exists() and "GEMINI_API_KEY" not in os.environ


def test_localhost_origin_and_empty_origin_accepted(base):
    port = base.rsplit(":", 1)[1]
    assert _post_key(base, {"provider": "gemini", "key": KEY}, origin=f"http://localhost:{port}")[0] == 200
    assert _post_key(base, {"provider": "gemini", "key": KEY}, origin=None)[0] == 200


def test_good_key_without_remember_does_not_write_env(base, calls):
    code, out, raw = _post_key(base, {"provider": "gemini", "key": KEY, "remember": False})
    assert code == 200 and out["ok"] and out["remembered"] is False
    assert out["mask"] == "AIza…3f9Q"
    assert KEY.encode() not in raw
    assert not O.ENV_FILE.exists()
    assert os.environ["GEMINI_API_KEY"] == KEY       # работающий сервер видит ключ сразу
    assert calls == [("gemini", KEY)]
    assert _req(base + "/")[0] == 200                 # теперь сразу система


def test_remember_writes_env_keeps_other_lines(base, calls):
    O.ENV_FILE.write_text("# мой файл\nOPENAI_MODEL=qwen3:8b\nGEMINI_API_KEY=old-value\nCLAUDE_CLI_MODEL=sonnet\n",
                          encoding="utf-8")
    code, out, raw = _post_key(base, {"provider": "gemini", "key": KEY, "remember": True})
    assert code == 200 and out["ok"] and out["remembered"] is True
    assert KEY.encode() not in raw
    lines = O.ENV_FILE.read_text(encoding="utf-8").splitlines()
    assert lines == ["# мой файл", "OPENAI_MODEL=qwen3:8b", f"GEMINI_API_KEY={KEY}", "CLAUDE_CLI_MODEL=sonnet"]
    if os.name == "posix":
        assert stat.S_IMODE(O.ENV_FILE.stat().st_mode) == 0o600
    # повтор с remember после проверки не вызывает модель второй раз
    _post_key(base, {"provider": "gemini", "key": KEY, "remember": True})
    assert len(calls) == 1


def test_claude_key_goes_to_anthropic_name(base):
    good = "sk-ant-api03-" + "z" * 30
    O_verify = O.verify_key
    try:
        O.verify_key = lambda p, k: (True, "Ключ работает")
        code, out, _ = _post_key(base, {"provider": "claude", "key": good, "remember": True})
    finally:
        O.verify_key = O_verify
    assert code == 200 and out["provider"] == "anthropic"
    assert O.ENV_FILE.read_text(encoding="utf-8").strip() == f"ANTHROPIC_API_KEY={good}"


def test_bad_key_is_alert_and_nothing_written(base):
    bad = "AIzaSyWRONG0000000000000000000000000000"
    code, out, raw = _post_key(base, {"provider": "gemini", "key": bad, "remember": True})
    assert code == 200 and out["ok"] is False
    assert out["message"].startswith("Ключ не подошёл")
    assert bad.encode() not in raw and not O.ENV_FILE.exists() and "GEMINI_API_KEY" not in os.environ


def test_bad_requests(base):
    assert _post_key(base, {"provider": "openai", "key": KEY})[0] == 400
    assert _post_key(base, {"provider": "gemini", "key": "  "})[0] == 400
    code, _, _ = _req(base + "/api/key", data=b"not json", headers={"Content-Type": "application/json"}, method="POST")
    assert code == 400


def test_key_never_in_logs_or_pages(base, capsys, caplog):
    caplog.set_level(logging.DEBUG)
    _post_key(base, {"provider": "gemini", "key": KEY, "remember": True})
    _post_key(base, {"provider": "gemini", "key": KEY + "x"})
    pages = b"".join(_req(base + p)[1] for p in ("/", "/welcome", "/api/providers"))
    err = capsys.readouterr()
    assert KEY not in err.out and KEY not in err.err and KEY not in caplog.text
    assert KEY.encode() not in pages


def test_verify_key_uses_doctor_live_and_scrubs(monkeypatch):
    from bcc_review.v2.providers import doctor
    seen = {}

    def fake_doctor(**kw):
        seen.update(kw)
        kw["out"]("Провайдер: gemini")
        kw["out"](f"  [нет] Google не принял ключ {kw['env']['GEMINI_API_KEY']}\nПодробности: 400 INVALID_ARGUMENT")
        return 2

    monkeypatch.setattr(doctor, "run_doctor", fake_doctor)
    ok, msg = O.verify_key("gemini", KEY)
    assert seen["live"] is True and seen["provider"] == "gemini" and seen["timeout_s"] <= 10
    assert not ok and msg == "Ключ не подошёл: Google ответил 400. Скопируйте ключ целиком."
    assert KEY not in msg
    monkeypatch.setattr(doctor, "run_doctor", lambda **kw: 0)
    assert O.verify_key("gemini", KEY) == (True, "Ключ работает")


def test_mask():
    assert O.mask(KEY) == "AIza…3f9Q"
    assert O.mask("short") == "…"


def test_agent_assets_served(base):
    code, body, h = _req(base + "/assets/agent.js")
    assert code == 200 and "javascript" in h["Content-Type"]
    js = body.decode()
    for s in ("BCCAgent", "mount", "mood", "say", "destroy", "data-bcc-agent", "IntersectionObserver",
              "visibilitychange", "prefers-reduced-motion", "makeDrone"):
        assert s in js, s
    code, body, h = _req(base + "/assets/agent.css")
    css = body.decode()
    assert code == 200 and "text/css" in h["Content-Type"]
    assert "prefers-reduced-motion" in css and "image-rendering:pixelated" in css.replace(" ", "")
    assert len((ASSETS / "agent.js").read_bytes()) < 40 * 1024
    assert "http" not in js.split("*/", 1)[1]          # никаких внешних ссылок
