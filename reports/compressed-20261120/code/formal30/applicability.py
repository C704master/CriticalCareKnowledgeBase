"""Answer-time applicability check. The grading prompt is frozen from the F28 pilot."""
import json
import re
from batch_transport import save
from evidence_selector import rule_fields

def message(role, value):
    return {'role':role,'content':value if isinstance(value,str) else json.dumps(value,ensure_ascii=False)}


def prompt(system, examples):
    messages = [message('system',system)]
    for inp, output in examples:
        messages.extend((message('user',inp),message('assistant',output)))
    return messages


def segments(source):
    parts=re.findall(r'[^。！？；\n]+[。！？；]?|[。！？；\n]',source)
    assert ''.join(parts)==source
    return {i:s for i,s in enumerate(parts,1)}


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


def fragment_text(number, row):
    text = f"[E{number}] {row['source_title']}（{row['fragment_id']}） {row['raw_text']}"
    if len(row.get("bindings", [])) > 1:
        text += "\n同文挂载（各自适用） " + json.dumps(row["bindings"], ensure_ascii=False)
    return text


async def answer_material(transport, cell, frozen, selected, ranks):
    patient = {i: s for i, s in enumerate(frozen["patient"].splitlines(), 1) if s.strip()}
    if frozen["patient"] not in frozen["prefix"]:
        raise ValueError("patient missing from answer prefix")
    rules = {row["uid"]: row["rule"] for row in ranks}
    evidence = {
        f"E{i}": {**rule_fields(row, rules[row["uid"]] or "未提供"), "标题": row["title"],
                  "L5原文": segments(row["raw_text"])}
        for i, row in enumerate(selected, 1)
    }
    notes = {}
    if evidence:
        payload = {"原题": frozen["question"], "截止": frozen["cutoff"], "病历行": patient, "证据": evidence}
        msgs = PROMPT + [message("user", payload)]
        reply = await transport.call("applicability", msgs, max_tokens=4800)
        data = json.loads(re.sub(r"^`{3}(?:json)?\s*|\s*`{3}$", "", reply["content"].strip()))
        for row in data.values():
            if row.get("病历行号") == [] and re.fullmatch(r"病历未记录[^。！？；，]+。?",row.get("本例事实","")):
                row["本例事实"] = "未定位"
        notes = validate(data, evidence, patient)
    kept = list(evidence)
    missing_l4 = []
    for i, row in enumerate(selected, 1):
        bindings = row.get("bindings")
        has_rule = any(b["L4规则"] for b in bindings) if bindings else bool(rules[row["uid"]])
        if not has_rule:
            missing_l4.append(f"E{i}")
    save(cell/"applicability.json", {"notes":notes, "eligible":kept, "withheld":[],
                                     "missing_l4":missing_l4})
    text = frozen["prefix"] + "\n".join(fragment_text(int(n[1:]),selected[int(n[1:])-1]) for n in kept)
    if kept:
        text += "\n\n【已选证据的适用条件核对】以下说明辅助使用上面的原文；保留有依据的数值与用途。遇到条件或病历事实未确认时按条件表达，原始病历与L5原文优先。\n"
        for n in kept:
            annotation = {k:v for k,v in notes[n].items() if k not in ("原文号","病历行号")}
            annotation["知识原句"] = [evidence[n]["L5原文"][i] for i in notes[n]["原文号"]]
            text += n+" "+json.dumps(annotation,ensure_ascii=False)+"\n"
    return text, kept

