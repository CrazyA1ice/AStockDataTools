# P70: P69 事务完成证明的只读消费核验（不自动启用）

## 动机

2026-11-18 P69 实盘只读前置核验：`002237.SZ` 的 102 个 Capital 报告日里仅 1 个 `m_quarter` 历史旧值与现缓存不符，其他八张财务表匹配；账本 SHA `550421c578b83c31465c9eafbe0ba95e327580a0c13a133452b2cb99adbb0736`，九表指纹 `37fb39622233ad58415d552eee5a161adadeba5f391a2412958c5de89ca761a9`。此证据来自**只读采样**；没有执行 P69 apply。

P69 事务可以验证单股、原子写入新 Capital 快照、保存精确规则并清除该股票的 pending。**然而当前无人值守 `qmt_extra_financial_cache_import.run()` 仍使用默认严格比较且在 5002/5656 历史冲突时直接熔断。** 因此不应将 P69 一次成功等同于持续日更修复。

## 本阶段新增

`qmt_capital_attested_policy_consumer.py` 提供：

1. `read_completed_policy(extra,workspace,code)`，仅在 `002237.SZ` 具有完备 P69 `COMPLETE` 事务、原始 ledger 的字节 SHA/备份、原 pending 证据、当前 pending 已释放、完整政策文件 SHA、基线 Parquet 和候选 Parquet 的真实物理 SHA、当日 active pin 一致时返回狭义 `m_quarter` 认可对象。仅有 `status=ACTIVE` 的政策 JSON，或孤立的伪 `COMPLETE` 日志、损坏的旧文件、恢复 pending 的状态，都不能自动获得授权。
2. `verify_next_day_without_writes(...)` 将第 1 步的可靠政策**仅作为显式参数**交给已经通过测试的 P67 比较器，对相同缓存的次日扫描返回 `UNCHANGED`，对新增报表日期、真实股本变化、非 Capital 财务字段变化仍 fail closed。
3. 合成临时目录中的事务、备份、策略、历史报表和次日数据测试。无 QMT 实机请求、无真实 Parquet 更新，也不接触 Windows 定时任务。

## 明确保持默认关闭

- **不改**原每日财务导入器、CLI、Scheduled Task、`--apply` 默认行为及大规模历史冲突熔断。
- 代码目前只证明一种已完成、窄范围、可核验的持久策略读取方式；只有在单股实际恢复和对照实测都成功、且独立完成对未来新增报告日期的 append-only 语义审查后，才能设计生产可控授权接线。
- 完成 P70 只读测试**不会改变 5003 条 pending**，也不会解除 5002 条历史熔断。
- 遇到实际事务中断应先通过 P69 独立补偿核验，不得删除 journal、旧 Parquet 或伪造 ACTIVE 策略。
