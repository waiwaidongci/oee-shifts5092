"""求解器单测：语义用例 + 与暴力枚举对照的最优性交叉验证。"""
import random
from itertools import combinations
from src.services import solver

def M(name,cyc,ws): return {'name':name,'cycle_sec':cyc,'windows':ws}
def O(code,qty,due,mold,ch,ms): return {'code':code,'qty':qty,'due':due,'mold':mold,'changeover_sec':ch,'machines':ms}
def snap(machines,orders,bookings=None): return {'machines':machines,'orders':orders,'bookings':bookings or []}

def validate_items(snapshot,items):
 """独立可行性校验：批次时长、交期、窗口、设备/模具不重叠、免换模规则、已确认占用。"""
 orders={o['code']:o for o in snapshot['orders']};machines={m['name']:m for m in snapshot['machines']}
 for it in items:
  o=orders[it['order']];m=machines[it['machine']]
  assert abs((it['end']-it['start'])-o['qty']*m['cycle_sec'])<1e-6,'批次时长不符'
  assert it['end']<=o['due']+1e-9,'逾期完工'
  assert any(it['setup_start']>=ws-1e-9 and it['end']<=we+1e-9 for ws,we in m['windows']),'跨窗口或落在窗口外'
  assert it['changeover_sec'] in (0,o['changeover_sec'])
  assert abs(it['start']-it['setup_start']-it['changeover_sec'])<1e-9
 for a,b in combinations(items,2):
  if a['machine']==b['machine']: assert a['end']<=b['setup_start']+1e-9 or b['end']<=a['setup_start']+1e-9,'设备重叠'
  if a['mold']==b['mold']: assert a['end']<=b['setup_start']+1e-9 or b['end']<=a['setup_start']+1e-9,'模具重叠'
 for it in items:
  o=orders[it['order']]
  if it['changeover_sec']==0 and o['changeover_sec']>0:
   assert any(x is not it and x['machine']==it['machine'] and x['mold']==it['mold'] and abs(x['end']-it['start'])<1e-9 for x in items),'免换模必须同机同模首尾相接'
 for it in items:
  for bk in snapshot.get('bookings',[]):
   if bk['machine']==it['machine'] or bk['mold']==it['mold']:
    assert it['end']<=bk['setup_start']+1e-9 or bk['end']<=it['setup_start']+1e-9,'与已确认占用冲突'

# ---------- 语义用例 ----------
def test_single_order():
 r=solver.solve(snap([M('A',10,[[0,10000]])],[O('X',10,5000,'K',60,['A'])]))
 assert r['objective']['pieces']==10 and r['objective']['changeover_sec']==60
 it=r['items'][0];assert it['end']-it['start']==100 and it['setup_start']==it['start']-60 and it['setup_start']>=0
 validate_items(snap([M('A',10,[[0,10000]])],[O('X',10,5000,'K',60,['A'])]),r['items'])

def test_same_mold_block_saves_changeover():
 s=snap([M('A',10,[[0,10000]])],[O('P',10,9000,'K',300,['A']),O('Q',10,9000,'K',300,['A'])])
 r=solver.solve(s)
 assert r['objective']['pieces']==20 and r['objective']['changeover_sec']==300,'同模连做只计一次换模'
 items=sorted(r['items'],key=lambda x:x['start'])
 assert items[1]['start']==items[0]['end'] and items[1]['changeover_sec']==0
 validate_items(s,r['items'])

def test_pieces_priority_over_changeover():
 s=snap([M('A',10,[[0,1200]])],[O('X',100,1200,'K1',0,['A']),O('Y',60,1200,'K2',0,['A']),O('Z',50,1200,'K3',0,['A'])])
 r=solver.solve(s)
 assert r['objective']['pieces']==110,'件数优先：选Y+Z而非单件更大的X'
 assert 'X' in r['unscheduled']
 validate_items(s,r['items'])

def test_changeover_tiebreak():
 s=snap([M('A',10,[[0,10000]])],[O('R',10,9000,'K',300,['A']),O('S',10,9000,'K',200,['A'])])
 r=solver.solve(s)
 assert r['objective']['pieces']==20 and r['objective']['changeover_sec']==200,'同件数选换模更少的排法'
 validate_items(s,r['items'])

def test_mold_no_overlap_across_machines():
 s=snap([M('A',10,[[0,150]]),M('B',10,[[0,150]])],[O('P',10,150,'K',0,['A']),O('Q',10,150,'K',0,['B'])])
 r=solver.solve(s)
 assert r['objective']['pieces']==10,'同一模具不能同时在两台设备上'
 validate_items(s,r['items'])

def test_machine_no_overlap():
 s=snap([M('A',10,[[0,1000]])],[O('P',60,1000,'K',0,['A']),O('Q',60,1000,'K',0,['A'])])
 r=solver.solve(s)
 assert r['objective']['pieces']==60
 validate_items(s,r['items'])

def test_batch_cannot_span_windows():
 s=snap([M('A',10,[[0,400],[500,900]])],[O('P',50,5000,'K',0,['A'])])
 r=solver.solve(s)
 assert r['objective']['pieces']==0 and r['unscheduled']==['P'],'整批连做不得跨窗口'

def test_bookings_block_occupancy():
 bk=[{'machine':'A','mold':'K','setup_start':0,'start':0,'end':600}]
 s=snap([M('A',10,[[0,1000]])],[O('P',40,1000,'K',0,['A'])],bk)
 r=solver.solve(s)
 assert r['objective']['pieces']==40 and r['items'][0]['setup_start']>=600
 validate_items(s,r['items'])

def test_setup_must_stay_inside_window():
 s=snap([M('A',10,[[100,1000]])],[O('P',10,1000,'K',50,['A'])])
 r=solver.solve(s)
 assert r['items'][0]['setup_start']>=100,'换模也属于班表窗口内作业'
 validate_items(s,r['items'])

def test_delay_enables_tight_chain():
 """已确认占用挡在中间时，推迟开工可让后续同模工单全部紧贴，换模归0。"""
 bk=[{'machine':'M0','mold':'K0','setup_start':100,'start':100,'end':260}]
 s=snap([M('M0',12,[[0,500],[600,900]]),M('M1',8,[[0,300],[900,1200]])],
  [O('O0',5,1678,'K0',0,['M0']),O('O1',6,1379,'K0',100,['M0']),O('O2',6,1217,'K0',100,['M0','M1'])],bk)
 r=solver.solve(s)
 assert r['objective']=={'pieces':17,'changeover_sec':0.0}
 validate_items(s,r['items'])

def test_window_crossing_setup_choice():
 """跨窗口必须重换模时，选换模耗时最小的工单断开链条。"""
 s=snap([M('M0',12,[[0,300],[1200,1700]])],
  [O('O0',5,1887,'K0',50,['M0']),O('O1',6,1023,'K0',100,['M0']),O('O2',13,561,'K0',0,['M0']),O('O3',20,1639,'K0',100,['M0']),O('O4',10,1222,'K1',50,['M0']),O('O5',18,1398,'K0',50,['M0'])])
 r=solver.solve(s)
 assert r['objective']['pieces']==44 and r['objective']['changeover_sec']==50
 validate_items(s,r['items'])

def test_mold_left_and_returned_needs_setup():
 """模具离机去他台后再回来，必须重新换模。A1占满窗口1，A2只能去窗口2。"""
 s=snap([M('M0',10,[[0,100],[200,300]]),M('M1',10,[[0,300]])],
  [O('A1',9,100,'K',10,['M0']),O('B1',1,300,'K',10,['M1']),O('A2',1,300,'K',10,['M0'])])
 r=solver.solve(s)
 assert r['objective']['pieces']==11 and r['objective']['changeover_sec']==30
 validate_items(s,r['items'])

def test_refused_when_not_proven_optimal(monkeypatch):
 import types
 class Fake:
  def __init__(self): self.parameters=types.SimpleNamespace(max_time_in_seconds=0,random_seed=0)
  def solve(self,model): return solver.cp_model.FEASIBLE
  def status_name(self,s): return 'FEASIBLE'
 monkeypatch.setattr(solver.cp_model,'CpSolver',lambda:Fake())
 s=snap([M('A',10,[[0,1000]])],[O('P',10,1000,'K',0,['A'])])
 try:
  solver.solve(s,30)
  assert False,'未证实最优时必须拒绝'
 except solver.Refused: pass

# ---------- 暴力枚举对照 ----------
def _interleavings(parts):
 parts=[p for p in parts if p[1]]
 if not parts: yield [];return
 for idx,(mn,s) in enumerate(parts):
  rest=parts[:idx]+parts[idx+1:] if len(s)==1 else parts[:idx]+[(mn,s[1:])]+parts[idx+1:]
  for tail in _interleavings(rest): yield [(s[0],mn)]+tail

def _oracle(snapshot):
 """枚举 指派×设备序列×全局交错，按"尽早连做"重放，取字典序最优（件数,-换模）。"""
 machines=snapshot['machines'];orders=snapshot['orders'];bookings=snapshot.get('bookings',[])
 cyc={m['name']:m['cycle_sec'] for m in machines};win={m['name']:m['windows'] for m in machines}
 bk_m={m['name']:[] for m in machines};bk_k={}
 for b in bookings: bk_m[b['machine']].append((b['setup_start'],b['end']));bk_k.setdefault(b['mold'],[]).append((b['setup_start'],b['end']))
 best=(0,0.0)
 def replay_min_ch(perm):
  """该交错下全量排入的最小换模；不可行返回 None。紧贴/换模为分支维度。"""
  best=[None]
  def rec(idx,mbusy,kbusy,mlast,kend,chsum):
   if best[0] is not None and chsum>=best[0]: return
   if idx==len(perm): best[0]=chsum;return
   i,mn=perm[idx];o=orders[i];p=o['qty']*cyc[mn];k=o['mold'];prev=mlast.get(mn)
   def overlaps(ivs,s,e): return any(s<b and a<e for a,b in ivs)
   if prev and orders[prev[0]]['mold']==k and kend.get(k,0)<=prev[1]:
    t=prev[1]
    if t+p<=o['due'] and any(t>=ws and t+p<=we for ws,we in win[mn]) and not overlaps(mbusy[mn],t,t+p) and not overlaps(kbusy.get(k,[]),t,t+p):
     mb2={x:list(v) for x,v in mbusy.items()};kb2={x:list(v) for x,v in kbusy.items()}
     mb2[mn].append((t,t+p));kb2.setdefault(k,[]).append((t,t+p))
     ml2=dict(mlast);ke2=dict(kend);ml2[mn]=(i,t+p);ke2[k]=max(ke2.get(k,0),t+p)
     rec(idx+1,mb2,kb2,ml2,ke2,chsum)
   setup=o['changeover_sec'];low=(prev[1]+setup) if prev else setup;t=None
   for ws,we in win[mn]:
    cand=max(low,ws+setup)
    while cand+p<=we and cand+p<=o['due']:
     s0=cand-setup
     hit=next((b for a,b in mbusy[mn] if s0<b and a<cand+p),None)
     if hit is not None: cand=hit+setup;continue
     hit=next((b for a,b in kbusy.get(k,[]) if s0<b and a<cand+p),None)
     if hit is not None: cand=hit+setup;continue
     t=cand;break
    if t is not None: break
   if t is not None:
    mb2={x:list(v) for x,v in mbusy.items()};kb2={x:list(v) for x,v in kbusy.items()}
    mb2[mn].append((t-setup,t+p));kb2.setdefault(k,[]).append((t-setup,t+p))
    ml2=dict(mlast);ke2=dict(kend);ml2[mn]=(i,t+p);ke2[k]=max(ke2.get(k,0),t+p)
    rec(idx+1,mb2,kb2,ml2,ke2,chsum+setup)
  rec(0,{m['name']:list(bk_m[m['name']]) for m in machines},{k:list(v) for k,v in bk_k.items()},{},{},0.0)
  return best[0]
 def evaluate(seqs):
  nonlocal best
  for perm in _interleavings([(m['name'],s) for m,s in zip(machines,seqs)]):
   ch=replay_min_ch(perm)
   if ch is None: continue
   pieces=sum(orders[i]['qty'] for i,_ in perm)
   if pieces>best[0] or (pieces==best[0] and ch<best[1]): best=(pieces,ch)
 seqs=[[] for _ in machines]
 def rec(i):
  if i==len(orders): evaluate(seqs);return
  rec(i+1)
  for mi,m in enumerate(machines):
   if m['name'] in orders[i]['machines']:
    for pos in range(len(seqs[mi])+1):
     seqs[mi].insert(pos,i);rec(i+1);seqs[mi].pop(pos)
 rec(0)
 return best

def test_bruteforce_crosscheck():
 rng=random.Random(20261120)
 for case in range(30):
  nm=rng.choice([1,2]);nk=rng.choice([1,2])
  def rand_machine(m):
   starts=sorted(rng.sample(range(0,1500,300),2))
   return M(f'M{m}',rng.choice([8,10,12]),[[a,a+rng.choice([300,500,700])] for a in starts])
  machines=[rand_machine(m) for m in range(nm)]
  molds=[f'K{k}' for k in range(nk)]
  orders=[O(f'O{i}',rng.randint(5,20),rng.randint(400,2000),rng.choice(molds),rng.choice([0,50,100]),[m['name'] for m in machines if rng.random()<0.8] or [machines[0]['name']]) for i in range(rng.randint(3,6))]
  bookings=[]
  if rng.random()<0.4 and nm:
   bookings=[{'machine':machines[0]['name'],'mold':molds[0],'setup_start':100,'start':100,'end':260}]
  s=snap(machines,orders,bookings)
  r=solver.solve(s,10)
  pieces,ch=_oracle(s)
  assert r['objective']['pieces']==pieces,f'case{case} 件数不一致 {r["objective"]} vs oracle {(pieces,ch)}'
  assert r['objective']['changeover_sec']<=ch+1e-6,f'case{case} 求解器换模多于暴力上界 {r["objective"]} vs oracle {(pieces,ch)}'
  validate_items(s,r['items'])
