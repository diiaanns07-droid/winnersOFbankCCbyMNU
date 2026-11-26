"""Общие фикстуры №06: путь к пакету, загрузчик Markdown, подставной транспорт ask()."""

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


def requirements_from(doc: dict) -> list[dict]:
    """Требования с номерами «**Ф-1.**» из пунктов списка — как их выдала бы нарезка."""
    reqs = []
    for b in doc["blocks"]:
        m = re.search(r"\*\*([A-Za-zА-Яа-яЁё]{1,4}-\d+)\.\*\*", b["text"])
        if m and b["kind"] in ("list_item", "paragraph"):
            reqs.append({"id": f"R-{len(reqs) + 1:02d}", "source_id": m.group(1), "text": b["text"],
                         "block_ids": [b["id"]], "evidence": []})
    return reqs


def evidence_ok(doc: dict, ev: dict) -> bool:
    """Инвариант контракта: block.text[start:end] == quote."""
    block = next((b for b in doc["blocks"] if b["id"] == ev["block_id"]), None)
    return block is not None and block["text"][ev["start"]:ev["end"]] == ev["quote"]


def block_with(doc: dict, needle: str) -> dict:
    hits = [b for b in doc["blocks"] if needle in b["text"]]
    assert len(hits) == 1, (needle, [h["id"] for h in hits])
    return hits[0]


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
    """Подставной транспорт ask(stage, payload, schema).

    pair_rules: [(подстрока A, подстрока B, builder(pair_a, pair_b) -> dict)] — ответ стадии cross.pairs
    для пары, где тексты содержат подстроки (в любом порядке; стороны выравниваются автоматически).
    coverage: dict | callable(payload) -> dict — ответ стадии cross.coverage.
    Каждый ответ проверяется по JSON-схеме стадии, которую передаёт модуль.
    """

    def __init__(self, pair_rules=(), coverage=None, fail_stages=()):
        self.pair_rules = list(pair_rules)
        self.coverage = coverage
        self.fail_stages = set(fail_stages)
        self.calls: list[tuple[str, dict, dict]] = []
        self.matched: list[str] = []

    def __call__(self, stage, payload, schema):
        self.calls.append((stage, payload, schema))
        json.dumps(payload, ensure_ascii=False)  # полезная нагрузка сериализуема
        if stage in self.fail_stages:
            raise TimeoutError(f"{stage}: 503 from provider")
        if stage == "cross.pairs":
            out = []
            for p in payload["pairs"]:
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
        elif stage == "cross.coverage":
            result = self.coverage(payload) if callable(self.coverage) else (self.coverage or {"links": []})
        else:
            raise AssertionError(f"неожиданная стадия {stage}")
        try:
            import jsonschema
        except ImportError:  # pragma: no cover
            return result
        jsonschema.validate(result, schema)
        return result


@pytest.fixture
def load():
    def _load(name: str, **kw) -> dict:
        return load_markdown(FIXTURES / name, **kw)
    return _load


@pytest.fixture
def case_doc():
    return load_markdown(FIXTURES / "case_ab.md")
