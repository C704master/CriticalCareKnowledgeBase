from pathlib import Path
import hashlib
import json
from paired import CASES, OUT, inputs, read, save

def counts():
    phases={}
    for path in OUT.glob("F*/**/attempt_*/status.json"):
        row=read(path)
        key=row['stage']
        i=phases.setdefault(key,{"attempts":0,"completed":0,"elapsed_seconds_sum":0.0})
        i["attempts"]+=1
        i["completed"]+=int(row["state"]=="completed")
        i["elapsed_seconds_sum"]+=row.get("elapsed_seconds") or 0
    return phases

def main():
    digest=hashlib.sha256((OUT/"开跑前验收标准.md").read_bytes()).hexdigest()
    assert digest==read(OUT/"freeze.json")["standard_sha256"]
    info={}
    for tag in CASES:
        f,_,patient,ev=inputs(tag)
        c=read(OUT/tag/"comparison.json")
        x={}
        for a in ["V1","V2","V3","V4","V5","V6","V7","V8","V9"]:
            root=OUT/tag/a
            if not (root/"answer.md").exists():continue
            v={"answer_sha256":hashlib.sha256((root/"answer.md").read_bytes()).hexdigest()}
            for stage in ("audit","audit2"):
                if (root/stage/"result.json").exists():v[stage]={k:d["标签"] for k,d in read(root/stage/"result.json").items()}
            if (root/"structured.json").exists():
                z=read(root/"structured.json")
                v["cited"]=sorted({n for r in z["回答"] for n in r["知识编号"]})
                for r in z["病历"]:assert r["摘录"] in patient[r["行号"]]
                raw=read(OUT.parents[1]/tag/"static/evidence.json")
                for r in z["知识"]:assert r["摘录"] in raw[int(r["编号"][1:])-1]["raw_text"]
            x[a]=v
        info[tag]={"question":f["question"],"cutoff":f["cutoff"],"patient_sha256":hashlib.sha256(f["patient"].encode()).hexdigest(),"eligible":c["eligible"],"withheld":c["withheld"],"versions":x}
    save(OUT/"核验索引.json",{"standard_sha256":digest,"cases":info,"api_attempts":counts()})
if __name__=="__main__":main()
