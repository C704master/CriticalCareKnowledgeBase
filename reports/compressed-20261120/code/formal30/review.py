from pathlib import Path
import json,re,asyncio,sys,random,hashlib,os
from dotenv import dotenv_values
from batch_transport import Transport,read,save
o=Path(__file__).resolve().parent;w=o.parent.parents[1]
key=dotenv_values(w/'t06_prompt_pilot_20261117/.env')['QWEN_TRIAL_API_KEY']
checks=(o/'预设检查点.txt').read_text('utf-8-sig').splitlines()
def refs(txt):
 ids=[]
 for g in re.finditer(r'\[E\s*\d+(?:\s*[-–—至,，、]\s*E?\s*\d+)*\](?:\s*[-–—至]\s*\[E\d+\])?',txt):
  nums=list(map(int,re.findall(r'\d+',g.group())))
  if len(nums)==2 and re.search(r'[-–—至]',g.group()) and 0<nums[0]<=nums[1]<=100:nums=list(range(nums[0],nums[1]+1))
  ids.extend(nums)
 return list(dict.fromkeys(ids))
def armdata(c):
 m=read(c/'freeze.json');out={}
 for a in ['direct','static','loop']:
  d=c/a;ev=read(d/'evidence.json');answer=(d/'answer.md').read_text('utf8');p=next(d.glob('calls/*_final/request.json'))
  r=read(p);res=read(p.parent/read(p.parent/'checkpoint.json')['selected_attempt']/'response.json')
  raw='\n'.join(f"[E{i}] {f['source_title']}（{f['fragment_id']}） {f['raw_text']}" for i,f in enumerate(ev,1))
  assert r['messages'][1]['content']==m['prefix']+raw and r['messages'][0]['content']==(o.parent/'citation_rule_r1/system_prompt.txt').read_text('utf8')
  assert res['finish_reason']=='stop' and res['message']['content']==answer and len(ev)<=10 and not r.get('tools')
  if a=='direct':assert not ev and not list(d.glob('query*'))
  out[a]=dict(ev=ev,ans=answer,refs=refs(answer),rank=read(d/'top20.json') if (d/'top20.json').exists() else [])
 return out
async def remote(c,k,prompt,obj,valid):
 dest=c/'review'/k
 if (dest/'output.json').exists():return
 for n in range(3):
  cell=dest/('pass'+str(n+1));cell.mkdir(parents=True,exist_ok=True)
  msg=[dict(role='system',content=prompt+' 只给合法JSON，无markdown。'),dict(role='user',content=json.dumps(obj,ensure_ascii=False))]
  try:
   raw=(await Transport(cell,cell,key).call('review',msg,max_tokens=4200))['content']
   j=json.loads(re.sub(r'^```(?:json)?\s*|\s*```$','',raw.strip()));valid(j);save(dest/'output.json',j);return
  except Exception as exc:
   print('review retry',c.name,k,n,type(exc).__name__,flush=True)
   await asyncio.sleep(12)
 raise RuntimeError(k)
async def review(c):
 m=read(c/'freeze.json');arms=armdata(c);case=dict(问题=m['question'],截止=m['cutoff'],患者=m['patient'],预设关注=checks[int(c.name[1:])-1])
 items={}
 for a,x in arms.items():
  for u in x['rank']:items['U'+u['uid']]=u['title']+'。'+u['content']
  for e in x['ev']:items['F'+e['fragment_id']]=e['raw_text']
 ids=list(items);random.Random(c.name).shuffle(ids);save(c/'review/key.json',ids)
 query=dict(**case,材料=[(i+1,items[v]) for i,v in enumerate(ids)])
 def check(j):
  groups=[j[k] for k in ('direct','background','unknown')]
  flat=[i for v in groups for i in v]
  assert all(isinstance(x,int) and 1<=x<=len(ids) for x in flat)
  assert len(set(groups[0])&set(groups[1]))==0
  j['labels']=[None if i in groups[2] else 2 if i in groups[0] else 1 if i in groups[1] else 0 for i in range(1,len(ids)+1)]
 await remote(c,'relevance_v2','你是医学信息检索相关性评阅者。为每个编号独立判定对本患者原题的价值，阅读全文。direct=直接回答一个重要子问题，background=仅背景或适用条件未满足，unknown=读不清或无法判断，其余你判为无关。只输出分组后的材料序号集合，每一组使用整数列表，不输出理由。格式 {"direct":[2,4],"background":[1],"unknown":[]}。例子数字仅示范格式；只填本题实际适合者。',query,check)
 order=list(arms);random.Random('blind'+c.name).shuffle(order);save(c/'review/blind.json',order)
 query=dict(**case,匿名答案=[dict(标签=l,回答=arms[a]['ans'],引文=[(i+1,e['raw_text']) for i,e in enumerate(arms[a]['ev'],0)]) for l,a in zip('甲乙丙',order)])
 def qc(j):
  assert set(j['answers'])==set('甲乙丙')
  for l,a in zip('甲乙丙',order):
   z=j['answers'][l]
   import difflib
   for k,src in [('quote',arms[a]['ans']),('fact',m['patient'])]:
    val=z[k]
    if val in src and val:continue
    z[k+'_model']=val
    hits=difflib.SequenceMatcher(None,val,src,autojunk=False).get_matching_blocks()
    hit=max(hits,key=lambda v:v.size)
    if hit.size>=6:
     z[k]=src[hit.b:hit.b+hit.size]
     z[k+'_status']='模型摘录非逐字，仅显示可定位的最长连续部分'
    else:
     z[k]='〔原句未可靠定位，需复核〕';z[k+'_status']='未定位'

  assert j.get('best') in ['甲','乙','丙','相当','各有得失']
 await remote(c,'quality','对同题三份答案做研究初评。每份给一个最重要贡献和一个局限；依据实际给出的病例和引文，特别核对截止时刻、跨日、趋势、适用条件。明确区分有直接反证与未获支持。仅提重点，不能宣布全文零错。返回 {"answers":{"甲":{"gain":"不超过65字的具体判断","limit":"不超过65字的局限","quote":"对应回答原文逐字短引","fact":"病例中逐字短引","support":"充分/部分/不支持/未引/无法判断"},"乙":同格式,"丙":同格式},"best":"甲/乙/丙/相当/各有得失","reason":"比较关键内容是否更好，不因用引文而加分"}。只返回JSON。',query,qc)
async def main():
 for m in read(o/'manifest.json'):
  c=o/m['tag']
  if not all((c/a/'result.json').exists() for a in ('direct','static','loop')):continue
  try:await review(c);print('REVIEWED',c.name,flush=True)
  except Exception as e:print('REVIEW_FAIL',c.name,type(e).__name__,flush=True)
if __name__=='__main__':asyncio.run(main())
