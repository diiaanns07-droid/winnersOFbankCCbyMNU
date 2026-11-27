"""Отчёт ревью для Confluence — вики-разметка Confluence (№34).

Страница вставляется в Confluence через «Вставить → Разметка → Confluence wiki» (Server/Data Center и Cloud) или
публикуется через REST API с ``representation: wiki``. В ней: вердикт для разработки и тестирования с метками
статуса, сводка по серьёзности, «исправить первым», таблица замечаний со ссылкой на строку документа и цитатой,
подробности каждого замечания в раскрывающемся блоке, вопросы владельцу с вариантами и «если ответа не будет»,
паспорт прогона. Источник — ``report.json`` (CONTRACT 2.6), числа и цитаты берутся из него без пересчёта.

Из командной строки::

    python -m bcc_review.v2.render.confluence out/report.json            # → out/report.confluence.txt
    python -m bcc_review.v2.render.confluence out/report.json -o page.txt
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Iterable

SEV = {"critical": ("Критичный", "Red"), "major": ("Существенный", "Yellow"), "minor": ("Незначительный", "Grey")}
SEV_PLURAL = {"critical": "Критичных", "major": "Существенных", "minor": "Незначительных"}
VERDICT = {"no": ("Нельзя", "Red"), "conditional": ("С условиями", "Yellow"), "yes": ("Можно", "Green"),
           "undetermined": ("Не определён", "Grey")}
BLOCKS = {"development": "разработку", "testing": "тестирование", "both": "разработку и тестирование"}
OPTION_LETTERS = "ABCDEFGH"

# Символы вики-разметки, которые в тексте документа должны остаться буквами: таблицы (|), макросы ({ }), ссылки
# ([ ]), картинки (!), а также начало форматирования (*bold*, _курсив_, -зачёркнутый-, +подчёркнутый+, ^ ~ ??).
_ALWAYS = re.compile(r"([|{}\[\]!])")
_EDGE = re.compile(r"(^|(?<=[\s(«\"']))([*_\-+^~])")
_EDGE_END = re.compile(r"([*_\-+^~])(?=$|[\s).,;:!?»\"'])")


def esc(value: Any) -> str:
    """Текст → вики-разметка: спецсимволы экранированы, переводы строк — «\\\\» (разрыв строки)."""
    s = "" if value is None else str(value)
    s = s.replace("\\", "&#92;")
    s = _ALWAYS.sub(r"\\\1", s)
    s = _EDGE.sub(lambda m: m.group(1) + "\\" + m.group(2), s)
    s = _EDGE_END.sub(r"\\\1", s)
    s = s.replace("??", "?\\?")
    lines = [ln.strip() for ln in s.splitlines()]
    return " \\\\ ".join(ln for ln in lines if ln) if len(lines) > 1 else (lines[0] if lines else "")


def status(title: str, colour: str) -> str:
    return "{status:colour=" + colour + "|title=" + re.sub(r"[|{}\]]", " ", title) + "}"


def _sev(f: dict) -> str:
    s = str(f.get("severity") or "minor")
    return s if s in SEV else "minor"


def _lines(ev: dict) -> str:
    a = ev.get("line_start") or ev.get("line")
    b = ev.get("line_end") or a
    if not a:
        return ""
    where = f"строка {a}" if not b or b == a else f"строки {a}–{b}"
    if ev.get("page"):
        where += f", стр. {ev['page']}"
    return where


def _first_where(f: dict) -> str:
    evs = [e for e in f.get("evidence") or [] if isinstance(e, dict)]
    return ", ".join(x for x in (_lines(e) for e in evs[:3]) if x) or "—"


def _plural(n: int, one: str, few: str, many: str) -> str:
    n = abs(int(n))
    if n % 10 == 1 and n % 100 != 11:
        return one
    return few if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14 else many


def _cell(text: str) -> str:
    """Ячейка таблицы не может быть пустой — иначе Confluence склеивает колонки."""
    return text if text.strip() else " "


def _row(cells: Iterable[str]) -> str:
    return "|" + "|".join(_cell(c) for c in cells) + "|"


def _head(cells: Iterable[str]) -> str:
    return "||" + "||".join(cells) + "||"


def render_wiki(report: dict) -> str:
    findings = [f for f in report.get("findings") or [] if isinstance(f, dict)]
    by_id = {f.get("id"): f for f in findings}
    doc = report.get("document") or {}
    run = report.get("run") or {}
    v = report.get("verdict") or {}
    title = doc.get("title") or Path(str(doc.get("file") or "документ")).stem
    out: list[str] = [f"h1. Ревью требований: {esc(title)}", ""]

    if run.get("status") in ("partial", "failed"):
        what = ("Прогон завершился ошибкой — вердикта нет." if run.get("status") == "failed"
                else "Прогон неполный — вердикт не выше «с условиями».")
        out += ["{warning}" + esc(what) + "{warning}", ""]
    if run.get("provider") == "offline":
        out += ["{info}Проверка без модели: только формальные дефекты по правилам, смысловые противоречия не "
                "искались.{info}", ""]

    dev = VERDICT.get(v.get("development", ""), ("—", "Grey"))
    tst = VERDICT.get(v.get("testing", ""), ("—", "Grey"))
    out += ["{panel:title=Можно ли начинать}",
            f"*Разработка:* {status(*dev)}    *Тестирование:* {status(*tst)}", ""]
    if v.get("summary"):
        out.append(esc(v["summary"]))
    out += ["{panel}", ""]

    counts = {s: sum(1 for f in findings if _sev(f) == s) for s in SEV}
    qs = report.get("quote_stats") or {}
    n_req = (report.get("summary") or {}).get("requirements", len(report.get("requirements") or []))
    quotes = f"{qs.get('verified', 0)} из {qs.get('quotes', 0)}" if qs.get("quotes") else "—"
    out += [_head([SEV_PLURAL[s] for s in SEV] + ["Требований", "Цитат сверено кодом"]),
            _row([str(counts[s]) for s in SEV] + [str(n_req), quotes]), ""]

    fix = [by_id[x] for x in v.get("fix_first") or [] if x in by_id]
    if fix:
        out += ["h2. Исправить первым", ""]
        out += [f"# *{esc(f.get('id'))}* {esc(f.get('title'))} — {esc(_first_where(f))}" for f in fix]
        out.append("")

    out += ["h2. Замечания", ""]
    if not findings:
        out += ["Замечаний нет: агент не нашёл дефектов, подтверждённых цитатами.", ""]
    else:
        out.append(_head(["ID", "Серьёзность", "Замечание", "Где", "Цитата", "Что сделать"]))
        for f in findings:
            lab, col = SEV[_sev(f)]
            ev0 = next((e for e in f.get("evidence") or [] if isinstance(e, dict)), {})
            quote = f"«{esc(ev0.get('quote'))}»" if ev0.get("quote") else ""
            sev = status(lab, col)
            if f.get("blocks") in BLOCKS:
                sev += " \\\\ блокирует " + BLOCKS[f["blocks"]]
            out.append(_row([f"*{esc(f.get('id'))}*", sev, f"*{esc(f.get('title'))}* \\\\ {esc(f.get('problem'))}",
                             esc(_first_where(f)), quote, esc(f.get("recommendation"))]))
        out.append("")
        out += ["h2. Подробно", ""]
        for f in findings:
            lab, _ = SEV[_sev(f)]
            out.append("{expand:title=" + re.sub(r"[|{}]", " ", f"{f.get('id')} · {lab} · {f.get('title') or ''}")[:250] + "}")
            out.append(f"*Проблема:* {esc(f.get('problem'))}")
            for e in f.get("evidence") or []:
                if isinstance(e, dict) and e.get("quote"):
                    sec = f" ({esc(e.get('section'))})" if e.get("section") else ""
                    out.append(f"{{quote}}{esc(_lines(e))}{sec}: «{esc(e['quote'])}»{{quote}}")
            for key, label in (("scenario", "Сценарий"), ("impact", "Последствия"), ("recommendation", "Что сделать"),
                               ("rewrite", "Предлагаемая формулировка"), ("question", "Вопрос владельцу")):
                if f.get(key):
                    out.append(f"*{label}:* {esc(f[key])}")
            if f.get("requirement_ids"):
                out.append("*Требования:* " + esc(", ".join(f["requirement_ids"])))
            if f.get("standard_refs"):
                out.append("*Стандарт:* " + esc("; ".join(f["standard_refs"])))
            stab = f.get("stability") if isinstance(f.get("stability"), dict) else {}
            if isinstance(stab.get("k"), int) and isinstance(stab.get("n"), int):
                out.append(f"*Устойчивость:* найден в {stab['k']} из {stab['n']} независимых проходов")
            out += ["{expand}", ""]

    questions = [q for q in report.get("questions") or [] if isinstance(q, dict)]
    if questions:
        out += ["h2. Вопросы владельцу", "",
                "Ответ — строкой «Q-01 \\[тема\\]: буква варианта или свой текст» в файле ответов; агент перепроверит "
                "замечания: {{" + esc("python -m bcc_review ТЗ отчёт.md --answers ответы.md --revise") + "}}.", "",
                _head(["ID", "Кому", "Вопрос", "Варианты", "Если ответа не будет", "Замечания"])]
        for q in questions:
            opts = " \\\\ ".join(f"*{OPTION_LETTERS[i] if i < len(OPTION_LETTERS) else i + 1}* — {esc(o)}"
                                 for i, o in enumerate(q.get("options") or []))
            qtext = esc(q.get("question"))
            if q.get("topic"):
                qtext = f"*{esc(q['topic'])}* \\\\ {qtext}"
            if q.get("blocking"):
                qtext = status("Блокирует", "Red") + " " + qtext
            out.append(_row([f"*{esc(q.get('id'))}*", esc(q.get("to")), qtext, opts, esc(q.get("if_no_answer")),
                             esc(", ".join(q.get("finding_ids") or []))]))
        out.append("")

    c = report.get("clarification") or {}
    if c:
        b, a = c.get("before") or {}, c.get("after") or {}
        vb, va = b.get("verdict") or {}, a.get("verdict") or {}
        out += ["h2. До и после ответов владельца", "", _head(["Показатель", "До ответов", "После ответов"])]
        for key, label in (("development", "Начинать разработку"), ("testing", "Начинать тестирование")):
            out.append(_row([label, status(*VERDICT.get(vb.get(key, ""), ("—", "Grey"))),
                             status(*VERDICT.get(va.get(key, ""), ("—", "Grey")))]))
        for s in SEV:
            out.append(_row([f"Замечания: {SEV[s][0].lower()}", str((b.get("findings") or {}).get(s, 0)),
                             str((a.get("findings") or {}).get(s, 0))]))
        out.append("")
        for x in c.get("answer_conflicts") or []:
            texts = x.get("texts") or {}
            sides = " ↔ ".join(f"{esc(k)} «{esc(texts.get(k, ''))}»" for k in x.get("answers") or [])
            out.append(f"* {status('Расхождение', 'Red')} {esc(x.get('finding_id'))}: {sides} — {esc(x.get('reason'))}")
        for p in c.get("postponed") or []:
            out.append(f"* {status('Отложено', 'Yellow')} {esc(p.get('question_id'))}: «{esc(p.get('text'))}»")
        out.append("")

    passes = (report.get("stability") or {}) if isinstance(report.get("stability"), dict) else {}
    model = ", ".join(run.get("models_used") or []) or run.get("model_requested") or "—"
    rows = [("Документ", f"{esc(doc.get('file'))} ({esc(doc.get('format'))})"),
            ("SHA-256 документа", "{{" + esc(doc.get("sha256") or "—") + "}}"),
            ("Модель", esc(model)), ("Провайдер", esc(run.get("provider") or "—")),
            ("Время прогона", f"{run.get('duration_s', '—')} с"),
            ("Вызовов модели", esc((run.get("calls") or {}).get("total", "—"))),
            ("Агент", esc(f"{run.get('agent', 'bcc-review')} {run.get('version', '')} {run.get('commit', '')}".strip()))]
    if passes.get("runs_counted"):
        rows.append(("Устойчивость", esc(passes.get("rule") or f"{passes['runs_counted']} проходов")))
    out += ["h2. Паспорт прогона", "", *(f"||{k}|{_cell(val)}|" for k, val in rows), "",
            "Каждая цитата найдена в документе программой, номер строки посчитан кодом. Повторная сверка: "
            "{{" + esc("python -m bcc_review verify report.json документ") + "}}."]
    return "\n".join(out).rstrip() + "\n"


def write(report: dict, path: str | Path) -> dict:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(render_wiki(report), encoding="utf-8")
    n = len([f for f in report.get("findings") or [] if isinstance(f, dict)])
    return {"format": "confluence", "status": "written", "path": str(p),
            "message": f"Confluence (вики-разметка): {n} {_plural(n, 'замечание', 'замечания', 'замечаний')}"}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m bcc_review.v2.render.confluence",
                                 description="Отчёт ревью для Confluence: вики-разметка для «Вставить → Разметка»")
    ap.add_argument("report", help="report.json")
    ap.add_argument("-o", "--out", help="куда записать (по умолчанию <отчёт>.confluence.txt рядом)")
    a = ap.parse_args(argv)
    src = Path(a.report)
    try:
        report = json.loads(src.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"Не удалось прочитать отчёт {src}: {type(exc).__name__}", file=sys.stderr)
        return 2
    stem = src.name[:-len(".json")] if src.name.endswith(".json") else src.stem
    out = Path(a.out) if a.out else src.with_name(stem + ".confluence.txt")
    res = write(report, out)
    print(f"{res['message']}: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
