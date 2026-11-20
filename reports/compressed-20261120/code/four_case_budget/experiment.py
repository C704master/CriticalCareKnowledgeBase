import sys,asyncio,os,json,re
from pathlib import Path
from dotenv import dotenv_values
O=Path(__file__).resolve().parent;D=O.parent;W=D.parents[1];root=W.parents[1]
R=next(W.glob('case10_acceptance*/outputs/case12_acceptance/qwen38_matched_abc12_20261112'))
sys.path[:0]=list(map(str,[D,R,R/'dependencies',root/'knowledge_reorg',root]))
os.environ.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',SEPSIS_LOG_DIR=str(O/'logs'),SEPSIS_TRACE_DIR=str(O/'traces'))
from pilot_transport import Transport,read,save,sha
from kb_adapter import Knowledge,Pool
import numpy as np
K=Knowledge();v=K.data.bge_encode_query('临床监护');assert np.isfinite(v).all() and K.data.l4_embedding_available()
source=root/'knowledge_reorg/data/05_evidence_fragments/evidence_fragments.jsonl'
snapshot=read(D/'environment.json')['snapshot']
for name,h in snapshot.items():assert sha(root/name)==h
save(O/'environment.json',dict(dim=len(v),snapshot=snapshot))
key=dotenv_values(W/'t06_prompt_pilot_20261117/.env')['QWEN_TRIAL_API_KEY'];S=(D/'citation_rule_r1/system_prompt.txt').read_text('utf8')
sem=asyncio.Semaphore(5)
async def call(cell,stage,msg,max_tokens):
 cell.mkdir(exist_ok=True,parents=True)
 async with sem:return (await Transport(cell,cell,key).call(stage,msg,max_tokens=max_tokens))['content']
async def plan(cell,prompt,obj):
 raw=await call(cell,'plan',[dict(role='system',content=prompt),dict(role='user',content=json.dumps(obj,ensure_ascii=False))],1500)
 return json.loads(re.sub(r'^\x60\x60\x60(?:json)?\s*|\s*\x60\x60\x60$','',raw.strip()))
async def experiment(tag):
 c=O/tag;m=read(c/'input.json');obj={'原题':m['question'],'病例':m['patient'],'截止':m['cut']}
 if not (c/'evidence.json').exists():
  qs=(await plan(c/('planning_reconnect' if tag=='C13' else 'planning'),'一次规划四个互补的知识检索问题，覆盖本例重要知识需求。只输出JSON {"queries":["..."]}',obj))['queries'];assert 1<=len(qs)<=4
  ranks=[]
  for i,q in enumerate(qs):
   folder=c/f'query{i+1}';p=Pool(K,q,folder)
   if not (folder/'selected_evidence.json').exists():p.retrieve(q)
   ranks.append([f for u in read(folder/'selected_evidence.json') for f in json.loads(u['content'])['fragments'] if f['raw_text'].strip()])
  seen=set();texts=set();cand=[]
  for i in range(max(map(len,ranks))):
   for rank in ranks:
    if i<len(rank):
     f=rank[i]
     if f['fragment_id'] not in seen and f['raw_text'] not in texts:
      seen.add(f['fragment_id']);texts.add(f['raw_text']);cand.append(f)
  cand=cand[:65];save(c/'candidate_order.json',cand)
  ids=(await plan(c/'selection','从实际检索片段选出与本例有关的最多15条，最直接有用者优先，前6条兼顾各子问题，其后逐步增加不同的条件或背景。若不足可少选。仅输出JSON {"ids":[一基序号]}。',dict(**obj,候选=[(i+1,f['raw_text'][:210]) for i,f in enumerate(cand)])))['ids']
  ids=list(dict.fromkeys(i for i in ids if type(i)==int and 1<=i<=len(cand)))[:15];assert ids
  save(c/'evidence.json',[cand[i-1] for i in dict.fromkeys(ids)])
 ev=read(c/'evidence.json')
 async def answer(n):
  cell=c/str(n);es=ev[:n];msg=[dict(role='system',content=S),dict(role='user',content=m['prefix']+'\n'.join(f"[E{i}] {f['source_title']}（{f['fragment_id']}） {f['raw_text']}" for i,f in enumerate(es,1)))]
  a=await call(cell,'final',msg,8192);p=cell/'calls/01_final';req=read(p/'request.json')
  res=read(p/read(p/'checkpoint.json')['selected_attempt']/'response.json');assert res['finish_reason']=='stop' and req['messages']==msg
  (cell/'answer.md').write_text(a,encoding='utf8')
  save(cell/'outcome.json',dict(budget=n,actual=len(es),usage=res['usage'],finish='stop',patient_input_sha=sha(c/'input.json'),refs=re.findall(r'\[E(\d+)\]',a)))
 results=await asyncio.gather(*(answer(n) for n in [0,6,8,10,15]),return_exceptions=True)
 for res in results:
  if isinstance(res,BaseException):raise res
 print('DONE',tag,len(ev),flush=True)
async def main():
 for tag in ['C27','C13','C31','C47']:await experiment(tag)
asyncio.run(main())



