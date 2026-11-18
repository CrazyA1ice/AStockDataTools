# P61 · Capital.m_quarter 全历史并集安全判据（2026-11-18）

## 为什么不是直接“忽略 m_quarter”

2026-11-18 本地库存审计表明：financial-cache-progress.json 的 5,003 个待审股票中，5,001 个属于 Capital 历史冲突，另有一只 Top10Holder 和一只缓存解码错误。688227.SH、688228.SH 的单表/九表 cache 与旧快照的对比均发现 m_quarter 变化，但目前**只有两只真实样本**验证其余字段相同。不能因此将所有待审自动标为成功。

此阶段仅新增 `qmt_capital_semantic_proof.py` 的**纯只读判据**，不修改实际财务入库器对原始记录的逐字段比较，不改变 pending，不写 Parquet，亦不触碰原市场八周期。

### 严格候选条件

- 使用正式入库器 `_prior_rows(extra, code, "Capital")` 读取**所有历史 asof 所选版本的原始并集**，而不是只取最新快照；原始快照和 SHA 校验逻辑不变
- 每个报告日期 `m_timetag` 必须存在、可对照；最新 QMT 返回同样的日期集合，既不能多也不能少
- 除 `m_quarter` 和提供方行索引 `_index` 外，所有业务及日期字段、字段存在性、字段类型和精确值必须一致
- 若已有不同时间版本对同一报告日的真实业务字段不一致，必须继续隔离
- 同日重复 key、同一原始行重复、报告日期新增/缺失、`m_quarter` 字段缺失、真实总股本或流通股本变更、QMT cache 缺失等一律不会成为候选
- 返回 `M_QUARTER_ONLY_CANDIDATE` **不等于**准许入库：回执中的 `ready_to_commit=false`。只有多市场真实样本证据充分，再设计受控版本化修复

### 启用范围

`qmt_capital_conflict_census_readonly.py --sample-size 0`：只读队列统计，不连接 QMT。
`--sample-size 5`：在正式 checkout 中使用共享锁，调用 `qmt_extra_financial_cache_import._recover_utf8_group(..., mode="cache")`，不下载财务历史，五市场采样，使用严格全历史 `Capital` 并集证明；仅操作自动清理的 OS TEMP 工作文件，除已有 writer 锁标记外不修改正规数据。

独立分支先本地离线跑 `test_qmt_capital_semantic_proof.py`、`test_qmt_capital_conflict_census_readonly.py`。这次变更**不改变**每天 16:30 任务、财务 200 只轮转和 5,001 个待审记录的判定。

### 后续申请的修复阶段（尚未实施）

只有跨沪深主板、创业板、科创板、北交所真实样本满足严格判据，才能进一步开发对单只股本变化逐条证明、不可变原始版本备份、逐股申请式修复及撤销路径。历史版本不得删除、改写或以所谓“m_quarter 是季度值/市值”这种未经证实的定义武断丢弃原始字段。
