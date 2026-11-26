"""Таблица сравнения режимов продукта по нескольким metrics.json.

Пропуск измерения показывается как «—» с причиной, а не как ноль.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _frac(num: int, den: int, value: float | None) -> str:
    if value is None:
        return "— (знаменатель 0)"
    return f"{value:.3f} ({num}/{den})"


def _val(v: Any, missing: str) -> str:
    return f"— ({missing})" if v is None else str(v)


def comparable(metrics: dict[str, dict]) -> tuple[bool, list[str]]:
    reasons = []
    def same(label: str, getter) -> None:
        vals = {name: getter(m) for name, m in metrics.items()}
        if len({json.dumps(v, sort_keys=True, ensure_ascii=False) for v in vals.values()}) > 1:
            reasons.append(f"{label} различается: " + "; ".join(f"{k}={v}" for k, v in vals.items()))
    same("эталон (sha256)", lambda m: (m.get("inputs", {}).get("gold") or {}).get("sha256"))
    same("манифест (sha256)", lambda m: (m.get("inputs", {}).get("manifest") or {}).get("sha256"))
    same("манифест в прогонах", lambda m: m.get("runs", {}).get("manifest_sha256"))
    same("настройки кэша", lambda m: m.get("runs", {}).get("cache"))
    same("формат представления", lambda m: m.get("policy", {}).get("render_format"))
    same("правило типов", lambda m: m.get("policy", {}).get("type_match"))
    same("размеченные кейсы", lambda m: m.get("counts", {}).get("cases_labeled"))
    return not reasons, reasons


def build_table(metrics: dict[str, dict]) -> tuple[str, dict]:
    ok, reasons = comparable(metrics)
    names = list(metrics)
    rows: list[tuple[str, list[str]]] = []

    def add(label: str, fn) -> None:
        rows.append((label, [fn(metrics[n]) for n in names]))

    add("Режим в прогонах", lambda m: ", ".join(m.get("runs", {}).get("modes") or []) or "— (нет строк run)")
    add("Кейсов измерено / размечено", lambda m: f"{m['counts']['independent_cases']} / {m['counts']['cases_labeled']}")
    add("Пропуски измерений", lambda m: str(m["counts"]["missing_measurements"]))
    add("TP / FP / FN", lambda m: f"{m['micro']['tp']} / {m['micro']['fp']} / {m['micro']['fn']}")
    add("Дубли (вне precision)", lambda m: str(m["micro"]["duplicates"]))
    add("Precision", lambda m: _frac(m["micro"]["tp"], m["micro"]["tp"] + m["micro"]["fp"], m["micro"]["precision"]))
    add("Recall", lambda m: _frac(m["micro"]["tp"], m["micro"]["tp"] + m["micro"]["fn"], m["micro"]["recall"]))
    add("F1", lambda m: "— (знаменатель 0)" if m["micro"]["f1"] is None else f"{m['micro']['f1']:.3f}")
    add("Precision с дублями", lambda m: "— (знаменатель 0)" if m["micro"]["precision_strict"] is None
        else f"{m['micro']['precision_strict']:.3f}")
    add("Ложные тревоги на чистых (находок; кейсов с тревогой / чистых)",
        lambda m: f"{m['clean_controls']['false_alarms']}; {m['clean_controls']['cases_with_alarms']} / "
                  f"{m['clean_controls']['cases']}")
    add("На разборе (pending)", lambda m: str(m["micro"]["pending_adjudication"]))
    add("Новые реальные дефекты (после разбора)", lambda m: str(m["micro"]["new_real_defects"]))
    add("Длительность, с: всего / медиана",
        lambda m: "— (не измерено)" if not m.get("runs", {}).get("duration_s", {}).get("measured_runs")
        else f"{m['runs']['duration_s']['total']} / {m['runs']['duration_s']['median']}")
    add("Физические вызовы LLM",
        lambda m: _val((m.get("runs", {}).get("physical_calls") or {}).get("total"), "отчёт не сообщает"))
    add("Токены вход / выход",
        lambda m: "— (не сообщены)" if not (m.get("runs", {}).get("tokens") or {}).get("measured_runs")
        else f"{m['runs']['tokens']['input']} / {m['runs']['tokens']['output']}"
             + (f" ({m['runs']['tokens']['note']})" if m['runs']['tokens'].get('note') else ""))
    add("Статусы прогонов", lambda m: ", ".join(f"{k}: {v}" for k, v in sorted((m.get("runs", {}).get("status") or {}).items()))
        or "— (нет строк run)")
    add("Нарушения режима", lambda m: str(len(m.get("runs", {}).get("violations") or [])))

    head = "| Показатель | " + " | ".join(names) + " |\n| :--- | " + " | ".join(":---" for _ in names) + " |\n"
    body = "".join(f"| {label} | " + " | ".join(vals) + " |\n" for label, vals in rows)
    verdict = "Сопоставимо: да (один эталон, манифест, формат, правило типов и кэш)." if ok else \
        "Сопоставимо: НЕТ.\n" + "\n".join(f"- {r}" for r in reasons)
    missing = []
    for n in names:
        for x in metrics[n].get("missing_measurements", []):
            missing.append(f"- {n}: {x['case_id']} ({x['format']}): {x['reason']}")
    md = "# Сравнение режимов\n\n" + verdict + "\n\n" + head + body
    if missing:
        md += "\n## Пропуски измерений\n" + "\n".join(missing) + "\n"
    return md, {"comparable": ok, "reasons": reasons, "rows": [{"metric": l, **dict(zip(names, v))} for l, v in rows]}


def compare_files(pairs: list[str], out_md: str | None, out_json: str | None) -> tuple[str, dict]:
    metrics = {}
    for p in pairs:
        if "=" not in p:
            raise ValueError("ожидается ИМЯ=путь/metrics.json")
        name, path = p.split("=", 1)
        metrics[name] = json.loads(Path(path).read_text(encoding="utf-8"))
    md, data = build_table(metrics)
    if out_md:
        Path(out_md).write_text(md, encoding="utf-8")
    if out_json:
        Path(out_json).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return md, data
