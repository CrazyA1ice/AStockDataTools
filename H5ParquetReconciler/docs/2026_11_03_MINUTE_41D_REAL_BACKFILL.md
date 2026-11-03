# 2026-11-03：实机41日、6,578万条分钟Parquet已验；立即启动剩余真实日期批量写盘

## 2026-11-03 用户实机启动结果 / 空白黑窗口修复

用户Windows运行 `run-minute-2026-backfill.ps1 -Run`：既有GUI worker **3/3** 和新增后台启动器 **5/5** 小测试全部PASS；实际创建独立后台任务 **`0625f02019fe`**，请求启动进程PID **3480**，范围2026-01-01→2026-10-13，`status=new_real_backfill_requested_detached`。**这仅是启动成功的证据，并没有本机后续进度日志，因此当前不能声称新完成了任何分钟行情日。**

用户报告启动后弹出黑色且没有输出的Python命令行。旧版GUI worker在Windows以 `python.exe` 加 `DETACHED_PROCESS` 启动且stdout/stderr重定向到 `work/minute_gui/jobs/<id>/worker-stdout.log`，所以即使出现黑窗口也不会显示进度。已修改 `tools/minute-private-parquet-gui.py`：未来从GUI或启动器创建worker时，**优先使用同一虚拟环境 `pythonw.exe`**，不存在则改用 `CREATE_NO_WINDOW`，去掉容易屏蔽该标志的 `DETACHED_PROCESS`，保留单例写入锁、独立PID、stdout/stderr日志和现有中断恢复机制；新增3项无窗口模拟单元测试，**Windows新版本尚待用户下一次启动核验**。**已经运行的PID 3480不受代码更新影响，不得单为隐藏旧窗口而强杀或重复启动任务。**

旧代码无需更新也可在另一个PowerShell直接查看本次当前任务：

```powershell
cd D:\ChatGPT\AStockDataTools; $j="H5ParquetReconciler\work\minute_gui\jobs\0625f02019fe"; Write-Host "===== 进程 ====="; Get-Process -Id 3480 -ErrorAction SilentlyContinue | Select-Object Id,ProcessName,CPU,StartTime; Write-Host "===== 状态 ====="; if(Test-Path "$j\state.json"){Get-Content "$j\state.json" -Raw -Encoding UTF8|ConvertFrom-Json|Select-Object status,done,total,current,last_error,pid|Format-List}; Write-Host "===== 日志 ====="; if(Test-Path "$j\activity.log"){Get-Content "$j\activity.log" -Tail 25 -Encoding UTF8}; if(Test-Path "$j\worker-stdout.log"){Get-Content "$j\worker-stdout.log" -Tail 25 -Encoding UTF8}
```

更新最新开发分支后，也可以使用新增的**只读**单行检查器（不用启动任何worker）：
`powershell.exe -NoProfile -ExecutionPolicy Bypass -File H5ParquetReconciler\inspect-minute-backfill.ps1 -JobId 0625f02019fe`。

若 `status=running` 并有持续变化的 `current` / 日志，可以打开 `start-minute-converter.bat` 监控或将空白黑窗口最小化。若 `failed`，记录 `last_error` 和 `activity.log`，由现有复用任务继续，不从头重复41天。若状态为 `completed`，仍须重新SHA统计真实非空日期，不能把零行情工作日也当完成。

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
