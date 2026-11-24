from evidence_refs import without_refs
import asyncio,random
from review import o,read,save,armdata,checks,remote
async def main():
 done=set()
 while len(done)<30:
  ready=[o/m['tag'] for m in read(o/'manifest.json') if m['tag'] not in done and all((o/m['tag']/a/'result.json').exists() for a in ('direct','static','loop'))]
  if not ready:await asyncio.sleep(5);continue
  for c in ready:
   d=armdata(c);order=list(d);random.Random('content-'+c.name).shuffle(order);names=dict(zip('甲乙丙',order));save(c/'review/content_order.json',names);m=read(c/'freeze.json')
   def validate(j):
    assert set(j)=={'甲乙','甲丙','乙丙'}
    for k,v in j.items():assert v['优先'] in [k[0],k[1],'相当','难判'] and v['理由']
   try:
    await remote(c,'pair_content','三份为同一真实病例的匿名回答，只按完成原题、重要事实正确和推断审慎比较。不要因文献口吻、篇幅或建议多少加分。评每一对；仅在存在具体、有意义差异时选择更好的一份，否则相当或难判。对每对用一个具体临床句说明增益或回退（45字以内）。给 JSON {"甲乙":{"优先":"甲、乙、相当或难判之一","理由":"..."},"甲丙":同格式,"乙丙":同格式}。',dict(原题=m['question'],截止=m['cutoff'],患者=m['patient'],关注=checks[int(c.name[1:])-1],回答={k:without_refs(d[a]['ans']) for k,a in names.items()}),validate)
    print('PAIRED',c.name,flush=True)
   except Exception as e:print('PAIR_FAIL',c.name,type(e).__name__,flush=True)
   done.add(c.name)
asyncio.run(main())
