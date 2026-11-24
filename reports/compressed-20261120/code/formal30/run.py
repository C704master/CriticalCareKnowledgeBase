import asyncio,json,sys,os,re,time,hashlib,subprocess
import argparse
from pathlib import Path
from applicability import answer_material, fragment_text
from evidence_selector import build_shortlist, candidate, selection_messages, validate_selection
from evidence_refs import refs as cited_ids
from dotenv import dotenv_values
D=Path(__file__).resolve().parent
base=D.parent;W=base.parents[1];ROOT=W.parents[1]
R=next(W.glob('case10_acceptance*/outputs/case12_acceptance/qwen38_matched_abc12_20261112'))
sys.path[:0]=list(map(str,[base,R,R/'dependencies',ROOT/'knowledge_reorg',ROOT]))
os.environ.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',SEPSIS_LOG_DIR=str(D/'logs'),SEPSIS_TRACE_DIR=str(D/'trace'),TOKENIZERS_PARALLELISM='false')
from batch_transport import Transport,read,save,sha
parser=argparse.ArgumentParser()
parser.add_argument('--case', choices=[r['tag'] for r in read(D/'manifest.json')])
parser.add_argument('--run-id', help='New isolated run using the pre-answer applicability check')
parser.add_argument('--frozen-evidence',action='store_true')
args=parser.parse_args()
if bool(args.case)!=bool(args.run_id) or (args.frozen_evidence and not args.run_id):
 parser.error('supply --case and --run-id together')
if args.run_id and not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,64}',args.run_id):
 parser.error('invalid run id')
output=D/'applicability_runs'/args.run_id if args.run_id else D
P=W/'six_evidence_control_20261119/controlled_raw/5/C6_prompt_v10_fixed/fixed_system_prompt.txt'
S=(base/'citation_rule_r1/system_prompt.txt').read_text('utf8')
assert sha(P)=='caaef8cfd052a75bdfae61eea2cb326969467f7343f10f1f10a62561b5bdb1ca'
if not args.frozen_evidence:
 from kb_adapter import Knowledge,Pool
 K=Knowledge()
 import numpy as np
 vec=K.data.bge_encode_query('机械通气 气道护理')
 assert vec is not None and np.isfinite(vec).all() and K.data.l4_embedding_available()
 snapshot={str(p.relative_to(ROOT)):sha(p) for p in sorted((ROOT/'knowledge_reorg/data').rglob('*.jsonl'))}
 if (base/'environment.json').exists():assert read(base/'environment.json')['snapshot']==snapshot
 save(output/'environment.json',{'embedding_dimensions':len(vec),'l4_available':True,'snapshot':snapshot})
key=dotenv_values(W/'t06_prompt_pilot_20261117/.env')['QWEN_TRIAL_API_KEY']
def planjson(s):
 return json.loads(re.sub(r'^\x60\x60\x60(?:json)?\s*|\s*\x60\x60\x60$','',s.strip()))
async def run(tag,arm):
 cell=output/tag/arm;m=read(D/tag/'freeze.json');cell.mkdir(parents=True,exist_ok=True)
 original=D/tag/arm
 if (cell/'result.json').exists():return
 t=Transport(cell,cell,key);start=time.monotonic();history=[];results=[];units={};orders=[]
 async def plan(instr,obj):
  msg=await t.call('plan',[{'role':'system','content':instr},{'role':'user','content':json.dumps(obj,ensure_ascii=False)}],max_tokens=900)
  return planjson(msg['content'])
 def search(q):
  assert len(history)<4
  p=Pool(K,q,cell/f'query{len(history)+1}');p.retrieve(q);hits=[]
  for u in p.selected:
   z=json.loads(u['content'])
   for f in z['fragments']:
    if f['raw_text'].strip():
     hits.append({'title':z['unit_title'],'fragment_id':f['fragment_id']})
     if len(hits)==8:break
   if len(hits)==8:break
  from dataclasses import replace
  from query_engine.sorter import rank_units_v2
  scores=K.data.l4_cosine_scores(p.query_vector,list(p.candidates))
  missing=[k for k in p.candidates if k not in scores]
  if missing:
   vs=K.data._get_bge_model().encode([p.candidates[k].unit_title+'。'+p.candidates[k].content for k in missing],normalize_embeddings=True)
   scores.update({k:float(np.dot(v,p.query_vector)) for k,v in zip(missing,vs)})
  ordered=rank_units_v2([replace(p.candidates[k],_semantic_score=scores[k],_reranker_score=None) for k in sorted(p.candidates)])
  orders.append([u.unit_id for u in ordered])
  save(p.directory/'fusion_order.json', orders[-1])
  for u in ordered:units[u.unit_id]=u
  history.append(dict(query=q,hits=hits))
  save(cell/'history.json',history)
 obj={'原题':m['question'],'截止':m['cutoff'],'病例':m['patient']}
 resume_final=next(cell.glob('calls/*_final/request.json'),None)
 if resume_final:
  history=read(cell/'history.json') if (cell/'history.json').exists() else []
  for previous in sorted((cell/'calls').glob('*')):
   if previous==resume_final.parent:break
   p=read(previous/'request.json')
   await t.call('plan',p['messages'],max_tokens=p['max_tokens'])
 if arm=='static' and not resume_final and not args.frozen_evidence:
  qs=(await plan('一次规划最多四个互补的知识检索词句，围绕本题重点和可推广知识，勿查患者事实。仅给JSON {"queries":["..."]}。',obj))['queries']
  assert isinstance(qs,list) and 1<=len(qs)<=4
  for q in dict.fromkeys(qs):search(q)
 if arm=='loop' and not resume_final and not args.frozen_evidence:
  for i in range(4):
   res=await plan('你在进行逐次知识检索。结合病例、原题和已查结果判断仍缺哪个最关键的知识依据。输出JSON {"reason":"已有覆盖与缺口","query":"一个检索词句"}。若已有足够依据或再查无益，query为空。初次须提出检索。',dict(**obj,已查=history))
   results.append(res);save(cell/'decisions.json',results);q=res['query'].strip()
   if not q or q in [h['query'] for h in history]:break
   search(q)
 ev=read(cell/'evidence.json') if resume_final else []
 if orders:
  # Apply the same reciprocal-rank fusion to both arms before source selection.
  from collections import Counter
  weights=Counter()
  for order in orders:
   for pos,uid in enumerate(order,1):weights[uid]+=1/(60+pos)
  top=sorted(weights,key=lambda uid:(-weights[uid],uid))[:20]
  save(cell/'top20.json',[dict(uid=u,title=units[u].unit_title,content=units[u].content,rule=units[u].operational_rule) for u in top])
  from kb_adapter import fragment_payload
  shortlist=build_shortlist((units[uid] for uid in top), lambda f: fragment_payload(K.data,f))

  paired = [candidate(i, f, units[f['uid']].operational_rule) for i, f in enumerate(shortlist, 1)]
  messages = selection_messages(obj, paired)
  reply = await t.call('plan', messages, max_tokens=2400)
  selections = validate_selection(planjson(reply['content']), paired)
  ids = [row['编号'] for row in selections]
  ev = [shortlist[i-1] for i in ids]
  save(cell/'selector.json', dict(version='l4_l5_source_bindings_v2', shortlist=[f['fragment_id'] for f in shortlist],
                                  bindings=[f['bindings'] for f in shortlist],
                                  ids=ids, selections=selections, call=t.calls[-1]['logical_call']))
 if args.frozen_evidence:
  ev=read(original/'evidence.json')
  old_request=read(next((original/'calls').glob('*_final/request.json')))
  original_text=m['prefix']+'\n'.join(fragment_text(i,f) for i,f in enumerate(ev,1))
  if old_request['messages']!=[{'role':'system','content':S},{'role':'user','content':original_text}]:
   raise ValueError('frozen input mismatch')
  if len(ev)>10 or (arm=='direct' and ev):raise ValueError('invalid frozen evidence')
 save(cell/'evidence.json',ev)
 eligible=[f'E{i}' for i in range(1,len(ev)+1)]
 final_transport=t
 if args.run_id:
  stage=cell/'answer_stage'
  final_transport=Transport(cell,stage,key)
  rankdir=original if args.frozen_evidence else cell
  ranks=read(rankdir/'top20.json') if ev else []
  content,eligible=await answer_material(final_transport,cell,m,ev,ranks)
 else:
  content=m['prefix']+'\n'.join(fragment_text(i,f) for i,f in enumerate(ev,1))
 a=await final_transport.call('final',[{'role':'system','content':S},{'role':'user','content':content}])
 answer=a['content']
 (cell/'answer.md').write_text(answer,encoding='utf8')
 refs=sorted(cited_ids(answer))
 calls=t.calls if final_transport is t else t.calls+final_transport.calls
 result=dict(retrievals=len(history),evidence=len(eligible),refs=refs,invalid=[i for i in refs if f'E{i}' not in eligible],seconds=time.monotonic()-start,calls=calls)
 if args.run_id:
  result.update(run_id=f'{args.run_id}/{tag}/{arm}',eligible=eligible,selected=len(ev),
                mode='frozen' if args.frozen_evidence else 'live',cutoff=m['cutoff'],
                patient_sha256=hashlib.sha256(m['patient'].encode()).hexdigest())
  if args.frozen_evidence:result['original_retrievals']=read(original/'result.json')['retrievals']
 save(cell/'result.json',result)
async def main():
 sem=asyncio.Semaphore(8)
 async def work(tag,arm):
  async with sem:
   try:
    await run(tag,arm)
    print('DONE',tag,arm,flush=True)
   except Exception as exc:
    print('FAIL',tag,arm,type(exc).__name__,str(exc)[:90],flush=True)
 if args.run_id:
  design={'case':args.case,'frozen_evidence':args.frozen_evidence,'run_id':args.run_id,'applicability_policy':'annotate_all_selected'}
  manifest=output/'design.json'
  if manifest.exists() and read(manifest)!=design:raise ValueError('run id already used')
  save(manifest,design)
  results=await asyncio.gather(*(run(args.case,arm) for arm in ('direct','static','loop')),return_exceptions=True)
  for arm,result in zip(('direct','static','loop'),results):
   if isinstance(result,BaseException):raise RuntimeError(f'{args.case}/{arm}: {result}') from result
  return
 cases=read(D/'manifest.json')
 await asyncio.gather(*(work(m['tag'],arm) for m in cases for arm in ('direct','static','loop')))
asyncio.run(main())
