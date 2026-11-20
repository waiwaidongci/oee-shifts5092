"""工单预排精确求解器（CP-SAT 约束规划）。

排产语义（与页面口径说明一致）：
- 整批连做：每张工单在同一台设备上占一个连续时段，不拆分、不跨班表窗口（避开停机）。
- 换模：批前换模占用设备与模具，且必须与该批落在同一班表窗口内；
  同一设备上相邻同模工单连做免换模（时段首尾相接）；模具离开设备或跨窗口后需重新换模。
- 设备与模具（含批前换模时段）均不可重叠占用；已确认占用为固定禁区。
- 目标字典序：先按期完工件数最多（完工时刻不晚于交期即按期），再换模总耗时最少。
- 只有在时限内证实最优才返回方案，否则抛 Refused，调用方拒绝出方案。
"""
import time
from ortools.sat.python import cp_model

SCALE=1000  # 秒→毫秒：CP-SAT 只接受整数

class Refused(Exception): pass

def _ms(x): return int(round(x*SCALE))

def solve(snapshot,time_limit_sec=30.0):
 """snapshot={'machines':[{'name','cycle_sec','windows':[[s,e],...]}],'orders':[{'code','qty','due','mold','changeover_sec','machines':[...]}],'bookings':[{'machine','mold','setup_start','end'}]}；超时未证实最优抛 Refused。"""
 machines=snapshot['machines'];orders=snapshot['orders'];bookings=snapshot.get('bookings',[])
 midx={m['name']:i for i,m in enumerate(machines)}
 cyc=[_ms(m['cycle_sec']) for m in machines]
 windows=[[(_ms(a),_ms(b)) for a,b in m['windows']] for m in machines]
 horizon=max([b for ws in windows for _,b in ws]+[_ms(b['end']) for b in bookings]+[1])
 n=len(orders)
 qty=[o['qty'] for o in orders];due=[_ms(o['due']) for o in orders];mold=[o['mold'] for o in orders];ch=[_ms(o['changeover_sec']) for o in orders]
 elig=[[midx[x] for x in o['machines']] for o in orders]
 proc=[{m:qty[i]*cyc[m] for m in elig[i]} for i in range(n)]
 model=cp_model.CpModel()
 start=[model.new_int_var(0,horizon,f's{i}') for i in range(n)]
 end=[model.new_int_var(0,horizon,f'e{i}') for i in range(n)]
 sched=[model.new_bool_var(f'ok{i}') for i in range(n)]
 x={}
 for i in range(n):
  for m in elig[i]: x[i,m]=model.new_bool_var(f'x{i}_{m}')
  model.add(sched[i]==sum(x[i,m] for m in elig[i]))
  model.add(end[i]==start[i]+sum(x[i,m]*proc[i][m] for m in elig[i]))
  model.add(end[i]<=due[i]+horizon*(1-sched[i]))
 # 每台设备一条回路：决定先后顺序；同模相邻则首尾相接免换模
 samepred=[[] for _ in range(n)]
 for mi in range(len(machines)):
  cand=[i for i in range(n) if mi in elig[i]]
  if not cand: continue
  nodes=[-1]+cand;arcs=[]
  for i in nodes:
   lit=model.new_bool_var(f'self{mi}_{i}');arcs.append((i,i,lit))
   if i!=-1: model.add(lit+x[i,mi]==1)
  for i in nodes:
   for j in nodes:
    if i==j: continue
    lit=model.new_bool_var(f'a{mi}_{i}_{j}');arcs.append((i,j,lit))
    if i==-1: model.add(start[j]>=ch[j]).only_enforce_if(lit)
    elif j==-1: pass
    elif mold[i]==mold[j]:
     # 同模相邻：模具仍在设备上则首尾相接免换模；模具已离开则重新换模
     t=model.new_bool_var(f't{mi}_{i}_{j}')
     model.add(t<=lit)
     model.add(start[j]==end[i]).only_enforce_if([lit,t])
     model.add(start[j]>=end[i]+ch[j]).only_enforce_if([lit,t.Not()])
     samepred[j].append(t)
    else: model.add(start[j]>=end[i]+ch[j]).only_enforce_if(lit)
  model.add_circuit(arcs)
 chvar=[]
 for i in range(n):
  v=model.new_int_var(0,max(ch[i],0),f'chv{i}')
  if samepred[i]: model.add(v==ch[i]*(sched[i]-sum(samepred[i])))
  else: model.add(v==ch[i]*sched[i])
  chvar.append(v)
 # 占用起点（含批前换模）：辅助变量，区间组件只接受单变量仿射
 occ_start=[model.new_int_var(0,horizon,f'os{i}') for i in range(n)]
 for i in range(n): model.add(occ_start[i]==start[i]-chvar[i])
 # 整批（含批前换模）必须完整落在同一班表窗口内
 for i in range(n):
  for m in elig[i]:
   lits=[]
   for a,b in windows[m]:
    w=model.new_bool_var(f'w{i}_{m}_{a}')
    model.add(occ_start[i]>=a).only_enforce_if(w)
    model.add(end[i]<=b).only_enforce_if(w)
    lits.append(w)
   model.add(sum(lits)>=x[i,m])
 # 设备不重叠（含已确认占用）
 for mi,m in enumerate(machines):
  ivs=[]
  for i in range(n):
   if mi in elig[i]: ivs.append(model.new_optional_interval_var(occ_start[i],chvar[i]+proc[i][mi],end[i],x[i,mi],f'mi{i}_{mi}'))
  for bi,b in enumerate(bookings):
   if b['machine']==m['name']: ivs.append(model.new_interval_var(_ms(b['setup_start']),_ms(b['end'])-_ms(b['setup_start']),_ms(b['end']),f'bk{mi}_{bi}'))
  if ivs: model.add_no_overlap(ivs)
 # 模具不重叠（含已确认占用）
 for kname in sorted(set(mold)|{b['mold'] for b in bookings}):
  ivs=[]
  for i in range(n):
   if mold[i]==kname:
    for mi in elig[i]: ivs.append(model.new_optional_interval_var(occ_start[i],chvar[i]+proc[i][mi],end[i],x[i,mi],f'mo{i}_{mi}'))
  for bi,b in enumerate(bookings):
   if b['mold']==kname: ivs.append(model.new_interval_var(_ms(b['setup_start']),_ms(b['end'])-_ms(b['setup_start']),_ms(b['end']),f'bm{kname}_{bi}'))
  if ivs: model.add_no_overlap(ivs)
 # 字典序目标：1 件按期完工重于全部换模耗时
 weight=sum(ch)+1
 model.maximize(weight*sum(qty[i]*sched[i] for i in range(n))-sum(chvar))
 solver=cp_model.CpSolver()
 solver.parameters.max_time_in_seconds=max(0.1,time_limit_sec-0.5)
 solver.parameters.random_seed=42
 t0=time.monotonic();status=solver.solve(model);elapsed=time.monotonic()-t0
 if status!=cp_model.OPTIMAL or elapsed>time_limit_sec:
  raise Refused(f'求解状态={solver.status_name(status)}，用时{elapsed:.1f}秒，未证实最优')
 items=[]
 for i in range(n):
  if solver.value(sched[i]):
   m=next(m for m in elig[i] if solver.value(x[i,m]))
   items.append({'order':orders[i]['code'],'order_id':orders[i].get('id'),'machine':machines[m]['name'],'mold':mold[i],'qty':qty[i],'changeover_sec':solver.value(chvar[i])/SCALE,'setup_start':(solver.value(start[i])-solver.value(chvar[i]))/SCALE,'start':solver.value(start[i])/SCALE,'end':solver.value(end[i])/SCALE})
 items.sort(key=lambda it:(it['machine'],it['start']))
 return {'status':'optimal','solve_ms':int(elapsed*1000),'objective':{'pieces':sum(qty[i] for i in range(n) if solver.value(sched[i])),'changeover_sec':sum(solver.value(v) for v in chvar)/SCALE},'items':items,'unscheduled':[orders[i]['code'] for i in range(n) if not solver.value(sched[i])]}
