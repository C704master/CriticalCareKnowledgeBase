"""Prompt and source checks shared by the static and loop experiments."""
import json
import re


# Only isolated line breaks between Chinese characters can be restored automatically.
WRAPPED_LINE = re.compile(r"(?<=[\u3400-\u9fff])(?:\r\n|\r|\n)(?=[\u3400-\u9fff])")


SYSTEM = """你为临床问答选择知识库证据。根据原题、截止时间和病例确定要回答的子问题。
候选按编号提供对应的 L4 规则和完整 L5 原文片段。L4 帮助定位知识点，证据强度以同一候选的 L5 为准。仔细读相邻句中的对象、方式、数值、时间、例外和否定。L4 缺失时仍可根据 L5 选证。
按价值从高到低选至多 10 条，兼顾不同子问题。仅主题相关、重复或不能支持具体判断的片段可跳过；全部无用时返回 {"选择":[]}。
仅输出 JSON。每条填写编号、子问题、支持程度、原句、理由。支持程度枚举为“充分”或“部分”，均针对写出的子问题。“充分”要求原文覆盖所问内容和限定条件；“部分”必须写明支持哪部分、哪部分缺依据。不要通过缩窄子问题掩盖未获支持的条件。
原句必须连续逐字摘自该编号的 L5，保留决定含义的限定语。不同方式、人群或用途的数值不能相互套用。理由简短说明为何选它。"""


def message(role, content):
    return {"role": role, "content": json.dumps(content, ensure_ascii=False)}


def build_shortlist(ranked_units, fragment_payload):
    """Keep first-seen candidate order and every distinct L4–L5 source attachment."""
    by_text = {}
    for unit in ranked_units:
        for original in unit.fragments:
            fragment = fragment_payload(original)
            text = fragment["raw_text"]
            if not text.strip():
                continue
            if text not in by_text:
                by_text[text] = {**fragment, "uid": unit.unit_id, "title": unit.unit_title,
                                 "bindings": []}
            binding = {
                "来源ID": fragment["source_id"], "来源": fragment["source_title"],
                "章节": fragment["section_id"], "定位": fragment["position_hint"],
                "L5片段": fragment["fragment_id"], "L4单元": unit.unit_id,
                "标题": unit.unit_title, "L4规则": unit.operational_rule or None,
                "适用人群": unit.population_tags,
            }
            bindings = by_text[text]["bindings"]
            if binding not in bindings:
                bindings.append(binding)
    return list(by_text.values())


def rule_fields(fragment, primary_rule):
    bindings = fragment.get("bindings", [])
    if len(bindings) > 1:
        return {"同文挂载（各自适用）": bindings}
    return {"L4规则": primary_rule}


def candidate(number, fragment, rule):
    return {"编号": number, "L4单元": fragment["uid"], "标题": fragment["title"],
            **rule_fields(fragment, rule or None), "L5片段": fragment["fragment_id"],
            "L5原文": fragment["raw_text"]}


# Synthetic examples use a non-clinical procedure to keep case answers out of the prompt.
EXAMPLE = {"编号": 1, "L4单元": "demo-unit", "标题": "设备校验",
           "L4规则": "启动前校验，运行两分钟。", "L5片段": "demo-fragment",
           "L5原文": "两种模式均应在启动前校验。自动模式需运行两分钟。"}
EXAMPLES = [
    ("启动前要校验吗？", "启动前是否要校验？", "充分",
     "两种模式均应在启动前校验。", "原文明示两种模式的校验要求。"),
    ("手动模式也要校验并运行两分钟吗？", "手动模式是否要校验并运行两分钟？", "部分",
     EXAMPLE["L5原文"], "原文支持启动前校验；两分钟只适用于自动模式，手动时长缺依据。"),
]


def selection_messages(context, candidates):
    messages = [{"role": "system", "content": SYSTEM}]
    for question, subquestion, strength, quote, reason in EXAMPLES:
        messages.append(message("user", {"原题": question, "截止": "示例时点",
                                         "病例": "演示设备处于手动模式。", "候选": [EXAMPLE]}))
        messages.append(message("assistant", {"选择": [{"编号": 1, "子问题": subquestion,
                        "支持程度": strength, "原句": quote, "理由": reason}]}))
    messages.append(message("user", {**context, "候选": candidates}))
    return messages


def restore_source_quote(quote, source, number):
    skipped = {i for match in WRAPPED_LINE.finditer(source) for i in range(*match.span())}
    offsets = [i for i in range(len(source)) if i not in skipped]
    joined = "".join(source[i] for i in offsets)
    start = joined.find(quote)
    if start < 0 or joined.find(quote, start + 1) >= 0:
        raise ValueError(f"候选 {number} 的原句无法在相应 L5 中唯一还原")
    return source[offsets[start]:offsets[start + len(quote) - 1] + 1]


def validate_selection(response, candidates):
    rows = response.get("选择") if isinstance(response, dict) else None
    if not isinstance(rows, list) or len(rows) > 10:
        raise ValueError("选择必须是最多十条的列表")
    seen = set()
    validated = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("选证记录必须是对象")
        number = row.get("编号")
        if type(number) is not int or not 1 <= number <= len(candidates) or number in seen:
            raise ValueError(f"重复或无效的选证编号 {number!r}")
        seen.add(number)
        if row.get("支持程度") not in ("充分", "部分"):
            raise ValueError(f"候选 {number} 支持程度缺失或无效")
        for field in ("子问题", "原句", "理由"):
            if not isinstance(row.get(field), str) or not row[field].strip():
                raise ValueError(f"候选 {number} 缺少{field}")
        source = candidates[number - 1]["L5原文"]
        quote = row["原句"]
        if quote not in source:
            restored = restore_source_quote(quote, source, number)
            row = {**row, "原句": restored, "模型原句": quote, "引文校验": "已还原排版换行"}
        validated.append(row)
    return validated
