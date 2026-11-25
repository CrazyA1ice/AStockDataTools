# 20:05 行情完成后企微个人报告 — 2026-11-25 Draft

## 验证状态与边界

2026-11-25 用户临时监视器首次真实发送返回 WECOM_API_ACK_NOT_DEVICE_PROOF、PROVIDER_CODE=0、WECOM_REMOTE_EXIT=0：这是企微 API 接受，不证明手机实收。旧监视器依赖人工 SSH 密码；本草稿新增独立无人值守候选，**尚未部署，没有再次向企微发送**。

本分支只新增文件，不覆盖 scheduled-afternoon-update.ps1、market_daily_verification.py、install-schedule.ps1、QMT、PR #243 或新闻系统。新 Windows 客户端拒绝 2026-11-25 及此前日期的再次发送；首次切换日为 2026-11-26。

## 新增文件

- market_wecom_report.py：Windows 只读 work/last-afternoon-unified.json，二次 SHA 稳定检查，要求 format=qmt_daily_single_trigger_v3、invocation=Scheduled、run_scope=ALL_FOUR_SECTIONS、history_only=false、北京时间20:05后；Windows 任务 Ready、LastRunTime 与当次回执启动不超过30分钟。以执行状态 SUCCESS/PARTIAL/FAILED 和独立质量 PARTIAL/UNVERIFIED 如实生成个人报告。先持久化本地 O_EXCL 日期意图，再进行一次性 SSH，超时不自动重发。preview 不发送，once/watch 需要 --approve-self-send。
- astock_market_wecom_server_once.py：Ubuntu 只读既有 owner-only 0600 的单人成员应用配置，gettoken 和 agent/get 验证可见成员；仅向本人应用发送，不向群组或新闻账本发送。在 POST 前创建服务器侧 O_EXCL UNKNOWN；API errcode=0 且无 invaliduser/unlicenseduser 等部分错误才报告 API_ACK_NOT_DEVICE_PROOF（非设备证明）；网络失败不重试。支持 {"mode":"preflight"} 无网络无发送。
- run-market-wecom-monitor.ps1：独立 Windows 监视器，将工作日志写入忽略的 work/wecom-report-monitor。
- install-market-wecom-schedule.ps1：默认 -Action Status 只读；仅在 -Action Install -ApproveDailySelfSend 且 SSH 强制命令预检通过后注册新的 AStockDataTools-WeCom-Report，20:10北京时间启动、最长8小时、不覆写已有新任务，**不改**原 AStockDataTools-ParquetLiveSync。
- tests/test_market_wecom_report_offline.py、tests/test_astock_market_wecom_server_once_offline.py：纯离线单测，无网络、无QMT、无Windows计划任务修改。

## 专用受限 SSH

新组件禁止密码回退，使用 Windows ~/.ssh/astock-market-wecom-only 的独立 ED25519 私钥。Ubuntu ~/.ssh/authorized_keys 对应公钥必须附带：

restrict,command="python3 /home/ubuntu/.local/bin/astock-market-wecom-once.py" ssh-ed25519 <公钥主体> astock-wecom-only

必须先通过已认证的密码 SSH 将本分支 astock_market_wecom_server_once.py 复制至 /home/ubuntu/.local/bin/astock-market-wecom-once.py，文件 owner0600，父目录0700，核对 SHA；随后**附加**公钥条目，绝不能覆盖原 authorized_keys。SSH BatchMode=yes、StrictHostKeyChecking=yes、ClearAllForwardings=yes。安装器故意请求 id -un 同时传 {"mode":"preflight"}；**只有服务器强制命令真正执行了新 sender，才会仅输出 WECOM_MARKET_PREFLIGHT_OK**。如果输出 ubuntu、要求密码或任何其它内容，就拒绝安装。勿将私钥或企业微信 Secret/Token 粘贴到聊天或 GitHub。

## Windows 只读隔离验收（一整行，不依赖压缩包）

$ErrorActionPreference='Stop';$r='D:\ChatGPT\AStockDataTools';$w=Join-Path $r 'work\market-wecom-report-audit-20261125';if(Test-Path -LiteralPath $w){throw 'AUDIT_WORKTREE_EXISTS_NO_OVERWRITE'};git -C $r -c http.sslBackend=schannel -c http.version=HTTP/1.1 fetch origin feat/market-wecom-receipt-report-once-20261125;if($LASTEXITCODE -ne 0){throw 'FETCH_FAILED'};git -C $r worktree add --detach $w FETCH_HEAD;if($LASTEXITCODE -ne 0){throw 'WORKTREE_FAILED'};$py=Join-Path $r '.venv\Scripts\python.exe';if(!(Test-Path $py)){throw 'PYTHON_MISSING'};foreach($f in @('test_market_wecom_report_offline.py','test_astock_market_wecom_server_once_offline.py')){& $py -B -m unittest discover -s (Join-Path $w 'ParquetLiveSync\tests') -p $f -v;if($LASTEXITCODE -ne 0){throw ('OFFLINE_TEST_FAILED_'+$f)}};foreach($f in @('run-market-wecom-monitor.ps1','install-market-wecom-schedule.ps1')){$tokens=$null;$errors=$null;[void][System.Management.Automation.Language.Parser]::ParseFile((Join-Path $w ('ParquetLiveSync\'+$f)),[ref]$tokens,[ref]$errors);if(@($errors).Count -ne 0){throw ('PS_SYNTAX_FAILED_'+$f)}};Write-Host 'MARKET_WECOM_OFFLINE_TEST_AND_AST_PASS_NO_SEND'

以上是**隔离脱离工作树**测试，不得从测试 worktree 注册 Windows 任务或执行 QMT。先核验固定 Git SHA、源文件 Git Blob SHA 和 Windows AST，再把上述四个**新增**生产脚本分别无覆盖拷入 canonical D:\ChatGPT\AStockDataTools\ParquetLiveSync。服务器 sender、专用公钥、无网络强制命令预检全部完成后，才可在 canonical 使用安装器 -Action Install -ApproveDailySelfSend，核对原 20:05 任务定义未改变。

## 未完成的现场验收

用户 Windows AST/单测、Ubuntu sender 安装、受限 SSH、公钥注册、新任务安装、11月26日后首次自动跨机推送、手机端实收均**尚未执行**。数据质量待审和跨源 UNVERIFIED 不因通知发送成功而被清除。