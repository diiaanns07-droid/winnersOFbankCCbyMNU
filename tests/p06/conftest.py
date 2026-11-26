"""Общие фикстуры №06: штатный читатель движка, синтетический загрузчик, подставной транспорт ask()."""

from __future__ import annotations

import copy
import json
import re
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for p in (ROOT / "src", HERE):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from p06_mdloader import load_markdown  # noqa: E402

FIXTURES = HERE / "fixtures"


def read_doc(source) -> dict:
    """Document штатным читателем движка (модуль №01 или резерв Max); строка с переводами — как текст файла."""
    try:
        from bcc_review.runtime.modules import Modules
    except ImportError:  # вне ветки интеграции
        return load_markdown(source)
    if isinstance(source, str) and "\n" in source:
        import tempfile

        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as fh:
            fh.write(source)
        source = fh.name
    return Modules().get("read_text").func(str(source))


def requirements_from(doc: dict) -> list[dict]:
    """Требования с номерами «Ф-1.» (или «**Ф-1.**») из пунктов списка — как их выдала бы нарезка."""
    reqs = []
    for b in doc["blocks"]:
        m = re.match(r"^\s*(?:[*\-]\s+)?(?:\*\*)?([A-Za-zА-Яа-яЁё]{1,4}-\d+)\.(?:\*\*)?\s", b["text"])
        if m and b["kind"] in ("list_item", "paragraph"):
            reqs.append({"id": f"R-{len(reqs) + 1:02d}", "source_id": m.group(1), "text": b["text"],
                         "block_ids": [b["id"]], "evidence": [], "review_status": "reviewed", "review_reason": None})
    return reqs


def evidence_ok(doc: dict, ev: dict) -> bool:
    """Инвариант контракта: block.text[start:end] == quote."""
    block = next((b for b in doc["blocks"] if b["id"] == ev["block_id"]), None)
    return block is not None and block["text"][ev["start"]:ev["end"]] == ev["quote"]


def block_with(doc: dict, needle: str) -> dict:
    hits = [b for b in doc["blocks"] if needle in b["text"]]
    assert len(hits) == 1, (needle, [h["id"] for h in hits])
    return hits[0]


def sub(res: dict, subkind: str) -> list[dict]:
    return [c for c in res["candidates"] if c.get("subkind") == subkind]


def fill(schema: dict, obj):
    """Как structured outputs: недостающие обязательные поля строгой схемы — пустые значения."""
    t = schema.get("type")
    if t == "object":
        obj = dict(obj or {})
        for k, sch in schema.get("properties", {}).items():
            if k in obj:
                obj[k] = fill(sch, obj[k])
            else:
                obj[k] = fill(sch, None)
        return obj
    if t == "array":
        return [fill(schema.get("items", {}), x) for x in (obj or [])]
    if t == "string":
        return "" if obj is None else str(obj)
    return obj


def _swap(res: dict) -> dict:
    r = copy.deepcopy(res)
    r["a"], r["b"] = r.get("b"), r.get("a")
    r = {k: v for k, v in r.items() if v is not None}
    w = r.get("witness")
    if w:
        for x, y in (("evidence_a", "evidence_b"), ("outcome_a", "outcome_b"), ("outcome_a_value", "outcome_b_value")):
            w[x], w[y] = w.get(y), w.get(x)
        r["witness"] = {k: v for k, v in w.items() if v is not None}
    return r


class ScriptedAsk:
    """Подставной транспорт ask(stage, payload, schema) по контракту движка.

    payload = {task, input, context}; стадии cross#pairs и cross#coverage. Ответ дополняется до
    строгой схемы стадии (как у structured outputs) и проверяется jsonschema.
    pair_rules: [(подстрока A, подстрока B, builder(pair_a, pair_b) -> dict)].
    coverage: dict | callable(input) -> dict.
    """

    def __init__(self, pair_rules=(), coverage=None, fail_stages=(), error=None):
        self.pair_rules = list(pair_rules)
        self.coverage = coverage
        self.fail_stages = set(fail_stages)
        self.error = error
        self.calls: list[tuple[str, dict, dict]] = []
        self.matched: list[str] = []

    def __call__(self, stage, payload, schema):
        self.calls.append((stage, payload, schema))
        assert set(payload) <= {"task", "input", "context"}, sorted(payload)
        assert isinstance(payload["task"], str) and payload["task"].strip()
        json.dumps(payload, ensure_ascii=False)
        if stage in self.fail_stages:
            if isinstance(self.error, BaseException):
                raise self.error
            raise TimeoutError(f"{stage}: 503 from provider")
        data = payload["input"]
        if stage == "cross#pairs":
            out = []
            for p in data["pairs"]:
                for i, (sa, sb, build) in enumerate(self.pair_rules):
                    if sa in p["a"]["text"] and sb in p["b"]["text"]:
                        res = build(p["a"], p["b"])
                    elif sb in p["a"]["text"] and sa in p["b"]["text"]:
                        res = _swap(build(p["b"], p["a"]))
                    else:
                        continue
                    res["pair_id"] = p["pair_id"]
                    out.append(res)
                    self.matched.append(f"rule{i}:{p['pair_id']}")
                    break
            result = {"pairs": out}
        elif stage == "cross#coverage":
            result = self.coverage(data) if callable(self.coverage) else (self.coverage or {"links": []})
        else:
            raise AssertionError(f"неожиданная стадия {stage}")
        result = fill(schema, result)
        import jsonschema

        jsonschema.validate(result, schema)
        return result


@pytest.fixture
def load():
    def _load(name: str, loader: str = "engine", **kw) -> dict:
        if loader == "engine":
            return read_doc(FIXTURES / name)
        return load_markdown(FIXTURES / name, table_mode=kw.get("table_mode", "row"))
    return _load


@pytest.fixture
def case_doc():
    return read_doc(FIXTURES / "case_ab.md")
