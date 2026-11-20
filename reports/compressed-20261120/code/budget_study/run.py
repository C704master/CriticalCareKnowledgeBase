from pathlib import Path
import sys,asyncio,json,re,hashlib
from dotenv import dotenv_values
out=Path(__file__).resolve().parent
d=out.parent
sys.path.insert(0,str(d))
from pilot_transport import Transport,read,save,sha
c=d/'C11/static'
base=read(next(c.glob('calls/*_final/request.json')))
original=read(c/'evidence.json')
sel=read(c/'selector.json')['shortlist']
byid={f['fragment_id']:f for p in sorted(c.glob('query*/selected_evidence.json')) for u in read(p) for f in json.loads(u['content'])['fragments']}
l5=d.parents[2]/'data/05_evidence_fragments/evidence_fragments.jsonl'
source={z['fragment_id']:z for line in l5.open(encoding='utf-8-sig') if (z:=json.loads(line)).get('quality_flag')!='retired'}
# Ordered before any new generation. Extend the historical six using the same frozen shortlist.
order=[3,27,21,12,18,16,2,13,28]
ev=original+[byid[sel[i-1]] for i in order]
assert len({f['fragment_id'] for f in ev})==len({f['raw_text'] for f in ev})==15
for f in ev:assert source[f['fragment_id']]['raw_text']==f['raw_text']
def render(i,f):return f"[E{i}] {f['source_title']}（{f['fragment_id']}） {f['raw_text']}"
prefix=read(d/'C11/freeze.json')['prefix']
def content(n):return prefix+'\n'.join(render(i,f) for i,f in enumerate(ev[:n],1))
assert base['messages'][1]['content']==content(6)
save(out/'design.json',dict(case='C11',arm='static',base_request=sha(next(c.glob('calls/*_final/request.json'))),selection='existing six; manual nested extension before generation',predefined_topics=['俯卧位管路与循环风险','意外拔管应急','人机对抗处置','疼痛镇静连续评估','危及生命低血压时的复苏条件','肺损伤及疼痛辨认'],evidence=ev))
key=dotenv_values(d.parents[1]/'t06_prompt_pilot_20261117/.env')['QWEN_TRIAL_API_KEY']
async def run(n):
 cell=out/str(n);cell.mkdir(exist_ok=True)
 msg=[base['messages'][0],dict(role='user',content=content(n))]
 t=Transport(cell,cell,key)
 resp=await t.call('final',msg,max_tokens=base['max_tokens'])
 p=cell/'calls/01_final';req=read(p/'request.json')
 assert req==dict(base,messages=msg)
 r=read(p/read(p/'checkpoint.json')['selected_attempt']/'response.json');assert r['finish_reason']=='stop'
 ans=resp['content'];(cell/'answer.md').write_text(ans,encoding='utf8')
 save(cell/'outcome.json',dict(usage=r['usage'],references=re.findall(r'\[E(\d+)\]',ans),finish=r['finish_reason']))
async def main():
 results=await asyncio.gather(*(run(n) for n in [8,10,15]),return_exceptions=True)
 for x in results:
  if isinstance(x,BaseException):raise x
asyncio.run(main())
