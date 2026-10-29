# 2026-10-29：真实Parquet int64日期的Footer时间基准候选核对

## 前置：Windows已实测的事实

- `test_probe_parquet_arrow_footer_schema_readonly.py`：**17项中16项ok、1项因Windows符号链接权限跳过**（1.859秒）。原生小合成Footer集成测试已实际成功。跳过不视作已覆盖。
- 已读取2026-09真实day、5min、1min三份Parquet的Footer，字段`datetime`候选日期角色均是Arrow **int64**；Open/High/Low/Close/Amount/Volume全部 **float64**。原始Arrow int64只表明存储，不表明Unix秒/毫秒/微秒/纳秒或YYYYMMDD格式。
- 三周期Footer行组/记录数分别为2/118208、47/5685792、233/28547414。现有4个跨周期脱敏历史窗口差异很小，但`fully_aligned_window_count=0`，缺交易日闭市/复权、供应商物理单位证明；`licensed_parquet_to_h5_mapping_certified=false`。
- 源代码`tools/reconcile-local-a-share-h5-parquet.py`中`pq_stamp(epoch_ms,period)`按UTC epoch毫秒转换到UTC+8，`tools/query-parquet-primary-readonly.py`的`day_bounds()`也用`timestamp()*1000`生成查询界限；此前真实只读核对在这些假设下成功得到符合交易日的观测。**这属于旧代码所采用并通过样本核对的时间规则，不是供应商规格认证，也不能仅据此肯定全部历史文件的一致性**。

## 新增轻量Footer验证

`tools/audit-parquet-int64-footer-timebase-readonly.py`

此工具只读取你明确指定的三份2026-09文件的**Parquet Footer**、日期列的**Row Group min/max统计范围**，不读取任何K线值，不打开其他源数据文件，也不修改任何真实行情源。各文件必须与上次v2 SAFE记录的文件大小、Footer长度、行组数、总行数一致，且确实包含唯一的int64日期字段。只采集**统计边界**、不输出任何真实时间整数、日期行、行情OHLCVA、列自由文本元数据或用户源文件名/目录。

对每个有可用统计量的非空Row Group，分别测试候选规则：
- `epoch_s`、`epoch_ms`、`epoch_us`、`epoch_ns`：UTC Unix时间戳按相应比例解释，再转UTC+8，检查**上下界都落在相同的文件命名月份**。
- `calendar_yyyymmddhhmm`：仅测试12位直写的年月日时分编码是否有效且上下界落在文件月份，**不认定这种候选已经真实发生**。

报告只输出每个候选**符合月份的Row Group数量**、具有有效int64最值的行组数、缺失统计的行组数、哪些候选覆盖了全部可用上下界。遇到缺统计、多个候选符合、输入文件改变都显式显示且不得认证。即使唯一候选是`epoch_ms`，`date_raw_calendar_encoding_certified`、`date_time_label_semantics_certified`、`source_timezone_semantics_certified`、`parquet_real_float64_to_h5_precision_certified`和商业镜像允许标记**永远为false**：Row Group极值不是每行的真实性证明，也不能证明5分钟起始/结束标签的官方语义。

## Windows命令（每条PowerShell指令都是独立完整单行）

项目根目录：

```powershell
git pull --ff-only origin main
```

```powershell
.\\.venv\\Scripts\\python.exe -m unittest discover -s H5ParquetReconciler\\tests -p "test_audit_parquet_int64_footer_timebase_readonly.py" -v
```

期望新增10项合成PyArrow测试全部OK，但**这仅是开发阶段目标，不是已经取得的运行结果**。

运行真实2026-09三份Footer的只读检查：

```powershell
.\\.venv\\Scripts\\python.exe H5ParquetReconciler\\tools\\audit-parquet-int64-footer-timebase-readonly.py --source-root "D:\\stock\\AllCycleAStockData" --day-relative "day/2026-09.parquet" --min5-relative "5min/2026-09.parquet" --min1-relative "1min/2026-09.parquet" --previous-schema-safe "H5ParquetReconciler\\reports\\parquet-3period-arrow-schema-footer-v2.json" --out "H5ParquetReconciler\\reports\\parquet-3period-int64-timebase-footer-v1.json" --footer-date-stats-only
```

只输出一个新的、位于`H5ParquetReconciler/reports/`的脱敏JSON。如果同名报告已存在，改用`v2`新名；不要删除或覆盖任何已有报告。无需上传商业Parquet、原始H5或用户绝对源路径。

## 后续步骤

如果此报告显示三周期均为唯一`epoch_ms` Footer候选，说明独立于旧查询代码的**元数据边界**对毫秒规则提供了进一步支持。下一轮可结合已完成的`2026-08-24`、`2026-09-30`真实日期网格报告及现有代码建立日期解析规则的多证据契约，但仍不得推定已认证供应商时区/分钟标签。另需开展实际**float64→Hikyuu缩放整数的保守精度误差研究**及独立源成交量/成交额物理单位证据，正式镜像写入仍关闭。

所有报告输出都不应包含用户私有源路径、原始浮点OHLCVA值或准确Parquet行级时间戳极值。
