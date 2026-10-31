# 2026-10-31 QDC购买Parquet日线数据包原始文件完整性（24/24）可重复验收

## 用户已经完成的Windows真实证据

- 随包`【先看我】数据说明.txt` SHA256 `4c4e7c2081390407a06fecbe8b2693bddc9ce76191c44381b6be0e7781a2f023`，本地源件与模块 `work/vendor_semantics/qdc-purchased-dataset-readme.txt`副本相同。
- 随包`文件校验清单.txt` SHA256 `24f099faeb0a2e810f46691b81b2a357cc5aa42cd7ccd800dae6e19db16b06eb`，本地源件与模块 `work/vendor_semantics/`副本相同。
- 用户PowerShell逐项比对原始`D:\stock\AllCycleAStockData\day`的**24个**Parquet文件（2011–2025年15个年文件、2026-01至09月9个月文件），**24/24大小+页脚行数+整字节SHA256匹配随包清单，合计14,115,707条日K线**。该事实来自用户本机日志，不可将新脚本未实测说成新一轮通过。
- 已验收的购买日线24文件 footer/schema 扫描只读、139行组、1种Arrow schema：`symbol string,ts int64,OHLC/volume/amount double`；页脚元数据单位声明键命中0（不意味着没有外置README）。
- QDC随包说明给出`OHLC 元/不复权原始价, volume 股, amount 元, ts Unix毫秒`，1分钟标准完整日241根且09:30单独集合竞价、其他分钟结束标签；5/15/30/60min采用**开始**标签。此前按README位置已登记7个`documented`类别，6个`unknown`，私有脱敏SAFE`reports/vendor-semantics-document-inventory-acbea8a5017f.json`。这只是**随包声明、用户本地来源**；不是第三方或供应商数字签名。
- 2026-09-30真实购买Parquet与原H5成交额两股都是**需候选舍入、0/2原生整数严格精确**。未认证的金额舍入/历史证券身份/1990–2010 H5历史规则仍是独立阻碍，**不能因此将原H5 RAW转换并与商业Parquet全市场自动合并**。

## 新只读工具

`tools/verify-qdc-purchased-day-bundle-integrity-readonly.py`提供可重复的原始24日线数据包完整性核验：

1. 必须显式提供**已由用户本机核过的原README及清单SHA256**；在原购买根目录中仅只读校验两份原文、按`日线 文件名 size rows first last SHA256`精确解析**24条**随包清单，严格限制应有`2011..2025.parquet`及`2026-01..09.parquet`的文件集、重复条、总行数与年份/月份范围。
2. 按原始`day`文件清单逐个执行：原件字节大小比较 → Arrow Parquet**页脚**`num_rows`比较（**不解码任何行情行**）→整文件SHA256比较。新工具不会读取H5、私有RAW、生产SQLite或改动源；原件文件stat/目录枚举/两份说明原件SHA前后核对。因需要对约0.3GB日线数据进行整字节哈希，该步需要I/O，但不会扫描62GB其他分钟市场文件。
3. 可选输入之前已验收的`reports/vendor-semantics-document-inventory-acbea8a5017f.json`：验证7类已登记、6类仍未知、文档SHA与README pin相同及所有授权false后，把**该SAFE文件整体SHA256**链接到新报告。不导出供应商原文、每股代码、原始市场数值、来源路径、每份商品Parquet文件名或实际来源原元数据值。
4. 只允许生成**全新**的模块`reports/`脱敏SAFE，成功前不会写报告。所有原源、购买Parquet、H5、生产数据库、活动指针不写入。私有原件与供货目录不得推送GitHub。
5. 输出的`all_original_day_file_full_sha256_match_received_manifest=true`**只证明这24个现有原件与随包SHA清单字节一致**，不证明公开发行方身份/签名、真实行情正确性、分钟周期已验收、2011前H5已规范化、金额取整方式或生产H5镜像转换资格。货币/股价/分钟时间标签仍需结合真实记录独立验证。

## 执行步骤（**PowerShell每条均为独立完整单行**）

**1. 检查新代码并跑13项虚构Parquet合成回归**（这版Draft PR尚未经过Windows验收）：

```powershell
cd D:\ChatGPT\AStockDataTools; git fetch origin; if ($LASTEXITCODE -ne 0) { throw "fetch失败" }; git switch feat/qdc-purchased-day-manifest-integrity-safe-20261031; if ($LASTEXITCODE -ne 0) { throw "切换分支失败" }; git pull --ff-only origin feat/qdc-purchased-day-manifest-integrity-safe-20261031; if ($LASTEXITCODE -ne 0) { throw "更新失败" }; .\.venv\Scripts\python.exe -m py_compile H5ParquetReconciler\tools\verify-qdc-purchased-day-bundle-integrity-readonly.py H5ParquetReconciler\tests\test_verify_qdc_purchased_day_bundle_integrity_readonly.py; if ($LASTEXITCODE -ne 0) { throw "语法检查失败" }; .\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test_verify_qdc_purchased_day_bundle_integrity_readonly.py" -v; if ($LASTEXITCODE -ne 0) { throw "13项合成测试失败，禁止真实Parquet读取" }; Write-Host "13项QDC随包清单完整性合成测试全部通过"
```

**2. 13项测试全部OK后，才对原24个日线文件跑一次只读SHA+footer+已登记供应商说明证据链审计**：

```powershell
cd D:\ChatGPT\AStockDataTools; $rid=[Guid]::NewGuid().ToString("N").Substring(0,12); $out="H5ParquetReconciler\reports\qdc-purchased-day-bundle-integrity-$rid.json"; .\.venv\Scripts\python.exe H5ParquetReconciler\tools\verify-qdc-purchased-day-bundle-integrity-readonly.py --source-root "D:\stock\AllCycleAStockData" --readme-sha256 "4c4e7c2081390407a06fecbe8b2693bddc9ce76191c44381b6be0e7781a2f023" --manifest-sha256 "24f099faeb0a2e810f46691b81b2a357cc5aa42cd7ccd800dae6e19db16b06eb" --vendor-intake-safe "H5ParquetReconciler\reports\vendor-semantics-document-inventory-acbea8a5017f.json" --out $out --read-only-all-original-purchased-day; if ($LASTEXITCODE -ne 0) { throw "QDC 24日线真实SHA门禁未通过" }; $r=Get-Content $out -Raw | ConvertFrom-Json; if ($r.purchased_day_file_count_verified -ne 24 -or $r.purchased_day_row_count_verified -ne 14115707 -or $r.all_original_day_file_full_sha256_match_received_manifest -ne $true -or $r.vendor_intake_seven_documented_six_unknown_linked -ne $true -or $r.historical_normalized_parquet_authorized -ne $false -or $r.hikyuu_h5_mirror_authorized -ne $false -or $r.market_source_h5_or_purchased_parquet_modified -ne $false) { throw "QDC真实SAFE或权限边界不通过" }; Write-Host "QDC购买日线24/24完整性SAFE：$out"
```

将新SAFE JSON与Windows单测的`OK`日志回传即可；不要上传原始购买Parquet文件、原vendor文档/校验清单或私有报价。只有新一轮Windows证据通过后，才可以标记工具为真实验证完成并合并Draft PR。下一阶段由已经确认的**元/股/不复权/Unix毫秒**字段说明进入**有限真实跨源amount精度与1min/5min时间标签**校验；不得将有限样本的舍入候选自动用于全市场。
