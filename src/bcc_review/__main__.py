"""CLI: ``python -m bcc_review INPUT OUTPUT.md`` и ``python -m bcc_review verify REPORT.json SOURCE``."""

from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    from .cli import main as _main

    return _main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
