# 两源主线：三日全市场实测与证券—日期缺口分类（2026-10-26）

## 一、严格来自2025年9月26/29/30实测的结论

用户上传 `h5-parquet-5min-2025-09-26-30-mainline.json` 和同名 Markdown，`status=complete`、`issues=[]`、`scan_complete=true`。一次完整遍历2025 Parquet年度522个RowGroup、64,081,920源行，没有按每个交易日重复扫描；H5与Parquet付费行情源文件都没有修改。

证券范围是 **a-share-candidate**（代码前缀的候选股票集），五分钟键比较使用 **Parquet五分钟起始时刻+5分钟对应H5终止时刻** 的未认证工作假设。

| 日期 | H5唯一键 | Parquet唯一键 | 同键重叠 | H5独有 | Parquet独有 | 量价至少一项冲突 | 重叠键冲突率 |
|---|---:|---:|---:|---:|---:|---:|---:|
| 2025-09-26 | 259,968 | 260,784 | 259,968 | 0 | 816 | 154,492 | 59.427% |
| 2025-09-29 | 259,728 | 260,736 | 259,728 | 0 | 1,008 | 156,346 | 60.196% |
| 2025-09-30 | 259,872 | 260,832 | 259,872 | 0 | 960 | 151,099 | 58.144% |
| **合计** | **779,568** | **782,352** | **779,568** | **0** | **2,784** | **461,937** | **59.256%** |

重叠中价格存在差异227,715根，成交量或成交额存在差异454,682根，两类可能重叠，不可把它们相加。H5、Parquet自身均未出现重叠时间键，`h5_duplicate_keys=0`，`pq_duplicate_keys_within_batch=0`，`pq_duplicate_keys_across_batches=0`。数据扫描完整，但并不等于计量单位、上市证券主数据、供应商时间规则或量价真值已认证。

**重要发现：三天H5记录的五分钟时间键全部包含在Parquet中，Parquet额外出现2,784根（相当于58份标准48根证券交易日的键数，但不能据此断定恰好58个整股票日缺失）。** 例如本次报告中的`BJ920680`、`SH600200`、`SH603056`、`SH603388`、`SH605255`各有144根Parquet独有键，提示部分证券可能H5整天缺失，但需要**证券×交易日真实聚合**而不是单纯根据3天总量推断。很多SH688前缀股票出现144根量价冲突，提示分组分析价值高，不代表科创板整体真实差异程度，更不证明任一源正确。

## 二、基于实测新开发的针对性归因

`tools/reconcile-local-a-share-h5-parquet.py` 增加：

1. **`stock_day_gap_summary`**：使用既有scratch SQLite中的H5有序时间键表`h`和精确Parquet已扫描时间键表`pq_seen`，各按`(证券,YYYYMMDD)`分组。将Parquet独有分成`pq_only_full_h5_absence_stock_days`（该证券日H5一条都无，但PQ有）和`pq_only_partial_h5_coverage_stock_days`（H5已存在当日部分键，PQ另有缺口），分别合计对应`*_keys_on_*_days`。H5独有同理拆分整证券日与部分K线；分类后独有键数必须与全窗口的源差集总数严格一致，否则报错而不是写报告。
2. 逐日`by_day`输出两类缺口的独有键数，避免把某股票没有H5 dataset直接误称为单根分钟K线丢失；额外保存两类代表性`证券+交易日+根数`示例，不包含原始OHLCV。
3. **`by_code_prefix_group`**按`SH_688_689_prefix`、`SZ_300_301_prefix`、`BJ_prefix`、`SH_other_prefix`、`SZ_other_prefix`分别统计重叠键、量价冲突、价格冲突、量额冲突及双向差集，`board_membership_certified=false`明确它只是前缀分组，不能代替正式上市板块和证券主数据。
4. `render_markdown`同步新增逐日交集与量价表、证券日缺口类型表和代码前缀量价冲突表，供人类验收。普通`day`/ `1min`旧流程继续保留；证券日缺口汇总目前仅针对**有界5min+实际Parquet文件**。没有Parquet数据或无H5数据时，不得借由`unknown`作无依据的数据认证。

新增2项完全合成的回归测试：同日一只证券有部分H5、另一只只有Parquet时，分别产生局部/整日缺口并满足守恒；前缀类别冲突统计只用重叠键作分母，不把Parquet独有数据当成匹配量。未在用户Windows执行，实际需本机验证。

## 三、下一步优先运行两个现实窗口

这次**不用再继续把67/522组的单源索引当成双源比较前置条件**，保持正在使用的索引不变。为了获得更新的数据覆盖结论，下一次优先在2026年10月19—23日实际检查新H5是否含有Parquet未提供的最新记录：

```powershell
git pull --ff-only origin main
.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test*.py" -v
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\reconcile-local-a-share-h5-parquet.py "D:\stock" --years 2026 --periods 5min --from-date 2026-10-19 --to-date 2026-10-23 --universe a-share-candidate --batch-size 8192 --read-only --out "reports\h5-parquet-5min-2026-10-19-23-latest-gap.json"
```

这会一次读取2026年所选日期窗口及涉及行组；如果Parquet年度文件确实只更新至9月，预期Parquet当周可能为0，但**是否为0应完全以真实报告为准，不能拿文件名月份推断或伪造H5独有数**。如果H5市场文件存在但数据尚未下载到当周，也会如实显示0、不能当成行情不存在。

随后如需明确前述2025年2,784个Parquet独有键属于哪些证券—日期模式，可用新文件名重新执行以前三日窗口一次扫描：

```powershell
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\reconcile-local-a-share-h5-parquet.py "D:\stock" --years 2025 --periods 5min --from-date 2025-09-26 --to-date 2025-09-30 --universe a-share-candidate --batch-size 8192 --read-only --out "reports\h5-parquet-5min-2025-09-26-30-gap-attribution-v2.json"
```

可选择进一步对`2026-09-28..30`运行一次有界五分钟对比检验购买Parquet末月的重叠和口径，使用独立新文件名即可。

无论哪条路径，报告JSON与Markdown保存在`H5ParquetReconciler/reports/`，临时SQLite限模块`work/`，不修改`D:\stock`，不上传付费OHLCV，不生成H5/Parquet并集，直到独立证券主数据、时标与复权/量额口径认证且冲突裁决规则验收。
