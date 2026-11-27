"""Есть ли готовые сборки (колёса) всех зафиксированных зависимостей для каждой ОС и версии Python.

    python scripts/check_wheels.py                 # constraints.txt, все цели
    python scripts/check_wheels.py --python 3.12   # одна версия Python

Без колеса pip собирает пакет из исходников, а на машине жюри нет компилятора (Rust, C) — установка падает.
Скачивать ничего не нужно: список файлов каждой версии берётся из JSON API PyPI, совместимость — по меткам колеса
(как у pip). Код выхода 1, если для какой-то цели нет колеса; печатается, чего не хватает.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from packaging import tags
from packaging.specifiers import SpecifierSet
from packaging.utils import parse_wheel_filename

ROOT = Path(__file__).resolve().parents[1]

# Цели: машина жюри (Windows, Mac Intel и Apple Silicon, Linux) и Docker на Mac с M-процессором (Linux arm64).
_MANYLINUX = [f"manylinux_2_{n}" for n in range(35, 16, -1)] + ["manylinux2014"]
TARGETS = {
    "Windows x64": ["win_amd64"],
    "macOS Apple Silicon": list(tags.mac_platforms((14, 0), "arm64")),
    "macOS Intel": list(tags.mac_platforms((13, 0), "x86_64")),
    "Linux x64": [f"{m}_x86_64" for m in _MANYLINUX],
    "Linux arm64 (Docker на Mac M)": [f"{m}_aarch64" for m in _MANYLINUX],
}
PYTHONS = ["3.11", "3.12", "3.13", "3.14"]


def pins(path: Path) -> list[tuple[str, str]]:
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        m = re.fullmatch(r"([A-Za-z0-9_.\-]+)(?:\[[^\]]*\])?==([0-9][A-Za-z0-9.\-+]*)", line)
        if m:
            out.append((m.group(1), m.group(2)))
    return out


def release_files(name: str, version: str) -> dict:
    url = f"https://pypi.org/pypi/{name}/{version}/json"
    with urllib.request.urlopen(url, timeout=60) as r:  # noqa: S310 — адрес PyPI фиксирован
        data = json.load(r)
    return {"requires_python": data["info"].get("requires_python") or "",
            "wheels": [u["filename"] for u in data.get("urls", []) if u["filename"].endswith(".whl")]}


def supported(py: str, platforms: list[str]) -> set:
    ver = tuple(int(x) for x in py.split("."))
    return set(tags.cpython_tags(ver, platforms=platforms)) | set(tags.compatible_tags(ver, platforms=platforms))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--constraints", default=str(ROOT / "constraints.txt"))
    ap.add_argument("--python", action="append", help="версия Python (можно несколько); по умолчанию 3.11–3.14")
    a = ap.parse_args(argv)
    pyvers = a.python or PYTHONS
    req = pins(Path(a.constraints))
    if not req:
        print(f"В {a.constraints} нет строк вида пакет==версия", file=sys.stderr)
        return 2
    with ThreadPoolExecutor(max_workers=8) as ex:
        info = dict(zip(req, ex.map(lambda p: release_files(*p), req)))
    want = {(t, py): supported(py, plats) for t, plats in TARGETS.items() for py in pyvers}
    missing: list[str] = []
    for (name, ver), rel in info.items():
        wheel_tags = set()
        for fn in rel["wheels"]:
            try:
                wheel_tags |= set(parse_wheel_filename(fn)[3])
            except Exception:  # noqa: BLE001 — нестандартное имя файла пропускаем
                continue
        spec = SpecifierSet(rel["requires_python"]) if rel["requires_python"] else SpecifierSet()
        for (target, py), sup in want.items():
            if not spec.contains(py):
                missing.append(f"{name}=={ver}: Python {py} не поддерживается ({rel['requires_python']}) — {target}")
            elif not (wheel_tags & sup):
                missing.append(f"{name}=={ver}: нет колеса для {target}, Python {py}")
    print(f"Пакетов: {len(req)}; целей: {len(TARGETS)} ОС × Python {', '.join(pyvers)}")
    if missing:
        print("Нет готовой сборки — pip будет собирать из исходников:")
        for m in missing:
            print("  " + m)
        return 1
    print("Колёса есть для всех пакетов на всех целях: " + "; ".join(TARGETS))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
