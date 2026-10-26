# 返回主线：真实H5 ↔ Parquet五分钟全市场双源核对（2026-10-26）

## 背景与主线目标

用户明确要求尽快推进两套本地行情数据的覆盖和量价对比，而不是继续把大部分工作用于SQLite索引微优化。本机付费来源`D:\stock\AllCycleAStockData`、Hikyuu H5来源`D:\stock\HikyuuData`始终只读，原始OHLCV及1GB+年度文件不能上传GitHub。

2025-09-30已有的全市场单日A股候选报告（见`5MIN_DAY_20250930_FINDINGS.md`）记录H5 259,872根，Parquet 260,832根，当前“PQ原始五分钟起点+5分钟=H5终点”规则下重叠259,872根、Parquet独有960根、H5独有0根、匹配键量价有差异151,099根（58.14%）。这是**实测差异**，但证券代码前缀、五分钟时标、金额量纲与复权口径尚未通过外部认证，不可直接自动合并。

本轮用户上传`pq-5min-2025-v3-commit-67.json`：主Parquet V3索引推进到67/522组（12.84%），本轮新增5组614,400源行、48.203秒，SQLite阶段32.454秒，退出COMMIT边界20.016秒，累计A股候选源行8,237,762；`report_detail=progress`使最新精确唯一键/重复键仍为null。本轮源指纹没变、时间和容量预算未触发、停因max_new_groups。**这是单源部分索引，不是两源覆盖对比，主线不需要先完成522组索引才可以继续有限窗口双源核对。**

## 本轮新增代码功能

沿用`tools/reconcile-local-a-share-h5-parquet.py`，不另建一套相互矛盾的对账逻辑：

1. `check_batch`新增仅含`(证券代码,标准时间键)`的临时SQLite `pq_seen`集合。跨批次/RowGroup/文件出现重复Parquet键时去重、计数并置为`issues`，不能把重复行当成独立的重叠或Parquet独有记录；批次内重复也去重与报警，避免原程序重复计算。
2. 原`by_day`字典进一步包含每个交易日的`h5_unique`、`parquet_unique`、`matched`、`intersection_unique`、`union_candidate_unique`、`h5_only`、`pq_only`、`value_mismatch`、`price_mismatch`、`quantity_mismatch`和`overlap_value_mismatch_pct`。对每一天检验 **H5唯一键=重叠+H5独有；Parquet唯一键=重叠+Parquet独有**（1分钟09:30另计候选类别）。
3. 累计`pq_unique_keys`、`pq_duplicate_keys_across_batches`等字段将明示确切核验边界。`scan_complete`仅在所有源/Schema/重复键检查无异常时成立；年度空H5导致的Parquet-footer元数据估计仍不能误称精确差集。
4. 两项纯合成测试：跨两个Arrow批次的重复键只核对一次、以及9/26—9/30多日按天重叠与双向差集守恒。无付费行情行或原始数值写入报告。

**性能原则：** 仅针对有界日期范围，H5通过每只证券时间有序区间二分读取；Parquet按照日期过滤并在2025年度文件上做一次行组遍历。已知2025年Parquet有522个RowGroup，并且先前9/30单日没能跳过任何组，因此多日窗口仍可能读取全年2025数据行，但不会按一天重复扫描一次。程序会显示H5/Parquet分段进度，所有临时SQLite都在模块`work`目录创建并在一轮结束后清理。

## 下一步：只跑一次跨三个交易日的2025全市场对账

在Windows仓库根目录，先合并当前PR、`git pull --ff-only origin main`并运行全模块测试。基础main已有约115项，新增2项后**预计117项**（不包括尚未合并的PR #29的6项）；实际请以Windows的`Ran ... tests / OK`结果为准。测试通过之后：

```powershell
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\reconcile-local-a-share-h5-parquet.py "D:\stock" --years 2025 --periods 5min --from-date 2025-09-26 --to-date 2025-09-30 --universe a-share-candidate --batch-size 8192 --read-only --out "reports\h5-parquet-5min-2025-09-26-30-mainline.json"
```

这一窗口覆盖9/26（周五）、9/29（周一）和9/30（周二）三个交易日（按数据实际覆盖报告判断，不从日历推断源数据一定齐全）。一次完成**全候选A股证券**的H5/Parquet同键交集、双向缺口、价格差、量额差以及逐日对照。输出JSON和同名MD都在`H5ParquetReconciler/reports`，scratch SQLite仅在模块内；如果报告名存在，请使用新文件名，不可覆盖。

**下一次请上传 `h5-parquet-5min-2025-09-26-30-mainline.json`**。需要优先读 `results["5min/2025"].by_day` 的覆盖与差异，以及 `issues`、`scan_complete`、`pq_unique_keys`、`pq_duplicate_keys_across_batches`；由于同一日期是开始/结束候选规则，不能据量价差异直接判哪个供应商真值正确。

如果担心源统计不同步或需要先只验证新逻辑，可用另一个新文件名仅做2025-09-30单日复测，核对旧260,832 Parquet候选根数、259,872重叠键和960差集。**不要为了快速比较先继续索引到522组；两源已有真实成交口径差异，主线优先量化这种差异的日期/证券分布。**

未来拓展：同样的窗口对比2026年最新重叠日；再以2025/2026日线结果核对一分钟缺失与日内量价守恒；确认证券主数据、时标、复权和量额映射后再制定真实并集的新库输出策略，绝不修改原始两源。 
