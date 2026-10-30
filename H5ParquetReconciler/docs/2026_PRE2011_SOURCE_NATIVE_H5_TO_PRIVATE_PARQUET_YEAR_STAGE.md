# 1990—2010历史A股日线：先无损保留H5原生数值到私有Parquet，后续再统一量价单位

## 本轮验收依据（PR #170）

2026-10-30 Windows用户实测 `test_inventory_pre2011_h5_parquet_day_readonly.py` **16项OK（1项因Windows符号链接创建权限跳过；6.274秒）**，真实`D:\stock` SAFE `H5ParquetReconciler/reports/pre2011-h5-purchased-day-inventory-d555bf7a707a.json`：

- 原H5 1990-12-20～2010-12-31，共**3,682,327条A股代码前缀候选日线**，沪市2,056,452、深市1,625,875；选中4,621个H5证券数据集，完整扫描16,041,861条日线时间键。
- 原购买Parquet日线目录全部24个Parquet、139个RowGroup均有真实`ts`最小/最大统计值，**最早2011-01-04**；在**当前已扫描的`AllCycleAStockData/day`目录**没有任何2011年以前时间键。不代表其他未纳入的商业数据源或历史证券主数据。
- 所有原H5/购买Parquet文件、私有活动指针、正式查询路径未改。该旧SAFE **没有**证明H5原生价格、量额物理单位或1990年代历史证券身份/复权口径。

PR #170 已合并main：`ffb3edb`。

## 为什么第一步只做“原生整数值无损存档”

以前`stage-h5-only-day-to-parquet.py`针对2026日线使用H5价格÷1000、成交量×100、成交额×1000的**候选换算系数**，但这些系数在**1990—2010历史日线**尚未获得独立来源证明，不能直接把368万条老H5数据按该猜测转换为与购买Parquet一致的正式OHLCVA。

本轮新增`tools/stage-pre2011-native-h5-year-to-private-parquet.py`，采用**保留原H5原生整数值**的临时私有Parquet结构：
`symbol` + `datetime` + `openPrice` + `highPrice` + `lowPrice` + `closePrice` + `transCount` + `transAmount`。日期键为原`YYYYMMDD0000`无符号64位整数，价格量额均为**原始整数，不做放大/缩小/浮点四舍五入**，这不是购买Parquet的`ts/open/high/.../volume/amount`兼容schema。

工作流程：

1. **`--action plan`**：要求传入原始1990—2010来源SAFE，重新全量只读审计同一`D:\stock`原H5所有A股候选日线日期键以及**购买day目录所有Parquet文件的ts footer**，逐字段/年对账旧SAFE和源文件stat指纹。对某一年输出实际审计原H5条数、原购买Parquet无旧日期、来源报告SHA；**不会生成任何真实行情副本**。
2. **`--action stage --allow-private-raw-parquet`**：相同全来源gate再次通过后，读取指定年份的原H5真实uint日线字段；每批最多8192条，检查原生日日期/严格有序和完整行数，不经候选量额缩放，在**全新**`work/unified_parquet/pre2011_native_h5_raw/native_pre2011_<year>_<hex>/h5-native-day.parquet`写入真实原生整数。写出后**读取整份私有Parquet并逐条比较所有整数与H5输入时的顺序流SHA256**，另外登记Parquet文件SHA。若失败，删除本次新建的不完整私有stage，不碰源文件。
3. 源H5/PQ写前写后均复核大小和mtime（是**源stat指纹，不是完整内容SHA**），该私有manifest登记审核SAFE的SHA、年份、源行数、市场归类和Parquet/原生行流SHA。仅`reports/`的脱敏SAFE可上传，真实股价/量额、具体股票代码只存在本机git忽略`work/`。原购买Parquet和原H5全部只读，不启用私有active pointer，不影响外部查询，也不会替换历史主数据。
4. 无论plan还是stage都比对源数据文件集合及其大小、mtime；尤其在stage前后重新枚举购买Parquet文件。如果**新的购买日线文件在写出过程中出现**，即使之前登记的24个文件没有变化，也拒绝发布并只清理本次新建的私有stage。这避免将新到货但可能包含历史键的Parquet数据错误认作H5独有。上述源校验仍非文件内容哈希认证。\n5. 该raw stage**不能直接作为正式统一Parquet的购买格式分区，也不能用于新的H5镜像**。它只建立可信的跨格式无损备份/转换中间层；后续仍需独立验证H5日线价格量纲、成交量/金额、除复权口径外的股票上市时间/退市证券身份，然后按明确的单位/复权规则生成真正`ts/symbol/open/high/low/close/volume/amount`兼容的新私有分区。原购买日线永远有键优先，不允许修改任何原购买分区。
6. 这次为**一年一次**的有界开发工具，最多500,000条/单年；不要一次性把1990—2010全部368万条视为完全合规地物化。首轮优先选**1990年**真实H5，仅24条候选旧日线，核查后再逐年开展；每个年份都需要不同的新stage目录和SAFE输出，禁止覆盖。

新建16项合成h5py/PyArrow集成测试，使用历史时间范围的虚构H5、购买Parquet及真实模块旧SAFE流程，验收源无更改、原始uint价格/量额逐字段存储、全流hash/Parquet回读、旧报告被篡改、来源突然出现2010年Parquet记录、目录和年份越界、错误键及私有输出防重等。**Windows尚未执行，PR保留Draft**。

## 下一步Windows仅跑合成测试与1990年只读计划

首轮命令（**单行PowerShell**，测试通过再查原始1990年来源；不会写入真实私有Parquet）：

```powershell
cd D:\ChatGPT\AStockDataTools; git fetch origin; if ($LASTEXITCODE -ne 0) { throw "fetch失败" }; git switch feat/pre2011-native-h5-year-raw-parquet-stage-20261030; if ($LASTEXITCODE -ne 0) { throw "切换分支失败" }; git pull --ff-only origin feat/pre2011-native-h5-year-raw-parquet-stage-20261030; if ($LASTEXITCODE -ne 0) { throw "更新失败" }; .\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test_stage_pre2011_native_h5_year_to_private_parquet.py" -v; if ($LASTEXITCODE -ne 0) { throw "16项合成测试失败，不访问真实历史源" }; $rid=[Guid]::NewGuid().ToString("N").Substring(0,12); $out="H5ParquetReconciler\reports\pre2011-native-year-plan-$rid.json"; .\.venv\Scripts\python.exe H5ParquetReconciler\tools\stage-pre2011-native-h5-year-to-private-parquet.py --action plan --root "D:\stock" --year 1990 --inventory-report "H5ParquetReconciler\reports\pre2011-h5-purchased-day-inventory-d555bf7a707a.json" --out $out --read-only-market-sources; if ($LASTEXITCODE -ne 0) { throw "1990年真实H5原生Parquet准备gate失败" }; $r=Get-Content $out -Raw | ConvertFrom-Json; if ($r.audited_year -ne 1990 -or $r.audited_h5_native_stockday_rows -ne 24 -or $r.purchased_no_pre2011_day_keys_proven_by_all_footers -ne $true) { throw "1990年真实审计数量不符，禁止写私有stage" }; Write-Host "1990年只读SAFE计划：$out"
```

通过并确认报告后，再执行**明确的真实1990年原生整数私有Parquet副本**（**第二条命令也单行，但仅在上述plan完全通过后**）：

```powershell
cd D:\ChatGPT\AStockDataTools; $rid=[Guid]::NewGuid().ToString("N").Substring(0,12); $out="H5ParquetReconciler\reports\pre2011-native-year-stage-$rid.json"; $stage="H5ParquetReconciler\work\unified_parquet\pre2011_native_h5_raw\native_pre2011_1990_$rid"; .\.venv\Scripts\python.exe H5ParquetReconciler\tools\stage-pre2011-native-h5-year-to-private-parquet.py --action stage --allow-private-raw-parquet --root "D:\stock" --year 1990 --inventory-report "H5ParquetReconciler\reports\pre2011-h5-purchased-day-inventory-d555bf7a707a.json" --private-dir $stage --out $out --read-only-market-sources; if ($LASTEXITCODE -ne 0) { throw "1990年原生历史日线私有Parquet写出未通过" }; $r=Get-Content $out -Raw | ConvertFrom-Json; if ($r.audited_h5_native_stockday_rows -ne 24 -or $r.new_raw_private_year_parquet_created -ne $true) { throw "1990年原生24条副本验收失败" }; Write-Host "1990年私有原生Parquet SHA：$($r.private_raw_parquet_sha256)；脱敏SAFE：$out"
```

**报告中的H5 24条是根据前一轮真实1990年inventory得到的代码前缀候选记录；这不能证明它们都是真实上市A股，也不意味着购买量额精度或复权方案已认证。** 任何原始H5/购买Parquet实际新变更会让来源前后核对拒绝执行，不能使用旧报告强行覆盖原市场分区。

## 进一步的主线

1990年私有raw stage通过后，再做1991—2010年逐年stage验收。与此同时逐年对齐2011—2026年日线**购买优先**，再对齐1min/5min全部时间键。完成数据字典、物理量额单位、复权口径与整数精度核对后，才将历史raw H5分区规范化为购买标准Parquet schema，连同已购买Parquet构成完整主线；最后从主线写到**全新的独立Hikyuu原生H5镜像**，原H5绝不覆盖，通达信留到用户自行更新后处理。
