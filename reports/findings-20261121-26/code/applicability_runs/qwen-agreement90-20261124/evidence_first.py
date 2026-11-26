"""Evidence-first audit. A collector sees the full case, then Qwen decides each claim separately."""
import asyncio
import json
import re
import sys
import time
from pathlib import Path
from dotenv import dotenv_values
from paired_audit import D,ROOT,PAIRS,prepare,read,save,sha,object_sha,msg,Transport

COLLECT="""你是答句复核的资料员。对每条指定片段，从原始临床资料和知识材料中找最能验证或质疑该句的原句。寻找紧邻的反例、记录所有限定词、来源、患者条件和统计时间，而不下是否正确的结论。每个编号输出至多四条连续短原文组成的JSON数组。不能摘得合适的原文时返回空数组。不要引用被审核的答案。示例输入：材料“周三记录昨日读数8，今天6。”待核“今天读数8”；示例输出：{"X":["周三记录昨日读数8，今天6。"]}。另例：材料“甲药用于已确诊甲类且B阳性者。”待核“B阳性，满足用药条件”；输出：{"X":["甲药用于已确诊甲类且B阳性者。"]}。"""
DECIDE="""你是为医生指出可核查疑点的审稿人。请像以下带有裁决依据的校准病例一样审查一个真实答句。可合理推断，但有实质、能具体指出的错配就提醒。只审目标片段，前后文字只解释指代。不要把片段隐含条件当成本例已满足，尤其区分“如果明确为……才……”（已经保留未知）与“本例符合……”（已经作出结论）。含“或”的充分条件要逐支检查。对于监测、护理、复评方向，能由已有风险合理推出就保留；加入具体切点、人群、剂量、或改用特定疗法时，必须核对这个新增条件本身。建议中若引用教材，不能把书里“此方法有作用”改成“遇到这个情况就该用”。不要将没有给出完整理想病史本身作为判断有误。
输出 JSON，动作仅限提醒/保留；理由指出具体得到支持的部分及真正缺口；定位是原始材料中相关的连续短引文数组。不得用材料中未出现的数字作支撑。"""
EXAMPLES=[
("病历：肺水肿，昨日净负平衡900 ml。书：严重肺水肿时可设特定负平衡目标。","昨日负平衡，已经达到严重肺水肿的个体治疗目标。","提醒","量有出处，但普通肺水肿记录不能证明本例严重度或个体目标。","严重肺水肿时"),
("病历：气体分压降低，采样部位及同期吸氧条件未记。","建议核对标本与当时吸氧条件；若证实为动脉且氧浓度偏高，应警惕氧合问题。","保留","不确定前提已明写，属于条件性判断。","采样部位及同期吸氧条件未记"),
("病历：气体分压从低值上升，标本未注明，呼吸支持中途有调整。","两次读数升高，说明治疗后氧合已经改善。","提醒","读数方向有据，标本和通气条件不可比，改善结论超出。","呼吸支持中途有调整"),
("病历：已接受血液净化，正用血管活性药。书：某种滤过技术可提高溶质清除。","该技术可能改善清除，但须留意当前循环耐受。","保留","用途与原文一致，对患者的耐受性留有条件。","可提高溶质清除"),
("病历：血压波动。书：某种滤过技术可提高溶质清除。","若血压不稳，可改用该技术。","提醒","来源没有把血压不稳列作这种方法的选择条件。","可提高溶质清除"),
("病历：某炎症指标由高值降至接近参考范围，仍标高。","指标仍异常，建议结合体温及临床表现随访。","保留","定性随访与已知异常相符，不依赖新的处置切点。","仍标高")]
def decode(s):
    return json.loads(re.sub(r"^`{3}(?:json)?\s*|\s*`{3}$","",s.strip()))
def paragraphs(patient,query):
    words=set(re.findall(r"(?=([\u4e00-\u9fff]{2}))",query))
    nums=set(re.findall(r"\d+(?:\.\d+)?|[A-Za-z]{2,}",query.lower()))
    header="";rows=[]
    for line in patient.splitlines():
        if line.startswith("【"):header=line;continue
        # Keep the entire dated clause, including neighbouring fields and time words.
        for s in re.split(r"[。；;]",line):
            if not s.strip():continue
            score=sum(w in s for w in words)+3*sum(n in s.lower() for n in nums)
            if score:rows.append((score,header+" "+s.strip()))
    return list(dict.fromkeys(s for _,s in sorted(rows,key=lambda t:-t[0])))[:18]
def prefix(version):
    extra=(ROOT/(version+".txt")).read_text("utf8") if (ROOT/(version+".txt")).exists() else ""
    ms=[msg("system",DECIDE+"\n"+extra)]
    for src,cl,act,why,anchor in EXAMPLES:
        ms.extend([msg("user",{"原始材料":src,"指定片段":cl}),msg("assistant",{"动作":act,"理由":why,"定位":[anchor]})])
    return ms
async def run(batch,version):
    prepare(batch)
    dest=ROOT/f"b{batch}"/version
    dest.mkdir(parents=True,exist_ok=False)
    key=dotenv_values(D.parents[2]/"t06_prompt_pilot_20261117/.env")["QWEN_TRIAL_API_KEY"]
    sem=asyncio.Semaphore(4)
    pre=prefix(version)
    save(dest/"freeze.json",{"prompt_sha256":object_sha([COLLECT,pre]),"source_sha256":sha(Path(__file__)),"inputs":{c:sha(ROOT/f"b{batch}"/"input"/(c+".json")) for c in PAIRS[batch]}})
    async def call(cell,ms,n):
        async with sem:
            t=Transport(cell,cell,key)
            result=await t.call("audit",ms,max_tokens=n)
        return decode(result["content"])
    async def case_run(case):
        cell=dest/case
        packet=read(ROOT/f"b{batch}"/"input"/(case+".json"))
        raw=packet["材料"].split("【已选证据的适用条件核对】")[0]
        patient=read(D/case/"freeze.json")["patient"]
        assert patient in raw
        knowledge=raw.split(patient,1)[-1]
        refs=await call(cell/"calls/collection",[msg("system",COLLECT),msg("user",{"原始材料":raw,"待核":packet["待核"]})],1800)
        assert set(refs)=={r["编号"] for r in packet["待核"]}
        decisions={}
        async def judge(r):
            k=r["编号"];assert isinstance(refs[k],list)
            located=[s for s in refs[k] if isinstance(s,str) and s.strip() and s in raw]
            payload={"资料员摘出的逐字原句":located,"按本题字段索引的病例原文":paragraphs(patient,r["待核片段"]),"该组入模知识全文":knowledge,"相邻语句（非裁决对象）":r["所在行"],"指定片段":r["待核片段"]}
            obj=await call(cell/"calls"/k,pre+[msg("user",payload)],1200)
            assert obj["动作"] in ("提醒","保留") and isinstance(obj["理由"],str) and obj["理由"].strip() and isinstance(obj["定位"],list) and all(isinstance(q,str) for q in obj["定位"])
            obj["连续引文检查"]=[bool(s) and s in raw for s in obj["定位"]]
            decisions[k]=obj
        jobs=await asyncio.gather(*(judge(r) for r in packet["待核"]),return_exceptions=True)
        for err in jobs:
            if isinstance(err,BaseException):raise err
        save(cell/"judgments.json",decisions)
    t=time.monotonic()
    jobs=await asyncio.gather(*(case_run(c) for c in PAIRS[batch]),return_exceptions=True)
    save(dest/"timing.json",{"seconds":time.monotonic()-t,"errors":[str(e) for e in jobs if isinstance(e,BaseException)]})
    for e in jobs:
        if isinstance(e,BaseException):raise e
if __name__=="__main__":
    asyncio.run(run(int(sys.argv[1]),sys.argv[2]))
