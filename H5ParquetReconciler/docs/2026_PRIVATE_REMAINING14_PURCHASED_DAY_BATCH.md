# 第21阶段：剩余14个购买历史年度SHA预检及私有分区独立验收

## 实际已固定的前序证据

2026-10-31已完成两个2016私有历史YEAR旧目录的完整独立审计，两个都为**655,448条购买日线+1条2016 H5混合候选=655,449条**，Parquet/SQLite/原始购买扩展字段逐字节源副本及逐行float64指纹完全一致。选择其中一个已验收目录作为本阶段仅用于比对的**锚点**，不将其设置为active，也不删除另一个。

- 2016选定锚点：`reports/recovered-2016-physical-fbae90cd49ec.json` 和 `reports/recovered-2016-independent-fbae90cd49ec.json`，其私有目录`work/unified_parquet/physical_years/physical_2016_999875510b81`。
- 2026独立锚点：`reports/physical-2026-purchased-plus-h5-f6d4a6e87887.json` 和 `reports/physical-2026-independent-full-audit-318b43aa9daf.json`，2026购买1,010,350条、H5补缺22,273条、共**1,032,623条**，10个物理分区。
- 购买QDC总24文件共**14,115,707条**，其中2016年655,448条，2026年9个月1,010,350条，因此其余2011—2015与2017—2025总**12,449,909条**。此计算仅用于当前已SHA绑定的QDC购买批次，不声称历史市场全覆盖。
- H5来源由同一`full-22274-private-candidates-60ae77774c30.json`绑定：2016年仅1条、2026年22,273条，其他历史年0条。本阶段不将全部H5替换到购买原件，也不宣称源H5金额单位/金额舍入语义已认证。

## 新工具设计

`tools/stage-remaining14-private-purchased-years.py`支持两个强制区分的模式：

1. `--preflight-only`：只检查14份原始`day/<year>.parquet`的QDC供应商原件完整SHA、真实footer行数、8个必要的Arrow字段及原始物理类型，允许至多1个未知额外字段（物化时将原始完整Parquet逐字节副本SHA绑定保存在私有work），另外将已有2016与2026两套独立审计SAFE及原始H5候选快照签名绑定。只写模块`reports`中脱敏预检SAFE，**绝不生成任何新物理Parquet、SQLite、active pointer、H5 mirror**。14年预检预期原购买12,449,909条，任何年份SHA、页脚、行数、类型、超1未知列或锚点失败都拒绝。
2. `--materialize-and-audit`：**必须**携带实际已通过预检SAFE及其SHA256，由命令行显式指定随机12位run-id；在开始前重验全部14个购买原件的SHA/footer及两个已验锚点，检查新私有文件名不与旧作业冲突，检查可用磁盘满足保守预算。之后仅对14个剩余年份逐年运行已测`M.materialize`与`I.verify`，每年独立SAFE和审计输出都直接写在`reports`，私人Parquet/SQLite/完整未知字段原件副本都写在`work/unified_parquet/physical_years/physical_<year>_<batch-id>`。任何一年失败立刻停止，旧年份已有成功私有文件保留，**没有总批次成功SAFE**。所有14年独立验收通过后才发布`remaining14-<id>-independent-batch.json`。

无生产写入、无2016或2026重构、无官方供应商超出SHA的真实性认证、无H5镜像、无原始市场数据/股票代码/价格/字段名导出。即使14年全部PASS，仍须单独开展16年完整私人数据版本manifest/2011-2026跨年一致性审计，不自动激活生产。失败不得直接在相同batch-id内重新跑。

## Windows第一步：新增8项合成测试＋14年真实来源SHA/Schema只读预检（单行PowerShell）

```powershell
cd D:\ChatGPT\AStockDataTools; git fetch origin; if ($LASTEXITCODE -ne 0) { throw "fetch失败" }; git switch feat/private-2011-2025-purchased-physical-year-20261031; if ($LASTEXITCODE -ne 0) { throw "分支切换失败" }; git pull --ff-only origin feat/private-2011-2025-purchased-physical-year-20261031; if ($LASTEXITCODE -ne 0) { throw "拉取失败" }; .\.venv\Scripts\python.exe -m py_compile H5ParquetReconciler\tools\stage-remaining14-private-purchased-years.py H5ParquetReconciler\tests\test_stage_remaining14_private_purchased_years.py; if ($LASTEXITCODE -ne 0) { throw "14年批次脚本语法错误" }; .\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test_stage_remaining14_private_purchased_years.py" -v; if ($LASTEXITCODE -ne 0) { throw "14年只读预检和批处理8项合成测试失败" }; $rid=[Guid]::NewGuid().ToString("N").Substring(0,12); $pre="H5ParquetReconciler\reports\remaining14-source-preflight-$rid.json"; .\.venv\Scripts\python.exe H5ParquetReconciler\tools\stage-remaining14-private-purchased-years.py --preflight-only --purchased-root "D:\stock\AllCycleAStockData" --candidate-safe "H5ParquetReconciler\reports\full-22274-private-candidates-60ae77774c30.json" --readme-sha256 "4c4e7c2081390407a06fecbe8b2693bddc9ce76191c44381b6be0e7781a2f023" --manifest-sha256 "24f099faeb0a2e810f46691b81b2a357cc5aa42cd7ccd800dae6e19db16b06eb" --accepted-2016-safe "H5ParquetReconciler\reports\recovered-2016-physical-fbae90cd49ec.json" --accepted-2016-audit "H5ParquetReconciler\reports\recovered-2016-independent-fbae90cd49ec.json" --accepted-2026-safe "H5ParquetReconciler\reports\physical-2026-purchased-plus-h5-f6d4a6e87887.json" --accepted-2026-audit "H5ParquetReconciler\reports\physical-2026-independent-full-audit-318b43aa9daf.json" --out $pre; if ($LASTEXITCODE -ne 0) { throw "剩余14个购买年原件SHA或2016/2026锚点只读预检失败，禁止批量物化" }; $r=Get-Content -LiteralPath $pre -Raw -Encoding UTF8 | ConvertFrom-Json; if ($r.status -ne "remaining_14_purchased_years_source_sha_and_arrow_footer_verified_not_materialized" -or $r.historical_year_files_verified -ne 14 -or $r.purchased_original_rows -ne 12449909 -or $r.original_market_files_written -ne $false -or $r.physical_parquet_or_sqlite_created -ne $false -or $r.ready_for_h5_mirror -ne $false -or $r.ready_for_automatic_market_merge -ne $false) { throw "14年脱敏预检SAFE数据或安全边界不符" }; Write-Host "PASS：2011—2015与2017—2025共14年购买Parquet原件SHA/页脚/类型全部通过，2016与2026锚点一致"; Write-Host "PRECHECK：$pre"; Write-Host "SHA256：$((Get-FileHash -LiteralPath $pre -Algorithm SHA256).Hash.ToLowerInvariant())"; Get-Content -LiteralPath $pre -Encoding UTF8
```

请先回传`remaining14-source-preflight-*.json`的**脱敏报告**和终端结果，确认14份原件都受支持。如果预检PASS，后续再执行下一步；目前不应该提前运行真实14年物化。

## Windows第二步：仅第一步完整PASS之后可执行私有14年逐年物化＋独立审计（单行PowerShell）

该命令依赖当前PowerShell会话中第一步保留的`$pre`变量，失去该变量时主动停止，不自动使用任何其它历史报告。

```powershell
cd D:\ChatGPT\AStockDataTools; if ([string]::IsNullOrWhiteSpace([string]$pre) -or -not (Test-Path -LiteralPath $pre -PathType Leaf)) { throw "缺少第一步通过的预检SAFE变量pre，不能盲目选择旧报告" }; $r=Get-Content -LiteralPath $pre -Raw -Encoding UTF8 | ConvertFrom-Json; if ($r.status -ne "remaining_14_purchased_years_source_sha_and_arrow_footer_verified_not_materialized" -or $r.historical_year_files_verified -ne 14 -or $r.purchased_original_rows -ne 12449909 -or $r.physical_parquet_or_sqlite_created -ne $false) { throw "原始14年预检SAFE未通过" }; $preSha=(Get-FileHash -LiteralPath $pre -Algorithm SHA256).Hash.ToLowerInvariant(); $rid=[Guid]::NewGuid().ToString("N").Substring(0,12); $out="H5ParquetReconciler\reports\remaining14-$rid-independent-batch.json"; .\.venv\Scripts\python.exe H5ParquetReconciler\tools\stage-remaining14-private-purchased-years.py --materialize-and-audit --purchased-root "D:\stock\AllCycleAStockData" --candidate-safe "H5ParquetReconciler\reports\full-22274-private-candidates-60ae77774c30.json" --readme-sha256 "4c4e7c2081390407a06fecbe8b2693bddc9ce76191c44381b6be0e7781a2f023" --manifest-sha256 "24f099faeb0a2e810f46691b81b2a357cc5aa42cd7ccd800dae6e19db16b06eb" --accepted-2016-safe "H5ParquetReconciler\reports\recovered-2016-physical-fbae90cd49ec.json" --accepted-2016-audit "H5ParquetReconciler\reports\recovered-2016-independent-fbae90cd49ec.json" --accepted-2026-safe "H5ParquetReconciler\reports\physical-2026-purchased-plus-h5-f6d4a6e87887.json" --accepted-2026-audit "H5ParquetReconciler\reports\physical-2026-independent-full-audit-318b43aa9daf.json" --preflight-safe $pre --preflight-sha256 $preSha --batch-id $rid --out $out; if ($LASTEXITCODE -ne 0) { throw "14年批次在某年停止，完整年份私有文件仍保留，不要再次盲目重建" }; $r=Get-Content -LiteralPath $out -Raw -Encoding UTF8 | ConvertFrom-Json; if ($r.status -ne "all_14_historical_purchased_years_independently_verified_private_not_activated" -or $r.year_count -ne 14 -or $r.historical_purchased_rows_verified -ne 12449909 -or $r.all_years_independent_full_row_sha_and_key_verified -ne $true -or $r.original_market_files_written -ne $false -or $r.ready_for_production_query -ne $false -or $r.ready_for_automatic_market_merge -ne $false -or $r.ready_for_h5_mirror -ne $false) { throw "14年全量私有独立验收SAFE未通过" }; Write-Host "PASS：2011-2015与2017-2025全部14年购买日线私有物化+独立审计通过；购买行数12449909"; Write-Host "BATCH_SAFE：$out"; Get-Content -LiteralPath $out -Encoding UTF8
```

全批次成功后的预期私有购买总日线：2011—2025的**13,105,357条**（12,449,909新做+已验2016年655,448条），加上2016 H5候选1条和2026购买+H5 1,032,623条，理论总2011—2026**14,137,981条**。此数是按本次固定购买批次与已审核H5缺口作的算术目标，不能替代16年的实际逐行核验。
