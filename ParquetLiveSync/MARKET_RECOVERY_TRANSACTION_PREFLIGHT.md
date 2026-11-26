# 八周期修复事务目标足迹预检（只读，不存在正式写集授权）

## 定位与前置验收

AStockDataTools 长期面向跨交易日期、不同证券、八周期、多个来源的行情管理与修复。此阶段不是 2026-11-25 的单日专用脚本。上一阶段 Draft PR #272 固定提交 `94b62812ccdfc0920e474c3fd7c3e288430c5b14` 已由用户 Windows 实机完成 **337/337 项测试通过**，同日九个原隔离股票日均输出阻塞审核请求，诊断审核方案 `plan_sha256=d73c29532e752b9922753419b76de43c7d0d27863baa8cc13a4e80720fe8bb3a`。没有生成 QMT 原生一分钟修复行情、没有市场写入或隔离放行。

新增 `market_recovery_transaction_preflight.py`，从已通过 `market_recovery_review_plan.validate_plan` 的完整审核请求构造**可能受影响的八周期 Parquet 目标足迹**。本工具不形成可写目标集合、不建立锁、不拷贝备份、不生成私有行情候选、不执行事务。

## 通用命名规则与去重

按与现存 `local_layout` 一致的文件名：

- 交易日所属年早于明确声明的 `--layout-year` 时，每周期使用 `period/YYYY.parquet`。
- 交易日所属年等于 `--layout-year` 时，每周期使用 `period/YYYY-MM.parquet`。
- 交易日所属年晚于声明的布局年时立即拒绝；布局年必须显式指定，不因系统时间变化而自动改变结果。
- 对同一月份、同一物理目标中的多只股票，生成**一个**文件条目并引用所有受影响的审核请求 ID。原始输入可覆盖不同日期、证券、周期、来源；每个日期保守展示八周期需要考虑的文件。
- “可能受影响”不是“所有八个文件一定需要覆盖”：实际写集还必须依赖将来经独立批准的分钟数据候选、周期聚合和逐文件差异复核，这些当前尚未存在。

一次最多 128 条已有审核请求，最多 256 个不重复可能目标文件；若超限直接拒绝，不能截断一部分并称整次审计通过。

## 可选物理目标只读 SHA

默认不主动定位用户的真实 Parquet 数据库。未指定 `--target-root` 时，所有目标均为 `NOT_INSPECTED_NO_TARGET_ROOT`，`physical_target_files_checked=0`。

只有操作者明确给出根目录时，才调用正式 `local_layout.storage_root` 复核 `AllCycleAStockData` 与八周期目录，并对当前目标按已存在的 `market_quality_source_proofs._hash_stable_file` 计算真实字节 SHA。缺文件记为 `ABSENT_BLOCKED`；已存在且字节已检查的文件记为 `EXISTING_BYTES_OBSERVED_NOT_BACKED_UP`。路径 symlink、目标为非普通文件、来源大小越过已有受控 SHA 限制等不降级通过，直接要求复核。

**注意：** 这个 SHA 是“当次读取的物理文件 SHA”，不是已经做了备份，绝不是经真实 CAS 锁保护的更新前快照；如果目标文件可能并发被其他进程更新，后续真正获批实施也必须重新核对最新版本，创建真实回滚备份并通过恢复演练。此阶段不假装自动锁定生产任务或停止其他读写者。

## 只读命令

仅生成静态事务目标足迹，不触碰真实数据文件（推荐先执行）：

```powershell
& "D:\ChatGPT\AStockDataTools\.venv\Scripts\python.exe" -B "D:\ChatGPT\AStockDataTools\work\PINNED_TXN_WORKTREE\ParquetLiveSync\market_recovery_transaction_preflight.py" --module-root "D:\ChatGPT\AStockDataTools\ParquetLiveSync" --start-day 2026-11-25 --end-day 2026-11-25 --layout-year 2026 --summary-only
```

若后来确需核查现有生产八周期文件的物理 SHA，**另行确认根目录确切位置和读盘负载**后，才可添加 `--target-root "D:\YourExistingStockRoot"`；本次没有给出这个参数，不扫描生产八周期 Parquet 文件。正式底层文件可能大于原来源字节审计的 1 GiB 限额，该情况会按已有安全策略报错而非悄悄跳过；不得擅自提高预算或关闭验证。

## 事务分层门禁

输出始终为 `TRANSACTION_BLUEPRINT_BLOCKED_NO_STAGING_OR_COMMIT`：

- 已经审核原隔离并保存了诊断 SHA，但不是“已生产私有候选”：`native_minute_payload_present=false`、`private_candidate_materialized=false`。
- “知道目标现有 SHA”不等于“已经完成回滚备份”：`private_backup_materialized=false`、`rollback_tested=false`。
- 正式写入、自动下载或关闭原隔离未授权：`market_parquet_or_h5_write_authorized=false`、`qmt_cache_write_authorized=false`、`production_merge_authorized=false`、`qmt_history_download_calls=0`、`producer_quarantine_cleared=false`。
- `staging_bytes_written=0`、`production_bytes_written=0`。

只有在另行独立来源认证、获得真实可校准的分钟数据、六字段及八周期验证、版本化不可变候选、回滚演练和用户明确批准后，才能考虑设计实际持久化事务及主数据库合并。

## 本轮测试事实

本轮在隔离 Python3 环境对与 GitHub 完全相同的模块及测试文件执行 **23/23 项单元测试 PASS**，涵盖 2019/2026 历史年度/当前年度布局、跨月目标、九只同月股票的八周期物理目标去重、缺省不扫描目标、可选真实临时文件的 SHA 与 mtime 不变、缺文件、symlink、目录伪装、伪造审批、证据版本变化、异常年度和无权限写入。源码 Git Blob `b988385e8c7e2484620ac3d83df99226820b3210`、测试 Git Blob `dd2256f23b3afa903335862e712521ce20c16217` 已与仓库远端完全一致。

这 23 项只使用合成审核输入、临时物理文件和局部布局测试替身；**尚未**完成新分支在用户 Windows 上与完整生产来源适配器联合执行。上一轮 337 项通过不应提前扩写为本轮的 **360 项 Windows 通过**。
