"""Сквозной прогон №06: штатный читатель и нарезка движка → review_set → JSON и таблица покрытия.

    python tests/p06/demo_case.py INPUT.md|INPUT.pdf OUT_DIR [--scripted]

Без флага — только правила (rules_only). С --scripted подключается подставной транспорт из тестов
(сценарии К2/К3 и покрытия), чтобы показать путь проверки witness; это НЕ ответ реальной модели.
Реальный прогон с LLM делает движок: python -m bcc_review INPUT OUTPUT.md --provider anthropic|gemini.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parents[1] / "src"), str(HERE)]

from conftest import ScriptedAsk, block_with  # noqa: E402

from bcc_review.analysis.cross import review_set  # noqa: E402
from bcc_review.analysis.facts import reconcile_facts  # noqa: E402


def _scripted(doc: dict) -> ScriptedAsk:
    from test_p06_case_ab import _k2, _k3

    fid = next(f["id"] for f in reconcile_facts(doc)["facts"] if f["field"] == "amount" and f["direction"] == "request")

    def coverage(payload: dict) -> dict:
        """Сценарий покрытия: приёмка №1 проверяет одну ветвь Ф-3, №3 — одну из двух исключённых операций Ф-2."""
        ob = {o["text"]: o["obligation_id"] for o in payload["obligations"]}
        ac = {a["text"]: a["acceptance_id"] for a in payload["acceptance"]}
        o = lambda needle: next(v for k, v in ob.items() if needle in k)  # noqa: E731
        a = lambda needle: next(v for k, v in ac.items() if needle in k)  # noqa: E731
        return {
            "obligations": [
                {"obligation_id": o("Когда расходы переходят"),
                 "branches": ["сумма становится равной порогу", "сумма становится выше порога", "сумма остаётся ниже порога"]},
                {"obligation_id": o("Переводы и снятие"), "branches": ["перевод не учитывается", "снятие наличных не учитывается"]},
            ],
            "links": [
                {"obligation_id": o("Когда расходы переходят"), "acceptance_id": a("48 500"), "relation": "checks_branch",
                 "branches_checked": ["сумма становится равной порогу"],
                 "explanation": "48 500 + 1 500 = 50 000 ₸ — проверен только переход ровно на порог."},
                {"obligation_id": o("Переводы и снятие"), "acceptance_id": a("Перевести"), "relation": "checks_branch",
                 "branches_checked": ["перевод не учитывается"],
                 "explanation": "Проверен перевод; снятие наличных не проверено."},
                {"obligation_id": o("Месяц определяется"), "acceptance_id": a("31 января"), "relation": "contradicts",
                 "explanation": "По Ф-2 покупка 31.01 относится к январю, приёмка ожидает февраль."},
            ],
        }

    return ScriptedAsk(coverage=coverage, pair_rules=[
        ("максимум один такой push", "независимо от истории", _k2),
        ("заполнены неверно", "Проверьте сумму",
         _k3(fid, block_with(doc, "параметры запроса заполнены неверно")["id"], block_with(doc, "Проверьте сумму")["id"])),
    ])


def _loc(doc: dict, bid: str) -> str:
    b = next((x for x in doc["blocks"] if x["id"] == bid), None)
    loc = (b or {}).get("loc") or {}
    if loc.get("page"):
        return f"стр. {loc['page']}"
    if "line_start" in loc:
        a, z = loc["line_start"], loc.get("line_end", loc["line_start"])
        return f"строка {a}" if a == z else f"строки {a}–{z}"
    return bid


def _q(s: str, n: int = 90) -> str:
    s = " ".join(str(s).split()).replace("|", "\\|")
    return s if len(s) <= n else s[: n - 1] + "…"


def render(doc: dict, res: dict) -> str:
    out = [f"# №06 — межраздельные противоречия и покрытие: {doc['title']}", "",
           f"Документ `{doc['id'][:12]}…`, режим `{res['stats']['mode']}`, вызовов модели: {res['stats']['llm_calls']}, "
           f"статус `{res['stats']['status']}`.", ""]
    s = res["coverage_summary"]
    out += ["## Покрытие обязательств приёмкой", "",
            f"Знаменатель **{s['denominator']}** обязательств: covered {s['covered']}, partial {s['partial']}, "
            f"conflict {s['conflict']}, uncovered {s['uncovered']}, unknown {s['unknown']}. "
            f"Связаны с приёмкой: {s['linked']} — это не покрытие.", "",
            "| Обязательство | Текст (опора) | Приёмка | Статус | Пояснение |", "| :--- | :--- | :--- | :--- | :--- |"]
    for c in res["coverage"]:
        h = c["hints"][0]
        out.append(f"| {c['obligation_id']} | «{_q(h['quote'], 70)}» ({_loc(doc, h['block_id'])}) | "
                   f"{', '.join(c['acceptance_ids']) or '—'} | **{c['status']}** | {_q(c['explanation'], 160)} |")
    out += ["", "## Кандидаты", ""]
    for c in res["candidates"]:
        out += [f"### {c['ref']} · {c['subkind']} ({c['kind']}, {c['criterion']}) · {c['severity']} — {c['title']}", "",
                f"Требования: {', '.join(c['req_ids']) or '—'}; приёмка: {', '.join(c.get('acceptance_ids', [])) or '—'}. {c['impact']}", ""]
        w = c.get("witness")
        if w:
            out += ["| Сторона | Опора | Исход |", "| :--- | :--- | :--- |",
                    f"| A | «{_q(w['evidence_a']['quote'])}» ({_loc(doc, w['evidence_a']['block_id'])}) | {_q(w['outcome_a'])} |",
                    f"| B | «{_q(w['evidence_b']['quote'])}» ({_loc(doc, w['evidence_b']['block_id'])}) | {_q(w['outcome_b'])} |", "",
                    f"Вход: {w['input']}", ""]
            for x in w["input_detail"].get("document_data", []):
                out.append(f"* данные документа — {x['name']}: «{x['value']}» ({_loc(doc, x['evidence']['block_id'])})")
            for x in w["input_detail"].get("illustrative", []):
                out.append(f"* иллюстративно — {x['name']}: {x['value']} ({x.get('why', '')})")
            out.append(f"* проверки: {c.get('checks')}")
            out.append("")
        if c.get("question"):
            out += [f"Вопрос для №08: {c['question']}", ""]
        if c["subkind"] == "missing_contract":
            out += [f"Обещание: «{_q(c['promise']['quote'], 140)}» ({_loc(doc, c['promise']['block_id'])}).",
                    f"Просмотрено: {c['inspected_scope']['span']}, блоков {len(c['inspected_block_ids'])}.",
                    f"Искали: {'; '.join(c['searched_for'])}. Найдено: {'; '.join(c['found'])}.", ""]
    out += ["## Таблица фактов (фрагмент)", "",
            "| ID | Поле | Направление | Тип | Значение / диапазон | Ед. | Условие | Опора |",
            "| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |"]
    for f in res["facts"]:
        if f["source"] in ("status_heading",):
            continue
        r = f["range"]
        val = (f"{r['min']}–{r['max']}" + (" вкл." if r.get("min_inclusive") else "")) if r else (f["value"] if f["value"] is not None else "")
        out.append(f"| {f['id']} | {_q(f['field'] or '', 30)} | {f['direction'] or '—'} | {f['type'] or '—'} | {_q(val, 30)} | "
                   f"{f['unit'] or '—'} | {_q(f['condition'] or '—', 40)} | {_loc(doc, f['evidence'][0]['block_id'])} |")
    out += ["", "## Сравнения фактов", ""]
    for c in res["comparisons"]:
        out.append(f"* `{c['id']}` {c['aspect']} → **{c['verdict']}**: {_q(c['explanation'], 220)}")
    a = res["evidence_audit"]
    out += ["", f"Опоры: проверено {a['checked']}, подтверждено {a['confirmed']}, перенесено {a['relocated']}, "
                f"неоднозначно {a['ambiguous']}, отклонено {a['rejected']}.", ""]
    if s.get("excluded"):
        out += ["## Вне знаменателя покрытия", ""] + [f"* {e['req_id']} ({e['label']}): {e['reason']}" for e in s["excluded"]] + [""]
    if res["warnings"]:
        out += ["## Предупреждения", ""] + [f"* {w}" for w in res["warnings"]] + [""]
    return "\n".join(out)


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print(__doc__)
        return 2
    src, out_dir = Path(argv[1]), Path(argv[2])
    out_dir.mkdir(parents=True, exist_ok=True)
    from bcc_review.runtime.modules import Modules

    m = Modules()
    doc = m.get("read_pdf" if src.suffix.lower() == ".pdf" else "read_text").func(str(src))
    inv = m.get("build_inventory").func(doc)
    ask = _scripted(doc) if "--scripted" in argv else None
    res = review_set(doc, inv["requirements"], ask, fact_hints=inv["fact_hints"])
    stem = src.stem + ("-pdf" if src.suffix.lower() == ".pdf" else "") + ("-scripted" if ask else "-rules")
    (out_dir / f"{stem}.json").write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / f"{stem}.md").write_text(render(doc, res), encoding="utf-8")
    s = res["coverage_summary"]
    kinds: dict[str, int] = {}
    for c in res["candidates"]:
        kinds[c["subkind"]] = kinds.get(c["subkind"], 0) + 1
    print(f"{stem}: candidates={kinds} coverage={s['covered']}/{s['denominator']} covered, "
          f"{s['conflict']} conflict, {s['partial']} partial, {s['uncovered']} uncovered, {s['unknown']} unknown; "
          f"llm_calls={res['stats']['llm_calls']} → {out_dir / (stem + '.md')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
