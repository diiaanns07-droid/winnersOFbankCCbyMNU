"""Три контрольных случая на открытом корпусе (ручной ответ — controls/expected.json).

    python -m evaluation.dev controls --out evaluation/dev/controls     # пересобрать
    python -m evaluation.dev controls --check                            # сверить с закоммиченным

1. similar_quote — два разных дефекта с похожей цитатой. Документ строится генератором из
   семейства cardblock двумя мутациями range_boundary: у обоих дефектов общая опора БК-2,
   а вторые опоры похожи («больше 1 и меньше 30» / «меньше 1 или не меньше 30»).
2. duplicate — один дефект и дубль находки: кейс корпуса transfer_limit.event_conflict.cancel_no_restore,
   две находки kind=conflict с одинаковыми цитатами (как выдаёт движок).
3. clean_alarm — чистый документ с одной ложной тревогой: кейс корпуса cashback.base.

Находки ниже заданы вручную; это фикстура протокола, а не вывод продукта. Смысловой хеш
корпуса seed 1 не меняется: контроли лежат отдельно и ссылаются на документы корпуса.
"""
from __future__ import annotations

import json
from pathlib import Path

from .families import CARDBLOCK
from .generator import build_base, build_mutant

ROOT = Path(__file__).resolve().parent
CORPUS = ROOT / "corpus"
OUT = ROOT / "controls"

C1 = "cardblock.combo.range_boundary-days_api_exclusive+range_boundary-days_400_at_30"
C2 = "transfer_limit.event_conflict.cancel_no_restore"
C3 = "cashback.base"

BK2 = "Клиент указывает срок блокировки от 1 до 30 суток включительно или выбирает бессрочную блокировку."
API_DAYS = "больше 1 и меньше 30; без поля — бессрочно"
LP4 = "Отменённый перевод уменьшает использованную сумму суток, в которые он был выполнен."
LP7 = "Отменённый перевод не уменьшает использованную сумму."
GOAL = "Клиент выбирает одну категорию покупок на месяц и получает кэшбэк за покупки в этой категории."

# (case_id, defect_id, поля находки, цитаты) — как строки протокола bcc-eval-pred/1
FINDINGS = [
    (C1, "F-07", {"issue_type": "boundary_conflict", "severity": "major"}, [API_DAYS, BK2]),
    (C1, "F-08", {"issue_type": "boundary_conflict", "severity": "major"}, [BK2]),
    (C2, "F-01", {"kind": "conflict", "severity": "critical"}, [LP4, LP7]),
    (C2, "F-02", {"kind": "conflict", "severity": "critical"}, [LP4, LP7]),
    (C3, "F-01", {"kind": "ambiguity", "severity": "minor"}, [GOAL]),
]


def _corpus_case(case_id: str) -> tuple[dict, list[dict]]:
    m = json.loads((CORPUS / "manifest.json").read_text(encoding="utf-8"))
    case = next(c for c in m["cases"] if c["case_id"] == case_id)
    labels = [json.loads(l) for l in (CORPUS / "labels.jsonl").read_text(encoding="utf-8").splitlines()
              if l.strip() and json.loads(l)["case_id"] == case_id]
    return case, labels


def build() -> dict[str, str]:
    """Файлы контролей: {относительный путь: содержимое}. Детерминированно."""
    v = {x["variant"]: x for x in CARDBLOCK["ops"]["range_boundary"]}
    c1 = build_mutant(CARDBLOCK, build_base(CARDBLOCK), [("range_boundary", v["days_api_exclusive"]),
                                                          ("range_boundary", v["days_400_at_30"])], "combo")
    assert c1.case_id == C1
    files: dict[str, str] = {f"cases/{C1}/source.md": c1.text}
    cases = [{"case_id": C1, "family": "cardblock", "kind": "control", "control": "similar_quote",
              "primary_render": "md", "renders": [{"render_id": f"{C1}@md", "format": "md",
                                                   "path": f"cases/{C1}/source.md", "sha256": c1.source_sha256}]}]
    labels = list(c1.labels)
    sha = {C1: c1.source_sha256}
    for cid, control in ((C2, "duplicate"), (C3, "clean_alarm")):
        case, labs = _corpus_case(cid)
        md = next(r for r in case["renders"] if r["format"] == "md")
        cases.append({"case_id": cid, "family": case["family"], "kind": "control", "control": control,
                      "primary_render": "md", "renders": [{**md, "path": "../corpus/" + md["path"]}]})
        labels.extend(labs)
        sha[cid] = md["sha256"]
    manifest = {"schema": "bcc-eval-manifest/1", "visibility": "public",
                "note": "Контроли на открытом корпусе. Ручной ответ — expected.json.", "cases": cases}
    preds = [{"record": "run", "source_sha256": sha[c], "status": "complete"} for c in (C1, C2, C3)]
    for cid, did, fields, quotes in FINDINGS:
        preds.append({"record": "finding", "source_sha256": sha[cid], "defect_id": did, **fields,
                      "anchors": [{"quote": q} for q in quotes]})
    dump = lambda rows: "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows)
    files["manifest.json"] = json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    files["labels.jsonl"] = dump(labels)
    files["predictions.jsonl"] = dump(preds)
    return files


def write(out: Path = OUT) -> list[str]:
    files = build()
    for rel, text in files.items():
        p = out / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(text.encode("utf-8"))
    return sorted(files)


def check(out: Path = OUT) -> list[str]:
    problems = []
    for rel, text in build().items():
        p = out / rel
        if not p.exists() or p.read_bytes() != text.encode("utf-8"):
            problems.append(f"{rel}: отличается от генератора")
    return problems
