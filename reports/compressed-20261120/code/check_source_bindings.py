"""Offline regression and mentor sample for the F09 loop's frozen Top 20."""
import asyncio
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

WORKSPACE = Path(__file__).resolve().parent
KB = WORKSPACE.parents[1]
FORMAL = WORKSPACE / "controlled_raw/formal30"
ADAPTER = KB / "workspaces/case10_acceptance_handoff_20261110/outputs/case12_acceptance/qwen38_matched_abc12_20261112"
sys.path[:0] = [str(FORMAL), str(ADAPTER), str(KB)]

from applicability import answer_material, fragment_text
from batch_transport import read
from evidence_selector import build_shortlist, candidate, selection_messages
from kb_adapter import fragment_payload
from query_engine.data_loader import DataLoader

TARGET = "ev_auto_960cbeb65e337e"
SECOND = "ev_auto_ff4bb3ecb1b345"
FIELD = "同文挂载（各自适用）"


class CheckRequest:
    """Exercise request assembly offline. No patient records or clinical verdicts."""
    def __init__(self, expected):
        self.expected = expected

    async def call(self, stage, messages, max_tokens):
        evidence = json.loads(messages[-1]["content"])["证据"]["E1"]
        assert stage == "applicability" and evidence[FIELD] == self.expected
        return {"content": json.dumps({"E1": {
            "拟支持判断": "回放", "原文前提与数值用途": "回放", "原文号": [1], "病历行号": [],
            "本例事实": "未定位", "未知条件": "回放", "等级": "本例缺依据", "允许写到": "回放"}})}


def check():
    cell = FORMAL / "F09/loop"
    ranks = read(cell / "top20.json")
    by_uid = {}
    for path in sorted(cell.glob("query*/candidate_pool.json")):
        by_uid.update(read(path))
    units = [SimpleNamespace(**by_uid[r["uid"]]) for r in ranks]
    loader = DataLoader()
    loader._load_l5()
    def resolve(f):
        return fragment_payload(loader, f)

    shortlist = build_shortlist(units, resolve)
    assert [s["fragment_id"] for s in shortlist] == read(cell / "selector.json")["shortlist"]
    by_text = {s["raw_text"]: s for s in shortlist}
    expected_links = set()
    count = 0
    for unit in units:
        for original in unit.fragments:
            f = resolve(original)
            if not f["raw_text"].strip():
                continue
            count += 1
            expected_links.add((f["raw_text"], unit.unit_id, f["fragment_id"], f["source_id"]))
            matches = [b for b in by_text[f["raw_text"]]["bindings"]
                       if b["L4单元"] == unit.unit_id and b["L5片段"] == f["fragment_id"]
                       and b["来源ID"] == f["source_id"]]
            assert len(matches) == 1
            link = matches[0]
            assert (link["L4规则"], link["适用人群"]) == (unit.operational_rule or None, unit.population_tags)
            assert (link["来源"], link["章节"], link["定位"]) == (f["source_title"], f["section_id"], f["position_hint"])
    assert sum(len(row["bindings"]) for row in shortlist) == len(expected_links)
    number, row = next((i, f) for i, f in enumerate(shortlist, 1) if f["fragment_id"] == TARGET)
    bindings = row["bindings"]
    assert [b["L5片段"] for b in bindings] == [TARGET, SECOND]
    assert len({b["来源ID"] for b in bindings}) == len({b["L4规则"] for b in bindings}) == 2
    payload = candidate(number, row, bindings[0]["L4规则"])
    sent = selection_messages({}, [payload])[-1]["content"]
    assert json.loads(sent)["候选"][0][FIELD] == bindings and sent.count(row["raw_text"]) == 1
    with TemporaryDirectory() as temp:
        text, kept = asyncio.run(answer_material(CheckRequest(bindings), Path(temp),
            {"patient": "回放样本", "prefix": "回放样本\n", "question":"挂载回放", "cutoff":"回放时点"}, [row], ranks))
        assert kept == ["E1"] and read(Path(temp)/"applicability.json")["missing_l4"] == []
        assert text.count("[E1]") == 1 and fragment_text(1, row) in text
        assert json.loads(text.split("同文挂载（各自适用） ", 1)[1].splitlines()[0]) == bindings

    # Repeating a link changes nothing. A change to the original text creates a new candidate.
    unit = SimpleNamespace(**by_uid[row["uid"]])
    assert build_shortlist([unit, unit], resolve) == build_shortlist([unit], resolve)
    different = dict(row, raw_text=row["raw_text"] + "。")
    group = SimpleNamespace(unit_id="unit", unit_title="unit", operational_rule=None,
                            population_tags=[], fragments=[row, different])
    assert len(build_shortlist([group], lambda f: f)) == 2
    other = SimpleNamespace(**{**vars(group), "unit_id": "other", "operational_rule": "另一个条件",
                               "population_tags": ["另一人群"], "fragments": [row]})
    links = build_shortlist([group, other], lambda f: f)[0]["bindings"]
    assert [(b["L4规则"], b["适用人群"]) for b in links] == [(None, []), ("另一个条件", ["另一人群"])]
    legacy = {k:v for k,v in row.items() if k!="bindings"}
    assert fragment_text(1, legacy) == f"[E1] {row['source_title']}（{TARGET}） {row['raw_text']}"
    assert candidate(number, legacy, "旧规则")["L4规则"] == "旧规则"
    return row, number, ranks, count, len(shortlist), len(expected_links), read(cell/"selector.json")["ids"]


def render():
    row, number, ranks, count, unique, links, selected = check()
    lines = ["# F09 动态组 · 同一原文的两条来源与规则", "",
             f"以历史 Top {len(ranks)} 为输入，本地逐字核对 L5 并重建候选。{count} 条非空挂载形成 {unique} 条候选原文，"
             f"候选编号与旧选证清单逐项一致。新版可展开全部 {links} 条不同的来源与规则关系。", "",
             f"**候选 {number} 的完整 L5 原文**", "", "> " + row["raw_text"], "",
             "两条来源记录使用相同章节名称，分别有独立的来源 ID 和 L5 定位。L4 规则中的触发条件属于各自的挂载。", ""]
    for i,b in enumerate(row["bindings"],1):
        rank = next(n for n,r in enumerate(ranks,1) if r["uid"] == b["L4单元"])
        lines += [f"<details><summary>挂载 {i} · {b['来源']} · 单元排第 {rank}</summary>", "",
                  f"- 来源 ID：{b['来源ID']}", f"- 章节与位置：{b['章节']}；{b['定位']}",
                  f"- L5 片段：{b['L5片段']}", f"- L4 单元：{b['L4单元']}（{b['标题']}）",
                  f"- L4 规则原文：{b['L4规则']}", f"- 适用人群：{'、'.join(b['适用人群'])}",
                  "", "</details>", ""]
    status = "已选" if number in selected else "未选"
    lines += [f"**验收范围。** 旧选证回复对此候选的结果为“{status}”。此次回放核对原候选清单，另将该条作为输入，"
              "离线验证选证、答前适用性核查和最终答题消息均可看到两条独立挂载。答前核查使用测试响应，新增模型调用为零。",
              "", "[冻结排名](controlled_raw/formal30/F09/loop/top20.json) · [历史选证结果](controlled_raw/formal30/F09/loop/selector.json) · [离线复验](check_source_bindings.py)", ""]
    return "\n".join(lines)


if __name__ == "__main__":
    print(render())

