"""Сквозная проверка PDF-экспорта №14 на комплекте релиза (release/) с независимым чтением.

    python tests/p14/release_check.py                       # release/input/requirements.pdf + offline-отчёт
    python tests/p14/release_check.py --source release/input/requirements.md \\
        --report release/reports/offline/requirements.json --out out/p14-release/requirements.md.pdf

1. Вызывается настоящий ``write_pdf`` (через ``export_pdf``) — тот же, что у ``--export pdf``.
2. Готовый файл перечитывается без MuPDF: аннотации — ``pypdf`` (``/NM``, ``/QuadPoints``,
   ``/Contents``), текст под выделением — PDFium (знаки, центр которых внутри четырёхугольника).
3. Для PDF-входа место сверяется с координатами слов ридера №02 из самого отчёта
   (``loc.page`` + ``loc.fragments`` блока). Для Markdown-входа сверяется номер строки
   источника, напечатанный на полях у выделенной строки, со строками блока.
4. Печатается перечень «ID → страница → выделенный фрагмент → причина пропуска» и покрытие с
   точным знаменателем: число опор, пересчитанное из отчёта, а не из манифеста экспорта.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

DEFAULT_SOURCE = ROOT / "release" / "input" / "requirements.pdf"
DEFAULT_REPORT = ROOT / "release" / "reports" / "offline" / "requirements_pdf.json"
DEFAULT_OUT = ROOT / "out" / "p14-release" / "requirements.annotated.pdf"
MANIFEST = "bcc_review_pdf_export.json"


def _norm(t: str) -> str:
    return re.sub(r"[\s|]+", "", unicodedata.normalize("NFKC", t))


def _sha(p: Path) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def anchors_from_report(rep: dict[str, Any]) -> list[tuple[str, str, int, str, int, int]]:
    """Опоры, которые обязан разместить экспорт: на замечание — уникальные (блок, начало, конец)
    из witness и evidence. Считается по отчёту, независимо от экспорта."""
    out = []
    for f in rep.get("findings") or []:
        seen: set[tuple[Any, Any, Any]] = set()
        w = f.get("witness") or {}
        items = [w.get("evidence_a"), w.get("evidence_b")] + list(f.get("evidence") or [])
        for e in items:
            if not isinstance(e, dict):
                continue
            key = (e.get("block_id"), e.get("start"), e.get("end"))
            if key in seen:
                continue
            seen.add(key)
            out.append((f["id"], str(e["block_id"]), len(seen), str(e.get("quote")), int(e["start"]), int(e["end"])))
        if not seen:
            out.append((f["id"], "", 0, "", 0, 0))
    return out


def _quad_inside(px: float, py: float, q: list[tuple[float, float]], tol: float = 0.5) -> bool:
    ring = [q[0], q[1], q[3], q[2]]  # ul, ur, lr, ll
    area = sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(ring, ring[1:] + ring[:1]))
    s = 1.0 if area >= 0 else -1.0
    return all(s * ((b[0] - a[0]) * (py - a[1]) - (b[1] - a[1]) * (px - a[0])) >= -tol
               for a, b in zip(ring, ring[1:] + ring[:1]))


def read_independently(pdf: Path) -> dict[str, Any]:
    """Аннотации (pypdf) и знаки страниц (PDFium) без MuPDF."""
    import pypdf
    import pypdfium2 as pdfium

    rd = pypdf.PdfReader(str(pdf))
    pd = pdfium.PdfDocument(str(pdf))
    pages = []
    for i, page in enumerate(rd.pages):
        tp = pd[i].get_textpage()
        chars = [(tp.get_text_range(k, 1), tp.get_charbox(k, loose=True)) for k in range(tp.count_chars())]
        annots = []
        for ref in page.get("/Annots") or []:
            a = ref.get_object()
            rec = {"subtype": str(a.get("/Subtype")), "nm": str(a.get("/NM", "")), "contents": str(a.get("/Contents", ""))}
            if rec["subtype"] == "/Highlight":
                qp = [float(v) for v in a["/QuadPoints"]]
                rec["quads"] = [[(qp[j], qp[j + 1]), (qp[j + 2], qp[j + 3]), (qp[j + 4], qp[j + 5]), (qp[j + 6], qp[j + 7])]
                                for j in range(0, len(qp), 8)]
                rec["under"] = ["".join(c for c, (x0, y0, x1, y1) in chars if _quad_inside((x0 + x1) / 2, (y0 + y1) / 2, q))
                                for q in rec["quads"]]
                rec["chars"] = [((x0 + x1) / 2, (y0 + y1) / 2) for q in rec["quads"]
                                for c, (x0, y0, x1, y1) in chars
                                if not c.isspace() and _quad_inside((x0 + x1) / 2, (y0 + y1) / 2, q)]
            annots.append(rec)
        cb = [float(v) for v in page.cropbox]
        pages.append({"annots": annots, "cropbox": cb, "rotate": int(page.get("/Rotate", 0) or 0), "chars": chars})
    attach = rd.attachments.get(MANIFEST)
    manifest = json.loads(attach[0]) if attach else None
    return {"pages": pages, "manifest": manifest}


def _gutter_labels(page: dict[str, Any]) -> list[tuple[float, int]]:
    rows: dict[float, list[tuple[float, str]]] = {}
    for c, (x0, y0, x1, y1) in page["chars"]:
        if x1 < 52 and c.isdigit():
            rows.setdefault(round((y0 + y1) / 2), []).append((x0, c))
    return [(ly, int("".join(c for _, c in sorted(v)))) for ly, v in rows.items()]


def _gutter_line(pages: list[dict[str, Any]], pno: int, y: float) -> int | None:
    """Строка Markdown для выделенной строки на высоте y: ближайший номер на левом поле (x < 52 pt)
    на той же высоте или выше. У продолжения перенесённой строки своего номера нет, а после разрыва
    страницы номер остаётся на предыдущей странице (самый нижний)."""
    above = [(ly, n) for ly, n in _gutter_labels(pages[pno]) if ly >= y - 3]  # PDF: ось y вверх
    if above:
        return min(above)[1]
    for prev in range(pno - 1, -1, -1):
        labels = _gutter_labels(pages[prev])
        if labels:
            return min(labels)[1]
    return None


def check(source: Path, report: Path, out: Path, *, rep: dict[str, Any] | None = None) -> dict[str, Any]:
    from bcc_review.exports.pdf import export_pdf, verify_export

    rep = rep if rep is not None else json.loads(Path(report).read_text(encoding="utf-8"))
    sha_before = _sha(source)
    out.parent.mkdir(parents=True, exist_ok=True)
    res = export_pdf(rep, source, out)  # настоящий write_pdf
    ind = read_independently(out)
    blocks = {b["id"]: b for b in rep["document"]["blocks"]}
    want = anchors_from_report(rep)
    by_nm = {a["nm"]: (pno + 1, a) for pno, p in enumerate(ind["pages"]) for a in p["annots"] if a["nm"]}
    is_pdf = (rep["document"].get("format") or "").lower() == "pdf"
    rows = []
    for p in ind["manifest"]["placements"]:
        e_ok = pos_ok = None
        under = raw = ""
        names = [n for n in p["annot_names"] if not n.endswith(":label")]
        if p["status"] == "highlight":
            pg, a = by_nm[names[0]]
            under = " ⏎ ".join(t.strip() for t in a["under"])
            raw = "".join(a["under"])
            b = blocks[p["block_id"]]
            e_ok = b["text"][p["start"]:p["end"]] == p["quote"]  # дальше: склейка всех частей опоры
            if is_pdf:
                page = ind["pages"][pg - 1]
                x0, y0, x1, y1 = page["cropbox"]
                assert page["rotate"] == 0, "позиционная проверка написана для страниц без /Rotate"
                frs = [f for f in b["loc"].get("fragments") or [] if f["start"] < p["end"] and f["end"] > p["start"]]
                boxes = [(x0 + f["rect"][0] - 1.5, y1 - f["rect"][3] - 1.5, x0 + f["rect"][2] + 1.5, y1 - f["rect"][1] + 1.5)
                         for f in frs]
                pos_ok = bool(a["chars"]) and pg == b["loc"]["page"] and all(
                    any(bx0 <= cx <= bx1 and by0 <= cy <= by1 for bx0, by0, bx1, by1 in boxes) for cx, cy in a["chars"])
            else:
                ys = [sum(pt[1] for pt in q) / 4 for q in a["quads"]]
                nums = {_gutter_line(ind["pages"], pg - 1, y) for y in ys} - {None}
                lo, hi = b["loc"]["line_start"], b["loc"]["line_end"]
                pos_ok = bool(nums) and all(lo <= n <= hi for n in nums)
        elif p["status"] == "note":
            pg, a = by_nm[names[0]]
            e_ok = a["contents"].startswith("БЕЗ ТОЧНОЙ ПРИВЯЗКИ:")
        rows.append({"id": p["finding_id"], "role": p["role"], "part": p["part"], "page": p["page"], "status": p["status"],
                     "quote": p["quote"], "under": under, "under_raw": raw, "content_ok": e_ok, "position_ok": pos_ok, "reason": p["reason"]})
    # опора может разойтись по страницам: текст сверяется по склейке её частей в порядке страниц
    for key in {(r["id"], r["role"], r["part"]) for r in rows if r["status"] == "highlight"}:
        parts = sorted((r for r in rows if (r["id"], r["role"], r["part"]) == key and r["status"] == "highlight"),
                       key=lambda r: r["page"])
        joined = _norm("".join(r["under_raw"] for r in parts))
        ok = all(r["content_ok"] for r in parts) and joined == _norm(parts[0]["quote"] or "")
        for r in parts:
            r["content_ok"] = ok
            r["pieces"] = len(parts)
    anchors_placed = {(r["id"], r["role"], r["part"]) for r in rows}
    hl = [r for r in rows if r["status"] == "highlight"]
    coverage = {
        "findings": len(rep.get("findings") or []),
        "anchors_in_report": len(want),
        "anchors_in_export": len(anchors_placed),
        "highlighted_anchors": len({(r["id"], r["role"], r["part"]) for r in hl}),
        "highlights": len(hl),
        "content_ok": sum(1 for r in hl if r["content_ok"]),  # по выделениям (у опоры на 2 стр. — 2)
        "position_ok": sum(1 for r in hl if r["position_ok"]),
        "anchors_split_across_pages": sum(1 for r in hl if r.get("pieces", 1) > 1) // 2,
        "notes": sum(1 for r in rows if r["status"] == "note"),
        "skipped": sum(1 for r in rows if r["status"] == "skipped"),
    }
    import pypdf

    pages_src = len(pypdf.PdfReader(str(source)).pages) if is_pdf else None
    return {
        "source": str(source), "source_sha256": sha_before, "source_sha256_after": _sha(source),
        "report": str(report), "output": str(out), "output_sha256": _sha(out),
        "pages_source": pages_src, "pages_output": len(ind["pages"]),
        "coverage": coverage, "rows": rows, "warnings": res.warnings,
        "verify_export": verify_export(out, source, rep),
    }


def table(result: dict[str, Any]) -> str:
    lines = ["| ID | роль/часть | стр. | выделено (PDFium под /QuadPoints) | текст | место | причина пропуска |",
             "| :--- | :--- | ---: | :--- | :---: | :---: | :--- |"]
    mark = {True: "да", False: "НЕТ", None: "—"}
    for r in result["rows"]:
        frag = r["under"] if r["status"] == "highlight" else f"[{r['status']}] «{(r['quote'] or '')[:60]}»"
        lines.append(f"| {r['id']} | {r['role']} {r['part']} | {r['page'] or '—'} | {frag.replace('|', '¦')[:110]} | "
                     f"{mark[r['content_ok']]} | {mark[r['position_ok']]} | {r['reason'] or '—'} |")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    ap.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    a = ap.parse_args(argv)
    result = check(a.source, a.report, a.out)
    a.out.with_suffix(".check.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    a.out.with_suffix(".check.md").write_text(table(result) + "\n", encoding="utf-8")
    c = result["coverage"]
    print(table(result))
    print(json.dumps({"coverage": c, "pages": [result["pages_source"], result["pages_output"]],
                      "source_sha_unchanged": result["source_sha256"] == result["source_sha256_after"],
                      "verify_export_ok": result["verify_export"]["ok"], "warnings": result["warnings"]}, ensure_ascii=False))
    ok = (c["anchors_in_report"] == c["anchors_in_export"] and c["content_ok"] == c["highlights"]
          and c["position_ok"] == c["highlights"] and result["verify_export"]["ok"]
          and result["source_sha256"] == result["source_sha256_after"]
          and (result["pages_source"] in (None, result["pages_output"])))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
