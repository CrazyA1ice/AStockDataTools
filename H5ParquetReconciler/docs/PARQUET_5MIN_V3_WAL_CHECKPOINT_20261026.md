# V3索引20组实测：SQLite WAL预算误触发与检查点修复

更新：2026-10-26。项目：`AStockDataTools/H5ParquetReconciler`。

## 一、用户上传报告

用户真实执行V3的第3轮续建命令（`--resume --max-new-groups 20 --max-index-mib 96`），上传 `pq-5min-2025-index-v3-budgeted-next.json`。

|统计|结果|
|---|---:|
|2025年度五分钟Parquet行组总数|522|
|本轮开始时已完成|10|
|本轮新增|10|
|目前累计完成|20|
|本轮新扫描源行|1,228,800|
|本轮耗时|76.125秒|
|平均新增行组|0.13136组/秒（约7.61秒/组）|
|累计候选有效唯一键|2,459,297|
|累计重复正常时段时间键|0（仅已扫描20组）|
|累计证券—日期分区|969,400|
|累计行组定位关系/物理行数|1,240,203 / 969,400|
|累计排除非候选记录|349|
|时间戳/非法时段/年份之外/未知证券代码|均0（仅20组）|
|SQLite逻辑已分配页|50,262,016字节，约47.93MiB|
|报告时主库+WAL占用|100,806,208字节，约96.14MiB|
|停止原因|`max_index_mib_after_group`|
|完成标记|`index_complete=false`|

初步判断：报告时SQLite WAL日志带来的**瞬时**空间占用接近主库自身大小，导致96MiB软预算在第20组触发。旧预算使用 `max(PRAGMA已分配页, main文件+WAL文件实际字节)`，原逻辑确实会保护磁盘，但**没有尝试通过安全WAL检查点释放可回收的重复页**，因此可能比必要时更早停止。

本报告只能证明预算因主库+WAL总和触发，**尚不能证明所有WAL都能被回收**，例如并发只读SQLite连接可能阻止检查点。

## 二、本轮代码修复

保持**原V3索引格式**及数据库路径：`work/indexes/pq-5min-2025-a-share-candidate-v3.sqlite`。不修改`daily_coverage`、`row_group_locator`、`groups_done`算法，也不迁移或覆盖原有20组checkpoint。

- 新增 `budget_check_after_wal_recovery(db,path,max_mib)`：先复用原来的主库+WAL空间预算统计；若低于阈值不改变任何SQLite WAL状态。
- 如果已经触发预算，必须确保**不在任何未提交事务内**；再尝试一次SQLite `PRAGMA wal_checkpoint(TRUNCATE)`，将已提交的WAL事务安全写回主库并尽可能截断临时日志。
- 检查点后再次测量SQLite逻辑主库及主库+WAL实际字节。如果降到预算以下，继续下一个RowGroup，而非直接认定预算失败；如主库本体仍超预算，或检查点显示busy，**保持保守停止**，绝不绕过限制或静默删除日志。
- 检查点只在预算边界触发，非每个组强制磁盘同步。保留整RowGroup事务提交与断点安全。
- JSON新增本轮`wal_checkpoint_attempts_this_run`、`wal_checkpoint_busy_this_run`与`wal_reclaimed_bytes_this_run`；后者是检查点前后的**物理主库+WAL字节差**，反映尝试回收的日志存储，不代表原始行情数据量或新增数据库行数。
- 新增4项真实临时SQLite合成测试，包括增加WAL负荷、真实检查点回收、主库确实超过软预算时保守停止、正常不触发、未提交事务拒绝。
- 原累计67项合成测试增加至预计**71项**，本机是否全部通过以Windows运行结果为准。

## 三、本机验证与小批续建

在`D:\ChatGPT\AStockDataTools`仓库根目录：

```powershell
git pull --ff-only origin main
.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test*.py" -v
```

检查当前V3数据库仍在本模块`work/indexes`内、磁盘空间充足后，继续沿用已经完成20组的V3索引。**最多新增10组**，保留96MiB软容量预算，使用全新报告文件名：

```powershell
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\index-parquet-5min-coverage.py "D:\stock" --year 2025 --universe a-share-candidate --resume --max-new-groups 10 --max-index-mib 96 --read-only --report "reports\pq-5min-2025-index-v3-wal-recovery-next.json"
```

检查`row_groups_complete`应在20—30范围，本轮新增不多于10组。特别注意：

- `wal_checkpoint_attempts_this_run`及`wal_reclaimed_bytes_this_run`：是否确实出现空间回收；
- `sqlite_logical_allocated_bytes`对比主库+WAL和软预算；
- `soft_budget_reached`、`stopped_for`：真实主库超预算时仍应安全停止；
- `duplicate_regular_session_keys`与时标异常计数是否出现新的问题；
- `elapsed_seconds_this_run`、`new_groups_per_second`，比较检查点带来的成本。

预算为**事务之间的软限制**，单次行组事务可能使文件临时突破96MiB，因此需本机确认有更多空余空间；这不是文件系统层面的硬磁盘配额。若还有其他SQLite进程持有索引长读事务可能导致WAL检查点busy，程序会保守停止而不破坏索引。

## 四、与并集目标的关系

这里只在建立2025年Parquet的`ts/symbol`覆盖键索引。原始 `D:\stock` 仍严格只读；所有报告、SQLite及临时文件仅在`AStockDataTools/H5ParquetReconciler`。**20/522仍是部分索引，不能当成全年度去重结果，更不能据此自动生成H5/Parquet并集库。**
