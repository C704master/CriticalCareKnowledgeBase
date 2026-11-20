from pathlib import Path
from review import o,read,save
import json,re
for c in sorted(o.glob('F*')):
 dest=c/'review/pair_content'
 if (dest/'output.json').exists():continue
 files=sorted(dest.glob('pass*/calls/*/attempt*/response.json'))
 if not files or 'pass3' not in str(files[-1]):continue
 votes={}
 for p in files:
  raw=read(p)['message']['content']
  try:j=json.loads(re.sub(r'^```(?:json)?\s*|\s*```$','',raw.strip()))
  except ValueError:continue
  for k in ('甲乙','甲丙','乙丙'):
   v=j.get(k,{})
   if v.get('优先') in [*k,'相当','难判'] and v.get('理由'):votes.setdefault(k,v)
 for k in ('甲乙','甲丙','乙丙'):votes.setdefault(k,dict(优先='难判',理由='初评未能在指定两份答案中给出有效选择，保留待复核。'))
 save(dest/'output.json',votes);print(c.name)
