# P3.11 原 9 条隔离与现有本地分钟源覆盖缺口（只读、无 QMT API）

## 目的

P3.10 已由用户 Windows 固定提交 `a9698deb4eccb1ec78b5fc1bb46adfe1c2403baf` 通过 **542/542** 项回归；三只 QMT 探针私有文件在 2026-10-14～2026-11-12 的 66 个真实股票日，观察到分钟成交量与本地 DAY 成交量存在高度一致的候选 100× 单位差，开高低收和原始成交额很接近。**这 66 个股票日均不是 2026-11-25 九条隔离数据**，不能将候选 100× 自动应用于生产补全。

必须明确评估当前真实原始故障缺口：2026-11-25 固定运行回执 `72a7104bd831e969958507399263ff74fb4092d6f7bf51d4ac3c42e000a1d837` 已确认 **5206 接收、9 条隔离、总共 5215**。其中 7 个 `QMT_RAW_ONE_MINUTE_MISSING`（`SZ300119`～`SZ300125`），另外 2 个 `OFFICIAL_DAY_OHLC_MISMATCH`（`SH605336`、`SZ300462`）。保留全部原回执与候选数据，不得删除 quarantine。

## 检查范围与真实性约束

新增 `market_nine_quarantine_offline_source_gap_readonly.py` 通过操作者**明确指定**的真实 `ParquetLiveSync` 模块目录与**现有**私有 QMT 探针目录，只读完成：

1. 使用原 `audit_market_quarantine_readonly.audit(...,verify_parquet=True)`，严格核对固定运行 SHA、当日正式调用、原 9 条的**确切证券和分类**、5206/9/5215、原候选 Parquet SHA、隔离未清除；检验扫描前后两次原回执同一性。即使当日已被修复或状态漂移，也只报告不符合钉死的原始验收条件，不批准修复。
2. 用原 `market_local_evidence_inventory_readonly.inspect` **仅遍历一次明确指定目录的直接 `.jsonl` 子文件**，限定最多 16 个现有文件、合计 64 MiB；每个单文件仍遵循 P3.5 的最多 32 MiB、20,000 行及 64 天窗口。不能递归整个硬盘、QMT 缓存目录或生产 H5/Parquet。
3. **实际读取 JSONL 行**推导其证券与实际最早/最晚日期，而不是相信文件名。再复用 P3.8 `market_native_minute_window_readonly.inspect` 做整文件合法时间格、唯一时间戳、OHLCVA、目标日期覆盖及物理 SHA/大小/身份复核。文件内容错误、包含多股票、读写竞争或不可靠原回执时整个检查立即失败，不默默跳过坏文件。
4. 对原 9 个 `SH/SZ六位码` 分别输出：明确目录里没有相同股票的已验收 JSONL；有相同股票文件但实际内容日期不涉及 **2026-11-25**；出现多个同证券文件须人工消歧；有目标日的原生 241/240/部分缺格时准确记录。**即便恰好 241 根，仍只表示该本地文件中存在逐行合法时点，不证明真实 QMT 来源、购买源校准、官方 DAY 六字段相容或原隔离可入库**。
5. 所有 `supplier_origin_authenticated`、`calibration_approved_or_applied`、`official_six_field_quality_passed`、`original_quarantines_cleared`、`production_merge_authorized`、`market_files_written`、`qmt_cache_queried_or_modified` 都必须始终为 false，且 `qmt_download_calls=0`。本操作不会调用 `xtquant`、`get_market_data_ex`、`download_history_data`，不会触碰生产 Parquet/H5、原 9 条隔离、47 项问题记录、原回执或调度器。

**重要解释**：若真实目录内仅有此前三份 `000001.SZ`、`600000.SH`、`688001.SH`（实际内容截至 2026-11-12），则当前**明确目录**找不到 2026-11-25 九只股票的对应原始分钟文件。不能扩大结论为 QMT 服务端/其他本地磁盘不存在分钟数据。真正的下一选项需从既有 QMT 缓存进行**单次明确授权的只读查询**或经授权取得原生证据，不能默认发起下载、解禁生产隔离。

## Windows 实机命令示例

先在固定提交的独立 worktree 完成全量回归，然后用真实生产模块与既有探针目录执行（`PINNED_P311_WORKTREE` 替换为固定提交工作树）：

```powershell
& "D:\ChatGPT\AStockDataTools\.venv\Scripts\python.exe" -B "D:\ChatGPT\AStockDataTools\work\PINNED_P311_WORKTREE\ParquetLiveSync\market_nine_quarantine_offline_source_gap_readonly.py" --module-root "D:\ChatGPT\AStockDataTools\ParquetLiveSync" --minute-evidence-root "D:\ChatGPT\AStockDataTools\ParquetLiveSync\work\qmt_1m_probe"
```

## 当前验证状态

- 新增 23 项独立回归用例：原回执 SHA/9 条证券与分类守恒、显式目录无文件、三个不相关旧文件、同证券旧文件、241/240/239、坏 JSONL、混合代码、多个来源、证据源 SHA 变更、回执/目录伪造、大小预算、链接拒绝、纯只读检查。
- 新阶段 GitHub 已提交源码与测试，**不能将单元测试代码存在等同于在 Windows 或该环境完成执行**。基于 P3.10 已实机验收 542 项，新累计 Windows 回归目标为 **565 项（23 个模块）**，由实际执行日志确定通过与否。
- 在取得真实 Windows P3.11 结果之前，不能宣称 9 条本地探针全部缺失；预计从原目录中已知三只文件的股票身份推断会有缺口，但只有这次物理来源的 SHA 内容重验后才能作相应结论。
