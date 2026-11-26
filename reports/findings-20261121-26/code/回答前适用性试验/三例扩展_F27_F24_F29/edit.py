"""Independent source-grounded editor; operates on the previous draft and frozen input."""
import asyncio
import re
from paired import CASES, OUT, call, inputs, read, save, v1

SYS="""你是回答原问题的独立校订者。草稿没有证据效力。依据截止时间、病历原句和可见知识原文重新写一份可单独交给提问者的答案。简洁，优先答提问，再写与提问直接相关的核实步骤。资料未提供的判断就留空或说明待核实。
每处判断分清三个层次：病历原文说了什么，知识原文许可了什么，二者共同允许对这个对象说到哪里。任何算式、总量、区间、趋势、现行操作必须能够从对应原句复现；不可测不能补零或按剩余项给总数。跨事件或跨来源的数值不拼配；记录日期与实际事件日期分开。不得把导出量入账成病历原记，也不得把通用方案写成已适用于当下的指令。删去草稿中经不起核查的内容，包括摘要和末段重复。对一般方法仍可解释，单独说明本案缺少的记录。只在实际支撑判断处保留对应知识编号。输出最终答复正文。"""
EXAMPLES=[
 ({"问题":"这次运费如何计算？","病历":{"1":"上午发运：质量2千克、单价3元/千克。"},"知识":{"E1":"费用为同期有效单价乘本次实测质量。"},"待校草稿":"此次运费6元。"},
 "此次质量为2千克，同次单价为3元/千克。按费用公式[E1]，可算得本次运费6元。"),
 ({"问题":"两次运费能比较吗？","病历":{"1":"周一登记：质量2千克，单价不可测。","2":"周二登记：账单原记9元，质量3千克，未列单价。"},"知识":{"E1":"费用为同期有效单价乘本次实测质量。"},"待校草稿":"周一2元，周二9元，运费上升，应补扣7元。"},
 "周一只记了质量，缺少当次单价，无法按公式计算费用[E1]。周二账单原记9元。两次费用的变化尚无法判断，需核对周一原账单或当次单价。")]
PROMPT=v1.prompt(SYS,EXAMPLES)

async def edit(tag):
    f, req, patient, evidence=inputs(tag)
    comp=read(OUT/tag/"comparison.json")
    notes=read(OUT/tag/"适用说明.json")
    kept=comp["eligible"]
    data={"问题":f["question"],"截止":f["cutoff"],"病历":patient,
          "知识":{n:evidence[n]["L5原文"] for n in kept},
          "适用说明":{n:notes[n] for n in kept},
          "待校草稿":(OUT/tag/"V3/answer.md").read_text("utf-8")}
    root=OUT/tag/"V4"
    msg=await call(root,"edit",PROMPT+[v1.message("user",data)],req["max_tokens"])
    answer=msg["content"]
    assert answer.strip() and set(re.findall(r"\[(E\d+)\]",answer))<=set(kept)
    (root/"answer.md").write_text(answer,encoding="utf-8")

async def main():
    await asyncio.gather(*(edit(tag) for tag in CASES))

if __name__=="__main__":
    asyncio.run(main())
