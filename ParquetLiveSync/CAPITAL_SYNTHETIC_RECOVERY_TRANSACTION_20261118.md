# P66 · Capital.m_quarter 单股恢复事务：只在 OS TEMP 的合成环境演练

**范围：没有 LIVE --apply 命令，没有生产白名单或定时任务入口。**

2026-11-18 以正式仓库已合入的 `1b85b93` 为基线，日志确认 145/145 项 Windows 离线回归通过；25 只五市场 Capital 抽样全部为单字段候选，其中五只九表联合预检通过。正式 5,003 条待审仍未恢复。

本阶段 `qmt_capital_recovery_transaction_rehearsal.py` 限于合成数据和操作系统 TEMP 下的模拟 Parquet。不调用 QMT 不读实际生产股票数据，且没有 CLI；要求：

- 临时 workspace 中存在完整匹配 `SYNTHETIC_ONLY_CAPITAL_PILOT_V1` 文本的标记；`extra` 和 `workspace` 均位于 OS TEMP 下；只允许合成 `002237.SZ`
- 在 `LIVE.exclusive_writer()` 下检查原 `pending` 项为 `Capital` 历史冲突，要求九表当前源与全部已选历史快照通过 `N.plan_symbol`，正式比较器 `I._plan_symbol` 只为此股票启用 m_quarter 单字段严格证明，其他八表不能出现变动
- 先写 `PREPARED` 恢复日记，记录原 pending、原财务账本 SHA256、原观察日选中版本文件名与 SHA、预检指纹
- 仅在合成文件系统中用真实的不可变 Parquet helpers `I._commit_symbol` 演练写入，验证候选内容寻址文件名及文件 SHA256，再记录 `SNAPSHOT_COMMITTED`
- 写入**合成**的 scoped policy `SYNTHETIC_APPROVAL_EVIDENCE_ONLY`，记录 `POLICY_RECORDED`；比对旧账本和 pending 完全相同后，才在 TEMP 中移除该证券 pending，记录 `LEDGER_RELEASED`、`COMPLETE`
- 四个故障注入：`AFTER_PREPARED`、`AFTER_SNAPSHOT`、`AFTER_POLICY`、`AFTER_LEDGER`。调用 `synthetic_compensate()` 将 pending 原始条目恢复、将模拟认可置为 REVOKED；若旧观察日有同日版本则恢复旧 active pin；所有已生成原始不可变文件均永久保留
- **重要的回退边界**：如果某日原来没有快照，恢复 pending 并撤销认可后，该日新建的不变快照仍存在、可能继续被选中；本协议明确报告 `physical_rollback_claimed=false`，不能虚报整个文件系统回到最初状态。因此生产实现仍需完善事务状态机与未完成版本的可见性控制
- 如果账本 pending 已发生并发变更、旧 same-day snapshot 的 SHA 不匹配、没有 TEMP marker 或试图使用 `D:\\stock`、`D:\\ChatGPT` 正式 workspace 均立即拒绝

**未实现 / 需要先完成：** 当前正式 `I.run()` 尚不读取任何持久化单股认可登记，因此实际释放 pending 会在下一轮再次被严格检测为冲突。P66 不能用来修复真实 002237.SZ，更不能批量放行。下一阶段才把“只读恢复凭证→显式生产授权→同锁重新读取九表→不可变备份→持久范围登记→按证券运行校验→宕机补偿→单股解除 pending”变成完整的生产事务，必须经过独立审批。

**建议 Windows 验收：** `python -B -m unittest discover -s ParquetLiveSync/tests -p test_qmt_capital_recovery_transaction_rehearsal.py -v`，合成安全测试完成后再复跑 P65 的 17 项、九表 15 项和原 QMT 的 83 项。不得手动修改真实 `financial-cache-progress.json`。
