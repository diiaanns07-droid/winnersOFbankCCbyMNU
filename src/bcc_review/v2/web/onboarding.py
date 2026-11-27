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
:root{--desk:#0B1220;--paper:#FFFFFF;--ink:#1A2433;--ink2:#4A5A6E;--num:#98A6B6;--green:#00B975;--gs:#008556;--gi:#00704A;
--red:#C2362B;--pad-r:64px;--ease:cubic-bezier(.2,.8,.2,1);
--serif:"PT Serif",Georgia,"Times New Roman",serif;
--mono:"JetBrains Mono",ui-monospace,SFMono-Regular,Consolas,"Liberation Mono",monospace;
--sans:Inter,-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Arial,sans-serif}
*{box-sizing:border-box}
html,body{margin:0;min-height:100%;background:var(--desk)}
body{color:#E6EDF5;font:400 16px/1.5 var(--sans);-webkit-font-smoothing:antialiased;overflow-x:hidden}
.w-top{height:48px;display:flex;align-items:center;padding:0 20px;border-bottom:1px solid rgba(255,255,255,.06)}
.w-top a{display:inline-flex;align-items:center;gap:10px;color:#E6EDF5;text-decoration:none;font:600 15px var(--sans);letter-spacing:-.01em}
.w-desk{padding:150px 16px 96px}
.w-sheet{position:relative;max-width:760px;margin:0 auto;background:var(--paper);color:var(--ink);border-radius:2px;
padding:56px var(--pad-r) 52px 92px;box-shadow:0 1px 2px rgba(0,0,0,.45),0 28px 70px rgba(0,0,0,.5);counter-reset:ln;
animation:w-in 360ms var(--ease) both}
@keyframes w-in{from{opacity:0;transform:translateY(12px)}to{opacity:1;transform:none}}
.ln{position:relative;margin:0}
.ln::before{counter-increment:ln;content:counter(ln);position:absolute;left:-62px;width:34px;text-align:right;top:.42em;
font:400 12px/1 var(--mono);color:var(--num)}
.w-h{font:700 25px/1.3 var(--serif);margin:0 0 16px;letter-spacing:-.01em;padding-right:220px}
.w-h::before{top:.62em}
.w-p{font:400 16.5px/1.6 var(--serif)}
.w-form{position:relative;margin-top:26px}
.w-field{display:flex;align-items:baseline;gap:14px;padding:5px 2px 5px 0;border-bottom:1.5px solid #CBD5E0;
transition:border-color 120ms var(--ease),background-color 220ms var(--ease)}
.w-field::before{top:.9em}
.w-field:focus-within{border-bottom-color:var(--green)}
.w-field label{font:400 16.5px/1.6 var(--serif);color:var(--ink2);flex:0 0 auto}
.w-field input{flex:1;min-width:0;border:0;outline:0;background:transparent;font:500 15px/1.75 var(--mono);color:var(--ink);
letter-spacing:.02em;padding:0}
.w-field input::placeholder{color:#A3AFBD}
.w-show{border:0;background:none;font:500 14px var(--sans);color:var(--ink2);cursor:pointer;padding:2px;
text-decoration:underline;text-underline-offset:3px;text-decoration-color:#CBD5E0}
.w-show:hover{color:var(--ink)}
.w-field.is-bad{border-bottom-color:transparent;background:rgba(194,54,43,.07) url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='8' height='4' viewBox='0 0 8 4'%3E%3Cpath d='M0 3 Q2 0 4 2 T8 2' fill='none' stroke='%23C2362B' stroke-width='1.3'/%3E%3C/svg%3E") repeat-x left bottom}
.w-hint{font:400 15.5px/1.6 var(--serif);color:var(--ink2);margin-top:10px}
.w-hint::before{top:.5em}
.w-sheet a{color:var(--gi);text-decoration-thickness:1px;text-underline-offset:3px}
.w-remember{display:flex;align-items:center;gap:10px;margin-top:14px;font:400 16.5px/1.6 var(--serif);color:var(--ink);cursor:pointer}
.w-remember::before{top:.55em}
.w-remember input{width:18px;height:18px;margin:0;accent-color:var(--gs)}
.w-actions{display:flex;flex-wrap:wrap;align-items:center;gap:20px;margin-top:28px}
.w-btn{height:44px;padding:0 22px;border:0;border-radius:8px;background:var(--gs);color:#fff;font:600 15px var(--sans);
cursor:pointer;display:inline-flex;align-items:center;transition:transform 120ms var(--ease),background-color 120ms var(--ease)}
.w-btn:hover{background:#007A4F}
.w-btn:active{transform:scale(.98)}
.w-btn[disabled]{opacity:.65;cursor:progress}
.w-btn[hidden],.w-remember[hidden],.w-note[hidden]{display:none}
.w-link{font:500 15px var(--sans);color:var(--ink2)!important;text-decoration:underline;text-underline-offset:4px;
text-decoration-color:#CBD5E0}
.w-link:hover{color:var(--ink)!important}
:focus-visible{outline:3px solid rgba(0,185,117,.55);outline-offset:2px}
.w-field input:focus-visible{outline:0}
.w-stamp{position:absolute;right:30px;top:24px;width:216px;color:#0B8A57;transform:rotate(-4deg);opacity:0;pointer-events:none}
.w-stamp.is-on{animation:w-stamp 220ms cubic-bezier(.2,.8,.3,1.3) both}
@keyframes w-stamp{from{opacity:0;transform:rotate(-4deg) scale(1.15)}to{opacity:.94;transform:rotate(-4deg) scale(1)}}
.w-note{position:absolute;top:auto;left:calc(100% + var(--pad-r) + 28px);width:244px;margin:-2.1em 0 0;
font:400 14px/1.45 var(--sans);color:#E6EDF5;animation:w-note 220ms var(--ease) both}
@keyframes w-note{from{opacity:0;transform:translateX(-6px)}to{opacity:1;transform:none}}
.w-note::before{content:"";position:absolute;right:calc(100% + 4px);top:.72em;width:24px;height:1px;background:rgba(240,97,106,.75)}
.w-note b{display:block;font:600 12px/1.7 var(--mono);color:#F0616A;letter-spacing:.06em}
.w-foot{max-width:760px;margin:22px auto 0;font:400 14px/1.5 var(--sans);color:#8FA3BA;padding:0 2px}
.w-sr{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}
@media (max-width:1360px){.w-note{position:static;width:auto;margin:10px 0 0;color:var(--red);animation:none}
.w-note::before{display:none}.w-note b{display:inline;margin-right:8px;color:var(--red)}}
@media (max-width:640px){.w-top{padding:0 16px}.w-desk{padding:92px 0 56px}
.w-sheet{padding:36px 18px 32px 46px;border-radius:0;--pad-r:18px}.ln::before{left:-38px;width:26px}
.w-h{font-size:21px;padding-right:0;margin-top:58px}.w-stamp{right:14px;top:16px;width:176px}.w-foot{padding:0 16px}
.w-actions{gap:16px}.w-actions .w-btn{flex:1 1 100%;justify-content:center}}
@media (prefers-reduced-motion: reduce){.w-sheet,.w-note{animation:none}.w-stamp.is-on{animation:none;opacity:.94}}
"""

PAGE_JS = r"""
(function(){
  var $=function(s){return document.querySelector(s)};
  var sheet=$('#w-sheet'), form=$('#w-form'), key=$('#w-key'), field=$('#w-field'), check=$('#w-check'), open=$('#w-open'),
      remember=$('#w-remember'), rem=$('#w-rem'), note=$('#w-note'), noteText=$('#w-note-text'), stamp=$('#w-stamp'),
      stampSub=$('#w-stamp-sub'), status=$('#w-status');
  var small = window.matchMedia && matchMedia('(max-width:640px)').matches;
  var P = window.BCCAgent ? BCCAgent.fly(sheet, {size: small ? 80 : 160, bottomInset: 0}) : null;
  var verified=false, busy=false;
  function after(fn){
    if (!P || P.state === 'landed') { fn(); return; }
    sheet.addEventListener('bcc-agent:landed', function h(){ sheet.removeEventListener('bcc-agent:landed', h); fn(); });
  }
  if (P) { after(function(){ P.say(sheet.getAttribute('data-hello')); }); P.land(); }
  function bad(msg){ field.classList.toggle('is-bad', !!msg); noteText.textContent = msg || ''; note.hidden = !msg; }
  function reset(){ verified=false; check.hidden=false; open.hidden=true; rem.hidden=true; stamp.classList.remove('is-on'); bad(''); }
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
    if (!key.value.trim()) { bad('Вставьте ключ: у Gemini он начинается с AIza, у Claude — с sk-ant-.'); if (P) P.mood('alert'); key.focus(); return; }
    busy=true; check.disabled=true; check.textContent='Проверяю…'; bad(''); status.textContent='Проверяю ключ, это до 10 секунд.';
    if (P) { P.say(''); P.takeoff(); P.mood('analyzing'); P.progress(field, 'проверяю ключ'); }
    var t0=Date.now();
    post(false).then(function(r){ return wait(Math.max(0, 1500-(Date.now()-t0))).then(function(){ return r; }); })
    .then(function(r){
      if (P) P.land();
      after(function(){
        if (r.ok) {
          verified=true; stampSub.textContent=(r.provider==='anthropic'?'CLAUDE':'GEMINI')+' · '+r.mask; stamp.classList.add('is-on');
          check.hidden=true; open.hidden=false; rem.hidden=false; status.textContent=(r.message||'Ключ работает')+' · '+r.mask;
          if (P) { P.mood('verified'); P.say('Ключ работает. Можно открывать систему.'); }
          open.focus();
        } else {
          bad(r.message||'Ключ не подошёл.'); status.textContent=r.message||'';
          if (P) { P.mood('alert'); P.say('Не подошёл. Что сделать — написал рядом с ключом.'); }
          key.focus();
        }
      });
    }).catch(function(){
      if (P) { P.land(); after(function(){ P.mood('alert'); P.say('Сервер не ответил.'); }); }
      bad('Сервер не ответил. Окно терминала с BCC Review открыто?');
    }).then(function(){ busy=false; check.disabled=false; check.textContent='Проверить ключ'; });
  });
})();
"""

STAMP_SVG = """<svg id="w-stamp" class="w-stamp" viewBox="0 0 240 92" aria-hidden="true">
<defs><filter id="w-ink" x="-5%" y="-5%" width="110%" height="110%">
<feTurbulence type="fractalNoise" baseFrequency=".85" numOctaves="2" seed="11" result="n"/>
<feColorMatrix in="n" type="matrix" values="0 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 0 0 -1.5 1.45" result="a"/>
<feComposite in="SourceGraphic" in2="a" operator="in"/></filter></defs>
<g filter="url(#w-ink)"><rect x="3" y="3" width="234" height="86" rx="7" fill="none" stroke="currentColor" stroke-width="4"/>
<rect x="11" y="11" width="218" height="70" rx="4" fill="none" stroke="currentColor" stroke-width="1.6"/>
<text x="120" y="48" text-anchor="middle" fill="currentColor" font-family="PT Serif,Georgia,serif" font-weight="700"
font-size="25" letter-spacing="2.5">КЛЮЧ ПРИНЯТ</text>
<text id="w-stamp-sub" x="120" y="69" text-anchor="middle" fill="currentColor"
font-family="JetBrains Mono,ui-monospace,Consolas,monospace" font-size="11.5" letter-spacing="1.2">GEMINI</text></g></svg>"""


def welcome_page() -> str:
    tokens = '<link rel="stylesheet" href="/assets/tokens.css">\n' if (ASSETS / "tokens.css").is_file() else ""
    return f"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>BCC AI · ключ модели</title>
<meta name="theme-color" content="#0B1220">
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Crect width='32' height='32' rx='7' fill='%230B1220'/%3E%3Crect x='7' y='11' width='18' height='10' rx='4' fill='%23CAA166'/%3E%3Crect x='9' y='13' width='14' height='6' rx='2' fill='%230E1525'/%3E%3Crect x='11' y='15' width='3' height='2' fill='%2334D36A'/%3E%3Crect x='18' y='15' width='3' height='2' fill='%2334D36A'/%3E%3C/svg%3E">
{tokens}<link rel="stylesheet" href="/assets/agent.css">
<style>{PAGE_CSS}</style>
</head><body>
<header class="w-top"><a href="/welcome" aria-label="BCC Review"><span data-bcc-agent data-size="24" data-mood="idle"></span>BCC Review</a></header>
<main class="w-desk">
<article id="w-sheet" class="w-sheet" data-hello="{_e(HELLO_LINE)}" aria-labelledby="w-title">
{STAMP_SVG}
<h1 id="w-title" class="ln w-h">Ключ модели для BCC AI</h1>
<p class="ln w-p">Здравствуйте! Я BCC AI — проверяю ТЗ до начала разработки.</p>
<p class="ln w-p">Чтобы думать, мне нужен ключ модели: Gemini — бесплатно, или Claude.</p>
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
<p class="w-foot">{_e(NO_KEY_LINE)} — если продолжить без ключа. Ключ остаётся на этом компьютере
и уходит только в Google или Anthropic.</p>
</main>
<script src="/assets/agent.js"></script>
<script>{PAGE_JS}</script>
</body></html>"""
