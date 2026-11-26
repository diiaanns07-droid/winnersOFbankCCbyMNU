"""Провайдер ``mock``: синтетические ответы для тестов и демонстрации без ключа.

Сценарий — JSON ``{"<этап>": ответ | [ответы по очереди] | {"error": kind, "retry_after_s": x}}``.
Этап сопоставляется по полному имени (``individual#1``), затем по базовому (``individual``).
Без сценария возвращается минимальный объект, валидный по схеме (пустые массивы).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping, Optional

from ..contracts import ProviderError

_STAGE_RE = re.compile(r"^ЭТАП: (\S+)", re.M)


def synth(schema: Mapping[str, Any], defs: Optional[Mapping[str, Any]] = None) -> Any:
    """Минимальное значение, проходящее схему."""
    defs = defs if defs is not None else schema.get("$defs", {})
    if "$ref" in schema:
        return synth(defs[schema["$ref"].split("/")[-1]], defs)
    if "const" in schema:
        return schema["const"]
    if "enum" in schema:
        return schema["enum"][0]
    if "anyOf" in schema:
        for opt in schema["anyOf"]:
            if opt.get("type") == "null":
                return None
        return synth(schema["anyOf"][0], defs)
    t = schema.get("type")
    if isinstance(t, list):
        t = "null" if "null" in t else t[0]
    if t == "object":
        return {k: synth(v, defs) for k, v in schema.get("properties", {}).items() if k in schema.get("required", [])}
    if t == "array":
        return [synth(schema["items"], defs) for _ in range(schema.get("minItems", 0))]
    return {"string": "", "integer": 0, "number": 0, "boolean": False, "null": None}.get(t, None)


class MockAdapter:
    name = "mock"
    params = {"mock": True}

    def __init__(self, script: Optional[Mapping[str, Any] | str | Path] = None, model: str = "mock-1"):
        if isinstance(script, (str, Path)):
            script = json.loads(Path(script).read_text(encoding="utf-8"))
        self.script = {k: (list(v) if isinstance(v, list) else v) for k, v in dict(script or {}).items()}
        self.model = model
        self.calls: list[str] = []

    def _next(self, stage: str) -> Any:
        for key in (stage, stage.split("#", 1)[0]):
            if key in self.script:
                entry = self.script[key]
                if isinstance(entry, list):
                    if not entry:
                        continue
                    return entry.pop(0) if len(entry) > 1 else entry[0]
                return entry
        return None

    @staticmethod
    def _auto_verdicts(text: str, entry: Mapping[str, Any]) -> dict[str, Any]:
        """Сценарий критика: ``{"__verdicts__": "confirmed", "reject": ["подстрока заголовка", ...]}``."""
        raw = text.split("ВХОДНЫЕ ДАННЫЕ (JSON):", 1)[1]
        items = json.loads(raw).get("candidates", [])
        reject = entry.get("reject", [])
        out = []
        for it in items:
            bad = any(s in it["title"] for s in reject)
            out.append({"cid": it["cid"], "verdict": "rejected" if bad else entry["__verdicts__"],
                        "severity": it["severity"], "reason": "mock: сценарий критика"})
        return {"verdicts": out}

    def invoke(self, *, model: str, messages: list[dict[str, Any]], schema: Mapping[str, Any],
               timeout_s: float) -> dict[str, Any]:
        text = messages[-1]["content"]
        m = _STAGE_RE.search(text)
        stage = m.group(1) if m else "unknown"
        self.calls.append(stage)
        entry = self._next(stage)
        usage = {"input_tokens": sum(len(x["content"]) for x in messages) // 4, "output_tokens": 0}
        if isinstance(entry, dict) and "error" in entry:
            raise ProviderError(entry["error"], entry.get("message", f"mock {entry['error']}"),
                                retry_after_s=entry.get("retry_after_s"), usage=usage, model=model)
        if isinstance(entry, dict) and "__verdicts__" in entry:
            data = self._auto_verdicts(text, entry)
        else:
            data = synth(schema) if entry is None else entry
        usage["output_tokens"] = len(json.dumps(data, ensure_ascii=False)) // 4
        return {"data": data, "usage": usage, "model": self.model, "request_id": f"mock-{len(self.calls)}",
                "stop_reason": "end_turn"}
