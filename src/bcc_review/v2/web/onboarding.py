"""Знакомство с BCC AI (№40): первый запуск без модели → /welcome, проверка и сохранение ключа.

Маршруты (подключаются одной строкой в начале ``Handler.do_GET`` / ``do_POST``)::

    GET  /                  → 303 /welcome, если ни один провайдер с моделью не готов и «Без ключа» не выбран
    GET  /welcome           экран знакомства (BCC AI 160 px, три капсулы, поле ключа)
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

def _e(v: Any) -> str:
    return escape("" if v is None else str(v), quote=True)


PAGE_CSS = """
:root{--w-ink:var(--b-ink,#0F2841);--w-ink2:var(--b-ink-2,#3A5068);--w-ink3:var(--b-ink-3,#5B6F84);
--w-green:var(--b-green,#00B975);--w-gs:var(--b-green-strong,#008556);--w-gi:var(--b-green-ink,#00704A);
--w-red:var(--b-red,#C2362B);--w-hair:var(--b-hair,rgba(15,40,65,.08));--w-hair2:var(--b-hair-2,rgba(15,40,65,.14));
--w-ease:var(--b-ease,cubic-bezier(.2,.8,.2,1));--w-font:var(--b-font,Inter,-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Arial,sans-serif)}
*{box-sizing:border-box}
html,body{margin:0;min-height:100%}
body{background:var(--b-canvas,#F3F6F5);color:var(--w-ink);font:400 17px/1.5 var(--w-font);-webkit-font-smoothing:antialiased;
overflow-x:hidden}
body::before,body::after{content:"";position:fixed;z-index:-1;border-radius:50%;filter:blur(110px);pointer-events:none}
body::before{width:680px;height:680px;left:-220px;top:-260px;background:rgba(0,185,117,.18)}
body::after{width:620px;height:620px;right:-200px;top:-240px;background:rgba(220,162,98,.26)}
.w{min-height:100vh;display:flex;align-items:center;justify-content:center;padding:40px 16px}
.w-card{width:100%;max-width:600px;background:var(--b-paper,#fff);border-radius:var(--b-r-xl,28px);padding:40px 40px 32px;
box-shadow:0 0 0 1px var(--w-hair),var(--b-shadow-2,0 2px 6px rgba(15,40,65,.05),0 16px 40px rgba(15,40,65,.10));
animation:w-in var(--b-slow,360ms) var(--w-ease) both}
@keyframes w-in{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:none}}
.w-hero{display:flex;margin-bottom:28px}
.w-hero .bcc-agent{align-items:center}
.w-h{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0)}
.w-pills{display:flex;flex-wrap:wrap;gap:8px;margin:0 0 20px;padding:0;border:0}
.w-pill{position:relative}
.w-pill input{position:absolute;opacity:0;pointer-events:none}
.w-pill span{display:inline-flex;align-items:center;height:var(--b-h,46px);padding:0 18px;border-radius:999px;cursor:pointer;
background:var(--b-paper,#fff);color:var(--w-ink);font-weight:600;font-size:16px;
box-shadow:0 0 0 1px var(--w-hair2);transition:box-shadow var(--b-fast,120ms) var(--w-ease),transform var(--b-fast,120ms) var(--w-ease),background var(--b-base,220ms) var(--w-ease)}
.w-pill span:hover{transform:translateY(-1px);box-shadow:0 0 0 1px var(--w-hair2),var(--b-shadow-2,0 2px 6px rgba(15,40,65,.05),0 16px 40px rgba(15,40,65,.10))}
.w-pill span:active{transform:scale(.98)}
.w-pill input:checked+span{background:var(--b-green-wash,#F1FBF5);box-shadow:0 0 0 2px var(--w-green)}
.w-pill input:focus-visible+span{outline:3px solid rgba(0,185,117,.55);outline-offset:2px}
.w-pill small{font-weight:500;color:var(--w-gi);margin-left:6px;font-size:15px}
.w-panel[hidden]{display:none}
.w-label{display:flex;justify-content:space-between;align-items:baseline;gap:12px;margin:0 0 8px;font-size:15px;color:var(--w-ink2)}
.w-label a{color:var(--w-gi);font-weight:600;text-decoration:none}
.w-label a:hover{text-decoration:underline}
.w-field{display:flex;align-items:center;height:var(--b-h,46px);border-radius:var(--b-r-md,14px);background:var(--b-paper,#fff);
box-shadow:0 0 0 1px var(--w-hair2);transition:box-shadow var(--b-fast,120ms) var(--w-ease)}
.w-field:focus-within{box-shadow:0 0 0 2px var(--w-green)}
.w-field input{flex:1;min-width:0;height:100%;border:0;background:transparent;padding:0 14px;font:500 16px var(--w-font);color:var(--w-ink);outline:0;letter-spacing:.02em}
.w-show{border:0;background:transparent;color:var(--w-ink2);font:600 15px var(--w-font);padding:0 14px;height:100%;cursor:pointer;border-radius:0 14px 14px 0}
.w-show:focus-visible,.w-btn:focus-visible,.w-check input:focus-visible{outline:3px solid rgba(0,185,117,.55);outline-offset:2px}
.w-actions{display:flex;flex-wrap:wrap;align-items:center;gap:12px;margin-top:20px}
.w-btn{display:inline-flex;align-items:center;justify-content:center;height:var(--b-h,46px);padding:0 24px;border-radius:999px;border:0;
font:600 16px var(--w-font);cursor:pointer;text-decoration:none;transition:transform var(--b-fast,120ms) var(--w-ease),box-shadow var(--b-fast,120ms) var(--w-ease),opacity var(--b-base,220ms)}
.w-btn:hover{transform:translateY(-1px);box-shadow:var(--b-shadow-2,0 2px 6px rgba(15,40,65,.05),0 16px 40px rgba(15,40,65,.10))}
.w-btn:active{transform:scale(.98)}
.w-btn[hidden]{display:none}
.w-btn[disabled]{opacity:.55;cursor:progress;transform:none;box-shadow:none}
.w-main{background:var(--w-gs);color:#fff}
.w-sec{background:var(--b-paper,#fff);color:var(--w-ink);box-shadow:0 0 0 1px var(--w-hair2)}
.w-msg{margin:14px 0 0;min-height:1.5em;font-size:15px;color:var(--w-ink2)}
.w-msg.ok{color:var(--w-gi);font-weight:600}
.w-msg.err{color:var(--w-red);font-weight:600}
.w-check{display:flex;align-items:center;gap:10px;margin-top:16px;font-size:15px;color:var(--w-ink2);cursor:pointer}
.w-check input{width:20px;height:20px;accent-color:var(--w-gs);margin:0}
.w-done[hidden]{display:none}
.w-foot{margin:24px 0 0;font-size:15px;color:var(--w-ink3)}
@media (max-width:560px){.w{align-items:flex-start;padding:24px 16px}.w-card{padding:28px 20px 24px;border-radius:var(--b-r-lg,22px)}
.w-hero{justify-content:center}.w-pills{justify-content:center}.w-actions .w-btn{flex:1}}
@media (prefers-reduced-motion: reduce){.w-card{animation:none}.w-pill span,.w-btn{transition:none}}
"""

PAGE_JS = r"""
(function(){
  var $=function(s){return document.querySelector(s)};
  var host=$('#w-agent'), A=window.BCCAgent&&BCCAgent.mount(host,{size:160,mood:'idle'});
  var say=function(t,m){ if(!A) return; if(m) A.mood(m); A.say(t); };
  say(host.getAttribute('data-hello'));
  var form=$('#w-form'), key=$('#w-key'), check=$('#w-check'), msg=$('#w-msg'), done=$('#w-done'),
      remember=$('#w-remember'), open=$('#w-open'), keyPanel=$('#w-keypanel'), nokey=$('#w-nokey'),
      get=$('#w-get'), lbl=$('#w-keylbl'), verified=false;
  var LINKS={gemini:[get.getAttribute('data-gemini'),'получить за минуту'],anthropic:[get.getAttribute('data-claude'),'где взять']};
  function prov(){ var r=form.querySelector('input[name=provider]:checked'); return r?r.value:'gemini'; }
  function setMsg(t,c){ msg.textContent=t||''; msg.className='w-msg'+(c?' '+c:''); }
  function reset(){ verified=false; done.hidden=true; check.hidden=false; setMsg(''); }
  form.addEventListener('change',function(ev){
    if(ev.target.name!=='provider') return;
    var p=prov();
    keyPanel.hidden=(p==='none'); nokey.hidden=(p!=='none'); reset();
    if(p==='none'){ say('Без ключа покажу готовые отчёты и проверю документ правилами.','idle'); return; }
    lbl.textContent=p==='gemini'?'Ключ Gemini':'Ключ Claude API';
    key.placeholder=p==='gemini'?'AIza…':'sk-ant-…';
    get.href=LINKS[p][0]; get.textContent=LINKS[p][1];
    say(p==='gemini'?'Ключ Gemini бесплатный: войдите в Google AI Studio и нажмите Create API key.':'Подойдёт ключ Claude API из консоли Anthropic.','idle');
  });
  key.addEventListener('input',function(){ if(verified) reset(); });
  $('#w-show').addEventListener('click',function(){
    var s=key.type==='password'; key.type=s?'text':'password'; this.textContent=s?'скрыть':'показать';
    this.setAttribute('aria-pressed',s?'true':'false'); key.focus();
  });
  function post(rem){
    return fetch('/api/key',{method:'POST',headers:{'Content-Type':'application/json','Accept':'application/json'},
      body:JSON.stringify({provider:prov(),key:key.value,remember:!!rem})}).then(function(r){return r.json()});
  }
  form.addEventListener('submit',function(ev){
    ev.preventDefault();
    if(prov()==='none'){ location.href='/welcome/skip'; return; }
    if(!key.value.trim()){ setMsg('Вставьте ключ в поле.','err'); say('Вставьте ключ в поле — я подожду.','alert'); key.focus(); return; }
    check.disabled=true; check.textContent='Проверяю…'; setMsg('Проверяю ключ, это до 10 секунд.');
    say('Проверяю ключ…','analyzing');
    post(false).then(function(r){
      if(r.ok){ verified=true; setMsg((r.message||'Ключ работает')+' · '+r.mask,'ok'); say('Ключ работает. Можно открывать систему.','verified');
        check.hidden=true; done.hidden=false; open.focus(); }
      else { setMsg(r.message||'Ключ не подошёл.','err'); say('Не получилось. Что сделать — написал под кнопкой.','alert'); }
    }).catch(function(){ setMsg('Сервер не ответил. Он запущен?','err'); say('Сервер не ответил. Он запущен?','alert'); })
    .then(function(){ check.disabled=false; check.textContent='Проверить ключ'; });
  });
  open.addEventListener('click',function(){
    if(!remember.checked){ location.href='/'; return; }
    open.disabled=true;
    post(true).then(function(r){
      if(r.remembered){ location.href='/'; return; }
      open.disabled=false; setMsg(r.message||'Файл .env не записан.','err');
    }).catch(function(){ open.disabled=false; setMsg('Сервер не ответил.','err'); });
  });
})();
"""


def welcome_page() -> str:
    tokens = '<link rel="stylesheet" href="/assets/tokens.css">\n' if (ASSETS / "tokens.css").is_file() else ""
    return f"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>BCC AI · знакомство</title>
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Crect width='32' height='32' rx='9' fill='%230F2841'/%3E%3Crect x='8' y='12' width='16' height='9' rx='4' fill='%23CAA166'/%3E%3Crect x='10' y='14' width='12' height='5' rx='2' fill='%230E1525'/%3E%3Crect x='12' y='15' width='2' height='2' fill='%2334D36A'/%3E%3Crect x='18' y='15' width='2' height='2' fill='%2334D36A'/%3E%3C/svg%3E">
{tokens}<link rel="stylesheet" href="/assets/agent.css">
<style>{PAGE_CSS}</style>
</head><body>
<main class="w"><section class="w-card" aria-labelledby="w-title">
<h1 id="w-title" class="w-h">Знакомство с BCC AI</h1>
<div class="w-hero"><div id="w-agent" data-hello="{_e(HELLO)}"></div></div>
<form id="w-form" autocomplete="off" novalidate>
<fieldset class="w-pills"><legend class="w-h">Чем BCC AI будет думать</legend>
<label class="w-pill"><input type="radio" name="provider" value="gemini" checked><span>Ключ Gemini<small>бесплатно</small></span></label>
<label class="w-pill"><input type="radio" name="provider" value="anthropic"><span>Ключ Claude</span></label>
<label class="w-pill"><input type="radio" name="provider" value="none"><span>Без ключа</span></label>
</fieldset>
<div id="w-keypanel" class="w-panel">
<div class="w-label"><label for="w-key" id="w-keylbl">Ключ Gemini</label>
<a id="w-get" href="{GEMINI_KEY_URL}" target="_blank" rel="noopener noreferrer" data-gemini="{GEMINI_KEY_URL}" data-claude="{CLAUDE_KEY_URL}">получить за минуту</a></div>
<div class="w-field"><input id="w-key" name="key" type="password" placeholder="AIza…" spellcheck="false" autocapitalize="off" autocomplete="off" aria-describedby="w-msg">
<button type="button" id="w-show" class="w-show" aria-pressed="false" aria-controls="w-key">показать</button></div>
<div class="w-actions"><button id="w-check" class="w-btn w-main" type="submit">Проверить ключ</button></div>
<p id="w-msg" class="w-msg" role="status"></p>
<div id="w-done" class="w-done" hidden>
<label class="w-check"><input id="w-remember" type="checkbox" checked> Запомнить на этом компьютере (файл .env)</label>
<div class="w-actions"><button id="w-open" class="w-btn w-main" type="button">Открыть систему</button></div>
</div>
</div>
<div id="w-nokey" class="w-panel" hidden>
<p class="w-msg">{_e(NO_KEY_LINE)}. Ключ можно добавить позже.</p>
<div class="w-actions"><a class="w-btn w-main" href="/welcome/skip">Открыть систему</a></div>
</div>
</form>
<p class="w-foot">Ключ хранится только на этом компьютере и уходит только в {_e("Google или Anthropic")} для проверки.</p>
</section></main>
<script src="/assets/agent.js"></script>
<script>{PAGE_JS}</script>
</body></html>"""
