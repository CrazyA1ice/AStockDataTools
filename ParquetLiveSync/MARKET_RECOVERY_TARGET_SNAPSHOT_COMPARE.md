# 八周期物理目标双时间点快照比较（只读、没有 CAS 提交权）

## 目的

AStockDataTools 是长期跨日期、证券、数据源与八周期的行情清洗和数据库维护工具。前序 PR #273 已在用户 Windows 固定提交 `32fa76dd996c35cf0dd2f42c8e4a92ced852057b` 上执行 **360/360 项回归 PASS**；九只 2026-11-25 原生产隔离对应的八周期 **8 个可能目标文件**已成功去重，每个文件对应 9 个稳定审核请求。生成的只读蓝图规范诊断 SHA256：

`483c61620d4e9385ed9c7d3ecfb0e9dad961194befadf8bbf15d0f0553997eab`

特别注意，上一轮没有传 `--target-root`，**因此这八个可能目标文件的真实物理字节根本没有被读取或取得 SHA**。这串摘要仅是已生成目标足迹 JSON 的诊断 SHA，不是八周期数据文件备份、CAS 锁或供应商身份凭证。

## 新增只读能力

`market_recovery_target_snapshot_compare.py` 在原 `market_recovery_transaction_preflight` 的目标蓝图上新增：

1. **旧快照严检**：旧蓝图必须是操作者确实另外保存的完整原始 JSON，使用独立指定的 `--prior-root`、`--prior-relative`、`--prior-file-sha256` 三个参数，检查真实文件字节 SHA、内部 `blueprint_sha256`、源审核方案 SHA、原 backlog SHA、冻结布局年度、稳定审核请求数、全部八周期目标与仍为 false 的下载/写库/备份授权字段。最大 4 MiB；在大文件哈希之前检查大小；拒绝路径越界、符号链接、重复 JSON 键和物理文件读时变化。
2. **范围保持**：新旧审核计划、布局年度、backlog、各物理目标及其所关联的审核请求 ID 必须完全一致，否则停止并要求**重新建立基线**，不允许对不同数据版本强行比较“文件是否变更”。同一请求必须恰好覆盖 8 个**不同周期**。
3. **观测差异桶**：分别表示双次未观测、一次未观测、双次缺失、文件新增、文件消失、SHA 不同、SHA 相同但**没有锁**。如果任一时间点未实际读取目标文件，就不把相同的文件路径/蓝图 SHA 当成物理文件相同。
4. **仍然阻塞**：即使两次实际物理 SHA 相同，结论也只意味着在两次读取时间点观察到相同字节 SHA。源在扫描后可能变化，没有排它锁，也没有证明回滚可用。报告中 `physical_source_lock_held=false`、`compare_and_swap_authorized=false`、`backup_materialized_or_restoration_tested=false`、`production_merge_authorized=false`、`market_files_written=false`，不会下载 QMT、生成私有行情候选、关闭原生产隔离或修改正式 Parquet/H5。

## 默认安全运行

不提供 `--target-root` 和旧蓝图三个参数时，只重新生成当前来源审核蓝图，**既不会扫描八周期物理文件，也不会执行快照时间差异比较**：

```powershell
& "D:\ChatGPT\AStockDataTools\.venv\Scripts\python.exe" -B "D:\ChatGPT\AStockDataTools\work\PINNED_WORKTREE\ParquetLiveSync\market_recovery_target_snapshot_compare.py" --module-root "D:\ChatGPT\AStockDataTools\ParquetLiveSync" --start-day 2026-11-25 --end-day 2026-11-25 --layout-year 2026 --summary-only
```

预期状态是 `NO_PRIOR_BLUEPRINT_SUPPLIED_COMPARISON_NOT_PERFORMED`，不是物理文件相同。仅当用户已经合法取得、完整保存旧蓝图并核对文件真实 SHA，且另行允许读取现存八周期数据库文件时，才能提供 `--prior-*` 与 `--target-root`。没有必要也不能为了“凑两份独立证据”自动复制同一份未读取市场数据或虚构签名。

此模块**默认不持久保存蓝图**。若未来需要有审计意义的历史快照保存、真实可恢复备份和 CAS 事务，将分别经过隐私范围、存储位置、校验和回滚前提的独立授权；目前所有操作只打印 JSON 到标准输出。

## 测试与限制

本轮隔离 Python 3.13 真实执行新增 **32/32 单测 PASS**，加上前置目标足迹 23/23 与审核方案 29/29 各项离线测试也通过。包括八个不同周期守恒、跨年月布局、历史源范围变动重新基线、实际临时文件 SHA、物理文件出现/消失/字节改变、无物理观测、不一致授权、旧 JSON 文件 SHA/重复键/路径、超过 4 MiB 的提前拒绝、无操作权限等。已核对提交的源和测试 Git Blob 与执行字节完全一致。

**未完成**：本轮新分支的 Windows 真实 `pyarrow` 环境累计回归，以及有真实物理目标文件的跨时间快照对照。原 360 项 Windows 通过不应提前写成新增后 **392 项通过**。原 5,206 已接收 +9 隔离、47 项问题与 `PARTIAL` 状态均保持不变。没有独立交易所股票全集认证、原始 QMT 1min 修复、私有 Parquet 候选、备份恢复演练或正式写库授权。

## P3.4：跨周期分片一致性与物理观察覆盖补强（只读）

本阶段专门修正两个“诊断摘要可以重新计算，但输入在语义上自相矛盾”的边界案例：

- **同一审核请求的八周期目标必须采用相同的年/月分片名**。例如同一个 `review_request_id` 同时被分配到 `1min/2026-10.parquet` 和 `5min/2026-11.parquet`，即使各自路径合法、八周期数量为八且内部蓝图 SHA 已重新计算，也必须报 `SNAPSHOT_REVIEW_REQUEST_CROSS_PERIOD_SHARD_MISMATCH` 并停止。不同股票日的不同请求仍可以合法属于不同月。此处仅检查蓝图的跨周期守恒，不能替代原审核请求里交易日与目标分片的来源证明。
- **相同文件 SHA 却记录不同字节长度属于自相矛盾的来源记录**，即使重新计算蓝图 SHA 也要报 `SNAPSHOT_IDENTICAL_SHA_DIFFERENT_FILE_SIZE`，不能称作“字节未变”。纯十六进制字母大小写差异不构成 SHA 内容漂移。
- **增加物理比较覆盖口径**：`physical_sha_pairs_compared`、`not_observed_at_one_or_both_timepoints`、`absent_at_one_or_both_timepoints` 三个互斥统计之和必须等于目标文件数；`full_physical_sha_pair_coverage` 只在非空目标集合每个文件在两个时间点都有合法物理 SHA 时为 true。即使为 true，仍然没有源文件锁、CAS、备份、数据校准或生产写入权限。

本补强在已有 `market_recovery_target_snapshot_compare.py` 内进行，不增加磁盘写入，也不扩大默认文件读取范围。原 2026-11-25 未提供旧快照或 `--target-root` 的验收状态及八目标足迹 SHA 必须保持不变。

新增九项不依赖真实市场数据的跨日期、跨周期、同 SHA 不同大小、物理覆盖和无授权回归。其完整 Windows 验收目标是此前 392 项加九项，即 **401 项方法**。在用户 Windows 执行前，不能宣称 401/401 已通过；也不能把新增代码提交等同于交易数据质量认证。
