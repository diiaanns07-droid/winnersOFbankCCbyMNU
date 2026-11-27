"""Реконструкция ответа модели-судьи из выхода этапа stages/judge.json → mock-dir/judge.json ([ответ, проверка])."""
import json, sys, pathlib
run, out = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
o = json.load(open(run / "stages" / "judge.json"))["output"]
key = {f["id"]: f"F{i:02d}" for i, f in enumerate(o["findings"], 1)}
fs = []
for f in o["findings"]:
    fs.append({"key": key[f["id"]], "candidate_ids": f["candidate_ids"], "base": f["candidate_ids"][0],
               "title": f["title"], "kind": f["kind"], "criterion": f["criterion"],
               "requirement_ids": f.get("requirement_ids") or [], "problem": f["problem"],
               "scenario": f.get("scenario") or "", "wish": False, "severity_basis": "",
               "severity": f["severity"], "blocks": f.get("blocks") or "none", "priority": f.get("priority") or 0})
rej = [{"candidate_id": r["candidate_id"], "reason_code": r.get("reason_code") or "misread",
        "reason": r.get("reason") or "", "line": r.get("line") or 0} for r in o["rejected"]]
ch = [{"n": i, "answer": c["answer"], "comment": c.get("comment") or "",
       "finding_keys": [key[x] for x in c.get("finding_ids") or [] if x in key]} for i, c in enumerate(o["checklist"], 1)]
main = {"findings": fs, "rejected": rej, "checklist": ch, "verdict_summary": o.get("verdict_summary") or ""}
check = {"checks": [{"key": f["key"], "basis": "", "severity": f["severity"], "reason": ""} for f in fs],
         "verdict_summary": o.get("verdict_summary") or ""}
out.mkdir(parents=True, exist_ok=True)
json.dump([main, check], open(out / "judge.json", "w"), ensure_ascii=False, indent=1)
print(len(fs), "дефектов,", len(rej), "отклонено")
