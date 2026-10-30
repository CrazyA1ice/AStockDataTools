# 2026-10-30：1990～2010年原始H5日线年度批量原生整数备份（购买Parquet优先）

## 已有真实Windows结果

- 原H5 1990-12-20～2010-12-31有保守A股代码前缀候选日线 **3,682,327** 条（SH 2,056,452 / SZ 1,625,875），源扫描16,041,861个原生日线datetime键。
- 购买原始`AllCycleAStockData/day`的**24个Parquet文件、139个完整ts footer行组**均始于**2011-01-04**（仅针对扫描过的这一目录）；因此这些文件不包含1990～2010的购买日线，但这仍非历史证券主数据/量额单位认证。
- PR #171 已经用户 Windows **17/17 OK (10.345s)**；真实1990年24条原生日线**完整、无损**写入全新模块私有原生数值Parquet，真实stage SAFE `reports/pre2011-native-year-stage-499b0006339c.json`，私有Parquet SHA `224b6d6f597775c2266df919c58fe18113de44598953b89bd8106b9ba6ca19e1`，源行流SHA `06b17e412b0a92c06bc16b0f269c302a7fa2a89e15551c938cf535f9bbe47223`。原购买Parquet、原H5、活动私有指针及生产查询均不变。PR #171 已squash合并`c1049e3`。
- 用户要求**先将H5独有数据补到新建统一Parquet主线，再从完整Parquet生成独立的新H5镜像**。这次的历史文件仅是**原H5整数的无损RAW中间层**，**不是**与购买Parquet字段兼容的标准化行情，还**不能**作为统一主线正式日线，也不能生成H5镜像。

## 新批量工具的工作方式

新增`tools/batch-pre2011-native-h5-years-to-private-parquet.py`，与已验收的单年`stage-pre2011-native-h5-year-to-private-parquet.py`协作，支持显式1～3个不同年份（1990～2010）：

1. 每个**batch操作只运行一次**旧`inventory-pre2011-h5-parquet-day-readonly.py`对应的**全部H5日期键和全部购买day Parquet页脚**的真实来源重验，而不是每个年份重新扫描1,604万时间键；必须与`reports/pre2011-h5-purchased-day-inventory-d555bf7a707a.json`的每个年度数量/来源stat指纹等相同。年度批次之间仍会分别重验，以防真实源变化。
2. `--action plan`只扫描并完整读取核验**对应年份**已存在的私有RAW Parquet（包括用户1990年独立单年工具生成的分区），核对私有manifest所含source inventory SHA、原H5股日行数、全部uint原始字段类型、SHA256、日期/股票唯一键和逐股日线顺序；输出有哪些年份已完成、哪些尚缺。**不创建行情文件或修改版本**。
3. `--action stage --allow-private-raw-parquet --job-id <12~32位小写hex>`仅对确实缺失的有记录年份创建`work/unified_parquet/pre2011_native_h5_raw/native_pre2011_<year>_<jobid>/`新分区（同年既有已通过全内容核对的stage直接复用）。每个源H5分区流式读8192条完整原生整数，写PyArrow Parquet后全部读回、用源行流哈希证明所有整数和行序正确。不存在行的年份不造空文件。
4. 任何来自购买目录的文件**新增/删减**、已有H5/PQ源文件大小与mtime变化、既有私有文件SHA/字段结构/行数量异常、同一个年份存在两份可验收的私有stage、输出目录碰撞，都**拒绝运行或发布成功SAFE**。本批次中若第2或第3年出错，先前已验收并完成写出的分区会保留，不覆盖也不销毁；下一次选择不同`job-id`可重验复用已完成年份、仅补缺年份。这是真实的“逐年中断可恢复”，不会假设先前所有年已经成功。
5. 最多3年/批、最多750,000条原始日线/批、每年最多500,000条；仅在Git忽略的`work/`产生私有数据，不写购买Parquet或原H5、未修改私有active pointer/生产路由。所有`reports/`只含年份/计数/状态/SHA，无股价、股票代码、原始量额及绝对数据目录。
6. **核心口径仍未认证**：原历史H5候选股票代码非上市历史证券主数据，原生`transCount/transAmount`不能擅自按现代系数转换，复权/交易日与分钟线尚未对齐。私有RAW `symbol/datetime/openPrice/highPrice/lowPrice/closePrice/transCount/transAmount` **不是**购买Parquet标准`ts/symbol/open/high/low/close/volume/amount`，不自动union或转H5。
7. 新增12项全合成H5/PyArrow集成测试，涉及一批只重验一次、两年实际Parquet写出/完整回读、历史1990/1999的单年stage复用、分年失败保留已成功文件及恢复、覆盖保护、原购买新文件到货、输出碰撞/伪造manifest、源清单变化/报告SHA绑定、数量预算等。**尚待Windows实机执行，PR保持Draft**。

## 本地Windows单行命令：先运行12项测试并做1990/1991/1992只读PLAN

```powershell
cd D:\ChatGPT\AStockDataTools; git fetch origin; if ($LASTEXITCODE -ne 0) { throw "fetch失败" }; git switch feat/pre2011-batch-native-h5-year-stage-resume-20261030; if ($LASTEXITCODE -ne 0) { throw "切换分支失败" }; git pull --ff-only origin feat/pre2011-batch-native-h5-year-stage-resume-20261030; if ($LASTEXITCODE -ne 0) { throw "更新失败" }; .\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test_batch_pre2011_native_h5_years_to_private_parquet.py" -v; if ($LASTEXITCODE -ne 0) { throw "12项合成测试失败，不访问真实历史源" }; $rid=[Guid]::NewGuid().ToString("N").Substring(0,12); $out="H5ParquetReconciler\reports\pre2011-batch-native-plan-$rid.json"; .\.venv\Scripts\python.exe H5ParquetReconciler\tools\batch-pre2011-native-h5-years-to-private-parquet.py --action plan --root "D:\stock" --inventory-report "H5ParquetReconciler\reports\pre2011-h5-purchased-day-inventory-d555bf7a707a.json" --years 1990 1991 1992 --out $out --read-only-original-sources; if ($LASTEXITCODE -ne 0) { throw "1990/1991/1992只读批次计划失败" }; $r=Get-Content $out -Raw | ConvertFrom-Json; if ($r.selected_year_source_native_rows -ne 7959 -or $r.historical_all_year_h5_candidate_rows -ne 3682327 -or $r.purchased_compatible_normalized_day_parquet_created -ne $false) { throw "年度实际计数或RAW禁用门槛异常" }; Write-Host "历史1990-1992批次只读SAFE：$out"
```

已知真实审计的1990=24、1991=2043、1992=5892条，合计**7959条**。首次计划若看到1990年`private_raw_parquet_present_and_verified=true`而1991/1992为false是正常的，意味着1990先前文件被安全复用。

## 上述测试/plan全部通过后的显式私有RAW年度批次

```powershell
cd D:\ChatGPT\AStockDataTools; $rid=[Guid]::NewGuid().ToString("N").Substring(0,12); $out="H5ParquetReconciler\reports\pre2011-batch-native-stage-$rid.json"; .\.venv\Scripts\python.exe H5ParquetReconciler\tools\batch-pre2011-native-h5-years-to-private-parquet.py --action stage --allow-private-raw-parquet --job-id $rid --root "D:\stock" --inventory-report "H5ParquetReconciler\reports\pre2011-h5-purchased-day-inventory-d555bf7a707a.json" --years 1990 1991 1992 --out $out --read-only-original-sources; if ($LASTEXITCODE -ne 0) { throw "1990-1992原生历史RAW Parquet私有批次失败" }; $r=Get-Content $out -Raw | ConvertFrom-Json; if ($r.selected_year_source_native_rows -ne 7959 -or $r.remaining_nonempty_missing_years.Count -ne 0 -or $r.purchased_compatible_normalized_day_parquet_created -ne $false) { throw "1990-1992真实年度RAW核验不通过" }; Write-Host "1990-1992原生RAW私有批次完成，脱敏SAFE：$out"
```

批次私有RAW成功不是全历史已统一。1993～2010年尚有真实记录需按年份依次完成新raw stage；之后还要验证**历史量额倍率、正式A股身份/复权口径，输出购买格式兼容的独立标准Parquet**。其余2011～2026年按年补齐、5min/1min对齐，最后从完全验收的统一Parquet转换成全新独立的Hikyuu H5镜像。原购买Parquet和原H5始终只读，通达信后续由用户更新。
