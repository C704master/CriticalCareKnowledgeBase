"""Reproduce the V21 development decisions from identical saved Qwen requests."""
import re
import sys
from arith import RANGE
from paired_audit import PAIRS, ROOT, read, sha

def selected_version(claim):
    return "v20" if RANGE.search(claim) and re.search(r"\[E\d+\]",claim) else "v19"

def decisions(n):
    folder=ROOT/f"b{n}"
    rows=[]
    for case in PAIRS[n]:
        for record in read(folder/"input"/(case+".json"))["待核"]:
            key=record["编号"]
            version=selected_version(record["待核片段"])
            path=folder/version/case/"judgments.json"
            judgment=read(path)[key]
            rows.append({"case":case,"id":key,"source":version,"source_sha":sha(path),"qwen":judgment["动作"]})
    return rows

if __name__=="__main__":
    n=int(sys.argv[1])
    actual=decisions(n)
    saved=read(ROOT/f"b{n}"/"v21"/"同输入开发回放.json")["rows"]
    assert actual==[{k:r[k] for k in actual[0]} for r in saved]
    print(len(actual),"saved Qwen decisions reproduced")
