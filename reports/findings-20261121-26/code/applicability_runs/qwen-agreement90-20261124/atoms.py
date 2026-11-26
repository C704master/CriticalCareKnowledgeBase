"""Audit ordered parts of a sentence separately, preserving the sentence's qualifications."""
import asyncio
import json
import re
import sys
from pathlib import Path
import calibrated as audit
from minimal import index
from paired_audit import msg
from batch_transport import CallFailure

RUBRIC="""你是逐项来源核对员。只审标明的一段有没有实质材料缺口，整句用于保留条件、否定及对它的解释。核实实际患者、日期、器官/标本、治疗场景、知识阈值或出处用途、行动强度。若仅为风险提示或按风险核查的建议，可以合理推断；若声称某项已发生、持续或发病原因、某明确处置切点，则须有对应该主张的实际依据。若提到“继续”并指定剂量或管路，核对截止时仍在用哪一项；不能用旧记录没有停用来证明现在的剂量。先写所核字词、最贴近的原文，再说明支持程度及明确缺口或为何无缺口。不要审别的分句，不要用你对疾病的偏好替代资料。只输出不超过140字的核查记录。
例：记录“镇静中，M2到M1”。整句“运动反应下降，说明额叶病灶进展”；指定片段“说明额叶病灶进展”；输出“额叶病灶进展：记录只有M2到M1，不能从运动分项定位病灶，且镇静干扰未排除。”另例：同材料，指定片段“建议复评神经体征”；输出“复评：运动分项确有变化，提出检查有据，未断言已有新病灶。”"""
base=audit.Transport
def parts(s):
    pieces=[m.group() for m in re.finditer(r"[^，；;。！？]+[，；;。！？]*|[，；;。！？]+",s)]
    if not pieces:return [s]
    while len(pieces)>4:
        i=min(range(len(pieces)-1),key=lambda j:len(pieces[j])+len(pieces[j+1]))
        pieces[i:i+2]=[pieces[i]+pieces[i+1]]
    assert "".join(pieces)==s
    return pieces

async def complete(cell,key,messages,budget):
    try:
        return await base(cell,cell,key).call("audit",messages,max_tokens=budget)
    except CallFailure:
        records=list(cell.rglob("response.json"))
        if not any(audit.read(p).get("finish_reason")=="length" for p in records):raise
        retry=cell.with_name(cell.name+"-truncation_retry")
        return await base(retry,retry,key).call("audit",messages+[msg("user","请把本次回答收束到160字以内，保留必要原文和最后判断，按原格式输出。")],max_tokens=3200)
class AtomReader:
    def __init__(self,batch,cell,key):
        self.cell,self.key=cell,key
    async def call(self,stage,messages,max_tokens):
        if not self.cell.name.endswith("-reader"):
            return await complete(self.cell,self.key,messages,2600)
        p=json.loads(messages[-1]["content"])
        cl=p["仅核片段"];raw=p["实际材料"];out=[]
        for i,section in enumerate(parts(cl),1):
            body={"同次原材料":raw,"所在行":p["所在行"],"完整待审答句":cl,"只核这部分":section,"数值索引":index(raw,section)}
            cell=self.cell.with_name(self.cell.name+"-"+str(i))
            r=await complete(cell,self.key,[msg("system",RUBRIC),msg("user",body)],2100)
            out.append([section,r["content"]])
        return {"content":json.dumps(out,ensure_ascii=False)}
if __name__=="__main__":
    audit.Transport=AtomReader
    audit.JUDGE+="\n提供的每一项来自独立的Qwen逐片核查。请综合整句，对每个真实疑点核实材料，最后由你决定是否提醒。实现 "+audit.sha(Path(__file__))
    asyncio.run(audit.run(int(sys.argv[1]),sys.argv[2]))
