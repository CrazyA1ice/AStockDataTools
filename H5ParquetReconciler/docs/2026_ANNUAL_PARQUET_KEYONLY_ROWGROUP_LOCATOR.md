# 2026-10-30：2025年度Parquet的RowGroup时间包络全重叠，使用有界键列定位

## 真实证据（非猜测）

用户Windows已运行第148轮新增的7项合成阶段诊断测试并全部通过（13.579秒）；真实诊断`real-h5-parquet-crossyear-2025-2026-diagnostic-v1.json`明确显示：

- `status=blocked`、`last_stage=annual_target_rowgroup_selection`。
- 2025年度日线 Parquet 源Footer：**1,333,385行，12个RowGroup**。
- 仅通过`ts` Footer的区间交集判断，**12/12组**都可能含2025-09-30。旧读取器只允许最多2个匹配组，故安全拒绝。这**不是**跨源倍率不匹配，也不意味着股票日线记录不存在。
- 原报告`source_files_stat_or_footer_unchanged=true`，之前三份SAFE前置检查通过；**真实行情还未获得跨年4条验证结果**，供应商物理单位与生产转换仍未认证。
- 12组的时间范围全部覆盖同一个目标日期，**可能**是按证券或其他方式交错布局。Footer不足以推断真实存储排序，不能随意增加读取范围到全量OHLCVA。

## 本轮新增方案：只读两列全年度键扫描，保留原OHLCVA预算

工具：`tools/probe-real-2025-annual-day-keyonly-readonly.py`

- 独立于第145-147轮生产跨年读取器，并不修改、扩大既有`2025年度目标OHLCVA≤150000行、≤2RowGroups`限制。当前工具**完全不读取开高低收、成交量、成交额、原始H5、生产SQLite**。
- 固定只打开合法的`D:\\stock\\AllCycleAStockData\\day\\2025.parquet`，先再次验证三份此前真实SAFE（9月30日原生2/2、同日跨源2/2、9月28/29留出4/4）和年度Parquet源是否安全。
- 从年度Parquet**只投影`ts`和`symbol`两列**，实际最多解码**1,600,000条键**、最多16个RowGroup、分批最多16,384键，任何空行组/列不符合类型/超预算均安全阻断；不将任何键、具体股票标识、原始时间戳写入SAFE。真实旧Footer的133万行落在该明确授权的**键列读取预算**内，但它**不等于可以读取133万条OHLCVA**。
- 目标仍严格固定2025-09-30（北京时间日界）、SH600000/SZ000001，每个目标股票日必须精确命中一次；从所有行组中只计算哪些组实际含该目标键、目标组数量和目标组的Footer行数总和，不存储行组编号、真实行情值或代码。
- 新SAFE汇总`key_only_rows_scanned`、`selected_target_rowgroups`和`selected_target_rowgroup_total_rows`以及固定安全状态。若目标没有精确2条、重复或者被记录在超过2组，报告相应`no_target_keys`、`duplicate_target_keys`、`selected_price_group_count_exceeds_budget`；如果实际目标组总行数超过15万，则报告`selected_price_rows_exceed_budget`，**本轮仍不读OHLCVA**，下一阶段再设计不放宽预算的进一步定位方案。
- 只有`status=ready_for_bounded_price_group_read`才说明**键已定位、对应行组处于旧OHLCVA预算内**，仍不代表本次验证已经读取到任何目标价量额、不代表此时已经完成跨年倍率匹配。后续需要将键定位结果用于主工具受控读取，同时保留跨组重复键检查。**当前工具不会自动将诊断结果写回主工具或据此授权格式互转。**
- 报告会核对源Parquet Footer与size/mtime前后不变，**不保证整文件SHA256验证**。只写项目模块的`reports/`中新SAFE文件，采用独占创建，若路径已占用不会删除或覆盖用户文件；任何Python/PyArrow异常不得带出源路径、原始行数据或堆栈信息。
- 新增**12项全部使用虚构Parquet源的合成测试（Windows尚待实测）**，包括人工让12/12 RowGroup的Footer minmax同时覆盖9月30日、但键列只在一个RowGroup实际出现目标两股的情况、跨组目标键定位、重复键拒绝、缺键拒绝、严格150000行价格扫描预算保留、源缺失、伪造SAFE、输出不可覆盖。

## Windows PowerShell执行

先拉取GitHub main：

```powershell
git pull --ff-only origin main
```

运行12项新增的合成键列回归：

```powershell
.\\.venv\\Scripts\\python.exe -m unittest discover -s H5ParquetReconciler\\tests -p "test_probe_real_2025_annual_day_keyonly_readonly.py" -v
```

检查输出名是**新**文件：

```powershell
Test-Path "H5ParquetReconciler\\reports\\real-2025-annual-parquet-day-keyonly-20250930-v1.json"
```

只有12项测试`OK`且新文件不存在才执行：

```powershell
.\\.venv\\Scripts\\python.exe H5ParquetReconciler\\tools\\probe-real-2025-annual-day-keyonly-readonly.py --parquet-root "D:\\stock\\AllCycleAStockData" --prior-raw-safe "H5ParquetReconciler\\reports\\real-parquet-h5-raw-day-unit-factor-candidates-20260930-v1.json" --prior-native-safe "H5ParquetReconciler\\reports\\real-hikyuu-native-20260930-hmac-v3.json" --prior-heldout-safe "H5ParquetReconciler\\reports\\real-h5-parquet-heldout-day-factors-20260928-29-v1.json" --out "H5ParquetReconciler\\reports\\real-2025-annual-parquet-day-keyonly-20250930-v1.json" --key-only-read-2025-annual
```

注意：本轮将按明确的键列预算扫描一年133万条`ts/symbol`键，不会打开真实H5或任何OHLCVA列，故与之前仅元数据诊断不同，但依旧只读、按batch受控。上传**仅脱敏SAFE**和12项测试日志；不要上传商业源Parquet、原始H5或仓库下scratch。

## 下一步

- 若命中目标组数为1/2且其Footer总行数≤150000，可以设计受限、跨组重复键可验证的读取器，让2025与2026跨年四条样本真正进入候选倍率检验。
- 若目标组数≤2但总行数>150000，优先研究RowGroup内的列页级别索引/精确下推与可证明实际读取范围，**不要把133万键扫描偷换成读取133万行全部行情**。
- 若两只固定股票在2025-09-30未匹配或重复，应保留失败结果，先核对历史覆盖、键别名及真实日期语义，绝不换一个更容易通过的样本或修改H5。
