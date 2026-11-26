"""Two-case paired audit of source support. No clinical labels are set by code."""
import argparse
import asyncio
import hashlib
import json
import re
import sys
import time
from pathlib import Path

ROOT=Path(__file__).resolve().parent
D=ROOT.parents[1]
sys.path.insert(0,str(D))
from batch_transport import Transport,object_sha,read,save,sha
from dotenv import dotenv_values

PAIRS=[("F28","F25"),("F13","F23"),("F02","F18"),("F04","F11"),("F06","F20"),("F08","F21"),("F10","F14")]
PAIRS += [("F01","F03"),("F05","F07"),("F09","F12"),("F15","F16"),("F17","F19"),("F22","F26")]
RUBRIC="""只核指定片段，参考上下文解释指代。两种裁决：提醒／保留。提醒用于能具体指出的事实、关键限定、原文用途、时间、对象、单位或行动阈值的实质缺口或矛盾；一个独立关键主张失据则该片段提醒。保留忠实转述，以及有病例依据且强度合宜的条件性推断或建议；不因没有引用编号或病例没逐字写出建议而报警。不要以自己的诊疗偏好判断。"""
V1="""你负责给复核者筛查需要查看的临床答句。输入为同一病例的原始材料（含知识原文，末尾若有模型适用说明则仅供辅助）及若干答句。"""+RUBRIC+"""
输出一个JSON对象，外层键与待核编号完全相同，每项仅含定位、理由、动作。先选至多三条原始材料中的连续短句（字符串数组），再用一句话说明具体哪一判断获支持，或哪一项尚缺什么，最后给动作。确定支持前执行一次反向核对：在来源找到相同的数和词后，再核对它们在哪一天、什么标本或部位、哪种患者、用于分期还是处置；若用多个量共同分型，找是否同次测量且对象相符。日档日期与正文中昨日/今晨/既往分开。病例未提病史或未检到实测值属于未知；患者接受过处理只能证明它被实施。趋势须方向和顺序相符，明确提出的建议允许保留；具体新增药量、频次、启动/撤除阈值和无条件诊断必须有匹配的依据。无需抄整段材料。"""
DEMOS=[
 ("4月3日点检记载：昨日甲秤示值9克，今日乙秤示值11克。规则：同一台秤读数超过10克时复测。",
  [("X","4月3日乙秤示值11克，可用乙秤复测。"),("Y","甲秤从4月2日9克升至4月3日11克。")],
  {"X":(["今日乙秤示值11克","同一台秤读数超过10克时复测"],"本日乙秤记录及复测依据均匹配。","保留"),"Y":(["昨日甲秤示值9克","今日乙秤示值11克"],"第二个数字来自乙秤，不能判为甲秤的趋势。","提醒")}),
 ("设备日志：管路读数7，标本未标来源。说明：只有回流端的读数低于8才分为低值组；低值组要复核，不规定时间。",
  [("X","管路读数7，可核对采样位置。"),("Y","设备属于低值组，须每两小时复查。")],
  {"X":(["管路读数7，标本未标来源"],"记录和核实方向相符。","保留"),"Y":(["只有回流端的读数低于8才分为低值组","低值组要复核，不规定时间"],"采样位置未知且材料无此频次。","提醒")})]

def msg(role,body):
    return {"role":role,"content":body if isinstance(body,str) else json.dumps(body,ensure_ascii=False)}

def select_claims(answer,case):
    pool=[]
    for line in answer.splitlines():
        if not line.strip():continue
        for piece in re.split(r"(?<=[。！？；;])",line):
            piece=re.sub(r"^\s*(?:[-*]\s+|\d+[.)、]\s*)","",piece).strip()
            if len(piece)<18 or len(re.findall(r"[\u4e00-\u9fff]",piece))<8:continue
            if not re.search(r"。|；|;|\d|建议|患者|应|监测|评估|提示",piece):continue
            if piece not in [v[0] for v in pool]:pool.append((piece,line))
    if len(pool)<5:raise ValueError("insufficient original claims")
    chosen=[]
    patterns=[r"\d",r"若|超过|阈值|目标|低于|高于",r"\[E\d",r"建议|考虑|可|应|需",r"升|降|患|无|未"]
    for i,pattern in enumerate(patterns):
        eligible=[row for row in pool if row not in chosen and re.search(pattern,row[0])]
        if not eligible:eligible=[row for row in pool if row not in chosen]
        chosen.append(min(eligible,key=lambda x:hashlib.sha256((case+str(i)+x[0]).encode()).digest()))
    return [{"编号":str(i),"待核片段":s,"所在行":line} for i,(s,line) in enumerate(chosen,1)]

def prepare(batch):
    target=ROOT/f"b{batch}"/"input"
    for index,case in enumerate(PAIRS[batch]):
        if batch==0:
            old=D/"applicability_runs/item2-source-audit-20261124"/case/"calls/01_judge/request.json"
            packet=json.loads(read(old)["messages"][-1]["content"])
            data={"材料":packet["原始答题消息"][-1]["content"],"待核":packet["待核"]}
        else:
            arm=("static","loop")[index]
            cell=D/case/arm
            old=next((cell/"calls").glob("*_final/request.json"))
            text=read(old)["messages"][-1]["content"]
            a=(cell/"answer.md").read_text("utf8")
            assert any(read(p)["message"]["content"]==a for p in old.parent.glob("attempt_*/response.json"))
            data={"材料":text,"待核":select_claims(a,case)}
        dest=target/(case+".json")
        if dest.exists(): assert read(dest)==data
        else: save(dest,data)

def prompt(version):
    if version=="v1":return V1
    return V1+"\n"+(ROOT/(version+".txt")).read_text("utf8")

def witnesses(material,rows):
    """Rank verbatim clinical clauses; keep the day header attached to each hit."""
    raw=material.split("【已选证据的适用条件核对】")[0].split("[E1] ")[0]
    terms=[("呼吸衰竭","氧分压|pCO₂|PaO₂|pCO2|FiO₂|动脉血气"),("灌注","乳酸|MAP|血压"),("感染","PCT|CRP|培养")]
    clauses=[]
    header=""
    for line in raw.splitlines():
        if line.startswith("【"):
            header=line
        elif header:
            for clause in re.split(r"[；;。]",line):
                if clause.strip():
                    clauses.append((header,clause.strip()))
    result={}
    for row in rows:
        claim=row["待核片段"]
        grams=set(re.findall(r"(?=([\u4e00-\u9fff]{2}))",claim))
        numbers=set(re.findall(r"\d+(?:\.\d+)?",claim))
        def rank(pair):
            h,s=pair
            score=sum(g in s for g in grams)+3*len(numbers&set(re.findall(r"\d+(?:\.\d+)?",s)))
            for term,pat in terms:
                if term in claim and re.search(pat,s,re.I):score+=9
            return score
        best=sorted(clauses,key=rank,reverse=True)
        result[row["编号"]]=[h+" "+s for h,s in best[:8] if rank((h,s))>0]
    return result

def messages(data,version):
    msgs=[msg("system",prompt(version))]
    for source,rows,out in DEMOS:
        msgs.extend([msg("user",{"材料":source,"待核":[{"编号":i,"待核片段":s,"所在行":s} for i,s in rows]}),
                     msg("assistant",{i:dict(定位=q,理由=r,动作=a) for i,(q,r,a) in out.items()})])
    if version!="v1":
        for idx in (2,4):
            example=json.loads(msgs[idx]["content"])
            for ref,row in example.items():
                row["待核断言"]=next(v for k,v in DEMOS[(idx-2)//2][1] if k==ref)
                row["实证边界"]="；".join(row["定位"])
            msgs[idx]=msg("assistant",example)
        if data:
            data={**data,"材料":data["材料"].split("【已选证据的适用条件核对】")[0]}
            if version not in ("v1","v2","v3"):
                data["自动索引的相关原文（非穷尽）"]=witnesses(data["材料"],data["待核"])
        if version not in ("v1","v2","v3"):
            msgs.extend([
                msg("user",{"材料":"10月2日低值分组规则：须同一时点、取自主出口的甲乙两个指标。10月2日记录甲为4，取样点未注；10月1日乙为3。","待核":[{"编号":"X","待核片段":"当前属于低值组。","所在行":"甲低、乙低，当前属于低值组。"}]}),
                msg("assistant",{"X":{"待核断言":"当前分组已确定。","实证边界":"甲的取样点未注；乙来自前一天。缺同一时点及规定取样点。","定位":["须同一时点、取自主出口","取样点未注","10月1日乙为3"],"理由":"两次低值分别存在，配对条件没有成立。","动作":"提醒"}})])
    msgs.append(msg("user",data))
    return msgs

async def run(batch,version):
    dest=ROOT/f"b{batch}"/version
    dest.mkdir(parents=True,exist_ok=False)
    prefix=messages({},version)[:-1]
    prefixes=[messages({},"v2")[:-1],prefix] if version=="v3" else [prefix]
    save(dest/"freeze.json",{"prompt_sha256":object_sha(prefixes),"cases":list(PAIRS[batch]),"input_sha256":{c:sha(ROOT/f"b{batch}"/"input"/(c+".json")) for c in PAIRS[batch]}})
    key=dotenv_values(D.parents[2]/"t06_prompt_pilot_20261117/.env")["QWEN_TRIAL_API_KEY"]
    async def one(case):
        packet=read(ROOT/f"b{batch}"/"input"/(case+".json"))
        cell=dest/case
        t=Transport(cell,cell,key)
        msgs=messages(packet,version)
        if version=="v3":
            first=messages(packet,"v2")
            historical=ROOT/f"b{batch}"/"v2"/case/"calls/01_audit"
            if historical.exists():
                assert read(historical/"request.json")["messages"]==first
                previous=read(historical/"checkpoint.json")
                replay=read(historical/previous["selected_attempt"]/"response.json")
                assert replay["finish_reason"]=="stop"
                draft=replay["message"]
                save(cell/"draft_replay.json",{"path":str(historical),"sha256":object_sha(draft)})
            else:
                draft=await t.call("initial",first,max_tokens=2200)
            payload=json.loads(msgs[-1]["content"])
            payload["初核意见（须独立核对）"]=draft["content"]
            msgs[-1]=msg("user",payload)
        out=await t.call("audit",msgs,max_tokens=2200)
        result=json.loads(re.sub(r"^`{3}(?:json)?\s*|\s*`{3}$","",out["content"].strip()))
        assert set(result)=={r["编号"] for r in packet["待核"]}
        raw=packet["材料"].split("【已选证据的适用条件核对】")[0]
        for r in result.values():
            assert r["动作"] in ("保留","提醒") and isinstance(r["理由"],str) and r["理由"].strip()
            assert isinstance(r["定位"],list) and all(isinstance(q,str) and q.strip() for q in r["定位"]) and len(r["定位"])<=3
            r["连续引文检查"]=[q in raw for q in r["定位"]]
        save(cell/"judgments.json",result)
    t0=time.monotonic()
    results=await asyncio.gather(*(one(c) for c in PAIRS[batch]),return_exceptions=True)
    save(dest/"timing.json",{"seconds":time.monotonic()-t0,"errors":[str(x) for x in results if isinstance(x,BaseException)]})
    for result in results:
        if isinstance(result,BaseException):raise result

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("batch",type=int,choices=range(len(PAIRS)))
    p.add_argument("--version")
    args=p.parse_args()
    prepare(args.batch)
    if args.version:asyncio.run(run(args.batch,args.version))
