# P69 · 真实 002237.SZ 单股财务恢复事务候选（默认只读）

## 依据与现状

- 2026-11-18 本机只读 census: pending 5003 = Capital 5001, Top10Holder 1 (688006.SH), CACHE_DECODE_ERROR 1；触发 mass guard 的历史冲突总数 5002。此处不是 5002 条实质性错误的证明。
- 单股九表真实预检: `002237.SZ`、2026-11-18，`ELIGIBLE_FOR_MANUAL_PILOT_PREVIEW`；Capital 102 报告日期，1 个 `m_quarter` 旧值差异；其他 8 表完全一致。PerShare 为 0 行，覆盖范围未证明。
- 当次预检摘要 `37fb39622233ad58415d552eee5a161adadeba5f391a2412958c5de89ca761a9`，私有账本摘要 `550421c578b83c31465c9eafbe0ba95e327580a0c13a133452b2cb99adbb0736`；这两个 SHA 是 2026-11-18 17:05 左右的**历史证据**，不能保证之后源未变化，应执行最新只读预检。
- 全局熔断保持开启，既有日更脚本不加载 P67 策略，不执行本模块。没有任何自动的 5001 只放行流程。

## 新模块

`qmt_capital_one_stock_transaction.py` 独立于 daily runner、无人值守计划任务，默认读取已存在的 QMT 本地财务缓存，仅处理完全匹配的股票 `002237.SZ`。

默认预检（只读财务数据、不进行全量下载、不释放 pending）：

```powershell
& "D:\ChatGPT\AStockDataTools\.venv\Scripts\python.exe" -B "D:\ChatGPT\AStockDataTools\ParquetLiveSync\qmt_capital_one_stock_transaction.py" --repo "D:\ChatGPT\AStockDataTools" --root "D:\stock" --symbol "002237.SZ"
```

预检在**唯一真实生产 checkout** 上取得与日常采集共用的 exclusive writer lock，原始历史快照、当前缓存九表、账本、候选文件名和冻结摘要全部重新校验。实际写入必须额外显式传入：

- `--apply`；
- `--approval AUTHORIZE_CAPITAL_ONLY_002237.SZ`；
- 与**同日最新预检**严格相等的 `--expected-ledger-sha256` 和 `--expected-preflight-sha256`，均为完整 64 位十六进制；
- 正式主 checkout，且 China 日期与预检观察日一致；不能在 Windows 定时任务运行期间操作。

**目前不建议执行真实 --apply：必须先在 Windows Preview 中跑完新增 synthetic 回归并审核事务故障行为。**

## 事务步骤

1. 锁内检查其 `Capital` pending 仍在、九表其余八表字节语义相同、Capital 只变动白名单字段、来源日期集合不变，且候选版仅需创建 Capital 一张表。
2. 在私有工作空间落 `PREPARED` 日志，记录原始 pending、原账本 SHA、九表预检 SHA、原始版本 SHA 和候选文件名。
3. 使用现有 `qmt_extra_data` 内容寻址原语只写新的 **Capital** 单表 Parquet；完整校验后原子更新该 asof 的活动指针。**绝不删除/覆盖旧原始快照**。
4. 生成严格限定 report_key、approved_quarter、所有旧值、业务字段 hash 的 P67 策略，并由 P67 独立读取验证所有历史原始记录，随后原子写入 policy；只有明确审批的本次事务可以生成此文件。
5. 比较私有账本 CAS SHA 与旧 pending 精确内容，仅删除 `002237.SZ` 这一项，并原子保存账本，按序写 `LEDGER_RELEASED` 和 `COMPLETE` 事务日志。
6. 任何步骤中断都会留下未完成 journal，自动**拒绝重复 apply**；此时仍需人工执行隔离补偿。补偿可恢复 pending、撤销策略，但新写入的 immutable 文件保留，**不声称物理完全回滚**。

## 明确限制

- 模块不变更量化行情八周期、H5、交易日、ETF、板块、除权或 20:05 单计划任务。
- 当前 P67 检查器要求批准时的旧报告日期集合准确一致；新增公告日期、真正的总股本/流通股本修订、新的 `m_quarter` 变体、SHA 差异一律拒绝，须后续另行设计新增公告增量管理。
- 完成单股事务也**不会解锁 5002/5656 mass guard**，当天的财务 daily 仍会阻断，直到具备可信的分批异常恢复机制。
- 不应直接在 Git Bash/Preview 中写入真实文件；生产状态机只能由安装目录下已验证的主 checkout 执行。
- `status=ACTIVE` 的文件本身不是信任根；必须依赖对单股显式 SHA 绑定、日志和事务内验证。无人值守导入器不会使用它。
- 若手工事务中断，不要随意删除 journal、候选快照或策略，应先读取 journal 的 phase 并复核事务以确定安全补偿方式。
