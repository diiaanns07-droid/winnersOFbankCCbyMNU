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
sys.path.insert(0, str(ROOT / "src"))
TBD = '<span class="tbd">—</span>'


def e(v) -> str:
    return escape("" if v is None else str(v), quote=True)


def tx(v) -> str:
    """Текст модели: «L038» → «строка 38» (как в HTML-отчёте), затем экранирование."""
    try:
        from bcc_review.v2.render.html import tx as html_tx
        return html_tx(v)
    except Exception:  # noqa: BLE001
        return e(v)


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
                     f'<small>{tx(_clip(f.get("problem") or "", 170))}</small></div><span class="where">{e(where)}</span></div>')
    ok = total = 0
    for f in fs:
        for ev in f.get("evidence") or []:
            total += 1
            ok += ev.get("verified") in ("exact", "normalized", "fuzzy")
    models = ", ".join(run.get("models_used") or []) or run.get("model_requested", "")
    dur = run.get("duration_s")
    calls = run.get("calls") or {}
    when = ("ответы модели из кэша живого прогона" if calls.get("cached") and not calls.get("total")
            else (f"{dur / 60:.0f} мин" if dur else ""))
    src = f"отчёт агента {path.name}: модель {models}" + (f", {when}" if when else "") + \
          (f", коммит {run.get('commit', '')[:7]}" if run.get("commit") else "")
    n = len(crit)
    title = (f"{n} {_plural(n, 'блокер', 'блокера', 'блокеров')}, <em>которые агент нашёл сам</em>" if n
             else "Блокеров нет")
    return {"critical_count": str(n), "blockers_title": title, "blockers": "".join(items),
            "quotes_verified": _pct(ok / total) if total else None,
            "rejected": str(len(r.get("rejected") or [])), "report_source": src}


def _tone(value: str, bad: bool, warn: bool = False) -> str:
    """Цвет числа по смыслу: плохое — красным, спорное — оранжевым, иначе цвет карточки."""
    cls = "bad" if bad else ("warn" if warn else "")
    return f'<span class="{cls}">{e(value)}</span>' if cls else e(value)


def _clip(s: str, n: int) -> str:
    s = " ".join(str(s).split())
    return s if len(s) <= n else s[:n].rsplit(" ", 1)[0] + "…"


def _plural(n: int, one: str, few: str, many: str) -> str:
    n = abs(int(n))
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def _dur(s) -> str:
    if not isinstance(s, (int, float)):
        return "—"
    s = int(round(s))
    return f"{s} с" if s < 60 else f"{s // 60} мин {s % 60:02d} с"


def _model_name(row: dict) -> str:
    m = str(row.get("model") or "")
    prov = row.get("provider") or ""
    name = {"opus": "Claude Opus", "sonnet": "Claude Sonnet", "haiku": "Claude Haiku"}.get(m.lower(), m or "—")
    if prov == "claude_cli":
        name += " (CLI)"
    return name


def from_evaluation(root: Path) -> dict:
    """Числа №15: история замеров официального документа и корпус. Только то, что посчитал счётчик."""
    out: dict = {}
    hist = root / "evaluation" / "v2" / "history.jsonl"
    rows = []
    if hist.is_file():
        for line in hist.read_text(encoding="utf-8").splitlines():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    v1 = next((r for r in rows if r.get("version") == "v1"), None)
    v2 = [r for r in rows if r.get("version") == "v2" and r.get("status") == "complete"]
    strong = [r for r in v2 if "opus" in str(r.get("model", "")).lower()] or \
             [r for r in v2 if "sonnet" in str(r.get("model", "")).lower()] or v2
    best = strong[-1] if strong else None
    if best:
        qt, qm = best.get("quotes_total") or 0, best.get("quotes_missing") or 0
        cost = best.get("cost_usd")
        out.update({
            "k_found": f"{best['K']}/5", "k_crit": str(best.get("K_as_critical", "—")), "s_found": f"{best['C']}/20",
            "crit_false": _tone(str(best.get("critical_false", "—")), bool(best.get("critical_false"))),
            "quotes": f"{(qt - qm) * 100 // qt} %" if qt else "—",
            "official_time": _dur(best.get("duration_s")), "official_calls": str(best.get("calls") or "—"),
            "official_cost": f"≈ ${cost:.2f}" if isinstance(cost, (int, float)) else "стоимость не замерена",
            "official_source": f"{_model_name(best)}; замер №15 {best.get('at', '')}: «{best.get('label', '')}»",
        })
    # модели: последний полный замер по каждой модели
    per: dict = {}
    for r in v2:
        per[(r.get("provider"), r.get("model"))] = r
    if per:
        order = sorted(per.values(), key=lambda r: ["opus", "sonnet", "haiku"].index(str(r.get("model")).lower())
                       if str(r.get("model")).lower() in ("opus", "sonnet", "haiku") else 9)
        out["models_rows"] = "".join(
            f"<tr><td>{e(_model_name(r))}</td><td class=mono>{r['K']}/5</td><td class=mono>{r['C']}/20</td>"
            f"<td class=mono>{r.get('findings', '—')}</td><td class=mono>{e(_dur(r.get('duration_s')))}</td>"
            f"<td class=mono>{r.get('calls') or '—'}</td></tr>" for r in order)
        out["models_source"] = "Официальный документ, счётчик №15 (evaluation/v2/history.jsonl); статус каждого прогона — complete."
    # было → стало
    if v1 and best:
        def row(lbl, a, b, better: bool | None = True):
            cls = "new" if better else ("mixed" if better is None else "worse")
            return f'<tr><td>{e(lbl)}</td><td class="old">{e(a)}</td><td class="{cls}">{e(b)}</td></tr>'

        def num(r, k):
            v = r.get(k)
            return v if isinstance(v, (int, float)) else None

        def better(k, more_is_better):
            a, b = num(v1, k), num(best, k)
            return None if a is None or b is None else (b >= a if more_is_better else b <= a)
        rws = [row("Ключевые блокеры К1–К5", f"{v1['K']}/5", f"{best['K']}/5", better("K", True)),
               row("Существенные дефекты С1–С20", f"{v1['C']}/20", f"{best['C']}/20", better("C", True)),
               row("Дубли замечаний", str(v1.get("duplicates", "—")), str(best.get("duplicates", "—")), better("duplicates", False)),
               row("Английские слова в отчёте", str(v1.get("english", "—")), str(best.get("english", "—")), better("english", False)),
               row("Строк в отчёте", f"{v1.get('report_md_lines', 0):,}".replace(",", " "),
                   f"{best.get('report_md_lines', 0):,}".replace(",", " "), better("report_md_lines", False))]
        out["_v1v2_rows"] = rws
        out["v1v2_rows"] = "".join(rws)
        out["v1v2_source"] = (f"Официальный документ, один счётчик №15: v1 — «{v1.get('label', '')}» ({v1.get('at', '')}), "
                              f"v2 — «{best.get('label', '')}» ({best.get('at', '')}).")
    # корпус
    best_c = None
    for p in sorted((root / "evaluation" / "v2" / "corpus_results").glob("*/summary.json")):
        try:
            c = json.loads(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if "офлайн" in str(c.get("label", "")).lower() and best_c is not None:
            continue
        if best_c is None or "офлайн" in str(best_c.get("label", "")).lower() or str(c.get("at")) > str(best_c.get("at")):
            best_c = c
    if best_c:
        h = best_c.get("harness") or {}
        clean = best_c.get("clean") or {}
        alarms = h.get("clean_false_alarms", clean.get("findings"))
        prec = h.get("precision") or 0
        out.update({
            "corpus_recall": f"{h.get('tp', 0)}/{h.get('support', 28)}",
            "corpus_precision": _tone(f"{round(prec * 100)} %", prec < 0.5, prec < 0.8),
            "corpus_clean": _tone(str(alarms if alarms is not None else "—"), bool(alarms)),
            "corpus_source": f"Корпус evaluation/dev, строгий счётчик: «{best_c.get('label', '')}» ({best_c.get('at', '')}). "
                             f"v1 на том же корпусе: 0 из 28 и 44 тревоги на чистых.",
        })
        if out.get("_v1v2_rows"):  # v1 на корпусе — docs/plan-v2/ref/BCC-quality-08d3af5.md (bcc/eval-independent)
            worse_alarms = isinstance(alarms, (int, float)) and alarms > 44
            out["_v1v2_rows"].append(
                f'<tr><td>Корпус: заложенные дефекты / тревоги на 8 чистых ТЗ</td><td class="old">0 из 28 / 44</td>'
                f'<td class="{"mixed" if worse_alarms or alarms else "new"}">{h.get("tp", 0)} из {h.get("support", 28)} / '
                f'{e(alarms if alarms is not None else "—")}</td></tr>')
            out["v1v2_rows"] = "".join(out["_v1v2_rows"])
    return out


def from_metrics(path: Path) -> dict:
    if not path.is_file():
        return {}
    m = json.loads(path.read_text(encoding="utf-8"))
    out = {k: v for k, v in m.items() if isinstance(v, str) and v}  # любое поле слайдов можно задать вручную
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
            "blockers_title": f'{TBD} блокеров, <em>которые агент нашёл сам</em>',
            "stability_source": "Стабильность — 3 прогона подряд (замер №15).",
            "team": f'<div class="panel mem"><div class="av">ST</div><b>{TBD}</b><span>имена и роли — из presentation/metrics.json</span></div>',
            "blockers": f'<div class="panel bk"><span class="id">К</span><div class="t">{TBD} список появится после финального прогона агента</div><span></span></div>',
            "report_source": "финальный отчёт ещё не собран"}
    data.update({k: v for k, v in from_report(report).items() if v})
    data.update({k: v for k, v in from_evaluation(ROOT).items() if v and not k.startswith("_")})
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
        jpg = p.with_suffix(".jpg")  # JPEG вместо PNG: файл PPTX в 4–5 раз меньше, на экране разницы нет
        from PIL import Image
        Image.open(p).convert("RGB").save(jpg, quality=88, optimize=True)
        s.shapes.add_picture(str(jpg), 0, 0, width=prs.slide_width, height=prs.slide_height)
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
