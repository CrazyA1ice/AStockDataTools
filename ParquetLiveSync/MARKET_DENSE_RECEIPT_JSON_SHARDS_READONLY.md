# P3.13：唯一剩余的高密度 receipts 直接 JSON 证据取证（只读）

## 真实 Windows 证据和剩余问题

已验收旧 P3.12 固定 SHA `985c39271bc19a9ba9cc360bacfcce0450351e5b`：原审计器额外 15/15、24 模块选定的 589/589；后续固定诊断 SHA `66d62a2a0e3a184db559bdc2c3ac3e76129f1889`：原审计器 15/15、诊断 27/27 通过（最新的选定 592 项还没有执行）。

用户在实际 `ParquetLiveSync/work` 的深度 3（根目录+所有一级子树，再细分 `qmt_1min_market`）有界取证后，只有 `qmt_1min_market/20261014_20261112` 下的两个目录曾阻断。专项只读直达 JSON 取证进一步确认：

- `source_parquet`：**0 个直接 JSON**，检查完成、无目标 SHA 命中。
- `receipts`：直接 `*.json` **至少 129 个**，旧 P3.12 的 `MAX_JSON=128` 保护正确阻断，**没有进入实际内容 SHA 检查**。
- `20261014_20261112` 自身、`day_recovery`、`opening_first_trade_v1`、`private_monthly_1min_v1` 的受限直接扫描都通过，总计检查 5 个 JSON、无匹配。其他所有已列明深度 3 子树也在各自安全预算内检查过。不能因为 `receipts` 尚未完成就声称整个 `work` 深度 3 找不到原件。

原始历史运行回执 SHA256 始终固定 `72a7104bd831e969958507399263ff74fb4092d6f7bf51d4ac3c42e000a1d837`；当前 `last-afternoon-unified.json` 的真实 SHA `6c283e5979312ea2bdf248747fd836bf96f8b0ce5e0a9e48c53d6e14955ff1c2`，不能互相替代。

## 新工具：按独立 SHA 文件名分片，逐片有界取证

新增 `market_dense_receipts_direct_json_shards_readonly.py`，限定且硬编码唯一扫描范围为既有 `ParquetLiveSync/work/qmt_1min_market/20261014_20261112/receipts` **直接一层 JSON 文件**；禁止相对路径输入、目录递归、QMT API、历史下载、文件写入、恢复回执、Market Parquet/H5 修改或隔离准入。

元数据级安全边界：只枚举直接目录，目录项**最多 65,536**，直接 JSON 物理元数据**最多 8,192**；这与旧 P3.12 的 768 目录项通用定位器属于不同只读工具，不会修改其 768 项和 128 JSON 预算。只对 JSON 实际读取内容：先将全部已见直接 JSON 名称计算稳定 SHA-256 文件名桶，16 桶中大于 128 个文件的桶细分为 256 桶，严格保证每个桶最多 **128 个 JSON**、累计最多 **64 MiB**，单个 JSON **24 MiB**，一次专项任务累计物理 JSON 读取量最多 **512 MiB**。某一分片不能满足上限就直接拒绝、不能输出 `scope_exhaustive=true`。即使目录包含成千上万的非 JSON 行情文件，也不会对它们读取内容或计算 SHA。

对每个 JSON 先后检查物理文件元数据（设备、inode、大小、mtime、模式），用既有 `market_quality_source_proofs._hash_stable_file` 进行读取与物理 SHA 核验；对目标 SHA 命中进行第二次物理读取校验。读取前、结束后完整对比目录级 JSON 文件清单及其排序 SHA-256、全部条目数量、元数据和目录身份，发现扫描期间新增/删改均拒绝。目标 SHA 严格固定，不允许用用户任意哈希替换或假证据通过。

只在所有 JSON 都成功核验且完整集合不变时，输出 `scope_exhaustive=true` 和准确的 `direct_json_candidates / physically_hashed_json_files / matching_file_count`。结果不输出普通文件名、私有绝对路径和 JSON 内容；只有真正 SHA 匹配时才返回 `work` 下的相对路径，标识为**仅物理字节命中**而非独立供应商认证、阶段日志合格、原候选 SHA 合格或行情准入。

## 与原审计链的衔接

如确实找到原始 SHA 且仅一个真实匹配文件：

1. 先调用 P3.12 现有 `audit_market_quarantine_readonly.py` 的 `--receipt-relative <此工具输出的确切路径>`，仍钉死上述 2026-11-25 回执 SHA、原次定时启动、EIGHT_PERIODS 阶段日志和当日候选 Parquet 物理 SHA，检查原 5206 accepted / 9 quarantined / 5215 expected。
2. 上述全通过后才能以相同真实相对路径调用 P3.11 `market_nine_quarantine_offline_source_gap_readonly.py`，仅核对既有三个私有 QMT probe 取证文件与原 9 条隔离是否在同日同票匹配，绝不能自动关闭隔离或添加行情。
3. 无 SHA 命中意味着**当前 `work` 深度不超过 3 的已列明 JSON 文件集合**没有发现原始字节；不能据此推断其他工作树、任意备份、压缩档、深度大于 3 的位置或外部系统中也不存在原始回执。

## Windows 实机文件身份字段差异及修复（2026-11-27）

用户 Windows 首轮在 `df10a86` SHA 出现 22/22 个测试夹具 `setUp` 目录缺失错误，固定 `a493186` 中通过先创建临时 `work` 解决。第二轮 `a4931867ad01defd6ecfd17b99171bc53b6b8deb` 实际运行旧原审计器 15/15 通过；新 22 项中出现 **4 个 ERROR、5 个 FAIL，其余 13 项通过**，均因在尚未改写的合成文件上抛 `DENSE_FILE_CHANGED_DURING_HASH`，其中一些本应报告文件体积/分片预算/目录变化。此问题定位到旧实现把 Windows `os.scandir()` 的 `DirEntry.stat(follow_symlinks=False)` 与 `pathlib.Path.stat()` 不同 API 的文件身份字段直接比较；Windows 缓存目录项信息可能未提供与实际物理 `stat` 相同的 inode 等身份信息，因此**推断是元数据 API 兼容差异，仍待 Windows 新版实机确认**。

修复仅将初始快照内 `item.stat(follow_symlinks=False)` 改为 `os.stat(item.path, follow_symlinks=False)`，后续 `Path.stat()` 和 `market_quality_source_proofs._hash_stable_file` 不变，继续拒绝 symlink、文件身份变动、内容哈希不稳定与目录清单变动。针对这一差异增加一个测试，用模拟 Windows DirEntry 缓存元数据缺失的代理对象（其 `stat` 故意抛错）确认新快照只以路径上的无跟随 stat 作身份依据。原 22 个测试全部保留，新阶段 **23 个专项测试、选定 25 模块 615 项**，另单独执行旧原审计器 15 项。不得将其视为已经通过 Windows 或已取得真实历史回执；最后 `receipts` 的 SHA 扫描仍未执行。

## 验收与限制

新分支最初新增 **22 个**合成临时文件回归用例，包括超过 768 个非 JSON 文件与 140 份 JSON 的实读、16→256 稳定分片/不重不漏、单片超限拒绝、原固定 SHA、不递归、符号链接、扫描中改写、目录元数据变化以及 CLI 不泄漏路径。目标 Windows 选定回归是旧 24 模块 592 项加新 1 模块 22 项，即 **25 模块 615 项**，另须单独跑原审计器的 15 项。当前仅代码与测试提交、GitHub 静态审查，不得在真正 Windows 614/614 和原始收据物理检查前宣称通过。PR 保持 Draft，不能合并 main 或改写历史回执。

如果目录项超过 65,536、JSON 超过 8,192、任一细化为 256 桶后仍超过 128、内容超过单文件/分片/全局预算，或活跃目录有变动，应报告具体安全错误码并保持未完成；不能自动提高上限、跳过候选或伪称没有原始回执。
