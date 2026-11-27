"""Готовит четыре входа и сравнивает шесть отчётов штатных CLI с измеренным результатом."""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path


def summarize(name, report):
    findings = [f for f in report["findings"] if f.get("status", "active") == "active"]
    passport = report["passport"]
    if name.startswith("myn-"):
        verdict = [report["verdict_dev"], report["verdict_test"]]
        calls = report["metrics"]["llm_calls"]
    else:
        verdict = [report["verdict"]["dev_status"], report["verdict"]["test_status"]]
        calls = passport["llm_calls"]
    return {
        "input_sha256": passport.get("sha256", passport.get("document_sha256")),
        "requirement_count": len(report["requirements"]),
        "finding_count": dict(Counter(f["severity"].lower() for f in findings)),
        "model_calls": calls,
        "verdict": verdict,
        "findings": [
            {"severity": f["severity"].lower(), "title": f["title"],
             "lines": list(dict.fromkeys(q["line"] for q in f.get("quotes", f.get("evidence", [])) if q.get("line")))}
            for f in findings
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["prepare", "check"])
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    evidence = json.loads(Path(__file__).with_name("code-leaders-evidence.json").read_text(encoding="utf-8"))
    if args.action == "prepare":
        docs = dict(evidence["base_inputs"])
        for change in evidence["changes"]:
            text = docs[change["base"]]
            if text.count(change["old"]) != 1:
                raise ValueError(f"Неоднозначная замена в {change['base']}")
            docs[change["id"]] = text.replace(change["old"], change["new"])
        args.directory.mkdir(parents=True, exist_ok=True)
        for name, text in docs.items():
            content = text.encode("utf-8")
            expected = evidence["observed"][f"solo-{name}"]["input_sha256"]
            if hashlib.sha256(content).hexdigest() != expected:
                raise ValueError(f"Не совпал SHA исходного документа {name}")
            target = args.directory / f"{name}.md"
            if target.exists() and target.read_bytes() != content:
                raise SystemExit(f"В {target} уже есть другой файл")
            target.write_bytes(content)
        print(f"Подготовлено входных документов: {len(docs)}")
        return 0
    failed = 0
    for name, expected in evidence["observed"].items():
        path = args.directory / f"{name}.json"
        actual = summarize(name, json.loads(path.read_text(encoding="utf-8-sig")))
        mismatches = [field for field in expected if expected[field] != actual[field]]
        print(name, ", ".join(mismatches) if mismatches else "OK")
        failed += bool(mismatches)
    return int(bool(failed))


if __name__ == "__main__":
    raise SystemExit(main())
