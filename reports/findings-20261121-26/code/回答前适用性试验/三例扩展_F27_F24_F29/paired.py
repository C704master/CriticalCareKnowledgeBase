"""Paired replay using the original static evidence and the frozen F28 grading/filter."""
import asyncio
import hashlib
import importlib.util
import json
import re
from pathlib import Path

OUT = Path(__file__).resolve().parent
FORMAL = OUT.parents[1]
CASES = ("F27", "F24", "F29")


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


v1 = load_module("f28_notes", OUT.parent/"F28-static-applicability-v1/run.py")
v2 = load_module("f28_filter", OUT.parent/"F28-static-applicability-v2/run.py")
read, save = v1.read, v1.save
LIMIT = asyncio.Semaphore(3)


def inputs(case):
    c = FORMAL/case
    f = read(c/"freeze.json")
    src = read(c/"static/evidence.json")
    rank = {x["uid"]:x for x in read(c/"static/top20.json")}
    req = read(next((c/"static/calls").glob("*_final/request.json")))
    body = "\n".join(f"[E{i}] {r['source_title']}（{r['fragment_id']}） {r['raw_text']}" for i,r in enumerate(src,1))
    assert req["messages"][-1]["content"] == f["prefix"]+body and f["patient"] in f["prefix"]
    patient = {i:s for i,s in enumerate(f["patient"].splitlines(),1) if s.strip()}
    evidence = {f"E{i}":{"L4规则":rank[r["uid"]]["rule"], "标题":r["title"], "L5原文":v1.segments(r["raw_text"])} for i,r in enumerate(src,1)}
    return f, req, patient, evidence


async def call(cell,stage,msgs,limit):
    cell.mkdir(parents=True,exist_ok=True)
    async with LIMIT:
        return await v1.Transport(cell,cell,v1.KEY).call(stage,msgs,max_tokens=limit)


def parse(msg):
    return json.loads(re.sub(r"^```(?:json)?\s*|\s*```$","",msg["content"].strip()))


async def generate(tag, arm, req, text):
    cell=OUT/tag/arm
    msgs=[dict(m) for m in req["messages"]]
    msgs[-1]["content"]=text
    msg=await call(cell,"final",msgs,req["max_tokens"])
    sent=read(cell/"calls/01_final/request.json")
    assert {k:v for k,v in sent.items() if k!="messages"}=={k:v for k,v in req.items() if k!="messages"}
    (cell/"answer.md").write_text(msg["content"],encoding="utf-8")
    print(tag,arm,"done",flush=True)
    return msg["content"]


async def run(tag):
    f,req,patient,evidence=inputs(tag)
    root=OUT/tag
    data={"原题":f["question"],"截止":f["cutoff"],"病历行":patient,"证据":evidence}
    msg=await call(root/"notes","applicability",v1.PROMPT+[v1.message("user",data)],4800)
    extracted=parse(msg)
    try:
        original=v1.validate(extracted,evidence,patient)
    except ValueError as exc:
        changes={}
        for n,row in extracted.items():
            fact=row.get("本例事实","")
            if row.get("病历行号")==[] and re.fullmatch(r"病历未记录[^。！？；，]+。?",fact):
                changes[n]=fact
                row["本例事实"]="未定位"
        save(root/"首次结构校验.json",{"error":str(exc),"empty_anchor_wording":changes})
        original=v1.validate(extracted,evidence,patient)
    notes={n:original[n] for n in evidence}
    save(root/"适用说明.json",notes)
    appendix="\n\n【已选证据的适用条件核对】以下说明辅助使用上面的原文；保留有依据的数值与用途。遇到条件或病历事实未确认时按条件表达，原始病历与L5原文优先。\n"
    for ref,item in notes.items():
        annotation={k:v for k,v in item.items() if k not in ("原文号","病历行号")}
        annotation["知识原句"]=[evidence[ref]["L5原文"][i] for i in item["原文号"]]
        appendix+=ref+" "+json.dumps(annotation,ensure_ascii=False)+"\n"
    full=req["messages"][-1]["content"]+appendix
    filtered,kept,blocked=v2.filter_evidence(full,f["prefix"],notes)
    for n in blocked:
        assert ("["+n+"] ") not in filtered[len(f["prefix"]):]
    same=(filtered==full)
    save(root/"comparison.json",{"case":tag,"cutoff":f["cutoff"],"eligible":kept,"withheld":blocked,"identical_requests":same,
        "grade_prompt_from":"F28-static-applicability-v1","filter_from":"F28-static-applicability-v2"})
    if same:
        ans=await generate(tag,"V1",req,full)
        cell=root/"V2"
        cell.mkdir(exist_ok=True)
        (cell/"answer.md").write_text(ans,encoding="utf-8")
        save(cell/"replay.json",{"same_request_as":"../V1/calls/01_final/request.json"})
    else:
        await asyncio.gather(generate(tag,"V1",req,full),generate(tag,"V2",req,filtered))


async def main():
    save(OUT/"freeze.json",{"cases":CASES,"standard_sha256":hashlib.sha256((OUT/"开跑前验收标准.md").read_bytes()).hexdigest(),
         "knowledge_source":"original static final input; no new retrieval"})
    results=await asyncio.gather(*(run(tag) for tag in CASES),return_exceptions=True)
    for tag,res in zip(CASES,results):
        if isinstance(res,BaseException):
            print(tag,type(res).__name__,str(res)[:240],flush=True)
            raise res


if __name__=="__main__":
    asyncio.run(main())
