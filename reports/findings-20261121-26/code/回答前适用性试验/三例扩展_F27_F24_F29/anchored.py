"""Render source dates/values beside the statement; verify free wording independently."""
import asyncio
import json
import re
from paired import CASES, OUT, call, inputs, parse, read, save, v1
from record_guard import ANSWER_VERSION, REVIEW_VERSION, OBSERVATION

SYS="""只写一句面向读者的定性判断或核实方法。完整事实数值、日期和量表分项会由程序在紧随其后的病例原文里展示，不在你的句子内抄写、拼接、改写任何日期、时刻、指标值、阈值、分项分值或总分。保留规范指标名称。若涉及计算或比较，点明哪些变量、标本和时点要对应；若涉及病因，分别说明记录到的暴露和需要核对的时间关系；若有不可测分项，保留符号和意义，不计算总量。使用全部给定依据约束措辞：一般机制只能作为可能解释，样本属性不同不能混用。不要引入新知识。只输出纯文本的一句答复，不给编号，不重复问题。"""
PROMPT=[{"role":"system","content":SYS},{"role":"user","content":"资料：运单原记5元。候选：该单记录费用5元。"},{"role":"assistant","content":"该运单已记录核定费用，可照录。"},{"role":"user","content":"资料：昨单有重量，今单有单价。候选：按二者相乘可计费。"},{"role":"assistant","content":"需核对同一笔运单的重量和单价，才能计算该笔费用。"}]
def hdr(patient):
    result={}
    current=""
    for i,l in patient.items():
        if l.startswith("【"): current=l
        result[i]=current
    return result
def skeleton(s):
    # Standard parameter names include e.g. FiO2 and PaO2. Digits in dates and values are disallowed.
    return re.sub(r'(?i)\b(?:PaO2|FiO2|SpO2|pCO2|PaCO2|CO2|O2)\b','指标',s,flags=re.ASCII)
def has_number(s):
    return re.search(r'\d',skeleton(s)) is not None
async def run(tag):
    _,_,patient,_=inputs(tag)
    heading=hdr(patient)
    root=OUT/tag/ANSWER_VERSION
    orig=OUT/tag/"V7/calls/01_compose"
    d=json.loads(read(orig/"request.json")["messages"][-1]["content"])
    pp,kk=d["病历片段"],d["知识片段"]
    drafts=parse(read(next(orig.glob("attempt_*/response.json")))["message"])
    P,K,A={},{},[]
    lines=["## 回答",""]
    for i,draft in enumerate(drafts,1):
        source=OUT/tag/REVIEW_VERSION/f"claim_{i:02}"
        decision=source/"decision.json"
        if not decision.is_file():
            raise ValueError("该主张尚无通过校验的核源结果："+str(source))
        r=read(decision)
        if r["处置"]=="删除":continue
        keys=list(dict.fromkeys(r["病历片段"])); refs=list(dict.fromkeys(r["知识片段"]))
        assert set(keys)<=set(pp) and set(refs)<=set(draft["知识片段"])
        facts={k:{"来源栏":heading[int(k.split('.')[0][1:])],"原句":pp[k]} for k in keys}
        citations={k:kk[k] for k in refs}
        body=r["内容"]
        # Reword when a proposed sentence carries numeric details or refers to a derived ratio.
        if has_number(OBSERVATION.sub("",body)) or "/" in body or "比值" in body:
            orig_msgs=PROMPT+[v1.message("user",{"原题":d["提问"],"候选":body,"病历":facts,"知识":citations})]
            msgs=orig_msgs
            for j in range(3):
                cell=root/f"claim_{i:02}"/f"wording_{j}"
                msg=await call(cell,"wording",msgs,350)
                body=msg["content"].strip()
                if body and not has_number(body):break
                msgs=orig_msgs+[{"role":"assistant","content":body},{"role":"user","content":"请去掉所有抄录的数值、日期或时刻，保留定性判断和指标名称。"}]
            assert body and not has_number(body),body
        item={"类型":r["类型"],"内容":body,"知识编号":list(dict.fromkeys(k.split('.')[0] for k in refs))}
        A.append(item)
        lines.append("- **"+item["类型"]+"**　"+body+"".join("["+n+"]" for n in item["知识编号"]))
        for k in keys:
            row=int(k.split('.')[0][1:]); P[k]={"行号":row,"摘录":pp[k]}
            lines.append("  - "+heading[row]+" "+k+"　"+pp[k])
        for k in refs:K[k]={"编号":k.split('.')[0],"摘录":kk[k]}
    assert P and K and A
    root.mkdir(exist_ok=True)
    save(root/"structured.json",{"回答":A,"病历":list(P.values()),"知识":list(K.values())})
    lines.extend(["","## 知识原文",""]+["- ["+k+"] "+kk[k] for k in K])
    (root/"answer.md").write_text("\n".join(lines)+"\n",encoding="utf8")
async def main():await asyncio.gather(*(run(t) for t in CASES))
if __name__=="__main__":asyncio.run(main())
