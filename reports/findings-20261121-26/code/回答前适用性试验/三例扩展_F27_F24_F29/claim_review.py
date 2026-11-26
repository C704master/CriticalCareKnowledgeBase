"""Verify each proposed claim using only its selected sources; render the verified wording."""
import asyncio
import json
from paired import CASES, OUT, call, inputs, parse, read, save, v1
from record_guard import REVIEW_VERSION, line_number, record_context, validate_record_claim

SYS="""你每次只核对一句。给你问题、一句候选答复及其实际引用的病历/知识短原文。请逐项问：哪部分是本次观察，哪部分只是一般机制？取样属性、时点、分项、配对条件、诊断和处置前提能否从所给出处复现？停止把病历没记录的细节或来源只谈到的一般机制写成个体事实。若夹杂推测，保留有用的部分并把待证原因写作待核实。若来源明确给出通用指标，解释该指标在本例的核查方法。不得凭材料缺项假定患者已有某一病情或为其补值。不要把单个文档事件的时间当作测量时间。使用最少且直接支持本句的知识片段，按实际需要选病历片段。
输出一个JSON对象：处置枚举 保留/改写/删除；类型枚举 可判断/待核实；内容（最后交稿的短句，避免复写数字，直接照录的事实会在下方展示）；病历片段、知识片段（只能取自本次给定的编号）；理由（不进正文）。"""
def example(text,kind,ver,claim,reason):
    return ({"问题":"运费能核实吗？","候选":text,"病历":{"P1":"本单记质量3kg，未列费率。"},"知识":{"E1":"计算费用须有同次质量和费率。"}},
            {"处置":ver,"类型":kind,"内容":claim,"病历片段":["P1"],"知识片段":["E1"],"理由":reason})
PROMPT=v1.prompt(SYS,[example("需补核本次费率。","待核实","保留","尚需核对本次费率才能计算。","缺费率。"),example("已确认费用上涨，应补扣。","待核实","改写","只有质量记录，缺本单费率，费用及变化尚不能确认。","计费规则不证明本次费用上涨。")])

def build_review_input(question, row, pp, kk, records, *, include_headings=True):
    ps={k:pp[k] for k in row["病历片段"]}
    ks={k:kk[k] for k in row["知识片段"]}
    # Attach all neighbouring pieces of the same original line when a clause starts mid-record.
    context={k:pp[k] for k in pp if any(k.rsplit(".",1)[0]==n.rsplit(".",1)[0] and abs(int(k.split(".")[-1])-int(n.split(".")[-1]))<=1 for n in ps)}
    def present(pieces):
        if not include_headings:
            return pieces
        result = {}
        for key, quote in pieces.items():
            heading = records[line_number(key)][0]
            result[key] = f"{heading} {quote}" if heading else quote
        return result

    return {"问题":question,"候选":row["内容"],"病历":present(ps),
            "同一病历相邻片段":present(context),"知识":ks}

async def one(tag,i,question,row,pp,kk,records, *, include_headings=True):
    root=OUT/tag/REVIEW_VERSION/f"claim_{i:02}"
    data=build_review_input(question,row,pp,kk,records,include_headings=include_headings)
    base=PROMPT+[v1.message("user",data)]
    msgs=base
    for attempt in range(3):
        cell=root if attempt==0 else root/f"repair_{attempt}"
        if (cell/"calls").exists() and not list(cell.glob("calls/*/attempt_*/response.json")):
            cell=cell/"resume_incomplete"
        response=await call(cell,"verify",msgs,750)
        try:
            r=parse(response)
            assert r["处置"] in ["保留","改写","删除"] and r["类型"] in ["可判断","待核实"] and r["理由"].strip()
            if r["处置"]!="删除":
                assert set(r["病历片段"])<=set(data["同一病历相邻片段"]) and set(r["知识片段"])<=set(data["知识"])
                body=r["内容"].strip()
                assert body and (r["病历片段"] or r["知识片段"]),"需定位来源"
                r, action=validate_record_claim(r,pp,kk,records)
                if action:
                    save(cell/"record_check.json",action)
            save(root/"decision.json",r)
            return r
        except (AssertionError,ValueError,KeyError,TypeError) as e:
            save(cell/"validation.json",{"error":str(e)})
            msgs=base+[v1.message("assistant",response["content"]),v1.message("user",{"请修正并完整返回":str(e)})]
    raise ValueError((tag,i))
async def run(tag, *, include_headings=True):
    source=OUT/tag/"V7/calls/01_compose"
    data=json.loads(read(source/"request.json")["messages"][-1]["content"])
    rows=parse(read(next(source.glob("attempt_*/response.json")))["message"])
    pp,kk=data["病历片段"],data["知识片段"]
    records=record_context(inputs(tag)[2])
    res=await asyncio.gather(*(one(tag,i,data["提问"],r,pp,kk,records,include_headings=include_headings) for i,r in enumerate(rows,1)),
                             return_exceptions=True)
    for result in res:
        if isinstance(result,BaseException):
            raise result
    P,K,A={},{},[]
    lines=["## 回答",""]
    for r in res:
        if r["处置"]=="删除":continue
        refs=list(dict.fromkeys(k.split(".")[0] for k in r["知识片段"]))
        A.append({"类型":r["类型"],"内容":r["内容"],"知识编号":refs})
        lines.append("- **"+r["类型"]+"**　"+r["内容"]+"".join("["+n+"]" for n in refs))
        for k in r["病历片段"]:
            P[k]={"行号":int(k.split(".")[0][1:]),"摘录":pp[k]}
            lines.append("  - "+records[line_number(k)][0]+" "+k+"　"+pp[k])
        for k in r["知识片段"]:K[k]={"编号":k.split(".")[0],"摘录":kk[k]}
    assert P and K and A,"no anchors"
    root=OUT/tag/REVIEW_VERSION
    save(root/"structured.json",{"回答":A,"病历":list(P.values()),"知识":list(K.values())})
    lines.extend(["","## 知识原文",""]+["- ["+k+"] "+kk[k] for k in K])
    (root/"answer.md").write_text("\n".join(lines)+"\n",encoding="utf8")
async def main():
    results=await asyncio.gather(*(run(t) for t in CASES),return_exceptions=True)
    for result in results:
        if isinstance(result,BaseException):
            raise result
if __name__=="__main__":asyncio.run(main())
