# V2-B 历史数据更新策略与只读核验 · 2026-11-20

用户确认：已有日期必须允许重新处理，不能一概禁止；上次任务 FAILED 与已有行情最新已提交日期应分开展示；保留同一组日期、多股票、来源自动展示、不修改唯一 20:05 任务。

## 1. 三种历史处理方式

| 用户选择 | 目标行为 | 目前实际功能 |
|---|---|---|
| 只补缺失数据（默认） | 先查股日周期缺口，已有合格记录跳过 | 只读核验已接入；真正缺失写入尚未开放 |
| 重新获取并核对差异 | 同范围重新获取到隔离区，与旧数据对比、输出差异 | 仅保留方案，未实现重新下载 |
| 审核后修复异常数据 | SHA/原文件备份、审核和可回滚的定向修复 | 仅保留方案，未开放任何覆盖 |

所有写入操作仍为 allowed_to_execute=false。切换更新/核验模式不重置日期、股票及历史处理选项。最新已提交时间只代表账本最远日，不证明每只股票每个周期都有记录；若历史区间有交叉，显示「允许核验，更新须选择处理策略」，而不是一律禁止重新更新。

原更新器从已提交最新日之后续跑；相同来源已安装可跳过，交叉重叠日期及 SHA 不符拒绝盲目覆盖；其它财务、板块、除权有各自隔离规则，不能盲目套用行情逻辑。唯一原 20:05 运行器的 Windows Local\AStockDataTools2005AllStages mutex 与本 V2-B 历史只读 CLI 采用同名锁，任务运行期间拒绝读取，不能绕过并发保护。

## 2. 现在可执行的功能：有界物理行情只读核验

新增 market_center_v2_readonly_audit.py、market_center_v2_audit_cli.py，GUI 新增「核验结果」页及历史只读核验按钮。此功能不下载、不查询 QMT、不写市场文件或财务数据库。所有证据只在界面内或 CLI stdout 展示，不自动创建报告文件。

仅接受用户显式指定的本机 AllCycleAStockData 目录；可核验 1min、5min、15min、30min、60min、day、week、month 八周期的已存在 Parquet，CLI 可指定一个或多个周期，GUI 首版一次只选一个周期。日期上限冻结为 2026-11-19；每次最多 20 只指定后缀股票、31 个自然日、32 个物理分区、160 个行组、250万候选行，单行组不大于256000行；如果预算不足，直接拒绝并要求缩小范围。无符号链接，存在相同年年度/月度 Parquet 重叠则拒绝。

只读核验的输出包括每只股票的时间戳标签日行数、重复股票时间戳、OHLC上下界、非有限值、负成交量/金额以及分钟标准根数偏差。仅是物理证据观察；没有接入官方交易日历、上市/停牌、复权因子语义、股本/财务 PIT、完整跨源认证。特别注意：没有记录 ≠ 已确认应有而缺失；周/月时间戳标签不是完整的交易日证据；月线未闭合时缺文件不能被误认为错误。源文件的大小/mtime 在读取前后检查，但尚不构成不可变版本快照。财务 44 项历史冲突及 688259.SH 的股东表异常继续隔离。

## 3. Windows PowerShell 验收（每段一行）

**检出独立工作树：**

    $ErrorActionPreference="Stop"; $r="D:\ChatGPT\AStockDataTools"; $w=Join-Path $r "work\market-center-v2b-20261120"; Set-Location -LiteralPath $r; git -c http.sslBackend=schannel -c http.version=HTTP/1.1 fetch origin feat/market-center-v2b-readonly-history-overlap-20261120; if($LASTEXITCODE -ne 0){throw "Fetch failed"}; if(Test-Path -LiteralPath $w){throw "Test worktree exists; do not overwrite"}; git worktree add --detach $w FETCH_HEAD; if($LASTEXITCODE -ne 0){throw "Worktree failed"}; git -C $w rev-parse HEAD

**两套纯合成测试，无 QMT、无生产数据写入：**

    $ErrorActionPreference="Stop"; $w="D:\ChatGPT\AStockDataTools\work\market-center-v2b-20261120"; $py="D:\ChatGPT\AStockDataTools\.venv\Scripts\python.exe"; $env:PYTHONPATH=Join-Path $w "ParquetLiveSync"; foreach($p in @("test_market_center_v2_preview.py","test_market_center_v2_readonly_audit.py")){& $py -u -B -m unittest discover -s (Join-Path $w "ParquetLiveSync\tests") -p $p -v; if($LASTEXITCODE -ne 0){throw "V2-B tests failed: $p"}}; Write-Host "MARKET_CENTER_V2B_OFFLINE_TESTS_COMPLETE"

**全部通过后，真实文件单只、单日、单周期只读检查：**

    $ErrorActionPreference="Stop"; $w="D:\ChatGPT\AStockDataTools\work\market-center-v2b-20261120"; $py="D:\ChatGPT\AStockDataTools\.venv\Scripts\python.exe"; & $py -u -B (Join-Path $w "ParquetLiveSync\market_center_v2_audit_cli.py") --market-root "D:\stock\AllCycleAStockData" --start 2026-11-19 --end 2026-11-19 --symbols 000001.SZ --period day --explicit-readonly; if($LASTEXITCODE -ne 0){throw "V2-B readonly historical audit blocked"}

**打开 V2-B 只读 GUI：**

    $ErrorActionPreference="Stop"; $w="D:\ChatGPT\AStockDataTools\work\market-center-v2b-20261120"; $py="D:\ChatGPT\AStockDataTools\.venv\Scripts\python.exe"; & $py -u -B (Join-Path $w "ParquetLiveSync\market_center_v2_preview.py") --state-module "D:\ChatGPT\AStockDataTools\ParquetLiveSync" --market-root "D:\stock\AllCycleAStockData"; if($LASTEXITCODE -ne 0){throw "V2-B GUI failed"}

GUI 使用：选择「数据核验」+「指定股票」+只勾选「八周期行情」，共同时间范围选 2026-11-19 至 2026-11-19，核验周期选 day，点击「开始历史行情只读核验」，查看新增「核验结果」页。超限/任务占用/不支持的其它模块明确阻断；不会偷偷改为全市场更新。

## 4. 下一阶段才允许实现

需另行以可信股票池、QMT交易日历、上市/停牌有效期和逐股分钟时间格证明应有且确实缺失；再做严格事务式只补缺失、重新下载差异比对、人工审核后可回滚修复。代码合入正式生产前必须经过 Windows 真实验收。此 PR 保持 Draft，未修改现有 20:05 计划任务或原 dashboard。
