"""Focused application of the frozen whole-answer reviewer to the approved paired traces."""
import asyncio
import json
import sys
from pathlib import Path

HERE=Path(__file__).resolve().parent
FORMAL=HERE.parents[1]
sys.path.insert(0,str(FORMAL/'全文盲评三例'))
import blind
from anchors import review as repair_anchor
from opposition import rerun as reread_opposition

# Retrospective subquestions from the agreed trace outline. First item traces a Top20 hit.
TOPICS={
 'F04':(4,['何时考虑外周专用采血通道','能否一概避免在CRRT管路采样口采血']),
 'F05':(1,['初始抗菌反应不佳时如何用培养及药敏调整抗菌药','痰培养能否确定中枢感染病原，脑脊液检查有何缺口']),
 'F06':(1,['考虑撤机时需要满足哪些氧合、通气和循环条件','哪一天何时开始或重新开始有创通气，依据有多确定']),
 'F07':(1,['如何给予胰岛素以控制血糖，区分输注途径与泵速','血滤导管若用于CRRT的条件性建议或实际血浆置换用途']),
 'F09':(1,['吸痰前预充氧的一般原则','手动呼吸、纯氧及持续时长能否连用','气囊压力监测的推荐间隔']),
 'F11':(1,['用什么氧合阈值和吸入氧浓度条件评估撤机','是否提出目前抗凝剂量可能偏低及其条件']),
 'F12':(1,['是否建议按乳酸或清除率变化评估复苏','如何比较收缩压最低值与平均动脉压目标，务必保留两端']),
 'F13':(1,['转运途中生命体征监测应保持何种强度','是否交代转出后呼吸恶化的风险与预案']),
 'F14':(2,['何种换管情况下需在多久内复查离子钙','如何判断头孢他啶阿维巴坦对CRABA的覆盖及药敏依据']),
 'F17':(1,['PCT及CRP可为感染判断提供什么信息','低pCO2的解释及是否需要调整高流量氧疗']),
 'F22':(1,['是否要求每日评价抗菌药疗效','如何在高钠及容量负荷下权衡补液与CRRT']),
 'F25':(3,['呼吸困难及痰量痰性状哪些变化支持AECOPD','低pCO2是否可由代谢性酸中毒的代偿解释']),
}
PICK=blind.prompt('针对各个研究子问题，从同一份完整原答选出最切题的一条可核验主张。逐字复制连续的最短原话。保留限定、否定、语气。比较必须保留两端；仅原则与实施细节分开时按子问题选。没有直接作答返回空串，可在near给与问题最近的实际短原话作对照。返回JSON对象，键为子问题编号，值为[quote,near]。禁止改写，程序回查原文。只选句，不评价。',
 [({'问题':{'k':'事前须做什么','p':'复核多久'},'原答':'提交前应复核。未提及具体时限。'},{'k':['提交前应复核',''],'p':['','未提及具体时限']}),
  ({'问题':{'k':'何时需要追加登记'},'原答':'若远程复核失败，需追加登记。'},{'k':['若远程复核失败，需追加登记','']})])
PAIR=blind.prompt('仅判断当前子问题的匿名配对。从甲相对乙看，给出分类及一条理由。材料含两组完整原答、对应引句、单组核源结果。未找到对应引句时先核对全文；未答与无依据分开。分类枚举：补上遗漏、纠正判断、依据增益、无实质变化、无依据新增、退化、待判。双边同一主张且甲有直接依据才能记依据增益；仅部分支持不能记充分获益。不要把整个病例胜负写进来。输出JSON对象，给定每个子问题编号对应[分类,一句理由]。仅根据提供材料。',
 [({'子问题':'提交前复核','甲':'提交前复核，有原文直接支持','乙':'提交前复核，未找到对应出处'},{'k':['依据增益','双方都提出复核，甲有可查的直接依据。']}),
  ({'子问题':'远程复核限时','甲':'远程复核五分钟，只有现场复核的时限有据','乙':'未提时限'},{'k':['待判','远程时限只获部分支持。']})])

def rows_for(case):
    return dict(zip(('k','p','q'),TOPICS[case][1]))

async def select(case,arm):
    folder=HERE/'records'/case/arm
    answer,sources=blind.load_input(case,arm)
    topics=rows_for(case)
    for i in range(3):
        ms=PICK+[blind.message('user',{'问题':topics,'原答':answer})]
        if i:ms.append(blind.message('user','每条必须能在输入中用字符串查找直接定位。不要调整空格或标点。'))
        try:
            obj=await blind.ask(folder/f'pick{i}','pick',ms,1600)
            assert set(obj)==set(topics)
            if i==2:
                offsets=[j for j,ch in enumerate(answer) if ch!='*' and not ch.isspace()]
                flat=''.join(answer[j] for j in offsets)
                for values in obj.values():
                    for j,v in enumerate(values):
                        if v in answer:continue
                        needle=''.join(ch for ch in v if ch!='*' and not ch.isspace())
                        pos=flat.find(needle)
                        if needle and pos>=0 and flat.count(needle)==1:
                            values[j]=answer[offsets[pos]:offsets[pos+len(needle)-1]+1]
                        elif j==1 and values[0] in answer and values[0]:
                            values[j]=''
            assert all(isinstance(v,list) and len(v)==2 and all(isinstance(t,str) and t in answer for t in v) for v in obj.values())
            break
        except (ValueError,AssertionError,TypeError,blind.CallFailure):
            if i==2:raise
    rows={}
    oldfile=FORMAL/'全文盲评三例'/'records'/case/arm/'final.json'
    cached=blind.read(oldfile) if oldfile.exists() else []
    pending=[]
    for key,(q,near) in obj.items():
        line=next((s for s in answer.splitlines() if q and q in s),'')
        row=dict(id=key,claim=q,line_text=line,near=near)
        old=next((r for r in cached if q and q==r['claim'] and r['line_text']==line),None)
        if old:
            row.update({k:old[k] for k in ('source','support','anchor','why')},cache_id=old['id'])
        elif q:pending.append(row)
        else:row.update(source='none',support='未提及',anchor='',why='盲抽未找到直接回答该子问题的主张。')
        rows[key]=row
    try:
        refs=await blind.locate(folder/'source',pending,sources) if pending else {}
    except (blind.CallFailure,ValueError,TypeError):
        numbered=[dict(r,id=i) for i,r in enumerate(pending,1)]
        picked=await blind.locate(folder/'source_numeric',numbered,sources)
        refs={r['id']:picked[str(i)] for i,r in enumerate(pending,1)}
    async def rate(r):
        src=refs[r['id']]
        res=await blind.judge(folder/'judge'/r['id'],r,src,sources)
        r.update(res)
        if '未通过格式' in r['why']:
            r.update(await repair_anchor(r,sources[src],folder/'anchor'/r['id']))
        if r['support']=='矛盾':
            # Existing second-reader expects a numerical row ID in its directory layout.
            numeric=dict(r,id=list(topics).index(r['id'])+1)
            second=await reread_opposition(folder,numeric,sources[src])
            r['second']=second
            if second['support']!='矛盾':
                r.update(support='待判',why='两次语义核验不一致，保留两次输出。')
    await asyncio.gather(*(rate(r) for r in pending))
    blind.save(folder/'rows.json',rows)
    return rows

async def run_case(case,owner):
    other='loop' if owner=='static' else 'static'
    a,b=await asyncio.gather(select(case,owner),select(case,other))
    cell=HERE/'records'/case
    answer,sources=blind.load_input(case,owner)
    source_id=f'E{TOPICS[case][0]}'
    hit={}
    for key in (['k','p'] if case in ('F09','F04') else ['k']):
        r=a[key]
        if not r['claim']:continue
        if r['source']==source_id:hit[key]=r
        else:hit[key]=await blind.judge(cell/'hit'/key,r,source_id,sources)
    order=rows_for(case)
    obj={'原题':blind.read(FORMAL/case/'freeze.json')['question'],'问题':order,'甲完整原答':answer,'乙完整原答':blind.load_input(case,other)[0],'甲':a,'乙':b}
    labels={'补上遗漏','纠正判断','依据增益','无实质变化','无依据新增','退化','待判'}
    for i in range(3):
        output=await blind.ask(cell/f'pair{i}','pair',PAIR+[blind.message('user',obj)],1600)
        if isinstance(output,dict) and set(output)==set(order) and all(isinstance(v,list) and len(v)==2 and v[0] in labels for v in output.values()):break
    else:raise ValueError(f'{case}配对结构')
    blind.save(cell/'result.json',dict(owner=owner,rows={owner:a,other:b},hit=hit,paired=output))

async def main():
    import csv
    traces=list(csv.DictReader((HERE.parent/'12题追踪表.csv').open(encoding='utf-8-sig')))
    blind.SLOTS=asyncio.Semaphore(5)
    errors=await asyncio.gather(*(run_case(t['病例'],t['单侧命中方法']) for t in traces if not (HERE/'records'/t['病例']/'result.json').exists()),return_exceptions=True)
    if any(isinstance(e,BaseException) for e in errors):raise RuntimeError([repr(e) for e in errors if isinstance(e,BaseException)])

if __name__=='__main__':asyncio.run(main())
