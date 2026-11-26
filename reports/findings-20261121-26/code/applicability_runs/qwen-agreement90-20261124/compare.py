"""Compare frozen simulated-review decisions and Qwen's unmodified first decisions."""
import argparse
import json
from collections import Counter
from paired_audit import D,ROOT,PAIRS,read,save,sha

def compare(batch,version):
    folder=ROOT/f"b{batch}"
    dest=folder/version
    if batch==0:
        gold={}
        for case in PAIRS[batch]:
            rows=read(D/"applicability_runs/item2-source-audit-20261124/研究侧预判.json")[case]
            gold[case]={k:{"动作":"保留" if tag=="材料支持" else "提醒","理由":gap if tag!="材料支持" else support} for k,_,tag,support,gap in rows}
    else:
        gold=json.loads((folder/"ref_codex.json").read_text("utf-8-sig"))
    rows=[]
    tokens=0
    for case in PAIRS[batch]:
        pk=read(folder/"input"/(case+".json"))
        result=read(dest/case/"judgments.json")
        ids={r["编号"] for r in pk["待核"]}
        assert set(result)==ids==set(gold[case])
        for rec in pk["待核"]:
            key=rec["编号"]
            g,q=gold[case][key],result[key]
            assert g["动作"] in ("保留","提醒")
            rows.append(dict(case=case,id=key,claim=rec["待核片段"],gold=g["动作"],ref_reason=g["理由"],qwen=q["动作"],reason=q["理由"],anchor_checks=q["连续引文检查"]))
        for p in (dest/case/"calls").rglob("response.json"):
            tokens+=read(p).get("usage",{}).get("total_tokens",0)
    counts=Counter((r["gold"],r["qwen"]) for r in rows)
    tp,tn,fp,fn=counts['提醒','提醒'],counts['保留','保留'],counts['保留','提醒'],counts['提醒','保留']
    info=dict(batch=batch,version=version,tp=tp,tn=tn,fp=fp,fn=fn,accuracy=(tp+tn)/len(rows),tokens=tokens,seconds=read(dest/"timing.json")["seconds"],rows=rows)
    save(dest/"comparison.json",info)
    print({k:v for k,v in info.items() if k!="rows"})
    for r in rows:
        if r["gold"]!=r["qwen"]: print(r["case"],r["id"],r["claim"],"REF",r["ref_reason"],"QWEN",r["reason"])
if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("batch",type=int)
    p.add_argument("version")
    a=p.parse_args()
    compare(a.batch,a.version)
