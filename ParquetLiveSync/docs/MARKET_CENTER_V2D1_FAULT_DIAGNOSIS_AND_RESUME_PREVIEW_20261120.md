# V2-D1：首页智能故障诊断与财务续跑前安全门禁

2026-11-20。开发继承用户已在 Windows 完成的 V2-C 财务专用断连补丁合成测试（100/100），本阶段仍是独立 Draft，不修改 20:05 唯一计划任务、正式更新脚本、行情/财务 Parquet 与旧版 canonical 工作树。

## 需求

更新中心首页出错时应明确类型、原因、影响范围和可用处理路线，并提供相应快捷入口。只有可证实的临时故障才可能支持有限重试；行情重新下载必须隔离并比对，不能把旧数据覆盖当作通用修复。

## 本轮功能

- market_center_v2_faults.py：通过显式 canonical ParquetLiveSync 目录，只读最新工作回执、本次精确命名的阶段日志和财务私有进度文件。最多 192 KiB 阶段日志尾段；回执与进度各 2 MiB。拒绝日志跨出工作根目录、时间戳不属于本轮、符号链接的重定向输入；SHA256记录两个状态文件读取时的字节完整性，不认证其来源真实性。
- market_center_v2_fault_cli.py：只有显式 --state-module 和 --explicit-readonly 才输出结构化错误诊断。无进程启动、下载、QMT调用、任何文件写入。
- market_center_v2_preview.py：首页新增错误诊断提示、错误说明及财务续跑门禁简述。单击可查看本次财务日志、进入逐条错误类型表、复制只读续跑预览。新增独立故障诊断页，可选择每个阶段的同次日志查看。新版首页可垂直滚动。实际一键重试按钮始终禁用。
- tests/test_market_center_v2_faults.py：纯合成错误、同次日志、财务检查点、进度文件等回归，覆盖错误分类、路径安全、日期变化、游标变化、结果不可执行。

## 2026-11-20 的本轮错误预期

财务阶段 exit=1，在 000755.SZ 成功保存检查点之后，股票 000756.SZ、000757.SZ、000758.SZ、000759.SZ、000761.SZ 的批次遇到 xtquant.download_financial_data2 / get_client / connect 的连接不可用异常。预计错误类型 QMT_FINANCE_CONNECTION_LOST，失败批次五只，最后日志检查点 000755.SZ。除权 exit=0、处理80只、next_batch_required=true 是正常轮换批次未结束，应另以 ADJUSTMENTS_ROTATION_PENDING 提示，不计入执行错误。45项 pending 是原有财务待审项目数，不应直接当成今天新增45条错误。

其他识别类别包括：QMT前置连接预检失败、财务文本解码、财务批次超时、历史版本冲突、跨源抽样价格不一致、阶段数据质量需要复核、无法识别的执行失败。只有证据匹配才会显示具体类型；否则标明日志来源不足或需要手工诊断。

## 续跑前门禁

只读续跑预览要求：精确同次财务日志、解析到最后保存检查点和失败股票批次、财务进度中的 daily_date 与本轮日期一致、财务进度实际游标与日志检查点一致、失败批次起始代码严格在持久化游标之后、当天日期不变、避开北京时间19:55至20:20。任何条件缺失则 PREVIEW_BLOCKED；即使全部静态条件吻合，只能得到 PREVIEW_CHECKS_PASSED_EXECUTION_STILL_DISABLED。

因为还没有验证实时QMT连接、唯一执行锁、canonical正式部署的 worker 版本，以及财务历史版本的备份/回滚，所有诊断和预览都保持 allowed_to_execute=false、allowed_to_download=false，且不修改进度。跨越2026-11-20自然日的原任务不能简单用“今日daily”重跑；必须独立设计下个日期的追赶策略，避免重设当天游标和重复下载。

## Windows 验收单行命令

1. 建立新的 detached 工作树（保留此前已验收 V2-C 与财务重试工作树；避免 Git 中文提交输出问题用 quiet 模式）：

    $ErrorActionPreference="Stop"; $r="D:\ChatGPT\AStockDataTools"; $w=Join-Path $r "work\market-center-v2d1-20261120"; if(Test-Path -LiteralPath $w){throw "V2D_TARGET_EXISTS"}; & git -C $r -c http.sslBackend=openssl -c http.version=HTTP/1.1 fetch --quiet origin feat/market-center-v2d-fault-triage-resume-preview-20261120; if($LASTEXITCODE -ne 0){throw "V2D_FETCH_FAILED"}; & git -C $r worktree add --quiet --detach $w FETCH_HEAD; if($LASTEXITCODE -ne 0){throw "V2D_WORKTREE_FAILED"}; & git -C $w rev-parse HEAD

2. 六组完全合成的Windows离线测试（之前100项+本阶段新增22项，精确数量按固定提交计算）：

    $ErrorActionPreference="Stop"; $w="D:\ChatGPT\AStockDataTools\work\market-center-v2d1-20261120"; $py="D:\ChatGPT\AStockDataTools\.venv\Scripts\python.exe"; $env:PYTHONPATH=Join-Path $w "ParquetLiveSync"; foreach($p in @("test_market_center_v2_preview.py","test_market_center_v2_readonly_audit.py","test_market_center_v2_evidence_gate.py","test_market_center_v2_minute_grid.py","test_market_center_v2_finance_connect_retry.py","test_market_center_v2_faults.py")){& $py -u -B -m unittest discover -s (Join-Path $w "ParquetLiveSync\tests") -p $p -v; if($LASTEXITCODE -ne 0){throw "V2D_TEST_FAILED: $p"}}; Write-Host "V2D1_OFFLINE_TESTS_COMPLETE"

3. 真实本次任务只读错误诊断（任何时间，不会接触行情下载、财务写入或QMT服务）：

    $ErrorActionPreference="Stop"; $w="D:\ChatGPT\AStockDataTools\work\market-center-v2d1-20261120"; $py="D:\ChatGPT\AStockDataTools\.venv\Scripts\python.exe"; & $py -u -B (Join-Path $w "ParquetLiveSync\market_center_v2_fault_cli.py") --state-module "D:\ChatGPT\AStockDataTools\ParquetLiveSync" --explicit-readonly; if($LASTEXITCODE -ne 0){throw "V2D1_FAULT_DIAGNOSIS_BLOCKED"}

4. 新版GUI：查看首页错误分类、点击查看故障详情、打开同次财务日志、复制一份执行权限为false的续跑预览：

    $ErrorActionPreference="Stop"; $w="D:\ChatGPT\AStockDataTools\work\market-center-v2d1-20261120"; $py="D:\ChatGPT\AStockDataTools\.venv\Scripts\python.exe"; & $py -u -B (Join-Path $w "ParquetLiveSync\market_center_v2_preview.py") --state-module "D:\ChatGPT\AStockDataTools\ParquetLiveSync" --market-root "D:\stock\AllCycleAStockData"; if($LASTEXITCODE -ne 0){throw "V2D1_UI_FAILED"}

## V2-D2 后续

先取得真实Windows合成测试、只读诊断CLI、GUI用户验收。在独立更严格的阶段设计“当前QMT连接检查 + 受同名写锁与版本SHA保护的仅财务批次续跑”，明确审批并提供事务备份；部署到canonical生产版本之前不得实际下载。对缺失行情的自动补写与冲突覆盖要另行经过交易日历/来源核验，并保留隔离区比对和用户审核。
