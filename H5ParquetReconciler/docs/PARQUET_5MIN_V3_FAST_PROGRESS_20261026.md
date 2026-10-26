# 2025年五分钟V3索引：40组写入排序实测与安全的快速进度报告

更新：2026-10-26；仓库 `CrazyA1ice/AStockDataTools`，模块 `H5ParquetReconciler`。

## 实测：第36—40组，同一35组快照、同一WAL模式

用户上传 `pq-5min-2025-ab-pk-sorted-40.json` 和 `pq-5min-2025-ab-source-order-40.json`。两份实验使用**相同35组索引源指纹** `516ae482...` 的独立SQLite快照，分别新增5组。均停于40/522组，扫描616,446条源键，有效唯一规则五分钟键4,918,521，重复键0（仅当前40组），证券—日期分区1,276,936，逻辑行组定位关系2,473,089，排除非候选771，异常时间/不识别证券/年份偏移均为0。两份报告既有覆盖字段完全相同，主库物理B-tree页数略有差别，不能误判为数据冲突。

|字段|source原顺序|pk-sorted主键排序|结论|
|---|---:|---:|---|
|新增5组总耗时|55.484秒|50.922秒|单轮快4.562秒、8.22%|
|SQLite写入阶段（含排序开销）|30.969秒|26.452秒|快4.517秒、14.59%|
|Parquet读取+键聚合|14.267秒|14.703秒|排序实验该阶段慢0.436秒|
|最终全表索引汇总|10.156秒|9.687秒|单轮快0.469秒|
|预算检查及WAL日志|0.062秒|0.064秒|基本相同|
|WAL截断检查点|5次|5次|均无busy|
|SQLite逻辑页分配|68,268,032B|68,194,304B|差73,728B，不是核心收益|

**暂不自动更改默认写入顺序**：一次先source、后sorted的试验可能受到OS文件缓存等影响。pk-sorted表现值得扩大验证，但不能仅凭5组试验宣称对2025年全部522组都提速14.6%。

## 第二个真实瓶颈：每轮重复完整SQLite摘要

新增性能计时已揭示，无论写入策略如何，第40组结束时对两个百万行级SQLite表做全量`index_summary()`都耗时约**9.7—10.2秒**（占本轮时间约19%）。在每次续建只有5—10个RowGroup的情况下，这笔完整核验成本重复出现且随着主库扩大可能上涨。

本轮新增可选`--report-detail full|progress`：
- **默认仍为`full`**：完整扫描`daily_coverage`与`row_group_locator`，精确计算唯一时间键数、重复时间键、股票日分区和逻辑定位关系数，检查`SUM(source_rows)`与`groups_done`一致。当前既有行为不变。
- **`progress`仅允许对未完成的年度索引节省全表扫描**，仍精确汇报已提交RowGroup数、`groups_done`累计源行/候选行、异常时间与证券类型行数、SQLite空间、每轮耗时和检查点次数。
- 快速模式**不会也不应伪装成完整检查**：`unique_regular_session_keys`、`duplicate_regular_session_keys`、`stock_day_partitions`、`row_group_locator_entries`、`row_group_locator_compact_rows`、`row_group_locator_payload_bytes`统一输出`null`，`full_key_audit_performed=false`、`report_detail_effective=progress`。源行与候选行不是精确唯一键。
- 报告保存时删除此前缓存的旧`duplicate_regular_session_keys`，同时保留`meta.completed=false`，杜绝续建后把上次0个重复键冒充新扫描范围已核实。
- **一旦522个RowGroup全部提交**，即使请求`--report-detail progress`，程序也**强制改为`full`**执行原有两个大表全量审计并验证行数守恒，只有审计成功才可能标记`meta.completed=true`。异常则拒绝把索引认证为完成。
- 该选项不能跳过任何Parquet读取、SQLite写入、行组去重处理，也不影响原始数据的可追溯性；只是省去每批报告结束时的重复全表扫描。快报本身不能证明重复键为0，更不能授权自动补录或合并。

新增5项合成测试：快速报告未知指标必须为null；追踪SQL确认未执行两张大表的全局扫描；最后一组强制完整审计；续建从全量报告切换到快报时清除旧重复键计数；不支持的报告类型必须拒绝。累计预计**88项合成测试**，需要Windows本机验证。

## Windows后续计划：小幅恢复主V3，不覆盖A/B快照

现在主V3应仍在35组（上面两份实验均为克隆，不应修改它）。先确认索引文件仍在，且有足够磁盘空间（WAL写入的事务临时占用可能超过软预算）：

```powershell
git status -sb
git pull --ff-only origin main
.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test*.py" -v
```

如果测试通过，建议从原主V3 **最多续建10组**、仍使用默认`source`写法作保守基线，同时采用`progress`省掉完整SQLite摘要扫描：

```powershell
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\index-parquet-5min-coverage.py "D:\stock" --year 2025 --universe a-share-candidate --resume --max-new-groups 10 --max-index-mib 192 --journal-mode wal --write-order source --report-detail progress --read-only --report "reports\pq-5min-2025-v3-quick-progress-45.json"
```

报告预期当前新增组不多于10，累计最多45/522组（若主索引在此期间已有推进，以真实断点为准）。查看`stage_profile_this_run.phases_seconds.final_index_summary`是否明显小于前次9.7—10.2秒，并核对`row_groups_stats`累计数据、`report_detail_effective`与`full_key_audit_performed`。若使用轻量报告，唯一键和重复键是`null`属于预期，不能按0解读；旧的第40组**快照A/B**上的唯一键4,918,521不能证明正在续建的**主索引**的新范围质量。

应在后续阶段定期执行`--report-detail full`作完整审计；年底必须执行完整索引审计。完整索引和来源元数据未认证前，任何并集数据库创建仍被阻断。

所有新SQLite与JSON报告文件均在 `AStockDataTools/H5ParquetReconciler/work` 和 `reports`，`D:\stock`原始H5/Parquet继续只读。
