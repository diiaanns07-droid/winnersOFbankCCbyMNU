"""Замер №11: полный прогон конвейера с ранним запуском вопросов (параллельно с судьёй) без правки pipeline.py.

python tests/v2/fixtures/11_audit/run_early.py ВХОД ОТЧЁТ.md [аргументы bcc_review ...]
Обёртка подменяет Pipeline.stage/_clarify так же, как это сделает правка №01 (см. статус №11).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "src"))
from bcc_review.v2 import pipeline
from bcc_review.v2.stages import clarify

_stage = pipeline.Pipeline.stage


def stage(self, name, fn, **kw):
    if name == "judge" and self.opts.get("clarify", True) and (self.reuse is None or "clarify" in self.rerun):
        rec = self.run.load_stage("quotes") if hasattr(self.run, "load_stage") else None
        cands = (rec or {}).get("output", {}).get("candidates") or []
        self._early = clarify.start(self.ctx, cands)
    return _stage(self, name, fn, **kw)


def _clarify(self, ctx, findings):
    early = getattr(self, "_early", None)
    return clarify.finish(ctx, findings, early) if early is not None else clarify.run(ctx, findings)


pipeline.Pipeline.stage = stage
pipeline.Pipeline._clarify = _clarify

from bcc_review.__main__ import main  # noqa: E402
sys.exit(main(sys.argv[1:]))
