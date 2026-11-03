# 2026-11-03：实机41日、6,578万条分钟Parquet已验；立即启动剩余真实日期批量写盘

## 已有Windows真实验收，禁止把测试当作重复物化

`run-tiered-day-and-minute-progress.ps1` Windows本机最新实测：
- 1990—2026分层研究DAY本地API：5项合成测试PASS、跨年SHA私有实际查询7条（2010历史候选4+2011购买3）；历史单位仍未认证，不激活生产。
- 分钟进度SHA去重统计：5项合成测试PASS，**41个唯一有行情交易日**、`1min=54,856,883`、`5min=10,930,272`，实际统一私有Parquet合计**65,787,155条**；未声称完成源范围全部日期。SAFE `reports/verified-unique-minute-physical-progress-95b8ddd0196a.json`。
- 历史DAY已验 `3,673,987` 未认证1990—2010候选 + `8,340` RAW隔离，旧16年 `14,137,981` 不变。

## 立即做真正数据写盘：2026-01-01 → 2026-10-13

已存在的分钟后台worker `tools/minute-private-parquet-worker.py` 和GUI `start-minute-converter.bat` 按工作日逐日写入**真正的1/5min购买优先私有Parquet**，每一天都完整回读、SHA验收。已验收的41天跨任务从SAFE SHA自动复用，已修正10月13日1min END标签特殊处理；绝不以重复日期增加完成量。H5完整缺股日才补入，原购买Parquet和原Hikyuu H5只读；不创建新Hikyuu全量镜像。

新增入口 `tools/launch-minute-year-backfill.py`：自动检测同一源目录和相同年月范围已有GUI任务，已完成任务不重跑、失败/暂停/中断状态恢复、活跃全局写入锁拒绝第二个物理worker。复用GUI已经有的Windows分离进程/日志机制；启动后PowerShell马上返回，任务在独立进程按日继续。仅启动成功**不代表转换完成**。

可直接运行这个PowerShell**整行**启动真写盘：

```powershell
cd D:\ChatGPT\AStockDataTools; git fetch origin; if ($LASTEXITCODE -ne 0) { throw "fetch失败" }; git switch feat/private-2011-2025-purchased-physical-year-20261031; if ($LASTEXITCODE -ne 0) { throw "分支切换失败" }; git pull --ff-only origin feat/private-2011-2025-purchased-physical-year-20261031; if ($LASTEXITCODE -ne 0) { throw "更新失败" }; powershell.exe -NoProfile -ExecutionPolicy Bypass -File H5ParquetReconciler\run-minute-2026-backfill.ps1 -Run; if ($LASTEXITCODE -ne 0) { throw "分钟真实后台回填启动或测试失败；原市场数据没有被写入" }
```

包装器执行**既有3项GUI worker**和**新增5项headless launcher**测试。默认不带 `-Run` 则只做预检。写盘任务仅在确认 `-Run` 后启动；任务ID/PID/状态路径立即输出。worker写盘会持续读取本机真实源，完整验收逐日SHA。用户无需先手工选择日期、再手工点击GUI按钮。

**监控与暂停**：任何时刻双击 `H5ParquetReconciler\start-minute-converter.bat`，会自动挂接最近已创建后台任务，展示当前日期、已完成/复用/无源、每期行数、日志；界面关闭不停止worker。点击“当前日期结束后暂停”则写出 `stop_after_day.flag`；再次运行上面的同一命令或GUI恢复任务可继续。任务文件均位于 `H5ParquetReconciler\work\minute_gui\jobs\<12位任务ID>\state.json` 和 `activity.log`。

**数据源边界**：截至前一轮真实源核查，H5最新观测是2026-10-13，购买分钟2026截至2026-09-30。因此当前不会自动请求10月14日以后的假数据；即使2026年某一周一到周五没有市场bar也不得算成完整交易日。若有新TDX或H5数据更新，再单独登记新来源与延长日期，切勿改旧凭证。

任务真实完成后再次用 `tools/report-verified-unified-minute-progress.py` 计算SHA唯一日期和总行数，观察相较**41天/65,787,155条**的新增。后续按同样方式跑2025-01-01→12-31数据（源库存确认后），再纳入购买15/30/60min、week、month和最终跨周期Parquet版本。

**新headless launcher及新增5项测试待用户Windows首次运行确认。** 2026后台任务开始时的PID/status也不是完成证明。
