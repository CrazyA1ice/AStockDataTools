# 2026年H5日线—五分钟成交量守恒已实测：下一步定位单一异常并检查Parquet内部

更新时间：2026-10-26。证据来源：用户本机上传的 `h5-day-vs-5min-volume-2026-09-24-30.json`。此报告由上一轮`inspect-h5-day-vs-5min-volume.py`生成、源文件未修改、仅H5数据、不读取购买Parquet。

## 一、实测结论

目标区间 2026-09-24 至 09-30（实际有记录的是09-24/28/29/30），候选A股共**22,192证券—交易日**，H5日线与五分钟两周期**全部均有源记录**，且所有22,192组都满足**1个午夜日线键和48个完整无重复的预期五分钟结束时标**。H5可读取证券dataset无效条目0，`scan_complete=true`。

| 日期 | 完整48根证券—交易日 | 5min成交量×100后与H5日线候选一致（0.1%容差） | 原始日线transCount与原始5min之和完全相等 | 超出容差 |
|---|---:|---:|---:|---:|
| 2026-09-24 | 5,547 | 5,547 | 5,517 | 0 |
| 2026-09-28 | 5,547 | 5,547 | 5,510 | 0 |
| 2026-09-29 | 5,548 | 5,547 | 5,497 | 1 |
| 2026-09-30 | 5,550 | 5,550 | 5,497 | 0 |
| **合计** | **22,192** | **22,191（99.99549%）** | **22,021（99.229%）** | **1** |

**基线：**未经一分钟量纲映射的`sum(H5_5min.transCount)`对比`H5_day.transCount×100`，通过组数**0**。

**候选：**`sum(H5_5min.transCount×100)`对比`H5_day.transCount×100`，有**22,191/22,192**组通过同一0.1%容差，其中**22,021组原始transCount求和完全相等**。其余**171组**原始整数和不完全相等，其中170组在0.1%容差内，**1组在2026-09-29超差**。旧报告只包含该交易日期，**没有证券ID和原始量差**，不能凭估计编造具体股票或误差原因。

与此前H5/PQ 5min双源逐条候选映射的结果互证：H5分钟量×100令1,060,937个旧成交量差降至3,097个、解决1,057,840个旧冲突，完整量价差从1,060,937降至3,440。现在同一H5供应商的day周期也与此方向高度吻合。这依然**不能正式认证提供方单位/上市证券身份/复权或交易所真实成交量**。

## 二、本轮新开发：只保留异常证券+日期，不导出成交量

扩展既有`tools/inspect-h5-day-vs-5min-volume.py`：
- 在日/分钟原始累计与候选条件都不一致时，仅记录最多12条`anomaly_stock_day_examples`，每条只含`symbol`、`day`、固定原因`H5_day_vs_5min_volume_sum_over_0.1pct`，不输出任何成交量、成交额、价格或比值。
- 保留原来所有计数、筛选规则、0.1%容差和`safe_to_automatically_union=false`，不改`D:\stock`或2025年Parquet V3索引。
- 适合只对2026-09-29复查，在精确日范围识别**唯一**的超差证券日以便后续指定证券检验，不必重扫之前四天。

## 三、本轮新开发：购买Parquet内部日线—五分钟量能守恒

新增`tools/inspect-parquet-day-vs-5min-volume.py`，设计目标是**把上一轮只在H5内部做过的验证，独立应用于购买Parquet的两个周期**：
- 使用原有的年度文件发现逻辑，在最多7个日历日内依靠Parquet row-group `ts`统计跳过不相关行组；每批**只读取ts/symbol/volume三列**。不读取购买数据中的OHLC、成交额、不输出任何原始量价数值。
- 只比较同证券同日两个周期都有数据，且Parquet日线恰好一条本地日期键、5分钟符合前述48个不重复候选时标的证券—交易日。
- 并行统计三种不改源数据的换算：`Parquet.day.volume ≈ sum(Parquet.5min.volume)`；`Parquet.day.volume×100 ≈ sum(Parquet.5min.volume)`；`Parquet.day.volume ≈ sum(Parquet.5min.volume)×100`。全部采用**0.1%相对容差、最小绝对容差1**，输出各自通过组数、部分周期缺记录、分钟不满48根、两周期同键重复和异常示例（最多12个证券+日期）。
- 有重复证券时间键或无法识别证券代码时`scan_complete=false`。模型输入只是代码前缀筛选，`unit_mapping_certified=false`，不能把通过组数当成提供方官方字段认证。
- 以上为真实用户数据前的代码实现，新增5项纯合成回归测试（原量纲、日线100倍候选、缺一个周期/分钟不完整、重复键检测、时间窗口上限），Windows本机需执行确认。

## 四、Windows下一步：仅在2026-09-29检查

在仓库 `AStockDataTools` 根目录：

```powershell
git pull --ff-only origin main
.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test*.py" -v
```

测试通过后，先定位H5唯一跨周期异常的证券—交易日：

```powershell
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\inspect-h5-day-vs-5min-volume.py "D:\stock" --year 2026 --from-date 2026-09-29 --to-date 2026-09-29 --read-only --out "reports\h5-day-vs-5min-volume-2026-09-29-anomaly-id.json"
```

再运行Parquet同源跨周期量能对比：

```powershell
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\inspect-parquet-day-vs-5min-volume.py "D:\stock" --year 2026 --from-date 2026-09-29 --to-date 2026-09-29 --batch-size 8192 --read-only --out "reports\pq-day-vs-5min-volume-2026-09-29.json"
```

请上传这两个JSON。若Parquet日线与五分钟线原量纲大多数守恒，H5原始日/分钟总量也大多数守恒，再结合官方单位文档，才可以更有把握地讨论成交量字段转换；剩余3,440个跨源多字段差异仍需定向归因。**不自动并集，不选择一方覆盖另一方，也不改原始数据**。
