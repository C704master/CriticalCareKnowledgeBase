"""Reconcile a frozen formal30 loop run with the requests actually sent to the planner."""
import argparse
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parent
KB = WORKSPACE.parents[1]
sys.path.insert(0, str(KB))
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def require(condition, message):
    if not condition:
        raise ValueError(message)


def unit_order(folder, query, data):
    from query_engine.retriever import RetrievedUnit
    from query_engine.sorter import rank_units_v2

    pool = read(folder / "candidate_pool.json")
    retrieval, = read(folder / "retrieval.json")
    selected = read(folder / "selected_evidence.json")
    snapshot = folder / "fusion_order.json"
    if snapshot.exists():
        order = read(snapshot)
        require(len(order) == len(pool) and set(order) == set(pool), "排名快照与候选池不符")
    else:
        vector = data.bge_encode_query(query)
        require(vector is not None, "本地 embedding 不可用")
        scores = data.l4_cosine_scores(vector, list(pool))
        require(scores is not None and set(scores) == set(pool), "冻结候选缺少可复算的向量")
        units = [RetrievedUnit(**(pool[uid] | {"_semantic_score": scores[uid], "_reranker_score": None}))
                 for uid in sorted(pool)]
        order = [u.unit_id for u in rank_units_v2(units)]
        require(all(abs(scores[v["unit_id"]] - v["semantic_score"]) < 1e-5 for v in selected),
                "复算语义分与当时记录不符")
    kept = [v["unit_id"] for v in selected]
    omitted = [v["unit_id"] for v in retrieval["omitted"]]
    kept_set = set(kept)
    require(retrieval["query"] == query and kept == retrieval["selected_unit_ids"], "检索记录不匹配")
    require([uid for uid in order if uid in kept_set] == kept and
            [uid for uid in order if uid not in kept_set] == omitted, "复算排序与历史保留/省略顺序不符")
    return pool, order, selected


def make_report(cell, data, output_directory):
    history = read(cell / "history.json")
    requests = [(p, json.loads(read(p)["messages"][-1]["content"]))
                for p in sorted((cell / "calls").glob("*_plan/request.json"))]
    seen_in = {}
    for p, body in requests:
        if "已查" in body:
            prefix = body["已查"]
            require(prefix == history[:len(prefix)], "规划请求与检索历史不符")
            for r in range(1, len(prefix) + 1):
                seen_in.setdefault(r, p.parent.name)

    all_units, hits, weights = {}, [], Counter()
    for r, record in enumerate(history, 1):
        pool, order, selected = unit_order(cell / f"query{r}", record["query"], data)
        all_units.update(pool)
        positions = {uid: pos for pos, uid in enumerate(order, 1)}
        for uid, pos in positions.items():
            weights[uid] += 1 / (60 + pos)
        fragments = []
        for item in selected:
            unit = json.loads(item["content"])
            for f in unit["fragments"]:
                if f["raw_text"].strip():
                    fragments.append((item, f, unit["unit_title"]))
        first = fragments[:8]
        require([{"title": title, "fragment_id": f["fragment_id"]} for _, f, title in first]
                == record["hits"], "无法按历史位置还原片段")
        for pos, (item, f, title) in enumerate(first, 1):
            uid = item["unit_id"]
            hits.append((r, pos, uid, f, title, positions[uid],
                         item["semantic_score"], pool[uid]["_reranker_score"]))

    ranked = sorted(weights, key=lambda uid: (-weights[uid], uid))
    final_pos = {uid: i for i, uid in enumerate(ranked, 1)}
    top = [v["uid"] for v in read(cell / "top20.json")]
    require(ranked[:20] == top, "复算的融合前20与冻结记录不同")
    shortlist, by_text = [], {}
    for uid in top:
        for f in all_units[uid]["fragments"]:
            text = f["content"]
            if text.strip() and text not in by_text:
                shortlist.append((uid, f["fragment_id"]))
                by_text[text] = len(shortlist)
    selector = read(cell / "selector.json")
    require([fid for _, fid in shortlist] == selector["shortlist"], "历史选证候选不匹配")
    select_calls = [(p, body["候选"]) for p, body in requests if "候选" in body]
    require(len(select_calls) == 1, "未定位到唯一选证请求")
    select_request, sent = select_calls[0]
    call = select_request.parent
    require(len(sent) == len(shortlist), "选证请求的候选数量不符")
    for n, ((uid, fid), item) in enumerate(zip(shortlist, sent), 1):
        unit = all_units[uid]
        text = next(f["content"] for f in unit["fragments"] if f["fragment_id"] == fid)
        if isinstance(item, list):  # Earlier requests carried a numbered title and excerpt.
            number, title, quote = item
        else:
            number, title, quote = item["编号"], item["标题"], item["L5原文"]
            require(item["L4单元"] == uid and item["L5片段"] == fid, "选证请求的单元或片段不符")
        require(number == n and title == unit["unit_title"] and quote and quote in text,
                f"选证请求候选 {n} 与原始材料不符")
    checkpoint = read(call / "checkpoint.json")
    response = read(call / checkpoint["selected_attempt"] / "response.json")
    require(response["finish_reason"] == "stop", "选证响应未完整结束")
    raw = response["message"]["content"].strip()
    payload = json.loads(re.sub(r"^`{3}(?:json)?\s*|\s*`{3}$", "", raw))
    ids = payload["ids"] if "ids" in payload else [v["编号"] for v in payload["选择"]]
    require(ids == selector["ids"], "实际模型选证与登记不符")
    ev = read(cell / "evidence.json")
    require([shortlist[i-1] for i in ids] == [(v["uid"], v["fragment_id"]) for v in ev],
            "选证次序与最终证据不符")
    final_calls = list(cell.glob("calls/*_final/request.json")) + list(cell.glob("answer_stage/calls/*_final/request.json"))
    require(len(final_calls) == 1, "未定位到唯一的最终答题请求")
    final = read(final_calls[0])["messages"][-1]["content"]
    for i, v in enumerate(ev, 1):
        require(f"[E{i}] {v['source_title']}（{v['fragment_id']}） {v['raw_text']}" in final,
                "最终答题请求缺少相应证据")
    evidence_no = {k: n for n, k in enumerate(ids, 1)}

    lines = [f"# {cell.parent.name} 动态组 · 规划器与最终排名对照", "",
             f"{len(history)} 轮检索，共 {len(ranked)} 个不同 L4 单元。表中每行表示一次检索返回中的一个 L5 片段；“规划请求”标出它首次实际送入的后续规划请求。最后一轮如无后续规划请求，单列为未送达。",
             "", "单轮与融合名次按 L4 单元计算。融合分为各轮 1/(60+单轮名次) 之和，同分按单元 ID 排列。语义分取当时记录；上游重排分取候选快照。实验入口在单轮重算时显式清空重排分，排序使用语义分和来源分组。空值不计作零分。",
             "", "| 检索轮·片段位 | 规划请求 | 片段 ID | L4 单元 / 标题 | 单轮L4名次 | 语义分 | 上游重排分 | 融合名次 / 分数 | 选证候选号 | 最终位置或去向 |",
             "|---|---|---|---|---:|---:|---:|---:|---:|---|"]
    for r, pos, uid, f, title, rank, semantic, rerank in hits:
        number = by_text.get(f["raw_text"])
        if final_pos[uid] > 20:
            result = "所属单元未进前20"
            number = None
        elif number is None:
            raise ValueError("前20原文未能定位")
        elif shortlist[number-1] != (uid, f["fragment_id"]):
            result = "同文合并到候选 " + str(number)
        elif number in evidence_no:
            result = f"E{evidence_no[number]} 已入模"
        else:
            result = "已送选证，回复未列此编号"
        title = title.replace("|", "&#124;")
        score = "空" if rerank is None else str(rerank)
        lines.append(f"| {r}·{pos} | {seen_in.get(r,'未送达')} | {f['fragment_id']} | {uid} / {title} | {rank} | {semantic:.6f} | {score} | {final_pos[uid]} / {weights[uid]:.8f} | {number or '—'} | {result} |")
    prefix = Path(os.path.relpath(cell, output_directory)).as_posix()
    count_seen = sum(r in seen_in for r, *_ in hits)
    lines += ["", f"**核对结果。** {len(hits)} 个片段位置中，{count_seen} 个进入过后续规划请求。"
              f"融合前 {len(top)} 个单元的顺序全部与旧表相符。选证请求的 {len(sent)} 个候选逐项核对过编号、标题和原文，"
              f"选出的 {len(ev)} 条均能在最终请求中按编号找到原文。",
              "", "“回复未列此编号”记录淘汰发生在选证阶段。这次旧选证回复仅返回入选编号，无法从中还原对未选片段的临床判断。"
              "单轮顺序优先取运行快照；缺少快照的历史轮次用本地向量复算，并与当时记录的语义分、保留顺序和省略顺序核对。",
              "", f"[实际规划与选证请求]({prefix}/calls/) · [冻结的最终前20]({prefix}/top20.json) · "
              f"[入选编号]({prefix}/selector.json) · [最终入模证据]({prefix}/evidence.json)", ""]
    return "\n".join(lines)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case", choices=[f"F{i:02}" for i in range(1, 31)])
    parser.add_argument("output", type=Path)
    parser.add_argument("--run-id", help="读取指定的非冻结检索实验，而非旧30例记录")
    args = parser.parse_args()
    from query_engine.data_loader import DataLoader
    loader = DataLoader()
    root = WORKSPACE / "controlled_raw" / "formal30"
    if args.run_id:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,64}", args.run_id):
            parser.error("invalid run id")
        root = root / "applicability_runs" / args.run_id
    directory = root / args.case / "loop"
    report = make_report(directory, loader, args.output.resolve().parent)
    args.output.write_text(report, encoding="utf-8")

