# V3五分钟索引：30组实测及SQLite WAL/DELETE对照试验（2026-10-26）

## 已确认的本机运行结果

用户上传 `pq-5min-2025-index-v3-wal-recovery-next.json`：

|项目|实际结果|
|---|---:|
|2025年度RowGroup总数|522|
|累计已建立索引|30组|
|本轮新增|10组|
|本轮扫描的ts/symbol键列行数|1,228,800|
|本轮运行时间|129.36秒|
|当前累计有效证券/时段唯一键|3,687,846|
|当前累计重复的正常时段键|0（**仅前30组**）|
|证券/日分区|1,214,620|
|逻辑行组定位关系/定位表物理行数|1,855,711 / 1,214,620|
|SQLite主库逻辑及报告时主库+WAL|63,975,424字节（约61.01MiB）|
|本轮WAL TRUNCATE尝试/繁忙|9/0|
|本轮各次回收物理字节累计报告|523,606,968字节（约499.35MiB）|
|停止原因|`max_new_groups`；96MiB预算未触发|

**解读边界**：523,606,968字节是9次检查点报告的**重复累计回收操作量**，不是本轮累计新增数据量，不代表索引永久节省了499MiB空间，也不代表最初占用了499MiB。前一轮10组耗时76.125秒，本轮10组耗时129.36秒；两批RowGroup中的股票、日期分布及数据库规模不同，不能单凭两轮时长证明检查点是全部性能损失。

本轮的实测说明`PRAGMA wal_checkpoint(TRUNCATE)`的容量回收机制有效、继续推进并未违反96MiB软预算，但在大数据库中频繁触发检查点。下一步需要在**相同数据库快照、相同后续RowGroup**比较事务日志模式，而不是无证据继续调大预算或变更索引编码。

## 独立、可回滚的WAL与DELETE试验

`tools/index-parquet-5min-coverage.py` 现可指定：
- `--journal-mode wal|delete`：默认`wal`，与既有脚本兼容；`delete`采用SQLite的回滚日志事务。两者保留`synchronous=FULL`、每个RowGroup完整事务及`groups_done`checkpoint，数据格式仍是V3。
- `--clone-from-index work/indexes/pq-5min-2025-a-share-candidate-v3.sqlite`：以SQLite**在线备份API**从已建立30组的V3索引，生成新的完整一致的SQLite备份。只读打开原索引，源文件指纹、V3版本及`completed=false`必须匹配。目标必须是**模块内全新、明确指定的`--out`路径**；已存在则拒绝覆盖，且必须指定`--max-new-groups`和`--max-index-mib`。
- 复制的两份V3索引位于本模块`work/indexes/`。原V3既有30组索引**不切换journal_mode、不新增checkpoint**；源购买的 `D:\stock` Parquet全程只读。
- 不会在独立A/B试验中自动选择WAL或DELETE优胜者，更不会自动写H5/Parquet并集。DELETE模式同样有回滚日志空间开销（可能在**事务内**瞬时增长），96MiB是仅在RowGroup事务边界检测的软预算，非严格磁盘配额。应检查实际空余空间。

## Windows本机指令：只做两份5组对照

先运行最新全部测试（代码修改前已71项，新增5项，预计**76项**）：

```powershell
git pull --ff-only origin main
.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test*.py" -v
```

随后从相同的**30组V3原索引**各创建一份独立快照，处理相同的第31—35组，不碰原有索引：

```powershell
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\index-parquet-5min-coverage.py "D:\stock" --year 2025 --universe a-share-candidate --clone-from-index "work\indexes\pq-5min-2025-a-share-candidate-v3.sqlite" --out "work\indexes\pq-5min-2025-ab-wal.sqlite" --journal-mode wal --max-new-groups 5 --max-index-mib 96 --read-only --report "reports\pq-5min-2025-ab-wal-35.json"

.\.venv\Scripts\python.exe H5ParquetReconciler\tools\index-parquet-5min-coverage.py "D:\stock" --year 2025 --universe a-share-candidate --clone-from-index "work\indexes\pq-5min-2025-a-share-candidate-v3.sqlite" --out "work\indexes\pq-5min-2025-ab-delete.sqlite" --journal-mode delete --max-new-groups 5 --max-index-mib 96 --read-only --report "reports\pq-5min-2025-ab-delete-35.json"
```

正确性先于速度判断：两份报告的`row_groups_complete`理论应均为35、`new_row_groups_this_run=5`、`unique_regular_session_keys`、`duplicate_regular_session_keys`、`stock_day_partitions`、`row_group_locator_entries`应完全相同。如任意不符、停止原因不是预期或事务报错，停止试验，不可拿速度做结论。

然后比较`elapsed_seconds_this_run`、`new_groups_per_second`、`sqlite_journal_mode`、`wal_checkpoint_attempts_this_run`、`sqlite_main_and_wal_on_disk_bytes`。第一次运行与第二次运行可能受OS缓存和SSD热状态影响；若结果接近或顺序影响很大，应采用另一组相同快照测试或重复，而不是过早认为`delete`更优。两份副本约需要额外数百MiB临时空间，请先检查磁盘余量。

## 不变的安全限制

`D:\stock`原始行情绝对只读；复制内容仅为原有不含OHLCV的V3键索引（symbol、date、48位时段、RowGroup ID、源行数等元数据）。所有数据库、结果和日志位于`AStockDataTools/H5ParquetReconciler/`，不上传付费原始行情。此时原有主V3仍然仅完成30/522组，不能用于完整年度跳组或自动合并。
