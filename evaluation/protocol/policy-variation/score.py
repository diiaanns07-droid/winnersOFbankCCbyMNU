"""Custodian scorer for a sealed PV-1 presentation. Raw reports and labels stay private."""
import argparse
from pathlib import Path
import sys

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent))
from run import call, digest, environment, git, jsonl, lines, read, write

def audit_evidence(ev,blocks,source_lines):
    b=blocks.get(ev.get("block_id"),{})
    loc=b.get("loc",{})
    left,right=ev.get("start"),ev.get("end")
    first,last=loc.get("line_start"),loc.get("line_end")
    q=ev.get("quote","")
    exact=isinstance(left,int) and isinstance(right,int) and bool(q) and 0<=left<right<=len(b.get("text","")) and b["text"][left:right]==q
    mapped=isinstance(first,int) and isinstance(last,int) and 1<=first<=last<=len(source_lines)
    literal=bool(mapped and q and q in "\n".join(source_lines[first-1:last]))
    return {"block_id":ev.get("block_id"),"quote":q,"start":left,"end":right,"line_start":first,"line_end":last,"block_exact":exact,"literal_in_cited_source_lines":literal}

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for flag in ("product","scorer","inputs","gold","reports","out"):
        ap.add_argument("--"+flag,type=Path,required=True)
    ap.add_argument("--presentation",choices=("primary","order","wording","live"),required=True)
    ap.add_argument("--mode",choices=("rules_only","rules_plus_llm"),required=True)
    a=ap.parse_args()
    product,scorer,inputs,gold,reports,out=[p.resolve() for p in (a.product,a.scorer,a.inputs,a.gold,a.reports,a.out)]
    seal=read(HERE/(a.presentation+".seal.json"))
    for worktree,expected in ((product,seal["agent_sha"]),(scorer,seal["scorer_sha"])):
        if git(worktree,"rev-parse","HEAD")!=expected or git(worktree,"status","--porcelain"):
            ap.error("Wrong or dirty checkout: "+str(worktree))
    manifest=inputs/"panel.manifest.json"
    if digest(manifest)!=seal["panel_manifest_sha256"] or digest(gold)!=seal["panel_gold_sha256"]:
        ap.error("Input manifest or reference differs from published commitment")
    if a.mode=="rules_plus_llm" and not seal["live_allowed"]:ap.error("Use the eight-document model panel")
    out.mkdir(parents=True,exist_ok=False)
    sys.path[:0]=[str(scorer),str(product/"src")]
    from bcc_review import contracts
    from evaluation.harness.adapter import report_to_rows
    from evaluation.harness.taxonomy import Taxonomy
    tax=Taxonomy.load(scorer/"evaluation/harness/taxonomy.toml")
    env=environment(product,"rules_only")
    rows=[]; audits=[]; log=[]
    measurements=lines(reports/"measurements.jsonl")
    rec={r["case_id"]:r for r in measurements}
    if len(measurements)!=len(rec):ap.error("Duplicate attempts in one return")
    for case in read(manifest)["cases"]:
        cid=case["case_id"];render=case["renders"][0];source=inputs/render["path"]
        if digest(source)!=render["sha256"]:ap.error("Changed document "+cid)
        row=rec.get(cid,{}); report_path=reports/"reports"/(cid+"-md")/"report.json"
        valid=False; verify=None; recorded_model=None; findings=[]
        if report_path.exists() and row:
            rep=read(report_path);ru=rep["run"]; sig=digest(report_path)
            contracts.validate(rep)
            verify,_=call(["-m","bcc_review","verify",report_path,source],env,product,out/(cid+"-verify"))
            valid=(sig==row.get("report_sha256") and ru.get("source_sha256")==rep["document"]["id"]==render["sha256"] and ru.get("agent_commit")==seal["agent_sha"] and ru.get("mode")==a.mode==row["requested_mode"] and ru.get("status") in ("complete","partial") and row.get("exit_code")==0 and (report_path.parent/"report.md").is_file() and ru["calls"]["cache_hits"]==0 and row.get("parameters",{}).get("cache")=="off")
            if a.mode=="rules_only":
                valid=valid and ru["calls"]["physical"]==0 and ru.get("model") is None
            else:
                wire=report_path.parent/"wire.jsonl"
                http=lines(wire) if wire.exists() else []
                models=sorted({r["response_model"] for r in http if r.get("status")==200 and r.get("response_model")})
                recorded_model=", ".join(models) or None
                valid=valid and bool(recorded_model and ru.get("model") and ru["provider"]=="gemini" and ru["calls"]["physical"]>0 and len(http)==row.get("http_requests"))
            if valid:
                findings=report_to_rows(rep,tax,case_id=cid,render_id=render["render_id"],fmt="md",duration_s=row.get("wall_seconds"))
                blocks={b["id"]:b for b in rep["document"]["blocks"]}
                source_lines=source.read_text("utf8").splitlines()
                for f in rep["findings"]:
                    evidence=list(f.get("evidence") or [])
                    witness=f.get("witness") or {}
                    for k in ("evidence_a","evidence_b"):
                        for e in witness.get(k,[]) if isinstance(witness.get(k),list) else [witness.get(k)]:
                            if isinstance(e,dict) and e not in evidence:evidence.append(e)
                    ev=[audit_evidence(e,blocks,source_lines) for e in evidence]
                    audits.append({"case_id":cid,"presentation":a.presentation,"corpus_version":"PV-1","agent_sha":seal["agent_sha"],"source_sha256":render["sha256"],"actual_model":recorded_model,"finding_id":f["id"],"title":f["title"],"status":f["status"],"kind":f["kind"],"evidence":ev,"all_block_exact":bool(ev) and all(x["block_exact"] for x in ev),"all_source_exact":bool(ev) and all(x["literal_in_cited_source_lines"] for x in ev),"human_decision":None})
        if not valid:
            findings=[{"case_id":cid,"record":"run","render_id":render["render_id"],"source_sha256":render["sha256"],"format":"md","status":"failed","mode":a.mode}]
        for f in findings:
            f.update(agent_sha=seal["agent_sha"],corpus_version="PV-1",presentation=a.presentation,actual_model=recorded_model)
            if f["record"]=="run":f.update(manifest_sha256=digest(manifest),cache={"policy":"off"})
        rows.extend(findings)
        log.append({"case_id":cid,"corpus_version":"PV-1","presentation":a.presentation,"agent_sha":seal["agent_sha"],"source_sha256":render["sha256"],"verify_exit":verify,"measured":valid,"actual_model":recorded_model,"report_sha256":row.get("report_sha256"),"mode":a.mode})
    jsonl(out/"predictions.jsonl",rows);jsonl(out/"source-audit.jsonl",audits);jsonl(out/"measurement-checks.jsonl",log)
    for st,flags in (("all",[]),("confirmed",["--status","confirmed"])):
        d=out/st
        rc,_=call(["-m","evaluation.harness","--gold",gold,"--pred",out/"predictions.jsonl","--manifest",manifest,"--render-format","md","--out-dir",d,*flags],env,scorer,out/("score-"+st))
        if rc: raise SystemExit("Scoring failed; see "+str(out))
    print(a.presentation,a.mode,"verified",sum(x["verify_exit"]==0 for x in log),"of",len(log),"documents")
if __name__=="__main__":main()
