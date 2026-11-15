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
