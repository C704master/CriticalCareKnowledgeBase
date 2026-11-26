"""Second read of every explicit contradiction before reporting it as a suspected error."""
import asyncio
from anchors import segments
from blind import ROOT, LABEL, CASES, ARMS, ask, message, prompt, read, save, load_input

REREAD=prompt(
    '任务：根据完整来源复核一条原答主张。输入含原答所在行以明确上下文、待审原话、编号来源。只用来源核事实。'
    '输出JSON对象：关系（直接蕴含、仅部分要素、明确相反、无关、不确定）、原文编号（整数数组）、原因。'
    '只有对同一对象、事件、时间和量纲，两种表述不能同时成立才算明确相反。注明具体冲突值或命题。'
    '同一天可有多个合法观测值，按原话确定取值时间；没指定最早值时别强加。'
    '比较相对与绝对、事实与风险、记录时间与事件时间。来源未写或用语含糊须保留不确定性。'
    '来源支持的部分可分辨则判仅部分要素；明确支持全句才判直接蕴含。只选必要的原文编号，勿推导临床正常范围。'
    '程序验证枚举和原文编号；原因必须简短指出可查证事实。',
    [({'所在行':'早班发出三份。','命题':'早班发出三份','来源':[[1,'早班共发出两份，晚班另发一份。']]},
      {'关系':'明确相反','原文编号':[1],'原因':'同一早班的总数两份与三份冲突。'}),
     ({'所在行':'周一的八件到周三剩两件。','命题':'周一的八件到周三剩两件','来源':[[1,'周一八时四件，十六时八件。'],[2,'周三剩两件。']]},
      {'关系':'直接蕴含','原文编号':[1,2],'原因':'两端都在相应日期记录中，周一上午另一个数值可同时成立。'}),
     ({'所在行':'本周仍有延误风险。','命题':'本周仍有延误风险','来源':[[1,'上周积压件数下降。']]},
      {'关系':'不确定','原文编号':[1],'原因':'上周积压量下降可以和本周仍有延误风险同时成立，目前缺少对本周风险的直接资料。'})])


async def rerun(cell,row,source):
    indexed=segments(source)
    data={'所在行':row['line_text'],'命题':row['claim'],'来源':list(indexed.items())}
    for i in range(3):
        folder=cell/'opposition'/f"q{row['id']:03}"/f't{i}'
        try:
            obj=await ask(folder,'opposition',REREAD+[message('user',data)],1200+400*i)
            rel,ids,why=obj['关系'],obj['原文编号'],obj['原因']
            assert rel in LABEL and isinstance(ids,list) and all(type(k) is int and k in indexed for k in ids)
            assert rel not in ('明确相反','直接蕴含','仅部分要素') or ids
            assert isinstance(why,str) and why
            quotes=[indexed[k] for k in dict.fromkeys(ids)]
            return dict(row,initial_support=row['support'],initial_why=row['why'],support=LABEL[rel],
                        source_indices=ids,anchor=quotes[0] if quotes else '',extra_anchors=quotes[1:],why=why)
        except (RuntimeError,KeyError,ValueError,AssertionError,TypeError) as exc:
            save(folder/'validation.json',{'issue':str(exc)})
    raise RuntimeError('无法完成明确矛盾复核')


async def main():
    for case in CASES:
        for arm in ARMS:
            cell=ROOT/'records'/case/arm
            _,sources=load_input(case,arm)
            rows=[r for r in read(cell/'pre_opposition.json') if r['support']=='矛盾']
            res=await asyncio.gather(*(rerun(cell,r,sources[r['source']]) for r in rows))
            save(cell/'opposition.json',res)


if __name__=='__main__':
    asyncio.run(main())
