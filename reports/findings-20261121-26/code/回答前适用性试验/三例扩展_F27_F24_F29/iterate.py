"""Replay final generation with a general instruction on evidence scope."""
import asyncio
from paired import CASES, OUT, generate, inputs, read

RULE = """作答和交卷前均按以下口径核对全文。先回答原题，其他内容仅在会改变判断时写。
1. 把病历原记、可独立推算及仍待核实的事项分开。推算总量或派生指标前要有全部必需分项；不可测或未给的分项保留原记号。缺项时只列可核实分项，不能把其余分项之和称作完整总量。引用病历自己写的数值要明示是病历原记。
2. 比较或计算前核对事件日期、同一时点的条件及样本属性。摘要抄录日期和测量日期分开。无法配对时分别陈述观察并说明下一步如何核实，不给未经核实的配对值、趋势或病情分层。
3. 一条来源只支持其实际写出的结论。区分病历已记录的暴露、尚待确认的病因以及只有前提成立才适用的操作。若缺少决定是否执行的条件，写出需核对什么，保留对原题有用的一般方法，无需把该操作列为本例应执行事项。
4. 用上述口径复查正文和结尾，删去后文又当成已证实的说法。"""

async def run(tag):
    f, req, _, _ = inputs(tag)
    msg = read(OUT/tag/"V2/calls/01_final/request.json")["messages"][-1]["content"]
    assert msg.startswith(f["prefix"])
    await generate(tag, "V3", req, msg+"\n\n【答题核对规则】\n"+RULE)

async def main():
    await asyncio.gather(*(run(tag) for tag in CASES))

if __name__ == "__main__":
    asyncio.run(main())
