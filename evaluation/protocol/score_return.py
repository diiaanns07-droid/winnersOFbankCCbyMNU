"""Custodian: independently verify a six-input return, rebuild predictions and score the panel."""
import argparse
import json
from pathlib import Path
import re
import sys
from run import HERE, call, digest, environment, git, jsonl, lines, read, write

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for arg in ("product","vault","returned","out"): ap.add_argument("--"+arg,type=Path,required=True)
    ap.add_argument("--operator-seal",type=Path,help="Published receipt for an anonymized six-input package")
    ap.add_argument("--operator-manifest",type=Path,help="Input-only manifest from that package")
    ap.add_argument("--mode",choices=("rules_only","rules_plus_llm"),required=True)
    a=ap.parse_args()
    product,vault,returned,out=map(Path.resolve,(a.product,a.vault,a.returned,a.out))
    if bool(a.operator_seal)!=bool(a.operator_manifest):
        ap.error("--operator-seal and --operator-manifest must be supplied together")
    reference=read(HERE/"seal.json")
    seal=read(a.operator_seal) if a.operator_seal else reference
    corpus=vault/"corpus"; mode=a.mode
    if git(product,"rev-parse","HEAD")!=seal["agent_sha"] or git(product,"status","--porcelain"):
        ap.error("Exact clean product checkout required")
    manifest=corpus/"panel.manifest.json"; gold=corpus/"panel.labels.jsonl"
    if digest(manifest)!=reference["panel_manifest_sha256"] or digest(gold)!=reference["panel_gold_sha256"]:
        ap.error("Reference or manifest digest mismatch")
    cases=read(manifest)["cases"]
    expected={c["case_id"] for c in cases}
    operator_ids={cid:cid for cid in expected}
    if a.operator_manifest:
        if (seal.get("reference_manifest_sha256")!=digest(manifest) or seal.get("panel_gold_sha256")!=digest(gold)
                or digest(a.operator_manifest)!=seal.get("panel_manifest_sha256")):
            ap.error("Operator package differs from the published panel commitments")
        original={next(r["sha256"] for r in c["renders"] if r["format"]=="md"):c["case_id"] for c in cases}
        operator_ids={}
        for c in read(a.operator_manifest)["cases"]:
            alias=c["case_id"]
            rs=c["renders"]
            if (not re.fullmatch(r"[A-Za-z0-9_-]+",alias) or len(rs)!=1 or rs[0]["format"]!="md"
                    or rs[0]["sha256"] not in original or original[rs[0]["sha256"]] in operator_ids):
                ap.error("Invalid panel alias or input SHA")
            operator_ids[original[rs[0]["sha256"]]]=alias
        if set(operator_ids)!=expected or len(set(operator_ids.values()))!=len(expected):
            ap.error("The mapped panel is incomplete or contains duplicate aliases")
    records=lines(returned/"measurements.jsonl")
    by_id={row["case_id"]:row for row in records}
    if len(records)!=len(by_id) or set(by_id)-set(operator_ids.values()): ap.error("Unexpected or duplicate primary case")
    out.mkdir(parents=True,exist_ok=False)
    env=environment(product,"rules_only")
    sys.path[:0]=[str(product/"src"),str(product)]
    from bcc_review import contracts
    from evaluation.harness.adapter import report_to_rows
    from evaluation.harness.taxonomy import Taxonomy
    tax=Taxonomy.load(product/"evaluation/harness/taxonomy.toml")
    rows=[]; checks=[]
    for c in cases:
        cid=c["case_id"]; r=next(x for x in c["renders"] if x["format"]=="md")
        source=corpus/r["path"]
        if digest(source)!=r["sha256"]: ap.error("Changed input "+cid)
        alias=operator_ids[cid]
        row=by_id.get(alias,{})
        valid=False; why=[]; models=[]; converted=[]; rc=None
        ref=returned/"reports"/(alias+"-md")/"report.json"
        if row and ref.exists():
            report=read(ref); run=report["run"]
            rc,_=call(["-m","bcc_review","verify",ref,source],env,product,out/(cid+"-verify"))
            try: contracts.validate(report)
            except Exception as exc: why.append(str(exc))
            why.extend(contracts.evidence_errors(report))
            if not (digest(ref)==row.get("report_sha256") and run["source_sha256"]==r["sha256"]==row.get("source_sha256") and run["agent_commit"]==seal["agent_sha"]==row.get("agent_sha") and run["mode"]==mode and row.get("requested_mode")==mode and row.get("format")=="md"):
                why.append("identity/mode mismatch")
            if row.get("parameters",{}).get("cache")!="off" or run["calls"].get("cache_hits")!=0:
                why.append("cache mismatch")
            if (row.get("parameters") or {}).get("max_calls")!=12 or row.get("parameters",{}).get("max_retries")!=0:
                why.append("budget mismatch")
            if mode=="rules_plus_llm":
                wire=ref.parent/"wire.jsonl"
                http=lines(wire) if wire.exists() else []
                models=sorted({w["response_model"] for w in http if w.get("status")==200 and w.get("response_model")})
                if not (models and run["provider"]=="gemini" and run.get("model") and (run["calls"].get("physical") or 0)>0 and len(http)==row.get("http_requests")):
                    why.append("no verified provider response/model")
            elif run["calls"].get("physical")!=0: why.append("unexpected provider call")
            valid=not why and rc==0 and row.get("exit_code")==0 and (ref.parent/"report.md").exists() and run.get("status") in ("complete","partial")
            if valid: converted=report_to_rows(report,tax,render_id=r["render_id"],case_id=cid,fmt="md",duration_s=row.get("wall_seconds"))
        if not valid:
            why.append("missing or failed measurement")
            converted=[{"record":"run","case_id":cid,"render_id":r["render_id"],"format":"md","source_sha256":r["sha256"],"mode":mode,"status":"failed"}]
        ident={"case_id":cid,"agent_sha":seal["agent_sha"],"corpus_version":seal["corpus_version"],"actual_model":", ".join(models) or None,"source_sha256":r["sha256"]}
        for pred in converted:
            pred.update(ident)
            if pred["record"]=="run":pred.update(cache={"policy":"off"},manifest_sha256=digest(manifest))
        rows.extend(converted);checks.append({**ident,"operator_case_id":alias,"requested_mode":mode,"valid":valid,"verify_exit":rc,"reasons":why})
    jsonl(out/"predictions.jsonl",rows);jsonl(out/"independent-check.jsonl",checks)
    for name,flags in (("all",[]),("confirmed",["--status","confirmed"])):
        code,_=call(["-m","evaluation.harness","--gold",gold,"--manifest",manifest,"--pred",out/"predictions.jsonl","--out",out/(name+".json"),"--adjudication-out",out/(name+"-review.jsonl"),"--render-format","md",*flags],env,product,out/("score-"+name))
        if code:raise SystemExit("Scoring failed")
    print("Verified",sum(r["valid"] for r in checks),"of",len(checks),"panel returns")
if __name__=="__main__": main()
