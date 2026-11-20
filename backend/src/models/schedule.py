from sqlalchemy import Column,Integer,String,JSON,Float
from src.config.database import Base
class Mold(Base):
 __tablename__='molds'
 id=Column(Integer,primary_key=True); name=Column(String(60),unique=True)
class ShiftWindow(Base):
 __tablename__='shift_windows'
 id=Column(Integer,primary_key=True); machine=Column(String(120)); start=Column(Float); end=Column(Float)
class WorkOrder(Base):
 __tablename__='work_orders'
 id=Column(Integer,primary_key=True); code=Column(String(60),unique=True); qty=Column(Integer); due=Column(Float); mold=Column(String(60)); changeover_sec=Column(Integer); machines=Column(JSON); created=Column(Float)
class Plan(Base):
 __tablename__='schedule_plans'
 id=Column(Integer,primary_key=True); status=Column(String(20)); source_version=Column(String(64)); snapshot=Column(JSON); result=Column(JSON); created=Column(Float)
class Confirmation(Base):
 __tablename__='schedule_confirmations'
 id=Column(Integer,primary_key=True); plan_id=Column(Integer,unique=True); final_plan_id=Column(Integer); idempotency_key=Column(String(120),unique=True); created=Column(Float); result=Column(JSON)
class Booking(Base):
 __tablename__='schedule_bookings'
 id=Column(Integer,primary_key=True); plan_id=Column(Integer); order_id=Column(Integer); order_code=Column(String(60)); machine=Column(String(120)); mold=Column(String(60)); setup_start=Column(Float); start=Column(Float); end=Column(Float)
class Meta(Base):
 __tablename__='schedule_meta'
 name=Column(String(40),primary_key=True); value=Column(String(200),default='')
