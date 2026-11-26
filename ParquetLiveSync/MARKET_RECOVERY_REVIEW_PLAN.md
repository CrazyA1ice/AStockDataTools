# 修复审核方案与证据版本比较（只读；不生成分钟修复数据）

## 长期能力

这不是只针对 2026-11-25 九只股票的脚本。任何由现有 `market_quarantine_recovery_readiness.inspect` 核验过的有界日期范围，都可使用 `market_recovery_review_plan.py` 生成版本化的**审核请求**。

已确认的前置 Windows 验收：固定 PR #271 HEAD `3cd94b8cbbc29c3ee214ebd6c2c497e609c66c23`，十三个模块共 **308/308 PASS**；2026-11-25 九只原隔离股票的 TDX DAY 只读来源检查通过，但全部维持 `BLOCKED_REVIEW_ONLY_NO_REPAIR`，原 47 项问题和 5206 接收/9 隔离、`PARTIAL` 均保持不变。

## 审核请求与物理修复候选绝不混淆

- 输入是上一阶段的**完整** `astock_market_quarantine_readiness_readonly_v1` JSON，通过原 `review_sha256` 规范化哈希与原 backlog SHA 检查真实性范围。还验证已批准状态均为 false、证券日范围/原隔离数量、原稳定事件 ID 与必需阻塞项没有静默删除。
- 输出 `astock_market_recovery_review_plan_v1`；`review_request_id` 由版本化作用域 `trading_day/symbol/period/source_id` 确定，`evidence_revision_sha256` 对独立来源证据、原生产回执字节 SHA、已接收候选 Parquet SHA、TDX DAY 物理 SHA、原规则与缺失证据清单建立确定性摘要。
- 原 QMT 缺失的 241 根一分钟行情**没有**被任何默认来源文件 SHA 代替；`minute_payload_present=false`、`market_candidate_rows_generated=0`，绝不写私有或正式候选。
- 即使本次只看到合法 DAY 记录，也**不能**自动清除原 QMT 分钟隔离。所有输出维持原数据未修复、没有独立官方证券日全集或供应商身份认证、无 QMT 下载、无正式数据写入、无入库授权。

每次输出还有 `plan_sha256`，它是规范化 JSON 的**诊断 SHA**，不是提供商签名、审批签名或原 QMT 数据字节 SHA。

## 无持久化的版本比较

只有操作者**已另外存在**旧版方案文件，才可指定 `--prior-root`、`--prior-relative`、`--prior-file-sha256` 三个参数一起读取它。读取时复用本仓库来源安全路径/物理 SHA 检查，拒绝 symlink、目录遍历、无效/重复 JSON 键、巨大文件、旧版本自动写入授权伪造。

比较结果只允许四类：`UNCHANGED_EVIDENCE_STILL_QUARANTINED`、`EVIDENCE_REVISION_CHANGED_REQUIRES_REVIEW`、`NEW_SCOPE_REQUIRES_REVIEW`、`NOT_IN_CURRENT_REVIEW_SCOPE_NOT_RESOLVED`。最后一类特别重要：本次不见某条旧隔离，**不代表**它已由市场证据证实解决，更不能将其标为 CLOSED。两个版本都没有自动关闭原生产隔离的权限。

## Windows 只读命令示例

无需额外独立数据源，也不调用 QMT；以下命令只读取现有的原生产回执、已接收候选 SHA 和本地 TDX DAY 证据并把版本审核结果**打印到控制台**：

    & "D:\ChatGPT\AStockDataTools\.venv\Scripts\python.exe" -B "D:\ChatGPT\AStockDataTools\work\PINNED_REVIEW_PLAN_WORKTREE\ParquetLiveSync\market_recovery_review_plan.py" --module-root "D:\ChatGPT\AStockDataTools\ParquetLiveSync" --start-day 2026-11-25 --end-day 2026-11-25 --summary-only

移除 `--summary-only` 可显示所有逐股票审核请求。只有确实另外留存了通过验证的完整旧方案时，才能追加 `--prior-root ROOT --prior-relative relative.json --prior-file-sha256 SHA256`。此前仅输出的 `--summary-only` JSON **不包含** `requests`，不可当作完整旧方案比较输入；也不能在测试中伪造同源独立供应商身份。

## 验收边界

新模块的 29 项离线规则与文件字节正反测试已经在隔离 Python 环境执行 **29/29 PASS**，包含 2019/2026 多日期、不同周期与来源、证据版本稳定身份、旧方案不自动解决、独立 SHA 篡改、伪造授权、重复记录、无原生 QMT 阻塞项、旧方案文件重复 JSON 键、路径越界和隐藏私有路径。测试使用合成准备度输入及临时文件；它**没有替代真实用户 Windows 完整联测**。

前置 Windows 308 项测试属于 PR #271，**不是**本 PR 的已运行 Windows 337 项。最终源码是否与离线所执行版本完全一致，须以新固定 GitHub commit 和下一轮 Windows 运行结果为准。不要自动修改生产 Parquet/H5、QMT 缓存或定时任务。真正生成可校准的原始分钟修复候选、隔离目录的不可变审计落盘和可回滚事务仍是下一阶段。
