"""CLI: ``python -m bcc_review ВХОД ОТЧЁТ.md`` (ядро v2), ``stage``, ``verify``, ``doctor``.

Старый движок v1 — за флагом ``--engine v1``: ``python -m bcc_review --engine v1 ВХОД ОТЧЁТ.md``.
``verify`` сам выбирает версию по полю ``schema`` отчёта (``bcc-review/2`` — v2, иначе v1).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def _engine(argv: list[str]) -> tuple[str, list[str]]:
    out, engine, i = [], "v2", 0
    while i < len(argv):
        a = argv[i]
        if a == "--engine" and i + 1 < len(argv):
            engine, i = argv[i + 1].strip().lower(), i + 2
            continue
        if a.startswith("--engine="):
            engine = a.split("=", 1)[1].strip().lower()
        else:
            out.append(a)
        i += 1
    return engine, out


def _is_v2_report(path: str) -> bool:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8")).get("schema") == "bcc-review/2"
    except (OSError, ValueError, AttributeError):
        return False


def main(argv: list[str] | None = None) -> int:
    engine, argv = _engine(list(sys.argv[1:] if argv is None else argv))
    if argv and argv[0] == "verify" and len(argv) > 1 and engine != "v1":
        engine = "v2" if _is_v2_report(argv[1]) else "v1"
    if argv and argv[0] == "contract":
        engine = "v1"
    if engine == "v1":
        from .cli import main as v1_main
        return v1_main(argv)
    from .v2.__main__ import main as v2_main
    return v2_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
