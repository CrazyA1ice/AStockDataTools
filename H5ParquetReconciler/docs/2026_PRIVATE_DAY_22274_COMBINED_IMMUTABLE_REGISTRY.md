# 2026-10-31：22,274条完整缺日＋混合股票日候选的不可变私有逻辑版本登记

## 前置实机验收

Windows 14/14（PR#189）和9/9（PR#190）合成测试通过；83条私有Parquet已完成真实暂存；22,191＋83＝22,274条真实只读联合校验通过。预检SAFE：reports/private-day-22274-readonly-plan-56f29229409b.json。
整日候选不可变版本SHA：46bd847de3d00c0f48ff50830fa8688547198c6db1a3cf3b10eb7d2261770c03；混合候选分区SHA：bd8f00dc78bce7877b1049972ea9a015ec0cefe942411989e3a4edd9d3068333。

## 新增工具

`tools/register-private-combined-day-22274-version.py` 独立注册新逻辑版本，不复制商业行情：读取并强校验已验收的联合只读SAFE，**重新跑完整现场H5/购买Parquet联合预检**，比较前后整个SAFE内容一致，双重SHA绑定；使用Canonical JSON正文SHA256作为版本ID。在`work/unified_parquet/combined_day_versions/<sha>.json`只新建或逐字校验不可变版本清单。
正文仅保存整日overlay SHA、混合stage SAFE SHA/Parquet SHA/manifest SHA、初次与新实时SAFE的SHA、来源状态指纹和计数/安全标志。**不写入原始H5/购买Parquet，不触碰任何已有活动指针，不启用查询、不创建H5镜像，也不认证价格、量和额的物理单位。**
注册时新生成两份脱敏reports/ SAFE：一份为再次独立现场验证，一份为新版本登记摘要；用户只需要回传登记摘要。
下一独立阶段才实现按 `(股票,交易日)` 做购买Parquet优先的联合只读查询；本阶段不能被称为已有正式合并数据文件，也不能生产启用。

## 新增测试/验收状态

11项纯合成守卫测试：注册成功/不可变读取、总数变动、SAFE伪造生产启用或量纲认证、mixed SAFE修改、真实重新校验不一致、并发锁、版本篡改、引用SAFE篡改、输出覆盖、重复报告路径、私有目录符号链接。当前尚未在用户Windows真实环境运行；Draft阶段不得声称已验收。

## Windows单行PowerShell

1. 拉分支并运行11项合成测试：
```powershell
cd D:\ChatGPT\AStockDataTools; git fetch origin; if ($LASTEXITCODE -ne 0) { throw "fetch失败" }; git switch feat/register-private-day-22274-version-20261031; if ($LASTEXITCODE -ne 0) { throw "切换版本注册分支失败" }; git pull --ff-only origin feat/register-private-day-22274-version-20261031; if ($LASTEXITCODE -ne 0) { throw "拉取失败" }; .\.venv\Scripts\python.exe -m py_compile H5ParquetReconciler\tools\register-private-combined-day-22274-version.py H5ParquetReconciler\tests\test_register_private_combined_day_22274_version.py; if ($LASTEXITCODE -ne 0) { throw "语法校验失败" }; .\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test_register_private_combined_day_22274_version.py" -v; if ($LASTEXITCODE -ne 0) { throw "11项新合成测试失败，禁止真实版本注册" }; Write-Host "PASS：22,274不可变私有版本11项合成测试通过"
```

2. 仅当11/11通过后显式准备不可变私有版本：
```powershell
cd D:\ChatGPT\AStockDataTools; $rid=[Guid]::NewGuid().ToString("N").Substring(0,12); $fresh="H5ParquetReconciler\reports\private-day-22274-registry-recheck-$rid.json"; $out="H5ParquetReconciler\reports\private-day-22274-registry-complete-$rid.json"; .\.venv\Scripts\python.exe H5ParquetReconciler\tools\register-private-combined-day-22274-version.py --source-root "D:\stock" --whole-day-version-sha256 "46bd847de3d00c0f48ff50830fa8688547198c6db1a3cf3b10eb7d2261770c03" --mixed-stage-safe "H5ParquetReconciler\reports\stage-mixed-day-83-complete-6ad057daca7c.json" --live-safe "H5ParquetReconciler\reports\live-mixed-day-83-keys-c8bf8ababde4.json" --private-keys "H5ParquetReconciler\work\unified_parquet\mixed_day_key_manifests\keys_c8bf8ababde4\keys.json" --history-ledger "H5ParquetReconciler\reports\history-day-ledger-full-91fae9458806.json" --source-2016 "H5ParquetReconciler\reports\historical-day-exact-2016-asof20261031-v1.json" --source-2026 "H5ParquetReconciler\reports\historical-day-exact-2026-asof20261031-v1.json" --mixed-plan "H5ParquetReconciler\reports\mixed-day-88-candidates-92274029928f.json" --prior-union-safe "H5ParquetReconciler\reports\private-day-22274-readonly-plan-56f29229409b.json" --fresh-recheck-out $fresh --out $out --original-sources-read-only; if ($LASTEXITCODE -ne 0) { throw "新私有统一逻辑版本注册失败" }; $r=Get-Content -LiteralPath $out -Raw -Encoding UTF8 | ConvertFrom-Json; if ($r.state -ne "prepared_private_combined_day_version_not_active" -or $r.candidate_total_new_stockday_rows -ne 22274 -or $r.whole_day_candidate_rows -ne 22191 -or $r.mixed_stockday_candidate_rows -ne 83 -or $r.new_private_combined_version_created -ne $true -or $r.private_or_production_active_pointer_modified -ne $false -or $r.source_market_files_written -ne $false -or $r.purchased_parquet_replaced -ne $false -or $r.h5_mirror_created -ne $false -or $r.candidate_source_units_certified -ne $false -or $r.ready_for_production_query -ne $false -or $r.ready_for_automatic_market_merge -ne $false -or $r.version_sha256 -notmatch '^[0-9a-f]{64}$') { throw "新私有统一逻辑版本SAFE门禁失败" }; $version="H5ParquetReconciler\work\unified_parquet\combined_day_versions\$($r.version_sha256).json"; if (-not (Test-Path -LiteralPath $version)) { throw "不可变版本文件不存在" }; Write-Host "PASS：22,274条候选不可变私有逻辑版本已准备，未启用，版本SHA=$($r.version_sha256)"; Write-Host "SAFE：$out"; Get-Content -LiteralPath $out -Encoding UTF8
```

不要上传work下Parquet、私有stock-day键或商业OHLCVA。仅回传reports目录中新生成的注册摘要SAFE。失败时禁止绕过源SHA或切换活动指针。