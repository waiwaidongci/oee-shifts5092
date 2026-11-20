import json,random
from src.config.database import Base,engine,Session
from src.config.settings import CONFIG
from src.models.identity import User
from src.models.source import Source,Policy,Period
from src.models import run
from src.utils.security import password_hash
from src.services.validation import validate_source

def demo_rows():
 rng=random.Random(42);rows=[]
 for i in range(240):
  total=rng.randint(600,1050);rows.append({'period':'2026-11-'+str(1+i%20).zfill(2),'department':['试制机A','试制机B','试制机C'][i%3],'start':480,'end':1020,'ideal_seconds':25,'total':total,'good':total-rng.randint(10,60),'downtime':[[540,570],[560,590],[950,970]]})
 return rows

def seed_schedule(db):
 import hashlib,time
 from datetime import datetime
 from zoneinfo import ZoneInfo
 from src.models.run import Run
 from src.models.schedule import Mold,ShiftWindow,WorkOrder
 from src.services.calculation import calculate
 tz=ZoneInfo('Asia/Shanghai')
 def ts(day,h): return datetime(2026,11,day,h,tzinfo=tz).timestamp()
 if not db.query(Run).filter_by(name='十一月核算（演示）').first():
  sources=[x.data for x in db.query(Source).order_by(Source.id).all()]
  policy=db.query(Policy).filter_by(version=CONFIG['policy']['version']).first()
  snapshot={'policy':policy.data,'sources':sources,'period':'全部'}
  checksum=hashlib.sha256(json.dumps(snapshot,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
  db.add(Run(name='十一月核算（演示）',status='completed',snapshot=snapshot,checksum=checksum,result=calculate(sources,policy.data),created=time.time(),approved=True,review='演示复核：口径与设备节拍已核对'))
 for name in ('模具甲','模具乙','模具丙'):
  if not db.query(Mold).filter_by(name=name).first():db.add(Mold(name=name))
 for machine in ('试制机A','试制机B','试制机C'):
  for day in (21,22,23):
   for h0,h1 in ((8,14),(15,21)):
    s,e=ts(day,h0),ts(day,h1)
    if not db.query(ShiftWindow).filter_by(machine=machine,start=s,end=e).first():db.add(ShiftWindow(machine=machine,start=s,end=e))
 orders=[('WO-101',300,'模具甲',1800,ts(21,18),('试制机A','试制机B')),('WO-102',240,'模具甲',1800,ts(22,12),('试制机A',)),('WO-103',180,'模具乙',2400,ts(21,21),('试制机A','试制机C')),('WO-104',120,'模具乙',2400,ts(22,18),('试制机B','试制机C')),('WO-105',360,'模具丙',1500,ts(23,12),('试制机B',)),('WO-106',90,'模具甲',1800,ts(22,21),('试制机C',)),('WO-107',500,'模具乙',2400,ts(21,14),('试制机A',)),('WO-108',200,'模具丙',1500,ts(23,21),('试制机A','试制机B','试制机C')),('WO-109',800,'模具甲',1800,ts(21,12),('试制机A',))]
 for code,qty,mold,ch,due,machines in orders:
  if not db.query(WorkOrder).filter_by(code=code).first():db.add(WorkOrder(code=code,qty=qty,mold=mold,changeover_sec=ch,due=due,machines=list(machines),created=time.time()))

def seed():
 Base.metadata.create_all(engine)
 with Session() as db:
  for role in ('admin','analyst','viewer'):
   if not db.query(User).filter_by(email=role+'@demo.local').first():db.add(User(email=role+'@demo.local',role=role,password=password_hash('Demo2026!')))
  rows=demo_rows()
  for name in sorted(set(r['period'] for r in rows)):
   if not db.query(Period).filter_by(name=name).first():db.add(Period(name=name,description='合成演示业务期间，seed=42'))
  for i,data in enumerate(rows):
   validate_source(data);key='demo-'+str(i+1)
   if not db.query(Source).filter_by(natural_key=key).first():db.add(Source(natural_key=key,data=data))
  if not db.query(Policy).filter_by(version=CONFIG['policy']['version']).first():db.add(Policy(version=CONFIG['policy']['version'],data=CONFIG['policy']))
  seed_schedule(db)
  db.commit();print(json.dumps({'users':db.query(User).count(),'sources':db.query(Source).count(),'policies':db.query(Policy).count(),'periods':db.query(Period).count()},ensure_ascii=False))
if __name__=='__main__':seed()
