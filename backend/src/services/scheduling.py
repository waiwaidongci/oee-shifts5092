"""工单预排业务编排：冻结输入快照、调用精确求解器、确认落账。

- 预排：以"已复核报告节拍 + 当前班表/模具/待排工单/已确认占用"为同一版输入，计算 SHA256 版本并冻结进方案。
- 确认：源数据版本不变则按冻结方案落账；有变化则以当前数据重算后确认新方案。
  进程内锁 + 数据库单行锁串行化确认，落账前复检占用冲突，幂等键保证同次重试不重复落账。
"""
import hashlib,json,threading,time
from fastapi import HTTPException
from src.models.run import Run
from src.models.schedule import Mold,ShiftWindow,WorkOrder,Plan,Confirmation,Booking,Meta
from src.services.calculation import downtime_minutes
from src.services.audit import log
from src.services import solver

SOLVE_LIMIT_SEC=30.0
MAX_ORDERS=60;MAX_MACHINES=12;MAX_WINDOWS_PER_MACHINE=64
_confirm_lock=threading.Lock()

# ---------- 已复核报告 → 设备节拍 ----------
def derive_cycles(run):
 """按报告冻结快照逐设备汇总：有效节拍秒/件 = 运行分钟×60 ÷ 总件数（含不良，停机已合并裁剪）。"""
 acc={}
 for s in run.snapshot['sources']:
  op=(s['end']-s['start']-downtime_minutes(s['start'],s['end'],s['downtime']))*60
  a=acc.setdefault(s['department'],[0,0]);a[0]+=op;a[1]+=s['total']
 return {m:op/tot for m,(op,tot) in acc.items() if op>0 and tot>0}

# ---------- 输入快照与版本 ----------
def open_orders(db):
 booked={b.order_id for b in db.query(Booking).all()}
 return [o for o in db.query(WorkOrder).order_by(WorkOrder.id).all() if o.id not in booked]

def build_snapshot(db,run_id):
 run=db.get(Run,run_id)
 if not run or run.status!='completed' or not run.approved: raise HTTPException(409,'预排需引用已完成且已复核的报告')
 windows={}
 for w in db.query(ShiftWindow).order_by(ShiftWindow.machine,ShiftWindow.start).all(): windows.setdefault(w.machine,[]).append([w.start,w.end])
 orders=[{'id':o.id,'code':o.code,'qty':o.qty,'due':o.due,'mold':o.mold,'changeover_sec':o.changeover_sec,'machines':o.machines} for o in open_orders(db)]
 bookings=[{'order':b.order_code,'machine':b.machine,'mold':b.mold,'setup_start':b.setup_start,'start':b.start,'end':b.end} for b in db.query(Booking).all()]
 snap={'run':{'id':run.id,'name':run.name,'checksum':run.checksum},'cycles':derive_cycles(run),'windows':windows,'molds':[m.name for m in db.query(Mold).order_by(Mold.name).all()],'orders':orders,'bookings':bookings}
 version=hashlib.sha256(json.dumps(snap,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
 return snap,version,run

def solver_input(snap):
 return {'machines':[{'name':m,'cycle_sec':c,'windows':snap['windows'].get(m,[])} for m,c in snap['cycles'].items()],'orders':snap['orders'],'bookings':snap['bookings']}

def validate_scale(snap):
 if not snap['orders']: raise HTTPException(409,'没有待预排的工单')
 if len(snap['orders'])>MAX_ORDERS: raise HTTPException(422,f'待排工单超过{MAX_ORDERS}张，超出预排规模限制')
 if len(snap['cycles'])>MAX_MACHINES: raise HTTPException(422,f'设备超过{MAX_MACHINES}台，超出预排规模限制')
 for m,ws in snap['windows'].items():
  if len(ws)>MAX_WINDOWS_PER_MACHINE: raise HTTPException(422,f'设备{m}班表窗口超过{MAX_WINDOWS_PER_MACHINE}段')
 for o in snap['orders']:
  missing=[m for m in o['machines'] if m not in snap['cycles']]
  if missing: raise HTTPException(422,f"工单{o['code']}的可用设备{missing}在报告《{snap['run']['name']}》中无已复核节拍")

# ---------- 预排 ----------
def preschedule(db,user,run_id):
 snap,version,run=build_snapshot(db,run_id)
 validate_scale(snap)
 t0=time.monotonic()
 try: res=solver.solve(solver_input(snap),SOLVE_LIMIT_SEC)
 except solver.Refused as exc:
  log(db,user.email,'plan.refused',str(exc));db.commit()
  raise HTTPException(422,f'{SOLVE_LIMIT_SEC:.0f}秒内未能证实最优解，已拒绝出方案（{exc}）')
 if time.monotonic()-t0>SOLVE_LIMIT_SEC:
  log(db,user.email,'plan.refused','墙钟超时');db.commit()
  raise HTTPException(422,f'{SOLVE_LIMIT_SEC:.0f}秒内未能证实最优解，已拒绝出方案')
 result={**res,'unscheduled':unscheduled_reasons(snap,res)}
 plan=Plan(status='proposed',source_version=version,snapshot=snap,result=result,created=time.time())
 db.add(plan);log(db,user.email,'plan.preschedule',f"run={run_id} 按期件数={result['objective']['pieces']} 换模={result['objective']['changeover_sec']}秒");db.commit();db.refresh(plan)
 return plan

# ---------- 确认落账 ----------
def _lock_confirm_row(db):
 row=db.get(Meta,'confirm')
 if not row: row=Meta(name='confirm',value='');db.add(row);db.flush()
 db.query(Meta).filter_by(name='confirm').with_for_update().first()

def _check_conflicts(db,items):
 for it in items:
  for b in db.query(Booking).filter((Booking.machine==it['machine'])|(Booking.mold==it['mold'])).all():
   if b.setup_start<it['end'] and it['setup_start']<b.end: raise HTTPException(409,f"占用冲突：{it['order']}与已确认工单{b.order_code}在设备或模具上重叠，请重新预排")

def confirm(db,user,plan_id,key):
 plan=db.get(Plan,plan_id)
 if not plan: raise HTTPException(404,'预排方案不存在')
 dup=db.query(Confirmation).filter_by(idempotency_key=key).first()
 if dup: return dup.result
 done=db.query(Confirmation).filter((Confirmation.plan_id==plan_id)|(Confirmation.final_plan_id==plan_id)).first()
 if done: return done.result
 with _confirm_lock:
  db.rollback()  # 结束旧快照事务，确保读到最新已提交占用
  _lock_confirm_row(db)
  dup=db.query(Confirmation).filter_by(idempotency_key=key).first()
  if dup: return dup.result
  done=db.query(Confirmation).filter((Confirmation.plan_id==plan_id)|(Confirmation.final_plan_id==plan_id)).first()
  if done: return done.result
  plan=db.get(Plan,plan_id)
  snap,version,_=build_snapshot(db,plan.snapshot['run']['id'])
  recomputed=False
  if version==plan.source_version:
   final=plan;result=plan.result
  else:
   validate_scale(snap)
   try: res=solver.solve(solver_input(snap),SOLVE_LIMIT_SEC)
   except solver.Refused as exc:
    log(db,user.email,'plan.confirm_refused',str(exc));db.commit()
    raise HTTPException(422,f'源数据已变化，重算未能在{SOLVE_LIMIT_SEC:.0f}秒内证实最优：{exc}')
   result={**res,'unscheduled':unscheduled_reasons(snap,res)}
   final=Plan(status='confirmed',source_version=version,snapshot=snap,result=result,created=time.time())
   db.add(final);db.flush();plan.status='superseded';recomputed=True
  _check_conflicts(db,result['items'])
  now=time.time()
  for it in result['items']: db.add(Booking(plan_id=final.id,order_id=it['order_id'],order_code=it['order'],machine=it['machine'],mold=it['mold'],setup_start=it['setup_start'],start=it['start'],end=it['end']))
  final.status='confirmed'
  payload={'plan_id':final.id,'requested_plan_id':plan_id,'recomputed':recomputed,'source_version':final.source_version,'confirmed_at':now,'objective':result['objective'],'items':result['items'],'unscheduled':result['unscheduled']}
  db.add(Confirmation(plan_id=plan_id,final_plan_id=final.id,idempotency_key=key,created=now,result=payload))
  log(db,user.email,'plan.confirm',f'plan={final.id} recomputed={recomputed}');db.commit()
  return payload

# ---------- 未排原因（对最优方案做非破坏性插入检查，逐设备说明）----------
def _merge(ivs):
 out=[]
 for a,b in sorted(ivs):
  if out and a<=out[-1][1]: out[-1][1]=max(out[-1][1],b)
  else: out.append([a,b])
 return out

def _gaps(windows,busy):
 gaps=[]
 for ws,we in windows:
  cur=ws
  for a,b in busy:
   if b<=cur or a>=we: continue
   if a>cur: gaps.append([cur,min(a,we)])
   cur=max(cur,b)
   if cur>=we: break
  if cur<we: gaps.append([cur,we])
 return gaps

def _hours(sec): return f'{sec/3600:.1f}小时'

def unscheduled_reasons(snap,res):
 items=res['items'];bookings=snap['bookings'];out=[]
 by_code={o['code']:o for o in snap['orders']}
 for code in res['unscheduled']:
  o=by_code[code];findings=[];insertable=False
  for m in o['machines']:
   if m not in snap['cycles']: findings.append(f'{m}：报告中无节拍');continue
   p=o['qty']*snap['cycles'][m];need=p+o['changeover_sec']
   win=[[ws,min(we,o['due'])] for ws,we in snap['windows'].get(m,[]) if ws<min(we,o['due'])]
   busy_m=_merge([[it['setup_start'],it['end']] for it in items if it['machine']==m]+[[b['setup_start'],b['end']] for b in bookings if b['machine']==m])
   busy_k=_merge([[it['setup_start'],it['end']] for it in items if it['mold']==o['mold']]+[[b['setup_start'],b['end']] for b in bookings if b['mold']==o['mold']])
   gaps=_gaps(win,_merge(busy_m+busy_k))
   same_ends={it['end'] for it in items if it['machine']==m and it['mold']==o['mold']}|{b['end'] for b in bookings if b['machine']==m and b['mold']==o['mold']}
   max_full=max([b-a for a,b in gaps],default=0)
   max_free=max([b-a for a,b in gaps if a in same_ends],default=0)
   max_machine=max([b-a for a,b in _gaps(win,busy_m)],default=0)
   if max_full>=need or max_free>=p: insertable=True;findings.append(f'{m}：存在可插入空档');continue
   if not win: findings.append(f'{m}：交期前无班表窗口')
   elif max_machine>=need: findings.append(f"{m}：设备空档足够但模具{o['mold']}在交期前被占用（最长空档{_hours(max_full)}，连做需{_hours(need)}）")
   else: findings.append(f'{m}：交期前可用空档不足（最长{_hours(max_full)}，连做含换模需{_hours(need)}）')
  reason='；'.join(findings) if findings else '无可用设备'
  if insertable: reason='存在可插入空档，但插入将降低整体按期件数或增加换模，按目标权衡未排（'+reason+'）'
  else: reason='无法按期插入：'+reason
  out.append({'order':code,'order_id':o['id'],'qty':o['qty'],'due':o['due'],'mold':o['mold'],'reason':reason})
 return out
