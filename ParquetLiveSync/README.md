# ParquetLiveSync：a-stock-data 本地 Parquet 增量更新器

核心目的：先把本地 Parquet 数据库的日线更新到最新，暂停任何 H5 写入。工具处于 AStockDataTools/ParquetLiveSync 独立目录。

## 已核实的上游来源

参照 simonlin1212/a-stock-data v3.10.4 (2026-11-04) 的 SKILL.md §1.3，Apache-2.0。
该 GitHub 仓库主要是查询数据的工具与说明，不提供可以直接下载的历史 Parquet 数据压缩包。

高效完整日线来源：通达信官网每日盘后 ZIP：
https://www.tdx.com.cn/products/data/data/g4day/YYYYMMDD.zip

ZIP 内沪深北各有 .cod 证券目录（每记录150字节）与 .md1 行情（每记录512字节），包含原始OHLC、成交量股、成交额元。来源端会在休市、未发布、过早的历史日期返回404；404只是暂未获得行情，**不代表交易日历判定**。

腾讯 §1.2 的沪深K线可以取1/5/15/30/60分钟、日周月，**没有成交额 amount**，分钟最多320根/个股，北交所不覆盖；绝不填 0 冒充成交额，也不认为八周期都已更新到最新。腾讯科创板量按股，其他股票多数为手，早期历史以及近期一天还有特殊量纲/回填限制。

## 对接现有本地数据库

固定已验收八周期物理 Parquet 数据集 SHA：
a4987bba0ce3a1f6da05242f64cc21b94b070b193b5590ddb7bbd7f9197f5b01

它的日线截至2026-10-13、14,137,981行。现有 45.59 亿行八周期数据来源不更改、不重复制。新的官方日线**仅在严格晚于2026-10-13的日期**另存为 Parquet SHA 增量帧。文件仍用同一 Arrow 数据列 ts/symbol/open/high/low/close/volume/amount，ts 按原购买 Parquet 对照日自动识别的交易日时标（以北京时间零时为基准保留实际偏移），证券如 SH600000/SZ000001/BJ920021。

官方通达信成交量为股、金额为元；为避免买入源 Parquet 量纲不同，工具第一次自动获取已有购买日线与官方重叠日（依次2026-09-30、09-24、10-13），比较至少120个重复证券及真实收盘价，验证量与额的唯一倍率。没有>=90%的正确匹配则**拒绝写入新的统一八字段日线**，不会静默混合不一致单位。此校准只认证实际对照日的观察关系，并非交易所统一的历史供应商口径。

单日增量写在 ParquetLiveSync/work/incremental/day/year=2026/YYYY-MM-DD.parquet，原始官方ZIP下载保存为 ParquetLiveSync/work/downloads/YYYYMMDD.zip，逐日SHA收据在同目录，汇总 state.json 在 work 根下。work 已被Git忽略，绝不上传付费行情或商业数据。

只读数据适配器：在Python项目中将 ParquetLiveSync 加入 sys.path，然后使用 from live_sync import open_live_dataset; 调用 open_live_dataset("day", r"D:\stock")，返回已经包含2026-10-13以前旧物理日线和其后新增日线的 Arrow Dataset。其他7周期 open_live_dataset(period, r"D:\stock")仍是老已验收来源，不会伪称全新。

历史1990-2010的H5推导日线仍留在原单独未认证研究层，**不**默认为标准日线。

## Windows 可视化运行

在 D:\ChatGPT\AStockDataTools 工作目录执行一整行：

    powershell.exe -NoProfile -ExecutionPolicy Bypass -File ParquetLiveSync\run-gui.ps1

入口会先跑20项全离线模拟回归测试，成功后打开 Tkinter 中文 GUI，展示八周期状态、日期、下载进度、日志，支持预览、开始、停止（在当前日完成后退出），不会再运行H5任务。

默认从2026-10-14取到前一个北京时间交易候选日；若当前已过北京时间20:00也允许尝试今天（仍以真实ZIP可下载为准）。建议先用3个最近日期验证，再扩大到10月14日以后的所有日期。

CLI 命令示例，使用仓库既有Python .venv：

    .\.venv\Scripts\python.exe -B ParquetLiveSync\live_sync.py --status
    .\.venv\Scripts\python.exe -B ParquetLiveSync\live_sync.py --preview --from-day 2026-10-14 --through-day 2026-11-11
    .\.venv\Scripts\python.exe -B ParquetLiveSync\live_sync.py --root D:\stock --from-day 2026-10-14 --through-day 2026-11-11 --max-days 60 --sync-day-overlay

请求单次不超过60个自然日，GUI最多180日；失败时保留已提交每日记录，重新运行自动跳过已校验SHA的交易日，未发布404将在后续重试。

## 限制与路线

- 不直接覆盖 D:\stock\AllCycleAStockData 或 D:\stock\HikyuuData，原已验历史只读。
- 2026-10-14..31 按通达信官方实际能取到的日期追加，不根据旧库存缺口编造行情。
- 源项目只提供获取方案。商业使用须遵守各官方数据源的许可与访问规定。
- 下一阶段：首次真机量纲校准和日线 Parquet 补齐确认后，增加可靠的定时增量和更全的分钟 OHLCVA 数据来源。分钟无法由无成交额的腾讯接口直接写入全部8个字段。


## 可选：首次实机验证通过后启用本地定时增量

这一步不会自动启用；仅在 GUI 完成至少一个真实交易日的日线同步、且状态和量纲校准检查通过后，由用户主动执行下面的 Install 操作。

    powershell.exe -NoProfile -ExecutionPolicy Bypass -File ParquetLiveSync\install-schedule.ps1 -Action Install
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File ParquetLiveSync\install-schedule.ps1 -Action Status
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File ParquetLiveSync\install-schedule.ps1 -Action Remove

Windows 任务计划程序将在**本机时间21:30**尝试使用既有 .venv Python 执行 ParquetLiveSync/scheduled-update.ps1。内置 --auto-recent-90-days 仅重新检查最近90天的未完成日线（已提交SHA日线直接跳过）；404仍会重试，不会重新下载45亿历史源行情。日志保存在被Git忽略的 work/scheduled-update.log。请保证本机在对应时间开机、网络连通；官方晚发布会在后续计划中再尝试。

当前只实现日线完整八字段增量：这不会擅自把腾讯缺成交额的分钟K线混入本地Parquet；其他七周期要完善必须另行接入有成交额及完整时标的可信来源。

## 2026-11-12 Windows 首次运行的文件占用修复

Windows Python 3.11 上首轮18项合成测试中5项真实 Parquet 写入均在 `temp.replace(output)` 处因 WinError 32 中断。原因是 PyArrow `ParquetFile(temp)` 保留打开的文件句柄，重命名前未关闭，并非GitHub、行情数据源或者原Parquet故障。修复后已明确 `try/finally: check.close()`，并在两项新回归测试中验证重命名前已经关闭、校验失败时也关闭（测试数量18→20）。用户新的Windows运行回执尚待验证；以前本机运行没有修改原始八周期Parquet/H5，也没有开始GUI实网下载。
