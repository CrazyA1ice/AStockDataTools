# 通用行情质量问题清单（P1.5）：跨日期、证券与来源

> 状态：新增只读的待处理清单快照。不是持久事务数据库、自动恢复代理或生产质量放行程序。

## 设计定位

用户要求 AStockDataTools 是持续管理、清洗、对齐和修复多来源八周期行情的工具。2026-11-25 九只股票只是已知的真实回归样本，不得成为核心日期或固定证券名单。

新增 market_quality_backlog.py，消费现有 market_quality_engine.py 及 market_quality_receipt_adapter.py 的结构化检查。根据 (trading_day, symbol, period, source_id, rule_id) 计算稳定 SHA256 incident_id。同一股票日允许多个问题；同一股票日的不同数据源有独立 ID。重复检测按证据内容去重，来源修订保留全部不同快照，**没有新证据就不关闭旧异常**，也不凭内容哈希排序猜“最新版本”。

状态：
- OPEN_QUARANTINED：至少一份检测为 DETECTED，哪怕另一版本只说证据不足。
- NEEDS_EVIDENCE：所有版本均为 INSUFFICIENT_EVIDENCE。
- revision_review_required：同一稳定事件有不止一个证据版；不得自动认定已解决。

优先级：P0 为物理文件/回执完整性问题，P1 为原生产隔离、缺股票日、时间网格、量额配对及 OHLCVA 不一致，P2 为其他明确异常，P3 为证据不足。优先级只是只读复核顺序，不能代表自动恢复权限。

任何处理结果必须保持 automatic_repair_authorized=false、automatic_closure_authorized=false、qmt_cache_download_calls=0、market_files_written=false 和 market_quality_cleared=false。既有生产源回执隔离数必须等于质量 case 数；沿用可见的原回执 SHA 与已接收候选 Parquet SHA，但**它们都不等于被隔离的 QMT 241 根原始行情 SHA**。

## CLI 调用

用已验收工作树中的脚本，替换示例中的真实路径。可针对任意不超过 180 个自然日的、实际存在的日回执日期范围：

~~~powershell
& "D:\ChatGPT\AStockDataTools\.venv\Scripts\python.exe" -B "D:\ChatGPT\AStockDataTools\work\REPLACE_PINNED_WORKTREE\ParquetLiveSync\market_quality_backlog.py" --module-root "D:\ChatGPT\AStockDataTools\ParquetLiveSync" --start-day 2026-11-25 --end-day 2026-11-25 --summary-only
~~~

这里的日期只是验收样例，不是限制。还支持单独选择 --quality-json PATH --summary-only 读取经授权提供的规范化质量 JSON 批次；不能同时使用两套输入。

--summary-only 只输出统计和整个清单的规范化 SHA，不展开每个事件；省略它时输出含证据版本的完整清单。程序仅输出到标准输出，**不会存档异常、写任何项目行情文件、使用 QMT、修改定时任务或发企微**。

## 上下游实证与界限

- 设计 PR #263 已要求跨日异常状态机、三种独立权限和不降质量阈值。
- 通用规则/回执 PR #264 的用户 Windows 验收已确认 121/121 测试 PASS。真实 2026-11-25 回执仅有 1 份，报告 5206 接收、9 隔离；已接收候选 Parquet 实际 SHA de113cbd202ea68590780e5509755d843ebc6363a2857399094c09982e6f7eff 与回执相符；回执本体字节 SHA eeed821ed64202d8c8b243443f2c9622785e3a0c715c333414e48c70353768a4。
- 这两个哈希**不能独立认证**九只隔离股票 QMT 原始字节及官方 DAY 原始字节。通用清单也不能把 UNKNOWN/PENDING 的核验状态提升为 PASS。
- 本轮新增 24 项多年份、多证券、多来源、重复观察、修订冲突、非法状态/授权和无副作用 CLI 合成单测已在隔离 Python 合约测试环境 **24/24 PASS**，源码与测试文件 Git Blob 均匹配。此结果不是 Windows 上新脚本的实机通过记录，也不意味着用户已授权创建持久私有待办数据库。

## 后续长期开发

P2：接入独立官方日线股票集合、QMT 原生分钟 SHA/时间格点、原购买校准与多数据商来源快照。P3：经批准的新版本化私有待办库，幂等事务、证据变更登记和可恢复备份，不能提前写入原 Parquet/H5。P4：不限股票日期的恢复计划器和可审计候选验证，QMT 自有缓存写入和生产行情写入权限仍要分开。P5：GUI、跨月巡检与定时任务质量状态统一，不按一次任务退出成功或一次候选清单空白而解除历史隔离。

**本阶段绝不更改 main、5206+9 原始 2026-11-25 回执、正式行情文件、Windows 调度或企微。**
