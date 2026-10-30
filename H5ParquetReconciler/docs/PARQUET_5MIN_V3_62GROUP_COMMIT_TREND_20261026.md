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

## 4. 已完成：62组主索引独立full审计（后续上传结果）

用户随后提交 `pq-5min-2025-v3-readonly-full-audit-62.json`，实际验收为：

- `row_groups_complete=62`、`row_groups_total=522`、`full_key_audit_performed=true`、`audit_mode=existing_index_read_only_full`。
- `unique_regular_session_keys=7,623,474`，`candidate_source_rows=7,623,474`，`duplicate_regular_session_keys=0`；原始总行7,624,698，排除非候选证券1,224，完整守恒。
- 证券日分区1,313,404，RowGroup定位关系3,845,191，压缩记录数1,313,404、压缩比2.9277。
- 年度越界、无效时间戳、非预期时段、不识别证券均为0。
- 审计耗时13.235秒，`new_row_groups_this_run=0`，`no_parquet_data_rows_read_this_run=true`，`sqlite_index_modified=false`，`source_files_modified=false`，源文件元数据指纹与本次62组构建相同。

**已完成审计，不需要重跑已经存在的审计报告或重建SQLite。** 上述正确性仍只针对当前62组，不能认证供应商原始行情真值、上市证券主数据或五分钟时间标记，自动H5/Parquet并集继续禁止。

## 5. 下一步：PR #29合并验收，主索引62→最多67组

此开发分支新增的`compare-v3-performance-batches.py`是纯JSON只读工具；只有**合并PR #29之后**，才能通过`main`的`git pull`得到它。新加6项合成测试，总量预计121项，必须用Windows本机的实际`OK`结果确认。

建议仓库根目录执行：

```powershell
git pull --ff-only origin main
.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test*.py" -v
```

如果PR #29仍处于Open状态，主分支预计仍只有此前约115项测试，**不要声称新趋势工具已经可用或已验收**；可在PR合并后重新执行测试。测试全部通过、当前主V3确实为62组、无其他进程同时写主库且确认磁盘剩余空间后，从主库继续最多5组：

```powershell
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\index-parquet-5min-coverage.py "D:\stock" --year 2025 --universe a-share-candidate --resume --max-new-groups 5 --max-run-seconds 90 --max-index-mib 192 --journal-mode wal --write-order source --report-detail progress --read-only --report "reports\pq-5min-2025-v3-commit-67.json"
```

这仍使用原本`synchronous=FULL`；不得直接在主索引上使用更低持久化设置，也不许把A/B副本替代主库。若出现`max_index_mib`软容量触发，严格保留断点并先分析WAL空间回收情况，不盲目提高阈值。目标结果为处理到67/522且`stopped_for=max_new_groups`，实际可能因预算更早停止。

当PR #29已经合并且测试通过，还可以只分析已有两个JSON（不访问SQLite及D盘）：

```powershell
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\compare-v3-performance-batches.py --previous "reports\pq-5min-2025-v3-sqlite-breakdown-57.json" --current "reports\pq-5min-2025-v3-transaction-exit-62.json" --report "reports\pq-5min-2025-v3-performance-trend-57-62.json" --read-only
```

输入和目标必须保存在本模块`reports/`，目标文件不能已存在。该趋势仅展示不同RowGroup批次的**观测差异**，不能证明`fsync`、SQLite版本或Windows缓存是因果根源。主索引仍未完成年度522组认证；`safe_to_automatically_union=false`保持不变。
