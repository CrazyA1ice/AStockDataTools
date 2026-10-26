# 2025年五分钟V3索引：主库62组事务退出诊断与只读趋势核验

更新：2026-10-26；依据本机上传的 `pq-5min-2025-v3-transaction-exit-62.json`。本说明只使用聚合审计JSON，绝不上传或复制付费原始OHLCV。

## 1. 主索引已从57推进至62/522组

本次 `saved_index=work/indexes/pq-5min-2025-a-share-candidate-v3.sqlite`、`clone_source_index=null`，说明不是先前的57组A/B副本。本轮新增5个RowGroup（文件0编号57—61），总共614,400原始源行，耗时57.297秒；本机报告`stopped_for=max_new_groups`。本次新候选行614,277，累计候选源行7,623,474，累计原始行7,624,698，累计排除非候选证券1,224行（上一批的1,101行新增123行）。年份越界、非法时间戳、异常交易时段与无法识别证券均为0。

SQLite主库约69.27MiB（72,630,272字节）；主库+WAL为145,426,584字节（约138.69MiB），低于192MiB软预算，90秒软运行时间也未触发，未执行WAL截断。主库和WAL相较57组的143,771,264字节增加1,655,320字节（约1.58MiB）；不能把过去10组的空间增长外推为未来460组的保证值。源指纹与以前一致，但它只绑定文件尺寸、修改时间与清单等元数据，并不是对付费Parquet数据内容做强哈希。

**此次仍为progress报告**，`unique_regular_session_keys=null`、`duplicate_regular_session_keys=null`；上一次主库独立full审计停在52组。主库62组需重新执行独立full只读审计后才有可引用的精确键/重复键指标，更不等于完成全年522组或认证H5/Parquet自动并集。

## 2. 事务退出耗时已经被独立测量

| 阶段 | 57组前一批（52—56号） | 62组本批（57—61号） | 绝对差（秒） |
|---|---:|---:|---:|
| 五个RowGroup总耗时 | 40.828 | 57.297 | +16.469 |
| Parquet读取/键聚合 | 14.874 | 16.016 | +1.142 |
| SQLite整段写入 | 25.923 | 41.265 | +15.342 |
| Python构造参数 | 0.312 | 0.328 | +0.016 |
| `daily_coverage` UPSERT | 2.047 | 2.267 | +0.220 |
| `row_group_locator` UPSERT | 8.376 | 12.685 | +4.309 |
| 事务退出及其他 | 15.156 | 25.938 | +10.782 |

最新62组报告新增`stage_profile_this_run.sqlite_transaction_boundary_seconds`：

- `context_enter_seconds=0.0`（报告显示四舍五入值）；
- **`context_exit_seconds=25.938`秒**，与`commit_and_other_seconds=25.938`秒在三位小数精度完全吻合；
- `other_within_commit_and_other_seconds=0.0`。

说明在此次成功提交的5个行组中，此前“事务退出及其他”耗时几乎全部来自调用原SQLite连接`__exit__`，成功退出时包含COMMIT处理。五组逐一为：编号57→2.781秒、58→5.875秒、59→3.516秒、60→6.891秒、61→6.875秒。绝不是一个单点造成25.938秒。

**不能由此证明实际fsync用时是25.938秒**：SQLite连接退出是包围COMMIT的Python计时边界，可能包含SQLite内部同步/等待或Windows文件系统/调度影响；并未直接测到磁盘设备flush。前一批57组仅有`commit_and_other`，没有该细化`context_exit`，不能假称两个批次都直接测得了同一内部边界。两批处理不同编号RowGroup，数据分布、系统缓存和后台负载可能不同，因此+16.469秒是观察差，不是可归因的性能回归。

## 3. 本轮新增纯只读趋势核验工具

`tools/compare-v3-performance-batches.py`只消费本模块`reports`内的两份聚合JSON、保存第三份趋势JSON；**不读取或修改SQLite，不读取Parquet实际行、不会扫描D盘，不会改变任何持久化级别/PRAGMA**。

对照前先严格验证：两份是同一主V3索引而非副本，同一year/universe/source元数据指纹/WAL/source策略与相同90秒/192MiB预算，都按`max_new_groups`正常结束；两轮新增RowGroup均不超过5组、彼此不重叠且顺序连续；累计源行和5个行组计数守恒；子阶段时间加总等于外层SQLite耗时，新的事务边界计时必须嵌套在旧`commit_and_other`内。任何异常拒绝出具速度结论；报告仅有聚合时间及行组编号，无证券/时间键与原始OHLCV。

Windows项目根目录运行：

```powershell
git pull --ff-only origin main
.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test*.py" -v
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\compare-v3-performance-batches.py --previous "reports\pq-5min-2025-v3-sqlite-breakdown-57.json" --current "reports\pq-5min-2025-v3-transaction-exit-62.json" --report "reports\pq-5min-2025-v3-performance-trend-57-62.json" --read-only
```

新增6项完全合成的测试：正常两轮形状、源指纹/主库身份不一致、RowGroup区间不连续、预算/修改状态异常、时间嵌套守恒或NaN错误、路径逃逸/覆盖保护。此前期望115项，加6项**预计121项**；需Windows Python3.11真实运行确认，不得声称开发端已经本机通过。

## 4. 下一步先做62组独立完整审计，别急着改同步持久化

```powershell
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\audit-parquet-5min-coverage.py "D:\stock" --year 2025 --universe a-share-candidate --read-only --report "reports\pq-5min-2025-v3-readonly-full-audit-62.json"
```

这只读取既有V3索引和Parquet footer，不推进RowGroup，不更改原始`D:\stock`，但得到当前62组真正独立的`unique_regular_session_keys`、`duplicate_regular_session_keys`和定位关系数。若出现重复键/校验不一致或源指纹变更，应先调查数据。若报告名已存在，应指定全新路径，不能覆盖。

后续性能试验优先关注**Windows设备写入延迟、SQLite WAL提交时的同步调用与缓存状态**，再考虑是否有其他“保持FULL持久性不变”的手段；不要直接在主索引上测试降低`PRAGMA synchronous`，也不能把一次顺序运行的速度变化推断为特定SQL或文件系统的因果效应。

目前2025年度主索引进度**62/522（11.88%）**，剩余460组。证券分类主数据、五分钟时标供应商真值与全年完整性均未认证，继续保持`safe_to_automatically_union=false`。
