# 榫川设备有效产出核对册

试制设备班次与重叠停机记录→可用率/性能/质量口径→班组复盘站内交付；不把简单平均当加权总OEE

## 业务场景与工作流
模拟客户：榫川研究协作组，12位业务与分析人员。每月研究明细先从`oee-shifts-202611.csv`录入底稿，经口径冻结、Python核算、负责人复核后向业务阅读者交付站内CSV。原有流程依靠人工表格抄算，痛点为口径版本难追溯、重复计算易错、复核与交付脱节。

模块：业务总览、业务底稿、新建口径版本、异步核算与复核、工单预排、定时交付、站内收件箱、审计。底稿可新增/修改/删除；口径仅新增版本；报告提交时冻结来源与版本并保存SHA256。定时交付引用已复核报告快照，worker到期写入数据库，业务阅读者下载。

## 工单预排（已复核节拍→承诺时段）
急单撞上共用模具时，只看设备空档容易多接。预排页以**已复核报告的设备节拍**（运行分钟×60÷总件数，逐设备汇总自报告冻结快照）精确预排工单：录入件数、交期、可用设备、模具、换模耗时与班表窗口；整批连做不跨班表窗口（避开停机），批前换模占用设备与模具且落在同一窗口内；同一设备相邻同模工单连做免换模，模具离开设备后需重新换模；设备与模具（含换模时段）均不重叠占用。目标字典序：**先按期完工件数最多，再换模总耗时最少**（按期=完工不晚于交期）。

- 预排把"已复核报告+班表+模具+待排工单+已确认占用"冻结为同一版输入（SHA256），CP-SAT 精确求解；**30秒未证实最优即拒绝出方案**，不落库。
- 确认时源数据版本不变则按冻结方案落账，有变化则以当前数据重算后确认（原方案标记"已被重算取代"）；进程内锁+数据库行锁串行化确认，落账前复检占用冲突，**并发确认不重复占用**；幂等键保证**同次重试不重复落账**。
- 页面可核对承诺时段（甘特图+明细表）与未排原因（逐设备说明空档/模具/窗口限制）；已确认占用形成承诺台账，后续预排自动避让。
- 规模上限：待排工单≤60、设备≤12、单设备班表窗口≤64；求解器实现在`backend/src/services/solver.py`，编排在`scheduling.py`。

## 算法口径
停机区间合并裁剪、OEE三因子与按班次透视。重叠区间去重、跨班裁剪手算；性能超1显示警示不静默截断。

停机去重 · 三因子核对 · 逐班回看。输入：业务底稿与口径JSON；输出：summary、透视rows、method、warnings。算法实现在`backend/src/services/calculation.py`，输入校验在`validation.py`。固定seed=42，240条合成数据；未对接真实业务系统。修改源数据和新建因子/口径不会改变已提交报告。

## 一天的验收剧本
1. 09:00 admin查看240条seed底稿与具名业务期间。
2. 09:10 analyst添加`oee-shifts-202611.csv`的一条具名业务记录。
3. 09:20 admin在口径版本页登记新版本；旧版本保留。
4. 09:30 analyst命名“十一月核算”并选择期间/版本排队。
5. 09:31 Redis worker真实执行Python计算，展示汇总/透视与口径边界。
6. 09:40 admin核对数值后填写至少4字复核说明。
7. 09:45 admin建立60秒周期计划，worker到期生成站内持久化交付。
8. 09:46 viewer在站内收件箱下载交付CSV；审计页查看操作者与时间。
9. 09:50 analyst在工单预排页查看已复核节拍，登记模具/班表/工单；选择已复核报告预排，核对承诺时段甘特图与WO-109未排原因。
10. 09:55 admin确认方案落账；修改班表后再次确认旧方案将触发重算；审计页可见预排/确认/拒绝留痕。

## 快速启动
```sh
cp .env.example .env
docker compose up -d --build
docker compose exec -T backend python -m scripts.seed_demo
```
前端 http://localhost:18251 ，后端 http://localhost:19251/docs ，数据库宿主端口17751。中文父目录可用。恰好5服务frontend/backend/worker/db/redis；均有真实healthcheck。停止并清空演示数据：`docker compose down -v --remove-orphans`。

|角色|邮箱|密码|权限|
|---|---|---|---|
|admin|admin@demo.local|Demo2026!|全部底稿、口径版本、核算、复核、调度|
|analyst|analyst@demo.local|Demo2026!|底稿增改删、核算、导出；无复核/调度/口径写权限|
|viewer|viewer@demo.local|Demo2026!|只读；仅可下载已复核报告与站内交付|

## 工程结构与开发
Python3.11/FastAPI/SQLAlchemy/Redis，MySQL8，OR-Tools CP-SAT（工单预排精确求解）；前端原生HTML/CSS/JS ES modules，Nginx代理`/api/`剥前缀至后端。`frontend/src`按api/stores/pages/components/hooks/utils/router/constants/types拆分；`backend/src`按models/schemas/services/controllers/routes/middlewares/config/utils/constants拆分；`backend/scripts/seed_demo.py`自然键幂等且不覆盖用户修改。SQLAlchemy启动创建初始结构，迁移说明在backend/migrations。

后端开发：在backend安装requirements，设置DATABASE_URL/REDIS_URL/JWT_SECRET，`uvicorn src.main:app --reload`；前端可用Nginx或带同等代理的静态开发服务器。前后端全部业务计算在Python。

环境变量：COMPOSE_PROJECT_NAME、FRONTEND_PORT、BACKEND_PORT、DB_PORT、JWT_SECRET（部署替换）、DATABASE_URL、REDIS_URL、SEED_DEMO。`.env`不入Git。数据库/Redis/共享产物为命名卷。共享角色枚举admin/analyst/viewer与状态queued/running/completed/failed分别定义于backend/src/constants/enums.py和frontend/src/constants/enums.js。两个中间件：统一可恢复校验错误、每IP每分钟360请求限流。

## 已知边界
定时分发为站内收件箱；一名worker轮询执行，无外部邮件。调度发送已复核固定报告快照，不自动重算新数据。时间显示Asia/Shanghai。报告导出适合小型数据；底稿全量加载240行演示数据。Google Fonts不可用时回退serif。后端API以专属字段对象收发，页面通过业务输入控件编辑，不要求用户写JSON。新增来源期间自动可选；专属字段和算法严格校验。JWT演示有效期2小时。预排为单请求同步求解（≤30秒），确认锁为进程内锁+数据库行锁（单后端进程部署）；同模工单跨班表窗口不视为连做，需重新换模；未证实最优时只拒绝、不出近似方案。

MIT License。

## 实际实体映射
来源记录（Source，专属业务字段校验）、口径版本（Policy）、核算报告（Run）、交付计划（Schedule）、交付（Delivery）均经数据库→模型→请求schema→service→route/controller→frontend API→store→page。Period为已有来源期间字典，在任务期间选择器使用；不单独作为复杂度计数。底稿JSON为小型多字段单记录存储，不虚构未落库的子实体。预排实体：模具（Mold）、班表窗口（ShiftWindow）、工单（WorkOrder）、预排方案（Plan，冻结同一版输入快照与SHA256）、确认记录（Confirmation，幂等键唯一）、承诺占用（Booking，落账台账）。
