# 每天 16:30 单任务四类数据增量更新

本文件描述候选调度简化方案。**更新 Git 代码不会自动改变 Windows 已安装的计划任务**；在真机验收和用户明确启用前，旧 21:30 任务继续运行。每日时刻均指中国市场时间（UTC+8）。

## 一个触发器、一个脚本、四个步骤

Windows 仅保留原任务名 `AStockDataTools-ParquetLiveSync`，将它的每日触发时间设置为**中国市场时间 16:30**（本机为中国时间则 16:30，日本时间则 17:30）。同一个 `scheduled-afternoon-update.ps1 -Apply` 进程依次执行：

1. **八周期 K 线**：QMT 分钟主源、TDX 官方日线、已有 eltdx/Tencent 样本交叉核验，再以已有事务规则增量更新 1/5/15/30/60 分钟、日、周、月
2. **财务**：QMT 最近 120 天公告窗口与九表缓存历史一致性检查、增量入库；单次最多 150 分钟，跨日轮转接续
3. **板块**：QMT 板块数据更新并保存每日成员快照
4. **除权**：QMT 除权因子增量；现有默认每次 80 只股票轮转，保留进度游标

**没有额外 20:45 触发器，不再按运行时间自动切换成“只执行行情”模式。** 任务只触发一次，四个步骤在一个脚本里完成。任何步骤失败都记录错误，不阻断其他独立步骤；运行结论不会把部分证券的扫描成功误报为全市场完整。

16:30 是**尝试采集的起点，不是多源数据就绪保证**。如官方 DAY 当天尚未发布、QMT 分钟不全或数据源冲突，行情模块保留已验证的旧数据并报告失败；不会为了按时完成而绕过核验。内部模块自己的财务 21:00–23:05 保护窗口是避免与既有 QMT 操作冲突的源安全约束，**不是另一个计划任务触发时间**。若用户希望当日等待所有来源齐备而非记录欠缺，须另行设计**同一进程内有界等待**并做真机验收，不能直接宣布已实现。

财务的 5,656 只和除权的 5,224 只当前不保证每天全部更新。每日游标、剩余未遍历股票和 pending 都保留；`source_completeness_verified=false` 仍需独立证据。已有 16 只 Capital 历史冲突以及 688259.SH 解码异常仍隔离，禁止覆盖旧版。当前真正具备多源核验的是**八周期行情**；财务、板块、除权暂时只有 QMT 入库主源，其他来源校验必须单独补齐，不得宣称“四类全部多源已核实”。

## 安全预检

先在 detached Preview worktree 跑以下离线回归及模拟任务安装，**绝不在 Preview worktree 执行 `-Apply`**：

```powershell
$ErrorActionPreference="Stop"; $env:PYTHONPATH=(Join-Path (Get-Location) "ParquetLiveSync"); & ".\.venv\Scripts\python.exe" -B -m unittest discover -s "ParquetLiveSync\tests" -p "test_market_1630.py" -v; if($LASTEXITCODE -ne 0){throw "Tests failed"}; & powershell.exe -NoProfile -ExecutionPolicy Bypass -File "ParquetLiveSync\tests\test_install_afternoon_schedule_mock.ps1"; if($LASTEXITCODE -ne 0){throw "Mock failed"}; & powershell.exe -NoProfile -ExecutionPolicy Bypass -File "ParquetLiveSync\scheduled-afternoon-update.ps1"
```

模拟安装应出现 `PASS_INSTALL_AFTERNOON_MOCK_NO_REAL_TASKS CST_1630_SINGLE`，预览应出现 `MARKET_1630_MODE=UNIFIED_SINGLE_RUN`。

## 安全切换

合并前确认原主 checkout 下有以下真正的私有进度文件：

- `ParquetLiveSync/work/market_update/commits.json`
- `ParquetLiveSync/work/qmt_extra/progress.json`
- `ParquetLiveSync/work/qmt_extra/financial-cache-progress.json`

**不得新建空游标、不得从 detached worktree 实盘写入**。确保 QMT 在线、Windows 用户登录、电脑不休眠；必须与其他批量行情/财务任务错开。正式安装前须完成实盘小批测试，并确认独立 `AStockDataTools-QMT-Financial-Daily` 任务不存在以及 `work/qmt_extra/schedule-enabled.json` 未启用。

仅在明确批准正式替换原任务后执行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "ParquetLiveSync\install-schedule.ps1" -Action Install -AfternoonUnified
```

此命令**覆盖原有同名任务的触发器**，只留每天 16:30 一个触发器，不安装第二个任务。安装器的默认旧选项仍是 21:30，切勿漏掉 `-AfternoonUnified`。

运行日志在 `ParquetLiveSync/work/afternoon-*.log`；最新汇总在 `ParquetLiveSync/work/last-afternoon-unified.json`。其他历史 `last-scheduled-run.json` 和旧版回执保留只读审计。
