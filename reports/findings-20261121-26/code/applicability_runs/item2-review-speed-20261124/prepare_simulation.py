"""Build matched local review packets. Exclude the reference annotations."""
import json
import re
import time
from datetime import date, timedelta
from pathlib import Path

from review_pilot import ROOT, D, prepare, read, save

def previous_day_conflict(patient, claim):
    """Flag an absolute same-day attribution only for a matching multi-value source passage."""
    if re.search(r"昨日|昨天|前日|回顾|查房记录|记录显示|前一日", claim):
        return None
    stated = re.search(r"(?<!\d)(?:(\d{4})[-/年])?(\d{1,2})[-/月](\d{1,2})(?!\d)", claim)
    if not stated:
        return None
    values = set(re.findall(r"\d+(?:\.\d+)?", claim[stated.end():]))
    if len(values)<2:
        return None
    report_date = None
    for line in patient.splitlines():
        header = re.match(r"【(\d{4}-\d{2}-\d{2})\s",line)
        if header:
            report_date = date.fromisoformat(header[1])
            continue
        if not report_date or (int(stated[2]),int(stated[3])) != (report_date.month,report_date.day):
            continue
        if stated[1] and int(stated[1])!=report_date.year:
            continue
        for match in re.finditer(r"(?:昨日|昨天)[^。；;\n]{1,90}",line):
            passage = match[0]
            if len(values & set(re.findall(r"\d+(?:\.\d+)?",passage)))>=2:
                return {"reason":f"请核对日期：{report_date} 记录回顾的昨日为 {report_date-timedelta(days=1)}。",
                        "exact":[passage]}
    return None

def main():
    example="【2026-08-04 rounds_record】\n昨日读数12，同期读数35。"
    assert previous_day_conflict(example,"08-04读数12，同期35")
    for claim in ("08-03读数12，同期35","08-04查房记录昨日读数12，同期35","08-04读数12，同期53","2025-08-04读数12，同期35"):
        assert previous_day_conflict(example,claim) is None
    root=ROOT/"simulated_review"
    output=[]
    for case in ("F28","F25","F30"):
        inp,material,jobs=prepare(case)
        claims=inp["待核"]
        patient=read(D/case/"freeze.json")["patient"]
        start=time.perf_counter()
        local={row["编号"]:previous_day_conflict(patient,row["待核片段"]) for row in claims}
        local_ms=(time.perf_counter()-start)*1000
        qcards=read(ROOT/"parallel"/case/"summary.json")["cards"]
        assert len(qcards)==len(claims)
        alerts=[]
        for card in qcards:
            ref=card["ref"]
            if card["action"]=="提醒":
                alerts.append({"编号":ref,"疑点":card["reason"],"来源短句":card["exact"],"来源":"模型"})
            if local[ref]:
                alerts.append({"编号":ref,"疑点":local[ref]["reason"],"来源短句":local[ref]["exact"],"来源":"程序"})
        base="待审核句子（只评价每个目标片段）\n"+"\n".join(r["编号"]+" "+r["待核片段"]+"\n所在原行："+r["所在行"] for r in claims)
        full="\n\n原始答题材料（包括原始病历与当时的辅助说明）\n"+material
        extra="\n\n系统提示（仍须判断）\n"+"\n".join(json.dumps(a,ensure_ascii=False) for a in alerts)
        for reviewer in ("R1","R2"):
            assist=(reviewer=="R1")==(case in ("F25",))
            packet=root/reviewer/(case+".txt")
            packet.parent.mkdir(parents=True,exist_ok=True)
            packet.write_text(base+(extra if assist else "")+full,encoding="utf8")
            output.append({"reviewer":reviewer,"case":case,"assisted":assist})
        save(ROOT/"parallel"/case/"alerts.json",{"alerts":alerts,"local_ms":local_ms})
    save(root/"allocation.json",output)
if __name__=="__main__":
    main()
