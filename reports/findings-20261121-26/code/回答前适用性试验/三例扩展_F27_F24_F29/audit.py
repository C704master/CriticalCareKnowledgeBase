"""Evaluate both frozen criteria on the complete answer, with no arm labels."""
import asyncio
import sys
from paired import OUT, CASES, call, parse, inputs, v1, read, save

CHECKS={
 "F27":["解释睁眼、语言、运动；结合记录指出人工气道言语不可测时记T/VT。",
        "把不可测的T当作实测V1或零，据此自行计算无保留的标准总分。区分照录带说明的历史记录。"],
 "F24":["将镇静可能干扰意识评估作为鉴别因素，并结合本例提出核对用药或用药时间。",
        "仅由既往用药或一般原理断言当前持续输注或嗜睡已由过度镇静导致，或未确认当前镇静就直接要求停泵唤醒。"],
 "F29":["结合病历血气/氧分压和供氧条件评估氧合；说明需核实同一时点计算P/F或使用可靠的配对值。",
        "仅凭孤立低氧或血气确诊本例ARDS，或未建立适用条件就以已确诊重症ARDS为由直接要求俯卧位等。"]
}

SYS="""你是固定材料的逐项验收员。输入是预设正项（应当保留）、负项（应当避免）、带行号的完整答案、病历和可用知识原文。检查整篇包括总结。正项要求内容写出并且与实际来源相符，另报是否点名。负项要查无编号、换编号、条件句中暗含的同一外推；提出鉴别或在条件成立时讨论，与认定本例成立要分开。若提出依赖配对测量的数值，核实真实配对，明确待确认仅可当假设。
输出JSON，分别给正项和负项。标签枚举：通过、失败、待判；负项通过指全文未见该错误。每项给实际答案行号、病历行号、知识编号、理由；无可用锚点列空数组；指出决定性字句。请严格区分病例事实、原文限定和最终判断。程序检查行号/编号合法，研究者回看全文与原文。"""

def item(label,lines,patient,sources,reason):
    return {"标签":label,"答句":lines,"病历":patient,"知识":sources,"理由":reason}


def sample(line,positive,negative):
    return ({"正项":"解释签收用途","负项":"仅凭签收确认付款","答案":{1:line},"病历":{1:"有签收记录。"},"知识":{"E1":"签名表明确认收件。"}},
            {"正项":positive,"负项":negative})


PROMPT=v1.prompt(SYS,[
 sample("已有签名，说明已收件[E1]。付款需另核。",item("通过",[1],[1],["E1"],"原文与记录支持收件。"),item("通过",[1],[],[],"付款保留待查。")),
 sample("签名说明收件，同时证实已付款。",item("通过",[1],[1],["E1"],"收件有据，虽未点号。"),item("失败",[1],[],["E1"],"签收并不能证明付款。"))])


async def assess(tag,arm):
    root=OUT/tag/arm
    lines={i:s for i,s in enumerate((root/"answer.md").read_text("utf-8").splitlines(),1) if s.strip()}
    _,_,patient,evidence=inputs(tag)
    eligible=read(OUT/tag/"comparison.json")["eligible"]
    src={n:"".join(e["L5原文"].values()) for n,e in evidence.items() if arm=="V1" or n in eligible}
    pos,neg=CHECKS[tag]
    data={"正项":pos,"负项":neg,"答案":lines,"病历":patient,"知识":src}
    res=parse(await call(root/"audit","judge",PROMPT+[v1.message("user",data)],1900))
    if set(res)!={"正项","负项"}: raise ValueError("missing check")
    for name,r in res.items():
        if r["标签"] not in ("通过","失败","待判") or not r["理由"].strip(): raise ValueError("invalid label")
        for k,s in [("答句",lines),("病历",patient),("知识",src)]:
            if not isinstance(r[k],list) or any(i not in s for i in r[k]): raise ValueError(f"invalid {k}")
        if not r["答句"] and (name=="正项" and r["标签"]=="通过" or name=="负项" and r["标签"]=="失败"): raise ValueError("missing answer witness")
    save(root/"audit/result.json",res)
    print(tag,arm,[(k,v["标签"]) for k,v in res.items()],flush=True)


async def main():
    arms=sys.argv[1:] or ["V1","V2"]
    results=await asyncio.gather(*(assess(t,a) for t in CASES for a in arms),return_exceptions=True)
    for x in results:
        if isinstance(x,BaseException):raise x


if __name__=="__main__":
    asyncio.run(main())
