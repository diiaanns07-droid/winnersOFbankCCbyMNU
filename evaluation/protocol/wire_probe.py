"""Run the official CLI and record Gemini response metadata at the release transport boundary."""
import json
import os
import runpy
from pathlib import Path
from bcc_review.runtime.fallback import gemini

transport = gemini.urllib_transport
wire_log = Path(os.environ["IE_WIRE_LOG"])

def observe(*args, **kwargs):
    entry = {"status": None, "response_model": None}
    try:
        response = transport(*args, **kwargs)
        entry["status"] = response[0]
        try:
            body = json.loads(response[2])
            if isinstance(body, dict):
                entry["response_model"] = body.get("modelVersion")
        except (ValueError, UnicodeError):
            pass
        return response
    finally:
        with wire_log.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(entry) + "\n")

gemini.urllib_transport = observe
runpy.run_module("bcc_review", run_name="__main__", alter_sys=True)
