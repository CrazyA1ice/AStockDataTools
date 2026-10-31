# 2026-10-31：22,191整日 + 83混合日 H5-only私有Parquet只读联合预检

## 前置已验收事实

PR #189已通过Windows 14/14测试、真实83-key PLAN及83条隔离STAGE；报告：reports/stage-mixed-day-83-complete-6ad057daca7c.json。
私有混合Parquet SHA256：bd8f00dc78bce7877b1049972ea9a015ec0cefe942411989e3a4edd9d3068333。2016年1条、2026年82条；2026-07-16的5条继续隔离。
整日私有候选为2026-10-08、09、12、13四个购买Parquet整日缺口，总计22,191条。
**22,274只是两组独立私有候选数量之和：不是已经合并的文件、不是生产主库行数、不是认证无损量纲。**

## 此轮脚本

tools/verify-private-combined-day-22274-readonly.py：引用现有不可变整日overlay版本SHA和独立83-key私有候选分区；逐级验 SHA/manifest/字段/行数，重读原始H5/购买Parquet精确键集合，验证整日与混合日期不交叉，逐字段验证83条OHLCVA与原H5候选归一化值一致；四个完整缺日重新走既有实时验证。检查前后文件指纹。
只生成模块reports中的新脱敏SAFE，**不建立新的联合版本、不自动启用、不触碰活动指针、不修改原H5和购买Parquet、不创建H5镜像**。成交量、金额及价格候选转换尚未认证。
此预检成功后才能进一步开发不可变联合逻辑版本及购买Parquet优先的查询接口。不能直接将83个混合股日当作购买Parquet整日缺失处理。

## 测试

新增9项虚构/模拟守卫测试：禁止覆盖原SAFE、禁止目录逃逸和软链接、拒绝PLAN假冒真实暂存、严格总数、拒绝混合/整日日期碰撞、拒绝OHLCVA不匹配与源变化。隔离模拟环境9/9已通过；用户Windows和真实源尚未执行，因此PR保持Draft。

## Windows PowerShell：每条命令单行

1. 先拉取分支并运行9项合成测试：
```powershell
cd D:\ChatGPT\AStockDataTools; git fetch origin; if ($LASTEXITCODE -ne 0) { throw "fetch失败" }; git switch feat/private-day-22274-union-preflight-20261031; if ($LASTEXITCODE -ne 0) { throw "切换分支失败" }; git pull --ff-only origin feat/private-day-22274-union-preflight-20261031; if ($LASTEXITCODE -ne 0) { throw "拉取分支失败" }; .\.venv\Scripts\python.exe -m py_compile H5ParquetReconciler\tools\verify-private-combined-day-22274-readonly.py H5ParquetReconciler\tests\test_verify_private_combined_day_22274_readonly.py; if ($LASTEXITCODE -ne 0) { throw "语法失败" }; .\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test_verify_private_combined_day_22274_readonly.py" -v; if ($LASTEXITCODE -ne 0) { throw "9项合成测试失败，禁止真实联合预检" }; Write-Host "PASS：联合候选只读预检9项合成测试通过"
```

2. 仅当测试全部通过，再运行实时只读联合验证。整日版本SHA沿用此前预备版本46bd847...；若本机版本不在，必须失败，不能忽略。
```powershell
cd D:\ChatGPT\AStockDataTools; $rid=[Guid]::NewGuid().ToString("N").Substring(0,12); $out="H5ParquetReconciler\reports\private-day-22274-readonly-plan-$rid.json"; .\.venv\Scripts\python.exe H5ParquetReconciler\tools\verify-private-combined-day-22274-readonly.py --source-root "D:\stock" --whole-day-version-sha256 "46bd847de3d00c0f48ff50830fa8688547198c6db1a3cf3b10eb7d2261770c03" --mixed-stage-safe "H5ParquetReconciler\reports\stage-mixed-day-83-complete-6ad057daca7c.json" --live-safe "H5ParquetReconciler\reports\live-mixed-day-83-keys-c8bf8ababde4.json" --private-keys "H5ParquetReconciler\work\unified_parquet\mixed_day_key_manifests\keys_c8bf8ababde4\keys.json" --history-ledger "H5ParquetReconciler\reports\history-day-ledger-full-91fae9458806.json" --source-2016 "H5ParquetReconciler\reports\historical-day-exact-2016-asof20261031-v1.json" --source-2026 "H5ParquetReconciler\reports\historical-day-exact-2026-asof20261031-v1.json" --mixed-plan "H5ParquetReconciler\reports\mixed-day-88-candidates-92274029928f.json" --out $out --original-sources-read-only; if ($LASTEXITCODE -ne 0) { throw "真实22,274候选联合只读验证失败" }; $r=Get-Content -LiteralPath $out -Raw -Encoding UTF8 | ConvertFrom-Json; if ($r.state -ne "read_only_union_preflight_passed_not_promoted" -or $r.whole_day_candidate_rows -ne 22191 -or $r.mixed_stockday_candidate_rows -ne 83 -or $r.candidate_total_new_stockday_rows -ne 22274 -or $r.new_private_combined_version_created -ne $false -or $r.source_market_files_written -ne $false -or $r.purchased_parquet_replaced -ne $false -or $r.private_or_production_active_pointer_modified -ne $false -or $r.candidate_source_units_certified -ne $false -or $r.ready_for_automatic_market_merge -ne $false) { throw "联合预检SAFE安全门禁失败" }; Write-Host "PASS：22,274候选联合只读验证通过；SAFE：$out"; Get-Content -LiteralPath $out -Encoding UTF8
```

不要上传work下商业行情或私有日键manifest；只回传reports新生成的脱敏SAFE。