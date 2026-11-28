# P3.24：固定 77 个财务待审股票的 QMT 本地 Finance DAT 文件名和元数据只读普查

## 前置、现存路径与可审计范围

P3.22 已由操作者固定 `b97386c994b60b33eb40f919324e465663d287ff` 实际 Windows 验收：选定 31 模块 **721/721 PASS**。原生产 `qmt_extra_financial_cache_import._prior_rows` 在严格固定的 76 个来源冲突范围、91 份旧 Parquet、48,754 行旧原始财务记录上，与独立 P3.21 旧来源的 46,478 不同／46,485 含重复 Counter 并集完全一致，旧内容 SHA `6d0fad5f54cb97730f2a9da8231c376491ba8a9c57d4e140133f0910f16b1cd5`。这**只证明旧保存财务源**。

已核实的保存进度文件 `ParquetLiveSync/work/qmt_extra/financial-cache-progress.json` SHA `2c1ef16dd2e9ef275e08175211d94968be15b55e78fc9e73555b0f3303a9c89a` 仍有财务 `SOURCE_HISTORY_CONFLICT=76`、`CACHE_DECODE_ERROR=1` 的原保存待审，不能被旧 `progress.json` 中的 `financial_pending=0` 抵消。这些数值是保存的本地状态，不是对当前 QMT 实时接口的证明。

查证既有 `ParquetLiveSync/run-qmt-financial-daily.ps1` 第 3 行，现有财务任务入口的明确参数默认 `$FinanceDir = "D:\software\JHQMT\datadir\Finance"`；既有 `qmt_extra_financial_cache_import._stock_universe` 对每个 `Finance/SH|SZ|BJ/86400` **只枚举** `<6位证券代码>_7<3位数字>.DAT` 文件名以补充退市证券等股票范围，**并不反解 DAT 私有内容**。该路径来自仓库的任务配置，是否现时仍存在须通过用户本机实测，不能从配置推断目录已存在。

更关键：`qmt_extra_financial_cache_import._worker_batch` 在 `tempfile.TemporaryDirectory(prefix="finance-cache-batch-",dir=workspace)` 下创建 `records.json`，读取九表结果之后即清理；生产 worker 输出不是长期保存的、可复验的 fresh 财务原始记录档案。原 `financial-cache-progress.json` 只记录原始新源已被判为冲突的**原因、时间、尝试次数和简短 detail**，没有九表新原始记录。因此目录里的 DAT 文件**即使存在**，也不代表它对应的财务新鲜快照完整/来源可鉴别、更不代表 `saved-current` 多重差异已经不存在。

## 本阶段只读可执行检查

独立 `market_finance_pending_dat_filename_readonly.py`：

`--module-root D:\ChatGPT\AStockDataTools\ParquetLiveSync --stock-root D:\stock --finance-dir D:\software\JHQMT\datadir\Finance --expected-ledger-sha256 2c1ef16dd2e9ef275e08175211d94968be15b55e78fc9e73555b0f3303a9c89a`

- 先严格核对旧 P3.18 的模块根、真实 `AllCycleAStockData/qmt_extra` 数据根与固定 `financial-cache-progress.json` 物理 SHA、类型、非链接文件及队列身份；只取其中 `pending` 的 **77 个**代码及原因在内存中作为白名单。其他股票的文件名不形成扫描结果、不读取文件属性。
- 只枚举用户明确指定、存在的本地 `Finance` 根下 `SH/86400`、`SZ/86400`、`BJ/86400` **直接目录项**，不递归。拒绝真实源根/市场/日目录或作用域内匹配 DAT 文件的符号链接、Windows reparse、非法非普通文件；缺失市场目录记录为缺失但不会创建。文件名只接受 6 位代码加 `_7xxx.DAT`（大小写不敏感）；匹配的股票须来自物理已验 `pending`。绝不打开、读取、解码或哈希任何 DAT 内容。
- 每市场最多 **100,000** 个直接目录项、全市场最多 **250,000** 个、匹配待审文件名最多 **100,000** 个；超过预算、账本 SHA 改变、目录属性/文件元数据在**两遍扫描之间变化**即失败关闭。只根据普通文件的文件名、大小、修改时间和文件身份编制不可逆**元数据**清单 SHA256（与 DAT 物理文件 SHA **完全不同**）。
- 结果按 `SOURCE_HISTORY_CONFLICT` 和 `CACHE_DECODE_ERROR` 两类分别汇总：固定待审股票数、有匹配文件名的股票数、有非空文件名的股票数、无文件的股票数、仅零字节文件的股票数、匹配文件名数及总字节数。报告只输出合计与目录项数，不公开逐股票明细或隐私路径；即使 `matching_pending_file_names > 0` 也绝不把文件名数量等同于九表数、原始行数、源提供商可靠性或覆盖完整性。
- 严格输出 `finance_dat_contents_read=false`、`finance_dat_file_sha256_verified=false`、`finance_dat_table_mapping_certified=false`、`source_financial_nine_table_coverage_certified=false`、`fresh_finance_original_rows_available=false`、`fresh_finance_records_compared_to_old_union=false`、`finance_dat_metadata_proves_provider_origin=false`、`financial_pending_resolved=false`、`financial_repair_authorized=false`、`original_run_receipt_authenticated=false`、`original_quarantines_cleared=false`、`market_files_written=false`、`qmt_cache_queried_or_modified=false`、`qmt_download_calls=0`。
- 两遍读取元数据相同**并不提供跨文件写锁**，因此 `cross_file_atomic_snapshot_certified=false`；存在的 DAT 可能是过时、损坏、部分表或不属于本次失败时点，不能据此解除来源历史差异或缓存解码隔离。

## 测试及边界

新增**18 项纯合成临时目录测试**：无文件、单个文件、两类原因独立分布、大小写文件名、不同交易所目录缺失、无关股票不读取、非法文件名忽略、零字节警告、单股多 DAT、链接路径拒绝、直接目录/全目录/匹配文件数限额、固定账本 SHA 不符、扫描期间元数据变化、报错信息不泄露路径、无 QMT/原始 DAT 内容读取与 `unittest.TestCase.run` 不遮蔽。旧 P3.22 在真实 Windows 已通过选定 31 模块 721/721，新增后目标 **32 模块 739 项**，另原审计器 15 项。**P3.24 新代码和 739 项尚未在 Windows 实机运行，亦尚未看到 Finance DAT 目录当前是否存在。**

若本机 Finance 根缺失或访问受阻，应明确报告证据缺口，不尝试调用 QMT 创建缓存或从其他路径猜测目录。即使核验 DAT 名称确实存在，下一个真正可比的阶段依然要求**受控、可独立验证的新九表原始记录**；原 `qmt_extra_financial_cache_worker.py` 的一次性 worker JSON 因默认回收不可作为现存记录。原 2026-11-25 定时保存回执固定 SHA `72a7104bd831e969958507399263ff74fb4092d6f7bf51d4ac3c42e000a1d837` 仍缺失；历史九条行情隔离与财务 76+1 待审独立保留，全部 PR 继续 Draft，禁止写行情或合并 main。
