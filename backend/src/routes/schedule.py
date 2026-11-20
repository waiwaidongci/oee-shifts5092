import time
from fastapi import APIRouter,Depends,HTTPException
from src.config.database import database
from src.controllers.auth import current,editor,admin
from src.models.run import Run
from src.models.schedule import Mold,ShiftWindow,WorkOrder,Plan,Confirmation,Booking
from src.schemas.requests import MoldInput,WindowInput,OrderInput,PrescheduleInput,ConfirmInput
from src.services import scheduling
from src.services.validation import validate_window,validate_order
from src.services.audit import log
from src.utils.serialize import row
router=APIRouter()

@router.get('/molds')
def molds(db=Depends(database),u=Depends(current)): return [row(x) for x in db.query(Mold).order_by(Mold.name).all()]
@router.post('/molds')
def create_mold(b:MoldInput,db=Depends(database),u=Depends(editor)):
 name=b.name.strip()
 if db.query(Mold).filter_by(name=name).first(): raise HTTPException(409,'模具已存在')
 obj=Mold(name=name);db.add(obj);log(db,u.email,'mold.create',name);db.commit();db.refresh(obj);return row(obj)
@router.delete('/molds/{id}')
def delete_mold(id:int,db=Depends(database),u=Depends(editor)):
 obj=db.get(Mold,id)
 if not obj: raise HTTPException(404,'模具不存在')
 if db.query(WorkOrder).filter(WorkOrder.mold==obj.name).first(): raise HTTPException(409,'仍有工单引用该模具，不可删除')
 db.delete(obj);log(db,u.email,'mold.delete',obj.name);db.commit();return {'deleted':id}

@router.get('/windows')
def windows(db=Depends(database),u=Depends(current)): return [row(x) for x in db.query(ShiftWindow).order_by(ShiftWindow.machine,ShiftWindow.start).all()]
@router.post('/windows')
def create_window(b:WindowInput,db=Depends(database),u=Depends(editor)):
 validate_window(b.machine,b.start,b.end)
 for w in db.query(ShiftWindow).filter_by(machine=b.machine).all():
  if w.start<b.end and b.start<w.end: raise HTTPException(409,f'班表窗口与已有窗口重叠（{w.start}~{w.end}）')
 obj=ShiftWindow(machine=b.machine,start=b.start,end=b.end);db.add(obj);log(db,u.email,'window.create',f'{b.machine} {b.start}~{b.end}');db.commit();db.refresh(obj);return row(obj)
@router.delete('/windows/{id}')
def delete_window(id:int,db=Depends(database),u=Depends(editor)):
 obj=db.get(ShiftWindow,id)
 if not obj: raise HTTPException(404,'班表窗口不存在')
 db.delete(obj);log(db,u.email,'window.delete',id);db.commit();return {'deleted':id}

@router.get('/orders')
def orders(db=Depends(database),u=Depends(current)): return [row(x) for x in db.query(WorkOrder).order_by(WorkOrder.id).all()]
@router.post('/orders')
def create_order(b:OrderInput,db=Depends(database),u=Depends(editor)):
 data=b.model_dump();data['code']=data['code'].strip()
 validate_order(data,{m.name for m in db.query(Mold).all()})
 if db.query(WorkOrder).filter_by(code=data['code']).first(): raise HTTPException(409,'工单编号已存在')
 obj=WorkOrder(**data,created=time.time());db.add(obj);log(db,u.email,'order.create',data['code']);db.commit();db.refresh(obj);return row(obj)
@router.delete('/orders/{id}')
def delete_order(id:int,db=Depends(database),u=Depends(editor)):
 obj=db.get(WorkOrder,id)
 if not obj: raise HTTPException(404,'工单不存在')
 if db.query(Booking).filter_by(order_id=id).first(): raise HTTPException(409,'工单已确认落账，不可删除')
 db.delete(obj);log(db,u.email,'order.delete',obj.code);db.commit();return {'deleted':id}

@router.get('/cycles/{run_id}')
def cycles(run_id:int,db=Depends(database),u=Depends(current)):
 run=db.get(Run,run_id)
 if not run or run.status!='completed' or not run.approved: raise HTTPException(409,'仅已复核报告可提供设备节拍')
 return {'run_id':run.id,'name':run.name,'checksum':run.checksum,'cycles':scheduling.derive_cycles(run)}

@router.post('/preschedule')
def preschedule(b:PrescheduleInput,db=Depends(database),u=Depends(editor)): return row(scheduling.preschedule(db,u,b.run_id))
@router.get('/plans')
def plans(db=Depends(database),u=Depends(current)): return [row(x) for x in db.query(Plan).order_by(Plan.id.desc()).limit(50).all()]
@router.get('/plans/{id}')
def plan_detail(id:int,db=Depends(database),u=Depends(current)):
 obj=db.get(Plan,id)
 if not obj: raise HTTPException(404,'预排方案不存在')
 return row(obj)
@router.post('/plans/{id}/confirm')
def confirm(id:int,b:ConfirmInput,db=Depends(database),u=Depends(admin)): return scheduling.confirm(db,u,id,b.idempotency_key)
@router.get('/bookings')
def bookings(db=Depends(database),u=Depends(current)): return [row(x) for x in db.query(Booking).order_by(Booking.machine,Booking.start).all()]
