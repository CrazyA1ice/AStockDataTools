# P3.25：固定财务待审 DAT 元数据清单的逐股票文件名数分布与 mtime 验证

## 来源、真实实机前提与要解决的问题

P3.24 的用户 Windows 实机验收固定提交 `c75d4b5d13c91b502e5cf99685657be496ec7680`：**32 模块 739/739 PASS**，本地 `D:\software\JHQMT\datadir\Finance` 的 `SZ/SH/BJ/86400` 三个直接目录均存在，共看到 44,982 个目录项（SZ=23,411，SH=18,742，BJ=2,829）。已固定 77 个财务待审代码全都找到至少 1 份非零的原 QMT Finance `_7xxx.DAT` 文件名，总数 **616**、合计 70,748,048 B；历史来源冲突 76 只／608 文件名／70,457,520 B，单独的缓存解码错误 1 只／8 文件名／290,528 B。实际 P3.24 **元数据**（非内容）清单 SHA `b5aa0aa3f0879eabbb65499d962fda3087a090f963399f42b72b13799c8dc711`。

**问题**：616 / 77 = 8、608 / 76 = 8，仅仅是平均数。不能因平均数就声称每个待审股票均有 8 个 DAT，更不能把这 8 个原生缓存文件名直接对应 8 或 9 张 QMT 财务业务表、报告日期或已解析的原始数据。历史来源数据内容、来源身份和真实可比的 fresh 九表仍然缺失；P3.22 早前证实的 91 旧 Parquet 文件、48,754 行和 46,485 条含重复旧历史并集只是**保存旧源**的真证据。

## 新工具、固定双 SHA、无 .DAT 内容读取

`market_finance_pending_dat_profile_readonly.py --module-root D:\ChatGPT\AStockDataTools\ParquetLiveSync --stock-root D:\stock --finance-dir D:\software\JHQMT\datadir\Finance --expected-ledger-sha256 2c1ef16dd2e9ef275e08175211d94968be15b55e78fc9e73555b0f3303a9c89a --expected-dat-metadata-sha256 b5aa0aa3f0879eabbb65499d962fda3087a090f963399f42b72b13799c8dc711`

- **开始和结束都完整重跑已验收的 P3.24 `DAT.inspect`**，严格确保保存 pending 账本的物理 SHA 不变、所有 DAT 作用域文件名／文件大小／mtime／st_dev／st_ino 元数据及目录结构核验仍与上述元数据清单 SHA 一致。中间仅对同一份固定 ledger `pending` 内 77 个股票 code/原因进行额外一次 bounded 直接目录项读取，重新计算**逐文件同样顺序和字段的原元数据 SHA**，不读取文件字节。扫描前后 P3.24 双遍校验均通过仍不构成跨文件原子快照或文件锁。
- 三个市场目录及源根来自 P3.24 的既有只读范围；要求所有根、市场目录、86400 目录和已匹配 pending DAT 都是非 symlink、非 junction/reparse 的真实目录／普通文件，不遍历其他路径、不递归。保留 P3.24 限额：单市场 100,000 目录项、累计 250,000 目录项、待审匹配文件名最多 100,000；作用域来源只能是 SHA 锁定的保存 pending。
- 输出按待审原因分组的**每只股票实际 DAT 文件名数直方图**（例如 `file_count_histogram_7`／`8`／`9`），统计正字节文件数直方图、确实有 8 个文件名的股票数、确实有 8 个**非零**文件名的股票数、不是 8 个的股票数以及匹配文件名总大小；用各股票实际看到的 `_7xxx` 文件名后缀集合计算**后缀集合的种类数与最大同组股票数**，不输出任何股票代码／单只股票记录／原始 DAT 文件名、文件路径或小集合原文，也不假定后缀=具体财务表。
- 额外记录仅基于**文件系统修改时间元数据**的 UTC 年月文件名分布和每只股票所有匹配 DAT 文件的最早至最晚 mtime 跨度分桶（相同时间／1 天内／7 天内／超过 7 天）。mtime 是本地文件属性，可能随复制、同步、版本升级、客户端写入而变化，**绝不**等于财报披露日期、数据来源观测日期或供应商真实历史变更时点；即使所有 8 文件 mtime 完全相同，也不能声明九表数据同步完整。
- 严格对 P3.24 原有 `by_reason` 实机汇总的保存待审股票数、文件名数、非零文件名数、观测字节总数逐类守恒；重新计算的**原元数据清单 SHA** 必须完全等于 P3.24 真实哈希。发现新文件、丢文件、大小/mtime 变化、原元数据 SHA 不符、非法路径或任一错误都**拒绝**本轮结果，不顺手修复。
- 恒定 `dat_content_bytes_read=false`、`dat_physical_file_sha256_checked=false`、`new_finance_raw_rows_read=false`、`financial_nine_table_completeness_certified=false`、`fresh_provider_provenance_certified=false`、`fresh_vs_old_finance_compared=false`、`cross_file_atomic_snapshot_certified=false`、`financial_pending_resolved=false`、`financial_repair_authorized=false`、`original_run_receipt_authenticated=false`、`original_quarantines_cleared=false`、`market_files_written=false`、`qmt_cache_queried_or_modified=false`、`qmt_download_calls=0`。

## 实验验收（尚待真实 Windows）

新增 **18 项**仅使用测试临时假 DAT 文件名/mtime 的模拟测试：单股 8 文件、**两股 7+9 却平均 8**、同样各 8 但后缀集合不同／相同、零字节、无文件、两类待审区分、UTC 月份及 mtime 三种跨度、两层固定 SHA、扫描中及 postflight 文件元数据漂移、DAT 符号链接、CLI 错误隐私、无 QMT/写盘调用且不遮蔽 `unittest.TestCase.run`。前阶段真实已通过 32 模块 **739/739**，P3.25 新目标为 **33 模块 757 项**另单独旧市场审计器 15 项；**P3.25 新 18、合计 757 项和真实 616 个现存本地 DAT 文件名分布尚未在 Windows 执行**，不能提前把平均 8 记为“每股票恰好 8”。

完整下一阶段真财务历史对账仍缺经独立验证的 fresh QMT 九表原始字节。源 `financial-cache-progress.json` SHA `2c1ef16dd2e9ef275e08175211d94968be15b55e78fc9e73555b0f3303a9c89a` 仍 76 个 `SOURCE_HISTORY_CONFLICT` 和 1 个 `CACHE_DECODE_ERROR`，不因本阶段检查成功而放行。独立原九条市场隔离及 2026-11-25 原定时运行收据 SHA `72a7104bd831e969958507399263ff74fb4092d6f7bf51d4ac3c42e000a1d837` 的缺失原字节仍是阻断。所有相关 PR 保持 Draft，不调用 QMT、修改财务进度/股票 Parquet/H5、放宽历史多重数据保全或合并 main。
