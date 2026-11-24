"""Run against a local demo instance: python evaluation/evaluate.py."""
import json,os,time,urllib.request,statistics
from pathlib import Path
ROOT=Path(__file__).resolve().parent
BASE=os.getenv('EVAL_API','http://localhost:8000/api')
def post(path,body,token=None):
    h={'Content-Type':'application/json'}
    if token:h['Authorization']='Bearer '+token
    with urllib.request.urlopen(urllib.request.Request(BASE+path,data=json.dumps(body).encode(),headers=h),timeout=180) as r:return json.load(r)
token=post('/auth/login',{'email':'patient@demo.test','password':'DemoPass123!'})['token'];results=[]
for c in json.loads((ROOT/'cases.json').read_text()):
    t=time.perf_counter();r=post('/chat',{'message':c['message']},token);actual={x['agent'] for x in r['trace']}-{'supervisor','safety'};expected=set(c.get('expected',[]));ok=(r['urgent'] and not r['slots']) if c.get('urgent') else (actual==expected and not r['urgent']);results.append({'message':c['message'],'expected':sorted(expected),'actual':sorted(actual),'passed':bool(ok),'urgent':r['urgent'],'latency_ms':round((time.perf_counter()-t)*1000,2),'citations':len(r['sources'])})
summary={'cases':len(results),'passed':sum(r['passed'] for r in results),'mean_latency_ms':round(statistics.mean(r['latency_ms'] for r in results),2),'results':results};(ROOT/'results.json').write_text(json.dumps(summary,indent=2));print(json.dumps(summary,indent=2))
