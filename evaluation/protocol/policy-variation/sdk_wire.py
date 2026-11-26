"""Capture only generation HTTP status and the modelVersion returned by the real SDK."""
import importlib
import json
import os
from pathlib import Path
import runpy


def attach(client, log_path):
    send = client.send

    def observe(self, request, *args, **kwargs):
        if not request.url.path.endswith(":generateContent"):
            return send(self, request, *args, **kwargs)
        entry = {"status": None, "response_model": None}
        try:
            response = send(self, request, *args, **kwargs)
            entry["status"] = response.status_code
            if response.status_code == 200:
                response.read()
                try:
                    body = response.json()
                except ValueError:
                    body = {}
                if isinstance(body, dict):
                    entry["response_model"] = body.get("modelVersion")
            return response
        finally:
            with log_path.open("a", encoding="utf8") as f:
                f.write(json.dumps(entry) + "\n")

    client.send = observe


if __name__ == "__main__":
    clients = set()
    for name in ("httpx2", "httpx"):
        try:
            clients.add(importlib.import_module(name).Client)
        except ModuleNotFoundError:
            continue
    if not clients:
        raise SystemExit("Install the release Gemini dependencies")
    for client in clients:
        attach(client, Path(os.environ["IE_WIRE_LOG"]))
    runpy.run_module("bcc_review", run_name="__main__", alter_sys=True)
