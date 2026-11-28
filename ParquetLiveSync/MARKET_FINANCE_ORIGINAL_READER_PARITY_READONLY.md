# P3.22：原生产财务历史读取器与 P3.21 已认证旧历史并集的逐源只读一致性

## 已经真实确认的审计基准

用户真实 Windows 固定 `c83e3d7045df5ac57686d996478cda9e48c2a7ae` 的 P3.21 修正版本 **30 模块 703/703 PASS**。在此前 2026-11-25 的原 `verification` 显示历史数据保全阻断及 76 项 `SOURCE_HISTORY_CONFLICT`、1 项 `CACHE_DECODE_ERROR` 的情况下，P3.21 只读取旧现存财务 Parquet，获得原 **76 个来源冲突表-股票作用域**下共 **91 份** SHA/active 指针锁定的旧不可变快照、**48,754 行**、`payload_json` **10,538,008 B**。按旧来源跨日期各行最大重复次数并集：**46,478 条不同原始记录，46,485 条含重复计数**；`Top10Holder` 多出 7 次应保留的历史重复观测，不能简单变成一个去重集合。

P3.21 在实机形成的固定三重输入：
- `financial-cache-progress.json` 已读文件 SHA `2c1ef16dd2e9ef275e08175211d94968be15b55e78fc9e73555b0f3303a9c89a`；
- P3.20 已有 91 个物理旧快照 + `active` 选中版本的物理文件清单 SHA `12be02042231302b6e1334797eb5751c52971e6497f1b42d5be03ae97095bcb8`；
- P3.21 历史选中版本 raw payload/Counter 并集不可逆摘要 `6d0fad5f54cb97730f2a9da8231c376491ba8a9c57d4e140133f0910f16b1cd5`。

按财务表的基准：`Capital` 14 个冲突作用域/28 个选中日期/3,289 原始行/1,686 不同和含重复并集；`HolderNum` 3/3/440/440；`Top10FlowHolder` 25/25/17,676/17,676；`Top10Holder` 34/35/27,349/26,676 不同/26,683 含重复并集。

**上述三份 SHA 和测试不是任何新 QMT 财务数据的身份验证**。原 2026-11-25 定时回执指定 SHA `72a7104bd831e969958507399263ff74fb4092d6f7bf51d4ac3c42e000a1d837` 的原始物理字节仍无从认证；原九条行情隔离及财务 76+1 待审全部维持。

## 本阶段新增的独立生产旧读取器核对

原 `qmt_extra_financial_cache_import._prior_rows(extra,code,table)` 是真实**生产导入前历史原行保全检查**读取器。它按已选中的每个旧观测日期读 `qmt_extra_data._financial_snapshot_rows`，再调用原 `_rows` 剥离来源 `_index` 后计算 `Counter` 的**每个键最大重复次数**并集。该函数只读取明确的本地 `qmt_extra/financial/<table>/<stock>/snapshots`，其自身不调用 QMT SDK、网络下载或文件写入；不能调用它所在模块的 `run/cli` 其他生产路径。

`market_finance_original_reader_parity_readonly.py` 对同一固定旧状态与内容做**再一次独立重读**，只能使用上述三份明确验过的 SHA：
`--module-root D:\ChatGPT\AStockDataTools\ParquetLiveSync --stock-root D:\stock --expected-ledger-sha256 2c1ef16dd2e9ef275e08175211d94968be15b55e78fc9e73555b0f3303a9c89a --expected-snapshot-manifest-sha256 12be02042231302b6e1334797eb5751c52971e6497f1b42d5be03ae97095bcb8 --expected-old-union-sha256 6d0fad5f54cb97730f2a9da8231c376491ba8a9c57d4e140133f0910f16b1cd5`

执行步骤：先调用 P3.21 `RAW.inspect`（其中严格对账本 SHA 和所有历史物理文件/active SHA、Arrow schema、旧 JSON 内容、行编号、历史并集，以及解码/行/文件预算做完整验证）；要求其历史并集 SHA 等于此前 Windows 的真实值。然后在原 76 个严格固定源冲突作用域上逐一调用原生产 `IMPORT._prior_rows`，确保它读取的最后历史日期与实际旧文件日期一致，计算原函数返回的完整 `Counter` 逐源的私有摘要，并按 `table + stock + scope union SHA` 与 P3.21 同一排序规则拼出历史总摘要。必须与第三个 SHA **逐字节一致**；同时分表验证 P3.21 已检验的不同记录和重复次数，并限制最多 128 个作用域、每源最多 20 万条不同 Counter 键、合计最多 100 万旧并集多重记录。若出错、来源出现新的物理文件、非法旧数据/重复键/缺少 active 或任意内容变化，停止并安全地只报告异常类型。读后再次执行 P3.21 全部旧源物理/内容复核、确认文件 SHA、历史并集总摘要和文件范围仍与事前一致。没有跨文件原子锁，明确 `cross_file_atomic_snapshot_certified=false`。

该报告只输出各财务表的源作用域数、原读取器重算的 `old union distinct/multiset`、三 SHA 和永久限制标志。**即使通过也只能证明原生产旧数据读取算法与独立旧数据审计的语义一致，不能证明新鲜来源保存了这些旧历史记录或实际恢复任何来源冲突。**

## 保留安全边界与下一阶段

报告必须始终：`fresh_qmt_or_finance_source_queried=false`、`fresh_finance_raw_records_compared=false`、`original_finance_source_provider_authenticated=false`、`all_historical_finance_coverage_certified=false`、`financial_pending_resolved=false`、`financial_repair_authorized=false`、`original_run_receipt_authenticated=false`、`original_quarantines_cleared=false`、`market_files_written=false`、`qmt_cache_queried_or_modified=false`、`qmt_download_calls=0`。

新增独立合成 **18 项测试**，覆盖原生产读取器的单日/跨日最大多重计数、零作用域、三份 SHA 错误、原读取器返回内容或日期偏差、非法 Counter、计数预算、老目录缺失、多财务表作用域、唯一的解码异常仍在队列、原读取器异常隐私及结束后数据变化、防御 unittest.run 命名遮蔽和无 QMT/写路径。此前 P3.21 30 模块 703/703 已实机通过；增加 18 后选定目标为 **31 模块 721 项**，另旧审计器 15 项。**P3.22 尚未取得真实 Windows 18/18、721/721 和实际生产旧读取器一致性验证**。不要将此阶段 GitHub 代码静态复核说成实机通过。

禁止因旧读取器双重一致而解除 76+1 项财务待审或 9 条行情隔离。后续要回答“新 QMT 记录究竟删除/修订了哪些旧行”，**必须存在可独立鉴别的新的财务原始来源及逐字段对照**，不能用旧账本中的 `removed_or_revised` 字样替代真实新数据。原始历史回执的真实 SHA 认证也保持独立阻断。所有相关 PR 继续 Draft、不合入 main。
