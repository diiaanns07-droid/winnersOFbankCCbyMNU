"""Рубрика понятности (WAVE3) для кандидатов линзы: заголовок ≤ 12 слов, без меток строк «L123», латиница —
только имена из документа, сценарий с конкретными значениями (цифрами), есть исправление (rewrite или вопрос).

    python tests/v2/fixtures/07_bench/clarity.py out/07bench/open2/v2 out/07bench/corpus/v2
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

LATIN = re.compile(r"[A-Za-z][A-Za-z_0-9$]*")
LMARK = re.compile(r"\bL\d{2,3}\b")
COMMON = {"api", "http", "json", "get", "post", "put", "patch", "delete", "head", "rfc", "id", "url", "rest", "kzt",
          "utc", "iso", "curl", "ok", "error", "dev", "prod", "content", "type", "application", "bearer", "sms", "push"}


def check(run: Path, vocab: set[str]) -> list[dict]:
    q = json.loads((run / "stages" / "quotes.json").read_text(encoding="utf-8"))
    out = []
    for c in (q.get("output") or {}).get("candidates") or []:
        if c.get("source") != "lens:architect":
            continue
        title = str(c.get("title") or "")
        text = " ".join(str(c.get(k) or "") for k in ("title", "problem", "scenario", "impact", "recommendation"))
        latin = sorted({w for w in LATIN.findall(text) if w.lower() not in vocab and w.lower() not in COMMON})
        probs = []
        if len(title.split()) > 12:
            probs.append(f"заголовок {len(title.split())} слов")
        if LMARK.search(text + " " + str(c.get("rewrite") or "")):
            probs.append("метка строки L…")
        if latin:
            probs.append("латиница: " + ", ".join(latin[:5]))
        if c.get("kind") in ("status_conflict", "unit_mismatch", "contradiction", "event_conflict") and \
                not re.search(r"\d", str(c.get("scenario") or "")):
            probs.append("сценарий без значений")
        if not str(c.get("rewrite") or "").strip() and not str(c.get("question") or "").strip():
            probs.append("нет исправления")
        out.append({"title": title, "problems": probs})
    return out


def main() -> None:
    """Аргументы: каталоги out/07bench/<набор>/<метка> (в них runs.json со списком прогонов и путями документов)."""
    root = Path(__file__).resolve().parents[4]
    total = ok = 0
    for arg in sys.argv[1:]:
        info = json.loads((Path(arg) / "runs.json").read_text(encoding="utf-8"))
        for r in info["runs"]:
            run = root / "runs" / r["rid"]
            if not (run / "stages" / "quotes.json").exists():
                continue
            vocab = {w.lower() for w in LATIN.findall(Path(r["path"]).read_text(encoding="utf-8", errors="ignore"))}
            for x in check(run, vocab):
                total += 1
                ok += not x["problems"]
                if x["problems"]:
                    print(f"{r['name']}: {x['title'][:80]} — {'; '.join(x['problems'])}")
    print(f"\nПо рубрике: {ok}/{total} без замечаний ({100 * ok / max(1, total):.0f} %)")


if __name__ == "__main__":
    main()
