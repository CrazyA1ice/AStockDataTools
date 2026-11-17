# 每天北京时间 16:30：一任务、一脚本、四类增量更新、结束通知

这是**待 Windows 真机验收的代码候选**。拉取/合入代码不会自动改变已安装的 Windows 计划任务；旧 21:30 任务必须在完成测试后**以同名任务覆盖**，不可增加并行任务。

## 单一流程

任务名：`AStockDataTools-ParquetLiveSync`。每日触发器**唯一**：中国市场时间 16:30，安装时转换为本机时间（中国电脑 16:30；日本电脑 17:30）。

单一入口：`ParquetLiveSync/scheduled-afternoon-update.ps1 -Apply`，顺序执行：

1. **八周期 K 线**：QMT 分钟、TDX DAY 与已有抽样交叉源核对；源不合格不覆盖旧验证数据
2. **财务**：QMT 最近 120 天公告窗口增量下载、九表完整历史缓存校验；`--max-minutes 0` 表示**没有整轮总分钟限制**；跨日轮转游标继续，不清空待审项
3. **板块**：更新 QMT 板块数据并保存当日成员快照
4. **除权**：增量轮转，默认 80 只股票/次，保留游标，不冒充每天全市场已更新

**没有旧 21:30 任务模式，也没有 20:45/00:30 补偿触发器。** `New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero)` 取消 Windows 计划任务运行时长上限。现有下载源的单次请求/单批工作进程超时**仍保留**，用于处理无响应的接口；这是单请求故障保护，而不是定时结束整轮更新。财务 21:00–23:05 采集禁入窗口已从统一财务导入器移除，不再限制晚间延续执行。

跨越午夜时，财务仍以 `PAUSED_DATE_ROLLOVER` 安全结束当次按日期编排的批次，避免把第二天的数据错误标为前一天；第二天继续轮转，不是另一个 Windows 定时器。若一个任务直到次日 16:30 还在运行，调度器以 `IgnoreNew` 避免开启重叠实例。Windows 登录、QMT 在线、电脑不休眠仍然是运行条件。

## 更新完自动提醒

无论四项全部正常退出、部分失败还是都无法开始，脚本都会尝试发送本地 Windows 消息：

- `SUCCESS` — 四阶段成功退出（**不代表全部数据全市场完整或交叉核验全部通过**）
- `PARTIAL` — 有阶段成功，有阶段失败
- `FAILED` — 没有阶段成功或预检失败

先尝试 Windows 通知，若系统拒绝则回退为 Windows 弹窗（20 秒后自动关闭）；Windows 未登录或系统通知被禁用时无法保证弹出，所以每次仍在 `ParquetLiveSync/work/last-afternoon-unified.json` 留下可审计结果和 `work/afternoon-*.log` 日志。状态写入失败也会尝试通知。**当前仅支持本机通知，未接入 QQ/微信远程推送**；远程通知需要单独配置现有机器人的有效消息发送接口，不能臆造 URL 或密钥。

通知脚本 `notify-market-update.ps1` 支持 `-DryRun`，可单独测试三类结果而不真正弹窗。代码出现语法错误、Windows 强制终止进程或电脑断电时，任何进程内通知都无法保证触发；这类异常需要任务历史/外部监控才能发现。

## 当日更新通知：明确区分执行、数据校验、跨源证据

用户通知与 `work/last-afternoon-unified.json` 的 `validation` 对象分别记录：

- **执行状态**：K线、财务、板块、除权四个子任务是否退出成功
- **数据校验**：只根据当次 `MARKET_DAILY_STAGED`、`MARKET_EIGHT_PERIOD_SUMMARY`、`QMT_FINANCIAL_CACHE_IMPORT_SUMMARY` 和 `MARKET_QMT_EXTRA_SUMMARY` 回执判断；有股票隔离、财务 pending 或尚未遍历的证券必须标注“部分通过”，没有最新回执必须标注“未验证”
- **交叉验证**：K线仅在当次所有配置的独立分钟样本源均报告 AGREE 时显示“抽样通过”；有价格差异显示“失败”，来源不可用或无新样本显示“未验证”；财务、板块、除权尚无认证的第二数据源，不能显示“跨源通过”

四阶段日志分别保存在 `work/afternoon-日期-阶段.log`，由新增的 **只读** `market_daily_verification.py` 解析，完整证据写入 `work/verification-日期.json`，且不读取前一天的成功记录。即使验证脚本损坏，主脚本仍会发送“执行情况已知、校验与跨源未验证”的保守通知。本机 Windows 通知仍是尽力发送，断电、注销或进程被系统强制终止不保证提醒。

既有 Windows 任务使用 `ExecutionTimeLimit=PT0S` 表示没有整轮执行上限。**在 `Get-ScheduledTask` 返回字符串形式的持续时间时，不要使用 `-ne [TimeSpan]::Zero` 判断；应该查询任务 XML 中的 `Settings/ExecutionTimeLimit`。** 下载器的单次请求故障超时仍保留，不属于任务运行总时长限制。

## 数据安全、覆盖率和已知隔离

- 项目已有八周期行情多源证据；财务、板块、除权现仍以 QMT 入库，**尚不具备完整第二来源核验**
- 财务历史源冲突 16 只 Capital 与 688259.SH 解码异常保留在 `pending`；不覆盖旧快照
- 财务股票池 5,656 只、除权股票池 5,224 只，限制批次意味着每日并非全市场完全更新。用户得到的是**准确的执行结果和未验证覆盖标志**，不能把四阶段进程返回 0 视为数据全面完整
- 真实写入只能在主 Git checkout 的原有私有状态目录中进行；任何独立 Preview worktree 禁止 `-Apply`，不得创建空进度文件绕过

## 安装前测试

先仅在 Preview worktree 执行 Python 离线测试、两个 Windows 调度模拟、通知三状态 `-DryRun` 和无 `-Apply` 的统一预览。确认旧任务依然保持现状。测试通过且备份原游标后，真机短批量验收须检查四步日志与失败消息是否正确生成，不能在日志未核对前直接宣布生产已经切换。

实际任务安装只有一个命令：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "ParquetLiveSync\install-schedule.ps1" -Action Install
```

**这会以同名任务覆盖原 21:30 配置，真正启用每天 16:30 的单一运行入口。仅在真机测试合格后执行。**

状态查看：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "ParquetLiveSync\install-schedule.ps1" -Action Status
```
