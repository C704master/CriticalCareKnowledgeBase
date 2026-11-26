"""Independent contradictory-sentence check. Same prespecified endpoints as audit.py."""
import asyncio
import sys
from audit import CHECKS
from paired import CASES, OUT, call, inputs, parse, read, save, v1

SYS="""检查一份回答的两个预设条件。对正项：找到实际支持的句子，核对相关病历及原文，同时找答案别处是否自己违背这一判断。对负项：主动找全文最可疑的一句，核实来源中是否真有对应事实或条件。逐项给通过/失败/待判。不要把一句正确提醒当作全篇正确。若一般原则写对但本例又无依据地算、比较、把既往当作当下，则对应条件失败。区分转述原账与自行计算。若判断是否为自行计算，除对照草稿写法外，还要查看原始记录是否真的给出该数。原文支持一部分不构成支持其余限制条件。按示例返回 JSON。程序校验行号、引句、来源编号及标签，全文争议交研究复核。"""
def ex(text,pos,neg):
    return ({"正项":"应解释按同次要素计费","负项":"用无单价的记录算费用","答案":{"1":text},"病历":{"1":"周一质量3kg，单价未知。"},"知识":{"E1":"费用=质量×同期单价。"}},
    {k:{"标签":label,"答句行号":1,"决定性原句":text,"病历":[1],"知识":["E1"],"理由":reason}
      for k,(label,reason) in zip(("正项","负项"),(pos,neg))})
PROMPT=v1.prompt(SYS,[
    ex("需同次质量和单价；周一缺单价，费用待核。",("通过","说明同次要素且遵守。"),("通过","无无据结果。")),
    ex("需同次质量和单价；周一单价未知，按其余已知量合计3元。",("失败","仍把非费用的数值写作费用。"),("失败","病历未记3元，原文不许按剩余输入给费用。"))])
async def check(tag,arm):
    root=OUT/tag/arm
    lines={i:s for i,s in enumerate((root/"answer.md").read_text("utf-8").splitlines(),1) if s.strip()}
    _,_,patient,ev=inputs(tag)
    eligible=read(OUT/tag/"comparison.json")["eligible"]
    src={n:e["L5原文"] for n,e in ev.items() if arm=="V1" or n in eligible}
    pos,neg=CHECKS[tag]
    data={"正项":pos,"负项":neg,"答案":lines,"病历":patient,"知识":src}
    val=parse(await call(root/"audit2","countercheck",PROMPT+[v1.message("user",data)],1900))
    assert set(val)=={"正项","负项"}
    for r in val.values():
        assert r["标签"] in ["通过","待判","失败"] and r["理由"].strip()
        assert r["决定性原句"].strip() and r["决定性原句"] in lines[r["答句行号"]]
        displayed={line.split("]")[0][3:] for line in lines.values() if line.startswith("- [E") and "]" in line}
        assert all(k in src or (k in displayed and k.split(".")[0] in src) for k in r["知识"]) and set(r["病历"])<=set(patient)
    save(root/"audit2/result.json",val)

async def main():
    jobs=[check(t,a) for a in sys.argv[1:] for t in CASES]
    results=await asyncio.gather(*jobs,return_exceptions=True)
    for r in results:
        if isinstance(r,BaseException): raise r

if __name__=="__main__":
    asyncio.run(main())
