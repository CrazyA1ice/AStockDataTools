# 第23阶段：已验收2011—2026年私有DAY版本的SHA绑定只读查询探针

## 已完成的基础证据（不要重做历史物理年）

16年私有版本报告 `reports/private-2011-2026-all16-sha-bound-version-15fb74d42d0b.json`，SHA256：`bd64abcd0580cbed404c31bc2db3a05f9b2411880fa24d6bf3b14ecabcdb0c05`。Windows真实结果是：7/7项独立合成安全回归PASS，已绑定2011—2026全部16个私有年度物理分区，购买14,115,707日线+经验证H5补缺22,274日线，共14,137,981条。所有私有Parquet、SQL索引均沿用原物理副本，不重做、不覆盖。**这是未激活的数据版本，不是生产已上线。**

## 新增SHA绑定覆盖查询

`tools/query-private-2011-2026-all16-coverage-readonly.py`：只接受原SAFE文件**明确指定的64位SHA256**、仍声明未激活的16年完整manifest；要求股票代码为规范A股编码、时间窗不超过31日、最大候选rowgroup条数在预设预算内。按年度分区定位原私有Parquet，并在读取前检查对应私有manifest与SQLite的SHA、选中Parquet分区SHA、字段类型、footer行数。对符合日期范围的RowGroup只读取`ts/trading_date/symbol/value_source`四个索引/来源字段，**不会加载open/high/low/close/volume/amount任何真实OHLCVA**。对结果计数与相同年月日及股票代码范围下SQLite唯一键表`kind/COUNT(*)`做独立对照；重复键、来源类型异常、列缺失、时间窗口超界、数据改变一律拒绝。

输出是一个**仅汇总计数**的脱敏`H5ParquetReconciler/reports/*.json`，包含总匹配行数、按来源分类行数、扫描RowGroup数和耗时；不保存股票代码、确切开始结束日期、任何OHLCVA或单行数据。请注意该工具用于私有版本完整性与查询准备检查，不是以此命令开放生产查询，也不替代将来带显式本地授权的实际OHLCVA检索API。它不打开原购买QDC/H5，不写Parquet/SQLite，不启用active pointer、H5镜像或正式生产路径。

新增`tests/test_query_private_2011_2026_all16_coverage_readonly.py`合成8项：2016年购买与H5混合查询、2025—2026跨年查询、版本SHA篡改、年度Manifest SHA篡改、Parquet字节篡改、SQLite键和Parquet不一致、预算与31日窗口限制、非法年份/股票代码拒绝。

## 下一步：Windows先跑8项合成测试，通过才运行真实SHA绑定的跨年覆盖只读查询（PowerShell单行）

```powershell
cd D:\ChatGPT\AStockDataTools; git fetch origin; if ($LASTEXITCODE -ne 0) { throw "Git fetch失败" }; git switch feat/private-2011-2025-purchased-physical-year-20261031; if ($LASTEXITCODE -ne 0) { throw "分支切换失败" }; git pull --ff-only origin feat/private-2011-2025-purchased-physical-year-20261031; if ($LASTEXITCODE -ne 0) { throw "更新失败" }; .\.venv\Scripts\python.exe -m py_compile H5ParquetReconciler\tools\query-private-2011-2026-all16-coverage-readonly.py H5ParquetReconciler\tests\test_query_private_2011_2026_all16_coverage_readonly.py; if ($LASTEXITCODE -ne 0) { throw "16年只读覆盖查询语法失败" }; .\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test_query_private_2011_2026_all16_coverage_readonly.py" -v; if ($LASTEXITCODE -ne 0) { throw "新8项只读覆盖查询测试失败，禁止真实查询" }; $v="H5ParquetReconciler\reports\private-2011-2026-all16-sha-bound-version-15fb74d42d0b.json"; $sha="bd64abcd0580cbed404c31bc2db3a05f9b2411880fa24d6bf3b14ecabcdb0c05"; if (-not (Test-Path -LiteralPath $v -PathType Leaf) -or (Get-FileHash -LiteralPath $v -Algorithm SHA256).Hash.ToLowerInvariant() -ne $sha) { throw "16年私有版本SHA不匹配" }; $rid=[Guid]::NewGuid().ToString("N").Substring(0,12); $out="H5ParquetReconciler\reports\private-all16-coverage-smoke-$rid.json"; .\.venv\Scripts\python.exe H5ParquetReconciler\tools\query-private-2011-2026-all16-coverage-readonly.py --version-safe $v --version-sha256 $sha --symbol SH600000 --start 2025-12-29 --end 2026-01-09 --max-candidate-rows 3000000 --out $out --private-coverage-only; if ($LASTEXITCODE -ne 0) { throw "真实16年SHA绑定的跨年度只读键查询失败，没有生成可用查询结果" }; $r=Get-Content -LiteralPath $out -Raw -Encoding UTF8 | ConvertFrom-Json; if ($r.status -ne "private_all16_bounded_day_coverage_keys_and_provenance_verified_only" -or $r.source_all16_private_version_sha256 -ne $sha -or $r.private_query_symbol_and_exact_dates_not_exported -ne $true -or $r.all_original_licensed_OHLCVA_values_read -ne $false -or $r.original_market_source_opened -ne $false -or $r.ready_for_production_query -ne $false -or $r.ready_for_automatic_market_merge -ne $false -or $r.ready_for_h5_mirror -ne $false -or $r.matched_stockday_rows -ne $r.sqlite_rows_matched) { throw "真实跨年覆盖SAFE不符合只读安全和数量一致性要求" }; Write-Host "PASS：已验收16年SHA版本上的2025—2026跨年股票日只读覆盖查询"; Write-Host "匹配行数：$($r.matched_stockday_rows)"; Write-Host "SAFE：$out"; Get-Content -LiteralPath $out -Encoding UTF8
```

当前测试尚未在用户Windows环境运行。若未通过不得执行真实查询；失败时原16年私有物理年全部保持不变，不在GitHub或聊天中粘贴任何licensed购买行情。
