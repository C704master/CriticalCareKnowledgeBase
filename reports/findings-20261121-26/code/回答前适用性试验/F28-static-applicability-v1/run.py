"""Replay the frozen F28 static answer, adding a source-bound applicability note."""
import asyncio
import hashlib
import json
import re
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parent
FORMAL = OUT.parents[1]
BASE = FORMAL / "选证改版核查/独立三题_F30_F28_F26/F28/static"
sys.path.insert(0, str(FORMAL / "全文盲评三例"))
from anchors import segments
from blind import KEY, Transport, message, prompt, read, save

LEVELS = {"可用于本例", "条件性参考", "本例缺依据"}
SYS = """你是答题前的依据核查员。根据原题、截止时间、带行号的病例以及已选的L4规则和完整L5原文，为每个E编号限定一句可用于答题的判断。不要撰写整份答案。
以L5为文字依据，L4用于理解范围。核对适用对象、必要条件、例外、数值的原用途、单位和强度。病例里的事实必须可回到病例行号，读清日期和“昨日”等相对时间。原题提供的背景可用但不要当成测量。材料没有提及的前提记为未知，不能推为不存在。
输出仅为JSON对象，每个E编号对应一条。字段为拟支持判断、原文前提与数值用途、原文号、本例事实、病历行号、未知条件、等级、允许写到。原文号和病历行号是整数数组。缺少病历事实时本例事实填“未定位”，病历行号给空数组。不得拼造数字。
等级为可用于本例、条件性参考、本例缺依据。判断可具体到一个有来源的子问题；不能把观察值改成目标、把分层标准改成干预指征。条件性参考需交代条件和局限。来源的对象或用途无法对应本例且没有依据支持外推时，仅说明其边界。保留有依据的建议和数字。程序逐条检查编号、字段、枚举和锚点，使用者据原文复核语义。"""

def demo(question, case, rule, text, claim, condition, fact, unknown, level, limit):
    return (
        {"原题": question, "截止": "演示时点", "病历行": {1: case},
         "证据": {"E1": {"L4规则": rule, "L5原文": {1: text}}}},
        {"E1": {"拟支持判断": claim, "原文前提与数值用途": condition, "原文号": [1],
                "本例事实": fact, "病历行号": [1], "未知条件": unknown, "等级": level, "允许写到": limit}}
    )

PROMPT = prompt(SYS, [
    demo("如何核对设备读数？", "自动秤显示8克。", "核对自动秤的读数。", "自动秤的测试目标为至少5克。",
         "自动秤读数是否达到测试目标", "自动秤；5克为测试目标下限。", "自动秤实测8克。", "无",
         "可用于本例", "实测8克达到至少5克的测试目标。"),
    demo("手动设备应等待多久？", "记录为手动设备，正在校验。", "校验时等待。", "自动设备通电后应等待两分钟。",
         "确定手动设备校验的时长", "两分钟限于自动设备通电后。", "设备为手动。", "手动设备的等待规范未提供。",
         "本例缺依据", "此条无法确定手动设备的等待时长。")
])

def validate(obj, evidence, patient):
    if not isinstance(obj, dict) or set(obj) != set(evidence):
        raise ValueError("证据编号缺失或多出")
    for ref, item in obj.items():
        for field in ("拟支持判断", "原文前提与数值用途", "本例事实", "未知条件", "允许写到"):
            if not isinstance(item.get(field), str) or not item[field].strip():
                raise ValueError(f"{ref} 缺字段 {field}")
        if item.get("等级") not in LEVELS:
            raise ValueError(f"{ref} 等级无效")
        for field, source in [("原文号", evidence[ref]["L5原文"]), ("病历行号", patient)]:
            ids = item.get(field)
            if not isinstance(ids, list) or any(type(i) is not int or i not in source for i in ids):
                raise ValueError(f"{ref} {field}越界")
        if not item["原文号"] or (not item["病历行号"] and item["本例事实"] != "未定位"):
            raise ValueError(f"{ref} 缺定位")
    return obj

async def main():
    frozen = read(FORMAL/"F28/freeze.json")
    prior = read(BASE/"calls/02_final/request.json")
    prefix = frozen["prefix"]
    material = prior["messages"][-1]["content"]
    assert material.startswith(prefix) and frozen["patient"] in prefix
    parts = re.split(r"(?m)^\[(E\d+)\] ", material[len(prefix):])
    bodies = dict(zip(parts[1::2], parts[2::2]))
    selected = read(BASE/"comparison.json")["new_ids"]
    candidates = json.loads(read(BASE/"calls/01_plan/request.json")["messages"][-1]["content"])["候选"]
    evidence = {}
    for i, n in enumerate(selected, 1):
        c = candidates[n-1]
        ref = f"E{i}"
        raw = c["L5原文"]
        assert bodies[ref].rstrip("\r\n").endswith(f"（{c['L5片段']}） {raw}".rstrip("\r\n"))
        evidence[ref] = {"L4规则": c["L4规则"], "标题": c["标题"], "L5原文": segments(raw)}
    assert len(evidence) == len(bodies) == 10
    patient = {i:s for i,s in enumerate(frozen["patient"].splitlines(),1) if s.strip()}
    data = {"原题":frozen["question"], "截止":frozen["cutoff"], "病历行":patient, "证据":evidence}
    t = Transport(OUT, OUT, KEY)
    first = await t.call("applicability", PROMPT+[message("user",data)], max_tokens=4800)
    notes = validate(json.loads(re.sub(r"^```(?:json)?\s*|\s*```$","",first["content"].strip())), evidence, patient)
    save(OUT/"适用说明.json",notes)
    appendix = "\n\n【已选证据的适用条件核对】以下说明辅助使用上面的原文；保留有依据的数值与用途。遇到条件或病历事实未确认时按条件表达，原始病历与L5原文优先。\n"
    for ref, item in notes.items():
        annotation = {k:v for k,v in item.items() if k not in ("原文号","病历行号")}
        annotation["知识原句"] = [evidence[ref]["L5原文"][i] for i in item["原文号"]]
        appendix += ref+" "+json.dumps(annotation,ensure_ascii=False)+"\n"
    msgs = [dict(m) for m in prior["messages"]]
    msgs[-1]["content"] += appendix
    second = await t.call("final",msgs,max_tokens=prior["max_tokens"])
    sent = read(OUT/"calls/02_final/request.json")
    assert {k:v for k,v in sent.items() if k!="messages"}=={k:v for k,v in prior.items() if k!="messages"}
    assert msgs[:-1]==prior["messages"][:-1] and msgs[-1]["content"]==material+appendix
    (OUT/"answer.md").write_text(second["content"],encoding="utf-8")
    save(OUT/"run.json",{"run_id":OUT.name,"baseline":"F28-static-l4l5-holdout","evidence_order":selected,
         "baseline_answer_sha256":hashlib.sha256((BASE/"answer.md").read_bytes()).hexdigest(),
         "baseline_final_request_sha256":hashlib.sha256((BASE/"calls/02_final/request.json").read_bytes()).hexdigest(),
         "same_final_parameters":True,"same_patient_and_ordered_evidence":True,"calls":t.calls})

if __name__=="__main__":
    asyncio.run(main())
