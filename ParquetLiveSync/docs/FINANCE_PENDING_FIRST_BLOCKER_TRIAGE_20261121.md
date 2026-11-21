# QMT 财务 pending 账本：仅首个阻断表的只读分类（2026-11-21）

## 已知本地证据
用户以SHA256前后双检读取正式账本：截至2026-11-21 `daily_cursor=001266.SZ`，pending 85条，其中历史来源冲突84条，缓存解码异常1条。此前手工 PowerShell 按 `detail` 包含表名字串统计：Capital 42、Top10Holder 33、Top10FlowHolder 5、HolderNum 4，合计84；重试次数1×42、3×39、4×3、6×1。该统计只是字符串匹配，并未独立逐项验证股票身份、完整语法或排除多标签。数据真实性尚未认证。

## 机制与边界
现有 `qmt_extra_financial_cache_import._plan_symbol` 按9表固定次序检查，发现旧版不可被当前原始记录覆盖时，抛出 `SOURCE_HISTORY_CONFLICT <symbol> table=<first-table> removed_or_revised=<count>`，特殊 Capital 校验失败时附 `scoped_m_quarter_proof=<classification>`；后续表可能还未检查。因此 **pending.detail 只能说明首个阻断表**，不能宣称另外8表没有冲突。

## 功能
- 新增 `market_center_finance_pending_triage.py`，必须提供 `--state-module` 和 `--explicit-readonly`。
- 只读取规范 `ParquetLiveSync/work/qmt_extra/financial-cache-progress.json`（2MiB限制、路径无symlink、前后SHA一致），不访问QMT、Parquet、H5、财务DAT、市场锁或重试入口，不产生持久化文件。
- 对每个pending严格检查股票代码、reason、日期和 attempts；按 **原始错误完整语法+股票身份** 而非 `contains()` 提取首个表名、冲突形式，分组输出次数交叉表和日期交叉表。无法识别的冲突为 UNCLASSIFIED，不伪报完成。只显示聚合数字，不输出原始detail或股票财务值。
- 任何表名匹配仅为日志诊断，不代表来源真实、快照内容哈希已认证或允许修复；m_quarter 专用证明被拒绝不等于对语义差异予以豁免。
- 所有输出字段保持 `can_execute=false`、`can_download=false`、`market_file_writes=false`、`qmt_calls=0`。

## 测试与后续
新增8项纯合成测试：首表独占/重试交叉表、Top10FlowHolder 不混成 Top10Holder、股票错误和未知明细隔离、Capital m_quarter 专用失败、非法待审项fail-closed、显式只读开关、空账本不认证、并发变化拒绝。

基于已实机通过的 finance-provider branch 315项，本分支预计323项 `test_market_center_v2*.py` + 新测试文件不符合这一匹配，因此执行时须改成 `test_market_center*.py` 并明确记录实际执行总数。**尚未经Windows验收，保持Draft**。

下一步：先获本机聚合结果，按首个阻断表抽取有限样本做历史快照只读对照和字段/报告日差异分析。不得自动覆盖旧版本，不推断没有冲突的8表，也不能从游标推进推断业务完整性。
