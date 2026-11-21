# Daily Autopilot S5：九表安全入库的只读事务准备与隔离演练

## 核心目标
把 S4 九表历史预检与最终写入事务之间的安全边界明确化。S4 财务缓存刷新会改变 QMT 供应商本地缓存，但正式财务 Parquet、active pin、pending、进度游标不应因为“没有发现第一处冲突”而直接修改。S5 只构建事务意图（intent），并对新版本的不可变目标做验证；**不执行正式入库或授权自动覆盖**。

## 已实现
新建 `market_scoped_finance_transaction_intent.py`：首先复核 S4 私有 JSON 与财务进度账本的精确 SHA256，重新读取临时财务回执并校验严格九表预检；对于没有历史冲突、没有旧待审记录的股票，复用正式导入器的 `_plan_symbol` 计算所需新增表，以原有 Arrow 模式生成候选快照的内容地址文件名、原同日快照 SHA、原 active pin SHA 和行数。整个过程只生成内存摘要，不创建 Parquet、pin 或事务日志。

不同结果：
- 有新增版本且无待审：生成 `candidate_stocks` 和精确目标文件名，`batch_fully_eligible_for_future_manual_review` 是未来人工设计资格，不等于允许提交。
- 无变化：计入 `no_change_stocks`，不是故障，也不生成新文件。
- 历史冲突、缓存缺失或已在 pending：计入 `blocked_stocks`，该批次无法整体自动提交。
- 目标文件已存在、同日旧快照没有明确 active pin、已有事务 journal、历史文件损坏或预检结果/股票范围变化：直接拒绝生成事务意图，需人工查明原因。

提交意图通过 `intent_sha256` 固定股票、观察日期、原私有 JSON/ledger SHA、候选内容地址、原版 SHA 与原 pin SHA；**这是内容指纹，不是电子签名、更不是用户审批**。预览结束后原有 S3 临时 JSON 仍会正常清理，所以这份指纹不能跨天被当作提交令牌：真正提交时必须在同一生产互斥锁中重新生成、验证、备份并执行。

## 故障恢复
已经添加纯函数 `recovery_decision()`，覆盖 `PREPARED / SNAPSHOT_WRITTEN / PINS_UPDATED / LEDGER_RELEASED / COMPLETE / QUARANTINED` 六类状态。对于任何未完成状态默认隔离并要求人工审查；**不自动重放、删除历史版本、回滚 active pin 或清理财务 pending**。真正可恢复事务仍需要在独立沙盒完成顺序注入失败、备份核验、崩溃恢复和无二次提交后，才能设计真实 `--apply`。

## 回归与安全修复
本阶段同时修复 S4 `run-scoped-qmt-finance-cache.ps1` 中被截断的正则以及意外重复的后半段脚本。上一版本尚未部署，但该语法问题会阻碍任何实机 S4 运行。新增 Windows PowerShell AST 解析测试验证完整语法（非 Windows 自动跳过），防止再次只用文本包含关系测试而漏掉语法错误。

新增 `test_market_center_scoped_finance_transaction_intent.py` 共 **22项合成/沙盒测试**：候选内容指纹、同一输入幂等、旧候选不可覆盖、已 pin 同日历史保留、未 pin 同日冲突、旧待审阻断、空来源、无变化、混合批次、日志阶段恢复策略、SHA校验、GUI未授权以及 Windows PowerShell 语法检查。使用临时目录和原有 `E._snapshot_write` 构造合成历史，没有测试生产 QMT 下载，也不编辑正式数据库。

以此前 S4 的预计 420 项 `test_market_center*.py` 为基线，本阶段新增22项，预计 **442项**（是否实际通过以用户 Windows 实测为准）。这次提交无正式20:05调度、财务数据写入程序、估值表或生产日志变更；不使用 GitHub Actions，不合并 main，不部署。下一阶段才能讨论真正的分阶段 journal、原始账本备份、原始 pin 备份和正式单股票隔离事务、以及独立于QMT的多源来源核验。