# 2026-10-30：1990—1993年历史H5成交量/成交额单边零值细分

## Windows已验收的真实聚合结论

- PR #173的6/6项合成测试通过；真实21年3,682,327条原生RAW已完成数值统计：OHLC上下界违例0、零价格0、uint32越界0、四价相等10,374。
- 成交量非零而成交额为零共60条：1990=3、1991=4、1992=50、1993=3；成交量为零而成交额非零共1条（1993）；两者同时为零4条（1991=3、1992=1）。
- 1990年24条中有19条四价相等，1991年2043条中有1186条四价相等。只表示需要研究，不能认定存在交易异常或者市场数据错误。
- 原始购买Parquet优先，原始H5/商业Parquet从来不允许修改，以上都是原生整数值不是供应商量纲。

## 本轮只读诊断目标

新增tools/audit-pre2011-early-zero-amount-strata-readonly.py，只读1990—1993年共28,325条私有RAW，并按年度、市场前缀SH/SZ/BJ、量额零值状态、四价是否完全一致汇总。只输出脱敏聚合计数，不输出证券代码、日期、实际价格、成交量或成交额。

先严格验证用户本地FULL21 SAFE（reports/pre2011-full21-verify-9bba81ed3c33.json）和21年数值SAFE（reports/pre2011-raw-numeric-profile-402f2c1309df.json）的来源SHA绑定以及量额单位/复权/生产禁止旗标；再全量核对21个私有RAW Parquet SHA和manifest、仅逐行解码4年早期数值。新的早期年度量额单边零值和四价相等数必须与用户已经验收的21年统计逐年相同，否则拒绝。私有文件扫描前后都复核SHA。

本轮不接触原H5、原购买Parquet、stock.db或生产指针。不创建标准化Parquet或新的H5镜像，不自动填充金额或删除任何记录。本轮的SAFE只反映前次真实full21认证时点的来源快照，不代表对当前原始行情做过新的现场认证。

## Windows单行PowerShell操作

1. 切新分支，运行8项纯合成回归：

    cd D:\ChatGPT\AStockDataTools; git fetch origin; if ($LASTEXITCODE -ne 0) { throw "fetch失败" }; git switch feat/pre2011-early-zero-amount-triage-readonly-20261030; if ($LASTEXITCODE -ne 0) { throw "切换失败" }; git pull --ff-only origin feat/pre2011-early-zero-amount-triage-readonly-20261030; if ($LASTEXITCODE -ne 0) { throw "更新失败" }; .\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test_audit_pre2011_early_zero_amount_strata_readonly.py" -v; if ($LASTEXITCODE -ne 0) { throw "8项合成测试失败，停止真实历史扫描" }; Write-Host "8项合成测试通过"

2. **仅前述8项测试全部通过**后，运行私有RAW 1990—1993年只读聚合：

    cd D:\ChatGPT\AStockDataTools; $rid=[Guid]::NewGuid().ToString("N").Substring(0,12); $out="H5ParquetReconciler\reports\pre2011-early-zero-strata-$rid.json"; .\.venv\Scripts\python.exe H5ParquetReconciler\tools\audit-pre2011-early-zero-amount-strata-readonly.py --full21-safe "H5ParquetReconciler\reports\pre2011-full21-verify-9bba81ed3c33.json" --numeric-profile-safe "H5ParquetReconciler\reports\pre2011-raw-numeric-profile-402f2c1309df.json" --out $out --read-only-private-raw; if ($LASTEXITCODE -ne 0) { throw "早期历史量额零值细分失败" }; $r=Get-Content $out -Raw | ConvertFrom-Json; if ($r.rows_profiled -ne 28325 -or $r.total_state_count.volume_positive_amount_zero -ne 60 -or $r.total_state_count.volume_zero_amount_positive -ne 1 -or $r.total_state_count.both_zero -ne 4 -or $r.historical_units_or_adjustment_certified -ne $false -or $r.private_stage_or_production_changed -ne $false) { throw "早期量额异常计数或安全门禁不符合预期" }; Write-Host "早期量额零值SAFE报告：$out"

只回传新SAFE及测试日志，不上传原始商业行情。只进行分布诊断，随后才研究历史单位及编码；尚未批准数值修复、正式统一Parquet和H5镜像。
