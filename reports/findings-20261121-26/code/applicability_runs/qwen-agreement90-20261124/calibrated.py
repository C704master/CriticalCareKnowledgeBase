"""Audit with independent evidence reading and frozen, balanced development exemplars."""
import asyncio
import math
import re
import sys
import time
from collections import Counter
from pathlib import Path
from dotenv import dotenv_values
from paired_audit import D,ROOT,PAIRS,prepare,read,save,sha,object_sha,msg,Transport
from evidence_first import decode,paragraphs

READER="""逐句核源。根据提供的病历、知识和问题截止时点，把指定答句拆成最小主张。请分别列出支持它的原文、有冲突/限定它的原文，以及可能被误解的条件。引用时保留原文日期和“昨日”等相对词，并换算它实际指的日期。关注临床截止、标本、单位、时间趋势、处方实施和建议的区别。临床常识可以解释定性建议，但不能补造原文。不要决定是否提醒。输出三行：支持方证据（精确摘录）／反方证据或未能核实什么／患者现在到底被断言或被建议做什么。示例：周二晨记“昨日测8，今日测7”，句子“周二测8”；输出：周二晨记“昨日测8，今日测7”／8是周一的值／句子断定为周二。"""
JUDGE="""你模拟临床医生，只就指定答句提出有实质价值的核查提醒。在已完成的教学示例中学习如何把材料和判断相匹配。来自其他病例的教学标签只示范口径，绝不能作为本病例的证据。收到的新病例只有一个需要裁定的片段。读资料员双方查证记录与原始出处，先判断这句话的真实语气和动作，再决定。
提醒＝有能明确指出的事实错配、日期或样本错配、从材料到诊断/原因/阈值/具体处置缺了关键一步。保留＝已核实的事实，或依据本例风险作出的适度、条件性临床建议。关注的是实质问题，举出某条普遍规则的具体实例可以成立，无需重复所有可能情况。真实风险下建议检查、观察、报告或先评估均可接受。若给出特定未获支持的时间/门槛/药品或把定植当感染，则即使语气委婉也要提醒。支持方与反方哪个读到了原句真正断言的那一步？保持跟已校准医生相同的严格程度。
输出一个JSON对象，先给“理由”（说明已支持的部分及关键缺口或消除疑点的证据），再给“定位”（本病例原始材料的连续短引用字符串数组），最后给“动作”（提醒/保留）。"""
def grams(s):
    words=re.findall(r"[a-z]+|\d+(?:\.\d+)?|[\u4e00-\u9fff]+",s.lower())
    return {w for t in words for w in ([t] if len(t)<2 else [t[i:i+2] for i in range(len(t)-1)])}
def makebank(last):
    bank=[]
    for n in range(1,last+1):
        gold=read(ROOT/f"b{n}"/"ref_codex.json")
        for c in PAIRS[n]:
            p=read(ROOT/f"b{n}"/"input"/(c+".json"))
            for r in p["待核"]:
                g=gold[c][r["编号"]]
                bank.append({"答句":r["待核片段"],"原始依据或其定位":g["定位"],"判定理由":g["理由"],"动作":g["动作"]})
    return bank
def examples(bank,claim):
    features=grams(claim); docfreq=Counter(w for g in bank for w in grams(g["答句"]))
    def rank(row):
        ws=grams(row["答句"])
        return sum(math.log((len(bank)+1)/(docfreq[w]+1))+1 for w in ws&features)/math.sqrt(max(1,len(ws)))
    return [row for action in ["保留","提醒"] for row in sorted((e for e in bank if e["动作"]==action),key=rank,reverse=True)[:3]]
async def run(n,version):
    prepare(n)
    bank=read(ROOT/(version+"-bank.json"))
    config=read(ROOT/(version+"-config.json"))
    assert n>config["last_development_batch"] and object_sha(bank)==config["bank_hash"]
    extra=config.get("extra","")
    dest=ROOT/f"b{n}"/version
    dest.mkdir(parents=True,exist_ok=False)
    key=dotenv_values(D.parents[2]/"t06_prompt_pilot_20261117/.env")["QWEN_TRIAL_API_KEY"]
    save(dest/"freeze.json",{"prompt_sha256":object_sha([READER,JUDGE,config]),"source_sha256":sha(Path(__file__)),"inputs":{c:sha(ROOT/f"b{n}"/"input"/(c+".json")) for c in PAIRS[n]}})
    sem=asyncio.Semaphore(4)
    async def call(cell,ms,ma):
        async with sem:return (await Transport(cell,cell,key).call("audit",ms,max_tokens=ma))["content"]
    async def work(c):
        cell=dest/c
        packet=read(ROOT/f"b{n}"/"input"/(c+".json"))
        raw=packet["材料"].split("【已选证据的适用条件核对】")[0]
        patient=read(D/c/"freeze.json")["patient"]; assert patient in raw
        knowledge=raw.split(patient,1)[1]
        async def one(r):
            k=r["编号"];cl=r["待核片段"]
            reader=await call(cell/"calls"/(k+"-reader"),[msg("system",READER),msg("user",{"实际材料":raw,"所在行":r["所在行"],"仅核片段":cl})],950)
            shots=examples(bank,cl)
            pre=[msg("system",JUDGE+"\n"+extra)]
            for sh in shots:
                pre.extend([msg("user",{"已结案的另一个教学病例的依据":sh["原始依据或其定位"],"教学答句":sh["答句"]}),msg("assistant",{"理由":sh["判定理由"],"定位":[sh["原始依据或其定位"]],"动作":sh["动作"]})])
            payload={"新病例、当前提问及截止":raw.split(patient,1)[0][:1800],"双方证据梳理（以原文核对）":reader,"带日期病例摘录":paragraphs(patient,cl+" "+reader),"已选知识原文":knowledge,"整行用来解释指代":r["所在行"],"指定裁决片段":cl}
            msgs=pre+[msg("user",payload)]
            def parse(s):
                j=decode(s)
                if j.get("动作") not in ("提醒","保留") or not isinstance(j.get("理由"),str) or not j["理由"].strip() or not isinstance(j.get("定位"),list) or not all(isinstance(v,str) for v in j["定位"]):raise ValueError("invalid JSON fields")
                return j
            first=await call(cell/"calls"/(k+"-judge"),msgs,950)
            try:j=parse(first)
            except (ValueError,TypeError,AttributeError):
                j=parse(await call(cell/"calls"/(k+"-format"),msgs+[msg("assistant",first),msg("user","请按要求输出完整JSON对象。")],950))
                j["首次格式失败"]=True
            j["连续引文检查"]=[bool(x) and x in raw for x in j["定位"]]
            return k,j
        jobs=await asyncio.gather(*(one(r) for r in packet["待核"]),return_exceptions=True)
        save(cell/"judgments.json",dict(v for v in jobs if isinstance(v,tuple)))
        for err in jobs:
            if isinstance(err,BaseException):raise err
    t=time.monotonic()
    jobs=await asyncio.gather(*(work(c) for c in PAIRS[n]),return_exceptions=True)
    save(dest/"timing.json",{"seconds":time.monotonic()-t,"errors":[str(e) for e in jobs if isinstance(e,BaseException)]})
    for e in jobs:
        if isinstance(e,BaseException):raise e
if __name__=="__main__":
    n=int(sys.argv[1]);v=sys.argv[2]
    if "--freeze" in sys.argv:
        bank=makebank(n)
        assert not (ROOT/(v+"-config.json")).exists()
        save(ROOT/(v+"-bank.json"),bank)
        extra=(ROOT/(v+".txt")).read_text("utf-8-sig") if (ROOT/(v+".txt")).exists() else ""
        save(ROOT/(v+"-config.json"),{"last_development_batch":n,"bank_hash":object_sha(bank),"extra":extra})
    else:asyncio.run(run(n,v))
