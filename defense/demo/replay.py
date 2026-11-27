"""Reproduce the public, post-benchmark checklist demonstration on the frozen agent."""
import argparse
from pathlib import Path
import sys
here=Path(__file__).resolve().parent
sys.path.insert(0,str(here.parents[1]/"evaluation/protocol"))
from run import call, digest, environment, git, read, write

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--product",type=Path,required=True)
    parser.add_argument("--out",type=Path,required=True)
    args=parser.parse_args()
    product,out=args.product.resolve(),args.out.resolve()
    if git(product,"rev-parse","HEAD")!=read(here.parents[1]/"evaluation/protocol/seal.json")["agent_sha"] or git(product,"status","--porcelain"):
        parser.error("Use the clean frozen release")
    out.mkdir(parents=True,exist_ok=False)
    env=environment(product,"rules_only")
    sys.path.insert(0,str(product/"src"))
    from bcc_review.decisions.__main__ import fill_answers
    source=here/"source.md"
    def command(arguments,log):
        rc,_=call(arguments,env,product,log)
        if rc: raise SystemExit((rc,str(log)))
    command(["-m","bcc_review",source,out/"before.md","--offline-lint","--no-cache"],out/"before-run")
    command(["-m","bcc_review.decisions","questions",source,out/"before.json","-o",out/"questions.md"],out/"export")
    before=read(out/"before.json")
    question=next(q for q in before["questions"] if "немедленно" in q["prompt"])
    info={"case_id":"demo-terms","corpus_version":"demonstration","agent_sha":before["run"]["agent_commit"],"before":before["checklist"],"actual_model":None,"variants":[]}
    for variant,seconds in (("A",30),("B",120)):
        folder=out/variant;folder.mkdir()
        wording=f"После регистрации заявления банк должен выдать квитанцию не позднее чем через {seconds} секунд."
        answer=fill_answers((out/"questions.md").read_text("utf-8"),{question["id"]:"Выбрана редакция "+variant+".\nФормулировка: "+wording},label=None)
        (folder/"answers.md").write_bytes(answer.encode())
        command(["-m","bcc_review",source,folder/"report.md","--compare",out/"before.json","--answers",folder/"answers.md","--offline-lint","--no-cache"],folder/"answers-run")
        revised,=folder.glob("*.rev-*.md")
        rc,_=call(["-m","bcc_review","verify",folder/"report.json",revised],env,product,folder/"answers-verify")
        command(["-m","bcc_review",revised,folder/"recheck.md","--offline-lint","--no-cache"],folder/"recheck-run")
        command(["-m","bcc_review","verify",folder/"recheck.json",revised],folder/"recheck-verify")
        info["variants"].append({"choice":variant,"seconds":seconds,"revision":revised.name,"source_sha256":digest(revised),"answers_verify_exit":rc,
                                 "recheck_verify_exit":0,"checklist":read(folder/"recheck.json")["checklist"]})
    write(out/"summary.json",info)
    print("Before:",[(x["id"],x["checked"]) for x in info["before"]])
    for x in info["variants"]:print(x["choice"],x["seconds"],x["checklist"][0]["checked"],"answers verify:",x["answers_verify_exit"],"recheck verify:",x["recheck_verify_exit"])
if __name__=="__main__": main()
