"""Демонстрация №14 на официальном кейсе BCC-HUB (requirements.md: части A и B).

    curl -sSfLo /tmp/requirements.md https://raw.githubusercontent.com/BCC-HUB/ai-requirements-validator-task/928c1aa364265426105b69ba7a3444eac11b22db/docs/requirements.md
    python tests/p14/demo_p14_case.py /tmp/requirements.md /tmp/p14-demo

Создаёт в OUT_DIR:
  requirements.md.annotated.pdf — производная PDF-копия Markdown с выделениями К1–К5;
  requirements.pdf               — чистая PDF-версия кейса (вход для PDF-режима);
  requirements.annotated.pdf     — аннотированная копия этого PDF (блоки и fragments как от №02);
  *.png                          — отрисовка страниц с выделениями;
  demo_summary.json              — размещения, verify_export и хеши.

Отчёт демо собран вручную по дефектам К1–К5 из docs/task-analysis.md, без обращения к модели.
Он показывает экспорт, а не качество ревью.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
for p in (HERE.parents[1] / "src", HERE):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import pymupdf  # noqa: E402

import p14_fixtures as fx  # noqa: E402
from bcc_review.exports.pdf import MANIFEST_NAME, export_pdf, render_page_png, verify_export  # noqa: E402

# (ID, серьёзность, вид, заголовок, последствие, вопрос, [(роль, строка Markdown, цитата)], witness)
CASE = [
    ("K-01", "critical", "contradiction", "Критерий приёмки №2 противоречит Ф-2",
     "покупка 31.01 23:58 попадёт в разные месяцы у разработчика и тестировщика",
     "По какой дате и в каком часовом поясе относить покупку к месяцу: совершения или проведения?",
     [("a", 38, "Месяц определяется по дате совершения покупки в Алматы"), ("b", 64, "Февральский счётчик вырос на 4 000 ₸")],
     {"input": "покупка 31 января 23:58, проведена 1 февраля 00:03 по Алматы", "outcome_a": "январский счётчик", "outcome_b": "февральский счётчик"}),
    ("K-02", "critical", "contradiction", "Ф-3 противоречит Ф-4 при смене порога",
     "второй push в месяце то запрещён, то обязателен",
     "Если push в этом месяце уже был, а порог изменили, отправлять ли второй push?",
     [("a", 39, "На карту приходится максимум один такой push за календарный месяц"),
      ("b", 40, "следующее достижение вызывает push независимо от истории предыдущей настройки")],
     {"input": "push уже отправлен в марте, порог повышен, расходы снова достигли порога", "outcome_a": "push не отправляется", "outcome_b": "push отправляется"}),
    ("K-03", "major", "contradiction", "Неверная сумма в API описана двумя способами",
     "клиент API не знает, ждать 400 или 200 с result=ERROR",
     "Какой HTTP-код и тело возвращать при сумме вне 1 000–1 000 000 ₸?",
     [("a", 163, "Ответ в случае, если параметры запроса заполнены неверно"), ("b", 171, '{"result":"ERROR","message":"Проверьте сумму"}')],
     {"input": "amount=999", "outcome_a": "400 Bad request", "outcome_b": "200 и result=ERROR"}),
    ("K-04", "major", "incompleteness", "Нет метода чтения настроек и суммы за месяц",
     "экран «Расходы → Уведомления» нечем заполнить",
     "Какой метод возвращает текущий порог, переключатель и сумму за месяц?",
     [("evidence", 52, "Приложение читает и сохраняет настройки"), ("evidence", 103, "Функциональные требования: чтение порога")], None),
    ("K-05", "critical", "ambiguity", "«Проведённая покупка» и событие процессинга не определены",
     "холд или клиринг дают разные суммы и разное время push",
     "Что считается проведённой покупкой: авторизация или клиринг? Какой состав у события?",
     [("evidence", 38, "В расходы входят проведённые покупки"), ("evidence", 46, "в течение минуты после получения события")], None),
    ("K-06", "minor", "incompleteness", "Prod URL не заполнен",
     "нельзя проверить метод на продуктиве",
     "Каков Request URL для Prod?",
     [("evidence", 108, "Prod: —")], None),
]


def _finding(kid, sev, kind, title, impact, evidence, witness, status="confirmed"):
    f = fx._finding(kid, sev, title, [e for _, e in evidence], kind=kind, criterion=kind, impact=impact,
                    scope="set" if witness else "requirement", req_ids=[], status=status,
                    blocked_decision=title, recommendation="уточнить требование до начала разработки")
    if witness:
        f["witness"] = dict(witness, evidence_a=evidence[0][1], evidence_b=evidence[1][1])
    return f


def _fill(rep: dict, find) -> dict:
    rep["requirements"], rep["questions"] = [], []
    for kid, sev, kind, title, impact, q, ev, w in CASE:
        evs = [(role, find(line, quote)) for role, line, quote in ev]
        rep["findings"].append(_finding(kid, sev, kind, title, impact, evs, w, "needs_review" if kid == "K-06" else "confirmed"))
        rep["questions"].append({"id": "Q" + kid[1:], "finding_ids": [kid], "prompt": q, "options": [], "affected_req_ids": []})
    return rep


def _team_reader(kind: str):
    """Ридер движка (контракт v1) или None, если пакет без runtime."""
    try:
        if kind == "pdf":
            from bcc_review.runtime.fallback.pdf_reader import read_pdf as reader
        else:
            from bcc_review.runtime.fallback.text_reader import read_text as reader
    except ImportError:
        return None
    return reader


def md_case_report(md: Path) -> dict:
    reader = _team_reader("md")
    if reader:  # блоки с loc.map — точная привязка по колонкам исходника
        doc = reader(md)
        blocks = doc["blocks"]
    else:
        blocks = fx.md_blocks(md.read_text(encoding="utf-8"))
    rep = fx._skeleton(fx.sha256(md), "Уведомление о расходах по карте", "markdown", blocks)

    def find(line: int, quote: str) -> dict:
        hits = [e for b in blocks if b["loc"]["line_start"] <= line <= b["loc"]["line_end"] and (e := fx.ev_loose(b, quote))]
        if len(hits) != 1:
            raise SystemExit(f"строка {line}: цитата {quote!r} в {len(hits)} блоках")
        return hits[0]

    return _fill(rep, find)


def clean_pdf_from_markdown(md: Path, out: Path) -> Path:
    """Чистая PDF-версия кейса: наша вёрстка без аннотаций и вложений (вход для PDF-режима)."""
    rep = fx.report_for(md, "md")
    rep["findings"] = []
    tmp = out.with_suffix(".tmp.pdf")
    export_pdf(rep, md, tmp)
    with pymupdf.open(tmp) as d:
        for page in d:
            for a in list(page.annots()):
                page.delete_annot(a)
        d.embfile_del(MANIFEST_NAME)
        d.save(out, garbage=4, deflate=True)
    tmp.unlink()
    return out


def pdf_case_report(pdf: Path) -> dict:
    reader = _team_reader("pdf")
    blocks = reader(pdf)["blocks"] if reader else fx.extract_blocks(pdf)
    rep = fx._skeleton(fx.sha256(pdf), "Уведомление о расходах по карте (PDF)", "pdf", blocks)

    def find(_line: int, quote: str) -> dict:
        hits = [e for b in blocks if (e := fx.ev_loose(b, quote))]
        if len(hits) != 1:
            raise SystemExit(f"цитата должна быть ровно в одном блоке PDF: {quote!r} → {len(hits)}")
        return hits[0]

    return _fill(rep, find)


def main(md_path: str, out_dir: str) -> int:
    md, out = Path(md_path), Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    summary: dict = {}

    rep_md = md_case_report(md)
    (out / "requirements.md.report.json").write_text(json.dumps(rep_md, ensure_ascii=False, indent=1), encoding="utf-8")
    r1 = export_pdf(rep_md, md, out / "requirements.md.annotated.pdf")
    summary["markdown"] = {**r1.summary(), "verify": verify_export(r1.output_path, md, rep_md),
                           "placements": [(p.finding_id, p.role, p.status, p.page, len(p.rects), p.reason) for p in r1.placements]}

    pdf = clean_pdf_from_markdown(md, out / "requirements.pdf")
    rep_pdf = pdf_case_report(pdf)
    (out / "requirements.pdf.report.json").write_text(json.dumps(rep_pdf, ensure_ascii=False, indent=1), encoding="utf-8")
    sha_before = fx.sha256(pdf)
    r2 = export_pdf(rep_pdf, pdf, out / "requirements.annotated.pdf")
    summary["pdf"] = {**r2.summary(), "verify": verify_export(r2.output_path, pdf, rep_pdf),
                      "source_sha_unchanged": fx.sha256(pdf) == sha_before,
                      "placements": [(p.finding_id, p.role, p.status, p.page, len(p.rects), p.reason) for p in r2.placements]}

    for res, key, stem in ((r1, "markdown", "md"), (r2, "pdf", "pdf")):
        pages = sorted({p.page for p in res.placements if p.page})
        summary[key]["png"] = [str(render_page_png(res.output_path, n, out / f"{stem}_page{n}.png", dpi=110)) for n in pages]
    (out / "demo_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(json.dumps({k: {"ok": v["verify"]["ok"], "highlights": v["highlights"], "notes": v["notes"],
                          "skipped": v["skipped"], "pages": v["pages"]} for k, v in summary.items()}, ensure_ascii=False))
    return 0 if all(v["verify"]["ok"] for v in summary.values()) else 1


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__)
        raise SystemExit(2)
    raise SystemExit(main(sys.argv[1], sys.argv[2]))
