# 2026-10-31：显式SHA版本22,274日线候选统一只读查询

## 实机前置
Windows 11/11合成测试和真实注册成功：不可变联合版本SHA e53e076f4eabf80a987d4e6e0bd7e4c239a8ea947f26a13cd455b66e39528b23。组成：购买Parquet为主；原H5缺口候选22,191条整日+83条混合股票日；2026-07-16的5条仍隔离。初始候选量纲未认证。

## 新入口
`tools/query-private-combined-day-22274-readonly.py` 显式注册版本SHA + 单证券 + 同一年1..31日日期窗口；每次读取前重新完整审计真实H5/购买Parquet的22,274条H5-only键与私有阶段SHA，拒绝过期来源/股票日冲突。依次读取购买Parquet、已认证来源的整日候选、混合日候选，严格按 `(symbol, trading_date)` 唯一键合并。当前任何未预期重叠均**fail closed**，不是默默用H5候选覆盖购买值。
OHLCVA仅作为本机Python内存结果，不打印源股票代码或单根商业OHLCVA；CLI输出两个聚合SAFE（一次现场重核SAFE + 一份查询摘要），不写任何原始行情或私有行情、不启用任何活动指针或生产路由，不创建H5镜像。暂不能替代正式生产查询。长窗口请分段查询。

## 测试与状态
15项纯合成测试（购买/整日/混合逐键合并、冲突/重复/畸形时间、量额几何、83键完整性、异常来源）已开发，**Windows与真实联合查询尚未验收**，此PR保持Draft。必须先15/15通过，再进行真实本地试点。

## PowerShell单行命令
1. 拉取分支并运行15项测试：
```powershell
cd D:\ChatGPT\AStockDataTools; git fetch origin; if ($LASTEXITCODE -ne 0) { throw "fetch失败" }; git switch feat/query-private-day-22274-readonly-20261031; if ($LASTEXITCODE -ne 0) { throw "切换查询分支失败" }; git pull --ff-only origin feat/query-private-day-22274-readonly-20261031; if ($LASTEXITCODE -ne 0) { throw "拉取分支失败" }; .\.venv\Scripts\python.exe -m py_compile H5ParquetReconciler\tools\query-private-combined-day-22274-readonly.py H5ParquetReconciler\tests\test_query_private_combined_day_22274_readonly.py; if ($LASTEXITCODE -ne 0) { throw "语法失败" }; .\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test_query_private_combined_day_22274_readonly.py" -v; if ($LASTEXITCODE -ne 0) { throw "15项研究只读查询测试失败，禁止实盘查询" }; Write-Host "PASS：22,274候选统一日线查询15项测试全部通过"
```
2. 仅在测试通过后，对此前已核实的SH600000 2026-09-30～10-13窗口进行有界只读真实试点。原先证据为购买1条＋整日候选4条；如果原始数据更新或复核不符，禁止继续。
```powershell
cd D:\ChatGPT\AStockDataTools; $rid=[Guid]::NewGuid().ToString("N").Substring(0,12); $fresh="H5ParquetReconciler\reports\private-day-22274-query-recheck-$rid.json"; $out="H5ParquetReconciler\reports\private-day-22274-query-smoke-$rid.json"; .\.venv\Scripts\python.exe H5ParquetReconciler\tools\query-private-combined-day-22274-readonly.py --source-root "D:\stock" --symbol SH600000 --from-date 2026-09-30 --to-date 2026-10-13 --version-sha256 "e53e076f4eabf80a987d4e6e0bd7e4c239a8ea947f26a13cd455b66e39528b23" --live-safe "H5ParquetReconciler\reports\live-mixed-day-83-keys-c8bf8ababde4.json" --private-keys "H5ParquetReconciler\work\unified_parquet\mixed_day_key_manifests\keys_c8bf8ababde4\keys.json" --history-ledger "H5ParquetReconciler\reports\history-day-ledger-full-91fae9458806.json" --source-2016 "H5ParquetReconciler\reports\historical-day-exact-2016-asof20261031-v1.json" --source-2026 "H5ParquetReconciler\reports\historical-day-exact-2026-asof20261031-v1.json" --mixed-plan "H5ParquetReconciler\reports\mixed-day-88-candidates-92274029928f.json" --fresh-recheck-out $fresh --out $out --max-candidate-rows 30000000 --max-result-bars 50 --max-overlay-source-rows 30000 --read-only; if ($LASTEXITCODE -ne 0) { throw "联合日线只读实盘试点失败，禁止后续读取" }; $r=Get-Content -LiteralPath $out -Raw -Encoding UTF8 | ConvertFrom-Json; if ($r.state -ne "explicit_private_combined_day_read_only_research_query" -or $r.private_combined_version_sha256 -ne "e53e076f4eabf80a987d4e6e0bd7e4c239a8ea947f26a13cd455b66e39528b23" -or $r.total_candidate_rows_in_registered_version -ne 22274 -or $r.matched_purchased_stockday_bars -ne 1 -or $r.matched_private_whole_day_stockday_bars -ne 4 -or $r.matched_private_mixed_day_stockday_bars -ne 0 -or $r.matching_stockday_bars -ne 5 -or $r.source_market_files_written -ne $false -or $r.purchased_parquet_replaced -ne $false -or $r.private_or_production_active_pointer_modified -ne $false -or $r.candidate_source_units_certified -ne $false -or $r.ready_for_production_query -ne $false -or $r.ready_for_automatic_market_merge -ne $false) { throw "联合日线实盘查询安全门禁或预期键数不满足" }; Write-Host "PASS：按SHA显式购买Parquet优先日线统一只读查询（1购买+4整日候选）；SAFE：$out"; Get-Content -LiteralPath $out -Encoding UTF8
```

成功后再开发/测试不暴露私有证券代码的83条混合候选覆盖率试点，而不是仅凭整日数据查询通过就宣布83个混合键均可消费。
全部SAFE均在模块reports目录，商业行情及私有键清单仍仅在本机work。