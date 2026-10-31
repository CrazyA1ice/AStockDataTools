# 2026-10-31：购买Parquet日线schema/元数据单位提示——只读页脚审计

## 为什么这轮做元数据审计

- PR #179已完成Windows真实Hikyuu 2.8.1隔离历史原生KRecord 7/7 HMAC核验，8/8合成测试OK（8.474秒），真实SAFE `reports/pre2011-historical-native-core311-hmac-dededf90b775.json`，并合并到main（`901ea7526bc18dd96c32da5a72736b211f73b8ce`）。这说明**选定的7条历史H5源记录**与C++原生解码数值一致。
- 但购买Parquet与原H5的真实日线2股样本存在不能忽视的**成交额原生整数不精确**：2026-09-30两股价格和成交量均可按候选倍率精确对应，金额则2/2需要Decimal候选舍入、0/2严格无损对应。其他5分钟也有跨源残差，不应把候选接成最终H5镜像。
- 缺少的关键不是更多1990年代倍率统计，而是**供应商对购买Parquet价格/成交量/成交额真实物理单位、精度、复权及时间标记的正式字段定义**。先核对购买文件本身是否携带这些解释的元数据字段，再决定是否必须联系供应商取得字典。

## 工具

`tools/audit-purchased-day-vendor-metadata-footer-readonly.py`：

1. 仅扫描当前原始 `D:\stock\AllCycleAStockData\day` 内的**全部Parquet文件页脚/Arrow schema metadata**。复用现有 `inventory-pre2011-h5-parquet-day-readonly.py` 的受预算目录枚举（防链接、限制文件数，包含所有名字），只用 `pyarrow.parquet.ParquetFile(...,memory_map=False,pre_buffer=False)` 获取Arrow字段、列类型、schema kv、file kv以及行组/总行数。
2. **不读取任何原始Parquet行情行**，不加载H5或私有RAW、不打开stock.db；即使文件在2011–2026年，报告也不输出原文件名、原字段元数据内容、真实股票代码/价格/时间戳、供应商名称或其他敏感内容。
3. SAFE只记录源文件数、页脚行组数、元数据文件行数之和、已知字段角色（ts/open/high/low/close/volume/amount等）出现文件数/列类型、单位/复权/时标等**候选元数据键角色的出现次数**，及总schema类型数量。只解析元数据键的固定词典，不读取、判断、转换或导出任何元数据**值**。非白名单键名不导出。
4. 任何元数据键的存在都**不构成**供应商合同/数据字典的可信单位证据；所有历史物理单位/复权/证券身份资格、可标准化历史RAW、可写H5/生产开关**始终为false**。即使发现明确文本内容也必须由正式供应商说明及逐单位验证进一步确认。
5. 输入源Parquet文件集合及size/mtime前后检查不变，SAFE只能是模块reports下**全新**JSON。任何缺源、symlink、ts缺失、过大metadata或源文件变化安全退出。全部输出仅在`H5ParquetReconciler/reports`，Git不收商业Parquet、原H5或meta原值。

## Windows单行PowerShell：先9项合成测试，再仅扫描原日线Parquet页脚

拉分支、检查语法并运行9项虚构Arrow/Parquet合成测试（新PR仍为Draft，未在Windows验证）：

    cd D:\ChatGPT\AStockDataTools; git fetch origin; if ($LASTEXITCODE -ne 0) { throw "fetch失败" }; git switch feat/purchased-day-vendor-metadata-footer-20261031; if ($LASTEXITCODE -ne 0) { throw "切换分支失败" }; git pull --ff-only origin feat/purchased-day-vendor-metadata-footer-20261031; if ($LASTEXITCODE -ne 0) { throw "更新失败" }; .\.venv\Scripts\python.exe -m py_compile H5ParquetReconciler\tools\audit-purchased-day-vendor-metadata-footer-readonly.py H5ParquetReconciler\tests\test_audit_purchased_day_vendor_metadata_footer_readonly.py; if ($LASTEXITCODE -ne 0) { throw "元数据页脚检查代码语法失败" }; .\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test_audit_purchased_day_vendor_metadata_footer_readonly.py" -v; if ($LASTEXITCODE -ne 0) { throw "9项合成测试失败，停止真实Parquet页脚读取" }; Write-Host "购买Parquet元数据只读检查合成测试全部通过"

仅全部测试OK才运行用户真实购买日线Parquet的**只读页脚**审计：

    cd D:\ChatGPT\AStockDataTools; $rid=[Guid]::NewGuid().ToString("N").Substring(0,12); $out="H5ParquetReconciler\reports\purchased-day-vendor-metadata-footer-$rid.json"; .\.venv\Scripts\python.exe H5ParquetReconciler\tools\audit-purchased-day-vendor-metadata-footer-readonly.py --root "D:\stock" --out $out --read-only-purchased-day-footer; if ($LASTEXITCODE -ne 0) { throw "购买Parquet页脚元数据审计失败" }; $r=Get-Content $out -Raw | ConvertFrom-Json; if ($r.source_files_footer_only_read -le 0 -or $r.parquet_footer_only_no_market_rows_read -ne $true -or $r.purchased_day_original_modified -ne $false -or $r.source_vendor_data_dictionary_attached_and_verified -ne $false -or $r.historical_physical_price_volume_amount_units_certified -ne $false -or $r.ready_to_normalize_historical_raw_or_write_h5_mirror -ne $false) { throw "元数据审计安全门禁错误" }; Write-Host "购买Parquet日线元数据页脚SAFE：$out"

请只回传两个命令的终端输出和SAFE JSON，不上传原付费数据、字段原值或具体OHLCVA。若原文件没有单位键，说明至少购买Parquet页脚**没有找到这些可识别的候选字段声明**；不能声称供应商完全没有定义。需要进一步向数据提供者索取原始字段定义，特别是open/high/low/close是否复权、volume单位、amount币种/单位与浮点精度、时间戳时区/标签以及是否有历史期间字段规则差异。

后续即使确认某些样本的元数据键含义，也必须设计独立的数据源合同验证（来自供应商的明确版本化描述）并配合跨年份有界真实重叠日对照，不可仅凭日线“H5原生解码7/7”批准1990–2010全部RAW进入统一Parquet。