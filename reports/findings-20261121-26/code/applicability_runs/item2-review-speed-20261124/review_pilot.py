"""Replay frozen claim-review inputs with a per-case bounded worker pool."""
import argparse
import asyncio
import json
import re
import sys
import time
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parent
D = ROOT.parents[1]
sys.path.insert(0, str(D))
from batch_transport import Transport, object_sha, read, save

AUDIT = D / "applicability_runs/item2-source-audit-20261124"
SYS = """你给临床复核者做来源核查。只审核待核片段，所在行用于理解指代，答题辅助说明也要核实。使用本次给定的原始答题材料。分辨记录日期和事件日期、标本和同期指标、规则人群和用途，及实际执行和应当执行。若只有部分内容有据，写清哪一步缺什么。只在有具体疑点时提醒，输出JSON，字段为动作、理由、定位。动作只能为提醒或保留；保留指该片段在所给材料中有依据。理由只写一句。定位为不超过三个连续短引文组成的数组，尽量取自患者记录或L5正文，带上“昨日”等限定，不要重述为原话。缺直接依据也要给最近的真实对照。程序核对字段、枚举和短引文是否出现，最后由读者裁决。"""
DEMOS = [
    ("日志：昨晚记录温度8度。今天未复测。", "今天温度8度。", "提醒", "读数属于昨晚。", "昨晚记录温度8度"),
    ("08时台秤读数7克。标准：校验下限5克。", "08时读数达校验下限。", "保留", "记录与标准能对应。", "校验下限5克"),
]

def msg(role, obj):
    return {"role": role, "content": obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False)}

def prepare(case):
    old = read(AUDIT / case / "calls/01_judge/request.json")
    inp = json.loads(old["messages"][-1]["content"])
    material = inp["原始答题消息"][-1]["content"]
    prefix = [msg("system", SYS)]
    for text, claim, action, why, quote in DEMOS:
        prefix.extend([msg("user", {"材料": text, "待核片段": claim, "所在行": claim}),
                       msg("assistant", {"动作": action, "理由": why, "定位": [quote]})])
    jobs = {}
    for row in inp["待核"]:
        jobs[row["编号"]] = prefix + [msg("user", {"材料": material, "待核片段": row["待核片段"], "所在行": row["所在行"]})]
    return inp, material, jobs

async def bench(case, mode, limit, key):
    inp, material, jobs = prepare(case)
    cell = ROOT / mode / case
    cell.mkdir(parents=True, exist_ok=False)
    start = time.monotonic()
    sem = asyncio.Semaphore(limit)
    async def work(ref, messages):
        async with sem:
            out = cell / ref
            t = Transport(out, out, key)
            msgout = await t.call("review", messages, max_tokens=550)
            answer = json.loads(re.sub(r"^`{3}(?:json)?\s*|\s*`{3}$", "", msgout["content"].strip()))
            if answer.get("动作") not in ("提醒","保留") or not isinstance(answer.get("理由"),str):
                raise ValueError("review format")
            quotes = answer.get("定位")
            if not isinstance(quotes,list) or len(quotes)>3 or not all(isinstance(q,str) and q.strip() for q in quotes):
                raise ValueError("invalid anchor list")
            raw = material.split("【已选证据的适用条件核对】")[0]
            # Display exact source spans only. A quote that exists only in a model annotation is not source evidence.
            located = [q for q in quotes if q in raw]
            result = {"ref":ref,"action":answer["动作"],"reason":answer["理由"],"exact":located,
                      "unlocated":len(quotes)-len(located),"ready_s":time.monotonic()-start,
                      "tokens":t.known_tokens,"request":object_sha(messages)}
            save(out/"card.json",result)
            return result
    data = await asyncio.gather(*(work(ref, m) for ref,m in jobs.items()),return_exceptions=True)
    errors = [str(x) for x in data if isinstance(x,BaseException)]
    stats = {"seconds":time.monotonic()-start,"cards":[x for x in data if isinstance(x,dict)],"errors":errors}
    save(cell/"summary.json",stats)
    print(case,mode,round(stats["seconds"],1),errors,flush=True)
    if errors:
        raise RuntimeError("incomplete benchmark")

async def main():
    key = dotenv_values(D.parents[2]/"t06_prompt_pilot_20261117/.env")["QWEN_TRIAL_API_KEY"]
    schedule = [("F28","parallel",3),("F28","serial",1),("F25","serial",1),
                ("F25","parallel",3),("F30","parallel",3),("F30","serial",1)]
    for case,mode,limit in schedule:
        await bench(case,mode,limit,key)

if __name__ == "__main__":
    asyncio.run(main())
