# 2026-10-29：真实单日日线 float64 → Hikyuu整数刻度的只读精度假说试验

## 已有证据（用户实测）

- 2026-09真实Parquet：day/5min/1min的`ts`角色均为Arrow int64，OHLC/amount/volume全部为float64。
- `test_audit_parquet_int64_footer_timebase_readonly.py`在Windows**10/10 OK（1.725秒）**。真实`parquet-3period-int64-timebase-footer-v1.json`中日期列Row Group最值：day 2/2、5min 47/47、1min 233/233，五种候选里**唯独epoch_ms与282/282个非空Row Group min/max的2026-09月份吻合**，没有缺统计。与仓库已有`pq_stamp(epoch_ms,...)`解析规则相容，但**Footer只看极值**，不等于单条日期编码、独立时区或分钟标签官方语义均已认证。
- 过去完全**合成**Parquet→H5→Hikyuu2.8.1 C++原生读取的6/6一致，所用*Hikyuu驱动解码单位*对应整数刻度是OHLC×1000、amount×10、volume×1；这些**不是**购买Parquet物理单位定义，也没有说明其Float64精度如何量化。

## 本轮工具及范围

`tools/audit-real-parquet-day-float64-h5-tick-candidates.py`

开始真正针对少量真实数值做精度分析，但**只读**、不产生任何H5、不运行商业Parquet大范围扫描：

1. 只允许一个明确的`day/YYYY-MM.parquet`文件、一个ISO交易日（本轮`2026-09-30`）和固定两只试点证券`SH600000`、`SZ000001`，必须先有上轮3周期`epoch_ms`唯一候选SAFE且日期月份一致。只允许从购买Parquet根路径的`day`直属文件读取，拒绝外部相对路径、符号链接及无效格式。
2. 执行严格的Footer、字段类型和行数预检：`ts`必须Arrow int64；`symbol`为Arrow string；六个OHLCVA角色均为Arrow float64；最多32 Row Group、总源记录≤**150000**（2026-09日线此前Footer计118208）。超预算**在读行数据前拒绝**。
3. 仅读取指定日线文件的`ts/symbol/OHLCVA`八列、先在Arrow批量过滤，最终内存中只留**指定交易日两只证券各一条**日线。若0根、重复时间键、非finite float、源文件变化即失败关闭。输入原文件始终只读，唯一输出模块`reports/`下新SAFE JSON。
4. 对每字段只做**假设性刻度适配测试**：假如购买数据数字恰好已经是Hikyuu驱动解码单位，则价格×1000、成交额×10、成交量×1之后能否无舍入落在合法原生整数区间？分别统计：
   - `shortest_decimal_tick_exact_count`：Python `str(float)`所提供的**最短十进制表现**再构造Decimal是否正好落在整数刻度上。
   - `binary_float_tick_exact_count`：原始float64的精确二进制有理数（`Decimal.from_float`）是否真的落在整数刻度上。比如通常的`10.1`在第一种意义可落在0.001刻度，但在第二种意义上不一定是精确的十进制10.1。
   - `would_require_rounding_count`：最短十进制表示要写进该Hikyuu整数刻度时，是否可能需要舍入；`half_tick_boundary_count`识别半个整数刻度的特殊中点；`range_overflow_count`检测uint32/uint64整数范围问题。
5. 每字段只输出这两条实际K线样本的**计数**，**绝不输出**源价格、成交量、成交额、源绝对目录、Parquet原始字段值、任何真实源时间戳、候选写入整数或实际H5。分析期间仅在本机Python内存中保留两条真实K线。
6. 无论样本是否能整数量化，本轮`licensed_parquet_physical_units_certified=false`、`real_float64_to_h5_precision_mapping_certified=false`、`licensed_parquet_to_h5_mapping_certified=false`、`ready_for_full_market_mirror=false`均不会改变。**不存在商业Parquet→真实H5转换的开关**。
7. 原版`query-parquet-primary-readonly.py`有多文件Footer预检及可选私有缓存，本轮只需一份小体量的2026-09日线Parquet，故不调用其9文件预检流程、不开缓存、不产生原始行情落盘。

说明：`Hikyuu解码单位`假说不等于真实Parquet金额的元/万元或成交量的手/股。即便10项字段数值都能整数化，也只能表示在假设尺度下的样本性数值特征，不能自动批准真实写入。

## Windows运行（PowerShell每条命令独立**完整单行**，不使用反引号）

拉取代码：

```powershell
git pull --ff-only origin main
```

运行新增12项**虚构Arrow小文件回归**（等待用户Windows实测）：

```powershell
.\\.venv\\Scripts\\python.exe -m unittest discover -s H5ParquetReconciler\\tests -p "test_audit_real_parquet_day_float64_h5_tick_candidates.py" -v
```

若12项OK，执行**一次**真实日线只读试验（原始购买文件根目录已确认过，无需重新找路径）：

```powershell
.\\.venv\\Scripts\\python.exe H5ParquetReconciler\\tools\\audit-real-parquet-day-float64-h5-tick-candidates.py --source-root "D:\\stock\\AllCycleAStockData" --day-relative "day/2026-09.parquet" --trading-day "2026-09-30" --previous-timebase-safe "H5ParquetReconciler\\reports\\parquet-3period-int64-timebase-footer-v1.json" --out "H5ParquetReconciler\\reports\\parquet-day-float64-h5-tick-candidates-20260930-v1.json" --read-only-one-day-precision
```

如输出报告同名已存在，请改用`v2`新名字，勿覆盖已有报告。只需要回传这份**安全的聚合计数JSON**以及12项测试结果；**不要**上传商业Parquet、原始H5、真实的OHLCVA数值或私有缓存。

## 后续

如果真实日线仅2个样本表现出需要舍入，下一轮优先结合原始采集数据字典、独立H5基准，研究阈值和物理单位转换；如果本轮完全落在刻度上，也不能因两个样本而断定整个2011–2026所有股票日都无需舍入。完全通过才有资格讨论在**另外的隔离临时目录**构建只读源的缩放整数预览（仍不能覆盖用户正式H5或切换生产路由）。

### 数据安全边界

脚本仅一次性读指定**日线月文件**8个已知列、两个指定股票日；检查源大小/mtime执行前后不变，这是stat完整性检测，**不是不可变内容SHA证明**。源码中的Hikyuu整数刻度仅用于模拟量化分析，不写任何数值到H5或任何其他私有市场文件。
