# P3.20：76 项财务历史冲突对应的原有不可变快照及 active 指针只读取证

## 已证实前提

P3.19 用户 Windows 固定提交 `60f99dad06580036f996ca6d6a036f93c1c4ec8b` 的原审计器 15/15、新专项 17/17、28 模块 663/663 项均 PASS。真实 `work/qmt_extra/financial-cache-progress.json` 与 P3.18 相同物理 SHA `2c1ef16dd2e9ef275e08175211d94968be15b55e78fc9e73555b0f3303a9c89a`：保存待审 77（`SOURCE_HISTORY_CONFLICT=76`、`CACHE_DECODE_ERROR=1`）；62 条严格历史 raw 观测缺失或修订（`Top10Holder=34`、`Top10FlowHolder=25`、`HolderNum=3`），14 条 `Capital` 的 `REPORT_KEYS_ADDED_OR_REMOVED`。总待审的 `asof` 是 2026-11-23～25；76 个历史冲突一次尝试，单独解码失败尝试数介于 4～9。这些是**真实已保存 pending 分类事实**，不是 QMT 实时源验证，也不意味着所有 76 项都可以按同一规则修复。

原定时 2026-11-25 固定 SHA `72a7104bd831e969958507399263ff74fb4092d6f7bf51d4ac3c42e000a1d837` 仍无物理原件，P3.14/16/17 的阶段、验证输入/输出、Parquet 字节链是独立旁证，不替代原回执；原九条行情隔离和 77 项财务 pending 各自维持。

## 原代码为什么需要区分多版本快照

原 `qmt_extra_financial_cache_import.py::_prior_rows` 对 `extra/financial/<table>/<stock>/snapshots` 中每个日期的不可变历史版本的**并集**作保守对比，而不能直接取文件名最大的 Parquet。原 `qmt_extra_data._financial_snapshot_file` 在某日期有多个版本时，必须有 `active/<YYYY-MM-DD>.json` 指明合法选中哪一版本；同一日期有多个 Parquet 文件但没有有效 active 指针必须保留为待审。文件名末尾 16 位指纹来自规范化行内容，**不是 Parquet 物理文件 SHA 的前 16 位**。

## 新独立仅旧数据检验器

`market_finance_prior_snapshot_census_readonly.py --module-root D:\ChatGPT\AStockDataTools\ParquetLiveSync --stock-root D:\stock --expected-ledger-sha256 2c1ef16dd2e9ef275e08175211d94968be15b55e78fc9e73555b0f3303a9c89a`

- 仅通过指定固定 SHA 的现存 `work/qmt_extra/financial-cache-progress.json`，从每条已分类 `SOURCE_HISTORY_CONFLICT` 的**精确内部 detail** 取得其旧 snapshot 的 `table` 与 `stock`；必须完全匹配 P3.19 的 strict 或 Capital scoped 字段，未知详情直接拒绝扫描。正常真实数据应得到 76 个独立路径作用域；单次最多 128 个作用域，单作用域最多 256 个直接文件、全部最多 4096 个，单文件最多 24 MiB，物理 Parquet SHA 读取总上限 512 MiB，超限拒绝而不悄悄跳过。
- 限定只读物理路径 `<stock root>/AllCycleAStockData/qmt_extra/financial/<table>/<stock>/snapshots`，只枚举直接文件，不递归，不扫描其他股票。若旧路径本身不存在，报告缺失作用域而不创建。文件名必须符合 `YYYY-MM-DD-16lowerhex.parquet`，所有真实文件必须是非符号链接正规文件；文件内容 SHA256 以持有的同一文件句柄、`fstat` 和独立路径 `os.stat` 前后身份核验，按本次真实哈希形成只展示总 SHA 的隐私摘要。
- 按历史日期检查**所见旧快照的** `active/<YYYY-MM-DD>.json`。若 active 文件存在，严格核对格式、table、stock、asof、合法且存在的 filename 和真实目标 Parquet SHA；同一天仅一版且无 active 标记 `LEGACY_UNPINNED_UNIQUE`，同一天多版但无 active 标记 `MULTIPLE_VERSIONS_NO_PIN_REVIEW`，绝不随意选中。pin JSON 必须从一次受限读取、经过 SHA 检查的**同一原始字节缓冲**解析。
- 输出只有按财务表汇总的 `source_conflict_scopes`、快照目录存在/缺失/空目录数、真实文件 SHA 数、文件字节数、独立日期数、active 状态计数及不可逆 manifest SHA，不输出股票明细、路径、异常源码正文。**不读取/验证任何新 QMT 财务源，不解释 Parquet 原始 raw payload 的经济字段**。即使快照与 active 指针对得上，也绝不解除财务 76 个历史冲突或九条原行情隔离。
- 再次核对已固定的 pending 账本 SHA 与物理文件身份，拒绝扫描期间账本变化。无生产源锁，结果 `parquet_row_or_history_union_verified=false`、`new_finance_source_consulted=false`、`original_qmt_source_authenticated=false`、`all_source_history_conflicts_resolved=false`、`financial_repair_authorized=false`、`original_run_receipt_authenticated=false`、`original_quarantines_cleared=false`、`market_files_written=false`、`qmt_download_calls=0`。任何历史文件缺失或 active 指针冲突都不是自动修复授权。

新增 **19 项**仅用临时目录模拟假的快照字节和指针的测试：旧快照缺失、单版旧文件、多版无指针、多版有合法指针、指针 SHA/股票/文件名错误、意外文件、符号链接、原账本固定 SHA 错误、未知异常类型、Capital 报告键变化、单独解码失败不扫、文件数/大小预算、账本扫描中被修改、CLI 不泄漏路径、禁止 QMT/写入等。**真实 Parquet payload、原始历史来源并集、供应商来源均未在合成测试中认证。**

前阶段选定 28 模块 663 项已通过 Windows；P3.20 新目标是 **29 模块 682 项**，另原旧审计器 15 项额外复测，**尚未执行本阶段 Windows 验收与真实 76 个历史快照范围扫描**。如遇预算、原始目录不一致或 active 无法认证，应停止并记录具体安全阻断，不自动扩大规模或改数据。全部 PR 保持 Draft，不调用 QMT、不恢复/合成旧回执、不写市场/H5/Parquet、不自动放行任何隔离。
