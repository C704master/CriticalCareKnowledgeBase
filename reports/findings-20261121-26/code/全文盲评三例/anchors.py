"""Recover structurally invalid model citations using addresses into the same full source."""
import asyncio
import re
import blind
from blind import ARMS, CASES, ROOT, LABEL, CallFailure, ask, load_input, message, prompt, read, save

INDEXED=prompt(
    '你核验单个命题。来源按原顺序编号，合起来是完整来源。判定直接蕴含、仅部分要素、明确相反、无关、不确定。'
    '核对对象、时间、关系、条件与数值；日期或时间次序需要结合所在日期段。直接蕴含要求全部要素在同一条件下成立。'
    '输出JSON对象，字段关系、原文编号、原因。编号为整数数组，只选必要原文。理由一句话。充分、部分或相反都必须给出依据编号；'
    '不确定时如实报告。程序按编号取回原文，不允许编造句号。输入为命题与编号来源。',
    [({'命题':'周二收到三份','来源':[[1,'周一收到两份。'],[2,'周二收到三份。']]},
      {'关系':'直接蕴含','原文编号':[2],'原因':'日期与数量一致。'}),
     ({'命题':'远程复核应持续十分钟','来源':[[1,'允许远程复核。'],[2,'现场复核须持续十分钟。']]},
      {'关系':'仅部分要素','原文编号':[1,2],'原因':'时间要求属于现场复核。'})])


def segments(source):
    parts=re.findall(r'[^。！？；\n]+[。！？；]?|[。！？；\n]',source)
    assert ''.join(parts)==source
    return {i:s for i,s in enumerate(parts,1)}


async def review(row,source,folder):
    numbered=segments(source)
    data={'命题':row['claim'],'来源':list(numbered.items())}
    for i in range(4):
        try:
            obj=await ask(folder/f't{i}','indexed',INDEXED+[message('user',data)],1000+i*600)
            rel,indices,why=obj['关系'],obj['原文编号'],obj['原因']
            assert rel in LABEL and isinstance(indices,list) and isinstance(why,str) and why
            assert all(type(k) is int and k in numbered for k in indices)
            if rel in ('直接蕴含','仅部分要素','明确相反'):
                assert indices
            quotes=[numbered[k] for k in dict.fromkeys(indices)]
            return dict(row,support=LABEL[rel],why=why,anchor=quotes[0] if quotes else '',
                        extra_anchors=quotes[1:],source_indices=indices)
        except (AssertionError,CallFailure,ValueError,KeyError,TypeError) as exc:
            save(folder/f't{i}/validation.json',{'error':str(exc)})
    raise RuntimeError(f'引用定位恢复失败 {folder}')


async def run(case,arm):
    cell=ROOT/'records'/case/arm
    _,src=load_input(case,arm)
    edits={r['id']:r for r in read(cell/'repairs.json')} if (cell/'repairs.json').exists() else {}
    rows=[edits.get(r['id'],r) for r in read(cell/'result.json')['claims']]
    pending=[r for r in rows if '未通过格式或逐字定位检查' in r['why']]
    fixed=await asyncio.gather(*(review(r,src[r['source']],cell/'anchor_repair'/f"q{r['id']:03}") for r in pending))
    save(cell/'anchors.json',fixed)


async def main():
    blind.SLOTS=asyncio.Semaphore(4)
    await asyncio.gather(*(run(c,a) for c in CASES for a in ARMS if (ROOT/'records'/c/a/'result.json').exists()))


if __name__=='__main__':
    asyncio.run(main())
