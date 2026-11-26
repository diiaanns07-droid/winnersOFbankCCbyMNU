"""Run the frozen BCC agent on custodian inputs. Outputs are private, one directory per attempt."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from datetime import datetime, timezone

HERE = Path(__file__).resolve().parent

def read(path):
    return json.loads(path.read_text(encoding="utf-8"))

def lines(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode())

def jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows).encode())

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def git(at, *args):
    return subprocess.check_output(["git", "-C", str(at), *args], text=True).strip()

def call(args, env, product, log, timeout=240):
    start = time.perf_counter()
    try:
        p = subprocess.run([sys.executable, *map(str,args)], cwd=product, env=env, capture_output=True, timeout=timeout)
        rc, stdout, stderr = p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired as ex:
        rc, stdout, stderr = None, ex.stdout or b"", (ex.stderr or b"") + b"\nIE wall timeout"
    log.with_suffix(".stdout.txt").write_bytes(stdout)
    log.with_suffix(".stderr.txt").write_bytes(stderr)
    return rc, round(time.perf_counter()-start, 3)

def environment(product, mode):
    env = dict(os.environ)
    for key in list(env):
        if key.startswith("BCC_") or (mode == "rules_only" and any(x in key.upper() for x in ("API_KEY","TOKEN","SECRET","GOOGLE_","ANTHROPIC_","GEMINI_"))):
            env.pop(key)
    env.update(PYTHONPATH=str(product/"src"), PYTHONIOENCODING="utf-8", PYTHONUTF8="1", BCC_FORCE_FALLBACK="gemini")
    if mode=="rules_only":
        env.update(HTTPS_PROXY="http://127.0.0.1:9", HTTP_PROXY="http://127.0.0.1:9", ALL_PROXY="http://127.0.0.1:9", BCC_REVIEW_OFFLINE="1")
    return env

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--product", type=Path, required=True)
    parser.add_argument("--vault", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--mode", choices=["rules_only","rules_plus_llm"],required=True)
    parser.add_argument("--suite", choices=["all","panel"],required=True)
    args=parser.parse_args()
    product, vault, out = map(Path.resolve,(args.product,args.vault,args.out))
    mode=args.mode
    seal=read(HERE/"seal.json")
    corpus=vault/"corpus"
    if digest(vault/"sealed-files.json")!=seal["corpus_index_sha256"]:
        parser.error("Custodian index differs from public seal")
    for rel,expected in read(vault/"sealed-files.json").items():
        if digest(corpus/rel)!=expected: parser.error("Input hash mismatch: "+rel)
    if git(product,"rev-parse","HEAD")!=seal["agent_sha"] or git(product,"status","--porcelain"):
        parser.error("Run requires a clean checkout of the exact product SHA in seal.json")
    if (product/".env").exists(): parser.error("Use the clean checkout and pass the live credential through the environment")
    if mode=="rules_plus_llm":
        if args.suite!="panel": parser.error("Live measurements use the frozen six-document panel")
        if not (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")): parser.error("Team Gemini key missing; no measurements taken")
    out.mkdir(parents=True,exist_ok=False)
    env=environment(product,mode)
    sys.path[:0]=[str(product/"src"),str(product)]
    from bcc_review import contracts
    from evaluation.harness.adapter import report_to_rows
    from evaluation.harness.taxonomy import Taxonomy
    tax=Taxonomy.load(product/"evaluation/harness/taxonomy.toml")
    manifest=read(corpus/(args.suite+".manifest.json"))
    summaries=[]; predictions=[]
    parameters={"cache":"off","max_calls":12,"max_seconds":180,"timeout":30,"max_retries":0,
                "requested_model":"gemini-2.5-flash" if mode=="rules_plus_llm" else None,
                "temperature":0 if mode=="rules_plus_llm" else None,"max_output_tokens":65536 if mode=="rules_plus_llm" else None}
    write(out/"execution.json",{"started_utc":datetime.now(timezone.utc).isoformat(),"product":seal["agent_sha"],"mode":mode,"suite":args.suite,"parameters":parameters})
    for case in manifest["cases"]:
        cid=case["case_id"]
        for r in case["renders"]:
            fmt=r["format"]
            if args.suite=="panel" and fmt!="md": continue
            rel=Path("reports")/(cid+"-"+fmt)
            folder=out/rel
            folder.mkdir(parents=True)
            source=corpus/r["path"]
            command=["-m","bcc_review"] if mode=="rules_only" else [str(HERE/"wire_probe.py")]
            command += [str(source),str(folder/"report.md"),"--no-cache","--max-calls","12","--max-seconds","180","--timeout","30","--max-retries","0"]
            command += ["--offline-lint"] if mode=="rules_only" else ["--provider","gemini","--model","gemini-2.5-flash"]
            wire=folder/"wire.jsonl"
            runenv={**env,"IE_WIRE_LOG":str(wire)}
            rc,wall=call(command,runenv,product,folder/"run")
            path=folder/"report.json"
            rep=read(path) if path.exists() else {}
            run=rep.get("run",{})
            errors=[]
            if rep:
                try: contracts.validate(rep)
                except Exception as ex: errors.append(str(ex))
                errors.extend(contracts.evidence_errors(rep))
            verify_rc=None
            if rep: verify_rc,_=call(["-m","bcc_review","verify",path,source],env,product,folder/"verify")
            http=lines(wire) if wire.exists() else []
            models=sorted({m["response_model"] for m in http if m["response_model"]})
            calls=(run.get("calls") or {}).get("physical")
            actual_ok=run.get("mode")==mode and (calls==0 if mode=="rules_only" else bool(models and calls and run.get("model") and run.get("calls",{}).get("cache_hits")==0))
            identity=run.get("source_sha256")==digest(source) and run.get("agent_commit")==seal["agent_sha"]
            tech=rc==0 and verify_rc==0 and bool(rep) and (folder/"report.md").is_file() and identity and actual_ok and not errors and run.get("status") in ("complete","partial")
            actual_model=(", ".join(models) or None)
            record={"case_id":cid,"render_id":r["render_id"],"format":fmt,"family":case["family"],"stratum":case["stratum"],"corpus_version":seal["corpus_version"],
                    "agent_sha":seal["agent_sha"],"source_sha256":r["sha256"],"requested_mode":mode,"actual_mode":run.get("mode"),"actual_model":actual_model,
                    "report_model":run.get("model"),"parameters":parameters,"status":run.get("status"),"technical_success":bool(tech),
                    "semantic_complete":bool(tech and run["status"]=="complete" and not run.get("incomplete_stages")),"exit_code":rc,"verify_exit":verify_rc,
                    "physical_calls":calls,"http_requests":len(http) if mode=="rules_plus_llm" or rep else None,"wall_seconds":wall,
                    "input_tokens":(run.get("tokens") or {}).get("input"),"output_tokens":(run.get("tokens") or {}).get("output"),
                    "report":(rel/"report.json").as_posix() if rep else None,"report_sha256":digest(path) if rep else None,"contract_errors":errors}
            summaries.append(record)
            if rep and identity and actual_ok:
                rows=report_to_rows(rep,tax,render_id=r["render_id"],case_id=cid,fmt=fmt,duration_s=wall)
            else:
                rows=[{"record":"run","case_id":cid,"render_id":r["render_id"],"source_sha256":r["sha256"],"format":fmt,"mode":mode,"status":"failed"}]
            for row in rows:
                row.update(corpus_version=seal["corpus_version"],agent_sha=seal["agent_sha"],actual_model=actual_model)
                if row["record"]=="run":
                    row.update(cache={"policy":"off"},manifest_sha256=seal["panel_manifest_sha256"] if args.suite=="panel" else seal["full_manifest_sha256"])
            predictions.extend(rows)
            jsonl(out/"measurements.jsonl",summaries)
            jsonl(out/"predictions.jsonl",predictions)
            print(cid,fmt,run.get("status"),"verify",verify_rc,flush=True)
    for name in (["main","panel"] if args.suite=="all" else ["panel"]):
        ids={c["case_id"] for c in read(corpus/(name+".manifest.json"))["cases"]}
        selected=[x.copy() for x in predictions if x["case_id"] in ids and x.get("format")=="md"]
        for x in selected:
            if x["record"]=="run": x["manifest_sha256"]=digest(corpus/(name+".manifest.json"))
        dest=out/name
        jsonl(dest/"predictions.jsonl",selected)
        for suffix,additional in [("all",[]),("confirmed",["--status","confirmed"])]:
            cmd=["-m","evaluation.harness","--gold",corpus/(name+".labels.jsonl"),"--manifest",corpus/(name+".manifest.json"),
                 "--pred",dest/"predictions.jsonl","--out",dest/(suffix+".json"),"--adjudication-out",dest/(suffix+"-review.jsonl"),"--render-format","md",*additional]
            rc,_=call(cmd,env,product,dest/("score-"+suffix))
            if rc!=0: raise SystemExit("Scoring failed; see "+str(dest))
    write(out/"completed.json",{"finished_utc":datetime.now(timezone.utc).isoformat(),"records":len(summaries)})

if __name__=="__main__":
    main()
