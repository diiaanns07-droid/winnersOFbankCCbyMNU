"""Детерминированные фикстуры №14: синтетический PDF, блоки «как от №02», отчёты по контракту v1.

Сеть и модель не нужны. Тексты собственные, по мотивам учебного кейса (порог в ₸, REST API).
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

import pymupdf

ROOT = Path(__file__).resolve().parents[2]
FONT = ROOT / "src" / "bcc_review" / "exports" / "pdf_assets" / "NotoSans[wdth,wght].ttf"
EXAMPLE = ROOT / "contracts" / "examples" / "minimal_report.json"

# (поворот, CropBox, [(x, y_baseline, текст)])
PAGES: list[dict[str, Any]] = [
    {
        "rotate": 0,
        "crop": None,
        "lines": [
            (72, 100, "Требование Ф-1. Держатель карты задаёт порог 50 000 ₸ в приложении."),
            (72, 130, "Уведомление приходит при достижении порога."),
        ],
    },
    {
        "rotate": 0,
        "crop": None,
        "lines": [
            (72, 100, "Повтор: порог 50 000 ₸ встречается и на этой странице."),
            (72, 140, "Возврат уменьшает расходы месяца исходной покупки, а\nпереводы и снятие наличных исключаются из подсчёта."),
        ],
    },
    {"rotate": 90, "crop": None, "lines": [(72, 200, "Ответ API возвращает код 200 при ошибке суммы.")]},
    {
        "rotate": 270,
        "crop": (30, 40, 580, 700),
        "lines": [(80, 200, "Для чужой карты возвращается 404, как и для отсутствующей.")],
    },
    {"scan": True},
]
EXISTING_NOTE = "Комментарий коллеги: уточнить порог по умолчанию"
EXISTING_SQUARE = "Старая пометка рецензента"


def sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def build_pdf(path: Path) -> Path:
    doc = pymupdf.open()
    for spec in PAGES:
        page = doc.new_page(width=612, height=792)
        if spec.get("scan"):
            continue
        page.insert_font(fontname="noto", fontfile=str(FONT))
        for x, y, text in spec["lines"]:
            page.insert_text((x, y), text, fontname="noto", fontsize=11, lineheight=1.45)
    # «скан»: страница 5 — только картинка с текстом страницы 1, без текстового слоя
    pix = doc[0].get_pixmap(dpi=100, clip=pymupdf.Rect(60, 80, 560, 140))
    doc[4].insert_image(pymupdf.Rect(60, 80, 560, 140), pixmap=pix)
    # аннотации, которые были в документе до нас
    p1 = doc[0]
    a = p1.add_text_annot((560, 60), EXISTING_NOTE)
    a.set_info(title="Коллега", content=EXISTING_NOTE)
    a.update()
    sq = p1.add_rect_annot(pymupdf.Rect(60, 150, 220, 172))
    sq.set_info(title="Рецензент", content=EXISTING_SQUARE)
    sq.set_colors(stroke=(0, 0.4, 0.9))
    sq.update()
    for i, spec in enumerate(PAGES):
        if spec.get("crop"):
            doc[i].set_cropbox(pymupdf.Rect(*spec["crop"]))
        if spec.get("rotate"):
            doc[i].set_rotation(spec["rotate"])
    doc.save(path, garbage=3, deflate=True)
    doc.close()
    return path


def extract_blocks(path: Path) -> list[dict[str, Any]]:
    """Синтетический №02: абзац = текстовый блок MuPDF, fragment = строка (start/end/page/bbox)."""
    blocks: list[dict[str, Any]] = []
    n = 0
    with pymupdf.open(path) as doc:
        for page in doc:
            flags = pymupdf.TEXT_PRESERVE_LIGATURES | pymupdf.TEXT_PRESERVE_WHITESPACE
            for b in page.get_text("rawdict", flags=flags)["blocks"]:
                if b["type"] != 0:
                    continue
                text = ""
                frags = []
                for line in b["lines"]:
                    lt = "".join(ch["c"] for s in line["spans"] for ch in s["chars"]).strip()
                    if not lt:
                        continue
                    if text:
                        text += " "
                    start = len(text)
                    text += lt
                    frags.append({"start": start, "end": len(text), "rect": [round(v, 2) for v in line["bbox"]]})
                n += 1
                blocks.append(
                    {
                        "id": f"b{n:04d}",
                        "kind": "paragraph",
                        "section": ["Часть A"],
                        "text": text,
                        "loc": {"page": page.number + 1, "fragments": frags},
                    }
                )
    return blocks


def block_with(blocks: list[dict[str, Any]], needle: str, page: int) -> dict[str, Any]:
    for b in blocks:
        if needle in b["text"] and b["loc"].get("page") == page:
            return b
    raise KeyError((needle, page))


def ev(block: dict[str, Any], quote: str, nth: int = 0) -> dict[str, Any]:
    i = -1
    for _ in range(nth + 1):
        i = block["text"].index(quote, i + 1)
    return {"block_id": block["id"], "start": i, "end": i + len(quote), "quote": quote}


def ev_loose(block: dict[str, Any], quote: str) -> dict[str, Any] | None:
    """Как №07 из подсказки: цитата с любыми пробелами/переводами строк между словами →
    точная опора, где quote == block.text[start:end]."""
    import re

    m = re.search(r"\s+".join(map(re.escape, quote.split())), block["text"])
    if not m:
        return None
    return {"block_id": block["id"], "start": m.start(), "end": m.end(), "quote": m.group(0)}


def _skeleton(doc_id: str, title: str, fmt: str, blocks: list[dict[str, Any]]) -> dict[str, Any]:
    """Report v1: каркас берётся из contracts/examples/minimal_report.json (run, verdict, summary)."""
    requirement = {"id": "R-01", "source_id": "Ф-1", "text": "Держатель карты задаёт порог", "block_ids": [],
                   "evidence": [], "kind": "functional", "review_status": "reviewed", "review_reason": None}
    question = {"id": "Q-1", "finding_ids": ["F-01"], "prompt": "Какой порог действует по умолчанию?",
                "options": ["1 000 ₸", "уведомление выключено"], "affected_req_ids": ["R-01"]}
    if EXAMPLE.exists():
        rep = copy.deepcopy(json.loads(EXAMPLE.read_text(encoding="utf-8")))
        rep["run"].update({"source_sha256": doc_id, "agent_version": "p14-fixture", "status": "complete"})
        rep["document"] = {"id": doc_id, "title": title, "format": fmt, "blocks": blocks, "warnings": []}
        for k in ("checks", "findings", "facts", "coverage", "checklist", "test_cases", "decisions", "excluded", "rejected", "warnings"):
            rep[k] = []
        rep["requirements"], rep["questions"], rep["diff"] = [requirement], [question], None
        for side in ("development", "testing"):
            rep["verdict"][side]["finding_ids"] = []
        return rep
    return {
        "schema_version": "1.0",
        "run": {
            "source_sha256": doc_id,
            "agent_version": "p14-fixture",
            "provider": "mock",
            "model": "mock",
            "mode": "mock",
            "started_at": "2026-11-26T12:00:00+05:00",
            "finished_at": "2026-11-26T12:00:05+05:00",
            "calls": 0,
            "status": "complete",
        },
        "document": {"id": doc_id, "title": title, "format": fmt, "blocks": blocks, "warnings": []},
        "requirements": [requirement],
        "checks": [],
        "findings": [],
        "coverage": {},
        "questions": [question],
        "checklist": [],
        "test_cases": [],
        "decisions": [],
        "diff": None,
        "verdict": {"development": "not_ready", "testing": "not_ready", "first_actions": []},
        "warnings": [],
    }


def _finding(fid: str, sev: str, title: str, evidence: list[dict[str, Any]], **kw: Any) -> dict[str, Any]:
    f = {
        "id": fid,
        "scope": "requirement",
        "kind": "ambiguity",
        "criterion": "однозначность",
        "severity": sev,
        "title": title,
        "impact": "разработка и тестирование трактуют правило по-разному",
        "req_ids": ["R-01"],
        "hints": [],
        "status": "confirmed",
        "anchor_status": "supported",
        "meaning_status": "confirmed",
        "blocked_decision": "какое значение заложить в код и в тест",
        "recommendation": "уточнить формулировку в ТЗ",
        "blocks": ["development", "testing"],
        "witness": None,
        "evidence": evidence,
    }
    f.update(kw)
    if f["status"] == "needs_review":
        f["meaning_status"] = "uncertain"
    return f


def pdf_report(path: Path, blocks: list[dict[str, Any]]) -> dict[str, Any]:
    blocks = [dict(b) for b in blocks]
    p1 = block_with(blocks, "Держатель карты", 1)
    p1b = block_with(blocks, "Уведомление приходит", 1)
    p2 = block_with(blocks, "Повтор:", 2)
    p2para = block_with(blocks, "Возврат уменьшает", 2)
    p3 = block_with(blocks, "код 200", 3)
    p4 = block_with(blocks, "чужой карты", 4)
    # блок «как от OCR»: страница 5 подтверждена, координат нет
    ocr = {"id": "b9001", "kind": "paragraph", "section": [], "text": "Держатель карты задаёт порог 50 000 ₸ (скан)", "loc": {"page": 5}}
    # ложная привязка: текст со страницы 2, а fragments указывают на страницу 1
    fake = {
        "id": "b9002",
        "kind": "paragraph",
        "section": [],
        "text": p2["text"],
        "loc": {"page": 1, "fragments": [dict(p1["loc"]["fragments"][0], start=0, end=len(p2["text"]))]},
    }
    # те же координаты p4, но в пространстве PDF (низ-лево, MediaBox) — проверка пересчёта
    with pymupdf.open(path) as d:
        from bcc_review.exports.pdf import _unrot_to_pdf

        m = _unrot_to_pdf(d[3])
        fr = p4["loc"]["fragments"][0]
        pdf_bbox = pymupdf.Rect(fr["rect"]) * m
    p4pdf = {
        "id": "b9003",
        "kind": "paragraph",
        "section": [],
        "text": p4["text"],
        "loc": {"page": 4, "fragments": [dict(fr, rect=[round(v, 3) for v in pdf_bbox], space="pdf")]},
    }
    blocks += [ocr, fake, p4pdf]
    doc_id = sha256(path)
    rep = _skeleton(doc_id, "Синтетическое ТЗ (PDF)", "pdf", blocks)
    rep["document"]["warnings"] = [{"code": "ocr_required", "page": 5, "message": "страница 5 — скан без текста"}]
    rep["questions"].append({"id": "Q-2", "finding_ids": ["F-04"], "prompt": "Какой HTTP-код возвращать при отклонённой сумме?",
                             "options": ["400", "200 и result=ERROR"], "affected_req_ids": []})
    rep["findings"] = [
        _finding("F-01", "critical", "Порог без правила по умолчанию", [ev(p1, "порог 50 000 ₸")]),
        _finding("F-02", "major", "Повтор порога на стр. 2", [ev(p2, "порог 50 000 ₸")]),
        _finding("F-03", "major", "Состав расходов неполон", [ev(p2para, "исходной покупки, а переводы и снятие")]),
        _finding(
            "F-04",
            "critical",
            "Код ответа при ошибке суммы противоречит",
            [ev(p3, "код 200 при ошибке суммы"), ev(p4, "возвращается 404")],
            kind="contradiction",
            criterion="непротиворечивость",
            witness={
                "input": "сумма вне диапазона",
                "outcome_a": "200 и result=ERROR",
                "outcome_b": "404",
                "evidence_a": ev(p3, "код 200 при ошибке суммы"),
                "evidence_b": ev(p4, "возвращается 404"),
            },
        ),
        _finding("F-05", "minor", "Скан без текстового слоя", [ev(ocr, "порог 50 000 ₸")]),
        _finding("F-06", "minor", "Опора не подтверждена", [{"block_id": p1["id"], "start": 0, "end": 5, "quote": "НЕВЕРНО"}]),
        _finding("F-07", "major", "Ложная привязка fragments", [ev(fake, "порог 50 000 ₸")]),
        _finding(
            "F-08", "major", "Нет правила отключения уведомления", [], scope="set", kind="omission",
            inspected_block_ids=[p1b["id"]],
        ),
        _finding("F-09", "minor", "Координаты в пространстве PDF", [ev(p4pdf, "чужой карты")], status="needs_review"),
    ]
    return rep


MARKDOWN_ROWS = 46
LONG_TOKEN = "https://example.invalid/alerts/saveLimit?cardId=demo-42&amount=50000&enabled=1&trace=" + "x" * 60


def _markdown() -> str:
    rows = []
    for i in range(1, MARKDOWN_ROWS + 1):
        if i == 30:
            rows.append(
                f"| {i} | `amount` | Порог в тенге от 1 000 до 1 000 000 ₸ включительно; обе границы входят, дробные "
                f"значения отклоняются с сообщением «Проверьте сумму», а прежнее состояние сохраняется | `limit_kzt` |"
            )
        elif i == 12:
            rows.append(f"| {i} | `curl` | {LONG_TOKEN} | — |")
        else:
            rows.append(f"| {i} | `p{i}` | Сумма {i * 1000:,} ₸ в строке {i}".replace(",", " ") + " | `f_" + str(i) + "` |")
    return "\n".join(
        [
            "# Уведомление о расходах по карте",  # 1
            "",  # 2
            "Учебное ТЗ для проверки PDF-экспорта: тенге ₸, «кавычки», № 5 и казахские буквы Әә Іі Ңң Ғғ Үү Ұұ Ққ Өө Һһ.",  # 3
            "",  # 4
            "## Функциональные требования",  # 5
            "",  # 6
            "* **Ф-1.** Держатель активной карты KZT задаёт целый порог от 1 000 до 1 000 000 ₸ включительно.",  # 7
            "* **Ф-2.** Порог задаётся в тенге и хранится в тиынах.",  # 8
            "* **Ф-3.** Push приходит один раз за календарный месяц, когда расходы",  # 9
            "  переходят от суммы ниже порога к сумме, равной порогу или выше.",  # 10
            "",  # 11
            "Ответ метода: код 200 и `result=ERROR` при отклонённой сумме.",  # 12
            "",  # 13
            "```json",  # 14
            '{"result":"ERROR","message":"Проверьте сумму","amount":"50000"}',  # 15
            "```",  # 16
            "",  # 17
            "## Параметры запроса",  # 18
            "",  # 19
            "| № | Parameter | Logic | DB field |",  # 20
            "| ---: | :--- | :--- | :--- |",  # 21
            *rows,  # 22 .. 22+N-1
            "",
            "## Статусы",
            "",
            "Для чужой карты возвращается 404, как и для отсутствующей карты.",
            "",
            "Порог задаётся в тенге и хранится в тиынах.",
        ]
    ) + "\n"


MARKDOWN = _markdown()


def md_line(text: str, needle: str, nth: int = 0) -> int:
    hits = [i + 1 for i, line in enumerate(text.splitlines()) if needle in line]
    return hits[nth]


def md_blocks(text: str) -> list[dict[str, Any]]:
    """Синтетический разбор Markdown (как №01/№02): блок = строка, кроме абзаца 9–10."""
    blocks: list[dict[str, Any]] = []
    lines = text.splitlines()
    skip = set()
    for i, raw in enumerate(lines):
        ln = i + 1
        if ln in skip or not raw.strip() or raw.startswith("```") or set(raw.replace("|", "").strip()) <= set(":- "):
            continue
        s = raw.strip()
        if s.startswith("#"):
            t, kind = s.lstrip("#").strip(), "heading"
        elif s.startswith("* "):
            t, kind = s[2:], "list_item"
        elif s.startswith("|"):
            t, kind = " | ".join(c.strip() for c in s.strip("|").split("|")), "table_row"
        else:
            t, kind = s, "paragraph"
        loc = {"line_start": ln, "line_end": ln}
        if s.startswith("* ") and i + 1 < len(lines) and lines[i + 1].startswith("  ") and lines[i + 1].strip():
            t = t + " " + lines[i + 1].strip()
            loc = {"line_start": ln, "line_end": ln + 1}
            skip.add(ln + 1)
        blocks.append({"id": f"b{len(blocks) + 1:04d}", "kind": kind, "section": [], "text": t, "loc": loc})
    return blocks


def report_for(path: Path, fmt: str, findings: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Минимальный отчёт для произвольного Markdown/TXT: блоки по строкам, свои замечания."""
    text = Path(path).read_text(encoding="utf-8")
    rep = _skeleton(sha256(path), Path(path).stem, {"md": "markdown", "txt": "text"}.get(fmt, fmt), md_blocks(text))
    rep["findings"] = findings or []
    return rep


def md_report(path: Path) -> dict[str, Any]:
    text = Path(path).read_text(encoding="utf-8")
    blocks = md_blocks(text)
    by_line = {b["loc"]["line_start"]: b for b in blocks}
    l_f1 = md_line(text, "**Ф-1.**")
    l_f2 = md_line(text, "**Ф-2.**")
    l_f3 = md_line(text, "**Ф-3.**")
    l_code = md_line(text, "Ответ метода")
    l_row30 = md_line(text, "| 30 |")
    l_row12 = md_line(text, "| 12 |")
    l_404 = md_line(text, "Для чужой карты")
    l_dup = md_line(text, "Порог задаётся в тенге", 1)
    rep = _skeleton(sha256(path), "Уведомление о расходах по карте", "markdown", blocks)
    rep["findings"] = [
        _finding("F-01", "critical", "Граница порога", [ev(by_line[l_f1], "от 1 000 до 1 000 000 ₸")]),
        _finding(
            "F-02",
            "critical",
            "Код ответа при ошибке суммы",
            [ev(by_line[l_code], "код 200"), ev(by_line[l_404], "возвращается 404")],
            kind="contradiction",
            criterion="непротиворечивость",
            witness={
                "input": "сумма вне диапазона",
                "outcome_a": "200 и result=ERROR",
                "outcome_b": "404",
                "evidence_a": ev(by_line[l_code], "код 200"),
                "evidence_b": ev(by_line[l_404], "возвращается 404"),
            },
        ),
        # одинаковая фраза есть в строках l_f2 и l_dup: нужна вторая (другая страница)
        _finding("F-03", "minor", "Повтор правила о тенге", [ev(by_line[l_dup], "Порог задаётся в тенге")]),
        _finding("F-04", "major", "Многострочная формулировка Ф-3", [ev(by_line[l_f3], "когда расходы переходят от суммы")]),
        _finding(
            "F-05", "major", "Дробные значения", [ev(by_line[l_row30], "дробные значения отклоняются")], status="needs_review"
        ),
        _finding("F-06", "minor", "Длинный URL в таблице", [ev(by_line[l_row12], LONG_TOKEN[-30:])]),
        _finding("F-07", "minor", "Опора не подтверждена", [{"block_id": by_line[l_f2]["id"], "start": 0, "end": 3, "quote": "xyz"}]),
    ]
    rep["_lines"] = {"f1": l_f1, "f2": l_f2, "f3": l_f3, "code": l_code, "row30": l_row30, "row12": l_row12, "l404": l_404, "dup": l_dup}
    return rep
