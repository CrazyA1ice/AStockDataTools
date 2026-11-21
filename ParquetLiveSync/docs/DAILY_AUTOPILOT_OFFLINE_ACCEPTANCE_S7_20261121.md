# Daily Autopilot S7：一次性离线集中验收门禁

用户要求停止按个股、按阶段每天复制复杂命令。S1–S6已开发的功能尚未完整完成Windows验收，尤其S4 PowerShell语法缺陷已修复、S6真实Arrow/Parquet沙盒尚未实际运行。S7首先建设一个**只在固定提交的独立Git detached worktree内运行**的离线验收入口，不继续堆砌新功能或开放正式财务入库。

## `market_autopilot_offline_acceptance.py`
CLI参数仅为 `--expected-head <固定40位SHA>`、`--explicit-offline-acceptance`、可选 `--full-regression`；没有 `--root`、`--apply`、QMT下载、定时更新或数据库写入参数。必须同时满足：
- 当前目录名是 `ParquetLiveSync`，父级是Git worktree，其上层目录名是 `work`，`.git` 必须为非符号链接的**文件**（主仓库`.git`目录拒绝）；Git HEAD等于用户固定SHA，而且HEAD处于detached，不允许从可变分支直接跑。
- 8个S1–S6 Python模块 + 8套对应的合成测试源文件都存在、非链接且体积有界；逐个用 `ast.parse` 做纯语法检查，不产生pyc。
- 在Windows使用内置 PowerShell Parser AST 验证 `run-scoped-qmt-finance-cache.ps1` 的完整语法，确保旧S4截断条件不会漏过。Windows语法检查未通过、或者在Linux被跳过，都不能返回绿色验收状态。
- 按固定白名单依次执行8组 `test_market_center_*.py` 纯合成/GUI/沙盒测试；首组失败立即停止并输出限制长度的错误尾部，避免长日志淹没用户。可选 `--full-regression` 在专项全部通过后再运行既有 `test_market_center*.py` 回归，以及原操作面板的 `test_market_update_dashboard.py` 回归（此前 Finance P5单独通过351项，但S1–S6新增测试尚未验收）。
- `PYTHONDONTWRITEBYTECODE=1` + `python -B`，测试夹具可能写OS临时目录，但验收器不读写正式行情数据、财务Parquet/H5、QMT状态、进度账本、任何生产调度。进程返回JSON：明确PASS/FAILED、失败模块、exit、有限日志尾段、实际Windows AST结果、固定HEAD、`approved_for_production=false`。

## 此阶段不是正式部署
注意：验收器并非操作系统级网络隔离容器；它只启动受审查的有限测试白名单，**没有发起真实QMT下载的代码路径**。若追加的测试以后改变，仍需代码审查；不能仅凭标记OFFLINE就宣称操作系统阻止了一切外部访问。针对真实财务写入仍需独立备份、幂等事务日志、锁、故障恢复以及来源多源核验。

## 本轮验收状态
S7新增12项纯合成验收器测试；原预计458项命名回归，加上本轮预计470项，实际运行数量以Windows输出为准。本次只完成代码提交和GitHub静态检查，**没有在用户Windows运行，也不能在缺pyarrow的当前本地容器执行S6沙盒**。旧正式20:05计划任务、主仓库、财务旧快照、进度游标和pending均保持不变。全部仍为Draft、不使用GitHub Actions。

## 一次性验收的使用方式
在完成代码检查并确定固定Git SHA后，由维护者在 `D:\ChatGPT\AStockDataTools\work\autopilot-s7-review` 创建detached工作树，调用其 `ParquetLiveSync\market_autopilot_offline_acceptance.py`，传入与该工作树HEAD相同的**固定SHA**。可附带 `--full-regression`，一个入口同时完成Python AST、PowerShell AST、8组专项合成测试及完整回归。任何失败均阻止下一步正式入库和上线。