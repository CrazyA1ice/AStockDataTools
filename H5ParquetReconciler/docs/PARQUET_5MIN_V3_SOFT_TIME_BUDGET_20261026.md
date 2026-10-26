# 2025年五分钟V3索引：47组复测与单轮软运行时间预算

更新：2026-10-26。仅归档真实上传的JSON聚合摘要，不含原始付费OHLCV。

## 第46—47组实测

用户上传 `pq-5min-2025-v3-wall-gap-47.json`：主索引从45组继续到47/522组（9.00%）；本轮只新增2组、245,760行，**16.687秒**完成，进程CPU累计12.641秒，SQLite写入10.124秒，Parquet读取键聚合6.516秒。原先45组报告中超过1,145秒的未归因墙钟空档在本轮**未复现**：`row_group_loop_other=0.0`、`unattributed_seconds=0.0`。两个新增RowGroup(文件0，编号45/46)的整体墙钟时间为8.812秒和7.828秒。此结论只适用于本轮2组，不能证明早前22分钟慢跑的根因。

已处理47组累计源行5,781,498，A股候选行5,780,603，排除非候选895；时间/跨年/无法识别证券异常均0。由于继续使用 `--report-detail progress`，完整唯一键、重复键、分区与定位计数均为null；**它们不是0**，需要独立full审计验证。

SQLite主库逻辑分配69,914,624字节（约66.68 MiB），主库+WAL磁盘占139,876,376字节（约133.40 MiB），仍低于192 MiB软预算；停因为 `max_new_groups`，没有发生WAL截断，也没有源文件指纹变更。当前索引不能用于未经认证的H5/Parquet自动并集。

## 为什么增加运行时间软上限

此前第36—45组续建仅10组却耗时1,318.813秒，其中1,145.063秒未被当时的分阶段统计解释；现在第46—47组平均每组8.34秒，再次说明不能据单个慢点直接调整SQLite默认写入顺序。为减少批处理在不可预期停顿后继续运行大量行组的风险，本轮加入**可选** `--max-run-seconds`。

- 默认不设置：**完全保留原逻辑**，既有命令无需更改。
- 可选数值：正的有限秒数（如90），从打开年度Parquet footer前的运行起点计算单轮`time.monotonic()`墙钟时间；非法0、负数、NaN、Inf在打开索引前拒绝。
- 每个**尚未处理**的RowGroup开始前检查，并在该RowGroup SQL事务提交、现有SQLite磁盘/WAL预算检查完成后再次检查；耗尽则不继续下一个组，保存完整checkpoint和进度JSON，`stopped_for=max_run_seconds_before_group`或`max_run_seconds_after_group`。
- 报告增加 `max_run_seconds_soft_budget` 和 `soft_wall_budget_reached`；若年度未完成，已有 `run_limited_before_complete`仍正确指示受限停止。此限制与 `--max-new-groups`、`--max-index-mib`独立并存。
- **不是硬性超时**：无法中断正在进行的一个Parquet读取、SQLite事务、OS休眠或日志checkpoint；超过90秒仍可能继续至该组完成。运行起点之前的源清单建立、索引连接/克隆和最后的full审计、报告写入也不由该选项硬限制。
- 继续保持原始 `D:\stock` 只读；V3索引、WAL与报告只能位于 `H5ParquetReconciler/work`和`reports`，无任何H5/Parquet并集写入。

## 本机下一次限量续建建议：47→最多52组

先在仓库根目录通过完整合成测试，确认主V3索引实际为47/522且有足够本机磁盘余量，再运行：

```powershell
git pull --ff-only origin main
.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test*.py" -v
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\index-parquet-5min-coverage.py "D:\stock" --year 2025 --universe a-share-candidate --resume --max-new-groups 5 --max-run-seconds 90 --max-index-mib 192 --journal-mode wal --write-order source --report-detail progress --read-only --report "reports\pq-5min-2025-v3-soft-wall-52.json"
```

若报告名已存在须换新路径，绝不能覆盖旧报告。不要同时打开其他写入进程。检查 `row_groups_complete`（最多52）、`new_row_groups_this_run`、`stopped_for`、`soft_wall_budget_reached`、`soft_budget_reached`、`sqlite_budget_measure_bytes` 与分阶段/每组墙钟时间；不能将出现 `progress` 的null指标解读为无重复。

建议累计到约50组后单独执行已有的 `audit-parquet-5min-coverage.py` 做一次完整键审计（不推进任何RowGroup），再规划后续增量。出现不一致或异常时停止继续扩大处理规模。

## 开发及验收状态

仅改索引器可选时间预算、3项合成测试和文档，不改索引schema、主键、时标、去重策略、`source`默认写入顺序或历史索引。新测试覆盖阈值、非法参数及合成Parquet中断后安全续跑；此前预期98项+3=**预计101项**，实际总数和通过结果以用户Windows Python3.11本机运行结果为准。本轮没有在本机真实Parquet上继续推进第48—52组。
