# 2016/2026 H5-only混合日期83个精确股票—日键实时验证（2026-10-31）

## 验收依据

- 16/16年实际股票日线精确扫描完成：购买Parquet有效候选行13,916,797、H5候选13,345,263、交集13,322,984、H5-only 22,279。
- 2026年10月四个整日缺口22,191行已经隔离私有Parquet暂存，不属于本次任务。
- 上轮PR #187实机验证通过12/12合成测试及离线SAFE reports/mixed-day-88-candidates-92274029928f.json：剩余88条混合日期H5-only记录，2016年1条、2026年87条。2026-07-16的5条因同日存在4978条重叠价差而隔离。**非隔离只剩83条，均需本轮重新查原H5与购买Parquet的股票-日期精确键。**

## 只读工具设计

新增 tools/verify-live-mixed-h5-day-keys-readonly.py，先从已完成16年总账及2016/2026年SHA绑定源报告重算PR #187离线SAFE，并要求结果与已有SAFE字节解码后的对象完全一致；任何更换报告、改数或越界日期直接拒绝。

真实读取只使用H5指定股票日的日期键与购买Parquet的ts/symbol两列；按年份（2016、2026）分别计算逐日H5键、购买PQ键、交集及H5-only集合，对照原年度审计的日级数量。禁止把已有PQ股票日写成H5-only，严格检查重复源键和来源在查询前后的文件大小、mtime一致性。2026-07-16的五条完全排除。

通过后，工具在模块私有work/unified_parquet/mixed_day_key_manifests/keys_十六进制编号/keys.json创建仅包含83个股票代码+交易日期的精确缺口清单，不包含原OHLCVA，**严禁将此清单上传GitHub或复制外发**。同时在模块reports保存不包含股票代码的聚合SAFE（每年日期数量、SHA256和全程只读状态）。

本工具不会读取原数据来创建私有行情值，不会建立新的Parquet K线分区，不会改动购买Parquet、原H5、private active、production路由，不能创建H5镜像。83条键证明不代表候选成交量/成交额单位、舍入精度和价格真实性通过认证。新增13项合成测试，尚需Windows验收。其中新增的反向测试确保2016/2026年度源的完整SHA与总账一致时，也不能用错误的2026-10-01隔离日绕过真实2026-07-16的安全门禁。

## Windows PowerShell单行命令

第一步：更新新开发分支、Python编译、运行13项合成回归：

    cd D:\ChatGPT\AStockDataTools; git fetch origin; if ($LASTEXITCODE -ne 0) { throw "fetch失败" }; git switch feat/live-verify-mixed-day-83-keys-20261031; if ($LASTEXITCODE -ne 0) { throw "切换分支失败" }; git pull --ff-only origin feat/live-verify-mixed-day-83-keys-20261031; if ($LASTEXITCODE -ne 0) { throw "更新失败" }; .\.venv\Scripts\python.exe -m py_compile H5ParquetReconciler\tools\verify-live-mixed-h5-day-keys-readonly.py H5ParquetReconciler\tests\test_verify_live_mixed_h5_day_keys_readonly.py; if ($LASTEXITCODE -ne 0) { throw "语法检查失败" }; .\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test_verify_live_mixed_h5_day_keys_readonly.py" -v; if ($LASTEXITCODE -ne 0) { throw "新13项精确键合成测试失败，停止" }; Write-Host "13项精确键合成测试通过"

第二步：上一项测试全部OK后，运行真实83键只读核验。唯一可新增的是module work私有键清单和module reports脱敏SAFE，不生成行情K线：

    cd D:\ChatGPT\AStockDataTools; $rid=[Guid]::NewGuid().ToString("N").Substring(0,12); $dir="H5ParquetReconciler\work\unified_parquet\mixed_day_key_manifests\keys_$rid"; $out="H5ParquetReconciler\reports\live-mixed-day-83-keys-$rid.json"; .\.venv\Scripts\python.exe H5ParquetReconciler\tools\verify-live-mixed-h5-day-keys-readonly.py --source-root "D:\stock" --history-ledger "H5ParquetReconciler\reports\history-day-ledger-full-91fae9458806.json" --source-2016 "H5ParquetReconciler\reports\historical-day-exact-2016-asof20261031-v1.json" --source-2026 "H5ParquetReconciler\reports\historical-day-exact-2026-asof20261031-v1.json" --mixed-plan "H5ParquetReconciler\reports\mixed-day-88-candidates-92274029928f.json" --key-manifest-dir $dir --out $out --verify-only-read-only-sources; if ($LASTEXITCODE -ne 0) { throw "83条精确键验收失败：不得进行私有行情暂存" }; $r=Get-Content -LiteralPath $out -Raw -Encoding UTF8 | ConvertFrom-Json; if ($r.live_verified_nonquarantined_h5_only_stockdays -ne 83 -or $r.quarantined_stockdays_excluded_from_exact_live_keyset -ne 5 -or $r.original_market_files_written -ne $false -or $r.private_parquet_market_rows_staged -ne $false -or $r.private_or_production_active_pointer_modified -ne $false -or $r.ready_for_automatic_merge -ne $false) { throw "实时SAFE安全状态异常" }; Write-Host "只读SAFE：$out"; $r.years | Select-Object year,live_verified_h5_only_stockdays,live_h5_candidate_keys,live_purchased_candidate_keys | Format-Table -AutoSize

**下一阶段**：只有这83个精确键被本机真实来源重新证实，才能开发私有逐键H5行读取、几何校验、Parquet转换候选分区；2026-07-16五条继续隔离。所有源行情不上传，不覆盖。
