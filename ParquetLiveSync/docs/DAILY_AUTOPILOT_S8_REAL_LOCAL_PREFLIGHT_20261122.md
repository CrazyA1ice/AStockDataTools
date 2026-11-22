# Daily Autopilot S8｜正式本地财务目录的只读安全预检

## 目的与边界

在 S7 Windows 离线回归获得 **630次执行全部PASS**（其中八组专项134、31个市场中心文件485和原操作面板11）后，S8开始针对**真实磁盘上已有的**财务进度账本、Parquet补充数据及既有事务journal进行只读检查。S7通过不代表正式财务入库可启用。S8 **不连接QMT、不调用任何下载API、不写入生产Parquet/H5、active pin、账本或待审队列**，也不修改20:05调度，保持现有三页GUI不变。

S8新增：
- `market_scoped_finance_live_readonly_preflight.py`：仅接受明确的绝对 `--root` 与真实主仓库下 `ParquetLiveSync/work/qmt_extra` 目录。主仓库必须有 `.git` 目录，防止把detached测试工作树内的临时账本当成生产数据。
- 严格读取 `financial-cache-progress.json`，核验正式 `qmt_extra` 数据根的身份，读取前后校验账本SHA256且要求账本大小不超过2MiB，路径链不能含符号链接。
- 默认从账本 `pending` 按代码排序最多抽查3只股票；无待审时退回 `daily_cursor`，都没有时只输出无样本需复核。可以用 `--symbols 000001.SZ,000002.SZ` 显式指定 **1–5只股票、必须排序去重**，`--sample-count` 限1–5。
- 对每只样本扫描财务**九表**的快照文件名和active pin文件名（最新快照限64MiB、active pin限256KiB）、阻断残留 `.qmt-part` / 非法名称 / 符号链接 / 可疑同日版本；验证每张表**最新日期当前选中的Parquet**的Arrow schema、行身份、内容地址、pin SHA，并在报告结束时再次校验上述文件与目录清单未变化。
- 检查 `scoped-finance-transaction-journals` 与旧Capital试点的 `capital-recovery-journal` 是否有任何日志文件；无论状态如何，只要存在就提示 `EXISTING_TRANSACTION_JOURNAL_NEEDS_MANUAL_REVIEW`，避免未经人工确认便重用半成品事务。两目录清单在结束时也再次核验。
- 报告已待审股票数量及原因分布、抽样股票与九表最新快照的状态；**不输出财务原始行内容**，也不做任何人工审批。即使完全无异常，`status`也始终是 `S8_REAL_ENVIRONMENT_READONLY_REVIEW_REQUIRED`，`can_apply=false`、`can_commit=false`、`qmt_live_connection_checked=false`、`all_historical_versions_verified=false`、`multisource_verified=false`。

**重要局限：** 这只是“正式本地目录布局 + 最新选中快照”的有界核验，不是所有日期历史版本的审计。未经验证的较旧日期会在 `older_snapshot_dates_unverified` 展示；已有pending和journal均不得因为抽样通过而移除。未持有正式写锁，因此并发修改只按前后校验尽力检测，不能宣称事务级原子快照，也不能作为任何自动入库令牌。本阶段完全不确认QMT实时连接、行情范围或外部供应商可靠性。

## 开发与测试

新增 `test_market_center_scoped_finance_live_readonly_preflight.py` **21项合成/临时真实Parquet快照测试**：本地账本身份、pending排序抽样、九表检测、主动pin及遗留未pin、旧版本未全检标识、恶意文件残留、孤儿pin、pin篡改、事务日志阻断、运行时日志突变、未来日期、账本SHA变化、无输入授权、禁止apply、无真实写入API等。合成测试仅写OS私有临时目录。

S7统一验收白名单同步注册S8模块+测试，新版预计Python AST **18个文件**、专项 **155项测试**、市场中心32个测试文件约**506项**、操作面板11项，预估实际累计 **672次执行**（专项测试在全回归中重复），但**这些是目标量，不是新提交的Windows实测结果**。最后的正式验收证据仍是S7旧SHA `0f5a072737f7afe23e4370db4babe27ec4fbadf7` 的630次PASS。

## 实机只读预检（需先通过本次新增离线测试）

在独立固定SHA的detached工作树，用项目现有 `.venv/Scripts/python.exe` 运行统一验收（含S8）后，可在**相同解释器和工作树**调用新S8脚本并传：
`--root D:\stock --workspace D:\ChatGPT\AStockDataTools\ParquetLiveSync\work\qmt_extra --sample-count 3 --explicit-readonly`。

若正式目录结构或账本尚不存在，脚本会 `S8_READONLY_PREFLIGHT_BLOCKED`，**不要在预检时自动创建账本、合并账本或重试生产入库**。确认实际用户根目录后，再讨论独立的真实QMT连接检查、全历史证据对照与带写锁/备份的正式持久化事务；这三个尚未启用。

保持 PR #241 Draft，不合并主分支、不部署、不使用GitHub Actions。
