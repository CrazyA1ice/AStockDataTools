# 2026-10-30：历史H5原生整数日线内部量价额倍率候选检查

## 前置真实证据

- 1990～2010年原始H5日线已逐年无损暂存21个独立私有RAW Parquet；用户Windows完成实际21年/3,682,327条全局H5逐数值对比和SHA验证（本地SAFE `reports/pre2011-full21-verify-9bba81ed3c33.json`），没有修改原H5、商业Parquet或生产数据。
- 用户已通过6/6 synthetic，并对全部21年原生RAW做数值聚合（本地SAFE `reports/pre2011-raw-numeric-profile-402f2c1309df.json`）：0 OHLC边界违例、零价0、uint32越界0、开高低收完全相等10,374条；成交量正/额零60条（1990～93）、量零/额正1条、双零4条。
- 用户又通过8/8 synthetic，对1990～1993年28,325条量额零值细分。1992年上海50条有量无额日线全部四价相等，但没有证明历史异常原因；PR #174已合并main。

## 本轮目标：先验证跨21年的数学自洽性，不擅自标准化

此前2025/2026有限真实交易日样本支持过候选（**不是供应商单位证明**）：购买Parquet价格约H5原生整数价格/1000，数量约原生transCount×100，金额约原生transAmount×1000。若这些关系在某年某股票日成立，则

    该日的价格VWAP（原H5价格整数单位）≈原生 transAmount × 10000 / 原生 transCount

应落在原生 lowPrice..highPrice 范围附近。但历史时期是否保持这些倍率完全未知，历史证券可能停牌、特殊交易、价格精度不同；更没有购买Parquet覆盖2011年前来配对。

本轮新增 `tools/audit-pre2011-private-raw-vwap-factors-readonly.py`：

1. 接受已验收的本地FULL21 SHA链和21年数值诊断SAFE，核对全部21个私有分区的manifest、年度行数、SHA；不打开当前原始H5、购买Parquet或stock.db。
2. 从每条原生整数日线读出lowPrice/highPrice/transCount/transAmount。量额双正的记录比较候选倍率 `1、10、100、1000、10000、100000`：只检测 `transAmount × 倍率 / transCount` 是否在[lowPrice×0.995, highPrice×1.005]区间内。使用Python任意精度整数，杜绝uint64乘法溢出，结果只累计每年各倍率命中数。
3. 量额有零的记录直接排除，不准将零视为倍率命中；零值计数必须与用户前次21年SAFE一致，任一差异拒绝。
4. 输出仅为每年总数、各倍率命中数、正数量、零数量和SHA证据。不会写实际价格、成交量、成交额、股票代码、个别日期、绝对行情路径；不创建任何标准化Parquet或新H5。
5. **重要**：VWAP候选命中不能证明历史单位正确、复权口径一致、日交易额合法或供应商字段定义，也不能证明Hikyuu原生C++正确解码。`historical_physical_units_or_corporate_actions_certified=false`，生产路线和私有活动指针绝不改动。

## 用户Windows操作：每条命令必须单行

先fetch新分支，并运行7项纯合成小Parquet测试（PR #175仍Draft；测试尚未通过Windows）：

    cd D:\ChatGPT\AStockDataTools; git fetch origin; if ($LASTEXITCODE -ne 0) { throw "fetch失败" }; git switch feat/pre2011-private-raw-vwap-factor-evidence-20261030; if ($LASTEXITCODE -ne 0) { throw "切换分支失败" }; git pull --ff-only origin feat/pre2011-private-raw-vwap-factor-evidence-20261030; if ($LASTEXITCODE -ne 0) { throw "更新失败" }; .\.venv\Scripts\python.exe -m py_compile H5ParquetReconciler\tools\audit-pre2011-private-raw-vwap-factors-readonly.py; if ($LASTEXITCODE -ne 0) { throw "脚本语法检查失败" }; .\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test_audit_pre2011_private_raw_vwap_factors_readonly.py" -v; if ($LASTEXITCODE -ne 0) { throw "7项合成测试失败，停止真实RAW扫描" }; Write-Host "历史倍率候选诊断测试全部通过"

只有全部测试通过，才执行以下21年真实历史RAW**只读**候选矩阵（不覆盖原报告）：

    cd D:\ChatGPT\AStockDataTools; $rid=[Guid]::NewGuid().ToString("N").Substring(0,12); $out="H5ParquetReconciler\reports\pre2011-raw-vwap-factor-evidence-$rid.json"; .\.venv\Scripts\python.exe H5ParquetReconciler\tools\audit-pre2011-private-raw-vwap-factors-readonly.py --full21-safe "H5ParquetReconciler\reports\pre2011-full21-verify-9bba81ed3c33.json" --numeric-profile-safe "H5ParquetReconciler\reports\pre2011-raw-numeric-profile-402f2c1309df.json" --out $out --read-only-private-raw; if ($LASTEXITCODE -ne 0) { throw "历史量价额候选倍率诊断拒绝执行" }; $r=Get-Content $out -Raw | ConvertFrom-Json; if ($r.rows_audited -ne 3682327 -or $r.years_audited -ne 21 -or $r.original_h5_or_purchased_parquet_opened -ne $false -or $r.historical_physical_units_or_corporate_actions_certified -ne $false -or $r.standardized_historical_parquet_created -ne $false -or $r.production_or_private_active_modified -ne $false) { throw "候选倍率矩阵数量或安全门禁不符合预期" }; Write-Host "21年历史量价额候选倍率SAFE：$out"

只回传新SAFE报告和合成测试结果，不上传原始市场行情。此处只是**在原RAW记录内部做候选量价比例证据**，不应等同于供应商物理单位认证；进一步须结合Hikyuu 2.8.1原生历史解码及购买Parquet字段说明、复权/历史证券身份进行独立验证。
