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
## S7.1（2026-11-22）首次Windows验收的超时修复
用户在固定 SHA `b4606bc398f9123161fdd85f0ebef463dfd7ea83` 的 detached worktree 中执行一次性验收：Git HEAD匹配、Python AST 16/16、PowerShell AST PASS，**第一组 `test_market_center_autopilot_shadow.py` 在180秒超时**，没有进入其他套件。此结果只能证明旧子进程挂起/超时，**不能证明任意测试失败或生产市场数据损坏**；旧验收器在 `subprocess.TimeoutExpired` 时丢弃了部分 stdout/stderr，所以无法进一步定位。

修复：8个已核实包含 `if __name__ == '__main__': unittest.main()` 的专项测试文件，改为 `python -u -B <绝对测试文件> -v` 直接执行，避免额外 `unittest discover` 扫描；`-u -v` 让具体测试方法名在运行前输出到合并日志。首组纯合成S1改为45秒硬超时，其他含GUI/真实Parquet沙盒组保持180秒。即使超时也保留最多4000字符的子进程输出尾段与 `timeout_phase`（`STARTUP_OR_IMPORT`或`TEST_IN_PROGRESS_OR_TEARDOWN`），而非返回空白报错。依旧首组失败即停、保持 `approved_for_production=false`，不会跳过或改成PASS。

新增4项纯合成验收器测试覆盖：直接逐文件verbose调用、超时部分输出保留、无输出识别为启动/导入卡住、首组超时立即停止其余套件。既有固定SHA和detached审核检查、Windows PowerShell AST、可选完整市场中心+原操作面板回归保持不变。**这是提高诊断准确度的修复，不代表已经查清用户Windows上挂起的最终原因，更不代表S1—S6已通过**。

重新验收必须使用新的固定 SHA 和全新 detached worktree 目录（例如 `work/autopilot-s7r-review`），不修改旧 `work/autopilot-s7-review` 或正式主仓库；不执行任何真实QMT下载或生产入库。若首组再次超时，请查看 JSON 的 `timeout_phase` 和 `output_tail`，一次性定位具体停点，不再重复盲目加大超时。

## S7.2（2026-11-22）Windows 回执定位与验收器自测修复

用户固定提交 `c2ccdda3453d2347ef68a1421fe3350c0b5b5d1f` 的二次真实 Windows 验收记录：Python AST 16/16、PowerShell AST PASS；前七组单独执行的测试共 **107/107 PASS**（15+9+19+9+17+22+16），其中沙盒真实 Parquet 文件写入和事务故障注入组16项通过；S7 自测组16项全部在 `setUp` 阶段因同一错误而终止：

`AttributeError: module 'market_autopilot_offline_acceptance' has no attribute 'POWER_SHELL'`

原因是 S7 测试夹具以 `G.POWER_SHELL` 读取 PowerShell 脚本名，而 S7 本体此前用硬编码字符串读取该脚本，没声明这个常量。这是**测试夹具接口失配**，不是 QMT 下载或用户金融数据写入失败。修复在本体内定义 `POWER_SHELL = "run-scoped-qmt-finance-cache.ps1"`，并让实际解析器复用该常量，避免两边未来不一致；追加1项回归测试固定文件名。

**S7.2 代码尚未经过 Windows 实机复测**；新的测试预期S7自测17项，S1–S6已有七组107项通过的结果仅适用于旧提交，不能替代新版本全量回归。正式20:05任务、财务历史、市场数据库、GUI与人工更新脚本保持不变；整个PR仍为Draft，`approved_for_production=false`。

## S7.3（2026-11-22）：截断的验收 JSON 修复

用户固定 SHA `a712a8494fec07e7865085a3b537124479710a2e` 再次运行 Windows 统一验收，报告开头确认 Python AST 16/16、PowerShell AST PASS，前5组 69 项 PASS，第6组返回 `exit=0`；但用户上传内容中的整个 JSON **在第6组的 `output_tail` 字符串中被截断**（长度9747字符），后续 S6/S7/完整回归结论不可见。虽然 JSON 最前面是 `OFFLINE_ACCEPTANCE_FAILED`，**没有足够证据定位失败套件**，不能假定S7或完整回归已通过。

根因属于报告呈现层：旧验收器给每个已成功的专项和全回归保存1800字符 verbose 测试尾部，重复输出不断累积，导致粘贴的完整结果超过可见文本长度。S7.3 改为：**退出码0时只报告测试数量 `tests_run` 与耗时 `elapsed_seconds`，不输出通过测试的长日志；退出码非零或超时才保留受限的错误上下文**。新增零测试门禁：即使子进程成功退出，若没有标准 unittest 的 `Ran N tests` 证据或 N=0，也返回 `UNITTEST_NO_TESTS_EXECUTED`，避免虚假绿灯。原 Windows AST 门禁、固定Git SHA、detached worktree、首组45秒/其他专项180秒/回归600秒上限均不变。

新增3项验收器本身的合成测试，验证数百条成功测试输出压缩成摘要、测试失败的 traceback 保留、以及零测试不能作为PASS。原有单测按新的失败关闭逻辑同步修正模拟回执。只有在Windows新固定SHA复测后才能知道最早的真实失败项，**不允许因此触发生产财务入库或更改正式20:05任务**。

## S7.4（2026-11-22）：完整回归600秒超时与Tkinter隔离

用户用固定SHA `1e7d3605f436abb901d5dd5d87ed9257ebd60b34` 完成第三次Windows离线验收：8组专项**127/127项全部通过**（15+9+19+9+17+22+16+20），Python AST 16/16，PowerShell AST PASS。唯一阻断是 `FULL_MARKET_CENTER_REGRESSION` 单一`unittest discover -p test_market_center*.py`进程运行600秒超时。其部分输出反复出现 `ttk::ThemeChanged` 回调访问已销毁Tk应用的异常，另见 `>>>` 提示符；现有日志无法确定具体的测试模块，不应把原因直接断言为Tkinter死锁或QMT异常。

经对 PR 固定代码树清点，当前共有**31个**`test_market_center*.py`回归文件。完整回归已改为逐个对每个匹配文件启动单独的`python -u -B -m unittest discover -s tests -p <完整文件名> -v`进程，即使该测试文件没有`unittest.main()`也能被发现；每个文件最多90秒、整批回归累计最多600秒。它保留**全部匹配文件**，不会通过跳过疑难测试换取绿灯。每个文件的退出码、实际运行测试数量、耗时及失败日志单独记录；第一个失败立刻停，能明确定位失败文件，而不是整个套件空等600秒。完整市场中心测试文件全部通过后，再独立运行原操作面板`test_market_update_dashboard.py`。

新增4项验收器自身合成测试（含零退出码但Tk回调报错也拒绝绿灯）：完整回归包含新增的历史Tk模块、逐文件独立执行；指定失败文件准确定位且不运行之后的文件；`Ran 0 tests` 不能误判为PASS。原S7验收器20项变为24项（专项总数预期由127提升到131，但**须以真实Windows回归为准**）。

安全门禁不变：固定SHA detached工作树，原生Windows PowerShell AST、无真实QMT下载、无生产Parquet/H5写入。此次只修改统一验收器、自测及说明文档；代码仅做静态比对，未在本次会话中获得新Windows运行回执。尚不能宣称完整回归通过，也不能开启正式入库。


## S7.5（2026-11-22）：600秒与90秒超时的最终交互提示符根因

用户在固定SHA `0dede27d2411db1202f05caf6655b7e8b67ca5c1` 的Windows detached工作树完成8组专项测试，**131/131项PASS**（15+9+19+9+17+22+16+24），Python AST 16/16、PowerShell AST PASS。完整回归改为逐文件隔离运行后，首个文件 `test_market_center_autopilot_offline_acceptance.py` **24项在2.681秒内全部OK**，但测试进程随后输出 `>>> ` 并停在90秒超时；原操作面板回归未运行。

经复核发现根因不在 Tkinter 或QMT，而在S7验收器自身的`execute()`将`PYTHONINSPECT="0"`放进所有子进程环境。**Python 的PYTHONINSPECT环境变量是设置即启用交互检查模式（非空字符串"0"也算启用），使`python -m unittest discover`完成后进入REPL，并从继承的控制台stdin等待用户输入。**这解释了为什么文本中已包含 `Ran 24 tests ... OK`，却仍有尾随 `>>> ` 并被验收器超时终止。

S7.5修正：移除子进程环境中的`PYTHONINSPECT`（包括父环境继承的同名变量），同时移除`PYTHONSTARTUP`；所有验证子进程强制`stdin=subprocess.DEVNULL`，避免未来出现无人值守REPL等待。即使Python子进程退出码0且有有效unittest测试计数，只要输出中出现独立行首`>>> `交互提示符，也判定`PYTHON_INTERACTIVE_PROMPT_DETECTED`并保留诊断，不能绿灯。固定Git SHA、Windows AST、测试集合、逐文件回归的90秒单文件/600秒总预算、以及`approved_for_production=false`门禁均不变。

S7验收器自测从24增加至**27项**，新增：继承环境`PYTHONINSPECT="0"`及`PYTHONSTARTUP`时子进程仍清除它们并禁用stdin；真实独立`python -m unittest discover`合成用例不因继承检查环境卡住；退出码0但输出`>>> `的回执也不得PASS。预计8组专项合计**134项**，但当前仅有旧SHA的131项真实Windows PASS，新SHA尚未在用户Windows重验。

本轮只修改S7验收器、其合成测试和此文档；**没有修改**正式20:05调度、财务导入器、QMT缓存更新、Parquet/H5、真实股票历史、数据更新GUI，仍保持Draft、不部署、不开启正式财务入库。
