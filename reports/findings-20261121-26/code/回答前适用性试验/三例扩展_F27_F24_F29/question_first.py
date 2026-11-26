"""Decide what the question asks before seeing the patient's record, then anchor the answer."""
import asyncio
import re
from paired import CASES, OUT, FORMAL, call, inputs, parse, read, save, v1
from compose import checked
PLAN="仅看提问，不接触患者资料，写出答该题必须回答的判断。只输出最关键的判定指标或分项、需要怎样取得或比较这些量、为避免过度推断须确认什么。限三句。普通方法和缺少条件时的表达均保留。不要做任何患者个体诊断。"
PLAN_MSG=[{"role":"system","content":PLAN},{"role":"user","content":"如何判断两次运费是否上涨？"},{"role":"assistant","content":"先核对两笔运单的实付运费、发货重量和当期费率。条件可比时比较运费；单价或运单缺失时，分别列出已知项目并补核。"}]
TASK="""根据提问、通用答题要点、冻结病历及知识，交付一份简短完整的回答。通用要点仅提示核查方向。回答的首要任务是解释问题本身的判断方法及本例可以用到哪一步。先找直接定义核心指标/机制的原文，回答中必须把最相关指标的具体名称、所需分项及核实步骤写完整。若需对比，写明配对哪些指标和哪些时点；对原因题说明核对哪些暴露与症状发生时间、同时考虑哪些主要解释。只有已成立的事实写为可判断。干预的条件仍缺时保留待核实，不转入治疗路径。
在编写理由时使用定性语言。原始数字和评分只通过引用病历展示，不在正文推算带缺项的总量或重写病例数字。保留指标的规范名称。每条知识引用必须支持该句中相应原则；不得仅凭主题相似引用。病历不可用作一般规则，知识不可用作患者观察。
输出JSON数组，每条含 类型（可判断/待核实）、内容、病历片段（字符串编号数组）、知识片段（字符串编号数组）。给二至四条，整份至少各有一个真实病历和知识编号；知识引用按需。每条只选直接有用的短片段，程序会并列展示原文。"""
def demo(patient,claim,kind):
    return ({"提问":"运费的变化能否确认？","通用要点":"同次运单的费用及依据须可比。","病历片段":{"P1.1":patient},"知识片段":{"E1.1":"可直接比较相同口径的实付运费。"}},
            [{"类型":kind,"内容":claim,"病历片段":["P1.1"],"知识片段":["E1.1"]}])
PROMPT=v1.prompt(TASK,[demo("两笔同类运单核定价分别为5元与8元。","两笔运单计费口径相同，后笔费用较高。","可判断"),demo("仅前笔有收据，后笔只列重量。","缺少后笔同口径的实付运费，暂不能确认是否上涨。","待核实")])

def chunks(text):
    return [m.group().strip() for m in re.finditer(r"[^。；;]+[。；;]?",text) if m.group().strip()]

async def run(tag):
    f,req,patient,_=inputs(tag)
    kept=read(OUT/tag/"comparison.json")["eligible"]
    raw=read(FORMAL/tag/"static/evidence.json")
    ev={n:{"L5原文":{"全文":raw[int(n[1:])-1]["raw_text"]}} for n in kept}
    pp={f"P{i}.{j}":s for i,l in patient.items() for j,s in enumerate(chunks(l),1)}
    kk={f"{n}.{j}":s for n in kept for j,s in enumerate(chunks(ev[n]["L5原文"]["全文"]),1)}
    root=OUT/tag/"V7"
    plan=await call(root/"plan","method",PLAN_MSG+[{"role":"user","content":f["question"]}],480)
    data={"提问":f["question"],"截止":f["cutoff"],"通用要点":plan["content"],"病历片段":pp,"知识片段":kk}
    seed=PROMPT+[v1.message("user",data)]
    msgs=seed
    for i in range(5):
        cell=root if i==0 else root/f"repair_{i}"
        response=await call(cell,"compose",msgs,2600)
        try:
            rows=parse(response)
            assert isinstance(rows,list) and 1<=len(rows)<=4, "回答需为一至四条"
            P,K,A={},{},[]
            for row in rows:
                for k in row["病历片段"]:
                    P[k]={"行号":int(k.split(".")[0][1:]),"摘录":pp[k]}
                for k in row["知识片段"]:
                    K[k]={"编号":k.split(".")[0],"摘录":kk[k]}
                A.append({"类型":row["类型"],"内容":row["内容"],"知识编号":list(dict.fromkeys(k.split(".")[0] for k in row["知识片段"]))})
            assert P and K,"至少引用一处病历、一处知识"
            # The same source may support several observations; validate each independently.
            for a in A:
                selected=[r for r in K.values() if r["编号"] in a["知识编号"]]
                for r in selected: assert r["摘录"] in ev[r["编号"]]["L5原文"]["全文"]
                assert a["类型"] in ["可判断","待核实"] and a["内容"].strip()
                assert not re.search(r"(?<![a-zA-Z\d])[0-9]+",a["内容"]),("病例值/日期请通过片段展示，正文只保留定性判断和指标名",a["内容"])
            val={"病历":list(P.values()),"知识":list(K.values()),"回答":A}
            for r in P.values():assert r["摘录"] in patient[r["行号"]]
        except (AssertionError,KeyError,ValueError,TypeError) as e:
            save(cell/"validation.json",{"error":str(e)})
            msgs=seed+[{"role":"assistant","content":response["content"]},v1.message("user",{"请修正并完整重发":str(e)})]
            continue
        lines=["## 回答",""]
        for a,row in zip(A,rows):
            lines.append("- **"+a["类型"]+"**　"+a["内容"]+"".join("["+n+"]" for n in a["知识编号"]))
            lines.extend("  - 病历 "+k+"　"+pp[k] for k in row["病历片段"])
        lines.extend(["","## 知识原文",""]+["- ["+k+"] "+kk[k] for k in K])
        (root/"answer.md").write_text("\n".join(lines)+"\n",encoding="utf8")
        save(root/"structured.json",val)
        return
    raise ValueError(tag+" exhausted checks")

async def main():
    r=await asyncio.gather(*(run(t) for t in CASES),return_exceptions=True)
    for x in r:
        if isinstance(x,BaseException):raise x
if __name__=="__main__":asyncio.run(main())
