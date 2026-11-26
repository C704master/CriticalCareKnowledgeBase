"""Resume after a rejected response, sending explicit validation errors to the model."""
import asyncio
import re
import sys
from compose import checked
from paired import OUT, call, inputs, parse, read, save, v1

async def resume(tag):
    root=OUT/tag/"V5"
    _,_,patient,all_ev=inputs(tag)
    ev={n:all_ev[n] for n in read(OUT/tag/"comparison.json")["eligible"]}
    last=root/"repair_3"
    initial=read(root/"calls/01_compose/request.json")["messages"]
    for i in range(4,8):
        old=read(next(last.glob("calls/*/attempt_*/response.json")))["message"]["content"]
        val=parse({"content":old})
        refs={r["编号"] for r in val["知识"]}
        issues=[]
        for r in val["回答"]:
            missing=set(r["知识编号"])-refs
            if missing:issues.append("下列已引编号必须从可见原文选择一段连续摘录加入知识数组，或删除无依据的引用："+str(sorted(missing)))
            if re.search(r"(?<![a-zA-Z\d])[0-9]+",r["内容"]):issues.append("将这条正文中的日期、测量值移至病历摘录，正文只写定性判断："+r["内容"])
        try:
            checked(val,patient,ev)
        except (AssertionError,ValueError,KeyError,TypeError) as exc:
            issues.append(str(exc))
        last=root/f"repair_{i}"
        msg=await call(last,"compose",initial+[v1.message("assistant",val),v1.message("user",{"须修正":issues,"要求":"连接本题的核实方法及知识原文，交回完整JSON。只有实际支持语句的来源才可引用。"})],2600)
        try:
            val=parse(msg)
            answer=checked(val,patient,ev)
        except (AssertionError,KeyError,TypeError,ValueError) as e:
            save(last/"validation.json",{"error":str(e)})
            continue
        save(root/"structured.json",val)
        (root/"answer.md").write_text(answer,encoding="utf-8")
        return
    raise ValueError("validation failed")
if __name__=="__main__":
    asyncio.run(resume(sys.argv[1]))
