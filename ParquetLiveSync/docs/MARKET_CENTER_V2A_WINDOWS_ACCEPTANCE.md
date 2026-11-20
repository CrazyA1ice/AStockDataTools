# V2-A 简洁更新/核验中心：Windows 安全验收（Draft）

来源设计：docs/MARKET_CENTER_V2_DESIGN_BASELINE_20261120.md

## 已开发内容

- 全新只读 V2-A 预览窗口，不覆盖原 market_update_dashboard.py，独立启动脚本 start-market-center-v2-preview.cmd。
- 三页：运行总览、更新/核验共同配置、最新运行日志。首页突出上次真实状态、已提交交易日、安全截止及四阶段；本次净变化在没有受控的前后快照时明确显示无法比较。
- 更新/核验共用一组起止日期、同一个股票范围和数据类型选择；支持多股票批量粘贴、去重、市场后缀验证（SH/SZ/BJ）、最大500只；模式切换不清空输入。
- 数据源从现有项目配置读取（若存在 sources.local.json 优先），按“更新主源”和“已配置抽样交叉源”展示，但不允许选择替代源，也不冒称交叉验证已完成。
- 所有任务预览都返回 allowed_to_execute=false；未接入的任意股票/日期写入、历史段核验一律不能执行。本阶段不连接 QMT、不调用更新器、不注册任务、不写市场数据。
- 可选使用明确指定的 --state-module 来只读观察正式仓库原有 JSON 回执与日志；从独立 worktree 启动时不必复制、移动或上传私有状态。

## Windows 单行验收命令

### 1. 建立独立测试工作树（不更改正式生产分支）

    $ErrorActionPreference="Stop"; $r="D:\ChatGPT\AStockDataTools"; $w=Join-Path $r "work\market-center-v2-ui-20261120"; Set-Location -LiteralPath $r; git -c http.sslBackend=schannel -c http.version=HTTP/1.1 fetch origin feat/market-center-v2-design-and-ui-scaffold-20261120; if($LASTEXITCODE -ne 0){throw "Fetch failed"}; if(Test-Path -LiteralPath $w){throw "UI worktree exists: do not overwrite"}; git worktree add --detach $w FETCH_HEAD; if($LASTEXITCODE -ne 0){throw "Worktree add failed"}; git -C $w rev-parse HEAD

### 2. 先运行纯离线测试

    $ErrorActionPreference="Stop"; $w="D:\ChatGPT\AStockDataTools\work\market-center-v2-ui-20261120"; $py="D:\ChatGPT\AStockDataTools\.venv\Scripts\python.exe"; $env:PYTHONPATH=Join-Path $w "ParquetLiveSync"; & $py -u -B -m unittest discover -s (Join-Path $w "ParquetLiveSync\tests") -p "test_market_center_v2_preview.py" -v; if($LASTEXITCODE -ne 0){throw "V2-A model acceptance tests failed"}; Write-Host "MARKET_CENTER_V2A_OFFLINE_ACCEPTED"

### 3. 全部测试通过后，打开**独立预览界面**

可使用你真正的行情工作区作为明确授权的只读状态来源（读取指定 JSON 和本地最后日志，不进行 QMT/Parquet 写入）：

    $ErrorActionPreference="Stop"; $w="D:\ChatGPT\AStockDataTools\work\market-center-v2-ui-20261120"; $py="D:\ChatGPT\AStockDataTools\.venv\Scripts\python.exe"; & $py -u -B (Join-Path $w "ParquetLiveSync\market_center_v2_preview.py") --state-module "D:\ChatGPT\AStockDataTools\ParquetLiveSync"; if($LASTEXITCODE -ne 0){throw "V2-A read-only UI exited with error"}

## 手动验收要点

1. 首页有简洁四张关键状态卡与“本次变化暂无可比证据”的提示，没有长篇 JSON 填满主屏。
2. 切换更新/核验模式后，输入的时间段、股票及勾选模块不变。
3. 输入 000001.SZ, 600519.SH, 000001.SZ，经检查应显示两只；去除 .SZ/.SH 后缀会报错。
4. 尝试结束日期晚于北京时间 20:05 的安全候选上限，必须拒绝预览。
5. 原来源和抽样来源清晰显示，注明“配置”不等于“执行通过”。
6. 任务预览允许复制但永远不提供真的数据提交按钮，不得出现任何新文件写入市场数据。
7. 原正式 GUI、原 20:05 单任务、财务/行情源文件、已有账本均不被触碰。

## 后续 V2-B

在 V2-A 界面通过用户 Windows 验收后，才接入真实历史段 **只读**核验：先提供一个小范围股票/日期的 Parquet 查询预算与时间格核验，形成稳定 JSON 报告接口。更新路径中的定向按股票写入需要全市场账本语义审计与独立授权，不得同核验接口一起自动启用。

状态：代码和离线测试已提交，**还未在用户 Windows 测试 V2-A**；当前使用 Draft PR，不合并 canonical、不影响今晚 20:05 任务。
