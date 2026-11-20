import {heading} from '../components/common/header.js';import {table} from '../components/common/table.js';import {esc,time} from '../utils/format.js';import {store} from '../stores/business.js';
const PLAN_STATUS={proposed:'预排待确认',confirmed:'已确认落账',superseded:'已被重算取代'};
const badge=s=>`<span class="status">${PLAN_STATUS[s]||esc(s)}</span>`;
const hours=v=>(v/3600).toFixed(1)+'h';
const departments=d=>[...new Set(d.sources.map(s=>s.data.department))];
function gantt(items,nameOf){
 if(!items.length)return '<p class="empty">暂无时段。</p>';
 const t0=Math.min(...items.map(i=>i.setup_start)),t1=Math.max(...items.map(i=>i.end)),span=t1-t0||1;
 const machines=[...new Set(items.map(i=>i.machine))];
 return '<div class="gantt">'+machines.map(m=>`<div class="gantt-row"><span class="gantt-label">${esc(m)}</span><div class="gantt-track">${items.filter(i=>i.machine===m).map(i=>{const l=(i.setup_start-t0)/span*100,w=(i.end-i.setup_start)/span*100,sw=(i.start-i.setup_start)/(i.end-i.setup_start)*100;return `<div class="gantt-bar" style="left:${l}%;width:${w}%" title="${esc(nameOf(i))} · 换模 ${time(i.setup_start)} · 完工 ${time(i.end)}"><i style="width:${sw}%"></i><b>${esc(nameOf(i))}</b></div>`}).join('')}</div></div>`).join('')+`<div class="gantt-axis"><span>${time(t0)}</span><span>${time(t1)}</span></div></div>`;
}
function planDetail(plan,d,role){
 if(!plan)return '<p class="empty">选择已复核报告后点击“开始预排”，或在下方方案列表查看历史方案。</p>';
 const r=plan.result||{},items=r.items||[],uns=r.unscheduled||[];
 return `<section class="report"><div class="report-top"><h2>方案 #${plan.id} ${badge(plan.status)}</h2><span>${time(plan.created)}</span></div>
 <p>节拍来源：${esc(plan.snapshot.run.name)}（已复核）· 输入版本 <code class="checksum">${esc(plan.source_version.slice(0,16))}…</code> · 求解 ${r.solve_ms}ms（${esc(r.status||'')}）</p>
 <div class="metrics"><div><small>按期完工件数</small><strong>${r.objective?.pieces??0}</strong></div><div><small>换模总耗时</small><strong>${hours(r.objective?.changeover_sec??0)}</strong></div><div><small>承诺工单</small><strong>${items.length}</strong></div><div><small>未排工单</small><strong>${uns.length}</strong></div></div>
 <h3>承诺时段（设备/模具不重叠，整批连做避开停机）</h3>${gantt(items,i=>i.order)}
 ${table(items.map(i=>({工单:i.order,设备:i.machine,模具:i.mold,件数:i.qty,换模秒:i.changeover_sec,换模开始:time(i.setup_start),开工:time(i.start),完工:time(i.end)})))}
 <h3>未排原因</h3>${uns.length?table(uns.map(u=>({工单:u.order,件数:u.qty,交期:time(u.due),模具:u.mold,原因:u.reason}))):'<p class="empty">全部工单均已按期排入。</p>'}
 ${plan.status==='proposed'&&role==='admin'?`<button id="plan-confirm" data-id="${plan.id}">确认此方案并落账</button>`:''}
 ${plan.status==='proposed'&&role!=='admin'?'<p>仅负责人可确认落账。</p>':''}
 <details><summary>冻结输入快照（同一版输入，SHA256 见上）</summary><pre style="white-space:pre-wrap;overflow-wrap:anywhere;font-size:11px">${esc(JSON.stringify(plan.snapshot,null,2))}</pre></details></section>`;
}
export function schedule(c,d){
 const approved=d.runs.filter(r=>r.approved&&r.status==='completed');
 const plan=d.plans.find(p=>p.id===store.selectedPlan)||d.plans[0];
 const role=store.session?.role;
 return heading('PRE-SCHEDULE / 05','工单预排与承诺确认','急单与共用模具冲突时，只看设备空档容易多接。此处以已复核报告的设备节拍精确预排：整批连做避开停机，设备与模具不重叠占用；先按期完工件数最多，再换模总耗时最少；30秒未证实最优即拒绝出方案。')
 +`<h2>一、设备节拍（来自已复核报告）</h2><div class="inline-form"><label>已复核报告<select id="cycles-run">${approved.map(r=>`<option value="${r.id}">${esc(r.name)}</option>`).join('')}</select></label></div><div id="cycles-box"><p class="empty">选择报告后显示逐设备节拍。</p></div>`
 +`<h2>二、模具与班表</h2><details><summary>登记模具</summary><form id="mold-form" class="inline-form"><label>模具名称<input name="name" required maxlength="60" placeholder="模具丁"></label><button>登记模具</button></form></details>`
 +table(d.molds.map(m=>({编号:m.id,模具:m.name})),['编号','模具'])
 +(d.molds.length?'<div>'+d.molds.map(m=>`<button class="toggle mold-del" data-id="${m.id}">删除 ${esc(m.name)}</button>`).join('')+'</div>':'')
 +`<details><summary>登记班表窗口（整批连做不跨窗口，即避开停机）</summary><form id="window-form" class="inline-form"><label>设备<input name="machine" list="machine-list" required></label><label>开始<input name="start" type="datetime-local" value="2026-11-21T08:00" required></label><label>结束<input name="end" type="datetime-local" value="2026-11-21T14:00" required></label><button>登记窗口</button></form><datalist id="machine-list">${departments(d).map(m=>`<option value="${esc(m)}">`).join('')}</datalist></details>`
 +table(d.windows.map(w=>({编号:w.id,设备:w.machine,开始:time(w.start),结束:time(w.end)})))
 +(d.windows.length?'<div>'+d.windows.map(w=>`<button class="toggle window-del" data-id="${w.id}">删除窗口#${w.id}</button>`).join('')+'</div>':'')
 +`<h2>三、工单录入</h2><details open><summary>新增工单（件数/交期/可用设备/模具/换模耗时）</summary><form id="order-form"><div class="form-grid"><label>工单编号<input name="code" required maxlength="60" placeholder="WO-201"></label><label>件数<input name="qty" type="number" min="1" value="100" required></label><label>交期<input name="due" type="datetime-local" value="2026-11-22T18:00" required></label><label>模具<select name="mold">${d.molds.map(m=>`<option>${esc(m.name)}</option>`).join('')}</select></label><label>换模耗时（分钟）<input name="changeover_min" type="number" min="0" value="30" required></label></div><fieldset><legend>可用设备（报告中需有已复核节拍）</legend>${departments(d).map(m=>`<label class="weekday"><input type="checkbox" name="machine" value="${esc(m)}">${esc(m)}</label>`).join('')}</fieldset><button>保存工单</button></form></details>`
 +table(d.orders.map(o=>({编号:o.id,工单:o.code,件数:o.qty,交期:time(o.due),模具:o.mold,换模秒:o.changeover_sec,可用设备:(o.machines||[]).join('、')})))
 +(d.orders.length?'<div>'+d.orders.map(o=>`<button class="toggle order-del" data-id="${o.id}">删除 ${esc(o.code)}</button>`).join('')+'</div>':'')
 +`<h2>四、预排（冻结同一版输入）</h2><form id="preschedule-form" class="inline-form"><label>节拍来源（已复核报告）<select name="run_id">${approved.map(r=>`<option value="${r.id}">${esc(r.name)}</option>`).join('')}</select></label><button ${approved.length?'':'disabled'}>开始预排</button></form>`
 +(store.confirmNote?`<p class="method">${esc(store.confirmNote)}</p>`:'')
 +planDetail(plan,d,role)
 +`<h2>五、方案列表</h2>${table(d.plans.map(p=>({编号:p.id,时间:time(p.created),状态:PLAN_STATUS[p.status]||p.status,按期件数:p.result?.objective?.pieces??'-',换模秒:p.result?.objective?.changeover_sec??'-',版本:(p.source_version||'').slice(0,12)})))}`
 +(d.plans.length?'<div>'+d.plans.map(p=>`<button class="toggle plan-select" data-id="${p.id}">查看方案#${p.id}</button>`).join('')+'</div>':'')
 +`<h2>六、已确认占用（承诺台账）</h2>${gantt(d.bookings,b=>b.order_code)}`
 +table(d.bookings.map(b=>({工单:b.order_code,设备:b.machine,模具:b.mold,换模开始:time(b.setup_start),开工:time(b.start),完工:time(b.end),方案:b.plan_id})));
}
