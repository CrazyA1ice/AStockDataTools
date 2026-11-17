# 16:30 中国市场时间：股票八周期 + 财务 + 板块 + 除权盘后任务（谨慎试运行）

本分支是 **GitHub 候选版本，不代表 Windows 本机的任务已经切换，更不代表四类数据全市场每天均已完成**。原 21:30 `AStockDataTools-ParquetLiveSync`、原 00:30 可选财务任务，均不会因拉取代码而自动修改。此前 Capital.m_quarter 16 只历史冲突与 688259.SH UTF-8 待补保留，绝不强制覆盖。

## 核心规则

- 中国市场时间（Asia/Shanghai，UTC+08:00）16:30 是 **当日数据可尝试读取的最早时间**，不是来源就绪证明。旧 `update_market.last_eligible_day` 的 20:00 边界改成 16:30，同时保留 QMT 240/241 分钟规范化、TDX DAY 原始来源校验、eltdx/Tencent 分钟交叉样本核对，以及 `market_all_cycles` 的最新交易日落盘闸门。
- 如果 16:30 官方 DAY 包尚未公布、QMT 分钟未齐或跨源价格不合格，则八周期阶段返回失败、旧数据仍保留；同一 Windows **任务名称**在中国时间 20:45 再触发**只重试八周期行情**，避免将昨日数据标作当日完成。其他阶段相互独立，任何阶段异常都记录到单独日志/状态。
- 同一 PowerShell 任务，串行执行：股票八周期 → 板块全量快照 → 除权 **80 只轮转批次** → 财务最近120天公告窗口 **最多150分钟有界批次**。后两项并非每天全市场完成；`EXECUTED_COVERAGE_UNVERIFIED` 只表示步骤的调用没有错误，**不代表历史完整或当天所有证券完成**。后续还需要针对除权及财务做全市场每日覆盖率、增量与回补队列设计。
- 财务增量保留 `SOURCE_HISTORY_CONFLICT` 与 `CACHE_DECODE_ERROR` pending，不覆盖有冲突的历史 Capital 版本，也不强行将空 PerShare 列视为已采齐。`run-qmt-financial-daily.ps1` 的 `-MaxMinutes` / `-MaxSymbols` 是有界参数，不更改默认旧 00:30 手动入口的参数默认值。
- 多源：现有 **K 线**已经使用 QMT 主分钟、TDX 官方日线、eltdx/Tencent 抽样价证据；不同来源成交量/额单位或分钟定义未标定时只做观察，不覆盖。**财务、板块、除权当前仍以 QMT 为实际入库源，并没有新增已认证第二源。** 后续可增加交易所公告/巨潮财务原文与公告日的 PIT 核验，东方财富/同花顺等板块当日成员对照，交易所权益分派公告与 QMT 除权因子交叉核对，要求代码标准化、日期和复权基准口径一致，不能按名称或近似数值直接覆盖。
- 保持现有 `LIVE.exclusive_writer` 独占保护；八周期、财务、补充数据都在同一个定时任务里串行运行。**不得同时运行旧 00:30 财务任务、旧前台批量下载或额外启用 `schedule-enabled.json`。** 安装预检会阻止已发现的财务重复任务/旧 extras 配置。
- Windows 必须保持用户已登录、QMT 在线、未休眠；任务起始触发时刻按 Windows 本地时区从中国市场时间转换。中国时区机器是本机 16:30/20:45；日本时区机器则是 17:30/21:45。跨夏令时的计算机应当在时区变更后重新核对计划任务触发时间。

## Windows 预检（**先不要安装**）

在仓库根目录运行以下一行命令。检查新代码时，不修改正式 Parquet 或计划任务：

```powershell
$ErrorActionPreference="Stop"; $env:PYTHONPATH=(Join-Path (Get-Location) "ParquetLiveSync"); & ".\.venv\Scripts\python.exe" -B -m unittest discover -s "ParquetLiveSync\tests" -p "test_market_1630.py" -v; if($LASTEXITCODE -ne 0){throw "16:30 tests failed"}; & powershell.exe -NoProfile -ExecutionPolicy Bypass -File "ParquetLiveSync\tests\test_install_afternoon_schedule_mock.ps1"; if($LASTEXITCODE -ne 0){throw "Afternoon scheduler mock failed"}; & powershell.exe -NoProfile -ExecutionPolicy Bypass -File "ParquetLiveSync\scheduled-afternoon-update.ps1"
```

原八周期与 QMT 补充数据的其他模拟测试、真机早盘来源可得性试运行必须继续通过。已有真实任务状态可以用：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "ParquetLiveSync\install-schedule.ps1" -Action Status
Get-ScheduledTask -TaskName "AStockDataTools-QMT-Financial-Daily" -ErrorAction SilentlyContinue
```

## 独立 worktree 严禁直接实盘写入

`AStockDataTools-1630-Preview` 是**只有代码**的 detached worktree，`ParquetLiveSync/work` 下不会自动共享原项目的 `market_update/commits.json`、`qmt_extra/progress.json` 或 `financial-cache-progress.json`。直接用此工作树的 `-Apply` 更新 `D:\stock`，可能使用全新游标对已有物理数据重新执行导入，因此新增运行时拒绝保护：必须是带有目录型 `.git` 的主 checkout 且上述原生进度文件真实存在。禁止手动创建空进度、软链猜测或复制老版本覆盖当前进度以绕过保护。

新代码测试阶段只在预览 worktree 运行离线单测、模拟任务安装和无 `-Apply` 的预览。需要真机 `-Apply` 时，应先在原正式仓库中经审核合并候选改动（或将相同 SHA 以保护方式部署到既有主 checkout），**且**核对进度文件、QMT 在线和旧 21:30 任务窗口，不与任何批量财务下载进程并行。若其中一项不满足则暂不执行。当前开发分支尚未通过真机短批验收，请不要安装新任务。

## 真机受控试运行（不修改任务，但执行小批增量）

**仅在代码已安全部署到原主 checkout、状态文件确认齐全后**，于交易日北京时间 16:30–18:00 之间，无其他采集程序运行时，可以显式运行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "ParquetLiveSync\scheduled-afternoon-update.ps1" -AdjustmentStockLimit 5 -FinanceMaxMinutes 10 -Apply
```

原文件、QMT 缓存、进度与快照执行原有事务/幂等保护。日志在 `ParquetLiveSync/work/afternoon-*.log`，状态在 `ParquetLiveSync/work/last-afternoon-afternoon_all.json`，晚间重试状态另存 `last-afternoon-retry_market_only.json`。

## 明确授权后替换既有任务（不是新增并行任务）

仅在 16:30 真机试运行通过、确认原 00:30 财务任务不存在且 `work/qmt_extra/schedule-enabled.json` 不存在时运行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "ParquetLiveSync\install-schedule.ps1" -Action Install -AfternoonUnified
```

此命令**更新原有** `AStockDataTools-ParquetLiveSync` 任务，附加中国时间 20:45 的 market-only 重试触发。不得直接运行普通 `-Action Install` 误以为是 16:30 新模式，后者仍保留旧版安全默认 21:30。任何旧任务被替换前须检查最近一次日志和实际 Windows Task Scheduler 触发时间。

**待完成主线：** ① 16只 Capital 异常字段证据审计；② 688259 UTF8 单只/单表定位；③ 除权每日全市场而非轮转、财务每日首轮游标跨保护窗口恢复；④ 财务公告原文与板块/除权的独立第二源只读证据，交叉验证通过再开放自动合并。当前版本不应称为“全量四类、全多源生产验收”。
