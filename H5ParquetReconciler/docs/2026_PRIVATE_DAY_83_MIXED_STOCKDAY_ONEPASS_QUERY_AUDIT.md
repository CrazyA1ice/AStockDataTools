# 2026-10-31：单次真实来源核验下的全部83个混合股票日键查询验收

## 前置实测

PR #192 Windows已通过15/15合成测试；首次真实研究只读查询SH600000、2026-09-30至10-13返回购买Parquet=1、整日候选=4、混合候选=0，总计5，SAFE `reports/private-day-22274-query-smoke-64c171da174c.json`。本次实际查询耗时398.147001秒，不能把83键逐一执行完整全市场现场核验当作常规验收方法。

## 新工具

`tools/audit-private-combined-83-mixed-query-once-readonly.py`：要求显式完整SHA版本，执行**一次** `PRE.verify`，该既有函数真实扫描原始H5与购买Parquet、验证83个精确缺失股票日键与候选数值，及四个完整缺日。然后读取模块work下已SHA绑定的83行私有stage，在内存中逐键调用现有统一查询的`selected_mixed_rows`与`merge_stock_day_rows`，以证明83/83个混合键均能选中精确候选、唯一且符合OHLCVA几何规则。禁止私有83键与整日缺口日期重合，继续排除2026-07-16的5条隔离记录。
**已通过的实时购买Parquet键缺失扫描保证这83个候选不会覆盖购买同键；本工具并未为每个股票额外读取购买Parquet OHLCVA，不能将它误称为对83个股票分别执行了83次完整查询。**
新SAFE仅记录83、2016=1/2026=82、指纹与安全标志，不包含证券代码或商业OHLCVA；输出在模块reports目录。原H5、购买Parquet、任何active指针与镜像均不写入。量纲仍未认证，不能用于生产。

## 合成测试

`tests/test_audit_private_combined_83_mixed_query_once_readonly.py`新增11项虚构数据测试：83键成功、原stage缺行、manifest缺键、重复、错误source、价格几何异常、错日期、隔离日期、整日冲突、非法H5日期编码、2016/2026分布篡改。当前仍需Windows11/11验收，尚未执行真实83键现场读取。

## Windows PowerShell，均为单行

1. 先拉新分支，11项合成测试：
```powershell
cd D:\ChatGPT\AStockDataTools; git fetch origin; if ($LASTEXITCODE -ne 0) { throw "fetch失败" }; git switch feat/audit-private-day-83-mixed-query-once-20261031; if ($LASTEXITCODE -ne 0) { throw "切换83键实盘验收分支失败" }; git pull --ff-only origin feat/audit-private-day-83-mixed-query-once-20261031; if ($LASTEXITCODE -ne 0) { throw "拉取失败" }; .\.venv\Scripts\python.exe -m py_compile H5ParquetReconciler\tools\audit-private-combined-83-mixed-query-once-readonly.py H5ParquetReconciler\tests\test_audit_private_combined_83_mixed_query_once_readonly.py; if ($LASTEXITCODE -ne 0) { throw "语法检查失败" }; .\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test_audit_private_combined_83_mixed_query_once_readonly.py" -v; if ($LASTEXITCODE -ne 0) { throw "11项83键纯合成测试失败，禁止真实扫描" }; Write-Host "PASS：83个混合日股票日键的11项合成测试全部通过"
```
2. 仅11/11通过时，运行一次完整现场扫描并验收83/83个真实候选键：
```powershell
cd D:\ChatGPT\AStockDataTools; $rid=[Guid]::NewGuid().ToString("N").Substring(0,12); $fresh="H5ParquetReconciler\reports\private-day-83-mixed-readonce-recheck-$rid.json"; $out="H5ParquetReconciler\reports\private-day-83-mixed-readonce-complete-$rid.json"; .\.venv\Scripts\python.exe H5ParquetReconciler\tools\audit-private-combined-83-mixed-query-once-readonly.py --source-root "D:\stock" --version-sha256 "e53e076f4eabf80a987d4e6e0bd7e4c239a8ea947f26a13cd455b66e39528b23" --live-safe "H5ParquetReconciler\reports\live-mixed-day-83-keys-c8bf8ababde4.json" --private-keys "H5ParquetReconciler\work\unified_parquet\mixed_day_key_manifests\keys_c8bf8ababde4\keys.json" --history-ledger "H5ParquetReconciler\reports\history-day-ledger-full-91fae9458806.json" --source-2016 "H5ParquetReconciler\reports\historical-day-exact-2016-asof20261031-v1.json" --source-2026 "H5ParquetReconciler\reports\historical-day-exact-2026-asof20261031-v1.json" --mixed-plan "H5ParquetReconciler\reports\mixed-day-88-candidates-92274029928f.json" --fresh-recheck-out $fresh --out $out --read-only; if ($LASTEXITCODE -ne 0) { throw "83混合日股票日键真实批量读取审计失败" }; $r=Get-Content -LiteralPath $out -Raw -Encoding UTF8 | ConvertFrom-Json; if ($r.state -ne "all83_mixed_stockday_queries_verified_one_live_source_pass" -or $r.private_combined_version_sha256 -ne "e53e076f4eabf80a987d4e6e0bd7e4c239a8ea947f26a13cd455b66e39528b23" -or $r.live_full_source_audit_invocations -ne 1 -or $r.mixed_candidate_keys_verified -ne 83 -or $r.mixed_candidate_rows_returned_in_memory -ne 83 -or $r.mixed_candidate_year_counts.'2016' -ne 1 -or $r.mixed_candidate_year_counts.'2026' -ne 82 -or $r.purchased_exact_stockday_absence_checked_live -ne $true -or $r.purchased_ohlcva_requeried_for_each_candidate -ne $false -or $r.candidate_total_new_stockday_rows_in_version -ne 22274 -or $r.quarantined_2026_07_16_stockday_bars_not_included -ne 5 -or $r.private_or_production_active_pointer_modified -ne $false -or $r.source_market_files_written -ne $false -or $r.purchased_parquet_replaced -ne $false -or $r.h5_mirror_created -ne $false -or $r.candidate_source_units_certified -ne $false -or $r.ready_for_production_query -ne $false -or $r.ready_for_automatic_market_merge -ne $false -or $r.no_stock_symbols_or_ohlcva_in_safe -ne $true) { throw "83混合日批量查询SAFE安全门禁失败" }; Write-Host "PASS：83个真实混合股票日键已通过单轮现场键校验及候选读取；脱敏SAFE：$out"; Get-Content -LiteralPath $out -Encoding UTF8
```

只需返回脱敏SAFE `reports/private-day-83-mixed-readonce-complete-*.json` 或终端输出。不要上传work内商业Parquet或private key manifest。