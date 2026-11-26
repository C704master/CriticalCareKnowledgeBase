"""Compose from complete frozen L5 fragments and explicitly answer the source-supported method."""
import asyncio
from compose import PROMPT as BASE_PROMPT, SYS, checked
from paired import CASES, FORMAL, OUT, call, inputs, parse, read, save, v1

METHOD="""先明确提问者需要完成的判断。请用一项可操作的核实方法直接回答：说明所需观察、各自如何在本对象上取得、测量或事件的先后能否核对。解释变化时，写明具体比较量及应同期配对的量；分析原因时，写明应怎样核对候选原因与表现的先后；解释评定方法时，分清原记录、不可评项和可独立判断的内容。方法引用的文字本身必须包含该方法、指标或判读依据。一个来源只写操作步骤时，不能用它支持另一个来源中的判定指标。仅摘录完整且读得懂的短句。结论应覆盖原题的主要可行解释，留下与判断有关的备选方向，并把尚缺的条件说具体。"""
PROMPT=[dict(BASE_PROMPT[0],content=SYS+"\n"+METHOD),*BASE_PROMPT[1:]]

async def run(tag):
    f,req,patient,ev=inputs(tag)
    kept=read(OUT/tag/"comparison.json")["eligible"]
    original=read(FORMAL/tag/"static/evidence.json")
    visible={n:{"L5原文":{"全文":original[int(n[1:])-1]["raw_text"]}} for n in kept}
    notes=read(OUT/tag/"适用说明.json")
    data={"提问":f["question"],"截止":f["cutoff"],"病历":patient,"知识":{n:e["L5原文"] for n,e in visible.items()},
          "适用说明":{n:notes[n] for n in kept}}
    root=OUT/tag/"V6"
    seed=PROMPT+[v1.message("user",data)]
    messages=seed
    for i in range(5):
        cell=root if i==0 else root/f"repair_{i}"
        response=await call(cell,"compose",messages,3100)
        try:
            val=parse(response)
            answer=checked(val,patient,visible)
        except (AssertionError,KeyError,ValueError,TypeError) as err:
            save(cell/"validation.json",{"error":str(err),"class":type(err).__name__})
            messages=seed+[{"role":"assistant","content":response["content"]},v1.message("user",{"错误":str(err),"要求":"纠正不合要求的内容后按原规范完整重发。知识摘录须来自同一编号。病历摘录须来自指定行的连续文字。所有日期与个体数值只能出现在摘录中；回答中可写指标名称。每条回答引用的编号都需有独立的知识摘录。"})]
            continue
        save(root/"structured.json",val)
        (root/"answer.md").write_text(answer,encoding="utf-8")
        return
    raise ValueError(tag+" exhausted checks")

async def main():
    res=await asyncio.gather(*(run(t) for t in CASES),return_exceptions=True)
    for r in res:
        if isinstance(r,BaseException):raise r

if __name__=="__main__":
    asyncio.run(main())
