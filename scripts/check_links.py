"""Проверка относительных ссылок в документах сдачи: каждая ведёт на файл или каталог в дереве репозитория.

    python scripts/check_links.py                       # README.md, SUBMISSION.md, reports/README.md, presentation/README.md
    python scripts/check_links.py README.md docs/x.md   # свои файлы
    python scripts/check_links.py --no-git              # только диск (без сверки с git)
    python scripts/check_links.py --pending presentation/deck.pdf   # файл другой ветки: печатается, но не считается битым

Что считается ссылкой: `[текст](путь)`, `![картинка](путь)`, `[метка]: путь`, `href="путь"` и `src="путь"` в HTML.
Пропускаются внешние адреса (`https://…`, `mailto:`), якоря на ту же страницу (`#раздел`), блоки кода и `код в
строке`. Путь считается от каталога файла со ссылкой (как на GitHub); `/путь` — от корня репозитория; `#якорь` и
`?параметры` отбрасываются, `%20` раскодируется.

«В дереве» — файл есть на диске **и** отслеживается git: файл, которого нет в коммите, жюри на GitHub не увидит.
Вне git-репозитория (архив ZIP) и с `--no-git` проверяется только диск.

Код выхода: 0 — битых ссылок нет; 1 — есть (список в выводе); 2 — файл для проверки не найден.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FILES = ("README.md", "SUBMISSION.md", "reports/README.md", "presentation/README.md")

_FENCE = re.compile(r"^\s{0,3}(`{3,}|~{3,})")
_INLINE_CODE = re.compile(r"(`+)(?:(?!\1).)+?\1")
# [текст](цель) и ![alt](цель); цель — <в угловых скобках> или без пробелов, с необязательным "заголовком"
_INLINE_LINK = re.compile(r"!?\[(?:[^\[\]]|\[[^\[\]]*\])*\]\(\s*(<[^>]*>|[^)\s]+)(?:\s+(?:\"[^\"]*\"|'[^']*'))?\s*\)")
_REF_DEF = re.compile(r"^\s{0,3}\[[^\]]+\]:\s*(<[^>]*>|\S+)")
_HTML_ATTR = re.compile(r"""\b(?:href|src)\s*=\s*(?:"([^"]*)"|'([^']*)')""", re.IGNORECASE)
_EXTERNAL = re.compile(r"^(?:[a-zA-Z][a-zA-Z0-9+.\-]*:|//)")  # https:, mailto:, data:, //host


@dataclass(frozen=True)
class Link:
    source: str  # файл со ссылкой, относительно корня
    line: int
    target: str  # как написано в файле
    path: str  # куда ведёт, относительно корня (posix)


@dataclass(frozen=True)
class Problem:
    link: Link
    reason: str


def extract_links(text: str) -> list[tuple[int, str]]:
    """(номер строки, цель) всех ссылок вне блоков кода; внешние адреса и чистые якоря тоже возвращаются."""
    out: list[tuple[int, str]] = []
    fence: str | None = None
    for no, line in enumerate(text.splitlines(), 1):
        m = _FENCE.match(line)
        if m:
            mark = m.group(1)
            if fence is None:
                fence = mark[0] * len(mark)
                continue
            if mark[0] == fence[0] and len(mark) >= len(fence) and not line.strip()[len(mark):].strip():
                fence = None
                continue
        if fence is not None:
            continue
        bare = _INLINE_CODE.sub(lambda c: " " * len(c.group(0)), line)
        for m in _INLINE_LINK.finditer(bare):
            out.append((no, m.group(1)))
        m = _REF_DEF.match(bare)
        if m:
            out.append((no, m.group(1)))
        for m in _HTML_ATTR.finditer(bare):
            out.append((no, m.group(1) if m.group(1) is not None else m.group(2)))
    return out


def resolve(target: str, source: Path, root: Path) -> str | None:
    """Путь относительно корня (posix) или None для внешних адресов и якорей на ту же страницу."""
    t = target.strip()
    if t.startswith("<") and t.endswith(">"):
        t = t[1:-1].strip()
    if not t or t.startswith("#") or _EXTERNAL.match(t):
        return None
    t = unquote(t.split("#", 1)[0].split("?", 1)[0])
    if not t:
        return None
    base = root if t.startswith("/") else source.parent
    full = (base / t.lstrip("/")).resolve()
    try:
        return full.relative_to(root.resolve()).as_posix() or "."
    except ValueError:
        return "../" + t  # выходит за пределы репозитория


def git_tracked(root: Path) -> set[str] | None:
    """Отслеживаемые файлы и их каталоги (posix, от корня); None — не git-репозиторий или git нет."""
    try:
        r = subprocess.run(["git", "-C", str(root), "ls-files", "-z"], capture_output=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if r.returncode != 0:
        return None
    tracked: set[str] = {"."}
    for raw in r.stdout.split(b"\0"):
        if not raw:
            continue
        rel = raw.decode("utf-8", errors="surrogateescape")
        tracked.add(rel)
        parts = rel.split("/")
        for i in range(1, len(parts)):
            tracked.add("/".join(parts[:i]))
    return tracked


def check(files: list[Path], root: Path = ROOT, use_git: bool = True) -> tuple[list[Link], list[Problem]]:
    root = root.resolve()
    tracked = git_tracked(root) if use_git else None
    links: list[Link] = []
    problems: list[Problem] = []
    for f in files:
        f = f if f.is_absolute() else root / f
        rel_source = f.resolve().relative_to(root).as_posix()
        for no, target in extract_links(f.read_text(encoding="utf-8")):
            path = resolve(target, f, root)
            if path is None:
                continue
            link = Link(rel_source, no, target, path)
            links.append(link)
            on_disk = not path.startswith("../") and (root / path).exists()
            if path.startswith("../"):
                problems.append(Problem(link, "ведёт за пределы репозитория"))
            elif not on_disk:
                problems.append(Problem(link, "нет такого файла"))
            elif tracked is not None and path not in tracked:
                problems.append(Problem(link, "файл есть на диске, но не в git — на GitHub его не будет"))
    return links, problems


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="битые относительные ссылки в документах сдачи")
    p.add_argument("files", nargs="*", help=f"файлы (по умолчанию: {', '.join(DEFAULT_FILES)})")
    p.add_argument("--root", default=str(ROOT), help="корень репозитория")
    p.add_argument("--no-git", action="store_true", help="не сверять с git, только наличие на диске")
    p.add_argument("--pending", action="append", default=[], metavar="ПУТЬ",
                   help="путь от корня, который придёт из другой ветки: печатается отдельно и не считается битым")
    args = p.parse_args(argv)
    root = Path(args.root).resolve()
    names = args.files or list(DEFAULT_FILES)
    files = []
    for name in names:
        path = Path(name) if Path(name).is_absolute() else root / name
        if not path.is_file():
            print(f"нет файла для проверки: {name}", file=sys.stderr)
            return 2
        files.append(path)
    links, problems = check(files, root, use_git=not args.no_git)
    pending = {x.strip("/") for x in args.pending}
    broken = [pr for pr in problems if pr.link.path not in pending]
    waiting = [pr for pr in problems if pr.link.path in pending]
    for pr in broken:
        print(f"{pr.link.source}:{pr.link.line}: {pr.link.target} → {pr.link.path}: {pr.reason}")
    for pr in waiting:
        print(f"{pr.link.source}:{pr.link.line}: {pr.link.target} → ожидается из другой ветки ({pr.reason})")
    uniq = len({pr.link.path for pr in broken})
    print(f"Проверено ссылок: {len(links)} в {len(files)} файлах; битых: {len(broken)} (разных путей: {uniq})"
          + (f"; ожидаются: {len(waiting)}" if waiting else ""))
    return 1 if broken else 0


if __name__ == "__main__":
    raise SystemExit(main())
