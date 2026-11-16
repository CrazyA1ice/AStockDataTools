# QMT 财务、除权、板块、指数、ETF 补充数据（独立 Parquet）

> 这是八周期股票行情之外的独立数据集，**默认不开启每日定时下载**。
> 当前代码为 GitHub 版本，必须先由 Windows QMT 机器执行安全测试和真实只读探测。
> QMT 版本、证券账户权限及历史留存范围决定真实可取到的数据量，不能假定所有年份都有完整记录。

## 原有股票八周期，不改变

真实存放在 `D:\stock\AllCycleAStockData\`，每周期一个文件夹：

```text
AllCycleAStockData/
  1min/           5min/           15min/          30min/
  60min/          day/            week/           month/
    2025.parquet  ...             （往年年文件；当年 YYYY-MM.parquet）
```

2026-11-15 Windows 实测：5/15/30/60min 已追加 2026-10 与 2026-11；周/月完整已闭合区间已补齐，二次运行新增 0。***不修改上述任何股票周期文件。***

## 新增 qmt_extra，与上述数据放在同一根目录下但物理隔离

```text
D:\stock\AllCycleAStockData\
  qmt_extra\
    financial\
      Balance\<证券代码>\snapshots\<日期>-<摘要>.parquet
      Income\...        CashFlow\...     Capital\...
      [QMT 版本实际返回的所有财务报表名称]\...
    adjustments\<证券代码>\snapshots\<日期>-<摘要>.parquet
    sectors\snapshots\<日期>-<摘要>.parquet
    index\
      instruments\<指数代码>\snapshots\...
      weights\<指数代码>\snapshots\...
      1min\<指数代码>\2026-11.parquet
      5min\... 15min\... 30min\... 60min\...
      day\...  week\... month\...
    etf\
      info\snapshots\<日期>-<摘要>.parquet
      instruments\<ETF代码>\snapshots\...
      1min\<ETF代码>\2026-11.parquet
      5min\... 15min\... 30min\... 60min\...
      day\...  week\... month\...
```

- **指数/ETF K 线**八个周期从 QMT 原生对应周期下载，保持 QMT 的 `none`（不复权）OHLCVA，原始 `time` 毫秒时间戳。按周期、证券、年份/月份存放；**与原购买版股票的时间标签校准不是一回事**。原购买版的 8 个股票目录及 H5 一律不混入。
- **财务、除权及 ETF 信息、指数权重**：QMT 不同版本返回字段不固定，保存在 Parquet 的 `payload_json` 内，另外标明 `asof/symbol/item/index`。保留原列名与数据；不会把一份快照冒充逐日历史 PIT 信息。
- **板块**：`asof,sector,symbol` 记录每次实际抓取的当日成分快照；QMT 当前板块名单不等于完整历史板块沿革。
- **指数权重**：按 QMT 账户支持程度获取；不提供则明确记录 API 不可用，不能编造。
- **ETF**：优先 QMT ETF 分类接口，避免把 LOF 等其他基金错误标成 ETF。
- 价格旧数据同键遇到 OHLCVA 冲突直接拒绝；历史新增保留、失败不回滚此前已验收批次。新快照按内容摘要不可变命名。同一根目录下不等于相同的原厂校准来源。

## 使用同一个更新入口，但采用显式 extras 模式

在 Windows QMT 登录可连接、项目虚拟环境安装好的条件下：

**只读侦测（不下载、不写正式 Parquet）：**

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File ParquetLiveSync\update-market.ps1 -Mode extras -DryRun
```

输出 `MARKET_QMT_EXTRA_SUMMARY` 应包含 `READONLY_PREVIEW`、股票/指数/ETF 数量、下一批代码。先核对 QMT 对这些市场板块是否有权限、是否返回正确的 ETF 名单。

**小批量首批真实采集（下载进 QMT 缓存，再写隔离的 Parquet）：**

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File ParquetLiveSync\update-market.ps1 -Mode extras -ExtraStockLimit 3 -ExtraAssetLimit 1
```

只有首批确实生成财务/除权/板块/指数/ETF 文件并返回 `MARKET_QMT_EXTRA_ONE_COMMAND_SUCCESS` 后，才扩大每批数量，例如股票 40 只、指数与 ETF 各 5 只。每次会记录完整来源的证券游标，失败可重试。指定 `-ExtraStockLimit 0 -ExtraAssetLimit 0` 可请求全量剩余证券，但可能耗时很久且占大量磁盘/网络资源；大历史最好分批。

默认请求起始日期为 2011-01-01，可用 `-ExtraStart "2025-01-01"` 调整；QMT 没有历史记录则不能凭空补造。财务数据由 QMT 实际支持的全部财务表决定。每只指数/ETF 首轮尝试获取 QMT 可提供的八周期历史，以后重访该证券时，从上次成功日期前 15 日的重叠窗口更新。

数据进度：`ParquetLiveSync/work/qmt_extra/progress.json`；私有备份：`ParquetLiveSync/work/qmt_extra/backups/`。两者已通过 .gitignore 排除，不会提交证券行情文件到 GitHub。

## 在 **现有** 21:30 八周期计划任务中启用附加批次（仅首批实测通过后）

不安装第二个任务，不更换原有任务名称。原 `-Mode auto` 八周期先运行成功，随后才执行有限批次 QMT extras。

只在本机显式建立 `ParquetLiveSync/work/qmt_extra/schedule-enabled.json` 后生效，例如：

```json
{
  "format": "qmt_extra_schedule_v1",
  "stock_limit": 20,
  "asset_limit": 2,
  "start": "2011-01-01"
}
```

尚未创建该文件则定时行为 **完全保持此前的八周期**。文件只在本机，切勿在当前功能未经实际验证时提前启用。QMT 必须运行于登录用户会话；任务有 4 小时执行上限。某次 extras 失败会在同一任务的 `last-scheduled-run.json` 中记录失败，但已提交的股票数据仍保留，后续重试。

## 数据来源与版本差异

本实现仅使用已公开的 QMT xtquant 数据接口：`download_financial_data`、`get_financial_data`、`get_divid_factors`、`download_sector_data`、`get_sector_list`、`get_stock_list_in_sector`、`get_instrument_type`、`download_history_data`、`get_market_data_ex`、`download_etf_info`、`get_etf_info`、`download_index_weight`、`get_index_weight`。

参考文档：
- https://www.miniqmt.com/api/miniQMT/miniQMT%E5%AE%98%E6%96%B9API%E6%96%87%E6%A1%A3XtQuant.XtData%E8%A1%8C%E6%83%85%E6%A8%A1%E5%9D%97.html
- https://knowledge.thinktrader.net/docs/xtquant/code_examples.html

**当前开发状态**：代码及离线模拟测试已提交，实际 Windows QMT 执行及新增文件的真实落盘结果尚待本机运行；不应声称新类别已全量下载。原股票八周期已正式落盘且重复运行验证通过，两者状态应分开记录。

## QMT 客户端可选接口限制（2026-11-15 Windows 首次实测）

真实 QMT 连接与 15/15 离线测试成功后，首批 `-Mode extras -ExtraStockLimit 1 -ExtraAssetLimit 1` 在 `xtdata.download_etf_info()` 报错：

```text
RuntimeError: 当前客户端未支持此功能，请更新客户端或升级投研版
ErrorID: 300000; ErrorMsg: function not realize
```

这来自券商客户端的 `etfredemptionlist` 下载，**不能据此断言所有 ETF 行情均不支持**。修订后的逻辑只对同样的 QMT 客户端不支持代码做明确兼容降级：

- `download_etf_info`/`get_etf_info` → `etf_catalog.status=UNSUPPORTED_CLIENT_FUNCTION`，**不生成虚假的 ETF 申赎清单**；
- `download_index_weight`/`get_index_weight` → 保留 `index_weight_cache` / 各指数权重的明确缺失状态，**不伪造指数权重**；
- **股票财务、除权、板块成分、指数及 ETF 历史 OHLCVA 的既有接口按原闸门继续运行**。任何不符合确切错误码的 QMT RuntimeError 或数据冲突仍阻止虚假的完成标记。

此前失败已写入的板块快照是允许的、且不会被重复覆盖。真实首批下载与定时调度仍需这版代码在用户 Windows 环境验收；未安装第二个定时任务。

## 2026-11-15 深夜首批财务下载长时间无输出：阶段诊断版本

第二次 QMT 真机尝试：`18/18` 离线测试通过，QMT 连接成功，`etf_catalog=UNSUPPORTED_CLIENT_FUNCTION`，`index_weight_cache=DOWNLOADED`，此后长时间无新的输出。源码执行顺序下一步是 `financial/000001.SZ`，首先同步调用 `download_financial_data([code], [])`。此处尚无法确定是 QMT 服务等待、网络耗时或客户端锁，且之前没有打印每张表的开始状态；**不应声称已经完成 1 只股票财务或指数/ETF 实际入库。**

改动：
1. 默认财务下载不再用 `[]` 隐式连下全部表，而按 QMT 的 9 个官方表名逐个下载：`Balance`, `Income`, `CashFlow`, `Capital`, `Top10FlowHolder`, `Top10Holder`, `HolderNum`, `PershareIndex`, `PerShare`。
2. 每张表打印 `MARKET_QMT_EXTRA_FINANCIAL_TABLE_START` → `FETCHED` → `COMPLETE`，即使某个表卡住也能定位是**下载接口**还是查询/写盘；每张表的成功快照独立持久化，直到全部表都完成才推进该股票游标。
3. 指数、ETF 每个 **年 × 周期** 下载窗口打印 START/DONE/EMPTY；除权因子打印下载日线及查询因子阶段标记。长时间的同步 QMT 调用仍可能阻塞，此修改是**诊断和隔离**，不是保证自动超时。
4. 新增隔离入口：`-Mode extras -ExtraSection financial|adjustments|index|etf|sectors`，仅在实际要求的类别上调用 QMT 下载；缺省 `all` 行为不变。用户 Windows 21:30 的八周期自动任务、H5、原有 8 个股票周期都不改动。
5. 当前正在运行的旧 Python 进程不会自动载入新代码。**先在原运行窗口 Ctrl+C 中止旧版采集，确认不再有 `qmt_extra_data.py` 进程，再执行 Git 拉取和新版本预检。** 若 Ctrl+C 无响应，应只终止命令行明确包含 `qmt_extra_data.py` 的 Python 进程，不能误杀运行正常的 QMT 客户端、其他 Python 或 Windows 计划任务。

独立财务试验：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File ParquetLiveSync\update-market.ps1 -Mode extras -ExtraSection financial -ExtraStockLimit 1 -ExtraAssetLimit 1 -ExtraStart "2011-01-01"
```

只想验证 QMT 其他接口而不重新触发卡住的财务：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File ParquetLiveSync\update-market.ps1 -Mode extras -ExtraSection adjustments -ExtraStockLimit 1 -ExtraStart "2011-01-01"
```

这些命令真实写入 `qmt_extra`，只有首批完成并检查记录后才考虑全市场批量或定时加入。

## 2026-11-16 ETF 首批 15min 校验失败：只诊断，不放宽

真机 QMT 首批证券 `158000.SZ`：1min 成功提交 12,773 条、5min 成功提交 2,544 条；在 **2026 年 15min** 的 `_normalize_quote` 阶段出现 `QMT index/ETF Kline OHLCVA invalid`，中断时未输出该 ETF 的 `MARKET_QMT_EXTRA_COMMITTED`。原因仍未确定，可能是某一条源 K 线异常；**不要把所有 15min 数据都视为无效，也不能把 1min/5min 作为完整 ETF 的成功标记**。原来的 8 个购买版股票周期未被触及。

为查明根因，异常信息现在带 `period`、`row_index`、`timestamp_ms`、`local_day`、实际 `open/high/low/close/volume/amount` 值及违反的条件（如 `nonpositive_low`、`high_below_open_or_close`、`non_finite`）。校验仍拒绝异常行，绝不自动填充、裁剪或丢弃，ETF 证券游标只在全周期全部成功后推进。

推荐先使用 **本地只读 QMT 缓存查询** 单独审计 `158000.SZ` 的 2026 年 `15m` 记录（调用 `xtdata.get_market_data_ex` 和 `_normalize_quote`，但不调用 `download_history_data`、`run(apply=True)`、`_atomic_parquet`），拿到精确坏行，再决定是否是 QMT 历史原始缺陷、收盘外无效记录或数值舍入。该步骤不修改 `qmt_extra` 的行情文件或进度游标。切勿直接用 `-ExtraStart 2026-01-01` 代替旧 `2011-01-01` 的全历史试验，避免未补完历史就推进完成游标。
