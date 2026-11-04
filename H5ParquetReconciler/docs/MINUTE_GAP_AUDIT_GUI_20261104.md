# 分钟数据缺口核对可视化控制台（2026-11-04）

> **独立新工具**。不复用已停用的`minute-private-parquet-gui.py`购买Parquet整日复制按钮；原始`D:\stock\AllCycleAStockData`和`D:\stock\HikyuuData`始终只读。**本文件描述的是已提交、待用户Windows运行新回归测试的代码，不能视为全部实机验收完成。**

## 2026-11-04 Windows首次启动解析失败与修复（等待复验）

用户实际执行首次GUI启动，GitHub快速更新到 `a98a8ee` 已成功，但 `start-minute-gap-audit-gui.ps1` 在Windows PowerShell 5.1解析阶段出现 `TerminatorExpectedAtEndOfString`，错误指向`Start-Process`行，**尚未运行任何Python测试或GUI进程**。仓库文件是无BOM UTF-8，含非ASCII中文单引号提示，Windows PowerShell 5.1可能当作本地ANSI编码读取，导致引号被破坏。原始市场数据及已验私有索引没有任何修改。

修复：
- 将启动`.ps1`脚本中的提示全部替换为**纯ASCII**，从根本规避无BOM UTF-8与本地ANSI兼容问题；中文仍放在Python GUI界面中，其他PowerShell脚本暂不受此次修改影响。
- 加入Python GUI源码AST语法检查与Tkinter/worker真实导入检查，**先在PowerShell普通python.exe中完成，再用pythonw.exe打开GUI**，避免GUI导入异常导致无提示退出。
- `tests/test_minute_gap_audit_gui_worker.py`增加`test_powershell_launcher_is_ascii_for_windows_powershell_51`与`test_python_gui_module_is_syntax_valid_before_pythonw_launch`两项。现在一键启动应运行**7+5+4+4+8=28项**合成测试，而不是原来的26项。
- **新修复已提交GitHub，尚未获得用户Windows复验输出**。如果测试或import预检失败，先查看PowerShell错误并修正，不要跳过测试、重启旧购买数据复制GUI或更改原始行情。

## 一、为什么做这个GUI，而不是继续每月手工跑PS脚本

购买的1分钟、5分钟Parquet是权威来源；H5只有在确定缺失的规范分钟键存在、时标/单位/证券身份通过额外认证时才可能提供补差。之前的整日物化错误导致对01-05—08重复写出632万余购买行情，净H5新增0，旧任务`0625f02019fe`已安全暂停。之后的分钟键/SQLite索引只读流程证明可以在不重写任何购买OHLCVA的情况下精确比较H5。

**最近的用户真实回执**：
- `2026-01-05..07`：1min购买有效3,953,846键，5min 787,488键，两个周期H5整股票日/局部分钟新候选均0，已有私有SQLite索引。
- `2026-01-08..31`：覆盖17个候选工作日，已新建私有SQLite索引
  `purchased-minute-keys-2026-01-08-2026-01-31-deb70305182f.sqlite`，
  1min购源已有22,413,964键、5min 4,464,192键，均**0有效H5新时间键候选**，未生成任何行情文件；1min 4个不完整H5股票日被隔离。已直接确认在完整H5股票日上，1min购买独有的92,733个时间键属于**09:30**，其他时间桶0；这只是键标签核对，不等于行情数值/复权全面认证。
- 目前已完成的是2026年1月的已覆盖交易日**候选时间键审计**，不是2025/26所有月份或全周期生产数据补齐。来源指纹仅文件路径、大小、mtime_ns、inode，**不是SHA级不可变快照**。

## 二、GUI的三个执行层级

| 层级 | 写盘范围 | 功能 |
| --- | --- | --- |
| 预览任务计划 | **不写任何文件** | 选择源目录、起止日期（2025-01-01至2026-10-13、最多367个日历日），显示哪些已建索引可直接复用、哪些日期尚未索引、预计核对工作日数。 |
| 可选「建立缺失的私有键索引」 | 只允许在`work/unified_parquet/minute_key_index`产生新的**键位图SQLite** | 每个自然月/已有索引边界分段，每段≤31日。源Parquet只读`ts,symbol`两列，绝不复制OHLCVA。可取消勾选以强制「只复用已存在索引」模式；源变更、索引范围重叠、重复股票时间键都拒绝。 |
| 只读精确H5差集审计 | 仅在`work/minute_audit_gui/jobs/<id>`写任务state、日志及**聚合审计JSON** | 背景进程逐分段审计1/5min完整缺股票日、同股票日内部H5-only分钟候选、购源09:30独有和其他时间桶、隔离原因。全部候选`accepted=0`，不允许自动生产补入。 |

新GUI界面：`tools/minute-gap-audit-gui.py`，后台`tools/minute-gap-audit-gui-worker.py`，入口`start-minute-gap-audit-gui.ps1`，全部在`H5ParquetReconciler`目录。GUI采用Python标准库Tkinter，后台使用项目已有的Arrow/H5/SQLite环境，无需引入新的Web服务器或长期守护进程。

主要操作：选源目录`D:\stock`，日期范围，例如`2026-02-01..2026-02-28`；点击「查看将要复用/新建的索引分段」，再点击「开始批量只读核对」确认。列表显示任务状态、日期完成进度、H5候选差异、隔离股日总数；下方可查看最多最近200 KB日志；「查看隔离异常」按**日期、周期、隔离原因、股票日数量**展示已完成分段。不展示证券代码或OHLCVA，此版尚不能定位4个异常的具体股票，若后续需要可另行加入隐私保护的个股诊断清单。

**暂停**：「当前分段完成后暂停」只写本任务的`pause_after_window.flag`，不强杀进程；当前分段完成并保存SHA无关的聚合结果后安全退出。停下后选原任务点击「填入剩余未完成范围」，会自动填写下一分段日期，再启动**新任务**。此版没有中途恢复旧进程，不重复已完成分段的购买Parquet索引创建。

原始`D:\stock`文件不会被写；日志/私有索引持久化在项目内。旧的整日转换GUI继续保持禁用。结果并未启用任何生产查询/合并指针。

## 三、首次Windows运行命令

仓库开发分支`feat/private-2011-2025-purchased-physical-year-20261031`：

```powershell
cd D:\ChatGPT\AStockDataTools; git -c http.version=HTTP/1.1 pull --ff-only origin feat/private-2011-2025-purchased-physical-year-20261031; if ($LASTEXITCODE -ne 0) { throw "GitHub更新失败，未打开新核对GUI" }; powershell.exe -NoProfile -ExecutionPolicy Bypass -File H5ParquetReconciler\start-minute-gap-audit-gui.ps1; if ($LASTEXITCODE -ne 0) { throw "GUI后端安全回归失败，未启动界面" }
```

启动脚本先跑`test_preview_minute_exact_key_diff_readonly.py`、`test_build_minute_purchased_key_index.py`、`test_audit_minute_index_window_readonly.py`、`test_ensure_minute_key_index_window.py`、`test_minute_gap_audit_gui_worker.py`，共**7+5+4+4+8=28项**合成测试。**新增8项GUI worker/启动兼容性测试与界面尚未有真实Windows PASS回执。** 通过后使用venv的`pythonw.exe`打开GUI；关GUI不影响已启动的后台审计进程。

## 四、下一阶段边界

1. 把原H5的4个不完整1分钟股票日按日期、股票代码和缺少的原生时间桶做**独立只读诊断**；不能因为时间格不完整就直接写入购买Parquet。
2. 批量审计得到的非零候选H5键，还必须检查原生量纲、时间网格、数值有效性、证券身份及旧已验gap，才能生成只含真缺口的隔离Parquet。
3. 后续研究/正式查询应引用原购买年度Parquet + 签名H5补差分区，不复制购买源；15/30/60min和周/月仍优先原购买文件；原生H5镜像另走有损量化验收。
4. 来源指纹现仅元数据快速检验，不做内容SHA，因此**本GUI不是生产级来源签名/数据完整性认证工具**。月批量进度不可误称全市场历史全部补齐。
