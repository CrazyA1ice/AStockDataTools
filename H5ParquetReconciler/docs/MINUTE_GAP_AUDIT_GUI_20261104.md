# 分钟数据缺口核对可视化控制台（2026-11-04）

> **独立新工具**。不复用已停用的`minute-private-parquet-gui.py`购买Parquet整日复制按钮；原始`D:\stock\AllCycleAStockData`和`D:\stock\HikyuuData`始终只读。**本文件描述的是已提交、待用户Windows运行新回归测试的代码，不能视为全部实机验收完成。**

## 2026-11-04 Windows第二次启动：34项回归全PASS，PowerShell `python -c` 参数转义错误

用户更新到`bf52fcbb`后，PowerShell 5.1已能正确解析ASCII启动脚本，且**六组全部34项合成回归测试实机PASS**：7分钟差集、5索引、4多日审计、4索引复用、8 GUI后台、6历史日线（含1990/1991）。**GUI尚未打开**：在下一段语法检查 `& $py -B -c '... encoding="utf-8" ...'` 中Windows PowerShell 5.1向原生Python进程传递参数时丢失内部双引号，Python实际把`utf-8`当作表达式，报`NameError: name 'utf' is not defined`。这与文件内容是否UTF-8有效无关；也不是34项合成回归的失败。

修复方案：
- 新增`tools/preflight-minute-gap-audit-gui.py`，在独立Python进程中读取UTF-8 GUI源、AST语法检查、import tkinter、实际加载GUI模块并检查`App`存在；不创建Tk根窗口，不读写行情或调用旧worker。
- `start-minute-gap-audit-gui.ps1`不再使用任何`& $py -B -c`内嵌代码，而使用简单的`& $py -B $preflight --gui $gui`原生命令行参数，规避Windows PowerShell 5.1传参转义损坏。入口脚本仍全ASCII。
- 更新GUI合成测试：额外2项验证子进程运行preflight确实打印`GUI_PREFLIGHT_OK`且拒绝不相关worker脚本；原ASCII测试附加校验启动器不再使用`& $py -B -c`。
- 入口应当**先通过36项回归（7+5+4+4+10+6）**，再运行安全预检并使用`pythonw.exe`打开窗口。新增的两项和GUI启动仍**待用户Windows复验**；不得提前宣称已通过。

重复之前Windows已经确认的34项测试不会访问真实行情源；synthetic H5/Parquet fixture由测试用临时目录生成。新启动预检也不会修改原市场文件。若GitHub临时不可达且本地仍在`bf52fcbb`，仍可用`.\.venv\Scripts\python.exe -B H5ParquetReconciler\tools\minute-gap-audit-gui.py`直接启动已通过34项回归检查的旧GUI源码，仅跳过出问题的PS预检、不会恢复旧物理复制任务。

## 2026-11-04 Windows首次启动解析失败与修复（等待复验）

用户实际执行首次GUI启动，GitHub快速更新到 `a98a8ee` 已成功，但 `start-minute-gap-audit-gui.ps1` 在Windows PowerShell 5.1解析阶段出现 `TerminatorExpectedAtEndOfString`，错误指向`Start-Process`行，**尚未运行任何Python测试或GUI进程**。仓库文件是无BOM UTF-8，含非ASCII中文单引号提示，Windows PowerShell 5.1可能当作本地ANSI编码读取，导致引号被破坏。原始市场数据及已验私有索引没有任何修改。

修复：
- 将启动`.ps1`脚本中的提示全部替换为**纯ASCII**，从根本规避无BOM UTF-8与本地ANSI兼容问题；中文仍放在Python GUI界面中，其他PowerShell脚本暂不受此次修改影响。
- 加入Python GUI源码AST语法检查与Tkinter/worker真实导入检查，**先在PowerShell普通python.exe中完成，再用pythonw.exe打开GUI**，避免GUI导入异常导致无提示退出。
- `tests/test_minute_gap_audit_gui_worker.py`增加`test_powershell_launcher_is_ascii_for_windows_powershell_51`与`test_python_gui_module_is_syntax_valid_before_pythonw_launch`两项。现在一键启动应运行**7+5+4+4+8=28项**合成测试，而不是原来的26项。
- **新修复已提交GitHub，尚未获得用户Windows复验输出**。如果测试或import预检失败，先查看PowerShell错误并修正，不要跳过测试、重启旧购买数据复制GUI或更改原始行情。

## 2026-11-04 取消不合理的全局日期上限，分清日线历史与分钟精确核对

用户看到 GUI 日期`2025-01-01`到`2026-02-28`仍被拒绝，进一步指出H5原生日线可追溯到1990年前后，分钟H5则覆盖近期数据：两类数据的时间覆盖完全不同，不能用统一的`2025-01-01..2026-10-13`日期上限。最初为防整日Parquet重复转换而设置的367日全任务上限，也已经在月度键位图索引机制下失去必要性。

**新GUI的实际支持与安全边界**：
- 增加显式模式：**分钟精确缺口（1/5min）**和**日线历史H5覆盖清查**。用户选定的开始/结束时间本身仅做`YYYY-MM-DD`解析与起止顺序检查，**不再统一禁止1990年，也不再统一禁止超过367日的任务**。
- 分钟精确核对：依然复用已实机验证的分钟键索引+H5时间网格算法，目前**算法已验范围**为`2025-01-01..2026-10-13`；不是H5整体数据历史的边界。用户可以一次选择覆盖多个自然月/跨年度的分钟任务，GUI自动拆成**每段不超过31个自然日**的私有键索引（可以复用已有断点），仍不允许把尚未验证的年份或晚于已验终点的分钟任务当作已验差集；后续需要根据实际H5/购买Parquet源自动发现分钟范围并扩展验证窗口。
- 日线历史清查：允许用户输入**1990年前后乃至其他有效历史日期**，按年分段，通过`HikyuuData/*_day.h5`内每个股票原生日线数据集的datetime字段二分查找实际日期覆盖，并在逐年报告中记下H5候选A股日线行数/证券序列数、购买Parquet对应年份文件数。**此模式不创建分钟索引，不尝试用分钟数据伪造日线结果。**
- 增加`读取H5实际日线起止日期`按钮：直接读取股票日线候选H5序列首末datetime，返回源内**实际最早/最晚日期**，确认后自动选中日线模式并填写日期。不能以“1990年”主观猜测代替H5实际数据。
- 日线清查只证实**原生H5日线存在和年份覆盖**。此前1990—2010的日线候选有8,340条隔离清洗问题等，单凭H5行数、或购买Parquet某年存在文件，并不能计算经验证的净补差或安全入库量。因此日线模式UI表格显示**“H5候选缺口：未计算”**，而不是错误地显示0或称为“已补齐”。
- 工作输出仅可在`H5ParquetReconciler/work/minute_audit_gui/jobs/<id>/audit-day-YYYY-MM-DD-YYYY-MM-DD.json`产生年度统计报告/状态/日志。源`D:\stock`内购买Parquet与H5均只读；H5原生字段数值、时间网格、非交易日及旧已验私有日线缺口的对账另设阶段。
- 日期范围不再被人为截断，**单段资源保护仍保留**：分钟31日/索引行数预算；日线逐年；断点只在完整分段后保存；可以安全暂停，避免一次加载数十年全部数据。
- 新建`tools/inspect-daily-h5-coverage-readonly.py`专责历史日线覆盖，已连接到GUI worker；新增`tests/test_historical_daily_h5_coverage_gui.py`6项合成H5日线(1990、1991、2026)/分钟超367日/原文件SHA不变验证。启动脚本现在应运行旧28+新6=**34项关联合成测试**（**新日线模块尚待Windows实机首次运行**）。

**下一步**：核对1990年等H5年份真实覆盖边界；然后开发与既有购买Parquet及已验证日线H5候选分区的**逐股票逐日精确键差集**和隔离错误处理，再审批只写真正缺失的日线键，绝不能直接把整个H5历史复制为“新行情”。同时进一步依据分钟H5的真实时间边界完善分钟模式的动态日期许可。

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

启动脚本先跑`test_preview_minute_exact_key_diff_readonly.py`、`test_build_minute_purchased_key_index.py`、`test_audit_minute_index_window_readonly.py`、`test_ensure_minute_key_index_window.py`、`test_minute_gap_audit_gui_worker.py`，共**7+5+4+4+8+6=34项**合成测试。**新增8项GUI worker/启动兼容性测试与6项历史日线测试、更新后的界面，尚未有真实Windows PASS回执。** 通过后使用venv的`pythonw.exe`打开GUI；关GUI不影响已启动的后台审计进程。

## 四、下一阶段边界

1. 把原H5的4个不完整1分钟股票日按日期、股票代码和缺少的原生时间桶做**独立只读诊断**；不能因为时间格不完整就直接写入购买Parquet。
2. 批量审计得到的非零候选H5键，还必须检查原生量纲、时间网格、数值有效性、证券身份及旧已验gap，才能生成只含真缺口的隔离Parquet。
3. 后续研究/正式查询应引用原购买年度Parquet + 签名H5补差分区，不复制购买源；15/30/60min和周/月仍优先原购买文件；原生H5镜像另走有损量化验收。
4. 来源指纹现仅元数据快速检验，不做内容SHA，因此**本GUI不是生产级来源签名/数据完整性认证工具**。月批量进度不可误称全市场历史全部补齐。
