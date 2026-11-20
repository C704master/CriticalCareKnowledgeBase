from pathlib import Path
import json,csv,statistics,collections
from review import o,read
def rows(f):return list(csv.DictReader((o/f).open(encoding='utf-8-sig')))
r=rows('表一_逐例检索及成本.csv');rr=rows('表二_病例配对结果.csv')
pairs=[];cp={(x['病例'],x['方法']):x for x in r}
def paired(c,first,second):
 names=read(c/'review/content_order.json');j=read(c/'review/pair_content/output.json')
 for k,v in j.items():
  if {names[k[0]],names[k[1]]}=={first,second}:
   w=names.get(v['优先'],v['优先']);return ('改善' if w==second else '回退' if w==first else w),v['理由']
 raise ValueError('missing')
for x in rr:
 c=o/x['病例']
 if not (c/'review/pair_content/output.json').exists():continue
 for key,a,b in [('拆解相对直答','direct','static'),('循环相对拆解','static','loop'),('循环相对直答','direct','loop')]:
  outcome,why=paired(c,a,b);x[key]=outcome;x[key+'理由']=why;pairs.append((key,x['题型'],outcome,x['病例'],why))
if len(rr)==30 and len(pairs)==90:
 with (o/'表二_病例配对及改善回退.csv').open('w',encoding='utf-8-sig',newline='') as f:
  w=csv.DictWriter(f,list(rr[0]));w.writeheader();w.writerows(rr)
 freq=collections.Counter
 print('PAIR',[(k,dict(freq(z[2] for z in pairs if z[0]==k))) for k in dict.fromkeys(z[0] for z in pairs)])
 groups=list(dict.fromkeys(x['题型'] for x in rr))
 out=['# 30例三组配对实验 · 研究初评','', '30 位患者、30 道真实医生原题、90 份回答。患者摘要与连续三日日档按提问时刻裁剪。两查库组均最多四次检索、十条去重知识原文，采用相同排序融合和共用生成提示。每位患者仅贡献一题。抽样是为比较题型的目的抽样，各层例数不代表临床发生率。','', '[30例选样名单与检查点](正式30例选样清单.md) · [表一逐例原始指标](表一_逐例检索及成本.csv) · [表二完整病例配对](表二_病例配对及改善回退.csv) · [回答及病例定位](重要判断原句与初评.csv) · [知识、原文逐条标签](检索与原文逐条标签.csv)','', '## 表一　检索指标','', '|方法|Hit@5/10/20（题数）|P@5/10/20|MRR@20|实际查询|直接贴题/实际入模|正文点名有效条次|越界编号涉及答案|','|---|---|---|---:|---:|---:|---:|---:|']
 for a,name in [('direct','直答'),('static','一次拆解'),('loop','动态补查')]:
  sel=[x for x in r if x['方法']==a]
  summ=lambda k:sum(int(x[k]) for x in sel if x[k]!='')
  mean=lambda k:statistics.mean(float(x[k]) for x in sel if x[k]!='')
  hit='／'.join(str(summ('Hit@'+str(k))) for k in [5,10,20]) if a!='direct' else '—'
  prec='／'.join(f'{mean("P@"+str(k)):.1%}' for k in [5,10,20]) if a!='direct' else '—'
  mrr=f"{mean('RR@20'):.3f}" if a!='direct' else '—'
  out.append(f'|{name}|{hit}|{prec}|{mrr}|{summ("检索")}|{summ("直接贴题原文")}/{summ("入模")}|{summ("点名有效原文")}|{sum(bool(x["越界编号"]) for x in sel)}|')
 out+=['','检索以最终Top20知识条目评价，直接贴题和引用以真正入模的L5原文另计。相同知识条目可对应多个片段，引用条次在每份答案内去重。直答无检索。无全库穷尽相关集。','', '## 表二　30例回答的配对初评','','同题三答随机排列；内容比较隐藏方法和引用编号，按原题、患者事实和预设关注点比较每一对。另一次评阅打开实际提供的原文核对主张。两遍都由模型初评，须由医生判断临床严重度。改善和回退指研究评阅偏好。','', '|比较|题型|改善|相当|回退|难判|','|---|---|---:|---:|---:|---:|']
 for key in dict.fromkeys(z[0] for z in pairs):
  for g in ['全部']+groups:
   h=freq(z[2] for z in pairs if z[0]==key and (g=='全部' or z[1]==g));out.append('|'+key+'|'+g+'|'+'|'.join(str(h[k]) for k in ['改善','相当','回退','难判'])+'|')
 out+=['','|病例和匿名原答|原题|拆解相对直答|循环相对拆解|','|---|---|---|---|']
 for x in rr:out.append('|[{}]({})|{}|{} · {}|{} · {}|'.format(x['病例'],x['原文入口'],x['原题'].replace('|','／'),x['拆解相对直答'],x['拆解相对直答理由'].replace('|','／'),x['循环相对拆解'],x['循环相对拆解理由'].replace('|','／')))
 (o/'30例验收结果.md').write_text('\n'.join(out),'utf8')
else:print('paired so far',len(pairs)//3,'clinical reviews',len(rr))
