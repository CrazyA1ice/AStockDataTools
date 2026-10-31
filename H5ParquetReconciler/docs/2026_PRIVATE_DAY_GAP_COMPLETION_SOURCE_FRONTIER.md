# 2026-10-31：2026年9—10月私有日线缺口补齐与来源实际最后观测日

## 当前证据（来自此前真实Windows只读审计，并非本轮重新扫描）

- 原购买日线Parquet 2011—2026-09，共24份逐文件大小、footer行数、SHA256相符（14,115,707行），购买历史日期由原Parquet优先。
- 已存在可复用的真实源审计 reports/day-coverage-20260901-20261028-v1.json 与其SHA绑定的计划 reports/parquet-primary-day-bootstrap-plan-20260901-20261028-v1.json。审计窗口 **2026-09-01 至 2026-10-28**；H5-only的**Parquet整日缺失**共4日：
  - 2026-10-08：5,546根；
  - 2026-10-09：5,547根；
  - 2026-10-12：5,549根；
  - 2026-10-13：5,549根；
  - 总22,191根；混合日期H5-only股票日为0。
- **关键区别**：此前这一份审计的最后有数据行的日期为2026-10-13。10-14至10-28在这次审计的H5、购买Parquet来源中均未观测到任何股票日键。审计参数请求检查到10-28，**不是来源已更新到10-28的证明**，更不应该自己补造交易日/成交额。10月14日以后需要未来独立的TDX或其他实际来源重新审计（同时校验市场日历和闭市/交易规则）。
- 2026-09-28、29、30共6组真实日线H5 raw金额对照：候选 Parquet amount/1000 均低于现有H5原生整数，非整数残差6/6，half-even与ceil都能得到原H5整数6/6，无法区分取整规则。*保持QDC原始历史Parquet amount不变*，H5转私有Parquet的金额×1000仍是**候选尺度**，非全市场单位与舍入认证。

## 本轮新增来源观测前沿报告字段

在已有 tools/complete-private-parquet-primary-day-gap-set.py 中加了 **source_observation_frontier**：
- audit_requested_end_date：审计请求的结束日；
- last_source_stockday_observed_date：已SHA绑定的原日线源审计最后一个**有实际股票日键**的日期；
- calendar_days_after_last_source_observation：两日期间的日历天数（**不是未更新的交易日数**）；
- source_observations_reach_audit_window_end：是否观察到结束日有股票日数据；
- day_gap_staging_does_not_prove_later_market_freshness=true，post_frontier_market_data_fabricated=false。

在现有 gate/source SHA证据链中**重新调用原始审计分析器**，严查 gate 窗口与按日键清单是否与源报告一致；任何伪造日期边界拒绝。报告本身不含原价量额、单只代码或原始source绝对路径。**修复不修改任何真实H5、购买Parquet或私有active pointer**；工具的 plan 只读，complete 必须额外显式授权，且只暂存缺失的完整交易日到 module/work/unified_parquet；不会激活私有版本和生产数据路由。

新增 tests/test_complete_private_day_gap_source_frontier.py **10项合成**测试（Oct13→Oct28的15个日历天差额、审计至来源日、日历/交易日不混淆、重键和越界、错误日期/窗口、空审计、现有小型虚构市场源 plan/complete/篡改拒绝）。**本轮尚未运行Windows测试，不能提前标记通过。**

## Windows PowerShell命令（每条是完整的单行）

1. 拉开发分支、编译新工具并执行新增10项+原全市场补齐回归（旧测试也需要通过）：

    cd D:\ChatGPT\AStockDataTools; git fetch origin; if ($LASTEXITCODE -ne 0) { throw "fetch失败" }; git switch feat/day-gap-source-frontier-20261031; if ($LASTEXITCODE -ne 0) { throw "切换分支失败" }; git pull --ff-only origin feat/day-gap-source-frontier-20261031; if ($LASTEXITCODE -ne 0) { throw "更新失败" }; .\.venv\Scripts\python.exe -m py_compile H5ParquetReconciler\tools\complete-private-parquet-primary-day-gap-set.py H5ParquetReconciler\tests\test_complete_private_day_gap_source_frontier.py; if ($LASTEXITCODE -ne 0) { throw "语法检查失败" }; .\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test_complete_private_day_gap_source_frontier.py" -v; if ($LASTEXITCODE -ne 0) { throw "前沿新测试失败，停止" }; .\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test_complete_private_parquet_primary_day_gap_set.py" -v; if ($LASTEXITCODE -ne 0) { throw "原补齐回归失败，停止" }; Write-Host "来源观察边界和全市场缺口补齐合成测试全部通过"

2. 测试OK后，运行原有**只读PLAN**（只写一份新的脱敏SAFE到模块reports，不创建行情暂存）：

    cd D:\ChatGPT\AStockDataTools; $rid=[Guid]::NewGuid().ToString("N").Substring(0,12); $out="H5ParquetReconciler\reports\day-gap-4days-frontier-plan-$rid.json"; .\.venv\Scripts\python.exe H5ParquetReconciler\tools\complete-private-parquet-primary-day-gap-set.py --root "D:\stock" --gate-report "H5ParquetReconciler\reports\parquet-primary-day-bootstrap-plan-20260901-20261028-v1.json" --source-report "H5ParquetReconciler\reports\day-coverage-20260901-20261028-v1.json" --out $out --action plan --original-sources-read-only; if ($LASTEXITCODE -ne 0) { throw "安全PLAN失败，停止" }; $r=Get-Content -LiteralPath $out -Raw -Encoding UTF8 | ConvertFrom-Json; if ($r.audited_complete_h5_only_days -ne 4 -or $r.audited_complete_h5_only_day_rows -ne 22191 -or $r.source_observation_frontier.last_source_stockday_observed_date -ne "2026-10-13" -or $r.source_observation_frontier.audit_requested_end_date -ne "2026-10-28" -or $r.source_observation_frontier.source_observations_reach_audit_window_end -ne $false -or $r.private_active_pointer_changed -ne $false -or $r.original_market_files_modified -ne $false) { throw "PLAN日期证据/安全标志异常，停止" }; Write-Host "安全计划SAFE：$out"; $r.date_counts | Format-Table -AutoSize

3. 只有上述**全部OK、无混合日期H5-only、原源不变、4日22,191根严格匹配**且操作者明确希望暂存新的module-private数据时，才运行现有授权的 **COMPLETE**。它会在模块work下新增/复用四日Parquet并准备不可变版本（**不会激活版本或更改生产来源**）：

    cd D:\ChatGPT\AStockDataTools; $rid=[Guid]::NewGuid().ToString("N").Substring(0,12); $out="H5ParquetReconciler\reports\day-gap-4days-private-complete-$rid.json"; .\.venv\Scripts\python.exe H5ParquetReconciler\tools\complete-private-parquet-primary-day-gap-set.py --root "D:\stock" --gate-report "H5ParquetReconciler\reports\parquet-primary-day-bootstrap-plan-20260901-20261028-v1.json" --source-report "H5ParquetReconciler\reports\day-coverage-20260901-20261028-v1.json" --out $out --action complete --allow-new-private-parquet-stages --original-sources-read-only; if ($LASTEXITCODE -ne 0) { throw "私有完整日暂存或版本准备失败；不得移动原行情" }; $r=Get-Content -LiteralPath $out -Raw -Encoding UTF8 | ConvertFrom-Json; if ($r.audited_complete_h5_only_days -ne 4 -or $r.audited_complete_h5_only_day_rows -ne 22191 -or !$r.prepared_immutable_overlay_sha256 -or $r.private_active_pointer_changed -ne $false -or $r.h5_native_mirror_created -ne $false -or $r.original_market_files_modified -ne $false -or $r.production_query_route_modified -ne $false) { throw "COMPLETE安全结果不合格" }; Write-Host "私有4日补齐SAFE：$out"; Write-Host "准备的不可变版本：$($r.prepared_immutable_overlay_sha256)"

真实市场数据及其价格、数量、金额只留在本机H5ParquetReconciler/work目录；不得上传工作目录下的Parquet、购买原文件、原H5、私有RAW或市场stock.db。只回传不含市场数值的SAFE和PowerShell测试日志。**完成四天只说明截至最后观测日10-13的审计发现缺口已私有暂存，绝不能称10-28已更新完毕。**
