"""Поддельный сервер Gemini API (№24): настоящий HTTP на 127.0.0.1, без ключа и без интернета.

Агент ходит к нему через настоящий SDK ``google-genai`` — достаточно переменной окружения
``GOOGLE_GEMINI_BASE_URL=http://127.0.0.1:<порт>`` (её читает сам SDK) и любого ``GEMINI_API_KEY``.
Так проверяется весь путь жюри: CLI → конвейер → ``LLMClient`` → провайдер ``gemini`` → адаптер v1 → SDK → сокет.

Ответы — записанные ответы этапов (как у ``--provider mock``): этап узнаётся по первой строке файла промпта
этапа в тексте запроса. Отказы задаёт сценарий ``faults``: список правил, каждое срабатывает на первых
``times`` подходящих запросах (по этапу и/или модели):

* ``429`` — RESOURCE_EXHAUSTED, заголовок ``Retry-After`` и RetryInfo; ``429_day`` — дневная квота;
* ``503`` / ``500`` / ``504`` / ``404`` / ``401`` (неверный ключ) / ``400_schema`` («схема слишком сложная»);
* ``drop`` — сервер закрывает соединение, не ответив; ``slow`` — ответ через ``delay`` с (тайм-аут клиента);
* ``truncated_json`` — finishReason STOP, но JSON оборван; ``empty`` — кандидат без текста;
* ``no_candidates`` — пустой список кандидатов; ``max_tokens`` — finishReason MAX_TOKENS;
* ``403_proxy`` — 403 от прокси сети (HTML, не JSON Google); ``407`` — прокси требует пароль;
* ``safety`` — promptFeedback.blockReason=SAFETY; ``finish_safety`` — finishReason SAFETY.

Задержка ответа ``latency`` (с, на каждый успешный ответ, можно по этапам) — для замера времени прогона.
Запуск вручную: ``python tests/v2/fixtures/24_gemini/fake_gemini.py --port 8765 --latency 20``.
"""
from __future__ import annotations

import json
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[4]
PROMPTS = ROOT / "src" / "bcc_review" / "v2" / "prompts"
FIXTURES = ROOT / "tests" / "v2" / "fixtures" / "official"
# Файл промпта → (этап, номер вызова) mock-фикстуры: вторая проверка судьи — второй вызов этапа judge.
# Номер вызова задаётся промптом, а не счётчиком запросов: повтор после отказа получает тот же ответ.
PROMPT_STAGE = {"judge_check": ("judge", 2)}
_HINT = "строго по этой JSON Schema, без пояснений и без markdown:"
_PATH = re.compile(r"/models/([^/:]+):(generateContent|streamGenerateContent)")


def _markers() -> list[tuple[str, str]]:
    """Для каждого файла промпта — первая строка задания, которой нет в других промптах (≥ 30 знаков)."""
    texts = {p.stem: p.read_text(encoding="utf-8") for p in sorted(PROMPTS.glob("*.md")) if not p.stem.startswith("_")}
    out = []
    for stem, text in texts.items():
        for ln in (x.strip() for x in text.splitlines()):
            if len(ln) < 30 or "{{" in ln or ln.startswith("<") or ln in ("## system", "## user"):
                continue
            if not any(ln in other for s, other in texts.items() if s != stem):
                out.append((ln, stem))
                break
    return out


PROXY_PAGE = "<html><body><h1>Access denied</h1>Blocked by network policy</body></html>"


def _error(code: int, status: str, message: str, details: list | None = None) -> dict:
    return {"error": {"code": code, "status": status, "message": message, "details": details or []}}


class _QuietServer(ThreadingHTTPServer):
    def handle_error(self, request: Any, client_address: Any) -> None:
        """Клиент ушёл по своему тайм-ауту раньше ответа (сценарий ``slow``) — это ожидаемо, не шум в консоли."""
        import sys
        if not isinstance(sys.exc_info()[1], (BrokenPipeError, ConnectionResetError)):
            super().handle_error(request, client_address)


class FakeGemini:
    """Сервер в фоне. ``with FakeGemini(faults=[...]) as fake: env["GOOGLE_GEMINI_BASE_URL"] = fake.url``."""

    def __init__(self, faults: list[dict] | None = None, *, latency: float | dict = 0.0,
                 fixtures_dir: str | Path | None = None, port: int = 0) -> None:
        from bcc_review.v2.providers.mock import MockProvider
        self.mock = MockProvider(fixtures_dir=fixtures_dir or FIXTURES)
        self.faults = [dict(f, used=0) for f in (faults or [])]
        self.latency = latency
        self.markers = _markers()
        self.log: list[dict] = []          # каждый запрос: время, модель, этап, что ответили
        self.lock = threading.Lock()
        self.active = 0
        self.max_active = 0
        handler = self._handler()
        self.server = _QuietServer(("127.0.0.1", port), handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    # ------------------------------------------------------------------ жизненный цикл
    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_address[1]}"

    def __enter__(self) -> "FakeGemini":
        self.thread.start()
        return self

    def __exit__(self, *exc: Any) -> None:
        self.server.shutdown()
        self.server.server_close()

    # ------------------------------------------------------------------ логика
    def stage_of(self, text: str) -> str:
        for marker, stage in self.markers:
            if marker in text:
                return stage
        return "unknown"

    def data_for(self, prompt: str, schema: dict) -> Any:
        """Ответ этапа из фикстуры, приведённый к схеме запроса; нет фикстуры — валидный пустой ответ."""
        from bcc_review.v2.providers.mock import _valid
        from bcc_review.v2.types import conform, empty_for
        stage, k = PROMPT_STAGE.get(prompt, (prompt, 1))
        raw = self.mock._lookup(stage, k)
        data = conform(raw, dict(schema)) if raw is not None and schema else raw
        if data is None or (schema and not _valid(data, schema)):
            data = empty_for(dict(schema)) if schema else {}
        return data

    def _fault(self, stage: str, model: str, kinds: tuple = ()) -> dict | None:
        with self.lock:
            for f in self.faults:
                if f.get("stage") not in (None, stage) or f.get("model") not in (None, model):
                    continue
                if kinds and f.get("kind") not in kinds:
                    continue
                if f["used"] < int(f.get("times", 1)):
                    f["used"] += 1
                    return f
        return None

    def _delay(self, stage: str) -> float:
        lat = self.latency
        return float(lat.get(stage, lat.get("*", 0.0)) if isinstance(lat, dict) else lat or 0.0)

    def answer(self, model: str, body: dict) -> tuple[int, dict, dict | None, str]:
        """(HTTP-код, заголовки, JSON или None — оборвать соединение, что сделано)."""
        parts = []
        for c in [body.get("systemInstruction") or {}, *(body.get("contents") or [])]:
            parts += [p.get("text") or "" for p in (c.get("parts") or [])]
        text = "\n".join(parts)
        stage = self.stage_of(text)
        cfg = body.get("generationConfig") or {}
        schema = cfg.get("responseJsonSchema") or cfg.get("response_json_schema") or {}
        if not schema and _HINT in text:   # режим «схема текстом»: провайдер дописал её в конец запроса
            try:
                schema = json.loads(text.split(_HINT, 1)[1].strip())
            except ValueError:
                schema = {}
        fault = self._fault(stage, model)
        kind = (fault or {}).get("kind", "ok")
        rec = {"t": time.monotonic(), "model": model, "stage": stage, "kind": kind,
               "schema_mode": "native" if cfg.get("responseJsonSchema") else "text"}
        with self.lock:
            self.log.append(rec)
        if kind == "drop":
            return 0, {}, None, kind
        if kind == "slow":
            time.sleep(float(fault.get("delay", 30)))
        if kind == "429":
            ra = int(fault.get("retry_after", 2))
            return 429, {"Retry-After": str(ra)}, _error(429, "RESOURCE_EXHAUSTED", (
                f"You exceeded your current quota. Please retry in {ra}s."), [
                {"@type": "type.googleapis.com/google.rpc.QuotaFailure", "violations": [{
                    "quotaMetric": "generativelanguage.googleapis.com/generate_content_free_tier_requests",
                    "quotaId": "GenerateRequestsPerMinutePerProjectPerModel-FreeTier", "quotaValue": "10"}]},
                {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": f"{ra}s"}]), kind
        if kind == "429_day":
            return 429, {}, _error(429, "RESOURCE_EXHAUSTED", "You exceeded your current quota. limit: 20", [
                {"@type": "type.googleapis.com/google.rpc.QuotaFailure", "violations": [{
                    "quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier", "quotaValue": "20"}]}]), kind
        simple = {"503": (503, "UNAVAILABLE", "The model is overloaded. Please try again later."),
                  "500": (500, "INTERNAL", "An internal error has occurred."),
                  "504": (504, "DEADLINE_EXCEEDED", "Deadline expired before operation could complete."),
                  "404": (404, "NOT_FOUND", f"models/{model} is not found for API version v1beta."),
                  "400_schema": (400, "INVALID_ARGUMENT", "The specified schema produces a constraint that has "
                                                          "too many states for serving."),
                  "403": (403, "PERMISSION_DENIED", "Method doesn't allow unregistered callers.")}
        if kind in simple:
            code, status, msg = simple[kind]
            return code, {}, _error(code, status, msg), kind
        if kind in ("403_proxy", "407"):
            return int(kind[:3]), {}, PROXY_PAGE, kind
        if kind == "401":
            return 400, {}, _error(400, "INVALID_ARGUMENT", "API key not valid. Please pass a valid API key.", [
                {"@type": "type.googleapis.com/google.rpc.ErrorInfo", "reason": "API_KEY_INVALID"}]), kind

        # успешный ответ: данные этапа из фикстуры, приведённые к присланной схеме
        delay = self._delay(stage)
        if delay:
            time.sleep(delay)
        payload = json.dumps(self.data_for(stage, schema), ensure_ascii=False)
        finish = "STOP"
        if kind == "truncated_json":
            payload = payload[: max(1, len(payload) // 2)]
        elif kind == "empty":
            payload = ""
        elif kind == "max_tokens":
            payload, finish = payload[: len(payload) // 2], "MAX_TOKENS"
        elif kind == "finish_safety":
            payload, finish = "", "SAFETY"
        usage = {"promptTokenCount": len(text) // 3, "candidatesTokenCount": len(payload) // 3,
                 "thoughtsTokenCount": 100, "totalTokenCount": len(text) // 3 + len(payload) // 3 + 100}
        if kind == "safety":
            return 200, {}, {"promptFeedback": {"blockReason": "SAFETY"}, "usageMetadata": usage}, kind
        cand = {"content": {"role": "model", "parts": [{"text": payload}] if payload else []},
                "finishReason": finish, "index": 0}
        out = {"candidates": [] if kind == "no_candidates" else [cand], "usageMetadata": usage,
               "modelVersion": model, "responseId": f"fake-{len(self.log)}"}
        return 200, {}, out, kind

    def models_list(self) -> dict:
        names = ["gemini-3.8-flash", "gemini-3.7-flash", "gemini-3.6-flash", "gemini-3.5-flash",
                 "gemini-3.5-flash-lite", "gemini-3.1-flash-lite"]
        return {"models": [{"name": f"models/{n}", "displayName": n, "supportedGenerationMethods":
                            ["generateContent", "countTokens"], "inputTokenLimit": 1048576,
                            "outputTokenLimit": 65536} for n in names]}

    def _handler(self) -> type:
        fake = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a: Any) -> None:  # тишина в консоли тестов
                pass

            def _send(self, code: int, headers: dict, data: dict | str) -> None:
                html = isinstance(data, str)
                raw = (data if html else json.dumps(data, ensure_ascii=False)).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "text/html" if html else "application/json; charset=UTF-8")
                self.send_header("Content-Length", str(len(raw)))
                for k, v in headers.items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self) -> None:
                if "/models" in self.path:
                    # models.list (doctor): ключ, обрыв и задержка действуют и здесь; правило с stage=None — тоже
                    f = fake._fault("models_list", "", kinds=("401", "403", "403_proxy", "407", "drop", "slow"))
                    kind = (f or {}).get("kind")
                    with fake.lock:
                        fake.log.append({"t": time.monotonic(), "model": "", "stage": "models_list",
                                         "kind": kind or "ok", "schema_mode": ""})
                    if kind == "drop":
                        self.close_connection = True
                        self.connection.shutdown(2)
                        return
                    if kind == "slow":
                        time.sleep(float(f.get("delay", 30)))
                    if kind == "401":
                        self._send(400, {}, _error(400, "INVALID_ARGUMENT", "API key not valid.", [
                            {"@type": "type.googleapis.com/google.rpc.ErrorInfo", "reason": "API_KEY_INVALID"}]))
                        return
                    if kind in ("403_proxy", "407"):
                        self._send(int(kind[:3]), {}, PROXY_PAGE)
                        return
                    if kind == "403":
                        self._send(403, {}, _error(403, "PERMISSION_DENIED", "Permission denied."))
                        return
                    self._send(200, {}, fake.models_list())
                else:
                    self._send(404, {}, _error(404, "NOT_FOUND", "not found"))

            def do_POST(self) -> None:
                n = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(n) or b"{}")
                m = _PATH.search(self.path)
                model = m.group(1) if m else "?"
                with fake.lock:
                    fake.active += 1
                    fake.max_active = max(fake.max_active, fake.active)
                try:
                    code, headers, data, _ = fake.answer(model, body)
                finally:
                    with fake.lock:
                        fake.active -= 1
                if data is None:   # обрыв: закрыть сокет без ответа
                    self.close_connection = True
                    try:
                        self.connection.shutdown(2)
                    except OSError:
                        pass
                    return
                self._send(code, headers, data)

        return Handler


def main() -> None:  # pragma: no cover - ручной запуск
    import argparse
    import sys
    sys.path.insert(0, str(ROOT / "src"))
    p = argparse.ArgumentParser(description="Поддельный сервер Gemini для проверки агента без ключа")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--latency", type=float, default=0.0, help="задержка каждого ответа, с")
    p.add_argument("--faults", default="", help="JSON-список правил отказов")
    a = p.parse_args()
    fake = FakeGemini(json.loads(a.faults) if a.faults else None, latency=a.latency, port=a.port)
    print(f"GOOGLE_GEMINI_BASE_URL={fake.url}  GEMINI_API_KEY=fake  (Ctrl+C — стоп)")
    with fake:
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":  # pragma: no cover
    main()
