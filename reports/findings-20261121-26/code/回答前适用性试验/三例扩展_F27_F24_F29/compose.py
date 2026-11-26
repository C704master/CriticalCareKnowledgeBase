"""Generate from source spans. Only cited source text can carry measurement results."""
import asyncio
import re
from paired import CASES, OUT, call, inputs, parse, read, save, v1

SYS="""请直接围绕提问编写结构化答复。先选最相关的病历短原句和知识短原句（从输入逐字复制，不改排版、数字和符号），再用自然语言答题。只有原句区可以呈现个体数值或演算结果，正文只说明可判断的内容、意义以及还须核查什么。若某指标缺少必需分项，保留可观察的分项解释其意义，写明缺哪项，不能声称能计算出总量或确定趋势。核对时点、样本属性和干预的适用条件。不要凭知识定义认定患者身上发生过某事件。选材少而具体，避免复述无关病情。对一般方法有用的片段可以解释。若原文过长，仅选关键连续字串。引用编号仅指确实支持这句话的知识。
输出JSON，恰含 病历、知识、回答 三个数组，各一至四条；病历条目为 行号(整数)、摘录；知识条目为 编号、摘录（任一单段内连续原句）；回答条目为 类型、内容、知识编号(数组，可空)。类型枚举：可判断、待核实。内容不写个体数值、日期、算式，不自行给缺项赋值。不把病历行号写进内容。病历数字会由程序和原句一起展示。"""
def ex(line,ev,kind,summary):
    return ({"提问":"这笔交易的运费能核定吗？","病历":{1:line},"知识":{"E1":{"s1":ev}}},
            {"病历":[{"行号":1,"摘录":line}],"知识":[{"编号":"E1","摘录":ev}],
             "回答":[{"类型":kind,"内容":summary,"知识编号":["E1"]}]})
PROMPT=v1.prompt(SYS,[
    ex("同一运单记载已核定运费12元。","正式运单的核定金额可以照录。","可判断","同一运单已有核定费用，可照录。"),
    ex("运单只记质量4千克，费率未记。","计算运费须核对本次费率和质量。","待核实","已有质量记录，缺少本次费率，无法独立核定费用。")])

def checked(val,patient,ev):
    assert set(val)=={"病历","知识","回答"} and all(isinstance(v,list) and 1<=len(v)<=4 for v in val.values())
    facts,refs,claims=[],{},[]
    for row in val["病历"]:
        i,q=row["行号"],row["摘录"]
        assert q.strip() and q in patient[i],("patient span",i,q)
        facts.append(f"- 病历第 {i} 行：{q}")
    for row in val["知识"]:
        n,q=row["编号"],row["摘录"]
        assert q.strip() and any(q in s for s in ev[n]["L5原文"].values()),("knowledge span",n,q)
        refs.setdefault(n,[]).append(q)
    for row in val["回答"]:
        kind,s,ids=row["类型"],row["内容"],row["知识编号"]
        assert kind in ["可判断","待核实"] and s.strip(), ("类型或正文",kind,s)
        assert set(ids)<=set(refs), ("下列引用缺少逐字知识摘录，请补入知识数组或删去该引用", sorted(set(ids)-set(refs)))
        assert not re.search(r"(?<![a-zA-Z\d])[0-9]+(?:[.．][0-9]+)?",s),("unexpected numeric value",s)
        claims.append(f"- **{kind}**　{s}"+ "".join(f"[{n}]" for n in ids))
    return "\n".join(["## 回答","",*claims,"","## 病历依据","",*facts,"","## 知识原文","",
                     *(f"- [{n}] {q}" for n,qs in refs.items() for q in qs)])+"\n"

async def run(tag):
    f,req,patient,all_ev=inputs(tag)
    kept=read(OUT/tag/"comparison.json")["eligible"]
    ev={n:all_ev[n] for n in kept}
    data={"提问":f["question"],"截止":f["cutoff"],"病历":patient,"知识":{n:e["L5原文"] for n,e in ev.items()},
          "适用说明":{n:x for n,x in read(OUT/tag/"适用说明.json").items() if n in ev}}
    root=OUT/tag/"V5"
    messages=PROMPT+[v1.message("user",data)]
    for i in range(4):
        cell=root if i==0 else root/f"repair_{i}"
        response=await call(cell,"compose",messages,2600)
        try:
            val=parse(response)
            answer=checked(val,patient,ev)
        except (AssertionError,KeyError,ValueError,TypeError) as err:
            save(cell/"validation.json",{"error":str(err),"class":type(err).__name__})
            messages=messages+[{"role":"assistant","content":response["content"]},v1.message("user",{"结构或出处检查失败":str(err),"要求":"只纠正校验问题，逐字核对输入中的单个连续原句，删除不合项或换用可定位的原句，按同一格式完整重发。"})]
            continue
        save(root/"structured.json",val)
        (root/"answer.md").write_text(answer,encoding="utf-8")
        return
    raise ValueError(tag+" exhausted source-span checks")

async def main():
    res=await asyncio.gather(*(run(t) for t in CASES),return_exceptions=True)
    for r in res:
        if isinstance(r,BaseException):raise r

if __name__=="__main__":
    asyncio.run(main())
