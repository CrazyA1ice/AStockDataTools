# 单一 GUI 与原购买 1min Parquet 240/241 根数核对（2026-11-28）

## 单一 GUI（仅保留最新确认的更新运维中心）

本分支只保留 `market_update_dashboard.py` 作为 `ParquetLiveSync` 正式 GUI。重复的早期 Tkinter `gui.py`、`gui_simple.py` 均从本开发分支删除；旧启动脚本 `run-gui.ps1` 现仅转发至该更新中心，不再执行每次启动都必须跑全套离线测试的旧逻辑，也不要求旧历史私有 manifest 存在才能打开查看日志。

用户现有 `start-market-update-dashboard.cmd` 同样启动 **同一** `market_update_dashboard.py`。因此两个启动器是兼容入口，而非两套 GUI。唯一更新中心继续提供四阶段运行状态、QMT 预检/错误、阶段日志、读取本机游标及用户确认后的补更；GUI 自身不修改任何行情记录，正式补更由原 `scheduled-afternoon-update.ps1` 独占运行器执行，工作树禁止真实生产写入。旧 GUI 删除不意味着删除原日线、历史数据、H5、Parquet、private work、QMT 或数据处理命令行工具。

已删除源码仍能在 Git 历史中追溯，现有正式本地 checkout 不会因 GitHub Draft PR 自动改变；**合并/更新经验收的正式源码**后才会在本机删除旧文件。没有擅自修改已安装的 Windows 计划任务或真实市场数据库。

## 240 根还是 241 根：必须分清三个问题

1. **原始购买 Parquet**：必须直接读取原购买文件按 `(symbol, trading_day)` 精确计数，不能用 H5 合并后的 241 根、QMT 新的 241 根、原购买文件整日总行数或程序的目标 `240` 作替代。既往统一 Parquet 曾出现 `241 rows: 1 purchased + 240 H5-only`，它**不证明**购买数据本身 241 根。
2. **QMT 原始分钟回执**：Windows 历史实测存在 09:30～15:00 的 241 标签；其中 09:30 对应零量额占位或真实成交的情况不同。
3. **目标 240 根标准化分钟 K 线**：仓库 `market_month_storage._fold_241_day` 在原 QMT 09:30 量额双零时弃去占位；双正时将开盘竞价真实成交并入 09:31 标准根，并要求日级 OHLCVA 守恒；一正一零拒绝。此规则必须经过购买 Parquet 量纲、时间标签和官方同日报价校准。**240 根不证明丢了集合竞价成交，241 根也不证明保有所有 09:15–09:25 逐笔申报或撤单事件**。

### 直接审计购买 Parquet（只读，不涉及 H5 或 QMT）

工具 `audit_purchased_1min_bars_readonly.py` 只读取用户明确指定的原购买 `1min/2026-09.parquet`，按中国市场 `UTC+8` 对 `2026-09-30` 日期过滤，对每只股票输出精确行数的汇总直方图，240 / 241 / 其它根数的股票日数量、09:30 / 09:31 标签覆盖与 09:30 量额正正 / 零零 / 异常的**总量**；不会上传证券代码、逐股原始行情、单个文件数据，不修改源文件。只输出当天汇总计数，不打印每只股票的价格。

为防止主分支尚未合并时错误调用旧文件，下例使用本文所述**新独立 worktree** 的脚本路径；需先从下方 PR 固定提交建立该工作树。如果日后按验收流程合并到正式检出，再将脚本路径指向正式 `ParquetLiveSync` 即可。

```powershell
& 'D:\ChatGPT\AStockDataTools\.venv\Scripts\python.exe' -B 'D:\ChatGPT\AStockDataTools\work\market-single-gui-minute-audit-20261128\ParquetLiveSync\audit_purchased_1min_bars_readonly.py' --file 'D:\stock\AllCycleAStockData\1min\2026-09.parquet' --day 2026-09-30
```

**注意：** 默认价格时间戳按真实 UTC epoch 毫秒加 `UTC+8` 解释；若输出首次标签完全不在 A 股常规分钟时段，先排查数据商时标，不能把这种输出认定为 240/241 业务答案。本工具只认明确输入的原月份/原年度 Parquet，不追随当前工具生成的 2026-10/11 目标月文件，也不会补零、对齐或修复价格。源采购仓库不可见的事实需要用户 Windows 执行该命令才能确认；本项目 GitHub 开发环境不能代替真实数据盘。

**关于集合竞价：** 只凭 09:30 是否有行或 09:31 的 OHLCVA 不能证明竞价成交是否被完整累计；需要原始来源对 09:30/09:31 的标注规则、同日报告的官方 OHLCVA、可能的逐笔/竞价记录及聚合校准对比。对于 09:15–09:25 的订单簿变化，通常需要专门的逐笔委托/行情深度数据，分钟 K 线无从完整还原。

测试全部使用临时创建的假 Parquet：240、241、09:30 正成交、零占位、混合股票计数、时间筛选、空字段及错误时区，目标 **8 项**。新修改在 Windows 真机测试与原购买文件现场核对之前一律保留 Draft。
