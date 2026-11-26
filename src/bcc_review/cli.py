"""Временная оболочка CLI до подключения движка (заменяется в следующем коммите)."""

from __future__ import annotations

import sys

from . import __version__
from .contracts import SCHEMA_VERSION, schema_json


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in ("--version", "-V"):
        print(f"bcc-review {__version__} (contract {SCHEMA_VERSION})")
        return 0
    if argv and argv[0] == "contract":
        sys.stdout.write(schema_json())
        return 0
    print("usage: python -m bcc_review INPUT OUTPUT.md | verify REPORT.json SOURCE | contract | --version", file=sys.stderr)
    return 2
