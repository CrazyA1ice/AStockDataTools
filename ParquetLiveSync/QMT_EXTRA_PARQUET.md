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

## 2026-11-16 ETF 158000.SZ 的浮点误差根因与窄修复

Windows 真机只读 QMT 缓存查询 `158000.SZ` 2026 年 `15m`（848 条）复现首个异常：`row_index=399`, `timestamp_ms=1790751600000`, 日期 `2026-09-30`，`open=1.031`, `high=1.0319999999999998`, `low=1.031`, `close=1.032`, `volume=10667`, `amount=1100778`。原严格不等式误报 `high_below_open_or_close`，实际 `high/close` 相差一个二进制浮点数 ULP（约 `2.22e-16`）。

现在 **仅在 OHLC 边界校验比较**中容许最多 4 ULP 浮点舍入差异；不改变源值、文件结构、时间戳、成交量/额校验和非有限值处理。超过 4 ULP 的逆序值以及真实非法数据仍报错；新增真实值保留、low 方向微误差和更大差异拒绝三个回归测试。

这只是确认错误根因并修正误判，**仍需本机拉取分支运行全套离线测试并重试 `-Mode extras -ExtraSection etf -ExtraAssetLimit 1 -ExtraStart 2011-01-01` 才能确认全八周期真实下载完成**。之前 1min/5min 已提交的记录留在专用 `qmt_extra/etf`，失败未推进 ETF 游标。不要改为近期起点以免历史覆盖被错误标记完成；现有购买版股票八周期/H5/21:30 任务不变。

## 2026-11-16 财务批次停滞：000006.SZ / PershareIndex

Windows QMT 第一次扩大到 `-ExtraSection financial -ExtraStockLimit 5`：`000002.SZ` 九张表全部 `MARKET_QMT_EXTRA_COMMITTED`；`000006.SZ` 到 `PershareIndex` 的 `MARKET_QMT_EXTRA_FINANCIAL_TABLE_FETCHED` 后久未继续。根据执行顺序，`download_financial_data` 已返回，后续可能卡在 `get_financial_data`、`dataframe_records`、快照序列化或 Parquet 写入。该位置尚不能证明具体原因。剩余财务证券和除权阶段尚未处理。

新增财务单表分阶段日志 `FINANCIAL_TABLE_READ_START/READ_DONE`、`DECODE_START/DECODE_DONE`、`SNAPSHOT_START` 和 `SAVE_START/SAVE_DONE`，保留旧 `START/FETCHED/COMPLETE`。新增相应回归断言；未修改数据有效性、证券游标、重叠写入、QMT 调度或原购八周期目录。这是诊断增强，**不是 QMT API 超时修复**。

如果旧 Python 任务确已长时间不再前进，先在原窗口按 `Ctrl+C`，仍无法退出时只定位并终止命令行含 `qmt_extra_data.py` 的专用 Python 进程；勿结束 QMT 客户端、勿终止无关 Python。确认不再运行后更新分支，先用单只 `-ExtraSection financial -ExtraStockLimit 1` 续跑 `000006.SZ`。不要修改进度 JSON、删除快照或直接同时启动下一个批次；停止前已提交的财务表会留在隔离目录。注意与原计划 21:30 更新避免重叠。

## 2026-11-16 中断后单张财务表复用（第一阶段）

Windows 真机 21:19 只读进度确认：`financial=000002.SZ`, `adjustments=000001.SZ`, `index=000001.SH`, `etf=158000.SZ`，专用 `qmt_extra_data.py` 进程 0。`000006.SZ` 已多次遭遇 `download_financial_data` 同步阻塞，第一次到 PershareIndex 读取附近，第二次到 CashFlow 下载附近；不应将其认为是 Parquet 数据丢失或已完成股票。

本阶段加入 `_verified_financial_snapshot`：为当天、该股票、该财务表查找先前成功落盘的单个内容指纹 Parquet 快照，严格校验 schema、每行 `asof/symbol/item/index` 与快照文件名的内容哈希；**只有全部匹配才输出 `MARKET_QMT_EXTRA_FINANCIAL_TABLE_REUSED` 并跳过重复 QMT 下载**。找不到则仍正常下载；损坏、冲突快照拒绝且不推进股票游标；不同日期快照不能抑制当天刷新。空表没有快照，仍如实查询；绝不能合成缺失财务记录。恢复后，整只股票九表均完成才推进 `financial` 游标。

这只是**同日已完成表复用**，不是对 QMT 同步 `download_financial_data` 的强制超时或自动失败队列；其余未缓存的表仍可能卡住。夜间 21:30 已有购买版自动行情任务，在其结束前不要启动新增试点。下阶段需要将单只股票 QMT 调用交由独立子进程运行，设置可验证的超时与失败分类，再实现受控队列跳过与重试，避免影响原有八周期/H5。

## 2026-11-16 财务表进程隔离与超时控制（第二阶段）

为应对真机 `000006.SZ` 先后在 `PershareIndex` 和 `CashFlow` 附近的 QMT 同步接口长期停滞，新增 `qmt_extra_financial_worker.py`。**只有 extras 模式下的财务表真实调用使用子进程**，原八周期更新、H5、已有 21:30 定时入口和其他四类 QMT 数据不改。父进程保留 `LIVE.exclusive_writer` 写入锁、进度游标与 Parquet 文件写入权；子进程仅连接 QMT、逐表调用 `download_financial_data`/`get_financial_data`，将完整原始字段及索引保存到私有一次性 JSON。父进程校验结果结构/证券/表名/大小，并原样生成和提交内容指纹快照。

默认每个未完成的财务表 **180 秒**限时，可以在原 PowerShell 入口添加 `-ExtraFinancialTimeoutSeconds 180`（合法范围 30..3600）。子进程超时由父进程终止并回收；非零退出或结果文件异常也失败关闭。**超时/失败不推进股票游标**，记录到 `ParquetLiveSync/work/qmt_extra/financial-failures.jsonl`，带 `symbol/table/asof/reason/status=PENDING_RETRY`；失败队列现为可审计待重试账本，不会悄悄越过失败的股票。前面已经正确保存的同日财务表经指纹验证后复用，故真机 `000006.SZ` 的 7 张已保存表无需再次 QMT 下载。

日志中的 `MARKET_QMT_EXTRA_FINANCIAL_WORKER_START`/`WORKER_DOWNLOAD_START`/`TABLE_FETCHED`/`TABLE_READ_START`/`READ_DONE`/`DECODE_DONE`/`WORKER_EXPORT_DONE`/`WORKER_DONE` 区分父子进程，`WORKER_TIMEOUT` 表示实际超时。该墙钟限制覆盖 **子进程启动、QMT 下载/读取及导出**；不涵盖外部 `discover`、非财务接口、父进程 Parquet 写入或退出后其余批次，因此不能声称整个市场采集已经具备全局超时/自动无人值守能力。

离线新增模拟 worker 正常返回、超时持久失败、七表缓存复用和真正剩余两表调用等测试（总共 34 项），**需 Windows 端真实运行验证后再进行单只试点**。第一次可先只用 `-Mode extras -ExtraSection financial -DryRun` 检查下一只证券，再 `-ExtraStockLimit 1 -ExtraStart "2011-01-01" -ExtraFinancialTimeoutSeconds 180` 小试。原 `000006.SZ` 在 `2026-11-16` 已有七张当日快照；跨日期不自动复用，防止将过时财报标记为当天最新数据。**跨日增量/来源版本校验尚待后续开发**，禁止靠手动修改 `progress.json` 或更改 `-Day` 冒充历史源真实时点。原有 21:30 定时任务继续单独运行，保持 extras 未启用。

## 2026-11-16 第三阶段：财务失败清单、高水位扫描与只读覆盖审计

真机 `000008.SZ` + `000009.SZ` 2 只连续采集完成（34/34 测试、批次 121.9 秒、最终 `financial.cursor=000009.SZ`）。`000008.SZ/Income` 返回 **12 条**，`000008.SZ/Top10FlowHolder` 返回 **0 条**；这只代表 QMT 观测结果，不代表历史数据完整。为了支持长批量且不丢失失败证券，本阶段实现**显式启用**的容错扫描、独立待重试集合及追加式覆盖凭证（本阶段 39 项离线测试待本机运行）。

**默认行为不变、遇到故障停止。** 只有显式使用 `-Mode extras -ExtraSection financial -ExtraFinancialContinueOnError` 时才启用容错：仅将**独立 QMT 财务 worker** 的超时、非零退出、结果内容异常记为可重试故障，原地保留已有有效快照；损坏的既有 Parquet、磁盘/权限/本地数据写入问题继续中止，禁止静默跳过。失败股票的 `table/reason/attempts/asof` 和扫描高水位 `cursor.financial` **同一笔进度文件原子保存**，输出 `MARKET_QMT_EXTRA_FINANCIAL_DEFERRED`。因此此模式下 `cursor.financial` 明确仅指**证券扫描高水位**，而不是此之前的股票全部完整成功。待补股票列在 `progress.json.financial_pending`，`BATCH_HAS_PENDING_FINANCIAL_RETRIES`、`pending_retry_count` 也会明确显示不完整。原 `financial-failures.jsonl` 仍是每次 QMT worker 失败的追加日志。

容错扫描**到尾不自动回绕**，避免重复下载已扫描证券。待补单独使用 `-ExtraFinancialContinueOnError -ExtraFinancialRetryPending`，只选待补证券、重新核验同日已有快照；成功后清除对应待补记录而**不回退高水位 cursor**。若待补证券已不在本次 QMT 股票列表中，将拒绝暗中删除，需另行审计证券名录。未显式启用这些开关时，原有股票批次、ETF/指数/除权因子以及 21:30 任务逻辑均保持原样；**无需且不应修改现有定时任务**。

本阶段将每只完成股票的九张表行数与状态记录到私有 `ParquetLiveSync/work/qmt_extra/financial-coverage.jsonl`，`0` 条记为 QMT 无返回，`1..19` 条标记 `low_record_tables`（启发式风险提示，并非统一财报最低条数）。审核既有证券可调用**不连接 QMT** 的 `ParquetLiveSync/qmt_extra_financial_audit.py --root D:/stock --symbol 000008.SZ --asof 2026-11-16`；此脚本校验当天 Parquet 指纹、逐表行数，提供源字段 `m_timetag` 的**原始最小/最大文本值**、空快照与稀疏标记；`source_report_dates_validated=false`，不得把原始字段直接认定为校准后的最早/最晚报告期。先前已提交的 000008/000009 等证券不需要重抓，也能用该只读脚本审计现有快照。新 `financial-coverage.jsonl` 只覆盖本次版本后成功执行的证券，旧数据需用只读审计查验，不能假装旧日志已回填。

建议先执行 Windows 39 项离线测试及只读审计，再做单批 `-ExtraStockLimit 2 -ExtraFinancialContinueOnError -ExtraFinancialTimeoutSeconds 180` 试点。新增开关不会自动安装任务、不会改购买版八周期 Parquet/H5，也不提供所有 QMT 调用的全局超时、跨日历史版本校验或全市场无人值守长期任务。不要靠改 `progress.json` 或 `-Day` 绕过历史覆盖问题。原有 21:30 定时任务照旧，实测仍需避开任务时间。

## 2026-11-16 第四阶段：000008.SZ 财务缓存增量补齐（保留版本）

真实 QMT 缓存只读核对：000008.SZ/Income Parquet 12 条、缓存 149 条，旧 12 条在缓存中内容不变，另有 137 条；000008.SZ/Top10FlowHolder 原无 Parquet 快照、当前 QMT 缓存 924 条。其他七表行数相同，但这不足以证明其内容相同。两个确认的数量缺口合计 1,061 条，不代表所有来源历史已完整。不能未经验证将根因断定为 xtquant 异步下载。

新增 qmt_extra_financial_reconcile.py，只针对 000008.SZ 的 Income 和 Top10FlowHolder，默认 PREVIEW。通过既有带 180 秒超时的 QMT worker 读取现有本地缓存（新增 --cached-only 入口只调用 get_financial_data，不调用 download_financial_data）。持有原 LIVE.exclusive_writer 锁以排除与已有 21:30 更新任务交叠。预览期间仅产生并清理一次性私有 worker JSON，不改正式 Parquet、progress.json、H5、定时任务或购买版八周期目录。

显式 --apply 才在 qmt_extra/financial 写入新版本。以 2026-11-16 为历史观测基准，实际新快照日期默认市场本地当天，且 --apply 强制不得伪造旧观测日期。如果已经跨日，旧的 2026-11-16 快照保留原样，新版本标注真实当天观测日。

写入必须同时满足：Income 当前缓存至少 149 条、Top10FlowHolder 至少 924 条，并且旧快照每条原始字段记录（仅忽略 pandas 定位用的 _index）严格包含在新缓存中，按记录多重集合比较。若历史记录消失或被改写、QMT 返回数量下降、快照损坏或运行失败，则拒绝提交。此校验只证明非回退，不自动宣布来源历史完整。

同一观测日可保存多个不可变快照，active/<asof>.json 指明当前选中版本。提交新版本前，先为旧有效版本保存原子选择指针，创建新 Parquet 后校验并原子切换指针；中途崩溃旧版本仍可读取。原 _verified_financial_snapshot、原补充财务采集和新增离线审计均按有效指针选取，旧文件仍保留。修复记录追加到私有 financial-repair.jsonl；不修改财务扫描 cursor 或 pending 队列，也不宣称另外七表已校验完整。

本机先运行 45 项离线单测（原 39 项已经通过），然后只读预览：
    python -u -B ParquetLiveSync/qmt_extra_financial_reconcile.py --root D:/stock --baseline-asof 2026-11-16 --timeout-seconds 180
核对 QMT_FINANCIAL_REPAIR_SUMMARY 中两张表的 extra_exact_records、cached_rows、lost_or_changed_records，确认符合预期后才可另行显式 --apply。远离 21:30 自动任务，保持八周期和 H5 原样。若预览已跨日，新的财务版本作为新日期的单独快照保存；全证券的自动历史覆盖核验及统一最新版本读取接口仍需后续开发，尚不可启用无人值守大规模运行。

## 2026-11-16 第五阶段：全市场财务数据快速续批（前台、有界、原子断点）

000008.SZ 正式版本化修复已经由 Windows 真机验收：Income 有效快照 149 条，旧 12 条快照仍保留；Top10FlowHolder 有效快照 924 条，两张表累计补齐 1,061 条，财务扫描游标维持 000009.SZ，SUCCESS 未跟踪文件保持不动。现优先推进沪深A股金融财务 **9 张表** 的全市场首轮扫描，并将历史覆盖核查另列后续质量补齐主线，严禁将游标与绝对完整性混同。

新增 qmt_extra_financial_bulk.py：默认只读预览，必须显式 --apply 才能开始采集；默认最多 30 只、360 分钟、每张财务表 180 秒 worker 墙钟超时。采用**单只股票提交**，每只完成才进入下一只。使用已有 financial_continue_on_error 高水位 + financial_pending 失败账本，失败源接口可进入待补队列并继续扫描，本地损坏或磁盘错误立即失败退出，不吞掉异常；扫描到股票池末尾后绝不自动循环回头。用户可以重复执行入口，自动读取 progress.json 的真实游标，失败清单另行安排重试，旧 000008.SZ 有效版本保持不变。

提速点：每次控制器运行从 QMT 的“沪深A股”板块**仅查询一次**证券池（返回数量和 SHA256 摘要），随后按此源定义证券池复用；不再为了每只财务股票重复查询 ETF/指数板块及基金品种分类。每次重新运行会重新获取证券池；若上市证券集合动态变化，扫描高水位之前的新增或变动需另行审计，不能视为全部覆盖完成。

为保护已有 21:30 八周期定时更新，**每日市场本地时间 21:00-23:00 不启动新的股票**，并在 21:00 之前根据 9 张表 × 单表超时 + 120 秒安全余量判断是否适合开始下一只。所有 QMT 财务下载串行进行，原 LIVE.exclusive_writer 文件锁维持独占，避免同时改动购买版八周期/H5。运行时长上限按股票边界检查而不是强杀正在执行的股票；除了单表 worker，QMT discover/父进程写盘仍不是绝对时限保证。Ctrl+C 可以中断，恢复时继续同日已验证快照。控制器**不会静默安装任务或创建后台进程**，需在本机前台运行；停止后可以重复执行续传。

先在 Windows 本机运行 53 项离线测试（前 45 项已验证，新增 8 项在本机待验收），然后以最大 10 只、最长 60 分钟进行首次有界实盘：
    python -u -B ParquetLiveSync/qmt_extra_financial_bulk.py --root D:/stock --max-symbols 10 --max-minutes 60 --financial-timeout-seconds 180 --apply
若本批成功且没有本地数据文件错误，可提升至最多 200 只、每次最长 360 分钟重复运行，仍会被 21:30 守护窗口安全停下。两种限额均在股票边界生效。日志 QMT_FINANCIAL_BULK_CHECKPOINT 列出当前 cursor、成功与失败数，QMT_FINANCIAL_BULK_SUMMARY 给出 PAUSED_SYMBOL_LIMIT / PAUSED_TIME_BUDGET / PAUSED_PROTECTED_2130_WINDOW / SCAN_EXHAUSTED_PENDING_RETRIES / SCAN_EXHAUSTED_COVERAGE_UNVERIFIED 等状态。pending_retry_count 非零时后续仍需使用此前显式 ExtraFinancialRetryPending 独立补齐，而非将这些失败视为完成。

**重要局限**：此阶段目标是尽快实现全市场财务**首轮扫描**；由于 000008.SZ 已证明 QMT 缓存在某次初读后可能出现额外历史记录，即便全部股票九表采集成功，也不能承诺历史完全。现有 financial-coverage.jsonl 仍记录每只股票的低行数和空表，后续应使用缓存对照分层抽样、质量待补队列和安全版本化补齐流程。无需重复下载购买版 K 线，不修改旧 21:30 日程。

## 2026-11-17 第六阶段：全市场挂机自动续跑（显式 --apply / --keep-awake）

首批 53/53 Windows 离线测试通过，真实 10/10 只股票连续采集成功，QMT 源证券池 5,224 只，上一批财务扫描游标为 `000026.SZ`，无失败待补；前批采集时 `PerShare` 全部空表，属于来源覆盖质量疑点，未假装为完整数据。已验证 000008.SZ 修复快照保留，购买版八周期、H5 和既有 21:30 任务不变。

新增 `qmt_extra_financial_unattended.py`，可在操作者的**前台 PowerShell** 会话中连跑到源证券池尾部或最多 45 天。内部调用已验证的 `qmt_extra_financial_bulk.scan`，每次最多 6,000 只股票或 1,440 分钟；每只股票使用原有 9 张表独立 180 秒子进程看门狗、原子进度断点、故障待补队列及全局独占写入锁。单次遇到 21:00–23:00 保护窗口或 21:00 前安全余量不足时，不会盲目继续；挂起至中国市场时间 23:05 自动唤醒并续扫。首次扫描至股票池末尾后**停止**，不从第一只重新下载，不进行无限 pending 重试。非白名单停止状态、本地文件损坏、QMT 初始化故障、进度回退等直接退出，等待人工复核。运行时长预算与保护窗口仍在**股票边界**检查，不能保证每只股票父进程绝对墙钟时限。

可显式指定 `--keep-awake`，程序仅在自身运行期间临时调用 Windows SetThreadExecutionState 防止**系统自动睡眠**，结束或异常退出时归还原有状态；不会修改 Windows 电源计划、不能防止主动休眠、系统重启、QMT 断线、断电或强制策略。Windows 显示器可熄屏，必须保持电脑通电、QMT 在线登录、PowerShell 前台会话不关闭、磁盘空间足够。脚本不创建计划任务或后台服务，`--apply` 仍为强制写入许可，`--keep-awake` 为单独明确授权。建议保存完整输出日志，故障时根据最后一个持久化游标续跑，不能删除 progress.json 或已有快照。

Windows 首先运行本分支新增的 **60 项**离线测试（之前 53 项已通过，新增 7 项需本地验收），再使用以下独立入口（**一行 PowerShell**，按需改写运行日志位置）：
    $env:PYTHONPATH=(Join-Path (Get-Location) "ParquetLiveSync"); & ".\.venv\Scripts\python.exe" -u -B "ParquetLiveSync\qmt_extra_financial_unattended.py" --root "D:\stock" --max-days 45 --max-symbols-per-session 6000 --max-minutes-per-session 1440 --financial-timeout-seconds 180 --keep-awake --apply
运行中输出 `QMT_FINANCIAL_UNATTENDED_SESSION`、`QMT_FINANCIAL_UNATTENDED_WAIT`、`QMT_FINANCIAL_UNATTENDED_FINAL`。最终 `SCAN_EXHAUSTED_COVERAGE_UNVERIFIED` 表示首轮已达到 QMT 当前股票列表末尾（不代表每条历史记录完整）；若为 `SCAN_EXHAUSTED_PENDING_RETRIES` 表示仍有失败股票需要专门补抓；`STOPPED_MAX_DAYS` 表示达到设定挂机天数需复核再重启。**整市场约五千只股票，按首次 10 只约一小时的观察量级，通常无法在一晚下载完**；本入口跨天自动续跑且不绕过 21:30 定时任务。

请勿和此前的 qmt_extra_financial_bulk.py 单独启动命令同时执行。脚本会在首次启动时用进度文件决定下一只股票，不再硬编码 `000026.SZ`。下载到尾后不会自动执行历史覆盖修复；空表和稀疏表仍进入单独审计任务。若下载进程结束仍存在 `financial_pending`，应运行先前已支持的显式待补重试模式并单独核验。

## 2026-11-17 第七阶段：QMT 已缓存财务数据批量导入 Parquet + 每日公告增量

用户截图显示 D:\software\JHQMT\datadir\Finance\SZ\86400 下按股票代码和报表编号保存的 .DAT 文件，与 XTData 日志返回的 datadir 对应；但文件存在本身不证明 5,224 只股票每张财务表都完整。无需自行逆向 .DAT。迅投官方支持 xtdata.get_financial_data(stock_list, table_list, start_time, end_time, report_type) 读取现有本地缓存，以及同步 xtdata.download_financial_data2(stock_list, table_list, start_time, end_time) 按 m_anntime 公告日期窗口补充财务数据。首次导入模式只调用 get_financial_data，不调用任何下载 API；每日模式才按设定窗口调用 download_financial_data2，再读取缓存里的完整表做并集验证和版本更新。

如显式指定 --finance-dir D:/software/JHQMT/datadir/Finance，还会只读枚举 SH、SZ、BJ 三个 86400 子目录中财务文件的合法股票代码（不读取或反解 .DAT 文件内容），与 QMT 当前沪深A股名单合并。这样能够补充本机已有缓存中的历史/退市代码及北交所文件；没有对应缓存时必须通过 pending 披露，不能假装已经完整导入。不指定目录则只扫描当前沪深A股板块，不能称为所有历史股票。

新增 ParquetLiveSync/qmt_extra_financial_cache_worker.py：默认每批 5 只股票、一次多股票九表读取，最大 20 只，单批超时由父进程看门狗强制中止，全部中间结果只放临时私有 JSON 并回收。第九张 PerShare 在已有样例中是空表；每日向 QMT 下载时仅提交文档可支持的其他八表，读取仍包含九表，绝不凭空制造数据。原始字段加 _index 原样保存到 qmt_extra/financial，旧版 Parquet 主八周期和 H5 不变。

新增 qmt_extra_financial_cache_import.py：--mode cache 实现历史 QMT 本地缓存直接入库；--mode daily 仅下载最近 120 天（可调）公告窗口，再从缓存读取全表进行内容核对。以独立的 work/qmt_extra/financial-cache-progress.json 维护 import_cursor、daily_date、daily_cursor 和独立 pending 队列，不碰原有 financial.cursor。每日模式必须等第一次缓存导入的独立扫描游标达到最新 QMT 股票池末尾才开放，防止把未完成的初始导入误当成完成。来源暂缺的股票记 NO_CACHE，旧记录消失/修订则记 SOURCE_HISTORY_CONFLICT 并保留旧版，不自动覆写；原始记录逐条比对仅忽略 Pandas _index。比较范围包含同一财务表所有历史已选中有效快照的记录并集；新数据必须严格包含旧内容，不满足则待审。相同数据不重复写快照，同一天数据增长先将旧版设为 active 指针再创建新的不可变 Parquet 并原子切换。空源表只记审计，不能证明历史完整。每只股票提交后独立游标原子持久化，磁盘、数据损坏或 QMT 批调用报错均直接失败停止；持有已有 LIVE.exclusive_writer 独占锁，按中国市场时间 21:00 至 23:05 避免启动新批次。

先在 Windows 本地跑 73 项离线测试（以前 60 项已通过；新增 13 项尚未实机验收）。停止原 qmt_extra_financial_unattended.py 等全量下载后，QMT 保持启动登录；先选股预览：
    python -u -B ParquetLiveSync/qmt_extra_financial_cache_import.py --root D:/stock --finance-dir D:/software/JHQMT/datadir/Finance --mode cache --max-symbols 2
再试导前两只：
    python -u -B ParquetLiveSync/qmt_extra_financial_cache_import.py --root D:/stock --finance-dir D:/software/JHQMT/datadir/Finance --mode cache --max-symbols 2 --batch-size 2 --worker-timeout-seconds 300 --apply
成功后继续剩余整个当前股票池：
    python -u -B ParquetLiveSync/qmt_extra_financial_cache_import.py --root D:/stock --finance-dir D:/software/JHQMT/datadir/Finance --mode cache --max-symbols 10000 --batch-size 5 --max-minutes 1440 --worker-timeout-seconds 300 --apply
重复执行仅处理最新 import_cursor 以后的证券；PAUSED_* 说明时间边界停下，可续跑；SOURCE_UNIVERSE_EXHAUSTED 是当前 QMT 股票池第一轮已扫至尾部，须检查 pending_total，不能替代来源历史完整性验证。

每日增量手动入口：
    python -u -B ParquetLiveSync/qmt_extra_financial_cache_import.py --root D:/stock --finance-dir D:/software/JHQMT/datadir/Finance --mode daily --max-symbols 10000 --batch-size 5 --worker-timeout-seconds 300 --max-minutes 1440 --lookback-days 120 --apply
新增 run-qmt-financial-daily.ps1 入口会保存独立 transcript 日志。register-qmt-financial-daily.ps1 默认仅预览，显式使用 -Install 才创建名为 AStockDataTools-QMT-Financial-Daily 的独立本机时间 00:30 每日 Task Scheduler 任务（中国时间 UTC+8 或日本时间 UTC+9 环境下，均在中国市场 21:00-23:05 保护窗口之后），绝不覆盖已有 21:30 任务；只在用户登录的交互会话运行，需要 QMT 保持在线。此新任务不可在初始导入成功验收前安装。日期窗口下载无法保证追溯更早历史修订，所以继续保留周期性的全量缓存只读覆盖核对和 pending 人工审查。

## 2026-11-17 第八阶段：QMT UTF-8 解码截断导致五股缓存读取失败时安全恢复

首次 QMT 本地财务缓存的真机长时导入已达到至少 4,845 只成功股票，pending=16。上次最后明确的完整游标 688253.SH，此后 688255.SH 提交日志被截断，下一批 688256.SH..688260.SH 在 QMT xtdata.get_financial_data 内发生 UnicodeDecodeError: utf-8 unexpected end of data，旧版 importer 因 worker exit=1 中止；并非 Parquet 读取损坏。该情况可能由 QMT 批量结果解码截断或单只股票特殊源字段导致，不能直接推断 DAT 损坏。正式 qmt_extra/financial 快照和独立 import_cursor 均逐只安全保留，严禁删除、清零或从首股重新扫描。

新增 worker 对特定 UnicodeDecodeError 捕获及专用 exit 85。Importer 接到专用 85 时仅额外重试一次该批（不会重试磁盘/通用运行异常）；仍失败才将当前批次递归拆为更小组，逐只定位，能正常读取的股票照常版本化落盘。确实在单只缓存上重复出现 UTF-8 解码失败的证券进入独立 pending，reason=CACHE_DECODE_ERROR，不与 NO_CACHE 混淆，游标仍继续；若连续三个不同单股都存在 UTF-8 错误则保守终止，避免 QMT 全局损坏/断线被误判为大量异常股票。pending 证券可通过原 importer 的 --retry-pending 显式重试，历史内容不被覆盖。其他 worker 非零状态、单批超时、Parquet 校验错误依旧立即停止，不做宽泛的吞错或无限重试。

本阶段在原 73 项测试基础上增加 4 项（预期 77 项）：批错误拆分/单股待补/后续恢复；连续三个解码错误熔断；exit 85 仅重试一次；其他错误绝不被吞。新增代码仍需 Windows + QMT 实际验收。测试通过后从已有 import_cursor 进行最多 30 股的短批续扫（--batch-size 5，--max-symbols 30），查看 QMT_CACHE_BATCH_UTF8_SPLIT 与 QMT_FINANCIAL_CACHE_PENDING 的结果，确认 pending 合理后才继续 max-symbols 10000 的剩余本地缓存导入。除显式 --apply 的缓存快照外，购买版八周期/H5、21:30 任务不变；新补丁没有重新调用任何全历史下载 API。

## 2026-11-17 第九阶段：全市场首轮完成后的 17 个财务待补项分流

QMT 本地 Finance 文件名并集为 5,656 只，首轮缓存导入于 2026-11-17 跑至 920992.BJ，状态 SOURCE_UNIVERSE_EXHAUSTED。独立财务缓存 pending=17：其中 16 只为早期 000001.SZ、000002.SZ、000006.SZ、000007.SZ、000008.SZ、000009.SZ、000010.SZ、000011.SZ、000012.SZ、000014.SZ、000017.SZ、000019.SZ、000020.SZ、000021.SZ、000025.SZ、000026.SZ 的 Capital 历史记录严格内容对比不一致（旧行差异数分别 154、159、141、148、169、194、116、151、175、124、133、136、123、132、143、158）；另 688259.SH 在批量拆分后仍反复出现 CACHE_DECODE_ERROR。旧 Parquet 未覆盖，pending 均为独立、可追溯记录。该分布暗示前期采集批次与当前缓存可能存在共同的 Capital 数据表示/修订差异，但根因尚未核实，不能把全部旧数据直接替换，也不能说全部 5,656 只数据无缺失。

新增 qmt_extra_financial_conflict_diagnose.py：默认对 000008.SZ、000001.SZ 分别**只读**比较历史有效 Capital Parquet 与现有 QMT 缓存两种读取方式（单股票单表、单股票九表）；输出精确记录重合度、旧缺记录数、列集合、匹配报告期的具体变化字段/数值/类型样本，以及单表与九表 API 的直接差异。只调 QMT 缓存的 get_financial_data，不调下载接口，不改快照、active 指针、financial-cache-progress.json、高水位或旧 21:30 任务；QMT 子进程临时文件会自动删除，运行时持独占数据锁。诊断须先在 Windows 运行本分支全部 79 项离线测试（新增 2 项尚未真机确认），确认输出后再决定是修正规范化、另存来源修订版本，还是继续隔离。不要在诊断前用 --retry-pending 对这 16 只强制覆盖；688259.SH 解码错误另做分表只读定位，不能以 replacement 字符或忽略编码错误方式静默修数据。
