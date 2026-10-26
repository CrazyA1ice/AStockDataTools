# V3 2025五分钟：两轮写入策略A/B结论与SQLite细分剖析

更新：2026-10-26。此文仅归档本机上传的聚合报告，不复制或泄露付费OHLCV行情。

## 一、实验事实与正确性

**主V3索引仍为52/522 RowGroup**。用户先完成主库52组独立只读full审计：候选源行6,394,912、有效唯一五分钟键6,394,912、重复键0、股票日分区1,302,021；只针对52组，年度认证仍为false。

从同一主库52组快照分别克隆两份V3 SQLite副本，**各新增5个组（编号52—56，展示时是第53—57组）**；用户上传：
- `pq-5min-2025-ab-source-57.json`，`source`模式；
- `pq-5min-2025-ab-pk-sorted-57.json`，`pk-sorted`模式；
- `pq-5min-2025-ab-compare-57.json`，独立严格只读A/B比较。

比较器报告 `same_source_fingerprint=true`、`same_clone_source=true`、`same_journal_mode=true`、`full_key_audit_both=true`、`logical_tables_equal=true`，流式逐行比较两个索引的`groups_done`57行、`daily_coverage`1,308,088行、`row_group_locator`1,308,088行均一致。两份完整审计均得到候选源行7,009,197=有效唯一键7,009,197、重复键0。两份临时副本仍未完成全年度，不能自动生成H5/Parquet并集或声称源时标真实可信。

| 测量指标（第二轮，5个相同RowGroup） | source | pk-sorted |
|---|---:|---:|
| 全部新组的计时总耗时（秒） | **40.687** | 40.859 |
| SQLite写入含准备与提交（秒） | **25.156** | 26.233 |
| Parquet读取与键聚合（秒） | 15.484 | **14.595** |
| 进程CPU累计时间（秒） | 29.891 | 28.797 |
| 两组的完成行组数 | 57 | 57 |
| 空间/时间软预算触发 | 否/否 | 否/否 |

`pk-sorted`本轮总时间**慢0.42%**，写入阶段**慢4.28%**；当轮报告由严格比较器计算。两个实验均正常停于`max_new_groups`，没有WAL截断，单个行组没有明显的长时间异常。source副本主库+WAL占143,771,264字节（约137.11 MiB），sorted副本143,726,064字节（约137.07 MiB）；物理大小相近不证明索引性能优劣。

## 二、与第一次A/B对照

第一轮（不同的第36—40组，同一35组快照）`source`总耗时55.484秒，`pk-sorted`50.922秒；相应SQLite写入30.969秒和26.452秒，按主键排序表现更快。但第二轮反向，且只有两次配对实验：**没有足够证据将默认写入顺序由source改成pk-sorted**。两轮使用的RowGroup范围不同，不能把不同轮的绝对时间相减来证明策略改进；其次顺序执行存在Windows文件缓存、后台进程、日志状态的波动。

**开发决策：保留原`source`默认顺序和WAL；停止继续做相同的“盲目排序”对照。** SQLite写入仍为较大可测阶段，本轮source写入占总用时约61.8%，应追究内部哪张表/事务部分占时。

## 三、本轮新增无行为变化的SQL分项计时

修改`tools/index-parquet-5min-coverage.py`：`insert_group(..., timing_out=...)`可选收集已成功提交行组的下列壁钟时间；不更改任何SQL语句、SQLite schema、事务边界、commit机制、已存在checkpoint或源数据。失败事务不写入部分成功的阶段统计：

- `prepare_seconds`：Python按策略迭代/排序、生成daily和locator行参数。
- `daily_coverage_upsert_seconds`：`daily_coverage`的`executemany`耗时。
- `row_group_locator_upsert_seconds`：`row_group_locator`的`executemany`耗时（包含V3 UDF位置信息并集）。
- `groups_done_insert_seconds`：行组checkpoint记录写入。
- `commit_and_other_seconds`：事务上下文管理、提交与其他没有被以上计时覆盖的数据库处理。
- `outside_insert_group_seconds`：调用端记录的`sqlite_group_commit`总计时减去上述嵌套计时后的微小剩余。

新版JSON `stage_profile_this_run.sqlite_write_breakdown_seconds`汇总上述项目，`sqlite_write_breakdown_profiled_groups`说明实际记录分项计时的行组数；单组`slowest_sqlite_commit_groups`和`slowest_row_group_wall_groups`中也带细分信息。**这些指标是`sqlite_group_commit`的子集，不得再加到总elapsed或`phases_seconds`中**，否则会双重计算。读/聚合阶段仍是合并测量，没有拆开。

新增3项合成测试检查：实际SQLite写入统计不改变索引内容、事务失败不发布部分阶段数、profile可与旧无分项调用兼容且不能把嵌套计时再次累加到总时间。原预计110项加3项，**预计113项**；实际完整测试需Windows本机运行确认。

## 四、下一轮只推进主V3的5组并采集新的SQL阶段证据

**注意：两份A/B实验副本已处理57组，但主索引文件仍是52组。** 不允许用本轮副本报告替代主索引、或删除/覆盖已有SQLite，也无需重新做A/B副本。

Windows PowerShell仓库根目录：

```powershell
git pull --ff-only origin main
.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test*.py" -v
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\index-parquet-5min-coverage.py "D:\stock" --year 2025 --universe a-share-candidate --resume --max-new-groups 5 --max-run-seconds 90 --max-index-mib 192 --journal-mode wal --write-order source --report-detail progress --read-only --report "reports\pq-5min-2025-v3-sqlite-breakdown-57.json"
```

预期若源文件和主索引均与52组记录一致且预算未触发，主V3应达到57组；若出现不同值、`stopped_for`不是`max_new_groups`、`source_fingerprint`变化或空间压力，**不要继续扩大规模**，先分析报告。读数侧重`sqlite_write_breakdown_seconds`的daily更新、locator更新、commit余量及两份A/B报告的差别；不据单轮计时直接变更索引写入算法。

本轮仍不访问或修改`D:\stock`的付费行情，SQLite索引和进度JSON只存在`H5ParquetReconciler/work`及`reports`；不能以部分索引为准授权H5和Parquet自动合并。
