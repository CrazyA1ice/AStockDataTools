# 第22阶段：2011—2026年私有统一版本SHA绑定（不重新物化）

## 已完成、不可重做的物理年度数据

真实Windows批次 `44edd84e21ee`已完成2011—2015与2017—2025共14年 **12,449,909条购买日线**，全部14年的私有Parquet、原始扩展字段逐字节副本、SQLite唯一键及Float64来源指纹已独立核验。最终聚合 SAFE `reports/remaining14-44edd84e21ee-independent-batch.json` SHA256=`e8daed0db6a8960de4cc728000f262b620c42ecb8104e420d61f1de5286105a6`。2016年已恢复完整655,448购买+1 H5，选定`physical_2016_999875510b81`；另一个通过验收的2016目录保持不动。2026年1,010,350购买+22,273 H5=1,032,623，保持已验收物理年完整不动。

**本阶段只创建一个新的模块 `reports` 内聚合-only SAFE JSON**，不重建/拷贝Parquet、SQLite或vendor原件，不启用任何私有/生产active pointer、生产查询、H5镜像。

## 工具

`tools/certify-private-2011-2026-physical-version-readonly.py`读取已验收的14年批次SAFE、14份年度物化SAFE与独立审计SAFE、已选2016年恢复SAFE与审计SAFE、2026年物化SAFE与审计SAFE。所有报告都经过SHA与schema/路径校验，14年分区、16年每个私人manifest、原vendor额外字段整份副本SHA、私有SQLite唯一键索引在执行时重新检查。

对16个SQLite唯一键表按只读immutable方式执行完整性、实际行数及每条索引键所属年份检查。此前各年已逐行验证Parquet时间戳、原值、来源、股票日键与SQLite主键完全一致；基于该验收与各年时间区间完全分离，可以证明跨年度不存在相同 `(symbol,trading_date)`。**此处不是第二次逐行读取全部14,137,981条Parquet数值**，不得把各年先前审计重新表述成当前全值重验。

只在全部16年SHA/来源/索引键/行数检查均通过后发布一个新版本SAFE，须精确得到：

- 购买原始记录 14,115,707条；
- 经来源绑定的H5候选 22,274条；
- 私有合计 14,137,981条；
- 年度数16，年份 2011—2026，每年有不可变物理目录、SHA与已有独立审计SAFE；
- `ready_for_production_query`、`ready_for_automatic_market_merge`、`ready_for_h5_mirror`均为false；
- 未认证的H5单位及原vendor额外列业务语义仍为false，隔离的2026-07-16异常股票日仍不纳入。

## 下一步：Windows运行新增7项合成安全测试，然后创建16年私有版本SAFE（仅报告文件，单行PowerShell）

```powershell
cd D:\ChatGPT\AStockDataTools; git fetch origin; if ($LASTEXITCODE -ne 0) { throw "Git fetch失败" }; git switch feat/private-2011-2025-purchased-physical-year-20261031; if ($LASTEXITCODE -ne 0) { throw "切换分支失败" }; git pull --ff-only origin feat/private-2011-2025-purchased-physical-year-20261031; if ($LASTEXITCODE -ne 0) { throw "分支更新失败" }; .\.venv\Scripts\python.exe -m py_compile H5ParquetReconciler\tools\certify-private-2011-2026-physical-version-readonly.py H5ParquetReconciler\tests\test_certify_private_2011_2026_physical_version_readonly.py; if ($LASTEXITCODE -ne 0) { throw "16年版本工具语法错误" }; .\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test_certify_private_2011_2026_physical_version_readonly.py" -v; if ($LASTEXITCODE -ne 0) { throw "16年不可变版本7项测试失败，禁止生成清单" }; $batch="H5ParquetReconciler\reports\remaining14-44edd84e21ee-independent-batch.json"; $sha="e8daed0db6a8960de4cc728000f262b620c42ecb8104e420d61f1de5286105a6"; if ((Get-FileHash -LiteralPath $batch -Algorithm SHA256).Hash.ToLowerInvariant() -ne $sha) { throw "已独立验收的14年批次SAFE SHA漂移" }; $rid=[Guid]::NewGuid().ToString("N").Substring(0,12); $out="H5ParquetReconciler\reports\private-2011-2026-all16-sha-bound-version-$rid.json"; .\.venv\Scripts\python.exe H5ParquetReconciler\tools\certify-private-2011-2026-physical-version-readonly.py --historical14-batch-safe $batch --historical14-batch-sha256 $sha --accepted-2016-safe "H5ParquetReconciler\reports\recovered-2016-physical-fbae90cd49ec.json" --accepted-2016-audit "H5ParquetReconciler\reports\recovered-2016-independent-fbae90cd49ec.json" --accepted-2026-safe "H5ParquetReconciler\reports\physical-2026-purchased-plus-h5-f6d4a6e87887.json" --accepted-2026-audit "H5ParquetReconciler\reports\physical-2026-independent-full-audit-318b43aa9daf.json" --candidate-safe "H5ParquetReconciler\reports\full-22274-private-candidates-60ae77774c30.json" --out $out --certify-private-only; if ($LASTEXITCODE -ne 0) { throw "16年来源SHA、年度SQLite跨年键或总行数验证未通过；原始和已验收文件全部保留" }; $r=Get-Content -LiteralPath $out -Raw -Encoding UTF8 | ConvertFrom-Json; if ($r.status -ne "all16_private_annual_physical_shards_sha_and_stockday_years_verified_not_activated" -or $r.year_count -ne 16 -or $r.purchased_original_records -ne 14115707 -or $r.verified_h5_only_gap_records -ne 22274 -or $r.private_total_stockday_records -ne 14137981 -or $r.per_year_private_sqlite_index_integrity_rechecked_readonly -ne $true -or $r.cross_year_stockday_key_ranges_disjoint -ne $true -or $r.private_physical_parquet_or_sqlite_written -ne $false -or $r.source_market_files_opened -ne $false -or $r.ready_for_production_query -ne $false -or $r.ready_for_automatic_market_merge -ne $false -or $r.ready_for_h5_mirror -ne $false) { throw "16年完整脱敏版本清单SAFE字段不符合验收要求" }; Write-Host "PASS：16个年份已验收私有数据SHA绑定+SQLite跨年键边界核验完成；总数14137981条"; Write-Host "ALL16_SAFE：$out"; Write-Host "ALL16_SHA256：$((Get-FileHash -LiteralPath $out -Algorithm SHA256).Hash.ToLowerInvariant())"; Get-Content -LiteralPath $out -Encoding UTF8
```

若测试失败，不运行工具。若16年版本核验失败，不修改任何物理年，下一轮按具体年度SAFE/SHA分析，不重新物化14个年度。发布成功只是“私有版本清单已验收”，不代表生产已启用或H5回写已完成。
