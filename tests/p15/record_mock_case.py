"""Записать ответы модели для публичного кейса BCC в сценарий mock-провайдера.

Источник ответов — подставной транспорт владельца №06 (tests/p06/demo_case.py, «сценарии
К2/К3»): он отвечает этапам cross.pairs и cross.coverage так, как ответила бы модель на
этот документ. Скрипт запускает настоящий ``run_review`` на ``release/input/requirements.md``,
перехватывает эти два этапа и сохраняет ответы. Проверку смысла сценарий подтверждает
механизмом mock (``__verdicts__``), остальные этапы mock отвечает минимальным объектом.

    python tests/p15/record_mock_case.py release/input/requirements.md tests/p15/fixtures/mock_case_recorded.json

Нужна ветка bcc/integration (модули №06 и tests/p06). Это не ответы живой модели.
"""

from __future__ import annotations

import json
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main(src: Path, out: Path) -> int:
    sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests" / "p06")]
    from demo_case import _scripted  # транспорт владельца №06

    from bcc_review import run_review
    from bcc_review.engine import read_document
    from bcc_review.runtime import mock as M

    scripted = _scripted(read_document(src))
    recorded: dict[str, list] = {"cross.pairs": [], "cross.coverage": []}
    original = M.MockAdapter.invoke

    def invoke(self, *, model, messages, schema, timeout_s):
        text = messages[-1]["content"]
        stage = (re.search(r"^ЭТАП: (\S+)", text, re.M) or [None, "?"])[1].split("#")[0]
        if stage in recorded:
            data = scripted(stage, json.loads(text.split("ВХОДНЫЕ ДАННЫЕ (JSON):", 1)[1]), schema)
            recorded[stage].append(data)
            return {"data": data, "usage": {"input_tokens": 0, "output_tokens": 0}, "model": self.model,
                    "request_id": f"rec-{stage}-{len(recorded[stage])}", "stop_reason": "end_turn"}
        return original(self, model=model, messages=messages, schema=schema, timeout_s=timeout_s)

    M.MockAdapter.invoke = invoke
    tmp = tempfile.mkdtemp()
    run_review(src, Path(tmp) / "report.md", options={"provider": "mock", "use_cache": False, "artifacts_dir": tmp})
    script = {
        "_source": f"ответы транспорта №06 (tests/p06/demo_case.py) на {src.name}; не живая модель",
        "cross.pairs": recorded["cross.pairs"],
        "cross.coverage": recorded["cross.coverage"][0] if recorded["cross.coverage"] else {},
        "verify_meaning": {"__verdicts__": "confirmed"},
    }
    out.write_text(json.dumps(script, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"записано: {out} (cross.pairs: {len(recorded['cross.pairs'])}, совпавшие пары: {scripted.matched})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(Path(sys.argv[1]), Path(sys.argv[2])))
