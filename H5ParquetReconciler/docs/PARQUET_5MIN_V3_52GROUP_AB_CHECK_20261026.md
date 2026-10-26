# 2025五分钟V3索引：52组稳定续建、完整审计与写入策略严格A/B核验

更新：2026-10-26；只记录本机上传的聚合JSON，不包含原始付费OHLCV。

## 一、已经取得的52组真实证据

用户上传 `pq-5min-2025-v3-soft-wall-52.json`：2025年Parquet V3主索引由47推进至**52/522个RowGroup（9.96%）**，本轮新增5个组、614,400条源行、耗时44.703秒（8.941秒/组）；Parquet读取与聚合16.203秒，SQLite事务28.484秒，进程CPU时间30.469秒。`row_group_loop_other=0`、`unattributed_seconds=0`，本轮没有复现45组时超过19分钟的墙钟空档，但仍不能查明那次异常具体原因。单组整体墙钟时间8.281—9.578秒；继续保持WAL及source写入顺序，没有WAL截断。

累计原始源行6,395,898，A股候选源行6,394,912，排除非候选986行；年份越界、异常时间戳、非法交易时段和不识别证券均为0。SQLite主库约67.74MiB，主库+WAL为141,204,728字节（约134.66MiB），低于192MiB软预算。`soft_wall_budget_reached=false`、`soft_budget_reached=false`、`stopped_for=max_new_groups`，证明90秒软时间预算未触发。**这是progress报告：唯一键和重复键均为null，不表示重复为0，也没有认证全年完整性。**

## 二、第一件事：在52组暂停主索引，独立full只读审计

先在Windows项目根目录执行完整离线测试，再运行**不新增RowGroup**的只读full审计：

```powershell
git pull --ff-only origin main
.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test*.py" -v
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\audit-parquet-5min-coverage.py "D:\stock" --year 2025 --universe a-share-candidate --read-only --report "reports\pq-5min-2025-v3-readonly-full-audit-52.json"
```

检查`row_groups_complete=52`、`source_fingerprint`、`full_key_audit_performed=true`，并审阅`unique_regular_session_keys`、`duplicate_regular_session_keys`、`row_group_locator_entries`和`candidate_source_rows`与行组汇总是否守恒。若出现任何源指纹变化、重复或无效时间记录，先调查数据，不扩大原索引或批准自动并集。结果仍仅属于已处理52组。

## 三、第二件事：从同一个52组快照建立两份写入A/B副本

用户此前第36—40组`pk-sorted`初次A/B快了约8.2%（总时间），但是只进行过一轮，可能存在缓存等偏差。由于现在SQLite写入仍占本轮44.703秒中的28.484秒（63.7%），适合在**已有主库保持52组不变**的情况下，在后续同样的第53—57组做第二次等条件A/B。

**额外本机空间**：两个快照都会独立生成主库和WAL，请先检查本机留有足够剩余磁盘（建议至少额外约1GiB缓冲，具体瞬时空间可能受SQLite和外部任务影响）。确保没有其他程序正在写入原主V3索引。两份A/B命令必须从同一个初始52组主库快照出发，双方应`--max-new-groups 5 --max-run-seconds 90 --max-index-mib 192 --report-detail progress --journal-mode wal`：

**A：原始source顺序**

```powershell
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\index-parquet-5min-coverage.py "D:\stock" --year 2025 --universe a-share-candidate --clone-from-index "work\indexes\pq-5min-2025-a-share-candidate-v3.sqlite" --out "work\indexes\pq-5min-2025-ab-source-57.sqlite" --journal-mode wal --write-order source --max-new-groups 5 --max-run-seconds 90 --max-index-mib 192 --report-detail progress --read-only --report "reports\pq-5min-2025-ab-source-57.json"
```

**B：pk-sorted主键排序**

```powershell
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\index-parquet-5min-coverage.py "D:\stock" --year 2025 --universe a-share-candidate --clone-from-index "work\indexes\pq-5min-2025-a-share-candidate-v3.sqlite" --out "work\indexes\pq-5min-2025-ab-pk-sorted-57.sqlite" --journal-mode wal --write-order pk-sorted --max-new-groups 5 --max-run-seconds 90 --max-index-mib 192 --report-detail progress --read-only --report "reports\pq-5min-2025-ab-pk-sorted-57.json"
```

**如任一报告没有完成5个新增组、实际停因不是`max_new_groups`、两份源指纹不同或主索引已在A/B期间被推进，不进行性能结论，先排查。** 不能拿两份不同范围的报告推断速度，也不能把A/B副本取代主索引。

## 四、新增严格核验工具：数据库逻辑逐行相等之后再报告性能

现有 `index-parquet-5min-coverage.py --report-detail progress` 不会对大表计算完整重复键数，因此直接比较两份progress JSON的速度并不能证明索引结果一致。

新增独立`tools/compare-v3-write-order-ab.py`：
- 校验两份索引V3版本和当前年度Parquet文件指纹、footer行组范围；分别重新计算**完整**SQLite索引审计，拒绝候选键守恒不一致；
- 校验报告指向的是两个不同的模块内SQLite文件、双方都从相同`clone_source_index`开始、源指纹和WAL模式一致、新增组数量一致、均未触发软预算；
- **流式逐行精确比较**`groups_done`、`daily_coverage`、`row_group_locator`三张逻辑表；不导出任何证券/日期/48-slot具体键，也不依赖 SQLite 物理文件大小、页顺序或哈希替代精确比较；
- 只有以上条件全部成立才输出两种写入策略的总耗时和SQLite写入阶段差异百分比；不改变默认写入模式，不标记自动并集可用。一次配对A/B仍可能有缓存偏差，需要后续换先后顺序复验。

离线报告只写在模块内`reports/`，索引和源行情全程只读：

```powershell
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\compare-v3-write-order-ab.py "D:\stock" --year 2025 --universe a-share-candidate --source-index "work\indexes\pq-5min-2025-ab-source-57.sqlite" --sorted-index "work\indexes\pq-5min-2025-ab-pk-sorted-57.sqlite" --source-report "reports\pq-5min-2025-ab-source-57.json" --sorted-report "reports\pq-5min-2025-ab-pk-sorted-57.json" --out "reports\pq-5min-2025-ab-compare-57.json" --read-only
```

若报告文件存在就换新文件名，严禁覆盖；SQLite逻辑明细核验可能需要数十秒甚至更长，取决于磁盘与分区量。若与其他正在写索引的任务同时运行，不能声称来自固定快照。

## 五、验收限制

- 本轮**没有**在用户机器处理第53—57组，没有52组full唯一键/重复键实测，也未实际得到新的A/B速度。
- 添加6项合成测试，覆盖仅凭progress报告不能证明重复键、完整full审计、流式不同内容检测、来源/行组/预算停止条件拒绝、时间数值拒绝及SQLite路径保护。原预计101项，本轮**预计107项**，最终以Windows本地实际测试为准。
- 新比较工具是独立只读证据核验，不是合并器；未认证的时间标签、证券主数据、量价单位、供应商真值、异常冲突和完整年份全部保持阻断。不会生成可覆盖原H5/Parquet的文件。
