# Parquet 主线：2011—2026现有H5与Parquet日线精确差集总账（2026-10-31）

## 现有成果与本轮边界

购买日线24份共14,115,707条原件SHA和footer完整性已验收。2026-10-08/09/12/13四个完整缺口日22,191条已经私有Parquet暂存且准备了不可变版本：46bd847de3d00c0f48ff50830fa8688547198c6db1a3cf3b10eb7d2261770c03。真实SH600000查询买入1条+私有4条，不修改原H5、购买PQ或生产路由。截止10-28的审计中实际最后观测日期仅为10-13。

已实测2011、2025、2026-08、2026-09四份日线文件的原ts均对应UTC零点、北京时间08:00；并不是对所有年份字段语义的正式认证。H5 raw成交额的候选舍入仍待查证，不能把Parquet float64改写为整数后声称无损。1990—2010年的原H5历史已有独立的pre2011管道，本工具先解决购买数据对应的2011—2026。

本轮新建 tools/plan-parquet-primary-full-history-day-offline.py 和 tests/test_plan_parquet_primary_full_history_day_offline.py（15项纯合成测试）。

总账只处理 H5ParquetReconciler/reports 下的逐年原源覆盖报告，**不读真实H5/Parquet、OHLCVA或原生整数**，也不写入任意行情源。每年必须明确指定日线的完整日期边界（2011—2025年 Jan1至Dec31，2026年 Jan1至本次as-of 2026-10-31），day-only、a-share-candidate候选证券、无重复键、源报告完整、总量/逐日守恒、Parquet确实读取了具体键。**H5整年无行时的Parquet footer-only回退必须拒绝**，不能把年度元数据误判成精确差集。

不完整年份必须显式列为missing，不能补0。年级SAFE输出PQ-only、H5-only整日缺口、H5-only混合日期缺口、重叠OHLC/量额差异、按日类别计数、最后真实来源日和SHA256；不包含真实行情或股票代码。就算16年全审完也只代表精确键差集审计完毕，不意味着全历史已经并入私有Parquet；混合日期的缺证券记录不能使用现有整日stager。

## Windows PowerShell：下列每条命令均是单独完整的一行

先更新分支并运行新15项+旧11项Gate合成测试：

    cd D:\ChatGPT\AStockDataTools; git fetch origin; if ($LASTEXITCODE -ne 0) { throw "fetch失败" }; git switch feat/parquet-primary-full-history-day-ledger-20261031; if ($LASTEXITCODE -ne 0) { throw "切换分支失败" }; git pull --ff-only origin feat/parquet-primary-full-history-day-ledger-20261031; if ($LASTEXITCODE -ne 0) { throw "更新失败" }; .\.venv\Scripts\python.exe -m py_compile H5ParquetReconciler\tools\plan-parquet-primary-full-history-day-offline.py H5ParquetReconciler\tests\test_plan_parquet_primary_full_history_day_offline.py; if ($LASTEXITCODE -ne 0) { throw "语法失败" }; .\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test_plan_parquet_primary_full_history_day_offline.py" -v; if ($LASTEXITCODE -ne 0) { throw "新15项测试失败" }; .\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test_plan_parquet_primary_day_bootstrap_offline.py" -v; if ($LASTEXITCODE -ne 0) { throw "旧年度Gate失败" }; Write-Host "新旧日线总账合成测试全部通过"

新旧测试全通过后，先以2011和2025两个跨度较大的年度进行真实有界day-only精确只读扫描。即使某年H5没有数据，显式日期边界也强制扫描Parquet的具体键，避免metadata-only捷径；--resume允许从中断报告恢复，所有临时目录在模块内：

    cd D:\ChatGPT\AStockDataTools; foreach ($y in @(2011,2025)) { $out="H5ParquetReconciler\reports\historical-day-exact-$($y)-asof20261031-v1.json"; .\.venv\Scripts\python.exe H5ParquetReconciler\tools\reconcile-local-a-share-h5-parquet.py "D:\stock" --years $y --periods day --universe a-share-candidate --from-date "$($y)-01-01" --to-date "$($y)-12-31" --out $out --scratch "H5ParquetReconciler\work\_union_scratch" --batch-size 8192 --resume --read-only; if ($LASTEXITCODE -ne 0) { throw "年度 $y 真实日线审计失败" } }; Write-Host "2011与2025日线精确审计完成"

两年真实审计成功后，先生成partial年度总账，严格要求已确认2年、缺失14年、自动写入/镜像许可仍false：

    cd D:\ChatGPT\AStockDataTools; $rid=[Guid]::NewGuid().ToString("N").Substring(0,12); $out="H5ParquetReconciler\reports\history-day-ledger-partial-$rid.json"; .\.venv\Scripts\python.exe H5ParquetReconciler\tools\plan-parquet-primary-full-history-day-offline.py --reports "H5ParquetReconciler\reports\historical-day-exact-2011-asof20261031-v1.json" "H5ParquetReconciler\reports\historical-day-exact-2025-asof20261031-v1.json" --as-of-date 2026-10-31 --out $out --offline-reports-only; if ($LASTEXITCODE -ne 0) { throw "两年SAFE总账失败" }; $x=Get-Content -LiteralPath $out -Raw -Encoding UTF8 | ConvertFrom-Json; if ($x.annual_exact_day_audits_accepted -ne 2 -or $x.missing_exact_annual_day_audit_years.Count -ne 14 -or $x.full_2011_to_2026_as_of_source_key_coverage_audited -ne $false -or $x.ready_to_automatically_union_or_mirror -ne $false) { throw "部分历史账本状态错误" }; Write-Host "部分SAFE：$out"; $x.yearly_exact_source_coverage | Select-Object year,audited_purchased_unique_stockdays,audited_original_h5_unique_stockdays,audited_matching_stockday_keys,h5_only_complete_absent_date_candidate_rows,h5_only_mixed_date_candidate_rows,purchased_only_stockday_rows,latest_observed_source_stockday | Format-Table -AutoSize

两个年度门禁通过后，再执行2012—2024及2026年，共余14个年度（2026年仅至10-31，不能宣称原行情更新到了此日）。单年异常立即停止，保留已完成reports并可再次--resume：

    cd D:\ChatGPT\AStockDataTools; foreach ($y in @((2012..2024)+@(2026))) { $end="$($y)-12-31"; if ($y -eq 2026) { $end="2026-10-31" }; $out="H5ParquetReconciler\reports\historical-day-exact-$($y)-asof20261031-v1.json"; .\.venv\Scripts\python.exe H5ParquetReconciler\tools\reconcile-local-a-share-h5-parquet.py "D:\stock" --years $y --periods day --universe a-share-candidate --from-date "$($y)-01-01" --to-date $end --out $out --scratch "H5ParquetReconciler\work\_union_scratch" --batch-size 8192 --resume --read-only; if ($LASTEXITCODE -ne 0) { throw "年度 $y 扫描失败，保留其他年份，停止" } }; Write-Host "2011—2026截至10-31精确日线源审计完成"

16年源审计均通过后，离线合成全历史总账。仅输出年级计数与阻塞名单，绝不写原行情：

    cd D:\ChatGPT\AStockDataTools; $reports=@(2011..2026 | ForEach-Object { "H5ParquetReconciler\reports\historical-day-exact-$($_)-asof20261031-v1.json" }); $rid=[Guid]::NewGuid().ToString("N").Substring(0,12); $out="H5ParquetReconciler\reports\history-day-ledger-full-$rid.json"; .\.venv\Scripts\python.exe H5ParquetReconciler\tools\plan-parquet-primary-full-history-day-offline.py --reports $reports --as-of-date 2026-10-31 --out $out --offline-reports-only; if ($LASTEXITCODE -ne 0) { throw "16年精确日线总账未过门禁" }; $x=Get-Content -LiteralPath $out -Raw -Encoding UTF8 | ConvertFrom-Json; if ($x.annual_exact_day_audits_accepted -ne 16 -or $x.missing_exact_annual_day_audit_years.Count -ne 0 -or $x.full_2011_to_2026_as_of_source_key_coverage_audited -ne $true -or $x.ready_to_automatically_union_or_mirror -ne $false) { throw "历史账本状态或安全标志异常" }; Write-Host "全历史SAFE：$out"; $x.blockers | ConvertTo-Json -Depth 4

## 后续主线

先由16年精确差集结果决定全历史H5独有缺口所在的具体年份、日期与证券，再复用经认证的整日stager或新增按股票-日期键的保守私有分区，不修改购买源。2011之前原H5按pre2011管道；1min/5min分别独立核对时标与量额。只有私有Parquet主线内容完整并独立验证Hikyuu 2.8.1本地读回与精度策略后才考虑真正私有H5镜像。不得把统计审计完成误报成已实际合并，更不可修改原市场文件。
