import math
from src.config.settings import CONFIG
def number(value,name,minimum=0,integer=False):
 if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value<minimum or (integer and int(value)!=value): raise ValueError(name+'数值不合法')
 return value
def validate_source(d):
 if not isinstance(d,dict) or set(d)!=set(CONFIG['fields']): raise ValueError('底稿字段必须与业务字段一致')
 for key in ('period','department'):
  if not isinstance(d[key],str) or not 1<=len(d[key])<=100: raise ValueError(key+'不能为空或过长')
 number(d['start'],'开始分钟',integer=True);number(d['end'],'结束分钟',integer=True)
 if not d['start']<d['end']<=2880: raise ValueError('班次必须为正时长且不超过两日')
 number(d['ideal_seconds'],'理想秒/件',minimum=0.001);number(d['total'],'产量',integer=True);number(d['good'],'合格数',integer=True)
 if d['good']>d['total']: raise ValueError('合格数不可大于总产量')
 if not isinstance(d['downtime'],list) or len(d['downtime'])>100: raise ValueError('停机区间需为数组且最多100段')
 for pair in d['downtime']:
  if not isinstance(pair,list) or len(pair)!=2: raise ValueError('停机区间必须是两个分钟数')
  number(pair[0],'停机起点');number(pair[1],'停机终点')
  if pair[1]<=pair[0]: raise ValueError('停机结束需晚于开始')
def validate_policy(d):
 if not isinstance(d,dict) or not isinstance(d.get('version'),str) or not 2<=len(d['version'])<=120: raise ValueError('口径版本名不合法')
 if not isinstance(d.get('definition'),str) or not d['definition']: raise ValueError('核算说明不能为空')
def validate_window(machine,start,end):
 if not isinstance(machine,str) or not 1<=len(machine)<=120: raise ValueError('设备名不合法')
 number(start,'窗口开始');number(end,'窗口结束')
 if not start<end: raise ValueError('班表窗口结束需晚于开始')
 if end-start>7*86400: raise ValueError('单个班表窗口不得超过7天')
def validate_order(d,molds):
 if not isinstance(d.get('code'),str) or not 1<=len(d['code'].strip())<=60: raise ValueError('工单编号需为1-60字')
 number(d.get('qty'),'件数',minimum=1,integer=True)
 if d['qty']>1000000: raise ValueError('件数过大')
 number(d.get('due'),'交期',minimum=1)
 number(d.get('changeover_sec'),'换模秒数',integer=True)
 if d['changeover_sec']>86400: raise ValueError('换模耗时不得超过24小时')
 if d.get('mold') not in molds: raise ValueError('模具不存在，请先登记')
 ms=d.get('machines')
 if not isinstance(ms,list) or not 1<=len(ms)<=12 or len(set(ms))!=len(ms): raise ValueError('可用设备需为1-12台且不重复')
 if not all(isinstance(m,str) and 1<=len(m)<=120 for m in ms): raise ValueError('可用设备名不合法')
