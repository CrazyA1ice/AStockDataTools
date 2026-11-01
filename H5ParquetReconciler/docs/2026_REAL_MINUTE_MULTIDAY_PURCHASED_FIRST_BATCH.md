# 2026-11-01：按日期批量完成真正购买优先1min/5min私有Parquet

## 不重做的已验收工作

日线已于本机完成2011—2026年**14,137,981条**统一私有Parquet→原生Hikyuu三市场H5写出及完整整数回读。2026-10-13的1min **1,331,760条**、5min **266,352条**（各5,549个H5独有完整股票日）已经顺利完成：①原H5→独立私有Parquet（SAFE：`reports/real-minute-h5-only-private-parquet-20261013-b03f33b6ce64.json`）；②此Parquet→六个原生PyTables H5（SAFE：`reports/private-minute-native-h5-20261013-2ab658e3b184.json`）；③**购买优先的可消费统一1min/5min私有物理Parquet**（SAFE：`reports/real-unified-minute-parquet-20261013-9b354b363eed.json`）。当日购买Parquet记录为0，测试2/2通过，159万条全行回读正常；每周期13个原生H5时间格异常的股票日仍隔离。以上均已完成，**不能再次为测速或索引重建**。

## 本轮新增：一次运行多交易日的真实文件管线

`tools/run-real-minute-h5-gap-unified-range.py`直接串接此前已验过的两个**真实写入器**：

- `write-h5-only-complete-minute-stockdays-to-private-parquet.py`：只读当日购买Parquet键，购买股票日优先，只将H5中符合1min(239/240)/5min(48)完整网格的**Parquet独有缺日**写到私有Parquet；保留H5所有原生整数。
- `write-purchased-first-unified-minute-day-parquet.py`：把该日真实购买1min、5min的所有有效字段（包括供应商额外字段）与H5补缺真正写到**同一份新物理Parquet**，逐条全字段写后回读；既不覆盖原购买分区，也不触碰原Hikyuu H5。

命令按明确日期窗口处理，单批最多15个候选工作日；每个成功完成的日期留两个独立SAFE（H5补缺、安全统一）。如果有一个日子异常中止，**已经完成的日期不会丢失**：用相同12位批次ID重新执行，校验SHA后跳过已完成日期；如果某日只完成一半，拒绝误复用并要求检查残留私有目录（改用新run-id可重新建立该失败日的数据，不影响其他已完成结果）。日期不代表交易所日历，默认跳过周末但不能自动识别假日；真实H5交易日为空时可能产生0行私有分区。源数据或H5网格异常按原约定隔离/停止，不会悄悄丢失数据。

**本轮首个真实窗口选2026-09-28至2026-09-30**（3个候选交易日）：不同于10月13日纯H5补缺，9月位于已购买Parquet数据历史范围，可核实**实际购买行+H5缺口行共存的数量**。不要先假定数据一定重叠；真实报告若购买=0，应明确当前窗口没有证据证明购买/H5混合。脚本会生成`work/unified_parquet/minute_gap_staging/<日ID>/...`、`work/unified_parquet/minute_complete_day/minute_<日ID>/...`下的真实Parquet以及`reports/minute-batch-{stage,unified}-<日期>-<日ID>.json`。总报告只包含按日1min/5min的购买/H5行数、隔离原因数量、各文件SHA；**不包含原始证券、交易时间或OHLCVA**。时间端点换算依旧是候选，未认证。

## Windows单行PowerShell：必要的2项批量测试→真实3日两周期补差及物理合并

```powershell
cd D:\ChatGPT\AStockDataTools; git fetch origin; if ($LASTEXITCODE -ne 0) { throw "Git fetch失败" }; git switch feat/private-2011-2025-purchased-physical-year-20261031; if ($LASTEXITCODE -ne 0) { throw "分支切换失败" }; git pull --ff-only origin feat/private-2011-2025-purchased-physical-year-20261031; if ($LASTEXITCODE -ne 0) { throw "更新失败" }; .\.venv\Scripts\python.exe -m py_compile H5ParquetReconciler\tools\run-real-minute-h5-gap-unified-range.py H5ParquetReconciler\tests\test_run_real_minute_h5_gap_unified_range.py; if ($LASTEXITCODE -ne 0) { throw "分钟批量程序语法失败" }; .\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test_run_real_minute_h5_gap_unified_range.py" -v; if ($LASTEXITCODE -ne 0) { throw "2项跨源写盘批量测试失败" }; $id=[Guid]::NewGuid().ToString("N").Substring(0,12); $out="H5ParquetReconciler\reports\real-minute-batch-purchased-h5-20260928-30-$id.json"; Write-Host "本次批量ID：$id（若完成部分交易日后失败，请使用同一ID恢复已验收日期）"; .\.venv\Scripts\python.exe H5ParquetReconciler\tools\run-real-minute-h5-gap-unified-range.py --root "D:\stock" --from-date 2026-09-28 --to-date 2026-09-30 --run-id $id --max-days 3 --max-purchased-key-rows 30000000 --max-h5-rows 2500000 --max-unified-rows 4500000 --out $out --write-private-minute-range; if ($LASTEXITCODE -ne 0) { throw "真实3日分钟Parquet批量未全部完成；已完成日有单独脱敏SAFE可安全恢复，原购买/H5未修改" }; $r=Get-Content -LiteralPath $out -Raw -Encoding UTF8 | ConvertFrom-Json; if ($r.status -ne "bounded_two_period_actual_minute_days_physical_parquet_completed" -or $r.batch_days -ne 3 -or $r.original_purchased_parquet_or_hikyuu_h5_modified -ne $false -or $r.h5_minute_timestamp_alignment_vendor_certified -ne $false -or $r.all_historical_minute_days_completed -ne $false) { throw "3日分钟写盘批量SAFE不合格" }; Write-Host "PASS：9月28—30日共3个交易日、1min+5min实际补缺及购买优先统一Parquet全部写出"; Write-Host "1min：购买=$($r.aggregated_source_rows.'1min'.purchased_rows)，H5补缺=$($r.aggregated_source_rows.'1min'.h5_gap_rows)，合计=$($r.aggregated_source_rows.'1min'.physical_unified_rows)"; Write-Host "5min：购买=$($r.aggregated_source_rows.'5min'.purchased_rows)，H5补缺=$($r.aggregated_source_rows.'5min'.h5_gap_rows)，合计=$($r.aggregated_source_rows.'5min'.physical_unified_rows)"; Write-Host "脱敏总报告：$out"; Get-Content -LiteralPath $out -Encoding UTF8
```

**下一步**：首轮3日PASS后，直接将范围按周/月滚动扩展至有H5源覆盖的2025/2026全部日期，重点完成**有购买Parquet源的股票日**和H5独有的完整股票日；再将新增统一Parquet流式反向生成**包含购买数据+H5补缺**的完整Hikyuu原生分钟H5，按周期校验精度差异，最后接通达信盘后增量。处理混合股票日中的细粒度缺分钟与13异常时间格股票日时须单独说明未覆盖，不得宣称全历史零差异。