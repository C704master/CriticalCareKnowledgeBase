"""Per-number source index and a minimal-edit comparison, using Qwen for both decisions."""
import asyncio
import json
import re
import sys
from pathlib import Path
import calibrated as audit
from paired_audit import msg

EDITOR="""你负责为同行复核拟一条最小改动。先逐项定位句子里的患者事实和知识限定，尤其是日档对应的实测日期；哪些是现在病情、哪些是以往、哪些是医疗建议？再用两个角度回答：如果必须修，哪几个字有确凿理由需要改；如果不修，按通常临床表述能否直接成立。两种理由都写，找不到可靠改动就写无需改。保留可核对的原句/原材料短引文，并最好写明缺的是哪种关系。对资料不足优先问这句话有没有声称资料已经齐备。示例：记录“昨日血糖高，今日未测”，句子“目前仍高”；最小改动“目前仍高→昨日高，今日待测”，保留理由只有此前记录不足以支持现在。记录“昨日血糖高，今日未测”，句子“建议复查”；无需改，复查不预设当前已测。以250字以内交付。"""
base=audit.Transport
def index(doc,claim):
    # Attach actual source headers to bounded verbatim spans containing each number.
    numbers=list(dict.fromkeys(re.findall(r"(?<![\d.])\d+(?:\.\d+)?(?![\d.])",claim)))
    result={}
    for n in numbers:
        pattern=re.compile(r"(?<![\d.])"+re.escape(n)+r"(?![\d.])")
        rows=[];header=""
        for ln in doc.splitlines():
            if ln.startswith("【"):header=ln[:100]
            for m in pattern.finditer(ln):
                snippet=ln[max(0,m.start()-32):m.end()+42]
                if len(ln)>400 and ln.startswith("【"):header=ln[:80]
                row=header+" "+snippet
                if row not in rows:rows.append(row)
        if rows:
            result[n]=rows if len(rows)<=8 else rows[:4]+rows[-4:]
        else:result[n]=[]
    return result
class EditingTransport:
    def __init__(self,batch,cell,key):
        self.cell=cell
        self.inner=base(batch,cell,key)
    async def call(self,stage,messages,max_tokens):
        p=json.loads(messages[-1]["content"]) if messages[-1]["role"]=="user" and messages[-1]["content"].startswith("{") else {}
        if self.cell.name.endswith("-reader"):
            raw=p["实际材料"];cl=p["仅核片段"]
            p["数值在原始材料出现的位置（同数不保证同义）"]=index(raw,cl)
            return await self.inner.call(stage,[msg("system",EDITOR),msg("user",p)],max_tokens=1400)
        if "指定裁决片段" in p:
            c=self.cell.parents[1].name;batch=self.cell.parents[3]
            raw=audit.read(batch/"input"/(c+".json"))["材料"].split("【已选证据的适用条件核对】")[0]
            p["逐数查回的原文与日期（非穷尽，空表示未直接匹配字面）"]=index(raw,p["指定裁决片段"])
            messages=[*messages[:-1],msg("user",p)]
        return await self.inner.call(stage,messages,max_tokens=1400)
if __name__=="__main__":
    audit.Transport=EditingTransport
    audit.JUDGE+="\n意见中的最小修订须解决实质错误，单纯措辞偏好应保留。实现 "+audit.sha(Path(__file__))
    asyncio.run(audit.run(int(sys.argv[1]),sys.argv[2]))
