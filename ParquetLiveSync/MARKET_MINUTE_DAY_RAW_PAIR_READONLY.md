# P3.6 双真实文件 SHA 绑定的分钟与 DAY 六字段原始差异诊断

## 适用数据与不可越界的信任边界

在 P3.5 固定提交 `c8f5b0436383c684219331924335f36ef9da4221` 经操作者 Windows **434/434** 成功后，下一阶段不再仅检查单个分钟 JSONL，而是由 `market_minute_day_raw_pair_readonly.py` 将**两个显式指定的已存在物理文件**串行交叉审计：

1. QMT 探针原格式 JSONL，使用 P3.5 `market_native_minute_jsonl_readonly.inspect` 验证指定证券日的准确 **241 根**或仅缺开盘 09:30 的 **240 根**标签、六字段数值、实际 JSONL 文件 SHA、时间范围和单证券身份。
2. 声明的 DAY 导出 Parquet，使用原 `market_official_day_content_readonly.inspect_explicit` 对单独的根目录、相对路径、真实 SHA、指定交易日与证券代码核验物理字节与 DAY 内容。注意 **“声明的 DAY”不等于验证了官方交易所提供商身份，也不是交易所完整股票日全集**。
3. 同一范围的两份验证回执必须都报告没有来源身份认证、没有分钟校准、没有生产写入资格；作用域与 SHA 复核一致，且两份物理文件不能是同一 inode/路径。完成两次内容读取后再独立只读复核双方 SHA/大小/文件身份以缩小竞争变更窗口；**无法据此声称全程持有文件锁**。
4. 只生成六字段原始数值差、相对于声明 DAY 的原始相对差，输出单一可重算的组合来源诊断 SHA。字段包括 open/high/low/close/volume/amount。即使六字段数值恰巧相等，也不得将原始 241 根 OHLCVA（可能包含开盘集合竞价）直接判定为购买源校准成功，亦不得将来源的同一 SHA 解释为数据商的有效签名。
5. 显式始终设置 `provider_independence_or_identity_authenticated=false`、`qmt_native_origin_authenticated=false`、`minute_paid_scale_or_timestamp_calibrated=false`、`six_field_comparison_quality_passed=false`、`official_stock_day_universe_certified=false`、`eight_period_recalculation_verified=false`、`producer_quarantine_closed=false`、`market_candidate_validated=false`、`backup_materialized=false`、`physical_source_lock_held=false`、`production_merge_authorized=false`、`market_files_written=false` 和 `qmt_download_calls=0`。

## 操作示例（全部路径与 SHA 由操作者提供）

**仅在已经独立存在两份真实文件且知道其 SHA 时使用；不得按命令构造 QMT 原生分钟文件，也不得把已接收的 Parquet 候选 SHA 代替被隔离的原生分钟。**

```powershell
& "D:\ChatGPT\AStockDataTools\.venv\Scripts\python.exe" -B "D:\ChatGPT\AStockDataTools\work\PINNED_P36_WORKTREE\ParquetLiveSync\market_minute_day_raw_pair_readonly.py" --minute-evidence-root "D:\ExistingQmtProbePrivateRoot" --minute-file-relative "ACTUAL_PROBE.jsonl" --expected-minute-sha256 "ACTUAL_QMT_PROBE_FILE_SHA256" --day-evidence-root "D:\ExistingDayEvidencePrivateRoot" --day-file-relative "ACTUAL_DECLARED_DAY.parquet" --expected-day-sha256 "ACTUAL_DECLARED_DAY_FILE_SHA256" --symbol "300119.SZ" --target-day "2026-11-25" --minute-start-day "2026-11-20" --minute-end-day "2026-11-25"
```

所有占位符必须替换为真实已知的文件和 SHA，不需要、也不允许自动查询 QMT 缓存。没有实际存在的原始文件时按缺证处理，不改动任何生产文件。

## 验收

- 新增 21 个跨源物理证据组合的离线测试：241/240、不同年和股票、跨日期、字节 SHA 不符、目标缺格、路径越界、符号链接、伪造回执授权、SHA/日/证券范围不符、量纲差异、读取中变更、重复一致性和无写入。
- 隔离环境 **21/21 已执行通过**，使用了与正式回执 API 一致的 DAY 测试替身及真实临时文件，GitHub 新模块/测试 blob 与本地运行版本完全一致；**尚未在真实原仓库环境执行新增 21 项**，需要在 Windows PyArrow 26.0.0 下运行包含此前 434 项的 **455 项**。
- 由于没有操作者提供的对应被隔离 QMT 私有 JSONL 与独立 DAY Parquet 实际 SHA，此阶段也**没有运行真实 2026-11-25 九只隔离股票的内容对照**；本次任务没有取得访问该物理证据的路径权限。

后续真正六字段跨源质量判定仍须可验证的 QMT 提供商出处、购买源时区/时间偏移、复权及量额缩放校准、与交易所日期/证券全集的身份和内容证明，再由独立事务层经明确批准执行修复；原 9 条隔离和 47 个 incidents 不能自动清除。此工具从不修改正式 H5/Parquet、缓存、定时任务、原回执、私有源文件。
