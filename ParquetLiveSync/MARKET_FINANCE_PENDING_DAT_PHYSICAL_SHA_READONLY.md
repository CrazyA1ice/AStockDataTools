# P3.26：只读计算 77 个财务待审股票所对应原 QMT Finance DAT 物理字节摘要

## 真实已验前提与边界

P3.25 在固定提交 `e6fb7cb0debd84755c99351b50bb74463affe4ca` 用户 Windows **33 模块 757/757 PASS**。通过固定财务队列 `financial-cache-progress.json` 物理 SHA `2c1ef16dd2e9ef275e08175211d94968be15b55e78fc9e73555b0f3303a9c89a` 及 P3.24 真实 DAT **文件名/大小/mtime/设备/文件身份元数据**清单 SHA `b5aa0aa3f0879eabbb65499d962fda3087a090f963399f42b72b13799c8dc711`，发现 77 个既有财务待审股票每只均有**恰好 8 份非零的 `_7xxx.DAT` 文件名**。合计 616 文件名／70,748,048 字节，历史来源冲突 76 股／608 文件／70,457,520 字节（SZ），单独解码异常 1 股／8 文件／290,528 字节（SH），本阶段从不猜测其它股票。每组内同一文件名后缀集合，不证明两组跨组一致；616 个文件 mtime 在 UTC 2026-11，每股票自己内部 8 文件的最早/最晚 mtime 差在一天以内，**不等于业务报告期、供应商采集日期或任何真实源版本身份**。

P3.25 实际**没有读取 DAT 内容物理字节**，因此原 DAT 文件名存在性与修改时间本身不构成不可变内容证明。原本地财务 worker `records.json` 用 `TemporaryDirectory` 临时保存后清除，不能拿进度账本内 `removed_or_revised` 错误描述当作当时完整 fresh 九表记录。P3.21/P3.22 的 91 旧 Parquet 原始行和 46,485 条旧历史 Counter 数据，属于**保存的旧来源**，不能代替新 QMT 原始数据。

## P3.26 仅读取固定范围原生 DAT 的物理字节，不反解

独立工具 `market_finance_pending_dat_physical_sha_readonly.py` 必须强制提供两个经过实机验证的固定 SHA：

`--module-root D:\ChatGPT\AStockDataTools\ParquetLiveSync --stock-root D:\stock --finance-dir D:\software\JHQMT\datadir\Finance --expected-ledger-sha256 2c1ef16dd2e9ef275e08175211d94968be15b55e78fc9e73555b0f3303a9c89a --expected-dat-metadata-sha256 b5aa0aa3f0879eabbb65499d962fda3087a090f963399f42b72b13799c8dc711`

1. 开始完整复验 P3.25 `PROFILE.inspect`，间接多次复验 P3.24 的账本/目录/元数据清单 SHA；再从固定旧队列仅选出原 77 pending 股票。三个明确的 `Finance/{SH,SZ,BJ}/86400` 直接目录（路径来自原 `run-qmt-financial-daily.ps1`）须存在并拒绝 symlink、Windows reparse、其它非法路径；忽略其它证券和非法 `_7xxx.DAT` 文件，不遍历其内容。
2. 只为与 pinned pending 股票匹配的原生文件名生成目录项 `stat` 身份；须按 P3.24 完全相同的 `market,stock,filename,st_size,st_mtime_ns,st_dev,st_ino` 排序重算**元数据 SHA**。任何目录增删、大小/mtime/设备标识/目录项身份发生变化，则在实际打开 DAT 之前失败停止。约束扫描：每市场最多 100,000 个目录项、全范围最多 250,000 个、匹配文件最多 2,048（P3.24 本身允许最多 100,000 个），单文件最大 **128 MiB**，所有匹配文件总大小最大 **256 MiB**；不能因为超预算而静默跳过文件并输出“已通过”。
3. 对每个已固定的文件用严格只读 `os.open` 文件描述符读取最多 1 MiB/块、总计最大上述 256 MiB，使用 `hashlib.sha256` **仅在内存里计算原始物理字节 SHA256，不进行 DAT 解码/解析，不构建财务记录、不写文件，也不把内容拷贝到其他位置**。每文件连续**打开读取两遍**；两次 SHA 必须完全一致，同时每次读前/读后严格复验固定的路径 `stat` 身份、已打开文件 `fstat` 的规则文件属性与 size/mtime：Unix 继续完整比对 `fstat` 设备号、inode、权限位元组；Windows 由于 CRT `fstat` 的 inode/设备号可能与路径 `stat` 不一致，额外通过 `GetFileInformationByHandle` 对打开的 DAT 句柄和同一路径新打开的只读验证句柄比较**卷序号＋真实文件索引**，不可获取内核句柄身份时拒绝验收，绝不因 Windows 差异静默跳过身份校验。拒绝截断、追加、被替换或读取途中不一致。物理文件完整哈希仅作为最终聚合清单里 `[market,stock,filename,st_size,st_mtime_ns,st_dev,st_ino,sha256_of_D​AT_bytes]` 的散列输入；**最终只输出整体物理清单 SHA，不输出逐股票代码、DAT 文件名、单文件 SHA 或任何原始字节**。两遍总读取字节预算 **512 MiB**。
4. 完成后再次完整运行 P3.25 的双 SHA 元数据审计并确保汇总一致，对原 `financial-cache-progress.json` 再次验证固定 SHA 和实际文件身份。按 `SOURCE_HISTORY_CONFLICT`、`CACHE_DECODE_ERROR` 汇总双 SHA 物理核验文件数和两遍分别读取的字节数，并严格与此前 P3.25 每组文件数/大小守恒。两个文件遍历之间如存在恶意恢复原内容或等大小同时间的极短时间变动，**没有跨文件原子快照保证**，不得宣称持有财务源客户端事务级写锁。

本阶段**确实读取原生 DAT 物理字节用于计算 SHA**，因此必须将 `physical_DAT_bytes_read_for_hashing_only=true` 写清楚；但仍 `physical_DAT_bytes_saved_or_copied=false`、`raw_DAT_format_decoded=false`、`raw_DAT_financial_rows_parsed=false`、`physical_DAT_manifest_proves_provider_origin=false`、`DAT_business_table_mapping_certified=false`、`nine_financial_tables_coverage_certified=false`、`fresh_finance_raw_rows_authenticated=false`、`fresh_and_old_finance_rows_compared=false`、`financial_pending_resolved=false`、`financial_repair_authorized=false`、`original_run_receipt_authenticated=false`、`original_quarantines_cleared=false`、`market_files_written=false`、`qmt_cache_queried_or_modified=false`、`qmt_download_calls=0`。原生 DAT 物理 SHA 是当次本机原始文件字节校验，不是 QMT 财务提供商身份、九表可读数据或财报历史真实性证据。

## 合成测试与实机门槛

本阶段目前包含 **23 项**纯临时自造小文件测试，分别覆盖真正物理两次 SHA、分两种 pending 原因、相同文件大小/修改时间却不同内容物理 SHA、零文件、空文件、无关股票拒读、其它格式拒读、双固定 SHA 前置失败、单文件/总预算/文件数限制、链接拒绝、双次读取间篡改、元数据 SHA 漂移、后置清单变化、错误摘要隐私、禁止 QMT SDK/写盘、Windows DirEntry 零 dev/ino、原生句柄双遍一致性和纯仿真范围。前阶段 P3.25 实机 **33 模块 757/757 PASS**，新目标 **34 模块 780 项**，另旧市场审计器 15 项；**P3.26 23 项和真实 616 DAT 物理字节尚未实机验收，不得预先声称已认证其 SHA**。

即使 616 份 DAT 双重物理 SHA 通过，也不能直接构建本次 76 项 `SOURCE_HISTORY_CONFLICT` 的新旧业务财务 `saved-current` 比对：DAT 是未经解析的 QMT 本地二进制缓存，仍需独立认证提供商渠道、对应报告期以及同一股票完整九表来源的真实原始行；1 个 `CACHE_DECODE_ERROR` 可能继续无法解码。原 76+1 财务待审、原九条市场隔离和原 2026-11-25 定时回执 SHA `72a7104bd831e969958507399263ff74fb4092d6f7bf51d4ac3c42e000a1d837` 缺失状态不变，所有 PR Draft，不下载 QMT、不写行情、不合并 main。

## P3.26 Windows 失败回执与针对性修复（2026-11-28）

用户针对原固定 `93bc1d3` 运行旧市场审计 **15/15 PASS**，P3.26 新增 18 项中 **11/18 PASS、5 ERROR、2 FAIL**，主要是 Windows `os.fstat` 与文件路径元数据 `_id` 全字段比较误报 `FINANCE_DAT_FILE_IDENTITY_CHANGED_BEFORE_READ`，另一个测试中 `PhysicalError` 未加模块前缀触发 `NameError`。这是**代码回归未通过**，并非源 DAT 物理字节真的改变的证据，也不能因此认定 Windows 来源已认证。

修复在本 Draft 分支内保留原双 SHA、文件范围、预算与后置审计；Windows 增加内核双句柄身份比对，Unix 保留原强校验；补 2 项合成回归（模拟 CRT inode/设备号不匹配仍需真实句柄相同，以及伪造不同句柄必拒绝）。现为 **20 项新增合成测试、累计 34 模块 777 项目标**。**本仓库提交仅能静态审核，修复版本尚未通过用户实际 Windows 20/20、777/777 或 616 个 DAT 物理双 SHA；请以固定修复 HEAD 的后续 Windows 回执为准**。无 QMT 下载、未修改本机源数据、无放行、无 main 合并。


## P3.26 Windows 第二轮真实回执与零 inode 修复（2026-11-28）

用户在真实项目 `.venv\Scripts\python.exe`（PyArrow 26.0.0）运行固定旧 HEAD `3e15a64`：**20 项确实运行，13 PASS / 5 ERROR / 2 FAIL**。其中 4 个实物双 SHA 正常样例和两个后续预期失败用例，都在 `_assert_open_identity` 的路径身份比较阻断；第 19 项伪 Windows CRT `os.fstat` 模拟错误地全程作用于 `LEDGER._bytes`，造成独立账本校验 `PROGRESS_LEDGER_CHANGED_DURING_READ`，不是实际账本已变化的证据。新回执是**回归失败，尚未进入 616 文件物理读取**。

Python 官方 `os.DirEntry.stat` Windows 行为：`st_dev`、`st_ino` 恒为零；`os.stat(path)` 能报告真实数值。因此 P3.24/P3.25 已验的 616 文件元数据 SHA 中使用的是 **DirEntry 采样的零设备/文件标识**；P3.26 原先用 `DAT._id(os.stat(path)) == DAT._id(entry.stat())` 属于不同来源字段强行对比，在 Windows 正常文件上也会失败。不能为了绕过差异改写两个此前验收 SHA 或移除来源固定。

修复策略：

1. 继续原样验证独立财务账本 SHA、P3.24 的 **DirEntry 原始 metadata digest**、P3.25 文件数量/大小/时间统计。Windows 仅在固定历史采样的 dev/ino 均为零时，路径 os.stat 与固定 DirEntry 原始元组对比 size、mtime_ns、mode；否则维持完整对比。路径本身仍须是非 symlink、非 reparse 的规则文件。
2. 对每次原生只读 DAT 文件句柄与另开同路径的只读验证句柄，要求 Windows `GetFileInformationByHandle` 的卷序号和文件索引一致，且读前读后再次验证；新增 **第一遍与第二遍原生文件标识完全一致** 的跨遍核验，防止同大小同内容且可复原 mtime 的文件替换逃过 SHA。Linux/Unix 的路径 stat/fstat 严格元组比对保留不变。上述校验不能消除跨所有文件缺少原子事务快照的限制，也不声称之前零 dev/ino 的元数据清单本身能证明原物理文件未被调换。
3. 第 19 项 CRT 仿真只在 DAT 的双遍物理读取范围内执行，不再影响独立账本校验；新增第 21–23 项合成用例覆盖 Windows 零标识 metadata 对齐、两遍不同原生文件身份拒绝、大小漂移仍拒绝。合成目标从 20 改为 **23 项**、组合回归从 777 改为 **780 项（34 模块）**。

**修复提交尚需真实 Windows 实机验收**，不把 Linux/模拟静态检查计为 23/23；原 77 财务 pending、九条市场隔离和原 2026-11-25 回执缺失均不因本代码修复而消除。无市场文件写入、无 QMT 调用、无 main 合并。
