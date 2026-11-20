# 20:05 可见控制台、运行日志、关机后增量补更界面（2026-11-20 Draft）

> 实施在独立 `feat/market-2005-visible-log-catchup-gui-20261120` 分支，基于 AStockDataTools 的 `ff43f6679fdf0e7ad66a43697359735aa21b3765`。**尚未在用户 Windows 运行新测试或安装新版计划任务；不能宣称电脑上的旧任务已经更新。**

## 对用户现有 2026-11-19 数据的判定

2026-11 月八周期页脚检查为 **7/8 存在**，其中 month 月线未出现是合理的闭合策略：只有完整自然月结束且数据校验通过才会生成新月线。1min、5/15/30/60min、day、week 七个当前月文件有规范八列与可用的行组时间统计。此结论不代表 2011—2026 历史每只股票无缺口。

财务源 5,224 只冻结沪深 A 股中 5,223 有核心四表的历史非空回执；`688259.SH` 的 Top10Holder 于 2026Q3 查询窗口 UTF8 解码失败。44 只历史冲突未认证；`PerShare` 全部显示空源。20:05 的历史日常任务虽有四个阶段执行 exit0，但 11-19 的 finance/adjustments 轮转仍为 PARTIAL。正式 PIT 或复权策略回测不可开放。

## 代码修改

1. `install-schedule.ps1` 的**同一个** `AStockDataTools-ParquetLiveSync` 计划任务仍固定每天北京时间20:05，仍要求交互 Windows 用户登录 QMT；改为 PowerShell **WindowStyle Normal**，运行时可见实时控制台，不再隐藏；不使用 `-NoExit` 避免任务永远不退出。仍有 `StartWhenAvailable` 与 `IgnoreNew`。
2. `scheduled-afternoon-update.ps1` 原四段执行器继续逐行打印，原有 `work/afternoon-*.log`、分阶段 `afternoon-*-EIGHT_PERIODS|...log`、`last-afternoon-unified.json`、`verification-*.json` 均保留。新增 Win32 `Local\AStockDataTools2005AllStages` 命名 mutex 保证手动/计划不会交叉写入。发生 PARTIAL 验证时，结果已落盘且通知已尝试后返回非零，不再把部分质量通过当成完整成功。
3. 新 `run-market-catchup.ps1` 完全复用现有 `update-market.ps1`：从物理已提交 `market_update/commits.json` 的最新 1min 日期起，在北京时间截至日内最多每批 30 个日历日推进；一次运行最多12批（360日），超限保守失败。QMT、官方TDX、独立分钟抽检、分钟聚合、周/月闭合都由**原更新器**检查。没有新交易日时依据原更新器 QMT 交易日历的 fail-closed 返回判断正常 no-op；不人为写入日历占位。
4. **安全的 20:05 前模式：** 当天北京20:05之前，如果用户手动补更或 Windows `StartWhenAvailable` 补跑昨日任务，脚本只运行历史八周期行情，不请求今天的财务、板块或除权，并将结果写在 `work/last-precutoff-market-only.json`，不覆盖上一次正式四阶段的 `last-afternoon-unified.json`。到20:05后才允许四阶段完整增量。
5. 新 `market_update_dashboard.py` 使用标准库 tkinter，显示最近已提交的 1min 日期、本轮安全截止日期、财务轮转游标与待审数、上次四阶段及历史单独补更状态、执行/数据校验/跨源验证、原始私有日志，可打开日志目录和日志文件。点击补更会弹确认框，并在独立 PowerShell 控制台调用同一 runner；GUI 不自己解析行情文件、不写 QMT DAT、不另装计划任务。可选择本次财务轮转上限 200/500/1000/5000/10000，除权轮转上限80/200/500/1000；**数值只表示本次最多处理多少只，不代表所有股票数据已完全验收**。仍只处理 API 所能真实返回的数据。
6. 可双击 `ParquetLiveSync/start-market-update-dashboard.cmd` 打开 GUI，或从 PowerShell 运行 `python -B ParquetLiveSync/market_update_dashboard.py`。

### 安全事实

- **只有安装/重新注册本地计划任务后才会出现可见控制台。** GitHub PR 本身不修改 Windows 任务计划程序。
- 只有用户主动确认 GUI 更新时才会写生产月度 Parquet。普通查看状态/日志为只读；GUI 不能在 detached worktree 运行生产写入。
- 关机、退出 Windows 登录会话、QMT 不可用期间，仍无法采集。重新开机且登录后由 `StartWhenAvailable` 有机会补跑，但同时必须满足 QMT 数据源可用；不能保证已失去历史可访问窗口的第三方数据。
- 与独立财务表 SOURCE_HISTORY_CONFLICT、QMT UTF-8 异常有关的隔离不会因为点击补更而被抹去。全历史原始缺口、复权因子语义和财务 PIT 需要专门的审计门禁。
- 若一次运行分批后部分阶段失败，之前已提交的月份/证券记录继续保留，失败环节的日志和回执保持，重复点击会从成功游标续跑而不是强行覆盖。
- 预计接入版本必须包含全部新脚本；不能从检测用 worktree 的路径注册任务，必须在 canonical `D:\ChatGPT\AStockDataTools` 工作树完成源代码集成后再安装。

## Windows：独立代码验收（目前是待执行）

**1. 获取草稿分支到独立 worktree（不动当前主项目）**：

```powershell
$ErrorActionPreference="Stop"; $r="D:\ChatGPT\AStockDataTools"; $w=Join-Path $r "work\market2005-gui-audit-20261120"; Set-Location -LiteralPath $r; git -c http.sslBackend=schannel -c http.version=HTTP/1.1 fetch origin feat/market-2005-visible-log-catchup-gui-20261120; if($LASTEXITCODE -ne 0){throw "Fetch failed"}; if(Test-Path -LiteralPath $w){throw "Existing audit worktree: do not overwrite"}; git worktree add --detach $w FETCH_HEAD; if($LASTEXITCODE -ne 0){throw "Worktree creation failed"}; git -C $w rev-parse HEAD
```

**2. 只运行合成测试与 AST/mock，不读取 QMT 或修改真实 Task Scheduler**：

```powershell
$ErrorActionPreference="Stop"; $w="D:\ChatGPT\AStockDataTools\work\market2005-gui-audit-20261120"; $py="D:\ChatGPT\AStockDataTools\.venv\Scripts\python.exe"; $env:PYTHONPATH=Join-Path $w "ParquetLiveSync"; & $py -u -B -m unittest discover -s (Join-Path $w "ParquetLiveSync\tests") -p "test_market_update_dashboard.py" -v; if($LASTEXITCODE -ne 0){throw "GUI synthetic tests failed"}; foreach($name in @("test_visible_catchup_safety_mock.ps1","test_install_schedule_mock.ps1","test_native_stderr_stage_mock.ps1")){ & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $w ("ParquetLiveSync\tests\"+$name)); if($LASTEXITCODE -ne 0){throw ("PowerShell offline mock failed: "+$name)} }; Write-Host "VISIBLE_CATCHUP_GUI_OFFLINE_TESTS_COMPLETE"
```

**3. 从正式仓库观察正在使用的分支与本机任务，不作写入**：

```powershell
$ErrorActionPreference="Stop"; $r="D:\ChatGPT\AStockDataTools"; git -C $r status --short; git -C $r branch --show-current; git -C $r rev-parse HEAD; & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $r "ParquetLiveSync\install-schedule.ps1") -Action Status
```

请先提供以上三个步骤结果。真实上线时应由维护者把已验收的变更按既有分支合并流程整合到正式工作树，并再次确认安装路径、状态和未提交的文件。**不要在完成此确认前直接从 detached worktree 执行 `-Action Install` 或 `-Apply`。**

## 本机正式安装（只有源代码通过验收并已整合到 canonical 后）

重新注册**原任务名**，不新增第二个任务，打印真实 20:05/电脑本机转换时刻与交互登录账户：

```powershell
$ErrorActionPreference="Stop"; $r="D:\ChatGPT\AStockDataTools"; Set-Location -LiteralPath $r; & powershell.exe -NoProfile -ExecutionPolicy Bypass -File "ParquetLiveSync\install-schedule.ps1" -Action Install; if($LASTEXITCODE -ne 0){throw "Visible scheduled task installation failed"}; & powershell.exe -NoProfile -ExecutionPolicy Bypass -File "ParquetLiveSync\install-schedule.ps1" -Action Status
```

打开 GUI：

```powershell
$ErrorActionPreference="Stop"; $r="D:\ChatGPT\AStockDataTools"; $py=Join-Path $r ".venv\Scripts\python.exe"; & $py -u -B (Join-Path $r "ParquetLiveSync\market_update_dashboard.py"); if($LASTEXITCODE -ne 0){throw "Market dashboard stopped with error"}
```

## 验收成功的标准

- 只有一个 20:05 中国时间 Task，交互 Principal，`WindowStyle Normal`；没有额外财务计划任务。
- 在登录 Windows 且 QMT 连接正常时，调度触发时出现 PowerShell 控制台实时打印各阶段，退出后日志仍保存在 `ParquetLiveSync/work`。
- UI 可查看历史运行记录和四阶段情况；关机漏跑后用户可以点击一次补更，按账本补齐遗漏的日子；超过 30 日分批，不跳过未验证日期。
- 自动/手动同一时刻只有一个活动写入任务，手动撞上自动返回 `MARKET_2005_ALREADY_RUNNING` 而不是重复执行。
- 20:05 之前不更新当日财务或数据，20:05 后更新仍需通过原来源校验。月线只在自然月完整闭合后发布。
- `SUCCESS/PARTIAL/FAILED`、异常与分阶段日志有据可查，不把`PerShare`空源和财务44条修订隔离宣称全部通过。


## 2026-11-20 QMT 服务断连根因与就绪门禁（新增补丁，Draft）

用户本机实测：11 月 20 日 09:19 的唯一四阶段任务全部退出 1，四阶段真实日志同样报「无法连接xtquant服务」；当日 17:xx 在 Quant 同一登录会话中使用项目 `D:\ChatGPT\AStockDataTools\.venv\Scripts\python.exe` 执行 `xtdata.get_client()` 已连接 `127.0.0.1:58610`，QMT `XtItClient.exe` 当前进程 17:29:57 才启动。历史断连最可能是错过调度后的 QMT 初始化顺序问题；并不能单凭当前启动时间断言上午完全没有 QMT。

**新处理顺序**：进入四阶段前，在原统一运行器（`scheduled-afternoon-update.ps1`）完成现有工作树、原始账本、路径、单实例 mutex 检查和日志启动后，先运行 `qmt_connect_preflight.py`。这个 helper 只在隔离 Python 子进程中执行一次 `xtdata.get_client()`，没有行情、财务、板块、除权下载。每次子进程最多 25 秒；调用脚本最多尝试 6 次，失败两次尝试间等待 10 秒，最多 5 次等待。连接失败时退出码非零，runner 跳过八周期/板块/除权/财务**全部阶段**，发出 `MARKET_2005_QMT_SERVICE_UNAVAILABLE=TRUE`，将 `qmt_preflight_status=QMT_SERVICE_UNAVAILABLE`、`qmt_preflight_attempts=6`、`stage_records={}`、`status=FAILED` 写入本次私有 JSON 回执，并保存 PowerShell transcript 和桌面通知。不会覆盖原始行情或绕过失败的采购源。工作树没有通过预检查、进程无法启动、出错时仍然 FAIL closed。

QMT 已连接时输出 `MARKET_2005_QMT_PREFLIGHT_CONNECTED_ATTEMPT=N`，写入 `qmt_preflight_status=CONNECTED` 后才执行原流程。GUI 展示最新正式四阶段和 20:05 前历史补更的 QMT 就绪状态、尝试次数。**该门禁仅证明此刻 xtquant 客户端建立连接，不等于行情源质量/历史冲突/PIT/复权/全部财务周期通过。** 并非后台持续监测，不会尝试代替用户启动 QMT 或登录券商账户。

### Windows 下一轮验收（继续复用现有 detached 审计 worktree）

**A.** 把旧 `work\market2005-gui-audit-20261120` 的 detached HEAD 安全快进到当前 Draft 分支，不改正式工作树：

```powershell
$ErrorActionPreference="Stop"; $r="D:\ChatGPT\AStockDataTools"; $w=Join-Path $r "work\market2005-gui-audit-20261120"; if(-not(Test-Path -LiteralPath $w -PathType Container)){throw "Test worktree missing"}; if(@(git -C $w status --porcelain).Count -ne 0){throw "Test worktree not clean"}; git -C $r -c http.sslBackend=schannel -c http.version=HTTP/1.1 fetch origin feat/market-2005-visible-log-catchup-gui-20261120; if($LASTEXITCODE -ne 0){throw "Fetch failed"}; $pin=(git -C $r rev-parse FETCH_HEAD).Trim(); git -C $w switch --detach $pin; if($LASTEXITCODE -ne 0){throw "Cannot update detached test worktree"}; git -C $w rev-parse HEAD
```

**B.** 纯离线合成和 PowerShell AST/mock，**不调用真实 QMT、不下载、不注册任务**：

```powershell
$ErrorActionPreference="Stop"; $w="D:\ChatGPT\AStockDataTools\work\market2005-gui-audit-20261120"; $py="D:\ChatGPT\AStockDataTools\.venv\Scripts\python.exe"; $env:PYTHONPATH=Join-Path $w "ParquetLiveSync"; foreach($p in @("test_qmt_connect_preflight.py","test_market_update_dashboard.py")){& $py -u -B -m unittest discover -s (Join-Path $w "ParquetLiveSync\tests") -p $p -v; if($LASTEXITCODE -ne 0){throw "Python offline tests failed: $p"}}; foreach($p in @("test_qmt_service_gate_contract_mock.ps1","test_visible_catchup_safety_mock.ps1","test_install_schedule_mock.ps1","test_native_stderr_stage_mock.ps1")){& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $w ("ParquetLiveSync\tests\"+$p)); if($LASTEXITCODE -ne 0){throw "PowerShell offline tests failed: $p"}}; Write-Host "QMT_SERVICE_PREFLIGHT_OFFLINE_GATE_COMPLETE"
```

**C.** 只有 B 全通过时，可单独测试当前本地 QMT 连通性：只尝试 `xtdata.get_client()`，没有实际数据更新，也不受 20:05 盘后更新门禁限制：

```powershell
$ErrorActionPreference="Stop"; $w="D:\ChatGPT\AStockDataTools\work\market2005-gui-audit-20261120"; $py="D:\ChatGPT\AStockDataTools\.venv\Scripts\python.exe"; & $py -u -B (Join-Path $w "ParquetLiveSync\qmt_connect_preflight.py"); if($LASTEXITCODE -ne 0){throw "QMT service not ready; check QMT login and client service"}
```

只有 Windows 结果确认后才允许考虑把已审核代码以原有分支流程整合到真正的 `D:\ChatGPT\AStockDataTools` canonical 工作树、重新安装**已有唯一任务**。Detached worktree 绝不能使用 `-Apply` 或 `-Action Install`。既有旧任务此刻仍为 `-WindowStyle Hidden`；测试/代码提交不会自动调整本机任务动作。
