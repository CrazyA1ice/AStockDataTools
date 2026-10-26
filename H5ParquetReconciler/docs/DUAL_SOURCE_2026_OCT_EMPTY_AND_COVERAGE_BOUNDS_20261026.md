# 双源五分钟主线：2026年10月空窗口与高效真实时间覆盖定位

更新时间：2026-10-26。数据来自用户上传的本机只读报告，不包含采购源OHLCV或H5行情记录。项目`CrazyA1ice/AStockDataTools/H5ParquetReconciler`。

## 一、实际上传的2026-10-19至10-23双源窗口结果

上传的`h5-parquet-5min-2026-10-19-23-latest-gap.json`和同名Markdown报告：

| 项目 | 结果 |
|---|---:|
| 年份/周期 | 2026 / 5min |
| A股候选证券范围 | `a-share-candidate`，仅代码前缀判定 |
| H5记录 | **0** |
| Parquet记录 | **0** |
| 重叠键、两方向独有、量价冲突 | **全部0** |
| 2026 Parquet候选文件 | **9** |
| RowGroup总数 | **407** |
| 被2026-10-19至23日时间过滤跳过 | **407** |
| `scan_complete`/`issues` | `true` / `[]` |
| H5/Parquet源文件修改 | `false` |

这说明**当周没有从当前两个本地文件集合中找到五分钟候选股票记录**，但`scan_complete`只表示这次窗口按约定完整执行且无显式I/O/Schema错误。既不等于供应商全年数据完整，也无法推出H5是否最近更新、两边真正最后一个交易日，或两源更早重叠时是否一致。本报告仍保留`security_master_certified=false`、`source_units_certified=false`和`safe_to_automatically_union=false`。无记录的原因可能是未下载、源文件时间范围尚未覆盖或其他供应商分区/源状态，不能直接宣称数据错误。

## 二、为什么暂停继续盲猜2026日期

此前已对2025-09-26、29、30做过**真实有记录的三日全A股候选核对**：H5 779,568根、Parquet 782,352根、时间重叠779,568根、H5独有0、Parquet独有2,784根、重叠值冲突461,937根（59.26%）。用户要求尽快对比两源，因此下一步应直接寻找**真实存在的2026交集窗口**，而不是继续盲猜10月日期、续建2025 Parquet V3 67/522组或优化SQLite计时。

## 三、本轮新增源覆盖时间边界探针

`tools/inspect-h5-parquet-coverage-bounds.py`：
- H5逐市场读取候选证券数据集的**最早/最后日期字段**；仅在数据跨越指定年份时对按时标排序的数据集执行二分查找年度边界，不读取OHLCV数组、不输出原始行情值。输出年度候选证券dataset数量、存在年度数据dataset数量、最早/最晚时间和dataset末记录所属月份的聚合计数。`sorted_dataset_assumption_not_independently_certified=true`提醒来源排序仍是前提。
- Parquet使用与主对账程序一致的年度文件发现逻辑，仅读取**Parquet文件和RowGroup footer中的ts min/max**，不读取row group数据行；记录每文件行组数和时间包络，以及缺失/不可信ts统计的数量。起始时标+5分钟仅为工作假设。
- 只有H5市场文件完整、候选数据集时间列可读、Parquet所有非空行组都有可用ts footer、双方日期包络有交集时，才提出**不超过7个日历日的最新日期候选对比窗口**（`suggested_bounded_window`）。明确该建议仅由时间边界算得，`proves_real_overlap=false`；若两端不相交或footer统计不足，返回`available=false`，不得臆造日期。
- 强制`--read-only`，源根目录不能包含任何输出，报告限制在模块`reports/`下，禁止覆盖现有JSON。无新SQLite、无修改主索引、无Parquet行情行扫描、无自动并集。

新增4项纯合成离线测试：跨年H5二分边界、候选窗口受两个来源较早截止约束、不完整源/无可信footer时拒绝推荐，以及真实H5合成dataset+模拟Parquet footer集成路径。请以Windows本地测试结果确认。

## 四、下一次本机只做最小证据采集

在仓库根目录：

```powershell
git pull --ff-only origin main
.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test*.py" -v
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\inspect-h5-parquet-coverage-bounds.py "D:\stock" --year 2026 --read-only --out "reports\dual-source-5min-2026-date-envelopes.json"
```

**请先提供`dual-source-5min-2026-date-envelopes.json`。** 依据`suggested_bounded_window`挑选真实候选重叠窗口后，用已经验证的`reconcile-local-a-share-h5-parquet.py`一次性跑对应2026年5min双源覆盖/冲突对账；不重复无意义的空窗口扫描。如果窗口建议不可用，报告会明确指向缺失源文件或footer问题，先定位范围问题而不是扫描。

若近期更想直接定位历史互补，现成的另一条安全主线是重扫2025-09-26至30三日窗口，使用新加的`stock_day_gap_summary`准确分解2,784根Parquet独有键中，多少是整证券日H5无数据、多少是当日部分五分钟键缺失。2025数据已知两源都有记录，这一路径不依赖2026包络结果，且不需要先完成2025年度V3索引。

目标始终是**真实时间键交集、双向独有、重叠OHLCV差异与数据源截止日期**，在时间、量额、复权、证券主数据未独立认证前，禁止输出正式自动并集或将候选缺口当成已认证的历史漏数。
