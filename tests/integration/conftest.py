import copy
import json
import shutil
from pathlib import Path

import pytest

from bcc_review import engine
from bcc_review.contracts import RunOptions

FIX = Path(__file__).parent / "fixtures"
BCC = FIX / "bcc_requirements.md"


@pytest.fixture(autouse=True)
def _no_sleep_no_env(monkeypatch):
    sleeps = []
    monkeypatch.setattr(engine, "SLEEP", lambda s: sleeps.append(s))
    for var in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "GEMINI_API_KEY", "GOOGLE_API_KEY", "ANTHROPIC_MODEL",
                "GEMINI_MODEL", "BCC_FORCE_FALLBACK"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(engine, "load_dotenv", lambda *a, **k: None)
    return sleeps


@pytest.fixture
def sleeps(_no_sleep_no_env):
    return _no_sleep_no_env


@pytest.fixture
def bcc_copy(tmp_path):
    dst = tmp_path / "requirements.md"
    shutil.copyfile(BCC, dst)
    return dst


@pytest.fixture
def mock_script():
    return json.loads((FIX / "mock_bcc.json").read_text(encoding="utf-8"))


def write_script(tmp_path, script, name="script.json"):
    p = tmp_path / name
    p.write_text(json.dumps(script, ensure_ascii=False), encoding="utf-8")
    return str(p)


def run(tmp_path, src, out_name="report.md", **opts):
    base = {"cache_dir": str(tmp_path / "cache"), "artifacts_dir": str(tmp_path / (out_name + ".artifacts"))}
    base.update(opts)
    return engine.run_review(src, tmp_path / out_name, options=RunOptions.coerce(base))
