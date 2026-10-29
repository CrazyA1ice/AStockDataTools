# 2026-10-29 — 三周期真实 Parquet Footer/Arrow Schema 严格只读试点

## 已完成的历史证据及本轮范围

1. 用户此前在 Windows 实际验证了**合成** Parquet→H5→Hikyuu2.8.1 C++原生读取，6条K线完全匹配；这并不能证明购买Parquet的成交额/成交量物理单位。
2. `audit-sanitized-parquet-h5-unit-evidence.py` 的11项离线测试OK；`derive-sanitized-unit-evidence-from-existing-three-period-reports.py` 的8项离线测试OK（0.356秒）。历史真实只读三周期结果提取到4个stock-date窗口，4/4跨周期汇总差很小，但`fully_aligned_window_count=0`，`ready_to_plan_independent_unit_check=false`，因缺Schema/时间类型、完整收盘或复权证据、独立物理单位文档。
3. 本轮只新建`tools/probe-parquet-arrow-footer-schema-readonly.py`，要求用户显式指定**同一个购买Parquet目录中的3个文件**（day、5min、1min），只打开每个文件最前4字节、最后8字节以及PyArrow所需的Parquet **footer/Arrow Schema元数据**，不调用`read_table`/`read_row_group`/`iter_batches`，不读取任何OHLCVA数据行，不打开/修改Hikyuu H5、stock.db、正式SQLite或工作流，不使用任何在线Actions。
4. 为防止旧Windows临时文件句柄问题，`pq.ParquetFile`在`finally`显式`close()`。Parquet footer必须有`PAR1`头尾且footer长度≤16MiB，检查源文件大小和mtime在执行前后不变；**注意：stat不变只说明扫描期间未发现源变化，绝非源内容SHA认证，也不能检测恶意竞态。**
5. 不做目录递归/大盘扫描。只接受**现有真实源根目录的绝对路径**，相对路径必须严格为`day/<name>.parquet`、`5min/<name>.parquet`、`1min/<name>.parquet`，拒绝符号链接及穿越目录。输出只允许模块`reports/`中新文件，用`open('x')`防止覆盖。
6. 只提取固定字段角色的Arrow数据类型、受限时区标签，以及每个文件的footer长度/总行数/row group数/大小；不输出任何不在白名单内的字段名、自由文本元数据、实际原始行情、用户源绝对路径、源Parquet文件名。遇到同名字段多个别名、异常time或不在审核器支持的Arrow类型，一律填`unknown`。特别注意：`timestamp[ns,tz=Asia/Shanghai]`只表明Arrow类型声明；时间**标签规则**仍需独立论证，不能由Schema证实所有分钟线开/收时刻含义。
7. Arrow Schema**不能证明**`amount`是元还是万元、`volume`是股还是手。任何输出都将`amount_unit_declared`/`volume_unit_declared`设为`unknown`，`licensed_parquet_to_h5_mapping_certified`/`ready_for_full_market_mirror`始终`false`。已有历史4窗口的`closed_session=false`、`same_adjustment_basis=false`也保持不变。

## 输出

若顺利完成，会产生**三个全新SAFE JSON**，全部位于 `H5ParquetReconciler/reports/`：

- `parquet-3period-arrow-schema-footer-v1.json`：结构化元数据，仅保存常见列角色是否找到、允许的Arrow类型/时区、行组数量等；不含行级行情或源路径。
- `sanitized-parquet-h5-with-real-footer-schema-v1.json`：保持历史两股×两日期4窗口完整不变，将先前的 `unknown` schema类型补充为**真实footer观察值**；真实资金/量单位和独立时段、复权证据仍然未知。
- `parquet-h5-unit-evidence-with-footer-assessment-v1.json`：再次运行现有严格脱敏证据审核；若字段类型补全，一类阻碍`missing_parquet_schema_type_or_timezone`可消失，但其余独立证明仍不可跳过。

## Windows运行

**先拉取主分支，运行12项新测试：**

```powershell
cd D:\\ChatGPT\\AStockDataTools
git pull --ff-only origin main
.\\.venv\\Scripts\\python.exe -m unittest discover -s H5ParquetReconciler\\tests -p "test_probe_parquet_arrow_footer_schema_readonly.py" -v
```

期望12项OK，**其中真实的小合成PyArrow Parquet footer测试不能是SKIPPED**，否则本轮的元数据读取没有验证。注意离线测试只创建小型虚构文件，不读取商业行情。

真实只读试跑前，确认同一数据目录中2026年9月的三个文件存在。根据你前次提供的footer清单，路径**相对于购买数据的AllCycleAStockData根目录**应分别是：`day/2026-09.parquet`、`5min/2026-09.parquet`、`1min/2026-09.parquet`。先在你的本机查明原购买目录绝对路径，不要把路径/文件传到GitHub或聊天，不要修改源文件：

```powershell
$ParquetRoot = "D:\\YOUR_PRIVATE_DATA_ROOT\\AllCycleAStockData"  # 请自行替换成本机真实绝对目录
Test-Path "$ParquetRoot\\day\\2026-09.parquet"
Test-Path "$ParquetRoot\\5min\\2026-09.parquet"
Test-Path "$ParquetRoot\\1min\\2026-09.parquet"
```

**三个 Test-Path 都为True后**，才执行只读元数据程序：

```powershell
.\\.venv\\Scripts\\python.exe H5ParquetReconciler\\tools\\probe-parquet-arrow-footer-schema-readonly.py --source-root "$ParquetRoot" --day-relative "day/2026-09.parquet" --min5-relative "5min/2026-09.parquet" --min1-relative "1min/2026-09.parquet" --existing-sanitized "H5ParquetReconciler\\reports\\sanitized-parquet-h5-unit-evidence-from-existing-v1.json" --schema-out "H5ParquetReconciler\\reports\\parquet-3period-arrow-schema-footer-v1.json" --enriched-out "H5ParquetReconciler\\reports\\sanitized-parquet-h5-with-real-footer-schema-v1.json" --assessment-out "H5ParquetReconciler\\reports\\parquet-h5-unit-evidence-with-footer-assessment-v1.json" --footer-metadata-only
```

如果任一SAFE输出文件已存在，则**三个输出名称全部改成v2**，不覆盖旧记录。源路径只在本机命令参数使用，不被程序写进SAFE。成功后，请仅上传`parquet-3period-arrow-schema-footer-v1.json`和`parquet-h5-unit-evidence-with-footer-assessment-v1.json`；可以附上12项测试结果，**不上传原始Parquet、H5、SQLite或真实源目录/路径**。

## 预期与后续研究重点

- 当前Arrow的具体字段名/数据类型不能从旧报告推定，因此`unknown`是合理结果，尤其应防止把整型`date`推断成`YYYYMMDD`或把naive timestamp自动推断为北京时间。
- 若经此次footer取证补上实际Schema，接下来要寻找供应商数据字典、单位说明、前/后复权定义，并设计按同一股票与同日比对独立原H5基准的**少量只读验证**。
- 即使看到日线与两个分时周期在Parquet内部金额和量一致，也不等于已证实与Hikyuu物理单位完全相同，**严禁启动真实镜像写入**。
