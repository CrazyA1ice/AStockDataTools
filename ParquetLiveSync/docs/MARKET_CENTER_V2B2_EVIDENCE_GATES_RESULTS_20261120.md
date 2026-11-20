# V2-B2：历史缺口证据门禁与可视化核验结果（2026-11-20）

状态：独立 Draft 开发，原 20:05 Windows 任务和用户 canonical 数据库不修改。用户已在上一阶段通过 V2-B 48/48 合成测试，并核验 2026-11-19 的 000001.SZ 和 600519.SH 日线各存在1条记录、观察异常0。此结果不能证明官方交易日或跨源完整性。

## 功能和限制

**结果页**：核验结果改为四张摘要卡片（已观察、异常待审、未观察/待确认、缺失候选）+ 每股票/周期/时间戳标签日的滚动表格 + 可展开的原始证据，不再显示整个大块深色日志。

**资格证据门禁**：可选外部 JSON 快照，仅作为用户明确提供的补充材料。必须有精确覆盖查询范围的各交易所日期状态、每只股票上市有效期及逐日可交易/停牌/未知状态、声明来源名称；同时提供原始文件 SHA-256，不允许根据六位股票代码猜交易所，不允许缺失日期在表中默认为可交易。

**诚实标注**：
- 已经读到一条数据：RECORDS_PRESENT_NOT_CERTIFIED，不等于完全认证。
- 未读到记录而没有日历/股票状态证据：NO_ROWS_CALENDAR_AND_ELIGIBILITY_UNKNOWN。
- 声明为交易日、股票上市有效且不停牌但未读到：MISSING_CANDIDATE_SOURCE_AUTHENTICITY_UNVERIFIED，只是候选。
- 声明非交易日、上市前、退市后、停牌：只标 DECLARED_UNCERTIFIED；不冒充官方认证。
- 缺整个物理 Parquet 分区：PHYSICAL_PARTITION_MISSING_STOCK_GAP_UNDETERMINED，不将此误当成逐股确认缺失。
- 周/月时间戳标签不等于自然交易日：LONG_CYCLE_LABEL_NEEDS_CLOSURE_PROOF。
- 文件记录与外部日历/停牌声明相矛盾：PHYSICAL_SOURCE_DECLARATION_CONFLICT_UNVERIFIED，双来源均待复核。
- 任何结果 confirmed_missing_count 始终为0，allowed_repair_or_backfill 为false；不执行 QMT、下载、历史补更或覆盖。

**安全门禁**：必须明确指定 stock/AllCycleAStockData 目录和 --explicit-readonly；最多20只股票、31个自然日、32个分区、160个行组、250万候选行，ASOF 限制 2026-11-19。与唯一 20:05 运行器使用同名 Windows mutex，保留北京时间19:55—20:20 禁止核验窗口；新增最长约45秒的扫描超时，并在19:55前预留30秒释放空间。超预算、超时、证据SHA不一致、证据范围不完整则拒绝扫描/判定。

## 快照格式（只说明结构，不提供虚构的真实证据）

format: market_center_v2b2_eligibility_snapshot_v1

scope: start/end/stocks（必须与审计返回范围逐一相等）

exchange_calendar: SH、SZ、BJ所需交易所逐日映射 YYYY-MM-DD → TRADING / NOT_TRADING / UNKNOWN

stocks: 每只代码的 listed_on、valid_through（可为空）、day_states（每个日期 ELIGIBLE / SUSPENDED / UNKNOWN）

provenance: calendar_source、listing_source、suspension_source（三项来源名称）。

需同时传 --evidence-file 本地绝对路径与 --evidence-sha256 完整64位十六进制值。SHA 只证明文件字节完整性，绝不能证明来源权威性。不要把合成测试材料用于真实股日判断。默认没有提供快照时，保持证据不足，拒绝认证缺失。

## Windows 验收顺序

1. 关闭上一版 GUI。将新分支放到新 detached worktree，不覆盖原 V2-B 测试目录。为避免之前的中文提交输出问题，使用 git worktree add --quiet。

    $ErrorActionPreference="Stop"; $r="D:\ChatGPT\AStockDataTools"; $w=Join-Path $r "work\market-center-v2b2-20261120"; if(Test-Path -LiteralPath $w){throw "V2B2_TARGET_EXISTS"}; & git -C $r -c http.sslBackend=schannel -c http.version=HTTP/1.1 fetch origin feat/market-center-v2b2-evidence-gates-results-20261120; if($LASTEXITCODE -ne 0){throw "FETCH_FAILED"}; & git -C $r worktree add --quiet --detach $w FETCH_HEAD; if($LASTEXITCODE -ne 0){throw "WORKTREE_FAILED"}; & git -C $w rev-parse HEAD

2. 三组纯虚构合成测试；无真实数据写入或 QMT。

    $ErrorActionPreference="Stop"; $w="D:\ChatGPT\AStockDataTools\work\market-center-v2b2-20261120"; $py="D:\ChatGPT\AStockDataTools\.venv\Scripts\python.exe"; $env:PYTHONPATH=Join-Path $w "ParquetLiveSync"; foreach($p in @("test_market_center_v2_preview.py","test_market_center_v2_readonly_audit.py","test_market_center_v2_evidence_gate.py")){& $py -u -B -m unittest discover -s (Join-Path $w "ParquetLiveSync\tests") -p $p -v; if($LASTEXITCODE -ne 0){throw "V2B2_TEST_FAILED: $p"}}; Write-Host "V2B2_OFFLINE_TESTS_COMPLETE"

3. 三组测试均通过后，避开每天北京时间19:55—20:20，完成2只股票1天日线的真实只读核验。无证据快照时，必须保留“尚未认证”的结论。

    $ErrorActionPreference="Stop"; $w="D:\ChatGPT\AStockDataTools\work\market-center-v2b2-20261120"; $py="D:\ChatGPT\AStockDataTools\.venv\Scripts\python.exe"; & $py -u -B (Join-Path $w "ParquetLiveSync\market_center_v2_audit_cli.py") --market-root "D:\stock\AllCycleAStockData" --start 2026-11-19 --end 2026-11-19 --symbols "000001.SZ,600519.SH" --period day --explicit-readonly; if($LASTEXITCODE -ne 0){throw "V2B2_READONLY_AUDIT_BLOCKED"}

4. 运行独立 GUI：在更新/核验页选择数据核验、指定股票（000001.SZ,600519.SH），只勾选八周期行情，日期2026-11-19至2026-11-19，周期day，再进入核验结果查看摘要卡片和明细表。底部可以展开原始证据。

    $ErrorActionPreference="Stop"; $w="D:\ChatGPT\AStockDataTools\work\market-center-v2b2-20261120"; $py="D:\ChatGPT\AStockDataTools\.venv\Scripts\python.exe"; & $py -u -B (Join-Path $w "ParquetLiveSync\market_center_v2_preview.py") --state-module "D:\ChatGPT\AStockDataTools\ParquetLiveSync" --market-root "D:\stock\AllCycleAStockData"; if($LASTEXITCODE -ne 0){throw "V2B2_UI_FAILED"}

## 下一阶段才允许考虑

首先取得经独立验证并能追溯来源版本的交易日历、股票生命周期和停牌声明，以及受校准证明约束的分钟线真实交易时间格；再构建可靠“应有而未见”的只读差异清单。用户明确确认且后端事务/回滚经验收后，才能单独开放“只补缺失”、隔离重取对比、人工审核修复。当前三个写入选项仍只是设计配置。

本切片不更改正式计划任务、运行器、行情、QMT DAT/H5、Parquet 或财务/复权数据库；PR 在 Windows 合成及小范围真实验收前保持 Draft。
