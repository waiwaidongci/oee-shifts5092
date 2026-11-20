# 002 工单预排

SQLAlchemy启动时自动创建以下新表（`src/models/schedule.py`），无需手工迁移；已有数据库升级前请先备份。

- `molds`：模具（名称唯一）。
- `shift_windows`：班表窗口（设备+起止时间戳，同设备不重叠，保存前校验）。
- `work_orders`：工单（编号唯一；件数/交期/模具/换模秒/可用设备JSON）。
- `schedule_plans`：预排方案（status=proposed/confirmed/superseded；source_version为冻结输入SHA256；snapshot为同一版输入快照；result含承诺时段与未排原因）。
- `schedule_confirmations`：确认记录（plan_id唯一、final_plan_id指向重算方案、idempotency_key唯一、result为落账回执）。
- `schedule_bookings`：承诺占用台账（工单/设备/模具/换模开始/开工/完工），后续预排作为固定禁区。
- `schedule_meta`：单行锁表（confirm行），跨请求串行化确认。

求解器新增依赖 `ortools==9.15.6755`（requirements.txt）。测试：`backend/tests/`（求解器语义+暴力枚举对照、API端到端含并发与幂等），运行 `python -m pytest tests/`。
