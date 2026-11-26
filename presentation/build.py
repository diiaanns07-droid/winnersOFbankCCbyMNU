"""Сборка презентации STUPITS (№14): deck.html → PNG по слайдам → deck.pdf и deck.pptx.

    python presentation/build.py                         # только deck.html (данные из отчёта и metrics.json)
    python presentation/build.py --png --pdf --pptx      # плюс картинки слайдов, PDF и PowerPoint

Откуда числа:
* `--report` (по умолчанию reports/requirements.json) — блокеры, доля сверенных цитат, отклонённые, время;
* `presentation/metrics.json` — замеры №15/№17 (К1–К5, С1–С20, чистые ТЗ, стабильность, модели) и команда.
Чего нет — остаётся жёлтой плашкой «—»: в слайды не попадает ни одного выдуманного числа.
PNG и PDF рисует Chromium через Playwright (node), PPTX — python-pptx из тех же PNG.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from html import escape
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
TBD = '<span class="tbd">—</span>'


def e(v) -> str:
    return escape("" if v is None else str(v), quote=True)


def _pct(x) -> str:
    return f"{x * 100:.0f} %" if isinstance(x, (int, float)) else str(x)


def from_report(path: Path | None) -> dict:
    if not path or not path.is_file():
        return {}
    r = json.loads(path.read_text(encoding="utf-8"))
    run = r.get("run") or {}
    if str(run.get("provider", "")).lower() in ("mock", "fixture"):
        print(f"[!] {path}: отчёт mock — для слайдов не используется", file=sys.stderr)
        return {}
    fs = r.get("findings") or []
    crit = [f for f in fs if f.get("severity") == "critical"]
    crit.sort(key=lambda f: (int(f.get("priority") or 99), f.get("id", "")))
    items = []
    for f in crit[:5]:
        lines = sorted({ev.get("line_start") for ev in f.get("evidence") or [] if ev.get("line_start")})
        where = "строки " + ", ".join(map(str, lines[:4])) if lines else ""
        items.append(f'<div class="panel bk"><span class="id">{e(f.get("id"))}</span><div class="t">{e(f.get("title"))}'
                     f'<small>{e((f.get("problem") or "")[:170])}</small></div><span class="where">{e(where)}</span></div>')
    ok = total = 0
    for f in fs:
        for ev in f.get("evidence") or []:
            total += 1
            ok += ev.get("verified") in ("exact", "normalized", "fuzzy")
    models = ", ".join(run.get("models_used") or []) or run.get("model_requested", "")
    dur = run.get("duration_s")
    src = f"отчёт агента {path.name}: модель {models}" + (f", {dur / 60:.0f} мин" if dur else "") + \
          (f", коммит {run.get('commit', '')[:7]}" if run.get("commit") else "")
    return {"critical_count": str(len(crit)), "blockers": "".join(items),
            "quotes_verified": _pct(ok / total) if total else None,
            "rejected": str(len(r.get("rejected") or [])), "report_source": src}


def from_metrics(path: Path) -> dict:
    if not path.is_file():
        return {}
    m = json.loads(path.read_text(encoding="utf-8"))
    out = {k: m[k] for k in ("k_found", "s_found", "clean_fp", "stability", "v2_summary", "metrics_source") if m.get(k)}
    rows = []
    for row in m.get("models") or []:
        cells = [row.get(k, "—") for k in ("model", "k", "s", "findings", "time", "calls")]
        rows.append("<tr>" + "".join(f'<td{" class=mono" if i else ""}>{e(c)}</td>' for i, c in enumerate(cells)) + "</tr>")
    if rows:
        out["models_rows"] = "".join(rows)
    team = []
    for t in m.get("team") or []:
        ini = "".join(w[0] for w in str(t.get("name", "?")).split()[:2]).upper()
        team.append(f'<div class="panel mem"><div class="av">{e(ini)}</div><b>{e(t.get("name"))}</b><span>{e(t.get("role", ""))}</span></div>')
    if team:
        out["team"] = "".join(team)
    return out


def build_html(report: Path | None, metrics: Path) -> Path:
    data = {"models_rows": f'<tr><td colspan="6">{TBD} сравнение моделей — после замеров №15 и №17</td></tr>',
            "team": f'<div class="panel mem"><div class="av">ST</div><b>{TBD}</b><span>имена и роли — из presentation/metrics.json</span></div>',
            "blockers": f'<div class="panel bk"><span class="id">К</span><div class="t">{TBD} список появится после финального прогона агента</div><span></span></div>',
            "report_source": "финальный отчёт ещё не собран"}
    data.update({k: v for k, v in from_report(report).items() if v})
    data.update(from_metrics(metrics))
    src = (HERE / "deck.src.html").read_text(encoding="utf-8")
    html = re.sub(r"\{\{(\w+)\}\}", lambda mm: str(data.get(mm.group(1), TBD)), src)
    out = HERE / "deck.html"
    out.write_text(html, encoding="utf-8")
    left = html.count('class="tbd"')
    print(f"{out} (незаполненных мест: {left})")
    return out


def render_png(deck: Path) -> list[Path]:
    outdir = HERE / "out"
    outdir.mkdir(exist_ok=True)
    subprocess.run(["node", str(HERE / "render.cjs"), str(deck), str(outdir)], check=True)
    return sorted(outdir.glob("slide-*.png"))


def make_pdf(pngs: list[Path]) -> Path:
    from PIL import Image
    imgs = [Image.open(p).convert("RGB") for p in pngs]
    out = HERE / "deck.pdf"
    imgs[0].save(out, save_all=True, append_images=imgs[1:], resolution=144)
    print(out)
    return out


def make_pptx(pngs: list[Path], deck: Path) -> Path:
    from pptx import Presentation
    from pptx.util import Emu
    prs = Presentation()
    prs.slide_width, prs.slide_height = Emu(12192000), Emu(6858000)  # 16:9
    blank = prs.slide_layouts[6]
    titles = re.findall(r'<section class="slide" id="s\d+" data-title="([^"]*)"', deck.read_text(encoding="utf-8"))
    notes = _notes()
    for i, p in enumerate(pngs):
        s = prs.slides.add_slide(blank)
        s.shapes.add_picture(str(p), 0, 0, width=prs.slide_width, height=prs.slide_height)
        txt = notes.get(i + 1) or (titles[i] if i < len(titles) else "")
        if txt:
            s.notes_slide.notes_text_frame.text = txt
    out = HERE / "deck.pptx"
    prs.save(out)
    print(out)
    return out


def _notes() -> dict[int, str]:
    """Заметки докладчика: разделы «## Слайд N» из presentation/pitch.md (сценарий №17), если он есть."""
    p = HERE / "pitch.md"
    if not p.is_file():
        return {}
    out: dict[int, str] = {}
    cur = None
    for line in p.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^#+\s*Слайд\s+(\d+)", line, re.I)
        if m:
            cur = int(m.group(1))
            out[cur] = ""
        elif cur:
            out[cur] += line + "\n"
    return {k: v.strip() for k, v in out.items() if v.strip()}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--report", default=str(ROOT / "reports" / "requirements.json"))
    ap.add_argument("--metrics", default=str(HERE / "metrics.json"))
    ap.add_argument("--png", action="store_true")
    ap.add_argument("--pdf", action="store_true")
    ap.add_argument("--pptx", action="store_true")
    a = ap.parse_args()
    deck = build_html(Path(a.report), Path(a.metrics))
    if a.png or a.pdf or a.pptx:
        pngs = render_png(deck)
        if a.pdf:
            make_pdf(pngs)
        if a.pptx:
            make_pptx(pngs, deck)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
