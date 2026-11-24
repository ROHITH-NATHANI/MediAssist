import os
from datetime import datetime, timezone
from sqlalchemy import create_engine, String, Integer, Text, ForeignKey, Boolean, LargeBinary, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

def now(): return datetime.now(timezone.utc).isoformat(timespec='seconds')
URL=os.getenv('DATABASE_URL','sqlite:///./mediassist.db')
engine=create_engine(URL,connect_args={'check_same_thread':False} if URL.startswith('sqlite') else {},pool_pre_ping=True)
Session=sessionmaker(bind=engine,expire_on_commit=False)
class Base(DeclarativeBase): pass
class User(Base):
    __tablename__='users'
    id:Mapped[int]=mapped_column(primary_key=True)
    email:Mapped[str]=mapped_column(String(254),unique=True,index=True)
    name:Mapped[str]=mapped_column(String(100))
    password:Mapped[str]=mapped_column(String(300))
    role:Mapped[str]=mapped_column(String(20),default='patient')
    specialty:Mapped[str]=mapped_column(String(100),default='')
    verified:Mapped[bool]=mapped_column(Boolean,default=False)
class Slot(Base):
    __tablename__='slots'
    __table_args__=(UniqueConstraint('doctor_id','starts'),)
    id:Mapped[int]=mapped_column(primary_key=True)
    doctor_id:Mapped[int]=mapped_column(ForeignKey('users.id'))
    starts:Mapped[str]=mapped_column(String(40))
    booked:Mapped[bool]=mapped_column(Boolean,default=False)
class Appointment(Base):
    __tablename__='appointments'
    id:Mapped[int]=mapped_column(primary_key=True)
    patient_id:Mapped[int]=mapped_column(ForeignKey('users.id'),index=True)
    slot_id:Mapped[int]=mapped_column(ForeignKey('slots.id'))
    status:Mapped[str]=mapped_column(String(20),default='booked')
    notes:Mapped[str]=mapped_column(Text,default='')
class Report(Base):
    __tablename__='reports'
    id:Mapped[int]=mapped_column(primary_key=True)
    patient_id:Mapped[int]=mapped_column(ForeignKey('users.id'),index=True)
    name:Mapped[str]=mapped_column(String(200))
    text:Mapped[str]=mapped_column(Text)
    content:Mapped[bytes]=mapped_column(LargeBinary)
    created:Mapped[str]=mapped_column(String(40),default=now)
class Medication(Base):
    __tablename__='medications'
    id:Mapped[int]=mapped_column(primary_key=True)
    patient_id:Mapped[int]=mapped_column(ForeignKey('users.id'),index=True)
    name:Mapped[str]=mapped_column(String(120))
    instructions:Mapped[str]=mapped_column(String(500))
    time:Mapped[str]=mapped_column(String(5))
    timezone:Mapped[str]=mapped_column(String(80),default='Asia/Kolkata')
    active:Mapped[bool]=mapped_column(Boolean,default=True)
class Adherence(Base):
    __tablename__='adherence'
    __table_args__=(UniqueConstraint('medication_id','day'),)
    id:Mapped[int]=mapped_column(primary_key=True)
    medication_id:Mapped[int]=mapped_column(ForeignKey('medications.id'))
    day:Mapped[str]=mapped_column(String(10))
class Audit(Base):
    __tablename__='audit'
    id:Mapped[int]=mapped_column(primary_key=True)
    actor:Mapped[int]=mapped_column(Integer)
    action:Mapped[str]=mapped_column(String(80))
    created:Mapped[str]=mapped_column(String(40),default=now)
class Knowledge(Base):
    __tablename__='knowledge'
    id:Mapped[int]=mapped_column(primary_key=True)
    title:Mapped[str]=mapped_column(String(150))
    keywords:Mapped[str]=mapped_column(Text)
    body:Mapped[str]=mapped_column(Text)
    source:Mapped[str]=mapped_column(String(500))
