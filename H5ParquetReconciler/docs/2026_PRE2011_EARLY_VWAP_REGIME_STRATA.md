# 2026-10-30：1990—1996年H5原生RAW数值倍率早期制度分布调查

## 前置Windows真实结果

- 1990—2010年21个私有RAW年度分区已全部验收，3,682,327条候选日线与原H5整数逐行/文件SHA完成全量一致性检查；原商业Parquet日线从2011-01-04起。
- PR #175已合并（8fa439848e5d8eab88ded7543aacbc61b263facd）；7/7项Windows synthetic测试通过，真实21年RAW量价额候选F矩阵已完成：3,682,262条量额均正、候选F=10000命中3,673,987；F=100000命中2,344。结果仅是原H5内部VWAP算术，不是物理单位认证。SAFE在用户本地`H5ParquetReconciler/reports/pre2011-raw-vwap-factor-evidence-ad01206e74d1.json`。
- 1990有效21条F10000=0；1991 2036条中F10000=323/F100000=175；1992 5841条中F10000=2366/F100000=2103；1993 20362中F10000=19783；1994 52414中F10000=52295；1995 58848中F10000=57765；1996 75651中F10000=75424。因此需要定位1990—1996的过渡，而不是对全部历史以单一倍率改写。

## 新增只读工具

`tools/audit-pre2011-early-regime-vwap-strata-readonly.py`严格只读1990—1996七个年度合计215,238条私有原始整数Parquet，按年份、季度（Q1～Q4）和市场（SH/SZ/BJ）汇总各候选倍率命中计数、量额正数、量额零值状态、四价相同数量、所有候选不命中的数量。季度只作为聚合分类，SAFE中**不**包含单条原始日期和股票代码。

前置门禁：真实21年FULL21 SAFE＋21年零值和OHLC数值SAFE＋21年VWAP倍率SAFE三份报告的SHA互相绑定；21年私有RAW年度文件及manifest须与FULL21的SHA完全相同。新工具只需逐行扫描1990—1996，其每年的六个倍率命中数、单双零计数、flat OHLC计数必须与以前实际21年报告严格一致。SHA验证包含扫描前后，拒绝私有源中途变更。

**安全提醒**：这不是供货商单位证明，不读取原始购买Parquet/H5、无复权结论、不会重算或删除历史价量额、不会生成购买schema兼容的标准化日线或新H5镜像、不会触碰生产或私有active指针。此前现代有限样本的F=10000只作为候选解释，不是跨时间/历史证券类型的统一标准。

## Windows PowerShell（复制一整行，不能换行或用嵌套python -c）

第一步：拉取分支，检查语法和7个合成测试，未全部通过不得执行真实扫描：

    cd D:\ChatGPT\AStockDataTools; git fetch origin; if ($LASTEXITCODE -ne 0) { throw "fetch失败" }; git switch feat/pre2011-early-regime-vwap-strata-20261030; if ($LASTEXITCODE -ne 0) { throw "切换分支失败" }; git pull --ff-only origin feat/pre2011-early-regime-vwap-strata-20261030; if ($LASTEXITCODE -ne 0) { throw "更新失败" }; .\.venv\Scripts\python.exe -m py_compile H5ParquetReconciler\tools\audit-pre2011-early-regime-vwap-strata-readonly.py H5ParquetReconciler\tests\test_audit_pre2011_early_regime_vwap_strata_readonly.py; if ($LASTEXITCODE -ne 0) { throw "Python语法检查失败" }; .\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test_audit_pre2011_early_regime_vwap_strata_readonly.py" -v; if ($LASTEXITCODE -ne 0) { throw "7项合成测试失败，停止真实数据扫描" }; Write-Host "早期倍率分布合成测试全部通过"

第二步：测试通过后执行1990—1996历史数据只读矩阵（若超限或任何SHA不一致，自动拒绝）：

    cd D:\ChatGPT\AStockDataTools; $rid=[Guid]::NewGuid().ToString("N").Substring(0,12); $out="H5ParquetReconciler\reports\pre2011-early-regime-strata-$rid.json"; .\.venv\Scripts\python.exe H5ParquetReconciler\tools\audit-pre2011-early-regime-vwap-strata-readonly.py --full21-safe "H5ParquetReconciler\reports\pre2011-full21-verify-9bba81ed3c33.json" --numeric-profile-safe "H5ParquetReconciler\reports\pre2011-raw-numeric-profile-402f2c1309df.json" --factor-safe "H5ParquetReconciler\reports\pre2011-raw-vwap-factor-evidence-ad01206e74d1.json" --out $out --read-only-private-raw; if ($LASTEXITCODE -ne 0) { throw "1990—1996历史倍率分布诊断失败" }; $r=Get-Content $out -Raw | ConvertFrom-Json; if ($r.rows_stratified -ne 215238 -or $r.selected_years.Count -ne 7 -or $r.original_h5_or_purchased_parquet_opened -ne $false -or $r.physical_units_corporate_actions_or_securities_certified -ne $false -or $r.standardized_purchased_parquet_or_h5_created -ne $false -or $r.production_or_active_pointer_modified -ne $false) { throw "早期分布计数或安全门禁异常" }; Write-Host "历史倍率分布SAFE：$out"

只需要回传Windows测试结果及新SAFE JSON，不上传原始商业Parquet/H5或个股实际行情。