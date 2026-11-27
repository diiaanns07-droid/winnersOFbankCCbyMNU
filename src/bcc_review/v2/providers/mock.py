"""Mock-провайдер: отвечает записанными ответами этапов из каталога фикстуры, без сети.

Поиск ответа для этапа ``S`` (k-й вызов этого этапа, k с 1):
``S.k.json`` → ``S.json`` (если там список — k-й элемент, иначе сам объект) → валидный пустой ответ.
Ответ приводится к схеме запроса (лишние поля убираются, недостающие обязательные дописываются пустыми);
если и после этого он схему не проходит (например, этап сделал второй вызов с другой схемой) —
возвращается валидный пустой ответ. Так mock-прогон проходит весь конвейер на любом документе.

Каталог: аргумент ``fixtures_dir`` (``--mock-dir``); иначе ``tests/v2/fixtures/official``.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..types import conform, empty_for

ROOT = Path(__file__).resolve().parents[4]
DEFAULT_DIR = ROOT / "tests" / "v2" / "fixtures" / "official"


def _valid(data: Any, schema: Mapping[str, Any]) -> bool:
    try:
        import jsonschema
    except ImportError:  # pragma: no cover
        return True
    cls = jsonschema.validators.validator_for(dict(schema), default=jsonschema.Draft202012Validator)
    return not any(True for _ in cls(dict(schema)).iter_errors(data))


class MockProvider:
    name = "mock"
    handles_retries = False

    def __init__(self, *, fixtures_dir: str | Path | None = None, model: str | None = None, **_: Any) -> None:
        d = fixtures_dir or DEFAULT_DIR
        self.dir = Path(d)
        self.default_model = model or "mock"
        self.counts: dict[str, int] = {}
        self.calls: list[dict] = []
        self._lock = threading.Lock()

    def _lookup(self, stage: str, k: int) -> Any:
        p = self.dir / f"{stage}.{k}.json"
        if p.is_file():
            return json.loads(p.read_text(encoding="utf-8"))
        p = self.dir / f"{stage}.json"
        if p.is_file():
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return data[min(k, len(data)) - 1] if data else None
            if isinstance(data, dict) and isinstance(data.get("output"), dict) and "stage" in data:
                return data["output"]  # файл этапа из runs/<id>/stages
            return data
        return None

    def invoke(self, *, model: str | None, messages: Sequence[Mapping[str, Any]], schema: Mapping[str, Any],
               timeout_s: float = 0, max_output_tokens: int | None = None, stage: str = "", **_: Any) -> dict:
        stage = stage or "unknown"
        k = self._next(stage)
        return self._respond(stage, k, self._lookup(stage, k), schema, messages, model)

    def _next(self, stage: str) -> int:
        """Номер вызова этапа (с 1); под замком — параллельные вызовы одного этапа получают разные номера."""
        with self._lock:
            k = self.counts[stage] = self.counts.get(stage, 0) + 1
        return k

    def _respond(self, stage: str, k: int, raw: Any, schema: Mapping[str, Any],
                 messages: Sequence[Mapping[str, Any]], model: str | None) -> dict:
        data = conform(raw, dict(schema)) if raw is not None else None
        source = "fixture"
        if data is None or not _valid(data, schema):
            data, source = empty_for(dict(schema)), "empty"
        user = "\n".join(str(m.get("content") or "") for m in messages if m.get("role") != "system")
        with self._lock:
            self.calls.append({"stage": stage, "k": k, "source": source, "user_chars": len(user)})
        return {"data": data, "usage": {"input_tokens": len(user) // 4, "output_tokens": 0},
                "model": model or self.default_model, "request_id": f"mock-{stage}-{k}", "stop_reason": "end_turn",
                "meta": {"provider": "mock", "source": source, "models_used": [model or self.default_model]}}


Provider = MockProvider


class ReplayProvider(MockProvider):
    """``--replay runs/<id>`` (№22): ответы модели — только записанные этим прогоном (``responses/<этап>.json``),
    в порядке вызовов. Записи нет — ошибка «not_configured», а не пустой ответ: этап честно помечается
    невыполненным, вердикт не выносится. Сети и ключа не нужно."""

    name = "replay"

    def __init__(self, *, fixtures_dir: str | Path | None = None, model: str | None = None, **kw: Any) -> None:
        super().__init__(fixtures_dir=fixtures_dir, model=model or "replay", **kw)

    def _lookup(self, stage: str, k: int) -> Any:
        """Строго k-я запись: в отличие от mock, последний ответ не повторяется для лишних вызовов."""
        p = self.dir / f"{stage}.{k}.json"
        if p.is_file():
            return json.loads(p.read_text(encoding="utf-8"))
        p = self.dir / f"{stage}.json"
        if not p.is_file():
            return None
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data[k - 1] if 0 < k <= len(data) else None
        return data if k == 1 else None

    def invoke(self, *, model: str | None, messages: Sequence[Mapping[str, Any]], schema: Mapping[str, Any],
               timeout_s: float = 0, max_output_tokens: int | None = None, stage: str = "", **kw: Any) -> dict:
        stage = stage or "unknown"
        k = self._next(stage)
        raw = self._lookup(stage, k)
        if raw is None or not _valid(conform(raw, dict(schema)), schema):
            from bcc_review.contracts import ProviderError
            # bad_request, а не not_configured: ошибка одного этапа, а не «модель не настроена» на весь прогон
            raise ProviderError("bad_request", f"в сохранённом прогоне нет ответа модели для этапа {stage} "
                                               f"(вызов {k}); повтор без модели невозможен")
        return self._respond(stage, k, raw, schema, messages, model)
