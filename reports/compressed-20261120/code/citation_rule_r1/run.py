import sys,asyncio,copy
from pathlib import Path
from dotenv import dotenv_values
out=Path(__file__).resolve().parent
d=out.parent
sys.path.insert(0,str(d))
from pilot_transport import Transport,read,save,sha
rule='仅在知识原文直接支持当前句子或其中明确指出的判断时标注编号。材料未覆盖某项建议时，可依据患者资料作条件性分析；若缺少依据会影响具体剂量、阈值或处置选择，简要说明缺什么。无需在正文列举已排除的无关证据。'
key=dotenv_values(d.parents[1]/'t06_prompt_pilot_20261117/.env')['QWEN_TRIAL_API_KEY']
async def run(n):
 cell=out/str(n);cell.mkdir(exist_ok=True)
 old=d/'C11/static' if n==6 else d/'budget_study'/str(n)
 src=next(old.glob('calls/*_final/request.json'));prev=read(src)
 req=copy.deepcopy(prev);req['messages'][0]['content']+='\n'+rule
 t=Transport(cell,cell,key)
 a=await t.call('final',req['messages'],max_tokens=req['max_tokens'])
 p=cell/'calls/01_final';assert read(p/'request.json')==req
 r=read(p/read(p/'checkpoint.json')['selected_attempt']/'response.json');assert r['finish_reason']=='stop'
 (cell/'answer.md').write_text(a['content'],encoding='utf8')
 save(cell/'verification.json',dict(old_request_sha=sha(src),new_request_sha=sha(p/'request.json'),usage=r['usage'],only_change='system prompt appended rule',finish=r['finish_reason']))
async def main():
 pre=read(next((d/'C11/static').glob('calls/*_final/request.json')))['messages'][0]['content']
 (out/'system_prompt.txt').write_text(pre+'\n'+rule,encoding='utf8')
 results=await asyncio.gather(*(run(n) for n in (6,8,10,15)),return_exceptions=True)
 for result in results:
  if isinstance(result,BaseException):raise result
asyncio.run(main())
