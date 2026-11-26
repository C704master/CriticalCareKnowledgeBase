"""Run the three approved whole-answer reviews against each arm's frozen inputs."""
import asyncio
import hashlib
import json
import re
import sys
from pathlib import Path
from datetime import datetime

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parent
FORMAL = ROOT.parent
sys.path.insert(0, str(FORMAL))
from batch_transport import Transport, CallFailure, read, save

OLD = FORMAL / '单侧命中核查_20261123'
FROZEN = OLD / 'F09评阅验收/分步核源/static/B/calls/01_relation/request.json'
RELATION = read(FROZEN)['messages'][:-1]
LABEL = {'直接蕴含':'充分','仅部分要素':'部分','明确相反':'矛盾','不确定':'待判','无关':'无支持'}
KEY = dotenv_values(FORMAL.parents[2] / 't06_prompt_pilot_20261117/.env')['QWEN_TRIAL_API_KEY']
SLOTS = asyncio.Semaphore(14)
ARMS = ('direct','static','loop')
CASES = ('F09','F07','F12')


def message(role, value):
    return {'role':role,'content':value if isinstance(value,str) else json.dumps(value,ensure_ascii=False)}


def prompt(system, examples):
    messages = [message('system',system)]
    for inp, output in examples:
        messages.extend((message('user',inp),message('assistant',output)))
    return messages


COVER = prompt(
    '全文分段盲评。输入为带序号的原答行。逐行列出可核验的病例事实、建议及推断。'
    '每个非空行在输出中恰出现一次。纯标题列空数组。逐字摘录连续的最短独立命题，保留条件、否定、时间、对象和单位。'
    '总要求与实施方式分别列，方式与其时长放在一起；频率、目标与目的分别列。比较必须保留比较双方和关系。'
    '不要把若、如、考虑等条件删掉，不要把记录与建议合并。区分标题与确有动作的要求。只返回JSON对象，键为行号，值为原句片段数组。'
    '验收按原行逐字定位并检查限定词和独立要求。',
    [({'1':'# 日志','2':'昨日收件三份。建议每周核对清单。'},{'1':[],'2':['昨日收件三份','建议每周核对清单']}),
     ({'4':'发布前务必复核：通过视频连线核对签名（连续两分钟），便于追溯。','5':'若文件已签收，需登记；副本两份，低于要求的三份。'},
      {'4':['发布前务必复核','通过视频连线核对签名（连续两分钟）','便于追溯'],'5':['若文件已签收，需登记','副本两份，低于要求的三份']})])
FIND = prompt(
    '任务是为每条原话选一个最值得核对的出处，包括相反证据。输入是带编号的原话及所在行、患者记录和本组实际入模的知识原文。'
    '病例事实优先选择patient；通用建议选择有内容对应的E编号；多个要素仅部分有据时也选最相关者。'
    '计划或监测记录不足以证明推荐频率，主题相近不足以作出处。没有相关出处选none。'
    '范围只限输入，各条独立。输出JSON对象，每个编号对应一个来源编号字符串；程序核对编号与来源枚举。此步只选来源，下一步逐条核验。',
    [({'原话':{'1':'昨日收件三份','2':'签字后归档'},'患者记录':'昨日收件三份。','知识原文':{'E1':'签字后应归档。'}},{'1':'patient','2':'E1'}),
     ({'原话':{'1':'建议每隔两小时收件','2':'远程核对持续五分钟'},'患者记录':'八点和十点收件。','知识原文':{'E1':'允许远程核对。现场核对至少五分钟。'}},{'1':'none','2':'E1'})])


async def ask(folder, stage, messages, limit):
    folder.mkdir(parents=True,exist_ok=True)
    async with SLOTS:
        response = await Transport(folder,folder,KEY).call(stage,messages,max_tokens=limit)
    return json.loads(re.sub(r'^```(?:json)?\s*|\s*```$','',response['content'].strip()))


def pieces(rows, size):
    return [rows[i:i+size] for i in range(0,len(rows),size)]


async def coverage(cell, lines):
    data = dict(lines)
    for attempt in range(3):
        msgs = COVER + [message('user',data)]
        if attempt:
            msgs.append(message('user','重试格式校验。每个键都须返回。每段摘录必须原样复制，包含原有标点、空格与符号。'))
        try:
            obj = await ask(cell / f'c{attempt}', 'coverage', msgs, 4400)
            if set(obj) != set(data):
                raise ValueError('行号不全')
            result = {}
            for n, quotes in obj.items():
                if not isinstance(quotes,list):
                    raise ValueError('格式错误')
                result[n] = []
                for q in quotes:
                    if not isinstance(q,str) or not q.strip():
                        raise ValueError('空摘录')
                    if q not in data[n]:
                        raise ValueError('无法回查摘录')
                    if q not in result[n]:
                        result[n].append(q)
                if not quotes and len(re.sub(r'\[[^\]]*\]|[*#\s]','',data[n])) > 30:
                    raise ValueError('长行漏抽')
            return result
        except (ValueError,TypeError,CallFailure) as err:
            save(cell / f'c{attempt}/validation.json',{'issue':str(err)})
            if len(lines)>1:
                cut=len(lines)//2
                left,right=await asyncio.gather(coverage(cell/'left',lines[:cut]),coverage(cell/'right',lines[cut:]))
                return {**left,**right}
    # Keep the exact original when the model repeatedly fails localization.
    return {n:[s] for n,s in lines}


def load_input(case,arm):
    directory = FORMAL / case
    frozen = read(directory/'freeze.json')
    original = (directory/arm/'answer.md').read_text('utf8')
    material = read(next((directory/arm/'calls').glob('*final/request.json')))['messages'][-1]['content']
    sources = {'patient':frozen['patient']}
    for i,e in enumerate(read(directory/arm/'evidence.json'),1):
        sources[f'E{i}'] = e['raw_text']
    assert all(s and s in material for s in sources.values())
    return original, sources


async def locate(cell, rows, sources, correction=False):
    context = {'原话':{str(r['id']):[r['claim'],r['line_text']] for r in rows},
               '患者记录':sources['patient'],'知识原文':{k:v for k,v in sources.items() if k!='patient'}}
    msgs=FIND+[message('user',context)]
    if correction:
        msgs.append(message('user','请直接返回编号到来源的JSON对象。每个值是一个来源编号或none。'))
    try:
        obj = await ask(cell,'source',msgs,1000)
        if not isinstance(obj,dict) or set(obj)!=set(context['原话']) or any(v not in {*sources,'none'} for v in obj.values()):
            raise ValueError('候选来源输出不合规')
    except (CallFailure,TypeError,ValueError) as err:
        save(cell/'validation.json',{'issue':str(err)})
        if len(rows)>1:
            cut=len(rows)//2
            left,right=await asyncio.gather(locate(cell/'left',rows[:cut],sources,True),
                                            locate(cell/'right',rows[cut:],sources,True))
            return {**left,**right}
        if not correction or cell.name!='single':
            return await locate(cell/'single',rows,sources,True)
        raise
    return obj


async def judge(cell, row, src, sources):
    if src=='none':
        return dict(source=src,support='无支持',anchor='',why='本组实际输入中未选出可核对出处。')
    payload={'命题':row['claim'],'来源':sources[src]}
    for attempt in range(2):
        try:
            result = await ask(cell/f'v{attempt}','relation',RELATION+[message('user',payload)],1200 if attempt else 600)
            anchor,rel,why=result['锚句'],result['关系'],result['原因']
            if rel not in LABEL or not isinstance(why,str) or not why or not isinstance(anchor,str):
                raise ValueError('关系输出不合规')
            if anchor and anchor not in sources[src]:
                raise ValueError('锚句无法逐字定位')
            if rel=='直接蕴含' and not anchor:
                raise ValueError('充分缺少原文锚点')
            return dict(source=src,support=LABEL[rel],anchor=anchor,why=why)
        except (CallFailure,ValueError,KeyError,TypeError) as err:
            save(cell/f'v{attempt}/validation.json',{'issue':str(err)})
    return dict(source=src,support='待判',anchor='',why='模型输出未通过格式或逐字定位检查；需复核。')


async def review(case,arm):
    cell=ROOT/'records'/case/arm
    raw,sources=load_input(case,arm)
    lines=[(str(i),s) for i,s in enumerate(raw.splitlines(),1) if s.strip()]
    blocks=await asyncio.gather(*(coverage(cell/'extract'/f'b{i:02}',b) for i,b in enumerate(pieces(lines,6))))
    by_line={k:v for block in blocks for k,v in block.items()}
    assert set(by_line)==dict(lines).keys()
    rows=[]
    for n,s in lines:
        for q in by_line[n]:
            rows.append(dict(id=len(rows)+1,line=int(n),line_text=s,claim=q,start=s.index(q)))
    save(cell/'extracted.json',{'lines':by_line,'claims':rows})
    async def group(i, batch):
        candidates=await locate(cell/'source'/f'b{i:02}',batch,sources)
        decisions=await asyncio.gather(*(judge(cell/'relation'/f'q{r["id"]:03}',r,candidates[str(r['id'])],sources) for r in batch))
        return [dict(**r,**v) for r,v in zip(batch,decisions)]
    batches=await asyncio.gather(*(group(i,b) for i,b in enumerate(pieces(rows,16))))
    save(cell/'result.json',{'answer_sha256':hashlib.sha256(raw.encode()).hexdigest(),'nonempty_lines':len(lines),
                              'claims':[r for b in batches for r in b]})


async def main():
    results=await asyncio.gather(*(review(c,a) for c in CASES for a in ARMS),return_exceptions=True)
    errors=[repr(v) for v in results if isinstance(v,Exception)]
    if errors:
        raise RuntimeError(errors)


if __name__=='__main__':
    asyncio.run(main())
