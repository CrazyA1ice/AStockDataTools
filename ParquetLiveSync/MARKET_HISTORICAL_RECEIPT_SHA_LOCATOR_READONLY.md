# P3.12 可轮转最新回执与原始历史 SHA 的安全只读分离

## 触发证据：已证实的当前最新文件不匹配

2026-11-26 用户 Windows（P3.11 修复 SHA `46534644608bf6fb54e47921cfb13e8ff0362b5a`）完成 565/565 项测试，但执行九条隔离真实审计时返回 `EvidenceError`。进一步只读诊断证明：

- 固定的 **2026-11-25 历史运行回执** SHA256 是 `72a7104bd831e969958507399263ff74fb4092d6f7bf51d4ac3c42e000a1d837`。
- 当前 `ParquetLiveSync/work/last-afternoon-unified.json` 物理 SHA256 实际是 `6c283e5979312ea2bdf248747fd836bf96f8b0ce5e0a9e48c53d6e14955ff1c2`，Windows 最后修改时间为 **2026-11-26 20:06:13**。
- 旧审计器独立打印明确失败 `RUN_RECEIPT_SHA_MISMATCH`（exit 3）。因此当前最新文件已经**不是**原固定历史回执；其更换原因及原始历史回执是否仍有其他备份尚未证实。
- 先前 5206 接收/9 隔离（7 个 SZ300119～125 缺分钟、2 个 SH605336 / SZ300462 DAY 开盘不一致）是当时实测原回执事实，**不能**在当前回执不匹配的情况下说“11 月 25 日重新复核完成”。

## 代码：只读按固定 SHA 找真实历史原件

`market_historical_receipt_sha_locator_readonly.py`：

1. 唯一目标是**硬编码原回执 SHA**，不接受命令行任意 SHA 当作 Nov25 真相。仅从操作者提供的真正 `ParquetLiveSync` 目录下 `work` 开始，或显式指定其安全相对子目录（`--search-subdir`）；默认只探索 **2 层子目录**，最大允许 3 层。严禁扫描系统盘、跳出 `work`、遍历 symlink，且若目录实际不存在则明示错误。
2. 每次最多检查 **768 个目录项、128 个 JSON 候选、64 MiB 累计 JSON 字节**，对单个 JSON 最大 **24 MiB**；超限或路径不安全则停止，不能伪装成“未找到”。忽略超大或空 JSON 时单独记录相对路径并将 `scope_exhaustive=false`；如果找不到，也只能陈述**已指定深度及子目录里**没有发现匹配文件，不得推断所有磁盘、QMT 服务端、所有历史证据不存在。
3. 为候选 JSON 直接流式计算物理 SHA，固定 SHA 碰上时再核验一次，并比较文件大小、inode、mtime；仅输出 SHA、`work` 下相对路径、字节数与扫描范围，不打印私有绝对路径或 JSON 正文。
4. 即使完全 SHA 相同，`original_run_and_stage_log_chain_verified=false`：这个工具**不**承诺历史 stage log、原私有 DAY 候选或供应商身份均有效；须另行执行下述原审计器及真实九条缺口审计。

## 代码：显式历史原件路径（保留旧默认行为）

在 `audit_market_quarantine_readonly.py` 增加可选 `--receipt-relative` 参数，默认仍是原 `work/last-afternoon-unified.json`；传入时只能是 `work` 下的安全 JSON 相对路径，路径穿越、绝对路径、Windows 卷标、上级跳转、任意 symlink 均拒绝。**没有改变固定回执 SHA 的任何判断**，照旧校验原 `EIGHT_PERIODS` 日志、原生产元数据、当日私有候选 Parquet 文件物理 SHA。若历史日志因维护被删除、原回执找不到或候选已被改动，会继续 FAIL CLOSED。

P3.11 `market_nine_quarantine_offline_source_gap_readonly.py` 同样新增 `--receipt-relative`，其原九条生产审计依旧检查两次，并在输出中清楚列明选择的是哪个真实回执相对路径。**默认没有改变**。

示例（历史文件实际被找到、SHA 校验相同后才可填入相对路径；此处仅是示例，`history/...` 并不宣称存在于你的电脑）：

```powershell
& "D:\ChatGPT\AStockDataTools\.venv\Scripts\python.exe" -B "D:\ChatGPT\AStockDataTools\work\PINNED_P312_WORKTREE\ParquetLiveSync\market_historical_receipt_sha_locator_readonly.py" --module-root "D:\ChatGPT\AStockDataTools\ParquetLiveSync" --search-subdir "." --max-depth 2
```

找到原件时，应先这样验证整条旧证据链（将 `EXACT_RELATIVE_ARCHIVE_JSON` 替换为查出的实际相对路径）：

```powershell
& "D:\ChatGPT\AStockDataTools\.venv\Scripts\python.exe" -B "D:\ChatGPT\AStockDataTools\work\PINNED_P312_WORKTREE\ParquetLiveSync\audit_market_quarantine_readonly.py" --module-root "D:\ChatGPT\AStockDataTools\ParquetLiveSync" --day 2026-11-25 --expected-run-sha256 "72a7104bd831e969958507399263ff74fb4092d6f7bf51d4ac3c42e000a1d837" --verify-parquet --receipt-relative "EXACT_RELATIVE_ARCHIVE_JSON"
```

只有旧审计器以完整回执+日志+候选物理 SHA 验证成功，才可以继续 P3.11 对九条隔离的既存本地分钟文件清单。**绝不能重新创建或覆盖** `last-afternoon-unified.json` 以求通关，也不得伪造新 Nov25 回执、将不同 SHA 强行当作旧回执、修改市场 Parquet/H5、QMT 缓存、生产隔离或调度。

## 测试与真实数据阻塞

新增 **24 项** Python 回归用例：最新回执 SHA 不同而历史备份真实存在的完整合成 5206/9/5215 证据链、旧默认不变、显式 SHA/日志/候选文件缺一不可、路径穿越/卷标/symlink 拒绝、查找深度/条目数/字节预算、只读报告与九条清单可关联。P3.11 原 **565/565** 已由 Windows 验收；本 P3.12 提交后累计目标 **589 项（24 模块）**，尚待用户实机运行。所有新测试都使用临时合成源文件，不是用户私有回执，必须通过固定提交并在实际用户目录内查到同 SHA 原件后才可宣告历史证据链恢复。

若扫描结果无匹配，应如实报告“这一明确扫描范围无匹配”，停止历史证据复核。下一阶段只可在用户进一步指定已存在的其他备份目录后扩展**只读**定位范围；不因目标文件找不到就解禁九条隔离。
