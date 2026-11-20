import asyncio,json,sys,os,re,time,hashlib,subprocess
from pathlib import Path
from dotenv import dotenv_values
D=Path(__file__).resolve().parent
W=D.parents[1];ROOT=W.parents[1]
R=next(W.glob('case10_acceptance*/outputs/case12_acceptance/qwen38_matched_abc12_20261112'))
sys.path[:0]=list(map(str,[R,R/'dependencies',ROOT/'knowledge_reorg',ROOT]))
os.environ.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',SEPSIS_LOG_DIR=str(D/'logs'),SEPSIS_TRACE_DIR=str(D/'trace'),TOKENIZERS_PARALLELISM='false')
from pilot_transport import Transport,read,save,sha
from kb_adapter import Knowledge,Pool
P=W/'six_evidence_control_20261119/controlled_raw/5/C6_prompt_v10_fixed/fixed_system_prompt.txt'
S=P.read_text('utf8').strip()
assert sha(P)=='caaef8cfd052a75bdfae61eea2cb326969467f7343f10f1f10a62561b5bdb1ca'
K=Knowledge()
import numpy as np
vec=K.data.bge_encode_query('机械通气 气道护理')
assert vec is not None and np.isfinite(vec).all() and K.data.l4_embedding_available()
snapshot={str(p.relative_to(ROOT)):sha(p) for p in sorted((ROOT/'knowledge_reorg/data').rglob('*.jsonl'))}
if (D/'environment.json').exists():assert read(D/'environment.json')['snapshot']==snapshot
save(D/'environment.json',{'embedding_dimensions':len(vec),'l4_available':True,'snapshot':snapshot})
key=dotenv_values(W/'t06_prompt_pilot_20261117/.env')['QWEN_TRIAL_API_KEY']
def planjson(s):
 return json.loads(re.sub(r'^\x60\x60\x60(?:json)?\s*|\s*\x60\x60\x60$','',s.strip()))
async def run(tag,arm):
 cell=D/tag/arm;m=read(D/tag/'freeze.json');cell.mkdir(exist_ok=True)
 if (cell/'result.json').exists():return
 t=Transport(D,cell,key);start=time.monotonic();lists=[];history=[];results=[]
 async def plan(instr,obj):
  msg=await t.call('plan',[{'role':'system','content':instr},{'role':'user','content':json.dumps(obj,ensure_ascii=False)}],max_tokens=900)
  return planjson(msg['content'])
 def search(q):
  assert len(history)<4
  p=Pool(K,q,cell/f'query{len(history)+1}');p.retrieve(q);rank=[]
  for u in p.selected:
   z=json.loads(u['content'])
   for f in z['fragments']:
    if f['raw_text'].strip():rank.append(dict(**f,title=z['unit_title'],uid=z['unit_id'],score=u['semantic_score']))
  lists.append(rank);history.append(dict(query=q,hits=[{'title':v['title'],'fragment_id':v['fragment_id']} for v in rank[:8]]))
  save(cell/'history.json',history)
 obj={'原题':m['question'],'截止':m['cutoff'],'病例':m['patient']}
 resume_final=next(cell.glob('calls/*_final/request.json'),None)
 if resume_final:
  history=read(cell/'history.json') if (cell/'history.json').exists() else []
  for previous in sorted((cell/'calls').glob('*')):
   if previous==resume_final.parent:break
   p=read(previous/'request.json')
   await t.call('plan',p['messages'],max_tokens=p['max_tokens'])
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
  shortlist=candidates[:28]
  res=await plan('从候选片段选与原题及本病例直接相关、可支持关键回答的原文，兼顾不同子问题并排除间接或重复材料。按价值降序给至多六个序号，允许少选或空选。仅输出JSON {"ids":[1,2]}。',dict(**obj,候选=[(j+1,f['title'],f['raw_text'][:160]) for j,f in enumerate(shortlist)]))
  ids=res['ids'];assert isinstance(ids,list) and len(ids)<=6 and all(type(i)==int and 1<=i<=len(shortlist) for i in ids)
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
async def main():
 if sys.argv[1]=='C35':
  for arm in ('direct','static','loop'):
   # 两病例已经过首例放行，各自的请求独立；先等待本轮都落盘。
   outcomes=await asyncio.gather(*(run(case,arm) for case in ('C35','C17')),return_exceptions=True)
   for outcome in outcomes:
    if isinstance(outcome,BaseException):raise outcome
 else:
  outcomes=await asyncio.gather(*(run(sys.argv[1],arm) for arm in ('direct','static','loop')),return_exceptions=True)
  for outcome in outcomes:
   if isinstance(outcome,BaseException):raise outcome
asyncio.run(main())




