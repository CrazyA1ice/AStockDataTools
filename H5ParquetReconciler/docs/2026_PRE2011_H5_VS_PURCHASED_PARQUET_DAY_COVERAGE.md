# 2011年前的历史日线：先证实H5真实覆盖与原购买Parquet是否确实缺失，再补独立私有Parquet

## 已完成的全市场2026年4日期收口

用户Windows **12/12测试OK（7.972秒）**，2026-09-01～10-28实际source/gate完成全市场4个完整H5-only日期（日线）：2026-10-08=5,546，10-09=5,547，10-12=5,549，10-13=5,549，合计**22,191条**。四份已存在的、分别完整回读验收的模块私有Parquet分区全部复用，`staged_new_private_days_this_action=[]`，完成prep不可变逻辑版本`46bd847de3d00c0f48ff50830fa8688547198c6db1a3cf3b10eb7d2261770c03`，**未激活**。真实SAFE `reports/private-complete-day-plan-daaa2040b1cb.json`和`reports/private-complete-day-apply-a743bc19eac1.json`验证原始购买Parquet/原H5未写、私有active和生产路由未改。PR #169已合并main（`a2ddd308`）。

用户本轮指出，**1990—2010年**H5日线可能有记录、购买Parquet可能自2011年才有记录。这是十分重要的增量补齐范围，**但尚未在用户`D:\stock`执行真正旧年份审核**，因此不能将“Parquet早期为空”作为已核实事实。

## 旧年度对账器的限制与本轮新方案

既有`reconcile-local-a-share-h5-parquet.py`默认年度从2011年开始，CLI限制`--years`最早为2000，`YEAR_NAME`仅识别`20xx`文件名；即使`AllCycleAStockData/day`没有单独的2010/1999名称Parquet，也**不能因此推断购买Parquet内部绝无2011以前的行**。旧`plan-parquet-primary-day-bootstrap-offline.py`又限制2000～2030，旧stage只支持经过完整日级差集审核的4日类型，不能直接把整段历史当合格H5-only日期。

新增只读`tools/inventory-pre2011-h5-parquet-day-readonly.py`，以**1990-01-01至2010-12-31**为清晰范围：

1. 对真实`D:\stock\HikyuuData\sh_day.h5`和`sz_day.h5`（有合法bj日文件时一并只读）逐个读取原生`data`下符合保守A股**代码前缀候选**的日线证券dataset，只投影`datetime`字段，每个数据集以至多16,384个时间键的有界chunk流式扫描**完整历史所有日期键**，验证uint64日键结构、所有记录时间严格升序、所有1990～2010的日期有效且是00:00日线键。由**实际每条日期键**逐年统计21年各交易日记录数量、沪深市场数量、每年有记录的股票代码数量，输出**最早/最晚历史H5日期**。不会读取行情数值列或输出原始股票代码；股票代码前缀不是上市退市/复权的正式历史证券主数据验证。
2. 对`D:\stock\AllCycleAStockData\day`下面**所有**现有`.parquet`（含嵌套目录、不以2011/年份命名的文件），不按名称跳过任何年份，只读全部`ts`行组Footer的`min/max`，并在中国时区换算成候选交易日。只要**任意行组最小日期早于2011-01-01**，就标为`pre2011_timestamp_ranges_possible_in_purchased_day_files`，说明存在疑似旧行，需进一步按行/股票做有界核查；不得覆盖这些可能已有的Parquet键。
3. 如果有非空行组缺失或不可读`ts`统计，标为`unknown_pre2011_purchased_coverage_missing_row_group_stats`，**不能声称Parquet在2011年前没有数据**。仅当扫描目录内所有Parquet非空行组的时间戳最小值都不少于2011-01-01（且无缺失统计），才声明`no_pre2011_parquet_rows_proven_by_complete_footer_bounds=true`，**严格限定于这个已扫描的购买日线目录**，并不代表未列出的其他数据目录或供应商历史库存。
4. 不读取任何原始H5/PQ OHLCVA价格、成交量、金额列，不在SAFE输出股票代码/源绝对路径、任何商业行情数字。所有源文件前中后检查大小+mtime稳定（**stat-only摘要不是内容SHA**），没有交易所日历/证券类型/量额单位/复权因子认证，`pre2011_h5_to_new_private_parquet_authorized=false`，**不生成任何新的私有Parquet、不改原始Parquet/H5、不切换私有活动指针/生产查询**。
5. 有界保护：最多20,000个H5候选证券数据集；每块只读16,384个日键；购买Parquet最多512个文件、50,000个行组；全部符号链接/目录逃逸或已读取文件状态变化一律拒绝。旧年份没有行时单独显示为0，不能把全年或停牌日自动变成伪造的交易K线。
6. 提供16项全合成HDF5/PyArrow测试，涵盖1990～2010正确年份分布、2011名称Parquet含2010记录、异常文件名/嵌套分区、缺统计/缺目录、旧H5乱序/重复/日期/00:00结构问题、受保护的SAFE、源变化、符号链接等。**Windows实机尚未运行，PR必须保持Draft**。

## 本轮Windows操作：测试通过才只读检查1990—2010源数据

此命令仅读取原H5时间键及购买全部日线Parquet的Footer；大数据量时耗时取决于原H5日线总记录数，但会限定内存且不会复制用户私有市场值。

```powershell
cd D:\ChatGPT\AStockDataTools; git fetch origin; if ($LASTEXITCODE -ne 0) { throw "fetch失败" }; git switch feat/pre2011-h5-purchased-parquet-day-evidence-20261030; if ($LASTEXITCODE -ne 0) { throw "切换分支失败" }; git pull --ff-only origin feat/pre2011-h5-purchased-parquet-day-evidence-20261030; if ($LASTEXITCODE -ne 0) { throw "更新失败" }; .\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test_inventory_pre2011_h5_parquet_day_readonly.py" -v; if ($LASTEXITCODE -ne 0) { throw "16项历史日线合成测试失败，禁止访问真实行情" }; $rid=[Guid]::NewGuid().ToString("N").Substring(0,12); $out="H5ParquetReconciler\reports\pre2011-h5-purchased-day-inventory-$rid.json"; .\.venv\Scripts\python.exe H5ParquetReconciler\tools\inventory-pre2011-h5-parquet-day-readonly.py --source-root "D:\stock" --out $out --read-only-all-original-day-sources; if ($LASTEXITCODE -ne 0) { throw "真实H5和购买Parquet历史日线核查失败" }; Write-Host "1990—2010只读脱敏SAFE：$out"
```

若测试失败，不运行真实源；若真实日期、H5结构、购买Parquet统计、源状态变化不符，出错即中止，不生成新的`reports/`成功报告。发回控制台结果及本地脱敏SAFE即可，**不能上传购买的原始Parquet、H5或包含OHLCVA的私有stage**。

## 根据真实证据做下一步

- **如果原H5在1990～2010确实有记录，且购买Parquet全部日线文件Footers证明无2011年前时间戳：** 规划以**1990—2010逐年/有界窗口**只读H5完整性审核，明确各年的股票/日期键与H5价格/量额物理口径，再按分区生成**新的、git忽略的模块私有Parquet**，与2011～2026购买主源形成统一逻辑视图。原购买数据一字节不改；每年的新增分区需真实SHA、原H5后续复核、逐行Parquet回读和历史A股代码有效性核对，禁止仅以此inventory工具直接批量写入。
- **如果某些Parquet文件Footer显示覆盖2010以前或时间戳统计未知：** 先对对应文件按月/年有界扫描实际`ts/symbol`键，Parquet有键时优先，只有其缺失记录才允许把H5作为后备；不能把整个早期历史H5强行当成无重叠新数据。
- 与此同时，2011～2026年日线也仍需逐年覆盖/混合日期键审计；`5min`和`1min`必须各自单独对齐。**统一Parquet目标范围与数值精度等全部验证完后才制作独立新H5镜像**，任何原H5/原购买Parquet及生产路线均不得覆盖。通达信盘后由用户将来自行更新后再对接，当前不纳入。
