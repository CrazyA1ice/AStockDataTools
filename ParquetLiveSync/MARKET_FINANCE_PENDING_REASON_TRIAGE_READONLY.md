# P3.19：仅凭已核验财务缓存账本分析待审原因和重试分布（只读）

## 真实 P3.18 证据与不可突破的边界

固定 `41b113565f4afeee10bbc6a84eb6ae82b3e772af` 的用户 Windows 实机：原审计器 15/15、新专项 16/16、27 个测试模块 **646/646 PASS**。本机两个确切的现存账本已通过真实 SHA 检查：`progress.json` 为 328 B、SHA `2cb04a81ef86b417d1cb0c6b7375eac2b2bb53ac034f3722444de44a4a428300`，其旧补充模块待审数 0；`financial-cache-progress.json` 为 13,556 B、SHA `2c1ef16dd2e9ef275e08175211d94968be15b55e78fc9e73555b0f3303a9c89a`，其中 **77 个**缓存待审、`SOURCE_HISTORY_CONFLICT=76`、`CACHE_DECODE_ERROR=1`。缓存日扫游标 `002639.SZ`，`daily_date=2026-11-25`，`daily_sweep_start=2026-11-19`，`daily_sweep_reached_end=false`、`daily_sweep_finished=2026-11-18`。账本所称日子不是本地正在运行的现况或全股票覆盖认证；2026-11-25 校验报告的 `4526` 未访问只是当次历史数，不能套用为今天的队列余量。

P3.14/P3.16/P3.17 分别对 11-25 原定时阶段日志、候选 Parquet、总日志、验证输入/报告形成独立物理字节证据，确认四阶段执行 PASS 而数据 PARTIAL，原因涉及原九条行情隔离、未完成的除权批次和财务扫描。**原定时保存的固定回执 SHA `72a7104bd831e969958507399263ff74fb4092d6f7bf51d4ac3c42e000a1d837` 原件仍未找到**，任何阶段旁证不得视为恢复完整证据链，九条隔离原样保留。

## 代码根因：为什么 76 个财务历史冲突不能批量放行

只读核对 `qmt_extra_financial_cache_import.py`：导入器比较的是各次已有不可变财务快照的**历史记录并集**与新的 9 张财务表原始行；若新源无法保留旧观测，触发 `SOURCE_HISTORY_CONFLICT table=<table> removed_or_revised=<n>` 并保留待审。只存在独立受限研究用的 Capital `m_quarter` 语义证明候选，只有经过逐字段和报告键验证才可考虑极窄范围后续申请；当前一般批处理、计划任务不默认启用豁免。候选证明返回 `REPORT_KEYS_ADDED_OR_REMOVED`、`BUSINESS_OR_DATE_FIELD_CHANGED` 等时仍是异常，不应把它们改成忽略差异。`CACHE_DECODE_ERROR` 是真实缓存/供给解码异常，不能伪装为“空表”。

即使实际 76 条待审细节中有 `Capital`，也不能仅凭进度 JSON 推断差异只是无意义元数据；源快照原始字节和逐记录经济字段目前并未重比。要准备后续安全只读诊断，先分类才不会盲目全量重新导入。

## P3.19 固定 SHA 账本内证据审计

独立入口：

`market_finance_pending_reason_triage_readonly.py --module-root D:\ChatGPT\AStockDataTools\ParquetLiveSync --stock-root D:\stock --expected-ledger-sha256 2c1ef16dd2e9ef275e08175211d94968be15b55e78fc9e73555b0f3303a9c89a`

- 只读取 `module/work/qmt_extra/financial-cache-progress.json` 一份已经 P3.18 验证的实存原件，必须提供 **与 P3.18 真正核验过的一致的预期 SHA256**。复用 P3.18 的严格数据根目录身份、单文件最大 8 MiB、`os.stat/os.fstat` 前后物理身份与 SHA 检验，再次完整读/哈希对照并检查目录状态；变更或缺失立即拒绝，不会隐式初始化状态。
- 以账本自身的 `pending` 为唯一分类输入，输出每个 `reason` 的数量、总尝试次数的区间（1、2～3、4～9、10+）、各原因下区间、最后待审日期的月份和最早/最晚日期及缺失数量，不输出任何待审股票代码/日期明细/原始异常字符串。
- 对 `SOURCE_HISTORY_CONFLICT` 的 `detail` 只接受**完全匹配且股票 ID 与该条 pending 键一致**的内部固定格式。严格历史观测损失用 `RAW_HISTORICAL_VARIANT_REMOVED_OR_REVISED` 计数并按财务表 `Capital/Balance/...` 计数；只有 Capital 官方定义的 scoped proof 枚举名称才原样记为 `SCOPED_CAPITAL_PROOF_...`。其它、截断、不可信、缺失细节一律 `UNCLASSIFIED_DETAIL`，**绝不默认为已通过**。所有汇总都进行守恒数量检查。
- 报告明确 `raw_history_data_compared=false`、`financial_source_provider_authenticated=false`、`full_history_coverage_certified=false`、`financial_repair_authorized=false`、`original_run_receipt_authenticated=false`、`original_quarantines_cleared=false`、`market_files_written=false` 和 `qmt_download_calls=0`。
- 不调用任何财务 QMT worker 或新数据读取，不修改或重试任何 pending，绝不自动激活 Capital 例外策略。分类只是发现复核下一步可行性，不是历史来源的认证。

新增 **17 项合成临时文件测试**，覆盖原因/表/Capital scoped 分类、陌生异常拒绝认定、重试次数区间、月份汇总、无效日期、固定 SHA、文件缺失和扫描中变化、CLI 路径隐私、无生产写入等。此前 27 模块 646 项实机通过；P3.19 新选定验收目标为 **28 模块 663 项**，额外旧原审计器 15 项分开运行。**P3.19 尚无 Windows 实机结果，亦未读取用户私有 77 条 pending 的具体详情**。必须固定提交做全回归，然后在本机运行如上带固定 SHA 的只读命令，输出实际分类再讨论后续研究价值。保持所有 PR Draft，不改行情、QMT、定时器、历史回执和九条隔离。
