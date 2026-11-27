"""LLM-арбитр для спорных пар «замечание ↔ эталон» и замечаний вне эталона.

Решения кэшируются в JSONL (ключ — хеш версии промпта, id эталона и текста замечания), поэтому повторный
подсчёт того же отчёта детерминирован и не тратит вызовы. Режимы: `off` — только кэш; `sonnet`/`haiku`/`opus` —
недостающие решения запрашиваются у `claude -p` одной пачкой.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

PROMPT_VERSION = "arb-3"

SYSTEM = """Ты — независимый эксперт по ревью требований в банке. Тебе дают документ требований (построчно,
«L038| текст»), эталонный список известных дефектов этого документа и замечания, которые выдал проверяемый агент.
Твоя задача — честно и строго разметить замечания. Ты не автор замечаний и не автор эталона.

Правила:
1. Пара «замечание ↔ эталон» (раздел pairs): verdict = match, если замечание называет главную проблему эталонного
   дефекта — ту, что в его названии (то же место документа и тот же изъян), пусть другими словами.
   verdict = no_match, если замечание лишь касается тех же строк, говорит о другой проблеме или совпадает с эталоном
   только во второстепенной детали из пояснения (например, эталон — «противоречие A и B», а замечание — лишь
   «в A размытое слово»).
2. Замечание вне эталона (раздел extras):
   * gold — на самом деле описывает один из эталонных дефектов (укажи gold_id);
   * real — настоящий дефект документа, которого нет в эталоне: утверждение верно по тексту, конкретно и полезно;
   * false — ложное: неверно читает документ, придумывает факты, требует того, что уже есть в тексте,
     или это общая фраза без конкретики;
   * duplicate — повторяет другое замечание из этого же списка (укажи его id в dup_of).
3. reason — одно-два предложения по-русски: почему так.
Ответ — только JSON по схеме."""

SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["pairs", "extras"],
    "properties": {
        "pairs": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["key", "verdict", "reason"],
            "properties": {"key": {"type": "string"}, "verdict": {"type": "string", "enum": ["match", "no_match"]},
                           "reason": {"type": "string"}}}},
        "extras": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["key", "verdict", "gold_id", "dup_of", "reason"],
            "properties": {"key": {"type": "string"},
                           "verdict": {"type": "string", "enum": ["gold", "real", "false", "duplicate"]},
                           "gold_id": {"type": "string"}, "dup_of": {"type": "string"},
                           "reason": {"type": "string"}}}},
    },
}


def finding_canon(f: dict) -> str:
    quotes = " | ".join(e.get("quote", "") for e in f.get("evidence", []))
    return f"{f.get('title', '')}\n{f.get('text', '')}\n{quotes}"


def cache_key(kind: str, gold_id: str, f: dict) -> str:
    h = hashlib.sha256(f"{PROMPT_VERSION}\x00{kind}\x00{gold_id}\x00{finding_canon(f)}".encode("utf-8"))
    return h.hexdigest()[:20]


def load_cache(path: Path) -> dict[str, dict]:
    out: dict[str, dict] = {}
    if path.exists():
        for ln in path.read_text(encoding="utf-8").splitlines():
            if ln.strip():
                try:
                    r = json.loads(ln)
                    out[r["key"]] = r
                except (json.JSONDecodeError, KeyError):
                    continue
    return out


def _finding_block(f: dict) -> str:
    ev = "; ".join(f"L{e.get('line_start') or '?'}: «{e.get('quote', '')[:200]}»" for e in f.get("evidence", []))
    return (f"[{f['id']}] ({f.get('severity', '')}, {f.get('kind', '')}) {f.get('title', '')}\n"
            f"  текст: {f.get('text', '')[:1200]}\n  цитаты: {ev}")


def call_claude(system: str, user: str, schema: dict, model: str, timeout: int = 900) -> tuple[dict, dict]:
    # shutil.which: на Windows claude — это claude.cmd/claude.exe, без полного пути CreateProcess его не находит
    cmd = [shutil.which("claude") or "claude", "-p", "--output-format", "json", "--tools", "", "--model", model,
           "--json-schema", json.dumps(schema, ensure_ascii=False), "--system-prompt", system]
    t0 = time.monotonic()
    # вопрос арбитру — русский текст: на Windows без encoding он уходил бы в stdin в cp1251, а CLI читает UTF-8
    r = subprocess.run(cmd, input=user, capture_output=True, text=True, encoding="utf-8", errors="replace",
                       timeout=timeout)
    try:
        out = json.loads(r.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"claude -p: не JSON (rc={r.returncode}): {r.stdout[-300:]} {r.stderr[-300:]}") from exc
    if out.get("is_error"):
        raise RuntimeError(f"claude -p: ошибка: {str(out.get('result'))[:300]}")
    data = out.get("structured_output")
    if data is None:
        data = json.loads(out.get("result") or "{}")
    meta = {"seconds": round(time.monotonic() - t0, 1), "cost_usd": out.get("total_cost_usd"),
            "model": next(iter((out.get("modelUsage") or {}).keys()), model)}
    return data, meta


def resolve(*, doc_numbered: str, gold_items: list[dict], pairs: list[tuple[str, dict]], extras: list[dict],
            cache_path: Path, mode: str = "off", batch: int = 40) -> tuple[dict[str, dict], dict]:
    """pairs: [(gold_id, finding)], extras: [finding]. Возвращает ({key: решение}, статистика вызовов)."""
    cache = load_cache(cache_path)
    want: list[dict] = []
    decisions: dict[str, dict] = {}
    for gid, f in pairs:
        k = cache_key("pair", gid, f)
        if k in cache:
            decisions[k] = {**cache[k], "cached": True}
        else:
            want.append({"type": "pair", "key": k, "gold_id": gid, "f": f})
    for f in extras:
        k = cache_key("extra", "", f)
        if k in cache:
            decisions[k] = {**cache[k], "cached": True}
        else:
            want.append({"type": "extra", "key": k, "gold_id": "", "f": f})
    stats = {"calls": 0, "seconds": 0.0, "cost_usd": 0.0, "pending": 0, "model": ""}
    if mode in ("off", "", None) or not want:
        stats["pending"] = len(want)
        return decisions, stats
    gold_text = "\n".join(f"{g['id']} [{g['level']}] {g['title']} — {' '.join(str(g.get('essence', '')).split())}"
                          f" (строки: {', '.join(gr['lines'] for gr in g['anchors']['groups'])})"
                          for g in gold_items)
    for i in range(0, len(want), batch):
        chunk = want[i:i + batch]
        parts = [f"<документ>\n{doc_numbered}\n</документ>", f"<эталон>\n{gold_text}\n</эталон>"]
        p_lines = [f"key={w['key']} эталон={w['gold_id']}\n{_finding_block(w['f'])}" for w in chunk
                   if w["type"] == "pair"]
        e_lines = [f"key={w['key']}\n{_finding_block(w['f'])}" for w in chunk if w["type"] == "extra"]
        parts.append("<pairs>\n" + ("\n\n".join(p_lines) or "—") + "\n</pairs>")
        parts.append("<extras>\n" + ("\n\n".join(e_lines) or "—") + "\n</extras>")
        parts.append("Размечай каждый key ровно один раз: pairs — в pairs, extras — в extras. "
                     "Для pairs gold_id не нужен; для extras gold_id и dup_of — пустая строка, если не применимо.")
        try:
            data, meta = call_claude(SYSTEM, "\n\n".join(parts), SCHEMA, mode)
        except Exception as exc:  # арбитр не обязателен: спорные пары останутся неразрешёнными
            stats["error"] = str(exc)[:300]
            stats["pending"] += len(chunk)
            continue
        stats["calls"] += 1
        stats["seconds"] += meta["seconds"]
        stats["cost_usd"] += float(meta.get("cost_usd") or 0)
        stats["model"] = meta["model"]
        by_key = {w["key"]: w for w in chunk}
        with cache_path.open("a", encoding="utf-8") as fh:
            for r in list(data.get("pairs", [])) + list(data.get("extras", [])):
                w = by_key.get(r.get("key"))
                if not w:
                    continue
                rec = {"key": w["key"], "type": w["type"], "gold_id": r.get("gold_id") or w["gold_id"],
                       "finding_id": w["f"]["id"], "finding_title": w["f"].get("title", ""),
                       "verdict": r.get("verdict"), "dup_of": r.get("dup_of", ""), "reason": r.get("reason", ""),
                       "model": meta["model"], "prompt": PROMPT_VERSION,
                       "at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
                decisions[w["key"]] = {**rec, "cached": False}
        stats["pending"] += sum(1 for w in chunk if w["key"] not in decisions)
    return decisions, stats


def resolve_any(**kw: Any) -> tuple[dict[str, dict], dict]:
    return resolve(**kw)
