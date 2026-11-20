# V2-D2B：生产代码指纹与财务版本备份范围预检（只读）

基于用户截图验收 V2-D2A：首页和故障页可见 QMT_CONNECTION_OBSERVED_ONLY，意味着当时 xtdata.get_client 成功，不证明后续连接可靠。静态同次回执、000755.SZ 检查点、五股票失败批次已核验。尚未完成正式写锁独占、canonical财务重试模块版本批准、财务备份及事务回滚，所以“一键重试”仍禁用。

## 本阶段实现（不下载、不写入）

- 新增 market_center_v2_recovery_inventory.py：只读取正式 ParquetLiveSync 下5个关键源码/PowerShell文件：qmt_extra_financial_cache_import.py、qmt_extra_financial_cache_worker.py、qmt_extra_data.py、run-qmt-financial-daily.ps1、scheduled-afternoon-update.ps1。报告文件长度与 SHA256；即使文件均存在，也始终 approved=false，因为本地指纹不能替代事先审核的正式版本清单。
- 生产 Finance 数据目录在 AllCycleAStockData/qmt_extra。仅对同次回执中的失败股票和9张财务表进行本次 run-day 匹配元信息只读枚举：active/日期.json + snapshots/日期-内容指纹.parquet。默认五股×九表=45个股表范围。文件没有当天版本不等于异常，因为失败批次可能尚未提交当天记录。
- 清单只统计大小、修改时间、名称；不读 Parquet 载荷，不调用 QMT，不宣称已验证 active pin 指向和历史快照内容，不复制文件、不创建备份、不修改私有工作区账本。真正允许写入前还须核查全部受影响历史版本、生成可信备份并演练恢复；本次run-day候选范围不是完整财务历史备份。
- 每个股表最多16个同日期快照候选；每个源码最多2MiB、每个单独快照最多2GiB，拒绝符号链接路径、越权目录、无效股票代码和未知日期。北京时间19:50—20:25拒绝文件元信息盘点，避开20:05计划任务的潜在文件竞争。
- 新增 market_center_v2_recovery_inventory_cli.py：要求 --state-module、--market-root、--explicit-readonly；缺少显式许可直接拒绝。
- GUI首页与故障页新增“核对正式版本与备份范围（只读）”；按需后台分析，页面显示读取文件数、候选股表范围，并保留写锁、固定代码版本批准、备份与回滚三项未完成状态。刷新正式回执后旧结果失效；复制恢复预览时再次比对回执与进度SHA。
- 即使 QMT 即时连接成功，仍然 can_execute=false、can_download=false。没有生产部署，没有修改原定时任务、财务导入器和任何行情文件。

## 跨日续跑规则

原 qmt_extra_financial_cache_import.py 中的 _prepare_daily_sweep 明确：如前一日daily扫股未结束，下一天启动普通daily时可能保持既有 daily_cursor 与 daily_sweep_start，并把 daily_date 更新为当日；只有前一轮已经完成或扫末尾时才重新进入新扫描起点。因此不能简单拿2026-11-20故障的旧单日下载参数在11-21重放，更不能无条件清空000755.SZ游标。本阶段只读显示 CROSS_DAY_NO_OLD_DAILY_REPLAY; INSPECT_ORIGINAL_DAILY_SWEEP_CARRY_FORWARD_RULE，下一步需根据当日QMT来源、实际财务记录和保存游标，审批独立的受控追赶流程。

## Windows 验收

建立独立detached worktree，保留此前已验收的版本。合成测试目标数：原V2-D1 126 + V2-D2A 20 + V2-D2B 19 = 165项（待Windows运行确认）。测试不调用真实QMT，不占计划任务锁，不写市场Parquet。

可先用显式只读CLI进行代码指纹与45股表范围的检查；该程序不会生成备份。新GUI的按钮也只是清单与门禁，不包含Apply功能。任何日期变化、来源不一致、版本未经批准均不允许历史重放、直接覆盖、删除快照。

下一阶段V2-D2C才设计独立审批的单财务受控执行器：只允许从已批准的canonical正式版本出发，取得 Local\AStockDataTools2005AllStages 唯一写锁，执行前再次核对账本和来源，并生成SHA256可验证的回滚备份后恢复。不可在detached开发目录直接运行，也不能仅凭无blockers作为自动写入授权。
