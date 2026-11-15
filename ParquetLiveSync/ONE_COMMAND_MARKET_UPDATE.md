# 一条命令更新 A 股 Parquet（一期：1min + 官方 day）

## 用法：每天只执行同一条命令

在仓库根目录运行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File ParquetLiveSync\update-market.ps1
```

- 首次运行自动把已经通过真实 Windows 验收的 2026-10-14..11-12 QMT 私有 1min 增量接到 `D:\stock\AllCycleAStockData\1min`。
- 同时从原有、已验收的截至 2026-10-13 八周期数据集的来源清单中补入 2026-10-08、09、12、13 分钟数据；不重建 2011~2026 完整购买历史。
- 真实 QMT 1min 每股票日有 241 个分钟标签，其中 09:30 **并非总是零成交**。转换为原购买数据的 240 根/日时，若该根成交量/额都为零，则按占位根丢弃；若两者都大于零，视为真实集合竞价成交，将其开盘价、高低价范围和成交量额**合并进 09:31 第一根常规分钟线**，日级 OHLC 与量额严格守恒；若量额一零一正则拒绝，不猜测。来源 241 根原始数据仍保存在 SHA 绑定的私有 Parquet。
- 2026-10-14..11-12 的 114,739 个已验收股票交易日变为 **27,537,360 根标准 240 分钟线**，加上旧版 10 月 1~13 的实际已验收 1min 记录。 对有真实 09:30 成交的股票日，量额归并而非丢失。之前私有原生 241 格子的 27,652,099 行不受影响，仍可追溯。10 个 `301139.SZ` 旧日异常保留未补齐，不伪造。
- 初始化完成后自动检查新交易日：官方 TDX DAY → QMT 1min → pytdx/eltdx/AKShare可选分钟对照 → 240 分钟规范化 → 当前月 Parquet 的追加与校验。
- 每日只处理游标之后尚未成功写入的日期；会跳过非交易日和无官方 DAY 数据的日期；不会每天重复验证 5,039 份历史原始收据。
- `--mode bootstrap` 只做一次性历史衔接，`--mode daily` 只更新当天/落后的几天，默认 `auto` 两者按需执行。

首次可以只看预检，不修改文件：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File ParquetLiveSync\update-market.ps1 -DryRun
```

确认后，还是上面的同一条日常命令即可。如在某个工作日盘后定时运行，建议 **北京时间20:30以后**（TDX DAY 官方日包可能晚于收盘发布），使用 Windows 任务计划程序调用。不需要长时间保持每根分钟线在线订阅。

## 只诊断多源分钟线，不重做 5215 只股票的历史采集

首次日常更新后，已验收的当日 QMT 分钟记录在私有 `work/market_update/daily/YYYY-MM-DD.parquet` 保存并做了 SHA256 回执。如果某个交叉来源网络故障，可直接对这一份已缓存的当天数据重跑**仅8只股票**的分钟源抽样，不重抓 QMT、不断点回放、也不修改正式 Parquet：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File ParquetLiveSync\update-market.ps1 -Mode sources -Day "2026-11-13"
```

`pytdx` 优先尝试当前 Python 安装的 `pytdx.config.hosts.hq_hosts` 内置行情节点，其次使用配置中的固定备用节点。节点数与超时受 `market_sources.json` 的 `max_servers`、`connect_timeout_seconds` 限制。若全部不可用，将以 `status=UNAVAILABLE` 标记并记录尝试数/响应情况；这**不是行情不一致**，且同一天不再对另外7只股票重复做无用连接。其它来源（如已通过的 eltdx）仍会继续检查。此功能无法保证网络侧总有可用的 pytdx 节点，节点故障应作为来源可用性问题，而不是允许填入未经独立校验的数据。

## 配置数据源

编辑 `ParquetLiveSync/market_sources.json`，或通过 Python 的 `--config` 参数指定单独的本机配置文件。

| 名称 | 用途 | 默认 |
|---|---|---|
| QMT xtquant | A股 1min 完整 OHLCVA **唯一自动入库主源** | 必选 |
| TDX 官方日包 | 全市场日 OHLC、成交量、成交额独立对照，亦可更新 day Parquet | 必选 |
| pytdx (tiantianlaolao/astock-data-toolkit 的策略) | category=8, 1min OHLCVA；滚动历史，抽样对照 | 开启（未安装可记录错误） |
| eltdx (electkismet/eltdx) | `client.bars.get(period="1m",bar_time="end")` OHLCVA；也支持历史分时（分时仅价量不用于替代 OHLCVA） | 开启（未安装可记录错误） |
| AKShare 东方财富 | 1min 仅近 5 个交易日，额外的短期对照；与 QMT 不同的提供者 | 关闭，可选开启 |

pytdx 与 eltdx 均为 TDX 7709 协议家族，**不当作两个独立行情证据投票**。金额/数量未经跨源量纲认证不得从这些次源静默替换 QMT。次源连接失败记录为告警；独立 TDX 官方 DAY 对每只股票的 OHLCVA 闸门始终启用。次源实际返回的相同分钟价格如果显著冲突，将阻止该日静默入库，保留私有候选供排查。

两份参考项目：
- https://github.com/tiantianlaolao/astock-data-toolkit/tree/main/minute
- https://github.com/electkismet/eltdx
- https://akshare.akfamily.xyz/data/stock/stock.html

## 正式月文件安全边界

`D:\stock\AllCycleAStockData\1min\2026-10.parquet` 和 `2026-11.parquet` 在之前真实运行中均不存在。初始化直接创建这两个当前年月文件；原购买年度数据/截至10月13日的不可变来源版本和 H5 都不覆盖。

所有新月以原八列 `ts(int64),symbol(string),open/high/low/close/volume/amount(float64)` 保存，沿用上一个已存在的购买 1min 月文件的 symbol 书写方式。私有 QMT 时间偏移、量额倍率依靠此前 2026-09 的 SHA 固定校准，后续每天复用，不再反复拟合全市场。

对日新增按日期分隔、股票+分钟唯一键在单股票严格校验，历史月文件不会与同一交易日期盲目并集；不同来源区分日期和股票日来源收据。当前已写入交易日默认跳过，需单独开发有冲突的缺口补入路径，不覆盖原值。

单个受影响月份以有界 Parquet 批次重写；先对旧文件建立硬链接（不支持时退回复制）备份，再计算新文件 SHA、写事务意图、原子切换、写持久化成功账本。异常时报告失败且保留已成功提交的其他月份。自动运行使用现有 `live_sync.exclusive_writer` Windows 单进程写锁。

磁盘需留足 **新增月文件、正在更新月文件的临时文件以及旧文件备份** 的空间。首次运行可能较长：历史已验证 27m 根分钟线仍需要一次真实复制进现有目标目录；以后不会重复。每次修改的是当年月文件，不执行 2026 年年度归档。

## 一期没有宣称完成的能力

本期落地真实 `1min` 和现有 TDX `day` 写入，其它 5/15/30/60min、week、month 的同一个调度入口和独立已验证聚合规则尚未接入，**不能把 1min 派生数据冒充已核验的原始多周期格式**。2026-10-08..13 原有 minute 源的合法性和 10-14..11-12 新 QMT 241 验收由之前的已验收源目录、清单及 SHA 承担。2026-11-13 后的实时新分钟采集没有在此次 GitHub 代码环境执行，必须在用户的 Windows QMT 环境通过真实回归。

预计用户长期每天只需要一个入口；详细审计与失败库存是内部日志，不应再让用户手工运行 4~5 层分支脚本。
