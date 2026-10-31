# 2026-10-31：购买Parquet优先 + 全量22,274缺口候选 = 私有统一日线只读查询

## 已有真实Windows验收
全量候选物化实际成功：`reports/full-22274-private-candidates-60ae77774c30.json`。两个私有分区2016/2026包含1+22,273共22,274条（整日22,191、混合83），独立SHA/schema/全部键验证PASS：`reports/full-22274-private-candidates-verified-fe9266912917.json`。原购买历史日线仍只在`D:\stock\AllCycleAStockData\day`，从未复制进candidate-only分区。

## 本轮主线实现
新增 `tools/query-private-purchased-plus-22274-candidates.py`。对每次显式1–10只证券、同年≤31日查询：
1. 用既有 `verify-private-full-22274-gap-candidates.py::verify` 对22,274私有候选逐行核对**全部**2年份分区的SHA、Schema、A股股票日键唯一性、OHLCVA合法性及manifest。产生一份脱敏离线审核SAFE。**不再每只股票、每次查询执行耗时180s的全市场live H5/PQ键重审**。
2. 只从已验证候选年份分区按股票日键取需要的H5缺口候选（整日及混合保持独立来源），直接调用已有 `query-parquet-primary-readonly.py::query_bars` 查询购买Parquet原始float64，禁止启用本地行情缓存。根据已有的 `query-private-combined-day-22274-readonly.py::merge_stock_day_rows` 重复键保护严格合并。**任何购买+私有同股票日冲突均拒绝，而不是把购买原值覆盖/缩放。**
补充的预读取完整性门禁：独立候选全量核验成功后，在再次打开所选年份分区的Parquet之前，先重新核验该年份Parquet及manifest的磁盘SHA。若有人在两次读取间更改文件，直接以`ValueError`拒绝，不将损坏文件先交给PyArrow解析。新增测试确保损坏Parquet/manifest被拦截且解码器未被调用。
3. 调用前后对照：历史候选原始H5+购买2016/2026 stat指纹必须等于私有固定来源SHA；对实际查询的Parquet年份单独检查全部源文件清单和stat指纹前后不变；私有候选SAFE、不可变注册版必须未变。注意这是**源文件状态漂移告警**，不是原始市场数据重新逐键审计，也不是逐文件内容SHA认证。
4. 仅在内存返回原始六字段，reports仅输出按购买/整日/混合的聚合计数、文件SHA及安全标志。可快速执行后续研究只读查询；不是完整的物理购买主源+H5候选统一归档，不触及原购买/H5数据、活动指针及生产路由。

## 一直保持关闭
`candidate_source_units_certified=false`、`ready_for_production_query=false`、`ready_for_automatic_market_merge=false`、`full_unified_historical_market_database_materialized=false`。数据源复权、物理单位、成交额舍入仍未取得供应商正式证明。原购买Parquet负责历史真实性；候选仅来源于已明确SHA绑定的H5缺失日期。

## Windows第一步：新增15项 + 上轮11项 + 原批量12项测试
```powershell
cd D:\ChatGPT\AStockDataTools; git fetch origin; if ($LASTEXITCODE -ne 0) { throw "fetch失败" }; git switch feat/query-private-purchased-plus-22274-candidates-20261031; if ($LASTEXITCODE -ne 0) { throw "切换联合只读查询分支失败" }; git pull --ff-only origin feat/query-private-purchased-plus-22274-candidates-20261031; if ($LASTEXITCODE -ne 0) { throw "拉取失败" }; .\.venv\Scripts\python.exe -m py_compile H5ParquetReconciler\tools\query-private-purchased-plus-22274-candidates.py H5ParquetReconciler\tests\test_query_private_purchased_plus_22274_candidates.py; if ($LASTEXITCODE -ne 0) { throw "语法错误，禁止查询" }; $patterns=@("test_query_private_purchased_plus_22274_candidates.py","test_materialize_private_full_22274_gap_candidates.py","test_query_private_combined_day_22274_batch_readonly.py"); foreach ($p in $patterns) { .\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p $p -v; if ($LASTEXITCODE -ne 0) { throw "购买Parquet+私有候选安全测试失败：$p" } }; Write-Host "PASS：联合只读查询新增15项+全量候选11项+原来源12项安全回归"
```

## Windows第二步：已有两股窗口的实际私有联合日线只读验收
```powershell
cd D:\ChatGPT\AStockDataTools; $rid=[Guid]::NewGuid().ToString("N").Substring(0,12); $gate="H5ParquetReconciler\reports\private-union-full-candidates-recheck-$rid.json"; $out="H5ParquetReconciler\reports\private-union-purchased-first-query-$rid.json"; .\.venv\Scripts\python.exe H5ParquetReconciler\tools\query-private-purchased-plus-22274-candidates.py --source-root "D:\stock" --candidate-safe "H5ParquetReconciler\reports\full-22274-private-candidates-60ae77774c30.json" --symbols SH600000 SH600519 --from-date 2026-09-30 --to-date 2026-10-13 --candidate-recheck-out $gate --out $out --max-candidate-rows-per-symbol 30000000 --max-total-candidate-rows 30000000 --max-result-bars-per-symbol 100 --max-total-result-bars 1000 --read-only-view; if ($LASTEXITCODE -ne 0) { throw "购买Parquet优先+22,274候选私有视图查询失败，禁止生产启用" }; $r=Get-Content -LiteralPath $out -Raw -Encoding UTF8 | ConvertFrom-Json; if ($r.state -ne "purchased_first_private_22274_h5_gap_bounded_view_verified_not_activated" -or $r.private_source_version_sha256 -ne "e53e076f4eabf80a987d4e6e0bd7e4c239a8ea947f26a13cd455b66e39528b23" -or $r.requested_stock_count -ne 2 -or $r.returned_stockday_rows -ne 10 -or $r.purchased_parquet_rows -ne 2 -or $r.whole_h5_candidate_rows -ne 8 -or $r.mixed_h5_candidate_rows -ne 0 -or $r.purchased_parquet_first_no_duplicate_stockday -ne $true -or $r.private_candidate_all_22274_rows_sha_schema_keys_verified -ne $true -or $r.queried_purchased_year_file_count_and_stat_before_after_unchanged -ne $true -or $r.original_live_h5_keyset_not_rescanned -ne $true -or $r.source_stat_drift_detection_not_full_live_market_key_absence_audit -ne $true -or $r.candidate_source_units_certified -ne $false -or $r.ready_for_production_query -ne $false -or $r.ready_for_automatic_market_merge -ne $false -or $r.original_market_files_written -ne $false -or $r.purchased_parquet_replaced -ne $false -or $r.private_or_production_active_pointer_modified -ne $false -or $r.h5_mirror_created -ne $false) { throw "安全统计不符，禁止生产启用" }; Write-Host "PASS：购买2+私有完整日8+混合0=10，基于22,274候选的私有购买优先联合日线查询可用"; Write-Host "SAFE: $out"; Get-Content -LiteralPath $out -Encoding UTF8
```

**上传两个脱敏结果**：`reports/private-union-purchased-first-query-*.json` 与 `reports/private-union-full-candidates-recheck-*.json`。不要上传真实Parquet、H5、work目录或商业OHLCVA。通过后下一步按年份/股票建立私有索引与版本化查询加速，不再使用原始全市场180秒重审作为每次查询的前置条件；原始来源发生变化时应重新取得可信版本，而非绕过state gate。