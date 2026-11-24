"""Six cooperating roles. Offline mode is deterministic; online mode adds CrewAI
reasoning over public, fixed vocabulary only. No patient content is sent to Groq."""
import os,re,json,time
from sqlalchemy import select, text
from .db import Knowledge,Slot,User,Report,Medication,now
ROLES={'supervisor':'Workflow supervisor','health':'Health information specialist','report':'Medical report explanation specialist','appointment':'Appointment coordinator','medication':'Medication schedule coordinator','safety':'Safety reviewer'}
URGENT=re.compile(r'\b(chest pain|can.t breathe|cannot breathe|difficulty breathing|shortness of breath|suicid\w*|stroke|unconscious|severe bleeding|overdose)\b',re.I)
PATTERNS={'report':r'\b(report|lab|blood test|cbc|pdf|result)s?\b','appointment':r'\b(appointment|book|doctor|consultation|slot)s?\b','medication':r'\b(medicine|medication|reminder|prescription|dose|pill)s?\b','health':r'\b(health|explain|what|symptom|blood|pressure|diabetes|information|understand)\b'}
def route(query,report_id=None):
    plan=[k for k,p in PATTERNS.items() if re.search(p,query,re.I)]
    if report_id and 'report' not in plan: plan.insert(0,'report')
    return plan or ['health']
def public_reason(role,context):
    if os.getenv('AGENT_MODE','crewai')!='crewai' or not os.getenv('GROQ_API_KEY','').strip(): return None
    api_key = os.environ['GROQ_API_KEY'].strip()
    model_str = os.getenv('GROQ_MODEL','groq/qwen/qwen3.8-27b')
    try:
        from crewai import Agent,Task,Crew,LLM,Process
        llm=LLM(model=model_str,api_key=api_key,temperature=0,timeout=20)
        agent=Agent(role=ROLES[role],goal='Describe the administrative workflow and its limits.',backstory='A healthcare software workflow specialist, not a clinician.',llm=llm,allow_delegation=False,verbose=False,max_iter=2)
        task=Task(description='Using only this public workflow metadata: '+json.dumps(context)+'. '+('Return a JSON array of the requested role names in an appropriate execution order, without adding or removing any.' if role=='supervisor' else 'Return the single word READY if this administrative step can proceed, or REVIEW if it requires human review. No diagnosis or patient facts.'),expected_output='JSON array of role names' if role=='supervisor' else 'READY or REVIEW',agent=agent)
        result=Crew(agents=[agent],tasks=[task],process=Process.sequential,verbose=False,memory=False).kickoff()
        return str(result.raw)[:300]
    except Exception: pass
    try:
        from groq import Groq
        client = Groq(api_key=api_key)
        raw_model = model_str.removeprefix('groq/')
        models_to_try = [raw_model] if raw_model in ('qwen/qwen3.8-27b', 'openai/gpt-oss-20b') else [raw_model, 'qwen/qwen3.8-27b', 'openai/gpt-oss-20b']
        prompt = ('Using only this public workflow metadata: '+json.dumps(context)+'. Return a JSON array of the requested role names in an appropriate execution order, without adding or removing any. Reply ONLY with the JSON array, no other text or explanation.' if role=='supervisor' else 'Using only this public workflow metadata: '+json.dumps(context)+'. Return the single word READY if this administrative step can proceed, or REVIEW if it requires human review. No diagnosis or patient facts. Reply with ONLY READY or REVIEW.')
        for m in models_to_try:
            try:
                res = client.chat.completions.create(
                    model=m,
                    messages=[
                        {'role':'system','content':f'You are {ROLES[role]}, an administrative healthcare software specialist, not a clinician.'},
                        {'role':'user','content':prompt}
                    ],
                    temperature=0,
                    max_tokens=200,
                    timeout=20
                )
                text = (res.choices[0].message.content or '').strip()
                if text: return text[:300]
            except Exception:
                continue
    except Exception: pass
    return None

def retrieve(s,query):
    words=set(re.findall(r'[a-z]{3,}',query.lower()))-{'the','and','for','with','what','please','help','about','explain','understand'}
    if s.bind.dialect.name=='postgresql' and words:
        q=' | '.join(sorted(words)[:30]); ids=s.execute(text("SELECT id FROM knowledge WHERE to_tsvector('english',title || ' ' || keywords || ' ' || body) @@ to_tsquery('english', :q) ORDER BY ts_rank(to_tsvector('english',title || ' ' || keywords || ' ' || body),to_tsquery('english', :q)) DESC LIMIT 3"),{'q':q}).scalars().all()
        return [s.get(Knowledge,i) for i in ids]
    ranked=[(len(words & set(re.findall(r'[a-z]{3,}',(k.title+' '+k.keywords).lower()))),k) for k in s.scalars(select(Knowledge))]
    return [k for score,k in sorted(ranked,key=lambda x:-x[0])[:3] if score]

def run(s,u,query,report_id=None):
    start=time.perf_counter(); trace=[]; blocks=[]; sources=[]; slots=[]
    def step(role,detail,requested=None):
        t=time.perf_counter(); online=public_reason(role,{'role':role,'completed_roles':[x['agent'] for x in trace],'requested_roles':requested or []})
        decision=None
        if role=='supervisor' and online:
            try:
                candidate=json.loads(online.strip().removeprefix('```json').removesuffix('```').strip())
                if isinstance(candidate,list) and all(isinstance(x,str) for x in candidate) and sorted(candidate)==sorted(requested or []): decision=candidate
            except (ValueError,TypeError): pass
        elif online and online.strip().upper() in ('READY','REVIEW'):
            decision=online.strip().upper()
            if decision=='REVIEW': blocks.append('An administrative agent flagged this workflow for human review. No actions were executed automatically.')
        trace.append({'agent':role,'detail':detail,'mode':'crewai' if decision is not None else 'offline','latency_ms':round((time.perf_counter()-t)*1000,1)})
        return decision
    if URGENT.search(query):
        trace=[{'agent':'supervisor','detail':'Urgent keyword detected','mode':'offline','latency_ms':0},{'agent':'safety','detail':'Routine workflow stopped','mode':'offline','latency_ms':0}]
        return {'answer':'If this is happening now, seek urgent medical help or contact local emergency services. Do not wait for a chatbot or routine appointment. This system cannot assess emergencies.','trace':trace,'sources':[],'slots':[],'latency_ms':0,'urgent':True}
    plan=route(query,report_id);plan=step('supervisor','Selected '+', '.join(plan),plan) or plan
    for role in plan:
        if role=='report':
            r=s.get(Report,report_id) if report_id else None
            if r and r.patient_id==u.id:
                lines=[l.strip() for l in r.text.splitlines() if l.strip()][:12]
                blocks.append('Report excerpt (verbatim, not a diagnosis):\n'+'\n'.join(lines)+'\nCompare values with the report’s own reference ranges and discuss them with your clinician.')
            else: blocks.append('Select one of your uploaded reports to view an explanation. Scanned PDFs require a text-based copy.')
            step(role,'Extracted authorized report text locally' if r and r.patient_id==u.id else 'Report selection required')
        elif role=='health':
            ks=retrieve(s,query)
            if ks:
                for k in ks:
                    blocks.append(k.title+': '+k.body);sources.append({'title':k.title,'url':k.source})
            else: blocks.append('No matching curated information found. Ask a clinician or consult MedlinePlus for general information.')
            step(role,f'Retrieved {len(ks)} curated references')
        elif role=='appointment':
            rows=s.execute(select(Slot,User).join(User,User.id==Slot.doctor_id).where(Slot.booked==False,Slot.starts>now(),User.verified==True).order_by(Slot.starts).limit(5)).all()
            slots=[{'id':a.id,'doctor':d.name,'specialty':d.specialty,'starts':a.starts} for a,d in rows]
            blocks.append('Available appointment options are shown below. Choose a slot and confirm; nothing has been booked.' if slots else 'No available demo slots found.')
            step(role,'Checked live database availability')
        elif role=='medication':
            meds=s.scalars(select(Medication).where(Medication.patient_id==u.id,Medication.active==True)).all()
            blocks.append('Existing reminders: '+', '.join(f'{m.name} at {m.time} ({m.timezone})' for m in meds) if meds else 'No reminders yet. Add an existing prescribed schedule in Medications. Do not change dosage based on this assistant.')
            step(role,'Read existing schedules; no prescription changes')
    blocks.append('Educational and administrative assistance only. A qualified clinician must interpret medical findings and advise on treatment.')
    step('safety','Applied deterministic safety rules; no autonomous write actions')
    return {'answer':'\n\n'.join(blocks),'trace':trace,'sources':sources,'slots':slots,'latency_ms':round((time.perf_counter()-start)*1000,1),'urgent':False}
