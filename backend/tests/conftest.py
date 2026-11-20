import os,sys,json,types,time,hashlib,tempfile
from pathlib import Path
BASE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(BASE))
os.environ['SEED_DEMO']='false'
_settings=types.ModuleType('src.config.settings')
_settings.CONFIG=json.loads((BASE/'project.json').read_text())
_settings.DATABASE_URL='sqlite:///'+str(Path(tempfile.gettempdir())/'schedule_test.db')
_settings.REDIS_URL='redis://localhost:6379/0'
_settings.SECRET='test-secret'
sys.modules['src.config.settings']=_settings
import pytest
from fastapi.testclient import TestClient
from src.config.database import Base,engine,Session
from src.main import app
from src.models.identity import User
from src.models.run import Run
from src.utils.security import password_hash

@pytest.fixture()
def client():
 Base.metadata.drop_all(engine);Base.metadata.create_all(engine)
 with Session() as db:
  for role in ('admin','analyst','viewer'):
   db.add(User(email=role+'@demo.local',role=role,password=password_hash('Demo2026!')))
  db.commit()
 with TestClient(app) as c: yield c

def login(client,email='admin@demo.local'):
 r=client.post('/auth/login',json={'email':email,'password':'Demo2026!'})
 assert r.status_code==200,r.text
 return {'Authorization':'Bearer '+r.json()['token']}

def make_run(client,sources=None,name='测试报告'):
 """直接落库一份已完成且已复核的报告，提供设备节拍。默认机A=30秒/件、机B=60秒/件。"""
 sources=sources or [
  {'period':'2026-11-19','department':'机A','start':480,'end':1020,'ideal_seconds':30,'total':1080,'good':1000,'downtime':[]},
  {'period':'2026-11-19','department':'机B','start':480,'end':1020,'ideal_seconds':60,'total':540,'good':500,'downtime':[]}]
 snapshot={'policy':{'version':'v1','definition':'d'},'sources':sources,'period':'全部'}
 checksum=hashlib.sha256(json.dumps(snapshot,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
 with Session() as db:
  run=Run(name=name,status='completed',snapshot=snapshot,checksum=checksum,result={'summary':{},'rows':[]},created=time.time(),approved=True,review='已核对')
  db.add(run);db.commit();db.refresh(run);return run.id
