from pathlib import Path
from collections import Counter
import csv,statistics,itertools,json,re,sys
from review import o,read,armdata
from evidence_refs import refs_by_line
cases=read(o/'manifest.json')
l5={}
src=o.parents[3]/'data/05_evidence_fragments/evidence_fragments.jsonl'
for line in src.open(encoding='utf-8-sig'):
 f=json.loads(line);l5[f['fragment_id']]=f['raw_text']
rows=[];casesout=[];trace=[];qr=[];labrows=[]
def esc(s):return str(s).replace('|','／').replace('\n',' ')
def writecsv(name,rows):
 if not rows:return
 with (o/name).open('w',encoding='utf-8-sig',newline='') as file:
  w=csv.DictWriter(file,list(rows[0]));w.writeheader();w.writerows(rows)
for m in cases:
 tag=m['tag'];c=o/tag
 if not all((c/a/'result.json').exists() for a in ('direct','static','loop')):continue
 data=armdata(c)
 rel=c/'review/relevance_v2/output.json';quality=c/'review/quality/output.json'
 labels=dict(zip(read(c/'review/key.json'),read(rel)['labels'])) if rel.exists() else {}
 overrides=c/'review/标签复核.json'
 if overrides.exists():labels.update({k:v['label'] for k,v in read(overrides).items()})
 assert all(v is not None for v in labels.values()),tag
 order=read(c/'review/blind.json') if (c/'review/blind.json').exists() else ['direct','static','loop'];names=dict(zip(order,'甲乙丙'))
 q=read(quality) if quality.exists() else None
 packet=['# '+tag+'　'+m['question'],'','截止 '+m['cutoff']+'。研究评阅用。[三组共享的冻结病例](freeze.json)。每份答案下保留对应的实际知识原文。','']
 for a in order:
  x=data[a];r=read(c/a/'result.json');ev=x['ev'];ans=x['ans'];us=[u['uid'] for u in x['rank']]
  for f in ev:assert l5[f['fragment_id']]==f['raw_text']
  indices=[i for i,uid in enumerate(us,1) if labels.get('U'+uid)==2]
  first=min(indices) if indices else 0
  nr=x['refs'];invalid=[i for i in nr if not 0<i<=len(ev)]
  files=list((c/a/'calls').glob('*/attempt_*/status.json'))
  ss=[read(f) for f in files];usage=sum((y.get('usage') or {}).get('total_tokens',0) for y in ss)
  row=dict(病例=tag,分层=m['group'],方法=a,检索=r['retrievals'],实际排序条数=len(us),入模=len(ev),直接贴题原文=sum(labels.get('F'+f['fragment_id'])==2 for f in ev) if (labels or not ev) else '',点名有效原文=len(set(nr)-set(invalid)),越界编号=','.join(map(str,invalid)),调用尝试=len(ss),已知总token=usage,耗时秒=round(r['seconds'],1))
  for k in (5,10,20):
   num=sum(i<=k for i in indices)
   row['Hit@'+str(k)]=int(num>0) if a!='direct' and (labels or not us) else ''
   row['P@'+str(k)]=num/k if a!='direct' and (labels or not us) else ''
  row['RR@20']=(1/first if first else 0) if a!='direct' and (labels or not us) else '';rows.append(row)
  for i,u in enumerate(x['rank'],1):labrows.append(dict(病例=tag,方法=a,层='知识',位置=i,ID=u['uid'],标签=labels.get('U'+u['uid'],''),正文点名=''))
  for i,f in enumerate(ev,1):labrows.append(dict(病例=tag,方法=a,层='原文',位置=i,ID=f['fragment_id'],标签=labels.get('F'+f['fragment_id'],''),正文点名=int(i in nr)))
  packet+=['## 答案'+names[a],'']
  line_refs=refs_by_line(ans)
  for line_number,line in enumerate(ans.splitlines()):
   packet.append(line)
   for n in line_refs.get(line_number, []):
    f=ev[n-1] if 0<n<=len(ev) else None
    packet+=['','<details><summary>查看 E'+str(n)+' 原文</summary>','',('> '+f['raw_text'].replace('\n','\n> ')+'\n\n'+f['source_title']+' · '+f['fragment_id']) if f else '本次输入没有对应原文。']
    if f and len(f.get('bindings',[]))>1:
     packet+=['','同文挂载（各自适用）','']
     for b in f['bindings']:
      people='、'.join(b['适用人群'] or []) or '未标注'
      packet.append(f"- {b['来源']}（{b['来源ID']}，{b['章节']}，{b['L5片段']}） · {b['L4单元']} · {b['L4规则'] or '未提供规则'} · 适用人群：{people}")
    packet+=['','</details>','']
  if q:
   z=q['answers'][names[a]];qr.append(dict(病例=tag,方法=a,贡献=z['gain'],局限=z['limit'],答案定位=z['quote'],病例定位=z['fact'],支持初评=z['support'],答案定位状态=z.get('quote_status','完整逐字匹配'),病例定位状态=z.get('fact_status','完整逐字匹配')))
 (c/'三份匿名答案与原文.md').write_text('\n'.join(packet),'utf8')
 if q:casesout.append(dict(病例=tag,题型=m['group'],原题=m['question'],直答=q['answers'][names['direct']]['gain'],一次拆解=q['answers'][names['static']]['gain'],动态补查=q['answers'][names['loop']]['gain'],研究初评=q['reason'],首选={v:k for k,v in names.items()}.get(q['best'],q['best']),局限=' ／ '.join(q['answers'][names[a]]['limit'] for a in ['direct','static','loop']),原文入口=tag+'/三份匿名答案与原文.md'))
writecsv('表一_逐例检索及成本.csv',rows);writecsv('表二_病例配对结果.csv',casesout);writecsv('重要判断原句与初评.csv',qr);writecsv('检索与原文逐条标签.csv',labrows)
if len(rows)==90:
 print('COMPLETE',len(casesout),len(qr))
 for a in ('direct','static','loop'):
  rr=[r for r in rows if r['方法']==a];print(a,[sum(r[k] for r in rr) for k in ('检索','入模','点名有效原文')], 'bad refs',sum(bool(r['越界编号']) for r in rr))
  if a!='direct' and all(r['RR@20']!='' for r in rr):print('metrics',[(k,round(statistics.mean(r[k] for r in rr),3)) for k in ('Hit@5','Hit@10','Hit@20','P@5','P@10','P@20','RR@20')],sum(r['直接贴题原文'] for r in rr))
 print('judges',Counter(x['首选'] for x in casesout))
