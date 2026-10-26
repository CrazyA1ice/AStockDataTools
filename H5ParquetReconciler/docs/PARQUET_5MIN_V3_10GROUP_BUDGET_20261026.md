# 2025年五分钟V3索引：10个行组实测和容量预算续建（2026-10-26）

## 最新真实结果：索引构建正确，但全年成本仍未知

用户上传 `pq-5min-2025-index-v3-smoke-2groups.json` 与 `pq-5min-2025-index-v3-smoke-10groups.json`，后者由前者通过 `--resume --max-new-groups 8` 累计建立。两份报告中的源文件指纹相同，说明本轮没有发现源文件清单/大小/mtime等缓存指纹变化。

|指标|累计2组|累计10组|
|---|---:|---:|
|2025年度源文件RowGroup总数|522|522|
|实际累计已索引RowGroup|2|10|
|原始ts/symbol行数|247806|1230846|
|候选有效行/唯一证券+五分钟时间键|247776|1230687|
|跨Arrow批/行组正常时段重复键|0|0|
|证券—自然日分区|120646|565023|
|逻辑行组定位关系|122277|618228|
|真实压缩定位行数|120646|565023|
|行组定位列表payload字节|122277|618228|
|定位关系/物理定位行压缩比|1.0135|1.0942|
|SQLite逻辑分配字节（不含WAL）|6164480|28979200|
|过滤非候选证券记录|30|159|
|不合法/不在本年度/不在预期5分钟时段记录|0|0|

**10组内重复键为0，不代表全年无重复或全年一定可自动构建并集**。两个报告均保留 `index_complete=false`、`safe_to_automatically_union=false`。

10组V3的SQLite已分配约27.64MiB，累计2组约5.88MiB，新增8组约21.76MiB。仅按当前10组平均数线性外推，522组可能在GiB级，但这种推断未考虑股票—日期分区重叠、后续更长RowGroup ID和DB B-tree变动，**不是全年容量预测值，更不是此时要求直接续建512组的依据**。本次JSON没有实际每组处理耗时，不能判断V3速度。

## 新增保护：按容量和处理行组数进行渐进式续建

在 `tools/index-parquet-5min-coverage.py` 中，保留V3数据格式和现有 `work/indexes/pq-5min-2025-a-share-candidate-v3.sqlite`，不改变源股票筛选和48个时段唯一键计算。仅新增：

- `--max-index-mib`：设定**软**SQLite磁盘预算（MiB）。每完成一个RowGroup的事务后比较SQLite逻辑已分配页大小和数据库主文件+WAL实际字节的较大值。达到阈值后不继续下一组，给出明确停止原因并保留已有checkpoint。不是OS级别的严格磁盘配额：**正在提交的单个RowGroup可能使文件略超阈值**。
- 继续支持 `--max-new-groups`，每轮最多新增指定行组数。两个限制都传时先碰到哪个就停哪个。旧的未完成索引在相同源文件指纹下可 `--resume`，**不得使用未经完整认证的部分索引跳过日级核对行组**。
- 报告新增 `source_rows_this_run`、`elapsed_seconds_this_run`、`new_groups_per_second`、`max_index_mib_soft_budget`、`soft_budget_reached`、`stopped_for` 以及 `sqlite_logical_allocated_bytes`、`sqlite_main_and_wal_on_disk_bytes`、`sqlite_budget_measure_bytes`。索引只读源数据，不包含原始购买的OHLCV。
- 原本V3的SQLite事务、行组重复键检测与行组定位不变；三个新增合成测试覆盖WAL计入容量、预算阈值和无效限额的拒绝，原64项预计增加至67项。

## 下一次Windows验收（不运行全年）

在 `D:\ChatGPT\AStockDataTools` 仓库根目录：

```powershell
git pull --ff-only origin main
.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test*.py" -v
```

先检查用户电脑磁盘剩余空间，尤其是 `D:` 所在卷。确认足够后，用**当前已完成10组的V3索引原位续建**，本轮最多20个新行组并设置96MiB软预算：

```powershell
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\index-parquet-5min-coverage.py "D:\stock" --year 2025 --universe a-share-candidate --resume --max-new-groups 20 --max-index-mib 96 --read-only --report "reports\pq-5min-2025-index-v3-budgeted-next.json"
```

如果此前已经存在同名报告，换新的 `--report` 文件名，**不要覆盖**。程序会重新核对源文件尺寸/mtime/清单指纹；不同则拒绝继续，不得强行删除或绕过。

本轮重点检查：

1. `row_groups_complete` 是否处于10与30之间，`new_row_groups_this_run <= 20`；
2. `source_rows_this_run`、`elapsed_seconds_this_run` 和 `new_groups_per_second` 对应真实新一轮速度；
3. `sqlite_budget_measure_bytes` 及停止原因，预算只能保证**整组事务之间**检查，最后一组可能超过96MiB；
4. `duplicate_regular_session_keys`、非法时间键、来源排除数，确定年度更多行组是否出现新异常；
5. `index_complete=false`时禁止用于并集预检加速，自动合并仍禁止。

查询SQLite磁盘大小（命令只读）：

```powershell
Get-Item "H5ParquetReconciler\work\indexes\pq-5min-2025-a-share-candidate-v3.sqlite" |
  Select-Object Name,@{Name="MiB";Expression={[math]::Round($_.Length/1MB,2)}}
```

全部报告和索引保留在 `AStockDataTools/H5ParquetReconciler`，源 `D:\stock` 不写入。此阶段**只构建键覆盖索引，不创建新的H5/Parquet并集数据文件**。
