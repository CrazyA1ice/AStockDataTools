# 2025五分钟V3索引：第35组WAL/DELETE实测及分阶段性能诊断

更新：2026-10-26。仅限 `AStockDataTools/H5ParquetReconciler`。

## 一、同一30组快照的A/B结论

用户上传 `pq-5min-2025-ab-wal-35.json` 与 `pq-5min-2025-ab-delete-35.json`。两份独立SQLite副本均以2025年V3主索引已完成的第30组为起点，再读取相同的第31—35组。

|指标|WAL|DELETE|
|---|---:|---:|
|RowGroup累计进度|35/522|35/522|
|新处理组数/源行|5/614400|5/614400|
|唯一有效规则五分钟时间键|4302144|4302144|
|重复键（仅已扫描组）|0|0|
|证券—日期分区|1263710|1263710|
|逻辑行组定位关系|2159080|2159080|
|SQLite逻辑主库与最终主库+日志|67104768B|67104768B|
|执行耗时|51.796秒|51.219秒|
|检查点次数|5|0|
|WAL检查点回收操作量|328990400B|0B|
|停止原因|max_new_groups|max_new_groups|
|96MiB软预算触发|否|否|

`DELETE`快0.577秒，约1.11%（相对于WAL），差距很小，并且受到文件系统缓存、执行先后及系统负载影响。**没有足够证据证明DELETE比WAL更快，更不建议现在把既有主索引切换为DELETE**。

WAL报告中`wal_reclaimed_bytes_this_run`是5次检查点动作的回收字节累加，并非本轮永久节省314MiB存储。WAL和DELETE在35组末尾的数据库大小及统计数据完全一致，说明这两种日志模式均能正确完成这个小样本任务；**这也不等于2025全年已核验**。

## 二、本轮只新增耗时分段统计，不改存储算法

`tools/index-parquet-5min-coverage.py` 新增索引报告 `stage_profile_this_run`：

- `parquet_read_and_key_aggregation`：Parquet Arrow lazy批读取、解压与Python证券/时标归一化、键位图聚合。因为批生成器是惰性的，这一项**不能直接细分**“磁盘读”和“Python计算”，不能把它当作单纯I/O耗时。
- `sqlite_group_commit`：`insert_group()`包围的SQL批量写入与该RowGroup的事务提交，可能包括SQLite B-tree更新、日志及同步。
- `budget_guard_and_checkpoint`：预算检测、文件大小统计及已触发的WAL TRUNCATE恢复检查点。
- `wal_checkpoint_inside_budget_seconds`：上面预算阶段的**子集**，不能与`budget_guard_and_checkpoint`再次相加。
- `unattributed_seconds`：主循环耗时减去前三项，可能包含stdout、Parquet元数据处理、结束统计及控制开销。原报告的`elapsed_seconds_this_run`仍保留。
- `slowest_parquet_read_and_aggregate_groups`与`slowest_sqlite_commit_groups`最多列5个最慢源文件/RowGroup编号、处理行数、股票—日期分区数及阶段耗时；不输出任何原始付费OHLCV数值。

这轮仅新增3项合成测试，指数脚本中的阶段数据使用`time.monotonic()`，不引入外部监测、昂贵的操作系统采样或云服务。原索引版本仍为V3；SQLite表结构、已完成断点、源指纹、去重规则、单位和时标约定均未修改。所有存储和报告只在模块内，`D:\stock`完全只读。

## 三、本机操作建议

从`D:\ChatGPT\AStockDataTools`根目录运行：

```powershell
git pull --ff-only origin main
.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test*.py" -v
```

当前已有76项合成测试，本轮新增3项，**预计共79项**，尚需本机确认。

在原主V3索引仍为30组且空间充足的前提下，只新增**5个行组**，不必复制额外的A/B SQLite：

```powershell
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\index-parquet-5min-coverage.py "D:\stock" --year 2025 --universe a-share-candidate --resume --max-new-groups 5 --max-index-mib 128 --journal-mode wal --read-only --report "reports\pq-5min-2025-v3-stage-profile-35.json"
```

正确性先行：应累计完成35组，唯一有效键4,302,144、重复0、分区1,263,710（前提是源数据与此前快照相同）。若已有用户手动继续的组数不同，应按实际报告确认，不可硬套这个预期。若`stopped_for`显示提前触发预算或索引异常，则先停止排查。

这次特别观察`stage_profile_this_run.phases_seconds`，以及主循环`elapsed_seconds_this_run`，再决定如何优化。例如若SQL事务占大多数，可以考虑**一次事务更新的RowGroup内部键合并策略**；若Parquet读取+聚合占大多数，则优先研究矢量化证券/时间编码。未经此分段统计，不继续盲目在journal mode和稀疏编码间反复更换。

需要提醒：`--max-index-mib 128`是软预算，WAL或DELETE单事务可能超过阈值；执行前确认磁盘空余，源行情仍不写入。不应将未完成35/522组的索引当作全年度完整数据或开始H5/Parquet自动并集。
