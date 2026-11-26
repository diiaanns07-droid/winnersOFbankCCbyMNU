"""Наблюдатель для запуска `python -m bcc_review ...` без изменения пакета (подключается через PYTHONPATH).

P12_OBSERVE_LOG=путь   — JSONL: каждое socket.connect (audit hook) и каждый HTTP-запрос SDK.
P12_FAKE_TRANSPORT=1   — подмена самого нижнего транспорта SDK (httpx2/httpx HTTPTransport.handle_request):
                         ответ — фикстура P12_FIXTURE (конверт GenerateContentResponse), а текст ответа —
                         объект, построенный по responseJsonSchema этого же запроса (bcc_review.runtime.mock.synth).
Ключ в журнал не пишется: только признак наличия заголовка и совпадение с GEMINI_API_KEY окружения.
"""

import json
import os
import re
import sys

_LOG = os.environ.get("P12_OBSERVE_LOG")


def _write(rec):
    with open(_LOG, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


if _LOG:
    def _audit(event, args):
        if event == "socket.connect":
            _write({"event": "socket.connect", "address": str(args[1])[:80]})

    sys.addaudithook(_audit)

    if os.environ.get("P12_FAKE_TRANSPORT") == "1":
        def _install(mod):
            def handle_request(self, request):
                request.read()
                match = re.search(r"/models/([^/:]+):generateContent$", request.url.path)
                body = json.loads(request.content or b"{}")
                schema = (body.get("generationConfig") or {}).get("responseJsonSchema") or {}
                key = request.headers.get("x-goog-api-key")
                _write({"event": "http", "lib": mod.__name__, "path": request.url.path,
                        "model": match.group(1) if match else None, "api_key_header": bool(key),
                        "api_key_from_env": key == os.environ.get("GEMINI_API_KEY")})
                from bcc_review.runtime.mock import synth
                with open(os.environ["P12_FIXTURE"], encoding="utf-8") as fh:
                    fixture = json.load(fh)
                envelope = fixture["body"]
                envelope["candidates"][0]["content"]["parts"] = [
                    {"text": json.dumps(synth(schema), ensure_ascii=False)}]
                envelope["modelVersion"] = match.group(1) if match else envelope.get("modelVersion")
                return mod.Response(fixture["http_status"], json=envelope, request=request)

            mod.HTTPTransport.handle_request = handle_request

        for _name in ("httpx2", "httpx"):
            try:
                _install(__import__(_name))
            except ImportError:
                pass
