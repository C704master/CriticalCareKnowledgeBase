import asyncio,csv,json,re,sys,hashlib
from pathlib import Path
from dotenv import dotenv_values
D=Path(__file__).resolve().parent
F=D.parents[1];sys.path.insert(0,str(F))
from batch_transport import Transport,read,save
key=dotenv_values(F.parents[2]/'t06_prompt_pilot_20261117/.env')['QWEN_TRIAL_API_KEY']
cases={'F09':'吸痰前准备、预充氧的方式与时长、气囊压力监测频次；分为三个可独立判定的主张。','F04':'血液净化中采血部位和监测','F05':'抗菌药调整及感染病原是否已明确','F06':'撤机条件及判断有创通气开始时点','F07':'胰岛素管理、低钙风险与导管实际用途','F11':'撤机评估与抗凝剂量判断','F12':'乳酸趋势、血压指标与灌注目标','F13':'转出交接的监护要点与简洁要求','F14':'抗凝监测与抗菌药适用条件','F17':'感染指标与呼吸支持判断','F22':'感染疗效与容量、电解质处理','F25':'呼吸恶化与酸碱代偿解释'}
trace={r['病例']:r for r in csv.DictReader((D.parent/'12题追踪表.csv').open(encoding='utf-8-sig'))}
one='你是研究初评员。仅按实际材料核验所列子问题。对回答中出现的各项取最多4个关键主张；同句中的原则、操作方式/时长分别标注，保留原文适用条件。判的是文本支持程度，临床合理性不自行裁定。未答内容跳过。引句须连续逐字摘录，不能用省略号、改写或凭常识补造。返回JSON {"claims":[{"point":"主张","quote":"答案短原句","source":"E1或patient或none","excerpt":"相应来源连续短原句；无依据留空","support":"充分/部分/无支持/矛盾/待判","why":"一句理由"}]}。检查未点名的材料是否也支持；患者事实查患者输入。'
one+=' 每个子问题独立返回。仅评答案实际提出的主张，不得给答案未提出的主张造记录。并列的动作、设备、人群和时长能否联用必须逐项核对；仅分别出现各个词，不能据此断定组合用法充分。既往实际观测的时间点不提供规范性推荐间隔的依据。若给定了待审主张清单，应逐条照录为point并分别核验，不合并，不增加。'
two='盲评同一原题的两份答案。只比较给定子问题、两组原答和已定位的核源结果，忽略文风偏好。返回JSON {"rows":[{"gap":"具体子问题","side":"甲或乙","quote":"本方连续原句","other":"对方对应连续原句，缺项留空","gain":"补上遗漏/纠正判断/依据增益/无实质变化/无依据新增/退化/待判","why":"判断依据","breakpoint":"最早能证实的问题环节；缺检索轨迹不能猜测召回故障"}]}。最多4行，同一句原则及具体条件分别判断，双方核心判断相同而一方出处充分可独立记依据增益；纠正需要独立依据。保留负例及不确定。'
def parse(s):
 return json.loads(re.sub(r'^`{3}(?:json)?\s*|\s*`{3}$','',s.strip()))
async def call(cell,prompt,obj):
 cell.mkdir(exist_ok=True,parents=True);t=Transport(cell,cell,key)
 a=await t.call('review',[dict(role='system',content=prompt),dict(role='user',content=json.dumps(obj,ensure_ascii=False))],max_tokens=2400)
 return parse(a['content'])
async def run(tag):
 out=D/tag
 if (out/'result.json').exists():return
 c=F/tag;f=read(c/'freeze.json');name=['static','loop'] if int(tag[1:])%2 else ['loop','static']
 data={};checks={}
 async def side(arm):
  cell=c/arm; ans=(cell/'answer.md').read_text('utf8'); evidence=read(cell/'evidence.json')
  src={f'E{i}':v['raw_text'] for i,v in enumerate(evidence,1)}
  x=await call(out/arm,one,dict(原题=f['question'],事后拆解=cases[tag],待审主张清单=(['吸痰前应预充氧','手动呼吸给予纯氧3-5分钟'] if arm=='static' else ['建议每4–6小时监测气囊压力']) if tag=='F09' else [],实际患者输入=f['patient'],实际证据=src,原答=ans))
  for h in x['claims']:
   origin=h['source']; ex=h['excerpt']
   h['located']=bool(h['quote']) and h['quote'] in ans and (origin=='none' and not ex or bool(ex) and ex in ({**src,'patient':f['patient']}.get(origin,'')))
  return ans,x['claims']
 for label,(ans,claims) in zip('甲乙',await asyncio.gather(*(side(a) for a in name))):
  data[label]=ans;checks[label]=claims
 result=await call(out/'pair',two,dict(原题=f['question'],子问题=cases[tag],原答=data,核源={k:[v for v in vs if v['located']] for k,vs in checks.items()}))
 for row in result['rows']:
  k=row['side'];row['located']=k in data and bool(row['quote']) and row['quote'] in data[k] and (not row['other'] or row['other'] in data['乙' if k=='甲' else '甲'])
 save(out/'result.json',dict(names=dict(zip('甲乙',name)),single=checks,paired=result['rows']))
 print(tag,[(h['point'],h['support'],h['located']) for l,vs in checks.items() for h in vs] if tag=='F09' else 'done',flush=True)
async def main():
 sem=asyncio.Semaphore(2)
 async def job(t):
  async with sem:await run(t)
 await asyncio.gather(*(job(t) for t in sys.argv[1:]))
asyncio.run(main())
