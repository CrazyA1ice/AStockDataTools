# Daily Autopilot S6｜财务不可变快照事务的真实写入沙盒

本阶段**不是正式生产入库**。主界面保持“数据总览 / 下载·更新 / 异常与日志”三页，不增加用户操作流程。原 QMT 增量缓存 + 九表只读对照按钮保持不变；正式 H5/Parquet、20:05调度、共享写锁、财务 pending 和游标均未动。

## 为什么要使用独立沙盒
正式 `_commit_symbol` 已按九表 plan 依次写快照、更新 active pin、最后生成 coverage receipt，但一个股票跨多表写入时可能在多个文件之间崩溃。直接将 S5 `intent_sha256` 当作入库授权，存在部分已写入与原始状态不一致的风险。S6先用真正的 `E._snapshot_write`、`E._verify_financial_snapshot_file`、`E._pin_financial_snapshot` 处理**全新操作系统 TemporaryDirectory**中的合成股票及版本；不接受调用者指定生产数据根路径，也不提供 `--apply` 或正式提交入口。

## 已实现流程
1. 创建独立临时目录，合成9表来源（Capital含旧报表记录及新记录，其余为空），创建合成财务进度账本及同日已 pin 的旧不可变快照。
2. 用 S4 严格九表历史对照 + S5 事务意图计算新的目标文件名、原快照/active pin/账本 SHA256；不触碰真实市场目录。
3. 先将旧财务账本、旧 pin 的原始字节备份到沙盒并 fsync + SHA 校验，然后持久保存 `PREPARED` journal。
4. 用原正式 Arrow/Parquet 不可变快照写入与读回接口写入新版本，记录 `SNAPSHOT_WRITTEN`；读取新 pin 并核对后记录 `PINS_UPDATED`。
5. 仅在合成账本写入 `sandbox_committed_intent` 标记并验证，不修改原 pending 或原交易游标，再记录 `LEDGER_RELEASED` 与 `COMPLETE`。这是顺序模拟，并不是已具备通用的多股票分布式/崩溃原子事务。
6. 故障注入覆盖每一正式阶段及**文件已写而 journal 未写**、**pin 已改变而 journal 未写**、**账本已改变而 journal 未写**，另有旧 pin 备份字节被破坏。任何未完成阶段都只返回 `QUARANTINE_PENDING_MANUAL_RECOVERY`，不主动重放、覆盖、删除原文件或清理待审；备份SHA损坏必须拒绝恢复。

## 安全边界
`market_scoped_finance_transaction_sandbox.py` 仅提供 `--synthetic-only`，运行时自建 `astock-finance-s6-...` 临时目录并要求固定标记；没有 `--root`、`--apply`、股票列表或 QMT 调用，也没有生产数据目录探测。既有真实 `market_scoped_finance_transaction_intent.py` 仍只读、`can_commit=false`。中断演练报告的 `real_market_writes=0` 不意味着沙盒不写文件，而是所有真实写入均限定在临时目录。

## 交付门禁
本轮新增16项合成/沙盒测试（含不同故障点、旧版本哈希/旧 pin 备份/账本游标保留、意外备份损坏和禁止生产调用）。连同S5之前预计442项 `test_market_center*.py`，预计458项；**尚未在用户Windows或有pyarrow的本地解释器运行**，只能声称代码已提交、差异已核查。当前执行环境缺pyarrow且网络无法安装，因此不能伪称运行通过。

真正生产入库的后续工作仍需：在独占写锁下重取并复核原始源指纹、全九表真实交易 journal/备份/回读及断电恢复演练、同一批多股票一致性门禁、跨源核验、针对既有历史待审的额外拒绝规则、显式批准和独立回滚流程。**本阶段没有打开GUI正式入库按钮，也没有部署**。