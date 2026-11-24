import os,re,time
from collections import defaultdict,deque
from contextlib import asynccontextmanager
from datetime import datetime,timezone
from zoneinfo import ZoneInfo,ZoneInfoNotFoundError
import fitz
from fastapi import FastAPI,Depends,HTTPException,UploadFile,File,Request
from fastapi.responses import Response,JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel,Field
from sqlalchemy import select,update,func
from sqlalchemy.exc import IntegrityError
from .db import *
from .security import db,current,require,hash_password,verify_password,token
from .seed import seed
from .agents import run
@asynccontextmanager
async def lifespan(app):
    Base.metadata.create_all(engine)
    with Session() as s: seed(s)
    yield
app=FastAPI(title='MediAssist API',version='1.0.0',lifespan=lifespan)
app.add_middleware(CORSMiddleware,allow_origins=os.getenv('CORS_ORIGINS','http://localhost:5173').split(','),allow_methods=['GET','POST','PATCH','DELETE'],allow_headers=['Authorization','Content-Type'])
limits=defaultdict(deque)
@app.middleware('http')
async def guard(request:Request,call_next):
    if request.url.path in ('/api/auth/login','/api/auth/register','/api/chat'):
        key=(request.client.host if request.client else 'unknown',request.url.path);q=limits[key];t=time.monotonic()
        while q and q[0]<t-60:q.popleft()
        if len(q)>=20:return JSONResponse({'detail':'Rate limit exceeded'},429)
        q.append(t)
    response=await call_next(request);response.headers['X-Content-Type-Options']='nosniff';response.headers['Referrer-Policy']='no-referrer';response.headers['X-Frame-Options']='DENY';response.headers['Cache-Control']='no-store';return response
class Login(BaseModel):
    email:str=Field(min_length=3,max_length=254)
    password:str=Field(min_length=1,max_length=128)
class Register(Login):
    name:str=Field(min_length=2,max_length=100)
    password:str=Field(min_length=10,max_length=128)
class Book(BaseModel): slot_id:int
class SlotInput(BaseModel): starts:datetime
class Complete(BaseModel): notes:str=Field(min_length=1,max_length=4000)
class MedInput(BaseModel):
    name:str=Field(min_length=1,max_length=120)
    instructions:str=Field(min_length=1,max_length=500)
    time:str=Field(pattern=r'^([01]\d|2[0-3]):[0-5]\d$')
    timezone:str=Field(default='Asia/Kolkata',max_length=80)
class Chat(BaseModel):
    message:str=Field(min_length=1,max_length=2000)
    report_id:int|None=None
class Verify(BaseModel): verified:bool
class DoctorInput(Register): specialty:str=Field(min_length=2,max_length=100)
def profile(u):return {'id':u.id,'name':u.name,'email':u.email,'role':u.role,'specialty':u.specialty,'verified':u.verified}
def log(s,u,action):s.add(Audit(actor=u.id,action=action))
def commit(s):
    try:s.commit()
    except IntegrityError:s.rollback();raise HTTPException(409,'Conflicting record or duplicate entry')
def owned(s,model,id,u):
    x=s.get(model,id)
    if not x or x.patient_id!=u.id:raise HTTPException(404,'Record not found')
    return x
def appointment_view(s,a):
    slot=s.get(Slot,a.slot_id);d=s.get(User,slot.doctor_id);p=s.get(User,a.patient_id)
    return {'id':a.id,'slot_id':slot.id,'starts':slot.starts,'doctor':d.name,'specialty':d.specialty,'patient':p.name,'status':a.status,'notes':a.notes}
@app.get('/api/health')
def health():return {'status':'ok','agent_mode':os.getenv('AGENT_MODE','crewai')}
@app.post('/api/auth/register',status_code=201)
def register(body:Register,s=Depends(db)):
    email=body.email.strip().lower()
    if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',email):raise HTTPException(422,'Invalid email')
    u=User(email=email,name=body.name.strip(),password=hash_password(body.password),role='patient');s.add(u);commit(s);return {'token':token(u),'user':profile(u)}
@app.post('/api/auth/login')
def login(body:Login,s=Depends(db)):
    u=s.scalar(select(User).where(User.email==body.email.strip().lower()))
    if not u or not verify_password(body.password,u.password):raise HTTPException(401,'Invalid credentials')
    return {'token':token(u),'user':profile(u)}
@app.get('/api/me')
def me(u=Depends(current)):return profile(u)
@app.get('/api/doctors')
def doctors(u=Depends(current),s=Depends(db)):
    return [{'id':d.id,'name':d.name,'specialty':d.specialty} for d in s.scalars(select(User).where(User.role=='doctor',User.verified==True))]
@app.get('/api/slots')
def slots(doctor_id:int|None=None,u=Depends(current),s=Depends(db)):
    stmt=select(Slot,User).join(User,User.id==Slot.doctor_id).where(Slot.booked==False,Slot.starts>now(),User.verified==True)
    if doctor_id:stmt=stmt.where(Slot.doctor_id==doctor_id)
    return [{'id':a.id,'doctor':d.name,'specialty':d.specialty,'starts':a.starts} for a,d in s.execute(stmt.order_by(Slot.starts).limit(100))]
@app.post('/api/doctor/slots',status_code=201)
def add_slot(body:SlotInput,u=Depends(current),s=Depends(db)):
    require(u,'doctor');dt=body.starts
    if dt.tzinfo is None or dt<=datetime.now(timezone.utc):raise HTTPException(422,'Use a future timezone-aware time')
    sl=Slot(doctor_id=u.id,starts=dt.astimezone(timezone.utc).isoformat(timespec='seconds'));s.add(sl);commit(s);return {'id':sl.id}
@app.get('/api/appointments')
def appointments(u=Depends(current),s=Depends(db)):
    require(u,'patient','doctor');stmt=select(Appointment)
    if u.role=='patient':stmt=stmt.where(Appointment.patient_id==u.id)
    else:stmt=stmt.join(Slot,Slot.id==Appointment.slot_id).where(Slot.doctor_id==u.id)
    return [appointment_view(s,a) for a in s.scalars(stmt.order_by(Appointment.id.desc()))]
@app.post('/api/appointments',status_code=201)
def book(body:Book,u=Depends(current),s=Depends(db)):
    require(u,'patient');sl=s.get(Slot,body.slot_id)
    if not sl or not s.get(User,sl.doctor_id).verified:raise HTTPException(404,'Slot unavailable')
    result=s.execute(update(Slot).where(Slot.id==body.slot_id,Slot.booked==False,Slot.starts>now()).values(booked=True))
    if result.rowcount!=1:raise HTTPException(409,'Slot unavailable')
    a=Appointment(patient_id=u.id,slot_id=sl.id);s.add(a);log(s,u,'appointment.book');commit(s);return appointment_view(s,a)
@app.patch('/api/appointments/{id}/cancel')
def cancel(id:int,u=Depends(current),s=Depends(db)):
    require(u,'patient','doctor');a=s.get(Appointment,id);sl=s.get(Slot,a.slot_id) if a else None
    if not a or not (a.patient_id==u.id or (u.role=='doctor' and sl.doctor_id==u.id)):raise HTTPException(404,'Appointment not found')
    if s.execute(update(Appointment).where(Appointment.id==id,Appointment.status=='booked').values(status='cancelled')).rowcount!=1:raise HTTPException(409,'Appointment is not active')
    sl.booked=False;log(s,u,'appointment.cancel');commit(s);return {'status':'cancelled'}
@app.patch('/api/appointments/{id}/complete')
def complete(id:int,body:Complete,u=Depends(current),s=Depends(db)):
    require(u,'doctor');a=s.get(Appointment,id)
    if not a or s.get(Slot,a.slot_id).doctor_id!=u.id:raise HTTPException(404,'Appointment not found')
    if s.execute(update(Appointment).where(Appointment.id==id,Appointment.status=='booked').values(status='completed',notes=body.notes)).rowcount!=1:raise HTTPException(409,'Appointment is not active')
    log(s,u,'appointment.complete');commit(s);return {'status':'completed'}
@app.get('/api/reports')
def reports(u=Depends(current),s=Depends(db)):
    require(u,'patient');return [{'id':r.id,'name':r.name,'created':r.created,'preview':r.text[:200]} for r in s.scalars(select(Report).where(Report.patient_id==u.id).order_by(Report.id.desc()))]
@app.post('/api/reports',status_code=201)
async def upload(file:UploadFile=File(...),u=Depends(current),s=Depends(db)):
    require(u,'patient');content=await file.read(5*1024*1024+1)
    if len(content)>5*1024*1024:raise HTTPException(413,'Maximum PDF size is 5 MB')
    if not content.startswith(b'%PDF-'):raise HTTPException(415,'Only PDF documents are supported')
    try:
        with fitz.open(stream=content,filetype='pdf') as doc:
            if doc.needs_pass or len(doc)>30:raise ValueError()
            extracted='\n'.join(p.get_text() for p in doc)[:30000]
    except Exception:raise HTTPException(422,'Invalid, encrypted or oversized PDF (30 pages maximum)')
    if not extracted.strip():raise HTTPException(422,'No selectable text. OCR is not supported in this version.')
    name=re.sub(r'[^\w. -]','_',os.path.basename(file.filename or 'report.pdf'))[:180]
    r=Report(patient_id=u.id,name=name,text=extracted,content=content);s.add(r);log(s,u,'report.upload');commit(s);return {'id':r.id,'name':r.name}
@app.get('/api/reports/{id}/download')
def download(id:int,u=Depends(current),s=Depends(db)):
    require(u,'patient');r=owned(s,Report,id,u);log(s,u,'report.download');commit(s);return Response(r.content,media_type='application/pdf',headers={'Content-Disposition':'attachment; filename="report.pdf"'})
@app.delete('/api/reports/{id}')
def delete_report(id:int,u=Depends(current),s=Depends(db)):
    require(u,'patient');s.delete(owned(s,Report,id,u));log(s,u,'report.delete');commit(s);return {'ok':True}
def med_view(s,m):
    local=datetime.now(ZoneInfo(m.timezone));day=local.date().isoformat();taken=bool(s.scalar(select(Adherence.id).where(Adherence.medication_id==m.id,Adherence.day==day)))
    return {'id':m.id,'name':m.name,'instructions':m.instructions,'time':m.time,'timezone':m.timezone,'active':m.active,'taken':taken,'due':m.active and not taken and local.strftime('%H:%M')>=m.time}
@app.get('/api/medications')
def medications(u=Depends(current),s=Depends(db)):
    require(u,'patient');return [med_view(s,m) for m in s.scalars(select(Medication).where(Medication.patient_id==u.id,Medication.active==True))]
@app.post('/api/medications',status_code=201)
def add_med(body:MedInput,u=Depends(current),s=Depends(db)):
    require(u,'patient')
    try:ZoneInfo(body.timezone)
    except (ZoneInfoNotFoundError,ValueError):raise HTTPException(422,'Invalid timezone')
    m=Medication(patient_id=u.id,**body.model_dump());s.add(m);log(s,u,'medication.schedule');commit(s);return med_view(s,m)
@app.post('/api/medications/{id}/taken')
def taken(id:int,u=Depends(current),s=Depends(db)):
    require(u,'patient');m=owned(s,Medication,id,u)
    if not m.active:raise HTTPException(409,'Reminder inactive')
    day=datetime.now(ZoneInfo(m.timezone)).date().isoformat()
    if not s.scalar(select(Adherence.id).where(Adherence.medication_id==id,Adherence.day==day)):
        s.add(Adherence(medication_id=id,day=day));commit(s)
    return med_view(s,m)
@app.delete('/api/medications/{id}')
def archive(id:int,u=Depends(current),s=Depends(db)):
    require(u,'patient');m=owned(s,Medication,id,u);m.active=False;commit(s);return {'ok':True}
@app.post('/api/chat')
def chat(body:Chat,u=Depends(current),s=Depends(db)):
    require(u,'patient')
    if body.report_id:owned(s,Report,body.report_id,u)
    result=run(s,u,body.message,body.report_id);log(s,u,'agent.workflow');commit(s);return result
@app.get('/api/admin/stats')
def stats(u=Depends(current),s=Depends(db)):
    require(u,'admin');return {'patients':s.scalar(select(func.count()).select_from(User).where(User.role=='patient')),'doctors':s.scalar(select(func.count()).select_from(User).where(User.role=='doctor')),'appointments':s.scalar(select(func.count()).select_from(Appointment)),'agent_runs':s.scalar(select(func.count()).select_from(Audit).where(Audit.action=='agent.workflow')),'doctor_accounts':[profile(d) for d in s.scalars(select(User).where(User.role=='doctor'))]}
@app.post('/api/admin/doctors',status_code=201)
def create_doctor(body:DoctorInput,u=Depends(current),s=Depends(db)):
    require(u,'admin');d=User(email=body.email.lower().strip(),name=body.name,password=hash_password(body.password),specialty=body.specialty,role='doctor',verified=False);s.add(d);commit(s);return profile(d)
@app.patch('/api/admin/doctors/{id}')
def verify(id:int,body:Verify,u=Depends(current),s=Depends(db)):
    require(u,'admin');d=s.get(User,id)
    if not d or d.role!='doctor':raise HTTPException(404,'Doctor not found')
    d.verified=body.verified;log(s,u,'doctor.verify');commit(s);return profile(d)
