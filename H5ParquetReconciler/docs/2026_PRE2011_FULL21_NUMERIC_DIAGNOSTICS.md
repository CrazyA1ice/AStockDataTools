# 2026-10-30：21年H5 RAW整体验收后，保守开展历史数值诊断

## 已有Windows真实验收

- 1990-12-20～2010-12-31原H5保守A股代码候选日线共21年、3,682,327条。购买Parquet扫描的24个原日线文件/139行组Footer最早2011-01-04，证明被扫描的原购买day目录没有2011年前日线。
- 用户已逐年将3,682,327条原生整数全部转存到独立私有RAW Parquet，原购买Parquet、原H5、生产路由和活动指针均保持不变。
- 用户使用已验收代码对21个年份完整回读、SHA/行流、当前真实H5整数与购买原文件Footer状态做了全局复核，获得： FULL 21-YEAR RAW VERIFICATION PASSED: 3682327 rows。
- 全局SAFE仅保存在用户本地的 H5ParquetReconciler/reports/pre2011-full21-verify-9bba81ed3c33.json，记录21份文件的SHA256和年度行数，不上传源记录；所有历史单位/证券身份/标准化/生产开关均为否。
- 已合并 PR #172 (146e74203e6113ee703026d0dbb39bad3d0efa4d)，13/13项Windows批量回归测试成功。

## 本轮交付：历史原生RAW数值轮廓诊断（严格只读）

新增 tools/audit-pre2011-raw-numeric-profile-readonly.py：

1. 只接受模块reports/目录下此前真实生成的FULL-21 SAFE，核对21年完整列表、3,682,327条、每年行数/SHA、来源清单SHA、所有禁止认证及禁止生产变更标记。
2. 不接触原始H5/购买Parquet/数据库/生产指针，只读取每年唯一的私有RAW Parquet和manifest。每年SHA、清单来源链、原整数schema和行数全量核对。开始及结束读取复验SHA。注意：这个SAFE绑定的是原来完整验收的快照，**不是重新对当前原H5完成一次实时SHA审计**。
3. PyArrow按批次流式读取原生整数price四列、transCount和transAmount，统计每年和21年合计的：OHLC上下界不一致、任一价格为零、全部价格为零、四价相同、量额均零、量零而额非零、量非零而额零、数值大于uint32上限的行数。
4. 仅产生年度与总计的聚合计数，SAFE不记录任何原始股票代码、单个日期或价量额、真实行情文件地址。任何缺年、重复stage、篡改Parquet、错误manifest、覆盖同名SAFE均拒绝。
5. 数值异常**不是**单位结论，也可能来自停牌/原数据异常；不自动删除/修改记录。 historical_units_certified=false 和 ready_for_production_query_or_h5_mirror=false 始终保持关闭。

## 为什么还不能标准化

已有2025/2026年少数真实H5日线相对购买Parquet的候选匹配为：H5原始价除1000、成交量乘100、成交额乘1000。但这些只是有限样本的数值比例，不能直接外推到1990—2010年，更不能据此证明供应商的“股/手、元/万元”物理单位或不复权/前后复权口径。历史统一Parquet的正式写入和新的H5镜像须在这些内容被单独认证后进行。

## Windows PowerShell（每条命令一行）

先切本轮分支并运行全部合成测试（未执行Windows实测之前，不应运行真实数据诊断）：

    cd D:\ChatGPT\AStockDataTools; git fetch origin; if ($LASTEXITCODE -ne 0) { throw "fetch失败" }; git switch feat/pre2011-raw-numeric-profile-readonly-20261030; if ($LASTEXITCODE -ne 0) { throw "切换失败" }; git pull --ff-only origin feat/pre2011-raw-numeric-profile-readonly-20261030; if ($LASTEXITCODE -ne 0) { throw "更新失败" }; .\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test_audit_pre2011_raw_numeric_profile_readonly.py" -v; if ($LASTEXITCODE -ne 0) { throw "数值诊断测试失败，停止扫描" }; Write-Host "合成数值质量测试通过"

全部测试通过后执行只读诊断，报告写在模块reports下且不覆盖已有文件：

    cd D:\ChatGPT\AStockDataTools; $rid=[Guid]::NewGuid().ToString("N").Substring(0,12); $out="H5ParquetReconciler\reports\pre2011-raw-numeric-profile-$rid.json"; .\.venv\Scripts\python.exe H5ParquetReconciler\tools\audit-pre2011-raw-numeric-profile-readonly.py --full21-safe "H5ParquetReconciler\reports\pre2011-full21-verify-9bba81ed3c33.json" --out $out --read-only-private-raw; if ($LASTEXITCODE -ne 0) { throw "21年RAW数值诊断失败" }; $r=Get-Content $out -Raw | ConvertFrom-Json; if ($r.private_raw_rows_profiled -ne 3682327 -or $r.years_scanned -ne 21 -or $r.historical_units_certified -ne $false -or $r.original_h5_or_purchased_parquet_opened -ne $false -or $r.ready_for_production_query_or_h5_mirror -ne $false) { throw "诊断门禁异常" }; Write-Host "21年历史RAW数值质量诊断完成；脱敏SAFE：$out"

只需回传本轮单测与新增SAFE JSON；切勿上传商业原始Parquet/H5及其实际价格、股票代码或成交量。