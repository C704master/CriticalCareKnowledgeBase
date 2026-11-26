"""Rebuild the final request from the frozen v1 material and applicability grades."""
import asyncio
import re
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parent
V1 = OUT.parent / "F28-static-applicability-v1"
FORMAL = OUT.parents[1]
sys.path.insert(0, str(FORMAL / "全文盲评三例"))
from blind import KEY, Transport, read, save


def filter_evidence(material, prefix, notes):
    if not material.startswith(prefix):
        raise ValueError("病历前缀不一致")
    original, marker, appendix = material[len(prefix):].partition("\n\n【已选证据的适用条件核对】")
    entries = re.split(r"(?m)^(?=\[E\d+\] )", original)
    if entries[0] or not marker:
        raise ValueError("证据边界有误")
    pieces = {piece.split("]", 1)[0][1:]: piece for piece in entries[1:]}
    header, *rows = appendix.splitlines(keepends=True)
    annotations = {row.split(" ", 1)[0]: row for row in rows if row.strip()}
    if list(pieces) != list(notes) or set(annotations) != set(notes):
        raise ValueError("原文、说明和编号未对齐")
    grades = {n: v["等级"] for n, v in notes.items()}
    if set(grades.values()) - {"可用于本例","条件性参考","本例缺依据"}:
        raise ValueError("适用等级异常")
    kept = [n for n in pieces if grades[n] != "本例缺依据"]
    blocked = [n for n in pieces if n not in kept]
    body = "\n".join(pieces[n].rstrip("\r\n") for n in kept)
    return prefix + body + marker + header + "".join(annotations[n] for n in kept), kept, blocked


async def main():
    request = read(V1/"calls/02_final/request.json")
    prefix = read(FORMAL/"F28/freeze.json")["prefix"]
    messages = [dict(m) for m in request["messages"]]
    content, kept, blocked = filter_evidence(messages[-1]["content"], prefix, read(V1/"适用说明.json"))
    messages[-1]["content"] = content
    save(OUT/"design.json", {"run_id":OUT.name,"baseline":V1.name,"eligible":kept,"withheld":blocked,
         "negative":"全文无跨病因外推，包括换编号或未引用的复述","positive":"实测7.0和目标≥6.5均保留且分别有据"})
    t = Transport(OUT, OUT, KEY)
    answer = await t.call("final",messages,max_tokens=request["max_tokens"])
    sent = read(OUT/"calls/01_final/request.json")
    assert {k:v for k,v in request.items() if k!="messages"} == {k:v for k,v in sent.items() if k!="messages"}
    assert messages[:-1] == request["messages"][:-1] and content.startswith(prefix)
    (OUT/"answer.md").write_text(answer["content"], encoding="utf-8")
    save(OUT/"run.json",{"run_id":OUT.name,"calls":t.calls,"cited":re.findall(r"\[E\d+\]",answer["content"])})


if __name__ == "__main__":
    asyncio.run(main())
