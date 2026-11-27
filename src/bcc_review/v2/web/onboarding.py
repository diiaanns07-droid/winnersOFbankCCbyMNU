"""Знакомство с BCC AI (№40): первый запуск без модели → /welcome, проверка и сохранение ключа.

Маршруты (подключаются одной строкой в начале ``Handler.do_GET`` / ``do_POST``)::

    GET  /                  → 303 /welcome, если ни один провайдер с моделью не готов и «Без ключа» не выбран
    GET  /welcome           окно ключа — лист на тёмном столе (запасной путь, если не было терминала)
    GET  /welcome/skip      «Без ключа»: cookie и в систему (провайдер offline)
    GET  /assets/agent.js   маскот
    GET  /assets/agent.css
    POST /api/key           {"provider": "gemini"|"anthropic", "key": "…", "remember": bool}

Ключ проверяется тем же кодом, что ``python -m bcc_review doctor --live`` (:func:`run_doctor`), не дольше 10 с.
Ключ не попадает ни в журнал, ни в ответ, ни в HTML: наружу — только маска ``AIza…3f9Q``.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
from html import escape
from pathlib import Path
from typing import Any, Callable

ASSETS = Path(__file__).with_name("assets")
COOKIE = "bcc_nokey"
MODEL_PROVIDERS = ("claude_cli", "gemini", "anthropic", "openai")
ENV_NAME = {"gemini": "GEMINI_API_KEY", "anthropic": "ANTHROPIC_API_KEY"}
VENDOR = {"gemini": "Google", "anthropic": "Anthropic"}
GEMINI_KEY_URL = "https://aistudio.google.com/apikey"
CLAUDE_KEY_URL = "https://console.anthropic.com/settings/keys"
CHECK_BUDGET_S = 9.0
NO_KEY_LINE = "Без ключа: только правила и готовые отчёты"
HELLO = "Здравствуйте! Я BCC AI, проверяю ТЗ до начала разработки. Чтобы думать, мне нужен ключ модели."
HELLO_LINE = "Здравствуйте! Вставьте ключ модели в строку 4 — и начнём."
HELLO_SHORT = "Здравствуйте! Ключ — в строку 4."   # узкий экран: реплика остаётся одной строкой
MAX_BODY = 8 * 1024

ENV_FILE: Path | None = None          # куда писать .env; None — .env в текущем каталоге (тесты подменяют)
SKIP_WELCOME = False                  # в терминале выбрали «без ключа» (tty_agent.greet) — окно ключа не показываем
_verified: set[str] = set()           # отпечатки ключей, уже прошедших проверку в этом процессе
_lock = threading.Lock()


# ─────────────────────────────── состояние ───────────────────────────────

def has_model_provider() -> bool:
    """Готов ли хоть один провайдер с моделью (Claude Code CLI, Gemini, Claude API, свой сервер)."""
    from .runner import provider_status
    return any(p["ok"] for p in provider_status() if p["id"] in MODEL_PROVIDERS)


def _cookies(header: str | None) -> dict[str, str]:
    out: dict[str, str] = {}
    for part in (header or "").split(";"):
        k, _, v = part.strip().partition("=")
        if k:
            out[k] = v
    return out


def chose_no_key(cookie_header: str | None) -> bool:
    return _cookies(cookie_header).get(COOKIE) == "1"


def _fixture_mode(app: Any) -> bool:
    from .runner import FixtureRunner
    return isinstance(getattr(getattr(app, "worker", None), "runner", None), FixtureRunner)


def needs_welcome(app: Any, cookie_header: str | None) -> bool:
    """Показывать ли знакомство: провайдер «auto», не показ по фикстуре, модели нет и «Без ключа» не выбран."""
    if SKIP_WELCOME or getattr(app, "default_provider", "auto") != "auto" or _fixture_mode(app):
        return False
    return not chose_no_key(cookie_header) and not has_model_provider()


def status_line(cookie_header: str | None = None) -> str:
    """Строка состояния для главной (№39): «Gemini · ключ проверен» или «Без ключа: только правила…»."""
    from .runner import provider_status
    ready = [p for p in provider_status() if p["id"] in MODEL_PROVIDERS and p["ok"]]
    if not ready:
        return NO_KEY_LINE
    p = ready[0]
    for pid, name in ENV_NAME.items():
        if p["id"] == pid and _fingerprint(os.environ.get(name, "")) in _verified:
            return f"{p['label']} · ключ проверен"
    return f"{p['label']} · {p['note']}"


# ─────────────────────────────── ключ ───────────────────────────────

def mask(key: str) -> str:
    key = (key or "").strip()
    return f"{key[:4]}…{key[-4:]}" if len(key) >= 12 else "…"


def _fingerprint(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest() if key else ""


def _scrub(text: str, key: str) -> str:
    if key:
        text = text.replace(key, mask(key))
    return re.sub(r"(AIza|sk-ant-)[A-Za-z0-9_\-]{8,}", lambda m: mask(m.group(0)), text)


def _first_sentence(text: str, limit: int = 180) -> str:
    text = " ".join(text.split())
    m = re.search(r"^(.+?[.!?])(\s|$)", text)
    s = m.group(1) if m else text
    return s if len(s) <= limit else s[:limit - 1].rstrip() + "…"


def verify_key(provider: str, key: str) -> tuple[bool, str]:
    """Проверка ключа пробным вызовом — функцией ``doctor --live``. (ok, одна строка для человека)."""
    from bcc_review.v2.providers.doctor import NO, run_doctor
    env = {k: v for k, v in os.environ.items() if k not in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "ANTHROPIC_API_KEY")}
    env[ENV_NAME[provider]] = key
    lines: list[str] = []
    try:
        code = run_doctor(live=True, provider=provider, env=env, out=lines.append, timeout_s=CHECK_BUDGET_S)
    except Exception as exc:  # noqa: BLE001 — человеку одна строка, без трейсбэка и без ключа
        lines.append(f"{NO} {type(exc).__name__}: {exc}")
        code = 2
    text = _scrub("\n".join(lines), key)
    vendor = VENDOR[provider]
    if code == 0 or "Модель ответила" in text:
        return True, "Ключ работает"
    if "Ключ рабочий" in text:
        return True, "Ключ работает, но лимит запросов сейчас исчерпан — подождите минуту перед проверкой"
    tail = text.split("Провайдер:", 1)[-1]
    fails = [ln.strip()[len(NO):].strip() for ln in tail.splitlines() if ln.strip().startswith(NO)]
    detail = " ".join(fails) or tail
    status = re.search(r"\b(400|401|403)\b", tail)
    low = detail.lower()
    if re.search(r"не установлен|no module|pip install", low):
        return False, _first_sentence(f"Не хватает пакета для {vendor}: выполните pip install -r requirements.txt.")
    if not status and re.search(r"прокси|брандмауэр|не ответил|не отвечает|соединени|network|timeout|timed out", low):
        return False, f"Нет связи с {vendor}: проверьте интернет, прокси или брандмауэр."
    if not status and re.search(r"\b429\b|лимит запросов|quota|rate.?limit", low):
        return True, "Ключ работает, но лимит запросов сейчас исчерпан — подождите минуту перед проверкой"
    about_key = re.search(r"ключ|api.?key|unauthori|authenticat|permission|forbidden|отклон", low + tail.lower())
    if about_key or (status and status.group(1) in ("401", "403")):
        said = f"{vendor} ответил {status.group(1)}" if status else f"{vendor} его отклонил"
        return False, f"Ключ не подошёл: {said}. Скопируйте ключ целиком."
    if status:
        return False, f"{vendor} ответил {status.group(1)}: {_first_sentence(detail, 140)}"
    return False, _first_sentence(detail) or "Проверка не прошла. Попробуйте ещё раз."


def detect_provider(key: str) -> str:
    """По виду ключа: AIza… — Gemini, sk-ant-… — Claude. Иначе пусто."""
    if key.startswith("AIza"):
        return "gemini"
    if key.startswith("sk-ant-"):
        return "anthropic"
    return ""


def accept_key(provider: str, key: str, *, remember: bool, path: Path | None = None) -> str:
    """Проверенный ключ — в окружение работающего сервера, при ``remember`` — в .env. Пусто — всё записано."""
    name = ENV_NAME[provider]
    with _lock:
        _verified.add(_fingerprint(provider + ":" + key))
        _verified.add(_fingerprint(key))
        os.environ[name] = key
        if remember:
            try:
                write_env(path or env_path(), name, key)
            except OSError as exc:
                return f"Ключ работает, но файл .env не записан: {exc.strerror or 'нет доступа'}."
    return ""


def env_path() -> Path:
    return ENV_FILE if ENV_FILE is not None else Path.cwd() / ".env"


def write_env(path: Path, name: str, value: str) -> None:
    """Записать NAME=value в .env: прежнее значение заменить, остальные строки не трогать, права 600."""
    lines: list[str] = []
    if path.is_file():
        from bcc_review.v2.providers.doctor import read_env_text
        lines = read_env_text(path).splitlines()
    pat = re.compile(r"^\s*(export\s+)?" + re.escape(name) + r"\s*=")
    new = f"{name}={value}"
    done = False
    for i, ln in enumerate(lines):
        if pat.match(ln):
            if not done:
                lines[i], done = new, True
            else:
                lines[i] = None  # type: ignore[call-overload]  # дубликаты прежнего ключа убираем
    lines = [ln for ln in lines if ln is not None]
    if not done:
        lines.append(new)
    data = ("\n".join(lines) + "\n").encode("utf-8")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def handle_key(body: dict[str, Any], *, verify: Callable[[str, str], tuple[bool, str]] | None = None
               ) -> tuple[int, dict[str, Any]]:
    """Логика POST /api/key без HTTP: (код, ответ). Ключа в ответе нет — только маска."""
    provider = str(body.get("provider") or "auto").strip().lower()
    if provider == "claude":
        provider = "anthropic"
    key = re.sub(r"\s+", "", str(body.get("key") or ""))
    if not key:
        return 400, {"ok": False, "message": "Вставьте ключ в поле."}
    if provider == "auto":
        provider = detect_provider(key)
        if not provider:
            return 400, {"ok": False, "message": "Не похоже на ключ: у Gemini он начинается с AIza, у Claude — с sk-ant-."}
    if provider not in ENV_NAME:
        return 400, {"ok": False, "message": "Нужен ключ Gemini или Claude."}
    if len(key) > 400:
        return 400, {"ok": False, "message": "Это не похоже на ключ: слишком длинный текст."}
    remember = body.get("remember") is True
    fp = _fingerprint(provider + ":" + key)
    with _lock:
        known = fp in _verified
    if known:
        ok, msg = True, "Ключ работает"
    else:
        ok, msg = (verify or verify_key)(provider, key)
    out: dict[str, Any] = {"ok": ok, "provider": provider, "mask": mask(key), "message": msg, "remembered": False}
    if not ok:
        return 200, out
    problem = accept_key(provider, key, remember=remember)
    if problem:
        out["message"] = problem
    else:
        out["remembered"] = remember
    return 200, out


# ─────────────────────────────── HTTP ───────────────────────────────

def _same_origin(handler: Any) -> bool:
    origin = (handler.headers.get("Origin") or "").strip()
    if not origin:
        return True
    port = handler.server.server_address[1]
    if origin in (f"http://127.0.0.1:{port}", f"http://localhost:{port}", f"http://[::1]:{port}"):
        return True
    # Docker пробрасывает порт: страница открыта на localhost:<другой порт> — тот же источник, если совпал с Host
    host = (handler.headers.get("Host") or "").strip()
    return bool(re.fullmatch(r"(127\.0\.0\.1|localhost|\[::1\])(:\d+)?", host)) and origin == f"http://{host}"


def handle_get(handler: Any, path: str) -> bool:
    """True — запрос обработан здесь."""
    if path == "/" and needs_welcome(handler.app, handler.headers.get("Cookie")):
        handler._send(303, b"", "text/plain; charset=utf-8", {"Location": "/welcome"})
        return True
    if path == "/welcome":
        handler._html(200, welcome_page())
        return True
    if path == "/welcome/skip":
        handler._send(303, b"", "text/plain; charset=utf-8",
                      {"Location": "/", "Set-Cookie": f"{COOKIE}=1; Path=/; Max-Age=31536000; SameSite=Lax"})
        return True
    if path in ("/assets/agent.js", "/assets/agent.css"):
        p = ASSETS / path.rsplit("/", 1)[-1]
        ctype = "text/javascript; charset=utf-8" if path.endswith(".js") else "text/css; charset=utf-8"
        handler._send(200, p.read_bytes(), ctype)
        return True
    return False


def handle_post(handler: Any, path: str) -> bool:
    if path != "/api/key":
        return False
    if not _same_origin(handler):
        handler._json(403, {"ok": False, "message": "Запрос не с этой страницы."})
        return True
    try:
        length = int(handler.headers.get("Content-Length") or 0)
    except ValueError:
        length = -1
    if length < 0 or length > MAX_BODY:
        handler._json(400, {"ok": False, "message": "Слишком большой запрос."})
        return True
    try:
        body = json.loads(handler.rfile.read(length).decode("utf-8") or "{}")
        if not isinstance(body, dict):
            raise ValueError
    except (ValueError, UnicodeDecodeError):
        handler._json(400, {"ok": False, "message": "Нужен JSON: provider, key, remember."})
        return True
    code, out = handle_key(body)
    handler._json(code, out)
    return True


# ─────────────────────────────── страница ───────────────────────────────
# Запасной путь (двойной щелчок без терминала): не модалка, а лист на тёмном столе — как всё в системе.

def _e(v: Any) -> str:
    return escape("" if v is None else str(v), quote=True)


PAGE_CSS = """
:root{--canvas:#F3F6F5;--paper:#FFFFFF;--ink:#0F2841;--ink2:#3A5068;--ink3:#5B6F84;--num:#A3B0BE;--hair:rgba(15,40,65,.08);
--hair2:rgba(15,40,65,.14);--green:#00B975;--gs:#008556;--gi:#00704A;--red:#C2362B;--r-lg:22px;
--shadow-1:0 1px 2px rgba(15,40,65,.04),0 6px 18px rgba(15,40,65,.06);--shadow-2:0 2px 6px rgba(15,40,65,.05),0 16px 40px rgba(15,40,65,.10);
--ease:cubic-bezier(.2,.8,.2,1);--pad-l:92px;--pad-r:64px;
--sans:Inter,"Suisse Int'l",-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Arial,sans-serif;
--mono:"JetBrains Mono",ui-monospace,SFMono-Regular,Consolas,"Liberation Mono",monospace}
*{box-sizing:border-box}
html,body{margin:0;min-height:100%;background:var(--canvas)}
body{color:var(--ink);font:400 17px/1.55 var(--sans);-webkit-font-smoothing:antialiased;overflow-x:hidden}
.w-bg{position:fixed;inset:0;pointer-events:none;z-index:0;overflow:hidden}
.w-bg::before,.w-bg::after{content:"";position:absolute;border-radius:50%;filter:blur(110px)}
.w-bg::before{width:680px;height:680px;left:-260px;top:-300px;background:rgba(0,185,117,.18)}
.w-bg::after{width:620px;height:620px;right:-240px;top:-220px;background:rgba(220,162,98,.26)}
.w-top{position:sticky;top:12px;z-index:5;max-width:1180px;margin:12px auto 0;height:60px;display:flex;align-items:center;
gap:12px;padding:0 18px 0 10px;border-radius:20px;background:linear-gradient(180deg,rgba(255,255,255,.76),rgba(255,255,255,.56));
-webkit-backdrop-filter:blur(24px) saturate(175%);backdrop-filter:blur(24px) saturate(175%);
box-shadow:inset 0 1px 0 rgba(255,255,255,.95),0 0 0 1px rgba(15,40,65,.06),var(--shadow-2)}
@supports not ((backdrop-filter:blur(1px)) or (-webkit-backdrop-filter:blur(1px))){.w-top{background:rgba(255,255,255,.92)}}
.w-brand{display:inline-flex;align-items:center;gap:10px;color:var(--ink);text-decoration:none;font:650 16px var(--sans);letter-spacing:-.01em}
.w-brand .bcc-agent{gap:0}
.w-top-note{margin-left:auto;font:400 15px var(--sans);color:var(--ink3)}
.w-desk{position:relative;z-index:1;padding:196px 16px 96px}
.w-sheet{position:relative;max-width:760px;margin:0 auto;background:var(--paper);color:var(--ink);border-radius:var(--r-lg);
padding:0 var(--pad-r) 48px var(--pad-l);box-shadow:0 0 0 1px var(--hair),var(--shadow-1);counter-reset:ln;
animation:w-in 360ms var(--ease) both}
@keyframes w-in{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:none}}
.w-head{margin:0 calc(var(--pad-r) * -1) 34px calc(var(--pad-l) * -1);
padding:15px var(--pad-r) 14px var(--pad-l);border-bottom:1px solid var(--hair);font:400 15px/1.4 var(--sans);color:var(--ink3)}
#w-verdict{color:var(--ink2)}
#w-verdict b{font-weight:600;color:var(--ink)}
#w-verdict.is-ok b{color:var(--gi)}
#w-verdict.is-bad b{color:var(--red)}
.w-head .w-sep{color:var(--num)}
.ln{position:relative;margin:0}
.ln::before{counter-increment:ln;content:counter(ln);position:absolute;left:-62px;width:34px;text-align:right;top:.5em;
font:400 12px/1 var(--mono);color:var(--num)}
.w-h{font:700 28px/1.25 var(--sans);margin:0 0 14px;letter-spacing:-.025em}
.w-h::before{top:.72em}
.w-p{font:400 17px/1.6 var(--sans);color:var(--ink)}
.w-form{position:relative;margin-top:26px}
.w-field{position:relative;display:flex;align-items:baseline;gap:14px;padding:6px 2px 7px 0;border-bottom:1px solid var(--hair2);
transition:border-color 120ms var(--ease)}
.w-field::before{top:1em}
.w-field:focus-within{border-bottom-color:var(--green)}
.w-field label{font:400 17px/1.6 var(--sans);color:var(--ink3);flex:0 0 auto}
.w-field input{flex:1;min-width:0;border:0;outline:0;background:transparent;font:400 15px/1.8 var(--mono);color:var(--ink);
letter-spacing:.02em;padding:0}
.w-field input::placeholder{color:#A9B5C2}
.w-show{border:0;background:none;font:500 15px var(--sans);color:var(--ink3);cursor:pointer;padding:2px 0;
text-decoration:underline;text-underline-offset:3px;text-decoration-color:var(--hair2)}
.w-show:hover{color:var(--ink)}
.w-field.is-bad{border-bottom-color:var(--red);box-shadow:0 1px 0 var(--red)}
.w-field.is-checking::after{content:"";position:absolute;left:0;bottom:-1.5px;width:28%;height:2px;border-radius:1px;background:var(--green);
animation:w-scan 1.1s var(--ease) infinite alternate}
@keyframes w-scan{from{left:0}to{left:72%}}
.w-hint{font:400 15px/1.6 var(--sans);color:var(--ink3);margin-top:12px}
.w-hint::before{top:.55em}
.w-sheet a{color:var(--gi);text-decoration-thickness:1px;text-underline-offset:3px;text-decoration-color:rgba(0,112,74,.35)}
.w-remember{display:flex;align-items:center;gap:10px;margin-top:16px;font:400 17px/1.6 var(--sans);color:var(--ink);cursor:pointer}
.w-remember::before{top:.6em}
.w-remember input{width:18px;height:18px;margin:0;accent-color:var(--gs)}
.w-actions{display:flex;flex-wrap:wrap;align-items:center;gap:20px;margin-top:30px}
.w-btn{height:46px;padding:0 24px;border:0;border-radius:999px;background:var(--gs);color:#fff;font:600 16px var(--sans);
cursor:pointer;display:inline-flex;align-items:center;box-shadow:var(--shadow-1);
transition:transform 120ms var(--ease),box-shadow 120ms var(--ease),background-color 120ms var(--ease)}
.w-btn:hover{background:#007A4F;transform:translateY(-1px);box-shadow:var(--shadow-2)}
.w-btn:active{transform:scale(.98)}
.w-btn[disabled]{opacity:.7;cursor:progress;transform:none}
.w-btn[hidden],.w-remember[hidden],.w-note[hidden]{display:none}
.w-link{font:500 16px var(--sans);color:var(--ink2)!important;text-decoration:underline;text-underline-offset:4px;
text-decoration-color:var(--hair2)!important}
.w-link:hover{color:var(--ink)!important}
:focus-visible{outline:3px solid rgba(0,185,117,.45);outline-offset:2px}
.w-field input:focus-visible{outline:0}
.w-note{position:absolute;top:-10px;left:calc(100% + var(--pad-r) + 24px);width:264px;margin:0;padding:14px 16px 15px;
background:var(--paper);border-radius:16px;box-shadow:0 0 0 1px var(--hair),var(--shadow-1);
font:400 15px/1.5 var(--sans);color:var(--ink);animation:w-note 220ms var(--ease) both}
@keyframes w-note{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}
.w-note b{display:flex;align-items:center;gap:8px;margin-bottom:4px;font:400 12px/1.6 var(--mono);color:var(--num);letter-spacing:.04em}
.w-note b::before{content:"";width:7px;height:7px;border-radius:50%;background:var(--red)}
.w-foot{position:relative;z-index:1;max-width:760px;margin:22px auto 0;font:400 15px/1.55 var(--sans);color:var(--ink3);padding:0 4px}
.w-sr{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}
@media (max-width:1400px){.w-note{position:relative;top:auto;left:auto;width:auto;margin:12px 0 0;padding:0;background:none;
box-shadow:none;animation:none}.w-note b{display:inline-flex;margin:0 8px 0 0}}
@media (max-width:640px){.w-top{margin:8px 8px 0;top:8px;height:56px;border-radius:18px}.w-top-note{display:none}
.w-desk{padding:108px 0 56px}
.w-sheet{border-radius:var(--r-lg) var(--r-lg) 0 0;--pad-l:46px;--pad-r:18px;padding-bottom:32px}.ln::before{left:-38px;width:26px}
.w-head{margin-bottom:26px}.w-h{font-size:24px}.w-foot{padding:0 18px}
.w-actions{gap:16px}.w-actions .w-btn{flex:1 1 100%;justify-content:center}}
@media (prefers-reduced-motion: reduce){.w-sheet,.w-note{animation:none}.w-field.is-checking::after{animation:none;left:0;width:100%}
.w-btn{transition:none}}
"""

PAGE_JS = r"""
(function(){
  var $=function(s){return document.querySelector(s)};
  var sheet=$('#w-sheet'), form=$('#w-form'), key=$('#w-key'), field=$('#w-field'), check=$('#w-check'), open=$('#w-open'),
      remember=$('#w-remember'), rem=$('#w-rem'), note=$('#w-note'), noteText=$('#w-note-text'), verdict=$('#w-verdict'),
      status=$('#w-status');
  var small = window.matchMedia && matchMedia('(max-width:640px)').matches;
  var P = window.BCCAgent ? BCCAgent.fly(sheet, {size: small ? 96 : 192, bottomInset: 0, mood: 'idle'}) : null;
  var verified=false, busy=false;
  function line(wide, narrow){ return sheet.clientWidth < 600 ? narrow : wide; }   // реплика — всегда одна строка
  function after(fn){
    if (!P || P.state === 'landed') { fn(); return; }
    sheet.addEventListener('bcc-agent:landed', function h(){ sheet.removeEventListener('bcc-agent:landed', h); fn(); });
  }
  if (P) { after(function(){ P.say(line(sheet.getAttribute('data-hello'), sheet.getAttribute('data-hello-short'))); }); P.land(); }
  function show(state, html){ verdict.className = state ? 'is-' + state : ''; verdict.innerHTML = html; }
  function esc(s){ return String(s).replace(/[&<>"]/g, function(c){ return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]; }); }
  function bad(msg){ field.classList.toggle('is-bad', !!msg); noteText.textContent = msg || ''; note.hidden = !msg; }
  function reset(){ verified=false; check.hidden=false; open.hidden=true; rem.hidden=true; bad(''); show('', 'не проверен'); }
  key.addEventListener('input', function(){ if (verified || !note.hidden) { reset(); if (P) P.mood('idle'); } });
  $('#w-show').addEventListener('click', function(){
    var s=key.type==='password'; key.type=s?'text':'password'; this.textContent=s?'скрыть':'показать';
    this.setAttribute('aria-pressed', s?'true':'false'); key.focus();
  });
  function post(rememberIt){
    return fetch('/api/key',{method:'POST',headers:{'Content-Type':'application/json','Accept':'application/json'},
      body:JSON.stringify({provider:'auto',key:key.value,remember:!!rememberIt})}).then(function(r){return r.json();});
  }
  function wait(ms){ return new Promise(function(r){ setTimeout(r, ms); }); }
  function go(){
    if (!remember.checked) { location.href='/'; return; }
    open.disabled=true;
    post(true).then(function(r){ if (r.remembered) { location.href='/'; return; } open.disabled=false; bad(r.message||'Файл .env не записан.'); })
      .catch(function(){ open.disabled=false; bad('Сервер не ответил. Окно терминала с BCC Review открыто?'); });
  }
  open.addEventListener('click', go);
  form.addEventListener('submit', function(ev){
    ev.preventDefault();
    if (busy) return;
    if (verified) { go(); return; }
    if (!key.value.trim()) { bad('Вставьте ключ: у Gemini он начинается с AIza, у Claude — с sk-ant-.'); if (P) P.mood('oops'); key.focus(); return; }
    busy=true; check.disabled=true; check.textContent='Проверяю…'; bad(''); status.textContent='Проверяю ключ, это до 10 секунд.';
    field.classList.add('is-checking'); show('', 'проверяю…');
    if (P) { P.say(''); P.mood('work'); P.stage('проверяю ключ'); }
    var t0=Date.now();
    post(false).then(function(r){ return wait(Math.max(0, 1500-(Date.now()-t0))).then(function(){ return r; }); })
    .then(function(r){
      field.classList.remove('is-checking'); if (P) P.stage('');
      if (r.ok) {
        verified=true;
        show('ok', '<b>работает</b> <span class="w-sep">·</span> ' + (r.provider==='anthropic'?'Claude':'Gemini') + ' <span class="w-sep">·</span> ' + esc(r.mask||''));
        check.hidden=true; open.hidden=false; rem.hidden=false; status.textContent=(r.message||'Ключ работает')+' · '+r.mask;
        if (P) { P.mood('happy'); P.say(line('Ключ работает. Можно открывать систему.', 'Ключ работает.')); }
        open.focus();
      } else {
        bad(r.message||'Ключ не подошёл.'); status.textContent=r.message||''; show('bad', '<b>не подошёл</b>');
        if (P) { P.mood('oops'); P.say(line('Не подошёл. Что сделать — написал рядом с ключом.', 'Подсказка — под ключом.')); }
        key.focus();
      }
    }).catch(function(){
      field.classList.remove('is-checking'); show('bad', '<b>нет ответа</b>');
      if (P) { P.stage(''); P.mood('oops'); P.say('Сервер не ответил.'); }
      bad('Сервер не ответил. Окно терминала с BCC Review открыто?');
    }).then(function(){ busy=false; check.disabled=false; check.textContent='Проверить ключ'; });
  });
})();
"""


def welcome_page() -> str:
    tokens = '<link rel="stylesheet" href="/assets/tokens.css">\n' if (ASSETS / "tokens.css").is_file() else ""
    return f"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>BCC AI · ключ модели</title>
<meta name="theme-color" content="#F3F6F5">
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Cpath d='M16 3 29 27H3z' fill='%23FFFFFF' stroke='%23161E31' stroke-width='2' stroke-linejoin='round'/%3E%3Cpath d='M16 10 24 24H8z' fill='%23E6BD74'/%3E%3Cpath d='M16 14 21 22H11z' fill='%231F2E4A'/%3E%3Ccircle cx='16' cy='19' r='1.6' fill='%235ED6FF'/%3E%3C/svg%3E">
{tokens}<link rel="stylesheet" href="/assets/agent.css">
<style>{PAGE_CSS}</style>
</head><body>
<div class="w-bg" aria-hidden="true"></div>
<header class="w-top"><a class="w-brand" href="/welcome" aria-label="BCC Review"><span data-bcc-agent data-size="48" data-mood="idle"></span>BCC Review</a>
<span class="w-top-note">Знакомство с BCC AI</span></header>
<main class="w-desk">
<article id="w-sheet" class="w-sheet" data-hello="{_e(HELLO_LINE)}" data-hello-short="{_e(HELLO_SHORT)}" aria-labelledby="w-title">
<div class="w-head">Ключ: <span id="w-verdict">не проверен</span></div>
<h1 id="w-title" class="ln w-h">Ключ модели для BCC AI</h1>
<p class="ln w-p">Здравствуйте! Я BCC AI — проверяю ТЗ до начала разработки.</p>
<p class="ln w-p">Чтобы думать, мне нужен ключ: Gemini — бесплатно, или Claude.</p>
<form id="w-form" class="w-form" autocomplete="off" novalidate>
<div class="ln w-field" id="w-field"><label for="w-key">Ключ</label>
<input id="w-key" name="key" type="password" placeholder="AIza… или sk-ant-…" spellcheck="false" autocapitalize="off"
autocomplete="off" aria-describedby="w-note-text">
<button type="button" id="w-show" class="w-show" aria-pressed="false" aria-controls="w-key">показать</button></div>
<p class="w-note" id="w-note" hidden><b>K-01</b><span id="w-note-text"></span></p>
<p class="ln w-hint">Бесплатный ключ Gemini — за минуту: <a href="{GEMINI_KEY_URL}" target="_blank"
rel="noopener noreferrer">aistudio.google.com/apikey</a>. Ключ Claude — в <a href="{CLAUDE_KEY_URL}" target="_blank"
rel="noopener noreferrer">консоли Anthropic</a>.</p>
<label class="ln w-remember" id="w-rem" hidden><input id="w-remember" type="checkbox" checked>
Запомнить на этом компьютере (файл .env)</label>
<div class="w-actions"><button id="w-check" class="w-btn" type="submit">Проверить ключ</button>
<button id="w-open" class="w-btn" type="button" hidden>Открыть систему</button>
<a id="w-skip" class="w-link" href="/welcome/skip">Продолжить без ключа</a></div>
<p id="w-status" class="w-sr" role="status"></p>
</form>
</article>
<p class="w-foot">{_e(NO_KEY_LINE)}. Ключ остаётся на этом компьютере и уходит только в Google или Anthropic.</p>
</main>
<script src="/assets/agent.js"></script>
<script>{PAGE_JS}</script>
</body></html>"""
