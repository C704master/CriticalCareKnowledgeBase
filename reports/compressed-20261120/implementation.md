# 正式批次关键代码摘录

以下为实际执行文件的原样节选。运行依赖本地受控病例和知识库。

## 病例上下文与截止点裁剪

来源文件 prepare.py，完整文件 SHA-256 为 5adb1779994481ad9cb5d96b4d1c637cf36e8a87de1f136d6a8696bec5249068。

```python
 def add(k,v):
  if v and v.strip():parts.append('【'+k+'】\n'+clean(v));kept.append(k)
 if ss['summary_through_date']<=day:add('摘要 转入原因',(ss['transfer_before_or_reason'] or '').split('注：')[0])
 add('摘要 转入后病情','\n'.join(s for s in (ss['post_transfer_condition'] or '').splitlines() if re.match(r'^20\d\d-\d\d-\d\d',s) and s[:10]<day and not re.search(r'次晨|次日|翌日|附晨|跨夜',s)))
 for a in ds:
  date=a['archive_date']
  for k,v in a.items():
   if k=='archive_date' or not v:continue
   if date<day:
    if date==ds[1]['archive_date'] and clock<'08:00' and re.search('次日|次晨|翌日|跨日|跨夜|附晨',v):dropped.append([date,k,'跨日归属']);continue
    add(date+' '+k,v);continue
   if tag=='F04' and k=='rounds_record':
    head=v.split('TnI')[0];assert head.startswith('07:24');add(date+' '+k,head);continue
   if k in ('rounds_record','progress_record'):
    if re.match(r'^\s*(?:'+day+r'\s+)?\d{2}:\d{2}',v) and max(re.findall(r'\d{2}:\d{2}',v))<=clock and not re.search('次日|次晨|翌日|夜班|附晨',v):add(date+' '+k,v)
    else:dropped.append([date,k,'时标不完整或越界'])
   elif k=='abnormal_labs_summary':
    for clause in re.split('[；。\n]',v):
     times=re.findall(r'\d{2}:\d{2}',clause)
     if times and max(times)<=clock and not re.search('次日|次晨|翌日',clause):add(date+' '+k,clause)
   else:dropped.append([date,k,'当日整段不入模'])
 p='\n'.join(parts);q=clean(r['q']);prefix='临床截止点 '+cut+'。原问题：'+q+'\n患者概要及三日日档：\n'+p+'\n知识库证据：\n'
```

## 查询规划、排序融合、原文选择及最终请求

来源文件 run.py，完整文件 SHA-256 为 2dc449781af452186d40e10f147e16d2ffbe8839bde222ff336ee25901d27333。

```python
 if arm=='static' and not resume_final:
  qs=(await plan('一次规划最多四个互补的知识检索词句，围绕本题重点和可推广知识，勿查患者事实。仅给JSON {"queries":["..."]}。',obj))['queries']
  assert isinstance(qs,list) and 1<=len(qs)<=4
  for q in dict.fromkeys(qs):search(q)
 if arm=='loop' and not resume_final:
  for i in range(4):
   res=await plan('你在进行逐次知识检索。结合病例、原题和已查结果判断仍缺哪个最关键的知识依据。输出JSON {"reason":"已有覆盖与缺口","query":"一个检索词句"}。若已有足够依据或再查无益，query为空。初次须提出检索。',dict(**obj,已查=history))
   results.append(res);save(cell/'decisions.json',results);q=res['query'].strip()
   if not q or q in [h['query'] for h in history]:break
   search(q)
 ev=read(cell/'evidence.json') if resume_final else [];used=set();candidates=[]
 for i in range(max(map(len,lists),default=0)):
  for rank in lists:
   if i<len(rank) and rank[i]['fragment_id'] not in used:
    f=rank[i];used.add(f['fragment_id']);candidates.append(f)
 if lists:
  # Common relevance selection uses titles and verbatim short previews, same policy in both arms.
  # Apply the same reciprocal-rank fusion to both arms before source selection.
  from collections import Counter
  weights=Counter()
  for order in orders:
   for pos,uid in enumerate(order,1):weights[uid]+=1/(60+pos)
  top=sorted(weights,key=lambda uid:(-weights[uid],uid))[:20]
  save(cell/'top20.json',[dict(uid=u,title=units[u].unit_title,content=units[u].content,rule=units[u].operational_rule) for u in top])
  shortlist=[];seen=set()
  for uid in top:
   u=units[uid]
   from kb_adapter import fragment_payload
   for fragment in u.fragments:
    f=fragment_payload(K.data,fragment)
    if f['raw_text'].strip() and f['raw_text'] not in seen:
     seen.add(f['raw_text']);shortlist.append(dict(f,title=u.unit_title,uid=uid))

  res=await plan('从候选片段选与原题及本病例直接相关、可支持关键回答的原文，兼顾不同子问题并排除间接或重复材料。按价值降序给至多十个序号，允许少选或空选。仅输出JSON {"ids":[1,2]}。',dict(**obj,候选=[(j+1,f['title'],f['raw_text'][:160]) for j,f in enumerate(shortlist)]))
  ids=res['ids'];assert isinstance(ids,list);ids=[i for i in ids if type(i)==int and 1<=i<=len(shortlist)][:10]
  for i in dict.fromkeys(ids):
   f=shortlist[i-1]
   if f['raw_text'] not in [v['raw_text'] for v in ev]:ev.append(f)
  save(cell/'selector.json',dict(shortlist=[f['fragment_id'] for f in shortlist],ids=ids))
 save(cell/'evidence.json',ev)
 body='\n'.join(f"[E{i}] {f['source_title']}（{f['fragment_id']}） {f['raw_text']}" for i,f in enumerate(ev,1))
 pre=m['prefix'];a=await t.call('final',[{'role':'system','content':S},{'role':'user','content':pre+body}]);answer=a['content']
 (cell/'answer.md').write_text(answer,encoding='utf8')
 refs=sorted(set(map(int,re.findall(r'\[E(\d+)\]',answer))))
 save(cell/'result.json',dict(retrievals=len(history),evidence=len(ev),refs=refs,invalid=[i for i in refs if not 1<=i<=len(ev)],seconds=time.monotonic()-start,calls=t.calls))
```
