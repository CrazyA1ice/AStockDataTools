# 2026-10-31：历史H5原生解码的样本资格检查（不是原生解码本身）

## 已验收前置事实

用户Windows真实验收：原始H5历史候选日线1990—2010年3,682,327条，21年私有RAW无损暂存/全局H5整数逐值核对与SHA验收。通过了PR #173–#176全部合成测试与真实只读分布检查。1992年上海原RAW量价额F100000和F10000候选在季度上存在差异；1993上海逐渐以F10000占主导，1995上海Q1仍有453条不匹配已测试的全部6个候选因子。参见Issue #177。**这些比例绝不等于供应商物理单位或编码变更日期。**

## 本PR的安全交付

新增 `tools/qualify-pre2011-historical-native-h5-targets-readonly.py`，在即将开发隔离Hikyuu 2.8.1历史KRecord读取之前建立严格可复核的真实样本资格门禁：

1. 从此前用户实机生成的FULL-21 SAFE `reports/pre2011-full21-verify-9bba81ed3c33.json` 读取年度SHA与原始来源快照，逐个检查**全部21个**私有RAW Parquet/manifest的唯一性、年度行数、完整文件SHA和来源摘要；不把旧快照冒充本轮全部原H5的重新扫描。
2. 仅逐行读取1992、1993、1995三个私有RAW年度分区，按固定市场/季度/候选因子要求精确选出7条可复现的目标：1992 SH Q2/Q3 F100000，1992 SH Q4 F10000，1992 SZ Q2 F10000，1993 SH/SZ Q1 F10000，1995 SH Q1所有六种候选都不命中的正量额记录。各季度按股票代码/日键的字典序确定第一条目标，不能自动用不相干年份/证券替代。固定选择是研究抽样，不推断上市资格或单位。
3. 对每条目标使用只读 `h5py.File(...,'r')`，对原始 `HikyuuData/sh_day.h5`、`sz_day.h5` 的目标股票数据集采用二分定位当日KRecord原始整数，核对所有7个整数（含datetime）**与私有RAW完全相等**，原H5股票日线数据集每只不超过25000条；文件stat在核对前后保持不变。原H5完整文件SHA、本轮购买Parquet原件及证券主数据**没有**复核，状态明确为unknown/false。
4. 仅将目标原生股票代码、原生 `YYYYMMDD0000` 日期键、原H5原生索引和股票总日线条数写入**新的、本地gitignored的模块私有清单** `H5ParquetReconciler/work/h5_mirror/historical_native_qualification/native_targets_<runid>/selected-original-h5-native-targets.json`。**不会保存OHLC、成交量、成交额原数值，也绝不提交此清单到Git**。
5. `H5ParquetReconciler/reports/`中只生成新的SAFE：完成目标计数7、市场/季度/因子类型、旧full21证据SHA、本地私有清单文件SHA（不含股票代码/具体日期/个体OHLCVA、H5真实路径）。只要一个目标不存在、年份/市场错误、文件或SHA变化、原始H5字段不一致，都拒绝产生SAFE；不写生产、不修改源、不生成任何标准化Parquet或H5镜像。

本PR是对原生驱动实验的**资格检查**。安装的Hikyuu 2.8.1 C++驱动**没有在本轮执行**，`hikyuu_native_driver_called=false`。原市场H5只读、购买Parquet不打开，历史单位/复权/证券身份不认证，生产查询和私有active指针均不改变。

## Windows PowerShell一行一条

第一步：切开发分支并进行语法和7项完全合成测试（未经本机验证不得对真实H5运行）：

    cd D:\ChatGPT\AStockDataTools; git fetch origin; if ($LASTEXITCODE -ne 0) { throw "fetch失败" }; git switch feat/pre2011-historical-native-target-qualification-20261031; if ($LASTEXITCODE -ne 0) { throw "切换分支失败" }; git pull --ff-only origin feat/pre2011-historical-native-target-qualification-20261031; if ($LASTEXITCODE -ne 0) { throw "更新失败" }; .\.venv\Scripts\python.exe -m py_compile H5ParquetReconciler\tools\qualify-pre2011-historical-native-h5-targets-readonly.py H5ParquetReconciler\tests\test_qualify_pre2011_historical_native_h5_targets_readonly.py; if ($LASTEXITCODE -ne 0) { throw "语法检查失败" }; .\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test_qualify_pre2011_historical_native_h5_targets_readonly.py" -v; if ($LASTEXITCODE -ne 0) { throw "7项合成测试失败，停止原H5资格检查" }; Write-Host "历史原生H5目标资格合成测试全部通过"

第二步（**前一条全部OK才运行**）：仅只读校验真实原H5的7个历史目标，创建新本地私有索引清单（不记录OHLCVA）：

    cd D:\ChatGPT\AStockDataTools; $rid=[Guid]::NewGuid().ToString("N").Substring(0,12); $out="H5ParquetReconciler\reports\pre2011-historical-native-targets-$rid.json"; .\.venv\Scripts\python.exe H5ParquetReconciler\tools\qualify-pre2011-historical-native-h5-targets-readonly.py --root "D:\stock" --full21-safe "H5ParquetReconciler\reports\pre2011-full21-verify-9bba81ed3c33.json" --run-id $rid --out $out --read-only-historical-native-targets; if ($LASTEXITCODE -ne 0) { throw "历史原生H5目标资格检查失败" }; $r=Get-Content $out -Raw | ConvertFrom-Json; if ($r.sample_count -ne 7 -or $r.private_raw_original_h5_integer_rows_identical -ne $true -or $r.hikyuu_native_driver_called -ne $false -or $r.purchased_parquet_opened -ne $false -or $r.original_h5_file_stat_unchanged -ne $true -or $r.historical_native_units_or_securities_certified -ne $false -or $r.production_or_private_active_pointer_modified -ne $false) { throw "历史H5资格检查数量或安全门禁异常" }; Write-Host "7个历史原生H5样本资格SAFE：$out"

如果7条均能成功，后续才开始新一轮隔离core311原生历史KRecord/HMAC验证：根据私有清单中真实存在的H5股票原生索引构造严格有界的index Query，不使用近期64根、不能假定SH600000上市于1992；只比较HMAC，不输出解码数值，不使用原生产SQLite。当前没有完成C++读取或任何供应商标准化认证。

本次请只上传**SAFE报告和测试日志**，不要上传私有清单（里面有具体历史股票代码/日期）或任何市场数据、商业Parquet、原始H5。