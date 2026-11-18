# P67 · Capital.m_quarter 精确报告日认可登记的只读消费门槛

日期：2026-11-18。P66 Windows 本机回归 162/162 PASS、正式仓库 `725e0eb`；当前正式数据 5,003 待审仍未释放。本阶段以此版本新建独立开发分支。

## P67 已开发

`qmt_capital_scoped_policy_reader.py` 只提供只读解析和严格语义验证，不提供创建/授权/签发正式政策的流程。原正式财务导入器 `run()`、计划任务、CLI **没有自动加载任何授权文件**；仅新增内部 `_plan_symbol(..., capital_policy=None)` 与 `_commit_symbol(..., capital_policy=None)` 的默认关闭受控对象参数。未显式传入时行为与 P66 完全相同；同时传入此前 P65 的模拟单股参数会直接拒绝。

合成认可票据结构 `qmt_capital_explicit_record_allowance_v1` 的受控身份包含：

- `symbol`、`root`、`field=m_quarter`、`status=ACTIVE`、`activation_asof`；
- 旧版原始快照与获得认可的候选快照的观察日、内容寻址文件名、真实物理文件 SHA-256；
- 只针对列明 `m_timetag` 的具体业务字段 SHA-256、认可的当前 `m_quarter` 值、此前历史版本允许的**精确** `m_quarter` 值集合。

每次验证都独立检查旧/新快照物理字节与 Parquet 行身份；认可的 asof 仍指向原批准候选的 active pin，不能被别的同日快照替换；把不再被 active pin 选择的旧版原始快照也纳入校验。所有已保存报表日期、原始业务字段、字段有无和当前缓存必须准确匹配。除已明文列出的报告日期及准确值外，**其他 Capital 记录和其余八张财务表仍执行原有严格比较**。

该比较器可通过合成数据证明：即使旧的 m_quarter 异常记录仍永久保留，次日缓存完全相同时仍返回 `UNCHANGED`，不会再次创建重复的同一天内容寻址快照；但这尚不等于已完成真实日常生产管线的自动恢复。**新增财报日期、QMT 返回第三种 m_quarter、真实股本修订、老快照/hash 变化、版本 pin 改变、字段缺失、过宽名单一律拒绝或要求独立复核。**

## 明确尚未实施的真实事务边界

- 没有提供任何真实 `--apply`、`--approve` 或永久启用该策略的命令；单纯在文件中写 `status=ACTIVE` 不构成用户授权，也不能触发定时任务政策应用。
- `read_policy(...)` 只是只读文件接口；只有将来经过独立批准、原始账本审计和不可变事务写入的可信登记，才可能由正式 runner 接收。尚没有生产 ticket 签发器、签名/完整性锚点、持久撤销链、故障启动自恢复与跨 5001 只规模化的受控批量策略。
- 目前政策仅覆盖**相同的历史报告日期集合**；新公告产生新财务记录时不会自动放行，更不会悄悄丢弃变动的真实财务记录。要恢复公告日持续增量还需另行设计 append-only 报表日期验证。
- 现有 mass-history-conflict 熔断不改变，不因 P67 只读样本开启，也不清空 5,003 个 pending；行情、板块、除权阶段保持先行，16:30 自动任务调度不变。
- `PerShare` 的 0=0 只证明当前缓存与历史空表一致，不证明该供应商表的真实覆盖率。

## 推荐验收

只在 Preview worktree 用生产虚拟环境离线运行 `test_qmt_capital_scoped_policy_reader.py`、P65/P66、`test_finance_daily_guard.py`、`test_qmt_extra_data.py`。源和快照均为合成的 OS TEMP 目录，没有真实 QMT 请求，无需抢 16:30 计划任务的采集锁。待上述测试通过，再将**默认关闭的读取能力**合入原分支，不能在正式机器上人工制造 `ACTIVE` 政策文件。
