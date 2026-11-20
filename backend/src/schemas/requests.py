from pydantic import BaseModel,Field
class Login(BaseModel): email:str; password:str
class DataInput(BaseModel): data:dict
class RunInput(BaseModel): name:str=Field(min_length=2,max_length=120); policy_id:int; period:str='全部'
class ReviewInput(BaseModel): note:str=Field(min_length=4,max_length=2000)
class ScheduleInput(BaseModel): name:str=Field(min_length=2,max_length=120); run_id:int; interval_seconds:int=Field(ge=5,le=86400)
class MoldInput(BaseModel): name:str=Field(min_length=1,max_length=60)
class WindowInput(BaseModel): machine:str=Field(min_length=1,max_length=120); start:float; end:float
class OrderInput(BaseModel): code:str=Field(min_length=1,max_length=60); qty:int=Field(ge=1,le=1000000); due:float; mold:str=Field(min_length=1,max_length=60); changeover_sec:int=Field(ge=0,le=86400); machines:list[str]=Field(min_length=1,max_length=12)
class PrescheduleInput(BaseModel): run_id:int
class ConfirmInput(BaseModel): idempotency_key:str=Field(min_length=8,max_length=120)
