"""Напечатать SHA коммита по файлам каталога .git без программы git (для сборки Docker-образа).

    python scripts/git_commit.py [КАТАЛОГ_GIT]     # по умолчанию .git; пустая строка, если определить нельзя

Понимает HEAD с SHA (detached, тег) и HEAD со ссылкой на ветку (файл refs/… или packed-refs).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

SHA = re.compile(r"^[0-9a-f]{40}$")


def resolve(git_dir: Path) -> str:
    try:
        head = (git_dir / "HEAD").read_text(encoding="utf-8").strip()
    except OSError:
        return ""
    if SHA.match(head):
        return head
    if not head.startswith("ref:"):
        return ""
    ref = head.split(":", 1)[1].strip()
    try:
        value = (git_dir / ref).read_text(encoding="utf-8").strip()
        if SHA.match(value):
            return value
    except OSError:
        pass
    try:
        for line in (git_dir / "packed-refs").read_text(encoding="utf-8").splitlines():
            parts = line.strip().split(" ", 1)
            if len(parts) == 2 and parts[1] == ref and SHA.match(parts[0]):
                return parts[0]
    except OSError:
        pass
    return ""


if __name__ == "__main__":
    print(resolve(Path(sys.argv[1] if len(sys.argv) > 1 else ".git")))
