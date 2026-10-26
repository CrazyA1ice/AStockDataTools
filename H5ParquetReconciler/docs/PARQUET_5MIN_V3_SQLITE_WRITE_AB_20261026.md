# 2025年Parquet五分钟V3索引：第35组耗时归因与主键排序写入对照

更新：2026-10-26。所有工作文件仅在 `AStockDataTools/H5ParquetReconciler/`，源 `D:\stock` 完全只读。

## 一、用户上传的真实主V3报告

`pq-5min-2025-v3-stage-profile-35.json` 显示主V3从已完成30组续建第31—35组，数据与上一轮从30组快照建立的WAL/DELETE A/B报告**完全一致**：累积处理35/522组；有效唯一键4,302,144，正常时段重复键0（只针对35组），证券—日期分区1,263,710，行组定位关系2,159,080，实际定位表分区1,263,710。源指纹仍一致。主库分配67,104,768字节（约64MiB），96/128MiB预算未触发，停因本轮新增5组上限。

|墙钟时间分布|秒|占本轮53.078秒|
|---|---:|---:|
|SQLite逐行组事务与两表UPSERT|28.486|53.7%|
|Parquet惰性读取、解压及Python证券/时间键聚合|14.764|27.8%|
|预算检查（原报告显示）|0.0|约0.0%|
|未归因|9.828|18.5%|

**SQLite事务写入是已测得的最大单项阶段。** 但必须注意：现有 `index_summary()` 每次续建结束会扫描 `daily_coverage` 与 `row_group_locator` 两张已经越来越大的表，计算去重、定位关系及BLOB占用。此前它也被算进未归因耗时，因此不能把9.828秒全部归因于其他磁盘或Parquet读取。

`wal_checkpoint_attempts_this_run=1` 且回收67,221,952字节，但`budget_guard_and_checkpoint=0.0`。这一指标组合值得后续实测复查，不应直接把0秒理解为检查点确实免费。新工具维持回收事件计数，并补充分阶段壁钟报告；不要根据单轮差异夸大因果。

## 二、代码级下一步：主键排序写入作为可选A/B

新增 `--write-order source|pk-sorted`，保持默认`source`的旧行为。只读解析Parquet原始ts/symbol，不改变48个合法时段、证券类型、金额/量价、重复键统计或者V3的任何SQLite表结构。

- `source` 按Parquet中看到的顺序，对当组已有的约5.8—6.3万组证券—日期数据执行 `daily_coverage` 与 `row_group_locator` UPSERT。
- `pk-sorted` 先在内存中按（标准化证券代码、交易日）排序，再用完全**相同的SQL语句**按主键顺序执行UPSERT，测试能否减少SQLite随机B-tree页更新。排序本身也消耗CPU和内存，所以**没有先验保证会更快**。
- 两种方式保持逐RowGroup事务、`groups_done`、WAL/D­ELETE默认选择、源指纹校验、失败回滚与本地文件输出规则，索引格式仍V3。排序策略只影响处理顺序，不裁定价格或证券真值。
- V3报告新增 `sqlite_write_order`。耗时计量 `sqlite_group_commit` 对排序方案包含Python排序时间，使性能比较不作弊。
- `stage_profile_this_run.phases_seconds` 另外新增 `final_index_summary`，将每次结尾遍历SQLite全量摘要表的时间与`unattributed_seconds`分开。完整检验前不假设上次约9.828秒未归因全部是汇总。

本轮新增4项合成回归测试，覆盖相同数据不同写入顺序最终完整摘要/日覆盖/行组定位一致、排序方案重复提交回滚安全、不支持排序模式失败且不写入、全量汇总耗时独立归因。原合成用例79项，本轮预计83项。需要用户Windows本机验证。

## 三、严格同条件Windows试跑（不更改主V3）

仓库根目录先拉取及执行测试：

```powershell
git pull --ff-only origin main
.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test*.py" -v
```

主V3已经从30组推进到35组。用 `--clone-from-index` 建立**两份独立快照**，分别处理第36—40个行组，均使用WAL及128MiB软预算，防止比较不同来源组或更改主索引：

**基线：原始顺序**

```powershell
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\index-parquet-5min-coverage.py "D:\stock" --year 2025 --universe a-share-candidate --clone-from-index "work\indexes\pq-5min-2025-a-share-candidate-v3.sqlite" --out "work\indexes\pq-5min-2025-ab-source-order.sqlite" --journal-mode wal --write-order source --max-new-groups 5 --max-index-mib 128 --read-only --report "reports\pq-5min-2025-ab-source-order-40.json"
```

**实验：主键排序写入**

```powershell
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\index-parquet-5min-coverage.py "D:\stock" --year 2025 --universe a-share-candidate --clone-from-index "work\indexes\pq-5min-2025-a-share-candidate-v3.sqlite" --out "work\indexes\pq-5min-2025-ab-pk-sorted.sqlite" --journal-mode wal --write-order pk-sorted --max-new-groups 5 --max-index-mib 128 --read-only --report "reports\pq-5min-2025-ab-pk-sorted-40.json"
```

**正确性验收优先于时间：** 两份新报告必须分别有 `row_groups_complete=40`、`new_row_groups_this_run=5`，对应唯一键、重复键、过滤异常、证券日期分区、定位关系和最终SQLite统计完全一致。如产生任何差异、异常停机或软预算提前触发，则立即停止性能比较，检查是否复制了同一快照及源指纹。不得用部分索引自动生成并集。

然后比较 `sqlite_group_commit` 与 `final_index_summary` 耗时，连同 `elapsed_seconds_this_run`、`budget_guard_and_checkpoint`、WAL检查点次数和SQLite占用综合判断。单轮顺序运行会受到Windows文件缓存等影响；1—2秒的差距可能只是测量噪声，不能单凭单次试验切换默认模式。最好先看写入阶段是否有实质性改善，再在新副本上复验。

两个独立快照需要额外磁盘空间（每份当前约64MiB且执行时可能有较大的WAL），请先确保本机剩余容量充足。128MiB仍为RowGroup事务边界的软限制。

## 四、限制

2025年全年文件522组，目前主索引35组；当前任何测试只属于已检查的行组。源数据未用于自动OHLCV合并或交易所真值认证，不生成新的H5/Parquet数据库，也不上传付费原始行情。
