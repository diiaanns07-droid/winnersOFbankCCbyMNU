"""№02: все схемы, которые pipeline реально шлёт модели, принимаются провайдерами Gemini и Claude API.

Схемы этапов меняют их владельцы; этот тест ловит схему, которую санитайзер Gemini (v1 ``to_gemini_schema``)
или structured outputs Claude API (v1 ``to_wire_schema``) не смогут передать, до того как это увидит жюри.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bcc_review.v2.providers import doctor
from bcc_review.v2.providers.mock import MockProvider

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / "release" / "input" / "requirements.md"


class Recorder(MockProvider):
    name = "gemini"
    handles_retries = True

    def __init__(self):
        super().__init__(fixtures_dir=ROOT / "tests" / "v2" / "fixtures" / "official")
        self.schemas: dict[str, dict] = {}

    def invoke(self, *, schema, stage="", **kw):
        self.schemas.setdefault(stage, json.loads(json.dumps(schema)))
        return super().invoke(schema=schema, stage=stage, **kw)


@pytest.fixture(scope="module")
def sent_schemas(tmp_path_factory):
    from bcc_review.v2 import __main__ as cli
    mp = pytest.MonkeyPatch()
    rec = Recorder()
    tmp = tmp_path_factory.mktemp("schemas")
    mp.chdir(tmp)
    mp.setattr(doctor, "make_provider", lambda name=None, **kw: rec)
    try:
        cli.main([str(DOC), str(tmp / "r.md"), "--provider", "gemini", "--no-cache", "-q", "--no-html", "--rpm", "0"])
    finally:
        mp.undo()
    assert rec.schemas, "pipeline не вызвал модель"
    return rec.schemas


def test_pipeline_sends_expected_stages(sent_schemas):
    for stage in ("segment", "lens_analyst", "lens_qa", "lens_architect", "lens_risk", "consistency", "judge"):
        assert stage in sent_schemas, sorted(sent_schemas)


def test_every_stage_schema_is_valid_draft_2020_12(sent_schemas):
    from jsonschema import Draft202012Validator
    for stage, schema in sent_schemas.items():
        Draft202012Validator.check_schema(schema)


def test_every_stage_schema_converts_for_gemini(sent_schemas):
    from bcc_review.providers.gemini import to_gemini_schema
    for stage, schema in sent_schemas.items():
        wire, log = to_gemini_schema(schema)          # SchemaConversionError здесь = 400 у жюри
        text = json.dumps(wire, ensure_ascii=False)
        assert "$ref" not in text and "$defs" not in text, stage
        assert len(text) < 60_000, (stage, len(text))  # большие схемы Gemini отвергает («too many states»)


def test_every_stage_schema_converts_for_claude_api(sent_schemas):
    pytest.importorskip("anthropic")
    from bcc_review.providers.anthropic import to_wire_schema
    for stage, schema in sent_schemas.items():
        wire = to_wire_schema(schema)
        assert wire.get("type") == "object", stage
