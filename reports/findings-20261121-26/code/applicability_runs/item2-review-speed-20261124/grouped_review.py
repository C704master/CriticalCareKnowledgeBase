"""Run case-level review with a bounded queue and durable early alerts."""
import argparse
import asyncio
import json
import re
import time
from pathlib import Path

from dotenv import dotenv_values

from prepare_simulation import previous_day_conflict
from specimen_check import unmarked_oxygen
from review_pilot import D, ROOT, DEMOS, SYS, Transport, msg, prepare, read, save


def valid_input(packet):
    for key in ("病例","材料"):
        if not isinstance(packet[key], str) or not packet[key].strip():
            raise ValueError(f"missing {key}")
    rows = packet["待核"]
    ids = [row["编号"] for row in rows]
    if not rows or not all(isinstance(s,str) and s for s in ids) or len(ids)!=len(set(ids)):
        raise ValueError("invalid claim identifiers")
    for row in rows:
        if not row["待核片段"] or row["待核片段"] not in row["所在行"]:
            raise ValueError("claim must be a substring of its answer line")


def messages(packet):
    out = [msg("system",SYS+" 一份病例中有几条待核片段，使用编号作为外层JSON键。逐条给出上述三个字段，不要把不同句子的证据或结论混合。")]
    for text,claim,action,why,quote in DEMOS:
        row={"编号":"X","待核片段":claim,"所在行":claim}
        out.extend([msg("user",{"材料":text,"待核":[row]}),
                    msg("assistant",{"X":{"动作":action,"理由":why,"定位":[quote]}})])
    return out+[msg("user",{"材料":packet["材料"],"待核":packet["待核"]})]


async def run_batch(packets, output, limit, credential, check_specimen=False):
    if limit<1:
        raise ValueError("concurrency must be positive")
    for packet in packets.values():
        valid_input(packet)
    output.mkdir(parents=True,exist_ok=False)
    start=time.monotonic()
    slots=asyncio.Semaphore(limit)
    events=[]
    def emit(case,kind,data):
        event={"case":case,"kind":kind,"ready_s":time.monotonic()-start,**data}
        events.append(event)
        with (output/"events.jsonl").open("a",encoding="utf8") as file:
            file.write(json.dumps(event,ensure_ascii=False)+"\n")
    # Complete cheap local checks for every case before opening remote streams.
    for case,packet in packets.items():
        for row in packet["待核"]:
            alert=previous_day_conflict(packet["病例"],row["待核片段"])
            if alert:
                emit(case,"local_alert",{"ref":row["编号"],**alert})
            if check_specimen:
                alert=unmarked_oxygen(packet["病例"],row["待核片段"])
                if alert:
                    emit(case,"specimen_alert",{"ref":row["编号"],**alert})
    async def review(case,packet):
        async with slots:
            cell=output/case
            t=Transport(cell,cell,credential)
            response=await t.call("review",messages(packet),max_tokens=1600)
            rows=json.loads(re.sub(r"^`{3}(?:json)?\s*|\s*`{3}$","",response["content"].strip()))
            if set(rows)!={row["编号"] for row in packet["待核"]}:
                raise ValueError("incomplete case response")
            raw=packet["材料"].split("【已选证据的适用条件核对】")[0]
            for ref,verdict in rows.items():
                quotes=verdict.get("定位")
                if verdict.get("动作") not in ("提醒","保留") or not isinstance(quotes,list) or len(quotes)>3 or not all(isinstance(s,str) and s.strip() for s in quotes) or not isinstance(verdict.get("理由"),str) or not verdict["理由"].strip():
                    raise ValueError("invalid card")
            cards=[]
            for ref,verdict in rows.items():
                exact=[s for s in verdict["定位"] if s in raw]
                card={"ref":ref,"action":verdict["动作"],"reason":verdict["理由"],"exact":exact,"unlocated":len(verdict["定位"])-len(exact)}
                cards.append(card)
                if card["action"]=="提醒":
                    emit(case,"model_alert",card)
            save(cell/"cards.json",cards)
            emit(case,"complete",{"tokens":t.known_tokens})
    results=await asyncio.gather(*(review(c,p) for c,p in packets.items()),return_exceptions=True)
    for case,result in zip(packets,results):
        if isinstance(result,BaseException):
            emit(case,"failed",{"reason":type(result).__name__})
    save(output/"summary.json",{"seconds":time.monotonic()-start,"limit":limit,"events":events})
    if any(isinstance(result,BaseException) for result in results):
        raise RuntimeError("one or more cases require manual review; see case checkpoints")


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--input-dir",type=Path,help="One JSON per case: 病例, 材料, 待核 (编号, 待核片段, 所在行). Omit to replay the three frozen cases.")
    parser.add_argument("--output",type=Path,default=ROOT/"grouped")
    parser.add_argument("--concurrency",type=int,default=3)
    parser.add_argument("--check-specimen",action="store_true",help="Enable the pilot oxygen-specimen check.")
    args=parser.parse_args()
    if args.input_dir:
        packets={path.stem:read(path) for path in sorted(args.input_dir.glob("*.json"))}
    else:
        packets={}
        for case in ("F28","F25","F30"):
            inp,material,_=prepare(case)
            packets[case]={"病例":read(D/case/"freeze.json")["patient"],"材料":material,"待核":inp["待核"]}
    if not packets:
        parser.error("no case inputs")
    key=dotenv_values(D.parents[2]/"t06_prompt_pilot_20261117/.env")["QWEN_TRIAL_API_KEY"]
    asyncio.run(run_batch(packets,args.output,args.concurrency,key,args.check_specimen))
if __name__=="__main__":
    main()
