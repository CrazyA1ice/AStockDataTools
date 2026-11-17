# 一键更新八周期 Parquet + Windows 盘后自动任务（二期）

统一命令始终是 `ParquetLiveSync/update-market.ps1`。原始 H5 和 2011—2025 购买 Parquet 不会被更新器重写。

| 周期 | 新来源、写法 | 入库边界 |
|---|---|---|
| 1min | QMT 唯一写入源；官方 TDX DAY + eltdx + 腾讯 m1 交叉验证 | 已在 Windows 实测 2026-11-13 |
| day | 官方通达信 DAY zip，独立 OHLCVA 对照 | 已在 Windows 实测 2026-11-13 |
| 5min / 15min / 30min / 60min | 从已验收的物理 1min 按 120+120 两段交易分钟聚合 | **先以购买版 2026-09-30 对应周期校准标签和量额比例，验证通过才允许合入** |
| week / month | 从已验收的官方 DAY 聚合 | 复用旧 `rollup_week_month.py` 严格历史购买数据校准；**只写已收盘的周/月** |

禁止凭借腾讯分钟数据捏造成交额；不进行一个周期的自我推导并冒充独立行情源。所有时标与量额倍率都以实际购买版数据重叠验证为依据，验证失败会单独标记并拒绝该周期写入。原始同键值不盲目覆盖。

## 第一次：在本机核对并补齐其它周期

分支 `feat/all-cycle-market-scheduler-20261115` 基于已通过 QMT + eltdx + 腾讯的稳定一键分支开发。

先执行 **不修改正式 Parquet** 的预览。它对实际购买版 9 月数据做一次校准，核对 QMT 1min 的 SHA、对每个周期记录待补的日期，不再为了预览先扫描全部 34 百万根分钟线：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "ParquetLiveSync\update-market.ps1" -Mode cycles -DryRun
```

只有 `MARKET_EIGHT_PERIOD_SUMMARY` 标记 `PREVIEW`、`phases_blocked={}` 时才执行一次正式补齐：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "ParquetLiveSync\update-market.ps1" -Mode cycles
```

这一步从 `D:\stock\AllCycleAStockData\1min\2026-10.parquet` 和 `2026-11.parquet`（已验收的物理月文件）读出真实分钟记录，首次逐股票日生成其它 4 个分钟周期；不足标准 240 根的旧 H5 股票日**不会虚构补全**。用原 `local_layout.write_month` 的购买格式保留、SHA 备份、临时文件读回与原子替换写入相应目录，记入独立进度回执，异常后可继续。可能需要一次性扫描数千万条历史分钟记录，之后日更只补尚未入库的交易日。

周/月按原 `rollup_week_month.py` 的实付版日期标签校准和 OHLCVA 校验写入已完成周期。周线在有已验收星期五数据时收盘闭合；月线在自然月结束时闭合；节假日以 QMT 上海交易日历判定，缺少本应交易的官方 DAY 会阻止依赖它的周/月发布。

## 每天照旧：一条命令

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "ParquetLiveSync\update-market.ps1"
```

该命令依序处理：TDX DAY → QMT 1m → 两个独立分钟源抽样 → 物理 1m 月 → 已购买校准的 5/15/30/60m → 已完成 week/month。不同阶段分开报告，后段失败不会撤销先前合法提交，下一次按月份和交易日进度补继续，不需要重下已保存的 QMT 数据。

`-Mode daily -Day "2026-11-13"` 仍支持原定日，`-Mode sources -Day "2026-11-13"` 仍只做只读数据源抽检。新增的 `-Mode cycles` 可以单独补齐其它六周期，**不重采 QMT**。

## Windows 每日盘后定时任务

**用户明确选择安装时**再执行下面命令；此仓库代码不会擅自创建 Windows 任务。这个脚本采用原任务名称 `AStockDataTools-ParquetLiveSync` 注册/更新单个任务，替换旧 DAY_ONLY 调度逻辑，不会产生两个重叠任务。

安装默认 Windows **本机时间 21:30**（北京时间20:00以后才允许本机的 QMT/TDX 日收盘更新，注意若 Windows 不是北京时间须按本地时区调整）：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "ParquetLiveSync\install-schedule.ps1" -Action Install
```

自定义本机时间（如22:00）：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "ParquetLiveSync\install-schedule.ps1" -Action Install -At "22:00"
```

查看状态、上次任务运行及实际错误：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "ParquetLiveSync\install-schedule.ps1" -Action Status
```

移除**本仓库单个**行情任务：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "ParquetLiveSync\install-schedule.ps1" -Action Remove
```

定时任务只在登录用户的交互会话内运行：**Windows 必须已登录、QMT 客户端须可连接（`xtdata`）、电脑不能休眠/关机、网络必须可用**。为避免重叠，设置 IgnoreNew，同一时刻只允许运行一次；错过执行时间则在计算机可用时运行；最长单次执行 4 小时。该功能不等于关机/退出登录后仍能采集 QMT；如确实需要无人值守，先解决终端长期在线与登录会话稳定性。

私有运行日志：`ParquetLiveSync/work/scheduled-update.log`
私有最近结果：`ParquetLiveSync/work/last-scheduled-run.json`
计划任务名：`AStockDataTools-ParquetLiveSync`

## 保护与限制

- 所有新周期的时间标签、量额单位需要实际购买版证据，默认不盲猜，按周期失败保护；任何阶段失败都不是成功标记。
- 5/15/30/60m 来源仍是 QMT 的 1m 派生结果，**不是四个独立新行情上游**。另外核对的 eltdx、腾讯都是分钟抽样，不会覆盖正式值。
- 只生成已有 240 格点的完整股票交易日；原有隔离异常不会被“合成”成完整日。对既有周期物理文件的同键值保留旧值，显著价格冲突停止；不删除用户原始文件。
- 当前年月文件为 YYYY-MM.parquet；完整过去年度归档不由每日任务私自执行。
- **2026-11-15 Windows 实测已完成**：54/54 项 Python 测试通过，四分钟周期 2026-10/11 共 8 笔实际 Parquet 月提交成功；周线 2026-11 新增 5,574 条，10/11 周月线已验原有同键。随后再次运行 `-Mode cycles` 六个周期新增 0（幂等复查通过），计划任务 `AStockDataTools-ParquetLiveSync` 已安装且状态 `Ready`。**新计划任务首次自动运行的 SUCCESS 记录仍需 Windows 日志证明**，不能把模拟安装日志当成真实执行。
- **QMT 新增财务/复权因子/板块/指数/ETF：** [QMT_EXTRA_PARQUET.md](QMT_EXTRA_PARQUET.md)。继续沿用同一入口 `update-market.ps1 -Mode extras`，但真实 QMT 数据未验收前默认不接入现有 21:30 任务。
