"""Опора тестов №04: синтетический Document по контракту v1 и подставные модели.

Document = {id, title, format, blocks, warnings}, Block = {id, kind, section, text, loc} — как в
``bcc_review.contracts`` (bcc/integration @3e6b569): id документа — SHA-256 исходных байтов, id блока —
``b0001``… в порядке чтения, ``loc.line_start/line_end`` с 1. Режим ``visible=True`` имитирует парсер,
который убирает из ``block.text`` разметку (``**``, `````, маркер ``* ``, внешние ``|``).
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Callable

FIXTURES = Path(__file__).resolve().parent / "fixtures"

_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_LIST = re.compile(r"^(\s*)([*+-]|\d+[.)])\s+(.*)$")

try:  # стыковой контракт, если bootstrap уже в checkout
    from bcc_review import contracts as CONTRACTS
except ImportError:  # pragma: no cover - до появления bcc/integration
    CONTRACTS = None


def _visible(text: str) -> str:
    return text.replace("**", "").replace("`", "")


def md_document(text: str, name: str = "fixture.md", *, visible: bool = False) -> dict[str, Any]:
    """Минимальный разбор Markdown: заголовки, абзацы, пункты списков, строки таблиц, блоки кода."""
    raw = text.encode("utf-8")
    lines = text.split("\n")
    blocks: list[dict[str, Any]] = []
    stack: list[tuple[int, str]] = []
    title = None

    def section() -> list[str]:
        return [t for _, t in stack]

    def add(kind: str, start: int, end: int, body: str) -> None:
        if visible and kind != "code":
            body = _visible(body)
            if kind in ("table_header", "table_row"):
                body = body.strip().strip("|").strip()
        blocks.append({
            "id": f"b{len(blocks) + 1:04d}",
            "kind": kind,
            "section": section(),
            "text": body,
            "loc": {"line_start": start, "line_end": end},
        })

    i = 0
    while i < len(lines):
        line = lines[i]
        n = i + 1
        if not line.strip():
            i += 1
            continue
        m = _HEADING.match(line)
        if m:
            level, head = len(m.group(1)), m.group(2).strip()
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, head))
            title = title or head
            add("heading", n, n, head)
            i += 1
            continue
        if line.startswith("```"):
            j = i + 1
            while j < len(lines) and not lines[j].startswith("```"):
                j += 1
            add("code", n, j + 1, "\n".join(lines[i + 1 : j]))
            i = j + 1
            continue
        if line.strip() in ("---", "***", "___"):
            add("other", n, n, line.strip())
            i += 1
            continue
        if line.lstrip().startswith("|"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if any(cells) and all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
                i += 1
                continue
            first = i == 0 or not lines[i - 1].lstrip().startswith("|")
            add("table_header" if first else "table_row", n, n, line.strip())
            i += 1
            continue
        m = _LIST.match(line)
        if m:
            marker, body = m.group(2), m.group(3)
            if marker[0].isdigit():
                body = f"{marker} {body}"  # номер пункта — часть текста, а не служебная разметка
            j = i + 1
            while j < len(lines) and lines[j].startswith("  ") and lines[j].strip() and not _LIST.match(lines[j]):
                body += "\n" + lines[j].strip()
                j += 1
            add("list_item", n, j, body.rstrip())
            i = j
            continue
        j = i
        para: list[str] = []
        while j < len(lines):
            cur = lines[j]
            if (not cur.strip() or _HEADING.match(cur) or cur.startswith("```") or cur.lstrip().startswith("|")
                    or _LIST.match(cur) or cur.strip() in ("---", "***", "___")):
                break
            para.append(cur.rstrip())
            j += 1
        add("paragraph", n, j, "\n".join(para))
        i = j
    return {
        "id": hashlib.sha256(raw).hexdigest(),
        "title": title or name,
        "format": "markdown",
        "blocks": blocks,
        "warnings": [],
    }


def fixture_text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def fixture_document(name: str, *, visible: bool = False) -> dict[str, Any]:
    return md_document(fixture_text(name), name, visible=visible)


def block_by_text(doc: dict[str, Any], snippet: str) -> dict[str, Any]:
    found = [b for b in doc["blocks"] if snippet in b["text"]]
    assert found, f"нет блока с «{snippet}»"
    return found[0]


def payload_blocks(payload: dict[str, Any], doc: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Блоки окна с текстом: текст из payload (attach_text) или из документа (его прикладывает движок)."""
    texts = {b["id"]: b["text"] for b in doc["blocks"]} if doc else {}
    out = []
    for b in payload["input"]["blocks"]:
        item = dict(b)
        item.setdefault("text", texts.get(b["id"], ""))
        out.append(item)
    return out


def process_ids(call: dict[str, Any]) -> list[str]:
    return [b["id"] for b in call["payload"]["input"]["blocks"] if b["process"]]


_FACT_DEFAULTS = {"subject": None, "field": None, "direction": None, "type": None, "value": None, "unit": None,
                  "range": None, "condition": None, "required": None, "values": []}


class QuoteModel:
    """Подставная модель: пункты описаны цитатами, block_id подставляется по тексту окна.

    Эталон переносим между парсерами: ID блоков вычисляются из текущего payload. Пункт выдаётся,
    только если его первая цитата лежит в блоке окна с process=true. Ответ соответствует RESPONSE_SCHEMA.
    """

    def __init__(self, spec: dict[str, Any], doc: dict[str, Any] | None = None,
                 mutate: Callable[[dict[str, Any], int, dict[str, Any]], Any] | None = None,
                 overeager: bool = False):
        self.spec = spec
        self.doc = doc
        self.mutate = mutate
        self.overeager = overeager  # нарушает инструкцию: отвечает и по блокам контекста (process=false)
        self.calls: list[dict[str, Any]] = []

    @staticmethod
    def _find(quote: str, pool: list[dict[str, Any]]) -> str | None:
        """Блок по цитате: дословно, затем без учёта пробелов и разметки (имитация «дрейфа» модели)."""
        for b in pool:
            if quote in b["text"]:
                return b["id"]
        squeeze = " ".join(_visible(quote).split())
        for b in pool:
            if squeeze in " ".join(_visible(b["text"]).split()):
                return b["id"]
        return None

    def respond(self, payload: dict[str, Any]) -> dict[str, Any]:
        blocks = payload_blocks(payload, self.doc)
        proc = blocks if self.overeager else [b for b in blocks if b.get("process")]
        items = []
        for it in self.spec.get("items", []):
            quotes = it["quotes"]
            first = self._find(quotes[0], proc)
            if first is None:
                continue
            ev = [{"block_id": first, "quote": quotes[0]}]
            for q in quotes[1:]:
                bid = self._find(q, blocks)
                if bid:
                    ev.append({"block_id": bid, "quote": q})
            items.append({"source_id": it.get("source_id"), "kind": it["kind"], "text": it["text"], "evidence": ev})
        excluded = []
        for g in self.spec.get("excluded", []):
            ids = [b["id"] for b in proc
                   if any(s in b["text"] or _visible(s) in b["text"] for s in g.get("contains", []))
                   or any(b["text"].strip() == s for s in g.get("equals", []))]
            if ids:
                excluded.append({"category": g["category"], "reason": g["reason"], "block_ids": ids})
        facts = []
        for f in self.spec.get("facts", []):
            first = self._find(f["quotes"][0], proc)
            if first is None:
                continue
            fact = dict(_FACT_DEFAULTS)
            fact.update({k: v for k, v in f.items() if k != "quotes"})
            if fact["value"] is not None:
                fact["value"] = str(fact["value"])
            fact["evidence"] = [{"block_id": first, "quote": f["quotes"][0]}]
            facts.append(fact)
        return {"items": items, "excluded": excluded, "facts": facts, "done": True}

    def __call__(self, stage: str, payload: dict[str, Any], schema: dict[str, Any]) -> Any:
        self.calls.append({"stage": stage, "payload": copy.deepcopy(payload), "schema": schema})
        resp = self.respond(payload)
        if self.mutate is not None:
            resp = self.mutate(resp, len(self.calls) - 1, payload)
        return resp


class ScriptedModel:
    """Подставная модель с заранее заданными сырыми ответами (по одному на вызов)."""

    def __init__(self, responses: list[Any]):
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def __call__(self, stage: str, payload: dict[str, Any], schema: dict[str, Any]) -> Any:
        self.calls.append({"stage": stage, "payload": copy.deepcopy(payload), "schema": schema})
        if not self.responses:
            raise RuntimeError("ScriptedModel: ответы закончились")
        resp = self.responses.pop(0)
        if isinstance(resp, BaseException):
            raise resp
        return copy.deepcopy(resp)


def load_spec(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def fates(inv: dict[str, Any]) -> dict[str, str]:
    return {b["block_id"]: b["fate"] for b in inv["block_coverage"]["blocks"]}


def warning_codes(inv: dict[str, Any]) -> list[str]:
    return [w["code"] for w in inv["warnings"]]


def warned(inv: dict[str, Any], code: str, *needles: str) -> bool:
    """Есть предупреждение с кодом ``code``, в тексте или block_ids которого встречаются все ``needles``."""
    for w in inv["warnings"]:
        hay = w["message"] + " " + " ".join(w["block_ids"])
        if w["code"] == code and all(n in hay for n in needles):
            return True
    return False


def assert_invariants(doc: dict[str, Any], inv: dict[str, Any]) -> None:
    """Инварианты инвентаря: каждый блок получил ровно одну судьбу, цитаты дословны, ID уникальны."""
    text = {b["id"]: b["text"] for b in doc["blocks"]}
    ids = [r["id"] for r in inv["requirements"]]
    assert len(ids) == len(set(ids)), "ID требований не уникальны"
    req_blocks = {bid for r in inv["requirements"] for bid in r["block_ids"]}
    excl_blocks = [bid for g in inv["excluded"] for bid in g["block_ids"]]
    assert len(excl_blocks) == len(set(excl_blocks)), "блок в нескольких группах исключений"
    assert not (req_blocks & set(excl_blocks)), "блок одновременно требование и исключение"
    assert not (req_blocks & set(inv["unprocessed_block_ids"]))
    assert not (set(excl_blocks) & set(inv["unprocessed_block_ids"]))
    assert req_blocks | set(excl_blocks) | set(inv["unprocessed_block_ids"]) == set(text), "есть блок без судьбы"
    assert [b["block_id"] for b in inv["block_coverage"]["blocks"]] == [b["id"] for b in doc["blocks"]]
    for r in inv["requirements"]:
        assert r["text"].strip(), r
        assert r["hints"] and len(r["hints"]) == len(r["evidence"]), r
        assert r["kind"] in ("functional", "nonfunctional", "data", "integration", "ui", "contract", "acceptance")
        assert r["block_ids"] == sorted(set(r["block_ids"]), key=list(text).index)
        for h, ev in zip(r["hints"], r["evidence"]):
            assert h["quote"].strip(), r
            assert h["quote"] in text[h["block_id"]], (r["id"], h)
            assert text[ev["block_id"]][ev["start"]:ev["end"]] == ev["quote"] == h["quote"], (r["id"], ev)
            if "context" in h:
                assert h["quote"] in h["context"] and text[h["block_id"]].count(h["context"]) == 1
    for g in inv["excluded"]:
        assert g["reason"].strip() and g["block_ids"], g
    for f in inv["fact_hints"]:
        assert f["hints"], f
        for h, ev in zip(f["hints"], f["evidence"]):
            assert text[ev["block_id"]][ev["start"]:ev["end"]] == ev["quote"] == h["quote"], f
        for value in (f["subject"], f["field"], f["type"], f["unit"], f["condition"]):
            assert value is None or (isinstance(value, str) and value.strip()), f
    for w in inv["warnings"]:
        assert set(w) == {"code", "message", "stage", "block_ids"} and w["stage"] == "inventory", w
        assert set(w["block_ids"]) <= set(text), w
    cov = inv["block_coverage"]
    assert cov["total_blocks"] == len(text)
    assert cov["requirement_blocks"] + cov["excluded_blocks"] + cov["unprocessed_blocks"] == len(text)
    assert cov["level"] == ("complete" if not inv["unprocessed_block_ids"] else "partial")
    if CONTRACTS is not None:
        assert_contract(doc, inv)


def assert_contract(doc: dict[str, Any], inv: dict[str, Any]) -> None:
    """Стык с contracts v1: Document, Requirement, Hint, Evidence, Warning и опоры в Report-скелете."""
    C = CONTRACTS
    if isinstance(doc, dict) and doc.get("format") in C.DOC_FORMATS:
        C.validate(doc, "Document")
    for r in inv["requirements"]:
        C.validate(r, "Requirement")
    for f in inv["fact_hints"]:
        for ev in f["evidence"]:
            C.validate(ev, "Evidence")
        for h in f["hints"]:
            C.validate(h, "Hint")
    for w in inv["warnings"]:
        C.validate(w, "Warning")
    import jsonschema

    jsonschema.validate(inv["excluded"], C.REPORT_SCHEMA["properties"]["excluded"])
    report = C.empty_report_skeleton()
    report["document"] = doc if isinstance(doc, dict) else {}
    report["requirements"] = inv["requirements"]
    if report["document"]:
        assert C.evidence_errors(report) == []


# --------------------------------------------------------------------------- транспорт движка
_CTX_LINE = re.compile(r"^\[(b\d{4,})\] ?(.*)$")
_K_LABEL = re.compile(r"^(?P<label>[А-ЯЁA-Z]{1,4}-\d+)\.\s+(?P<body>.+)$")
_EXCEPTION = re.compile(r"^Исключение:\s+(?P<body>.+)$")


def _undecorate(rendered: str) -> str:
    """Текст блока из рендера ``runtime.context.render_block`` (снимает «• », «## », «| … |»)."""
    s = rendered
    s = re.sub(r"^\(заголовок таблицы\) ", "", s)
    if s.startswith("• "):
        return s[2:]
    if re.match(r"^#{1,6} ", s):
        return s.split(" ", 1)[1]
    if s.startswith("| ") and s.endswith(" |"):
        return s[2:-2]
    return s


def visible_blocks(messages: list[dict[str, Any]]) -> dict[str, str]:
    """Блоки, которые модель действительно видит в контексте сообщений Asker: ``{id: текст}``."""
    seen: dict[str, list[str]] = {}
    cur = None
    for msg in messages:
        if msg["role"] != "user" or "ВХОДНЫЕ ДАННЫЕ (JSON):" in msg["content"]:
            continue
        for line in msg["content"].split("\n"):
            m = _CTX_LINE.match(line)
            if m:
                cur = m.group(1)
                seen[cur] = [m.group(2)]
            elif cur is not None and line and not line.startswith(("ФРАГМЕНТЫ", "ДОКУМЕНТ", "ИНДЕКС")):
                seen[cur].append(line)
    return {bid: _undecorate("\n".join(lines)) for bid, lines in seen.items()}


class WindowContentAdapter:
    """Детерминированный «провайдер» за ``runtime.asker.Asker``.

    Отвечает только по тому, что Asker реально передал: тексты — из контекста сообщений
    (``[b0004] …``), список окна и разделы — из ``input.blocks``. Правила ответа:
    «К-1. …» → обязательство с номером; «Исключение: …» → обязательство с номером ближайшего
    видимого в окне пункта того же раздела (иначе null); «→» → design; «Документ …» → preamble.
    Порядок выдачи меняется от вызова к вызову. ``faults = {номер_вызова: "truncated"}`` имитирует
    ``ProviderError("truncated")`` адаптера (stop_reason=max_tokens по HANDOFF).
    """

    name = "mock"
    params = {"mock": True, "p04": "window-content"}

    def __init__(self, *, overeager: bool = False, faults: dict[int, str] | None = None):
        self.overeager = overeager
        self.faults = dict(faults or {})
        self.calls: list[dict[str, Any]] = []

    def invoke(self, *, model: str, messages: list[dict[str, Any]], schema: Any, timeout_s: float) -> dict[str, Any]:
        from bcc_review.contracts import ProviderError

        n = len(self.calls)
        body = messages[-1]["content"]
        inp = json.loads(body.split("ВХОДНЫЕ ДАННЫЕ (JSON):\n", 1)[1])
        texts = visible_blocks(messages)
        self.calls.append({"input": inp, "visible": sorted(texts), "context_lines": len(texts)})
        if self.faults.get(n) == "truncated":
            raise ProviderError("truncated", "mock: ответ обрезан по max_tokens", model=model)
        listed = inp["blocks"]
        answer_for = [b for b in listed if b["process"] or self.overeager]
        items, excluded = [], []
        for b in answer_for:
            text = texts.get(b["id"], b.get("text") or "")
            if not text:
                continue  # блока нет в переданном контексте — модель о нём не знает
            m, e = _K_LABEL.match(text), _EXCEPTION.match(text)
            if m:
                items.append({"source_id": m["label"], "kind": "functional",
                              "text": f"Правило {m['label']}: {m['body'].rstrip('.')}",
                              "evidence": [{"block_id": b["id"], "quote": m["body"]}]})
            elif e:
                parent = None
                for prev in listed[: listed.index(b)][::-1]:
                    pm = _K_LABEL.match(texts.get(prev["id"], ""))
                    if prev["section"] == b["section"] and pm:
                        parent = pm["label"]
                        break
                items.append({"source_id": parent, "kind": "functional",
                              "text": f"Исключение из правила: {e['body'].rstrip('.')}",
                              "evidence": [{"block_id": b["id"], "quote": e["body"]}]})
            elif "→" in text:
                excluded.append({"category": "design", "reason": "Схема без самостоятельного обязательства",
                                 "block_ids": [b["id"]]})
            elif text.startswith("Документ "):
                excluded.append({"category": "preamble", "reason": "Вводный текст", "block_ids": [b["id"]]})
            else:
                items.append({"source_id": None, "kind": "functional", "text": text,
                              "evidence": [{"block_id": b["id"], "quote": text}]})
        items = items[::-1] if n % 2 == 0 else items[1:] + items[:1]  # порядок выдачи меняется
        data = {"items": items, "excluded": excluded[::-1], "facts": [], "done": True}
        return {"data": data, "usage": {"input_tokens": len(body) // 4, "output_tokens": 0}, "model": "p04-window-content",
                "request_id": f"p04-{n + 1}", "stop_reason": "end_turn"}


def engine_ask(document: dict[str, Any], adapter: Any, *, max_calls: int = 40):
    """``ask`` из опубликованного рантайма движка: ContextBuilder → Asker → adapter, общий Budget."""
    from bcc_review.runtime.asker import Asker
    from bcc_review.runtime.context import ContextBuilder
    from bcc_review.runtime.core import Budget, Cache, StageStats, Tracer

    budget = Budget(max_calls, 600.0)
    asker = Asker(adapter=adapter, provider="mock", model="p04-window-content", budget=budget,
                  cache=Cache(None, enabled=False), stats=StageStats(), tracer=Tracer(None, "p04"),
                  context=ContextBuilder(document), max_retries=0, sleep=lambda s: None)
    return asker, budget


def published_document(path: Path | str) -> tuple[dict[str, Any], str]:
    """Document опубликованного читателя через слот движка (№01 или резерв) и normalize_document."""
    from bcc_review import contracts as C
    from bcc_review.runtime.modules import Modules

    reader = Modules().get("read_text")
    return C.normalize_document(reader.func(Path(path))), reader.label
