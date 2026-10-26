# 2025五分钟V3索引：主库57组SQLite阶段剖析与事务退出计时

更新：2026-10-26。依据用户上传的真实JSON汇总；不包含任何付费OHLCV、单股交易键或源数据行。

## 一、本机主索引从52组真正推进到57组

用户上传 `pq-5min-2025-v3-sqlite-breakdown-57.json`：主V3 SQLite索引 `work/indexes/pq-5min-2025-a-share-candidate-v3.sqlite` 已完成57/522组（10.92%），本轮从已审计的52组新增5组、614,400源行。用户此前从同一52组复制的两个A/B试验副本也已是57组，不能混同为主索引续建。

本轮总耗时40.828秒，其中 `parquet_read_and_key_aggregation=14.874`秒，`sqlite_group_commit=25.923`秒，未归因=0。平均每个RowGroup约8.17秒；进程CPU累计28.828秒。仍为WAL日志、`source`写入顺序、`progress`轻量报告。预算：90秒软运行时间及192MiB磁盘软容量均未触发，停止原因`max_new_groups`。主库逻辑占71,770,112字节（68.45MiB），主库+WAL占143,771,264字节（约137.11MiB）。源指纹与前次一致，原始D盘行情无修改，年度依然不完整。

57组主库候选源行7,009,197（含此前52组6,394,912，新增614,285候选行；新处理源行614,400中排除115）；异常年份/时标/交易时段/证券识别均为0。**此次是progress，精确唯一键和重复键为null，尚未对主V3的57组独立full审计**；虽然此前两个A/B副本已full审计至57组且重复0，不应伪称主库的独立审计已完成。

## 二、SQLite 25.923秒内部耗时

| SQL阶段 | 合计秒 | 占SQLite写入 |
|---|---:|---:|
| `commit_and_other_seconds`（事务退出及未分解部分） | 15.156 | 58.47% |
| `row_group_locator_upsert_seconds`（行组定位表） | 8.376 | 32.31% |
| `daily_coverage_upsert_seconds`（证券日覆盖表） | 2.047 | 7.90% |
| `prepare_seconds`（Python排序、生成批量SQL参数） | 0.312 | 1.20% |
| `groups_done_insert_seconds` | 0.000（四舍五入） | 约0% |
| `outside_insert_group_seconds`（外层余量） | 0.032 | 0.12% |

以上分项汇总与`sqlite_group_commit=25.923`完全一致。每一新行组`commit_and_other_seconds`在2.610—3.422秒，提示SQLite事务提交/同步可能是当前首要开销，但该指标还包括连接上下文进出及其他差值，**不能等同于操作系统fsync耗时，也不能仅据此更改PRAGMA synchronous**。57组主库本次用40.828秒；此前同样五组的source A/B副本总耗时40.687秒，差仅0.141秒。由于缓存/机器波动，不将此作为插桩零开销的严格证明。

## 三、本轮新增事务退出直接计时

仅在Python侧为需要计时的`sqlite3.Connection`包一层`_ObservedSQLiteTransaction`，精确调用原有`db.__enter__()`和`db.__exit__(exc_type,exc_value,tb)`；原SQL、事务范围、commit或rollback路径、WAL、`synchronous=FULL`、默认source顺序、索引表结构、RowGroup checkpoint均保持不变。失败事务仍由原连接回滚，不发布任何成功计时。

新增单组字段（属于原`sqlite_write_breakdown_seconds.commit_and_other_seconds`内部子项）：
- `transaction_context_enter_seconds`，原SQLite事务上下文的进入耗时。
- `transaction_context_exit_seconds`，原SQLite连接的`__exit__`调用耗时；成功事务主要体现`COMMIT`过程，不等同于内核磁盘同步细节。
- 新的汇总`stage_profile_this_run.sqlite_transaction_boundary_seconds`包含`context_enter_seconds`、`context_exit_seconds`与`other_within_commit_and_other_seconds`。

**严格不要将此汇总再加到`sqlite_write_breakdown_seconds`或总耗时中**。新字段用于判定15.156秒中究竟有多少花在SQLite连接事务退出，后续才决定是否对**严格隔离的索引实验副本**进行同步持久化模式对照。主库目前仍必须保持`FULL`，绝不直接为加速改变其断电持久性。

本轮新增2项离线合成测试，并更新已有分项测试断言。预计完整测试数从113→**115项**，必须以用户本地Windows Python3.11真实结果为准；当前未在用户本机执行。

## 四、安全后续：主V3索引57→最多62组

先`git pull --ff-only origin main`，再运行全模块unittest。全部通过后、确认主库确实仍在57组、磁盘可用、无其他写入进程时，最多新增5组、仍采用完整事务持久化、90秒软时间/192MiB磁盘预算：

```powershell
git pull --ff-only origin main
.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test*.py" -v
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\index-parquet-5min-coverage.py "D:\stock" --year 2025 --universe a-share-candidate --resume --max-new-groups 5 --max-run-seconds 90 --max-index-mib 192 --journal-mode wal --write-order source --report-detail progress --read-only --report "reports\pq-5min-2025-v3-transaction-exit-62.json"
```

如果旧报告存在需更换报告名，绝不能覆盖。新报告应包含`stage_profile_this_run.sqlite_transaction_boundary_seconds`与各组`transaction_context_exit_seconds`。判断成功条件：五组正常提交、`stopped_for=max_new_groups`、源指纹未变化、异常数不增加、预算无提前触发，且`context_enter+context_exit+other_within_commit_and_other`约等于`commit_and_other_seconds`。任何异常先停，不自动扩大年度扫描，更不触碰原始D盘付费行情或开启H5/Parquet并集。

当前主库57组，全年还有465组未索引，证券真值及时间标记规范未获独立认证；因此`safe_to_automatically_union=false`继续保持。
