"""Replay the four F24 source checks from archived responses, without an API call."""
import asyncio
import json
from unittest.mock import patch

import anchored
import claim_review
from paired import OUT, inputs, read, save
from record_guard import record_context, validate_record_claim

# This replay checks the exact messages and outputs of the original no-heading run.
REVIEW_VERSION = "V8_日期给药校验"
ANSWER_VERSION = "V9_日期给药校验"


async def replay():
    case = OUT/"F24"
    calls = []

    async def archived(cell, stage, messages, limit):
        old = case/"V8"/cell.relative_to(case/REVIEW_VERSION)
        for folder in (old, old/"resume_incomplete"):
            call = folder/"calls"/"01_verify"
            response = next(call.glob("attempt_*/response.json"), None)
            if response and read(call/"request.json")["messages"] == messages:
                calls.append(cell.name)
                cell.mkdir(parents=True, exist_ok=True)
                save(cell/"replay_source.json", {"response":str(response.relative_to(case))})
                return read(response)["message"]
        raise RuntimeError(f"no matching historical response for {cell}")

    with patch.object(claim_review, "call", archived), patch.object(claim_review, "REVIEW_VERSION", REVIEW_VERSION):
        await claim_review.run("F24", include_headings=False)
    root = case/REVIEW_VERSION
    assert len(calls) == 4, calls
    decision = read(root/"claim_01/decision.json")
    assert "10月20日至22日持续嗜睡" in decision["内容"]
    medication = read(root/"claim_03/decision.json")
    assert "需核实嗜睡发生的具体时点" in medication["内容"]
    assert "10月21日21:00" not in medication["内容"]
    answer = (root/"answer.md").read_text("utf-8")
    for witness in ["【2026-10-22 orders_execution】 P30.51　[艾司唑仑片(舒乐安定)] 21:00 1mg",
                    "【2026-10-21 orders_execution】 P20.78　22:00 艾司唑仑2mg"]:
        assert witness in answer
    request = read(case/"V7/calls/01_compose/request.json")
    data = json.loads(request["messages"][-1]["content"])
    records = record_context(inputs("F24")[2])
    pieces = data["病历片段"]
    for missing in (["P10.2"], ["P11.1","P16.1"], ["P26.147"]):
        subset = dict(decision, 病历片段=[k for k in decision["病历片段"] if k not in missing])
        try:
            validate_record_claim(subset,pieces,{},records)
        except ValueError as err:
            assert "未逐日覆盖" in str(err)
        else:
            raise AssertionError(f"missing date accepted: {missing}")
    wording = []
    async def archived_wording(cell, stage, messages, limit):
        old = case/"V9"/cell.relative_to(case/ANSWER_VERSION)/"calls"/"01_wording"
        assert messages == read(old/"request.json")["messages"]
        response = next(old.glob("attempt_*/response.json"))
        wording.append(cell.parent.name)
        cell.mkdir(parents=True, exist_ok=True)
        save(cell/"replay_source.json", {"response":str(response.relative_to(case))})
        return read(response)["message"]
    with patch.object(anchored,"call",archived_wording), patch.object(anchored,"REVIEW_VERSION",REVIEW_VERSION), patch.object(anchored,"ANSWER_VERSION",ANSWER_VERSION):
        await anchored.run("F24")
    assert not {"claim_01","claim_03"}.intersection(wording)
    final = (case/ANSWER_VERSION/"answer.md").read_text("utf8")
    assert decision["内容"] in final and medication["内容"] in final
    summary = {"核源历史完整响应回放":len(calls),"措辞历史完整响应回放":len(wording),"新增模型调用":0,"连续日期通过":True,
               "缺少首日中间日末日均拦截":True,"对调给药复述被拦截":True,"日期及执行原句回查":True}
    save(root/"离线回归.json",summary)
    print(json.dumps(summary,ensure_ascii=False))


if __name__=="__main__":
    asyncio.run(replay())
