"""预排 API 端到端：冻结版本、确认落账、幂等重试、源数据变化重算、并发不重复占用、拒绝出方案、未排原因。"""
import time
from datetime import datetime,timedelta,timezone
from itertools import combinations
from concurrent.futures import ThreadPoolExecutor
import pytest
from conftest import login,make_run
from src.services import scheduling

TZ8=timezone(timedelta(hours=8))
def ts(day,h): return datetime(2026,11,day,h,tzinfo=TZ8).timestamp()

def setup_basic(client,h,molds=('K1','K2'),machines=('机A','机B')):
 for m in molds:
  assert client.post('/molds',json={'name':m},headers=h).status_code==200
 for mc in machines:
  for day in (21,22):
   assert client.post('/windows',json={'machine':mc,'start':ts(day,8),'end':ts(day,14)},headers=h).status_code==200
   assert client.post('/windows',json={'machine':mc,'start':ts(day,15),'end':ts(day,21)},headers=h).status_code==200

def post_order(client,h,code,qty,due,mold,ch,machines):
 r=client.post('/orders',json={'code':code,'qty':qty,'due':due,'mold':mold,'changeover_sec':ch,'machines':machines},headers=h)
 assert r.status_code==200,r.text
 return r.json()

def test_cycles_from_approved_run(client):
 h=login(client);run_id=make_run(client)
 r=client.get(f'/cycles/{run_id}',headers=h)
 assert r.status_code==200 and r.json()['cycles']=={'机A':30.0,'机B':60.0}

def test_preschedule_freezes_version_and_confirm_idempotent(client):
 h=login(client);run_id=make_run(client);setup_basic(client,h)
 post_order(client,h,'W1',100,ts(21,18),'K1',300,['机A'])
 post_order(client,h,'W2',100,ts(21,20),'K1',300,['机A'])
 post_order(client,h,'W3',60,ts(22,12),'K2',600,['机A','机B'])
 r=client.post('/preschedule',json={'run_id':run_id},headers=h)
 assert r.status_code==200,r.text
 plan=r.json()
 assert plan['status']=='proposed' and len(plan['source_version'])==64
 assert plan['snapshot']['run']['id']==run_id,'冻结输入应引用已复核报告'
 assert {o['code'] for o in plan['snapshot']['orders']}=={'W1','W2','W3'}
 obj=plan['result']['objective']
 assert obj['pieces']==260 and obj['changeover_sec']==900,'同模连做只计一次换模'
 items=plan['result']['items']
 assert len(items)==3
 w1w2=sorted([i for i in items if i['order'] in ('W1','W2')],key=lambda x:x['start'])
 assert w1w2[1]['changeover_sec']==0 and w1w2[1]['start']==w1w2[0]['end'],'W2应紧贴W1免换模'
 assert plan['result']['unscheduled']==[]
 # 确认落账
 r=client.post(f"/plans/{plan['id']}/confirm",json={'idempotency_key':'key-0001'},headers=h)
 assert r.status_code==200,r.text
 res=r.json()
 assert res['recomputed']==False and res['plan_id']==plan['id']
 assert len(client.get('/bookings',headers=h).json())==3
 # 同次重试（同幂等键）：不重复落账
 r=client.post(f"/plans/{plan['id']}/confirm",json={'idempotency_key':'key-0001'},headers=h)
 assert r.status_code==200 and r.json()['plan_id']==plan['id']
 assert len(client.get('/bookings',headers=h).json())==3
 # 同方案不同键：同样幂等
 r=client.post(f"/plans/{plan['id']}/confirm",json={'idempotency_key':'key-0002'},headers=h)
 assert r.status_code==200 and r.json()['plan_id']==plan['id']
 assert len(client.get('/bookings',headers=h).json())==3
 assert client.get(f"/plans/{plan['id']}",headers=h).json()['status']=='confirmed'
 # 已确认工单不再进入新预排
 r=client.post('/preschedule',json={'run_id':run_id},headers=h)
 assert r.status_code==409,'全部落账后没有待排工单'

def test_confirm_recomputes_when_source_changed(client):
 h=login(client);run_id=make_run(client);setup_basic(client,h)
 post_order(client,h,'W1',100,ts(21,18),'K1',300,['机A'])
 plan=client.post('/preschedule',json={'run_id':run_id},headers=h).json()
 # 源数据变化：新增班表窗口 → 版本变化
 assert client.post('/windows',json={'machine':'机A','start':ts(23,8),'end':ts(23,14)},headers=h).status_code==200
 r=client.post(f"/plans/{plan['id']}/confirm",json={'idempotency_key':'key-recompute'},headers=h)
 assert r.status_code==200,r.text
 res=r.json()
 assert res['recomputed']==True and res['source_version']!=plan['source_version']
 assert client.get(f"/plans/{plan['id']}",headers=h).json()['status']=='superseded'
 assert client.get(f"/plans/{res['plan_id']}",headers=h).json()['status']=='confirmed'
 assert len(client.get('/bookings',headers=h).json())==1

def test_concurrent_same_key_retry(client):
 h=login(client);run_id=make_run(client);setup_basic(client,h)
 post_order(client,h,'W1',100,ts(21,18),'K1',300,['机A'])
 plan=client.post('/preschedule',json={'run_id':run_id},headers=h).json()
 def confirm(_): return client.post(f"/plans/{plan['id']}/confirm",json={'idempotency_key':'same-key-123'},headers=h)
 with ThreadPoolExecutor(2) as ex: rs=list(ex.map(confirm,range(2)))
 assert all(r.status_code==200 for r in rs),(rs[0].text,rs[1].text)
 assert rs[0].json()['plan_id']==rs[1].json()['plan_id']
 assert len(client.get('/bookings',headers=h).json())==1,'同次重试不重复落账'

def test_concurrent_confirms_no_double_occupancy(client):
 h=login(client);run_id=make_run(client);setup_basic(client,h)
 for i in range(1,5): post_order(client,h,f'W{i}',50,ts(22,21),'K1',60,['机A'])
 p1=client.post('/preschedule',json={'run_id':run_id},headers=h).json()
 p2=client.post('/preschedule',json={'run_id':run_id},headers=h).json()
 assert p1['source_version']==p2['source_version'],'同一版输入应冻结为同一版本'
 def confirm(pid,key): return client.post(f'/plans/{pid}/confirm',json={'idempotency_key':key},headers=h)
 with ThreadPoolExecutor(2) as ex:
  f1=ex.submit(confirm,p1['id'],'race-key-1');f2=ex.submit(confirm,p2['id'],'race-key-2')
  r1,r2=f1.result(),f2.result()
 assert sorted([r1.status_code,r2.status_code])==[200,409],(r1.text,r2.text)
 bs=client.get('/bookings',headers=h).json()
 assert len(bs)==4,'只应落账一次，不得重复占用'
 for a,b in combinations(bs,2):
  assert a['end']<=b['setup_start'] or b['end']<=a['setup_start'],'设备/模具不得重叠占用'

def test_refusal_when_solver_cannot_prove_optimal(client,monkeypatch):
 h=login(client);run_id=make_run(client);setup_basic(client,h)
 post_order(client,h,'W1',100,ts(21,18),'K1',300,['机A'])
 def fake(*a,**k): raise scheduling.solver.Refused('测试强制未证实')
 monkeypatch.setattr(scheduling.solver,'solve',fake)
 r=client.post('/preschedule',json={'run_id':run_id},headers=h)
 assert r.status_code==422 and '拒绝出方案' in r.json()['detail']
 assert client.get('/plans',headers=h).json()==[],'拒绝出方案不得落库'

def test_unscheduled_reasons(client):
 h=login(client);run_id=make_run(client);setup_basic(client,h)
 post_order(client,h,'BIG',10000,ts(22,21),'K1',300,['机A'])  # 83小时，任何窗口都装不下
 post_order(client,h,'W1',100,ts(21,18),'K1',300,['机A'])
 r=client.post('/preschedule',json={'run_id':run_id},headers=h)
 assert r.status_code==200
 uns=r.json()['result']['unscheduled']
 assert len(uns)==1 and uns[0]['order']=='BIG'
 assert '无法按期插入' in uns[0]['reason'] and '机A' in uns[0]['reason'] and '空档' in uns[0]['reason']

def test_validation_and_permissions(client):
 h=login(client);run_id=make_run(client);setup_basic(client,h)
 # 班表窗口重叠
 r=client.post('/windows',json={'machine':'机A','start':ts(21,10),'end':ts(21,12)},headers=h)
 assert r.status_code==409
 # 未登记模具
 r=client.post('/orders',json={'code':'X1','qty':1,'due':ts(21,18),'mold':'不存在','changeover_sec':0,'machines':['机A']},headers=h)
 assert r.status_code==422
 # 报告中无节拍的设备
 client.post('/orders',json={'code':'X2','qty':1,'due':ts(21,18),'mold':'K1','changeover_sec':0,'machines':['机A','机外']},headers=h)
 r=client.post('/preschedule',json={'run_id':run_id},headers=h)
 assert r.status_code==422 and '无已复核节拍' in r.json()['detail']
 # 阅读者只读
 hv=login(client,'viewer@demo.local')
 assert client.post('/molds',json={'name':'K9'},headers=hv).status_code==403
 assert client.get('/plans',headers=hv).status_code==200
 # 幂等键过短
 post_order(client,h,'W1',100,ts(21,18),'K1',300,['机A'])
 x2=[o for o in client.get('/orders',headers=h).json() if o['code']=='X2'][0]
 assert client.delete(f"/orders/{x2['id']}",headers=h).status_code==200  # 删除X2，排除干扰
 plan=client.post('/preschedule',json={'run_id':run_id},headers=h).json()
 assert client.post(f"/plans/{plan['id']}/confirm",json={'idempotency_key':'短'},headers=h).status_code==422
 # 分析师不能确认（仅负责人）
 ha=login(client,'analyst@demo.local')
 assert client.post(f"/plans/{plan['id']}/confirm",json={'idempotency_key':'key-analyst-1'},headers=ha).status_code==403

def test_preschedule_requires_approved_run(client):
 h=login(client)
 from src.config.database import Session
 from src.models.run import Run
 with Session() as db:
  db.add(Run(name='未复核',status='completed',snapshot={'sources':[],'policy':{}},checksum='x',created=time.time(),approved=False))
  db.commit();rid=db.query(Run).filter_by(name='未复核').first().id
 r=client.post('/preschedule',json={'run_id':rid},headers=h)
 assert r.status_code==409
