"""Paired development ablation: retain all V19 inputs, add verified cited lines and range arithmetic."""
import asyncio
import json
import re
import sys
import time
from decimal import Decimal
from pathlib import Path
from dotenv import dotenv_values
from paired_audit import D,ROOT,PAIRS,read,save,sha,object_sha,msg,Transport
from evidence_first import decode

RULE="""下面两项是从本例原始材料机械取得的辅助信息。数值比较仅限相同单位的数值关系，不证明为同个临床指标、同日或具有某适应证。请先逐字核对点名引文是否真能支撑片段中的对象、人群、条件及行动。若出现真实值或区间，请验算，条件句未声称患者达到该区间时不要向它强加该断言。程序不给提醒/保留，最后由你根据原材料和原句决定。"""
N=r"\d+(?:\.\d+)?"
UNIT=r"(?:mmol/L|μmol/L|umol/L|mL/kg/h|mg/dL|g/dL|mg/L|g/L|mmHg|cmH₂O|mL/h|mL|ml|%|％|℃)"
RANGE=re.compile(r"("+N+r")\s*[-–—~～至]\s*("+N+r")\s*("+UNIT+r")",re.I)
def facts(raw,cl):
    wanted=set(re.findall(r"\[(E\d+)\]",cl))
    citations={k:[line for line in raw.splitlines() if line.startswith("["+k+"]")] for k in sorted(wanted)}
    comparisons=[]
    for m in RANGE.finditer(cl):
        a,b=Decimal(m[1]),Decimal(m[2]);u=m[3]
        if a>b:continue
        pat=re.compile(r"(?<![\d.])("+N+r")\s*"+re.escape(u)+r"(?![a-z/])",re.I)
        seen=set()
        for row in raw.splitlines():
            for hit in pat.finditer(row):
                n=Decimal(hit[1])
                if n in seen:continue
                seen.add(n)
                comparisons.append({"范围":m.group(),"数值":hit.group(),"数值关系":"低于下界" if n<a else "高于上界" if n>b else "在闭区间内","原处":row[max(0,hit.start()-22):hit.end()+22]})
    return {"点名引用原行":citations,"同单位数值对照（需复核指标）":comparisons}
async def run(n):
    src=ROOT/f"b{n}"/"v19";dest=src.with_name("v20")
    dest.mkdir(exist_ok=False)
    key=dotenv_values(D.parents[2]/"t06_prompt_pilot_20261117/.env")["QWEN_TRIAL_API_KEY"]
    sem=asyncio.Semaphore(4)
    save(dest/"freeze.json",{"prompt_sha256":object_sha([RULE,read(src/"freeze.json")["prompt_sha256"]]),"source_sha256":sha(Path(__file__)),"from_version":"v19","use":"已揭盲开发复查"})
    async def case(c):
        packet=read(src.parent/"input"/(c+".json"))
        raw=packet["材料"].split("【已选证据的适用条件核对】")[0]
        async def one(r):
            k=r["编号"]
            old=next((src/c/"calls"/(k+"-judge")).rglob("request.json"))
            ms=read(old)["messages"]
            p=json.loads(ms[-1]["content"])
            p.update(facts(raw,r["待核片段"]))
            ms=[msg("system",ms[0]["content"]+"\n"+RULE),*ms[1:-1],msg("user",p)]
            cell=dest/c/"calls"/k
            async with sem: resp=await Transport(cell,cell,key).call("audit",ms,max_tokens=2700)
            j=decode(resp["content"])
            assert j["动作"] in ("提醒","保留") and isinstance(j["理由"],str) and isinstance(j["定位"],list)
            j["连续引文检查"]=[isinstance(x,str) and bool(x) and x in raw for x in j["定位"]]
            return k,j
        jobs=await asyncio.gather(*(one(r) for r in packet["待核"]),return_exceptions=True)
        save(dest/c/"judgments.json",dict(j for j in jobs if isinstance(j,tuple)))
        for e in jobs:
            if isinstance(e,BaseException):raise e
    t=time.monotonic(); jobs=await asyncio.gather(*(case(c) for c in PAIRS[n]),return_exceptions=True)
    save(dest/"timing.json",{"seconds":time.monotonic()-t,"errors":[str(e) for e in jobs if isinstance(e,BaseException)]})
    for e in jobs:
        if isinstance(e,BaseException):raise e
if __name__=="__main__":asyncio.run(run(int(sys.argv[1])))
