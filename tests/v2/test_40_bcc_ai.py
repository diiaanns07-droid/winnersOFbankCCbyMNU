"""№40: BCC AI — маскот и знакомство с ключом. Без сети: проверка ключа подменена."""
from __future__ import annotations

import io
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
    for s in ("Ключ модели для BCC AI", "Здравствуйте", "Gemini — бесплатно", "Claude", "https://aistudio.google.com/apikey",
              'type="password"', "показать", "Проверить ключ", "Запомнить на этом компьютере (файл .env)",
              "Открыть систему", "Продолжить без ключа", "/welcome/skip", "/assets/agent.js", "/assets/agent.css",
              "#F3F6F5", 'id="w-verdict"', "не проверен", 'data-size="48"', "backdrop-filter"):
        assert s in text, s
    # светло и мягко: ни тёмного стола, ни печати, ни тёмного дрона, ни таблеток выбора
    for banned in ("#0B1220", "w-stamp", "feTurbulence", "КЛЮЧ ПРИНЯТ", "radial-gradient", "w-pill", "makeDrone"):
        assert banned not in text, banned


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
              "visibilitychange", "prefers-reduced-motion", "makePixelBot", "PBASE", "tenge"):
        assert s in js, s
    assert "makeDrone" not in js and "DSK" not in js       # тёмного дрона больше нет нигде
    code, body, h = _req(base + "/assets/agent.css")
    css = body.decode()
    assert code == 200 and "text/css" in h["Content-Type"]
    assert "prefers-reduced-motion" in css and "image-rendering:pixelated" in css.replace(" ", "")
    assert len((ASSETS / "agent.js").read_bytes()) < 40 * 1024
    assert "http" not in js.split("*/", 1)[1]          # никаких внешних ссылок


def test_auto_provider_by_key_prefix(base):
    code, out, _ = _post_key(base, {"provider": "auto", "key": KEY})
    assert code == 200 and out["provider"] == "gemini" and out["ok"]
    code, out, _ = _post_key(base, {"key": "sk-ant-api03-" + "q" * 30})          # провайдер не указан — по виду ключа
    assert code == 200 and out["provider"] == "anthropic"
    code, out, _ = _post_key(base, {"provider": "auto", "key": "hello-world-123456"})
    assert code == 400 and "AIza" in out["message"]


def test_skip_from_terminal_hides_welcome(calls, tmp_path, monkeypatch):
    monkeypatch.setattr(O, "SKIP_WELCOME", False)
    app = S.build_app(tmp_path / "d")
    assert O.needs_welcome(app, None)
    monkeypatch.setattr(O, "SKIP_WELCOME", True)
    assert not O.needs_welcome(app, None)


# ─────────────────────────────── терминал (tty_agent) ───────────────────────────────

from bcc_review.v2.web import tty_agent as T  # noqa: E402


class _Out(io.TextIOWrapper):
    def __init__(self):
        super().__init__(io.BytesIO(), encoding="utf-8", write_through=True)

    def text(self) -> str:
        self.flush()
        return self.buffer.getvalue().decode("utf-8")


@pytest.fixture()
def tty(calls, monkeypatch):
    monkeypatch.setattr(T, "_sleep", lambda s: None)
    monkeypatch.setattr(O, "SKIP_WELCOME", False)
    monkeypatch.setenv("COLUMNS", "100")
    monkeypatch.setenv("LINES", "40")
    return calls


def _greet(asked, answers=("д",), **kw):
    out = _Out()
    secrets = list(asked)
    replies = list(answers)
    prompts = []

    def ask_secret(prompt):
        prompts.append(prompt)
        return secrets.pop(0)

    def ask(prompt):
        prompts.append(prompt)
        return replies.pop(0)

    kw.setdefault("interactive", True)
    kw.setdefault("mode", "truecolor")
    r = T.greet(8014, O.ENV_FILE, stdout=out, ask_secret=ask_secret, ask=ask, **kw)
    return r, out.text(), prompts


def test_greet_without_tty_asks_nothing(tty):
    r, text, prompts = _greet([], interactive=None)          # _Out — не терминал
    assert r == "" and prompts == []
    assert "http://127.0.0.1:8014/welcome" in text and "\x1b[" not in text


def test_greet_without_tty_with_key_one_line(tty, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", KEY)
    r, text, prompts = _greet([], interactive=None)
    assert r == "gemini" and prompts == []
    assert "AIza…3f9Q" in text and KEY not in text and text.count("\n") == 1


def test_greet_good_key_remembered(tty):
    r, text, prompts = _greet([KEY], ["д"])
    assert r == "gemini"
    assert tty == [("gemini", KEY)]                           # проверка — тем же кодом, что /api/key (verify_key)
    assert "▀" in text and "\x1b[38;2;" in text               # дрон 24-битным цветом
    assert "Здравствуйте! Я BCC AI" in text and "Ключ работает" in text and "AIza…3f9Q" in text
    assert "https://aistudio.google.com/apikey" in text
    assert KEY not in text
    assert O.ENV_FILE.read_text(encoding="utf-8").strip() == f"GEMINI_API_KEY={KEY}"
    assert os.environ["GEMINI_API_KEY"] == KEY
    assert any("[Д/н]" in p for p in prompts)
    assert text.endswith("\x1b[?25h\x1b[0m")                  # курсор вернули, цвет сбросили


def test_greet_key_not_remembered(tty):
    r, text, _ = _greet([KEY], ["н"])
    assert r == "gemini" and not O.ENV_FILE.exists() and os.environ["GEMINI_API_KEY"] == KEY


def test_greet_bad_key_then_enter_is_offline(tty):
    r, text, prompts = _greet(["AIzaSyWRONG0000000000000000000000000000", ""])
    assert r == "offline" and O.SKIP_WELCOME is True
    assert "Ключ не подошёл: Google ответил 400" in text
    assert not O.ENV_FILE.exists() and "GEMINI_API_KEY" not in os.environ
    assert len([p for p in prompts if "Ключ" in p]) == 2


def test_greet_unknown_key_is_not_sent(tty):
    r, text, _ = _greet(["hello", ""])
    assert r == "offline" and tty == []
    assert "AIza" in text and "sk-ant-" in text


def test_greet_returning_user(tty, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-api03-" + "w" * 30)
    r, text, prompts = _greet([])
    assert r == "anthropic" and prompts == [] and "С возвращением!" in text and "wwww" not in text.replace("…wwww", "")


def test_greet_claude_cli_needs_no_key(tty, monkeypatch):
    monkeypatch.setattr(R, "_have_claude_cli", lambda env: True)
    r, text, prompts = _greet([])
    assert r == "claude_cli" and prompts == [] and "Claude Code" in text


def test_greet_ascii_and_256(tty):
    r, text, _ = _greet([""], mode="ascii")
    assert r == "offline" and "\x1b" not in text and "/ oo \\" in text
    lines = T.render("idle", "256")
    assert any("38;5;" in ln for ln in lines) and not any("38;2;" in ln for ln in lines)
    # AIshka без пустых полей, вдвое меньше: 18 строк полублоков (в тесном окне — 9), не шире 40 колонок
    assert len(T.render("idle", "truecolor")) == 18 and len(T.render("idle", "truecolor", small=True)) == 9
    assert max(len(T._ANSI.sub("", ln)) for ln in T.render("analyzing0", "truecolor")) <= 2 + 40


def test_color_mode_detection():
    out = _Out()
    assert T.color_mode(out, {"NO_COLOR": "1", "COLORTERM": "truecolor"}) == "ascii"
    assert T.color_mode(out, {"TERM": "dumb"}) == "ascii"
    assert T.color_mode(io.StringIO(), {"COLORTERM": "truecolor"}) == "ascii"   # кодировка неизвестна — без «▀»
    if os.name == "posix":
        assert T.color_mode(out, {"COLORTERM": "truecolor", "TERM": "xterm"}) == "truecolor"
        assert T.color_mode(out, {"TERM": "xterm-256color"}) == "256"


def test_xterm256_mapping():
    assert T.xterm256((0, 0, 0)) == 16
    assert T.xterm256((255, 255, 255)) == 231
    assert 232 <= T.xterm256((128, 128, 128)) <= 255
