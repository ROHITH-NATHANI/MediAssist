import os,json
from pathlib import Path
from datetime import datetime,timedelta,timezone
from sqlalchemy import select
from .db import User,Slot,Knowledge
from .security import hash_password
DATA=Path(os.getenv('DATA_DIR',Path(__file__).resolve().parents[2]/'data'))
def seed(s):
    if not s.scalar(select(Knowledge.id).limit(1)):
        for entry in json.loads((DATA/'knowledge.json').read_text()): s.add(Knowledge(**entry))
    if os.getenv('DEMO_SEED','true').lower()=='true' and not s.scalar(select(User.id).limit(1)):
        pw=hash_password('DemoPass123!')
        s.add_all([User(email='patient@demo.test',name='Alex Demo',role='patient',password=pw),User(email='admin@demo.test',name='Demo Administrator',role='admin',password=pw)])
        for i,(name,specialty) in enumerate([('Dr. Maya Demo','General Medicine'),('Dr. Arun Demo','Cardiology'),('Dr. Sara Demo','Dermatology')],1):
            d=User(email=f'doctor{i}@demo.test',name=name,role='doctor',specialty=specialty,verified=True,password=pw);s.add(d);s.flush()
            for day in range(1,8):
                for hour in (5,6,7):
                    start=(datetime.now(timezone.utc)+timedelta(days=day)).replace(hour=hour,minute=0,second=0,microsecond=0)
                    s.add(Slot(doctor_id=d.id,starts=start.isoformat()))
    s.commit()
