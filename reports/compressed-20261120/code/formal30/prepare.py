from pathlib import Path
import sys,re,json,datetime,subprocess,os,concurrent.futures
from dotenv import dotenv_values
o=Path(__file__).resolve().parent;sys.path.insert(0,str(o.parent))
from freeze import read,save,count,sha,redact,W
d=W/'archive_three_case_20261118/controlled_raw';rows=read(d/'metadata.json')
groups={'护理重点':[3,21,43,50,51,88,64,71,74,75],'病程与交接':[67,68,69,58,87,95,98,139,113,114,115,123],'具体判断与方案':[53,57,81,92,104,120,127,134]}
e=dotenv_values(W/'db_context_freshness_20261116/.env')
def query(sql):
 r=subprocess.run(['mysql','--connect-timeout=15','--host='+e['DB_HOST'],'--port='+e['DB_PORT'],'--user='+e['DB_USER'],'--protocol=TCP','--default-character-set=utf8mb4','--batch','--raw','--skip-column-names'],input='SET SESSION TRANSACTION READ ONLY;START TRANSACTION READ ONLY;'+sql+';ROLLBACK;',capture_output=True,text=True,encoding='utf8',env={**os.environ,'MYSQL_PWD':e['DB_PASSWORD']},timeout=80)
 if r.returncode:raise RuntimeError('read_only_query_failed')
 return [json.loads(z) for z in r.stdout.splitlines()]
def cols(keys):return ','.join("'"+k+"',"+k for k in keys)
def clean(v):
 v=re.sub(r'[^。；\n]{0,60}(?:签名|签字|参加人员|查房人员|操作人员|床号|住院号|身份证号|联系方式|家庭住址|患者姓名|患者家属姓名)[：:].*?(?=[。；\n]|$)','〔标识略〕',v)
 v=re.sub(r'[（(][^（）()\n]{0,150}(?:医生|医师|护士|查房|会诊)[^（）()\n]{0,150}[）)]','（人员略）',v)
 v=re.sub(r'[\u4e00-\u9fff]{2,4}(?:主任医师|主治医师|医师|责任护士|护士)(?=[、。，；）\s])','医护人员',v)
 v=re.sub(r'(?:医师|护士|医生|主任)[：:]\s*[\u4e00-\u9fff]{2,4}','医护人员',v);v=re.sub(r'\d+\s*床','该床',v)
 return redact(v)
def prepare(item):
 tag,i,g=item;r=rows[i];day=r['d'];cut=r['t'].split('.')[0];clock=cut[11:16];lit="CONVERT(UNHEX('"+str(r['pid']).encode().hex()+"') USING utf8mb4)";c=o/tag
 src=c/'source.json'
 if not src.exists() or read(src)['row']['id']!=r['id']:
  fields=['archive_date','rounds_record','progress_record','abnormal_labs_summary','monitoring_data','orders_execution']
  ds=query('SELECT JSON_OBJECT('+cols(fields)+') FROM chat_history02.icu_daily_archive WHERE origin=\'daily_job\' AND patient_id='+lit+" AND archive_date BETWEEN DATE_SUB('"+day+"',INTERVAL 2 DAY) AND '"+day+"' ORDER BY archive_date")
  ss=query('SELECT JSON_OBJECT('+cols(['summary_through_date','transfer_before_or_reason','post_transfer_condition'])+') FROM chat_history02.icu_disease_summary WHERE patient_id='+lit)
  save(src,dict(row=r,ds=ds,ss=ss))
 x=read(src);ds=x['ds'];ss=x['ss'][0];assert [a['archive_date'] for a in ds]==[(datetime.date.fromisoformat(day)-datetime.timedelta(days=n)).isoformat() for n in (2,1,0)]
 parts=[];kept=[];dropped=[]
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
 save(c/'freeze.json',dict(question=q,cutoff=cut,patient=p,prefix=prefix,patient_question_tokens=count(p+q),kept=kept,dropped=dropped,source_sha=sha(src),group=g))
 return dict(tag=tag,index=i,group=g,question=q,cutoff=cut,tokens=count(p+q),sha=sha(c/'freeze.json'),current_fields=sum(k.startswith(day) for k in kept))
items=[('F%02d'%n,i,g) for n,(g,i) in enumerate(((g,i) for g,ids in groups.items() for i in ids),1)]
old={str(read(d/(t+'.json'))['row']['pid']) for t in 'C8 C11 C35 C17 C27 C13 C31 C47 C12 C30 C32 C45 C46 C38 C49 C9 C48 T01 T09 T10'.split()};pids={str(rows[i]['pid']) for _,i,_ in items};assert len(pids)==30 and not pids&old
with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:manifest=list(ex.map(prepare,items))
save(o/'manifest.json',manifest)
for x in manifest:print(x['tag'],x['cutoff'],x['tokens'],x['current_fields'],x['question'][:50])
