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

它的日线截至2026-10-13、14,137,981行。现有 45.59 亿行历史八周期数据不重新下载或转换。新官方日线从严格晚于2026-10-13的日期开始先生成SHA私有增量帧；GUI默认还会安全合并到 `D:\stock\AllCycleAStockData\day\YYYY-MM.parquet`，原月文件更新前先备份。文件仍用同一 Arrow 数据列 ts/symbol/open/high/low/close/volume/amount，ts 按原购买 Parquet 对照日自动识别的交易日时标（以北京时间零时为基准保留实际偏移），证券如 SH600000/SZ000001/BJ920021。

官方通达信成交量为股、金额为元；为避免买入源 Parquet 量纲不同，工具第一次自动获取已有购买日线与官方重叠日（依次2026-09-30、09-24、10-13），比较至少120个重复证券及真实收盘价，验证量与额的唯一倍率。没有>=90%的正确匹配则**拒绝写入新的统一八字段日线**，不会静默混合不一致单位。此校准只认证实际对照日的观察关系，并非交易所统一的历史供应商口径。

单日增量写在 ParquetLiveSync/work/incremental/day/year=2026/YYYY-MM-DD.parquet，原始官方ZIP下载保存为 ParquetLiveSync/work/downloads/YYYYMMDD.zip，逐日SHA收据在同目录，汇总 state.json 在 work 根下。work 已被Git忽略，绝不上传付费行情或商业数据。

只读数据适配器：在Python项目中将 ParquetLiveSync 加入 sys.path，然后使用 from live_sync import open_live_dataset; 调用 open_live_dataset("day", r"D:\stock")，返回已经包含2026-10-13以前旧物理日线和其后新增日线的 Arrow Dataset。其他7周期 open_live_dataset(period, r"D:\stock")仍是老已验收来源，不会伪称全新。

历史1990-2010的H5推导日线仍留在原单独未认证研究层，**不**默认为标准日线。

## Windows 可视化运行

在 D:\ChatGPT\AStockDataTools 工作目录执行一整行：

    powershell.exe -NoProfile -ExecutionPolicy Bypass -File ParquetLiveSync\run-gui.ps1

入口会先跑40项全离线模拟回归测试，成功后打开 Tkinter 中文 GUI，展示八周期状态、日期、下载进度、日志，支持预览、开始、停止（在当前日完成后退出），不会再运行H5任务。

默认从2026-10-14取到前一个北京时间交易候选日；若当前已过北京时间20:00也允许尝试今天（仍以真实ZIP可下载为准）。建议先用3个最近日期验证，再扩大到10月14日以后的所有日期。

CLI 命令示例，使用仓库既有Python .venv：

    .\.venv\Scripts\python.exe -B ParquetLiveSync\live_sync.py --status
    .\.venv\Scripts\python.exe -B ParquetLiveSync\live_sync.py --preview --from-day 2026-10-14 --through-day 2026-11-11
    .\.venv\Scripts\python.exe -B ParquetLiveSync\live_sync.py --root D:\stock --from-day 2026-10-14 --through-day 2026-11-11 --max-days 60 --sync-day-overlay --materialize-local-day

请求单次不超过60个自然日，GUI最多180日；失败时保留已提交每日记录，重新运行自动跳过已校验SHA的交易日，未发布404将在后续重试。

## 限制与路线

- H5 永不修改。GUI默认对已验收的新日线安全更新 D:\stock\AllCycleAStockData\day\当年-月份.parquet，更新前会备份旧文件、完整回读并计算SHA。其余七周期的历史原文件保持只读。
- 2026-10-14..31 按通达信官方实际能取到的日期追加，不根据旧库存缺口编造行情。
- 源项目只提供获取方案。商业使用须遵守各官方数据源的许可与访问规定。
- 下一阶段：首次真机量纲校准和日线 Parquet 补齐确认后，增加可靠的定时增量和更全的分钟 OHLCVA 数据来源。分钟无法由无成交额的腾讯接口直接写入全部8个字段。


## 可选：首次实机验证通过后启用本地定时增量

这一步不会自动启用；仅在 GUI 完成至少一个真实交易日的日线同步、且状态和量纲校准检查通过后，由用户主动执行下面的 Install 操作。

    powershell.exe -NoProfile -ExecutionPolicy Bypass -File ParquetLiveSync\install-schedule.ps1 -Action Install
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File ParquetLiveSync\install-schedule.ps1 -Action Status
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File ParquetLiveSync\install-schedule.ps1 -Action Remove

Windows 任务计划程序将在**本机时间21:30**尝试使用既有 .venv Python 执行 ParquetLiveSync/scheduled-update.ps1，并默认将通过校验的日线合并进本地规范月文件。内置 --auto-recent-90-days 仅重新检查最近90天的未完成日线（已提交SHA日线直接跳过）；404仍会重试，不会重新下载45亿历史源行情。日志保存在被Git忽略的 work/scheduled-update.log。请保证本机在对应时间开机、网络连通；官方晚发布会在后续计划中再尝试。

当前只实现日线完整八字段增量：这不会擅自把腾讯缺成交额的分钟K线混入本地Parquet；其他七周期要完善必须另行接入有成交额及完整时标的可信来源。

## 2026-11-12 Windows 首次运行的文件占用修复

Windows Python 3.11 上首轮18项合成测试中5项真实 Parquet 写入均在 `temp.replace(output)` 处因 WinError 32 中断。原因是 PyArrow `ParquetFile(temp)` 保留打开的文件句柄，重命名前未关闭，并非GitHub、行情数据源或者原Parquet故障。修复后已明确 `try/finally: check.close()`，并在两项新回归测试中验证重命名前已经关闭、校验失败时也关闭（测试数量18→20）。用户新的Windows运行回执尚待验证；以前本机运行没有修改原始八周期Parquet/H5，也没有开始GUI实网下载。

## 2026-11-12：遵照 D:\stock\AllCycleAStockData 本地物理归档标准

**自动路径识别**：Windows GUI 默认 `D:\stock`，新 `local_layout.storage_root()` 自动识别 `D:\stock\AllCycleAStockData`，也可以直接传 `D:\stock\AllCycleAStockData` 作为路径；八个合法周期固定为 `1min,5min,15min,30min,60min,day,week,month`。界面显示每个周期已有多少年度文件、当年有几个月文件、真实存储目录；不从GitHub下载现成Parquet。

**统一命名规则**：`D:\stock\AllCycleAStockData\<period>\2011.parquet ... 2025.parquet` 为往年整年文件；当前2026年的所有周期使用 `2026-01.parquet ... 2026-12.parquet`（仅实际有数据的月份才创建）。这与用户 Windows 截图中的 day 目录相同。新 GUI 的「把已校验的新日线合并进实际本地年月文件」选项默认勾选。日线 2026-11-09、10、11 成功下载之后，它们都合入**同一份** `D:\stock\AllCycleAStockData\day\2026-11.parquet`，不会每天在主库产生一个 YYYY-MM-DD.parquet。重复同键保留原本地数据，不覆盖已存在的正版行情值。

**10月缺口保护**：截图中的购买日线月文件截止2026-09，但接受的旧 A 股私有 Parquet 完整日线已覆盖到2026-10-13。首次创建或补全 `day\2026-10.parquet` 时，先只读从 SHA 绑定的旧16年完整日线导入 **2026-10-01..10-13 已有交易记录**，再加入官网新下载的2026-10-14以后行情。不能让月文件只存在10月后半月而遗漏已验数据；之后其他10月日期直接合入当前月文件，不重复查询16年旧库。

**修改原月文件的安全流程**：所有原文件原 SHA → 私有 `ParquetLiveSync/work/backups/day/` 备份且核验 → 将原有整月记录与新记录做 (标准化证券代码, ts) 唯一键合并且保留原值 → 新月文件写临时 Parquet → 读取完整文件核对 schema/行数/全部 Arrow 值 → 写耐久事务日志 → 最后 `os.replace()` 原子替换月文件。Windows ParquetFile 始终显式关闭。停电发生在重命名之前可按旧 SHA 恢复，发生在之后但状态未写入时可按事务日志新 SHA 恢复。月文件已有且新日期全部存在时无需重复改写；不修改 H5。

**年度归档**：每年结束后，`local_layout.rollover_all_periods(root,上一年,workspace,apply=False)` 对八周期做统一只读预检；在所有周期均已有全年文件或12个月的完整月文件后，GUI 点击「跨年归档检查」并确认才执行。程序以有界内存扫描12个月，磁盘SQLite验证全年度证券+时间键唯一，生成完整 `YYYY.parquet`，经SHA与行数回读且**先保存原12个月的私有完整SHA备份**，再将原月文件从标准期目录移走；可在中断后按事务计划继续清理。若去年某周期还缺月份，整批拒绝归档，不会制造缺失月份假数据。注意：归档搬移物理月文件将使旧的不可变八周期清单中硬编码月路径的读取器需要另行重建清单；此操作**不自动启动**。

**当前数据源能力**：`TDX g4day` 只够让 `day` 周期自动更新到最新并实际合并月文件；另外七周期的**目录识别、年月分区、规范月文件增量合并、跨年归档及本地Arrow读取接口**已经通用化，但**尚无可靠完整OHLCVA源来更新它们的最新行情**，不会将腾讯没有成交额的分钟价格直接充当完整八字段行情。

新使用方式（Windows PowerShell 单行命令）：

    .\.venv\Scripts\python.exe -B ParquetLiveSync\live_sync.py --root D:\stock --inspect-local-layout
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File ParquetLiveSync\run-gui.ps1
    .\.venv\Scripts\python.exe -B ParquetLiveSync\live_sync.py --root D:\stock --from-day 2026-10-14 --through-day 2026-11-11 --sync-day-overlay --materialize-local-day

要以**真正存放在指定年月文件中**的数据为研究数据源，而非旧SHA快照虚拟叠加入口，可用 `from local_layout import open_local_layout_dataset`，然后 `open_local_layout_dataset(r'D:\stock','day')`，返回对 `AllCycleAStockData/day/{2011.parquet,...,2026-11.parquet}` 的只读 PyArrow Dataset，不会同时读入月份与对应全年文件造成双计。

截至本提交，新增14项纯临时八周期原生Parquet/归档/10月预先补齐测试，加上此前20项数据源/ZIP/Arrow测试，总计**40项**。尚未在用户Windows下进行本次新逻辑的实机测试；不要声称已将最新日线真正写入 D:\stock。

## 2026-11-12：官网盘后包有收盘参考价但无交易量导致GUI误报的真实修复

用户首次GUI请求2026-10-14..10-31时弹窗 `Invalid active A-share OHLCVA in official daily package`。旧的校验器错误要求每只出现收盘价的A股都有非零开高低与非零成交，即使来源本身只是停牌或零交易参考报价。修复后统一分为：

- `close>0; volume=0; amount=0`：按**无真实成交报价**记录到来源统计和逐日SHA收据，不用零开高低造出假交易K线，也不以错误行情混合进物理年月Parquet；若一市场此类异常超过候选A股20%/300条则拒绝整日以防残缺源包；
- `volume>0` 但成交额为零或负、价格结构明显无效：严格拒绝整日，错误包含来源日期、证券代码、前收/开高低收、成交量、成交额与原ZIP摘要；
- `close<=0` 但原字段存在真实成交：拒绝而不是无声跳过；所有非有限数值依然强制拒绝；
- 作为自动量纲对照的首个原始交易日有特异/损坏ZIP时，只拒绝该**校准日**并记录来源异常，再尝试其他已验收的2026-09-24/10-13原购买重叠日；实际下载目标日仍必须完整通过严校验。
- 因真实异常导致的源ZIP拒收（不是HTTP 404）将保存为私有 `ParquetLiveSync/work/rejected_official_tdx/YYYYMMDD-<SHA16>.zip`，绝不写入原市场文件，也不会标记下载成功。GUI会显示具体异常，方便只读诊断；诊断工具 `ParquetLiveSync/probe_official_zip_readonly.py --date YYYY-MM-DD [--zip 已有文件]` 不修改Parquet或H5。

**实际校准日复核**：GitHub Actions 也使用2026-09-30官网ZIP作了公开数据检查，SHA256 `2699353d2851d4a13841c2014e9323720d3d9ec912a203a8d5046de2f2e35e36`。同样发现沪市5条零成交且开高低为零、收盘参考价有效的报价；修复后正确接受**5,560条有效A股交易记录**，`strict_source_accepted=true`。因此原GUI首个量纲校准基准日2026-09-30也存在同一类可以确认的旧校验错误。真实来源检测：https://github.com/CrazyA1ice/AStockDataTools/actions/runs/43148853933

**真实公开样本证据**：GitHub Actions 用2026-10-14官网ZIP做了网络直读，原始SHA256 `cfa745c7972fe52f698e829aacf7f21db947ddacd722ef6368f24c64ffb60ec6`，发现沪市5条 `close>0, open=high=low=0, volume=amount=0` 参考报价：SH600293、SH600825、SH601059、SH601198、SH688496。新解析器接纳其余 **5,562条有效A股成交记录**（沪2315、深2898、京349），对这5条不伪造成交K线。实证CI：https://github.com/CrazyA1ice/AStockDataTools/actions/runs/43148666361

新版本已在 Windows/Linux 上执行40项ZIP、量纲、Parquet实写、年月分区、跨年归档、断点和来源异常的全离线回归测试，另有2026-10-14真实公开盘后包校验。**这不是用户本机量纲校准和落库的成功回执**。用户需关闭旧GUI、更新脚本并重新尝试，并检查2026-10-14和当年月文件是否真正通过SHA/业务合并。

## 2026-11-12：日线已补至2026-11-11，开始安全派生周线/月线

用户 Windows 截图与实测日志：2026-10-14..30新增官方日线13个交易日72,375条；原购买日线2026-10-01..13共22,191条先补种，`D:\stock\AllCycleAStockData\day\2026-10.parquet`总94,566条；2026-11-02..11新增8个交易日44,569条，`day\2026-11.parquet`真实落盘。累计新TDX日线21个交易日116,944条。原 H5 未修改，其他周期至今仍为原数据。当前任务转向周/月线研究，不是重新处理日线或H5。

新增 `rollup_week_month.py`、`tests/test_rollup_week_month.py`、`run-week-month-readonly.ps1`。它不使用没有成交额的腾讯分钟接口；使用**已经真实写入的八字段日线OHLCVA**进行周/月聚合，分别取首个有交易日开盘、全周期最高/最低、最后有交易日收盘、整周期成交量与成交额之和；必须比对旧购买周/月源，否则不写。

安全门：从当前真实 `D:\stock\AllCycleAStockData\day|week|month\2026-05.parquet` 至09月文件抽取同符号/对应周或月，要求至少300条来源，旧周期价格OHLC匹配率>=94%、全量价额匹配率>=90%；而原购买周/月时间标签是周五、下周一、该月交易日最后日、日历月末等哪一种，只能靠真实旧文件>=92%匹配推断，分钟时刻偏移也要>=92%。跨月不完整周、交易周不足3天的样本不作为校准证据，避免用有误差的数据制造伪确认。**若旧周/月与日线量纲或时间规则不一致，工具坚决拒绝写入原周/月目录并输出具体理由。**

新周期完整性门：每个要派生的周或月必须已经结束，2026-10-14之后每个工作日日线都须有真实SHA日增量的已验收记录；不能把工作日404当成自动休市。还需确认2026-10-08、09、12、13四个真实购买日键已存在，避免生成缺前半月的2026-10月线。2026-11-09..13本周及2026-11整月未结束时不能写入，不会虚构。

独立入口默认**只读预检**（不下载、不修改本地市场文件）：

    powershell.exe -NoProfile -ExecutionPolicy Bypass -File ParquetLiveSync\run-week-month-readonly.ps1

GUI新增「核验周线/月线」按钮：后台执行严格只读校准，输出周/月对应的旧购买源匹配率、时间戳习惯和预计要写到哪些当年月文件。只有这一步通过，第二个「写入已完成周/月」按钮才可以点击，并会在用户确认后重新校验，在独占写锁下借用已验的 `local_layout.write_month()` 安全备份、同键去重、保留原记录、写临时Parquet、完整Arrow读回、SHA和事务日志，然后合并到 `D:\stock\AllCycleAStockData\week\2026-10.parquet`、`week\2026-11.parquet`、`month\2026-10.parquet`（以实际旧文件校准结果为准）。仅会更新上述两个周期；原日线、其余5个分钟、H5及未完结周/月不变。

CLI显式授权写入（只有已完成严格预检并确认风险后才能使用）：

    .\.venv\Scripts\python.exe -B ParquetLiveSync\rollup_week_month.py --root D:\stock --apply-to-local-week-month

新周/月派生逻辑另有6项真实临时Arrow Parquet/时间标签/缺失交易日/金额口径/仅已结周期/实际月文件合并测试；与原40项合计46项。代码先在Windows/Linux CI 通过，再用真实本地购买周/月源只读做校准。**在未拿到真实周/月口径验收结果前，不得声称周线/月线已同步到最新。**

## 2026-11-12：日线、周线、月线一键安全增量

根据用户Windows真实回执，2026-11-11日线已新增21个交易日116,944条，并在真实购买源2026年5—9月校准出周/月时间戳为最后交易日北京时间零时：周线100,847条样本，OHLCVA吻合率0.999732，时标吻合率1.0；月线28,091条样本，OHLCVA吻合率1.0，时标吻合率1.0。用户在本地成功物理写入：

- AllCycleAStockData/week/2026-10.parquet：16,712条
- AllCycleAStockData/week/2026-11.parquet：5,573条（11月2—6日的完整周）
- AllCycleAStockData/month/2026-10.parquet：5,576条；尚未结束的11月整月不输出

新增 update_pipeline.py，默认不联网、不写市场数据，仅查看计划；明确加 --apply 才执行日线→已结束周/月线的顺序增量。CLI：

    .\.venv\Scripts\python.exe -B ParquetLiveSync\update_pipeline.py --root D:\stock
    .\.venv\Scripts\python.exe -B ParquetLiveSync\update_pipeline.py --root D:\stock --recent-days 90 --apply

第一步沿用已验官方TDX原始日线下载、盘后校验、量价额系数校准、SHA确认及day/YYYY-MM.parquet按月安全合并；第二步重新比对原购买2026年5—9月周/月OHLCVA及时间标签，确认衍生周期的工作日已收齐、周期已结束，对所有拟写入week/month月份文件做同键OHLCVA全字段预检，不符合则在任何周/月目标物理文件改写前拒绝；然后才SHA备份+文件原子替换。同键重复运行时原OHLCVA必须与推导值匹配，不能只看存在就跳过。

新GUI按钮「一键更新日/周/月」必须用户明确确认后才会联网并写入；之前已有的「开始下载并补齐日线」「核验周线/月线」「写入已完成周/月」仍单独存在。可安全停止日期循环，日线已验记录保留，未完成的周期下次自动重算。日线成功而周/月校验失败会明显报错，不会伪装3周期全部完成。

定时任务由用户主动安装。当前 scheduled-update.ps1 默认保持DAY_ONLY，不会悄悄改变已有任务的行为。只有用户明确加 -IncludeClosedWeekMonth 才启用三周期定时增量，21:30使用Windows本机时钟：

    powershell.exe -NoProfile -ExecutionPolicy Bypass -File ParquetLiveSync\install-schedule.ps1 -Action Install -IncludeClosedWeekMonth

新增7项一键主流程离线测试及2项周/月已存在同键的逐字段对照与重复运行测试；与此前46项合计55项。Windows/Linux CI会执行这些真正临时Parquet文件和模拟HTTP ZIP的测试。H5、五个分钟周期继续保持原状。

## 2026-11-12：简化 GUI、定时任务状态、五周期分钟行情候选下载

默认启动脚本 ParquetLiveSync/run-gui.ps1 已切换到紧凑版 gui_simple.py。主界面只保留「更新日/周/月」「开始分钟下载」「停止」「刷新状态」，详细日志可点击查看/隐藏。旧高级界面 gui.py 仍保留；不会自动安装或修改定时任务。

电脑关机期间不会运行任务。已安装计划任务用 -StartWhenAvailable，重新开机且运行条件满足时Windows会尝试补运行（微软默认延迟约10分钟；并不保证立即、也不能在没电时运行）。目前无 WakeToRun，因此睡眠中不会自动唤醒电脑。每次日线任务重查最近90天，已验收日期跳过；仍受源网站ZIP保留期限和网络条件限制。

原版本默认不提供桌面成功/失败通知，是否看到PowerShell窗口取决于Windows任务运行会话。新版 scheduled-update.ps1 将最近一次完成状态 SUCCESS/FAILED、时间、模式持久保存到 work/last-scheduled-run.json，在简化GUI直接展示；完整运行日志保存在 work/scheduled-update.log。新版 install-schedule.ps1 用 -WindowStyle Hidden 申请不显示任务命令行窗口，但只在用户主动重新安装任务后才会更新已注册的任务配置；普通 Git pull 不会改变当前计划任务。

分钟行情候选源为东方财富公开接口（不是上游a-stock-data仓库中包含的可下载分钟Parquet）：1min使用 trends2/get ndays=5（仅近期，可能无法追补较早日期），5min/15min/30min/60min使用 kline/get 的klt=5/15/30/60、fqt=0不复权。必须区分字段语义：5/15/30/60min 的 kline/get 为 f51日期、f52开盘、f53收盘、f54最高、f55最低、f56来源成交量、f57成交额；但1min trends2/get 是 f51时间、f52价格（历史记录常为0）、f53均价、f54最高、f55最低、f56量、f57额，**不能把 f52/f53 错当作1分钟开盘/收盘**。因此1min目前仅保留原始分时资料，不合并K线数据库。

新 GUI 的分钟区可以选「三只样本」或「全市场下一批10只」，均可点击「开始分钟下载」。样本默认沪深北各1只；批量从当前本地已验收日线最后一天提取约五千多只真实A股代码，每次最多10只，已通过候选下载的股票记录私有断点，重复运行继续下一批。下载响应的SHA、各周期起止时间、逐日数量及异常收据都在被Git忽略的 work/minute_source_trials；完全不修改AllCycleAStockData下任何5个分钟周期的正式Parquet或H5。

CLI小样本：
    .\.venv\Scripts\python.exe -B ParquetLiveSync\minute_probe.py --symbols SH600000,SZ000001,BJ920021
CLI续跑批量：
    .\.venv\Scripts\python.exe -B ParquetLiveSync\minute_batch.py --root D:\stock --limit 10

GitHub Actions在2026-11-12对SH600000实际联网验证：5min=600根、15min=512根、30min=256根、60min=128根，四周期均含开高低收、来源成交量和成交额；1min trends2虽有分时价格、均价、最高最低和量额，但缺可证明的OHLC开/收，必须留在SOURCE_DOWNLOADED_BUT_OHLCVA_UNVERIFIED（原始JSON按SHA缓存），不能由均价伪造收盘价。批量「候选已缓存X只」表示取得**4种K线+1种分时原始响应**，并不表示全五周期K线都可使用。未完成北交所覆盖、量纲、时间戳和完整性验收之前，正式分钟Parquet全部不修改。

正式自动同步仍为三周期日线/周线/月线。五个分钟周期已进入同一GUI中的可验证公开源下载阶段，未声称全市场分钟数据更新完成。

## 2026-11-12：分钟线真正的历史分页、原购买校准与11月四周期安全落库

原来的三只股票分钟试下载观察：1min trends2仅原始趋势、不能直接构造OHLCVA；5min在沪深京真实返回600根、15min真实返回496根、30/60min部分曾遇RemoteDisconnected，API偶发断开不是内容校验成功。后续新增 HTTP 超时/连接中断/429/5xx最多4次新连接退避重试，不把结构异常的行情当作成功。

真实联网重要突破：同一沪市股票SH600000，官方公开历史分钟K线接口指定 end=2026-09-30 实际返回该日及以前的288根；end=2026-10-20实际返回2026-09-24..2026-10-20 600根，表明end日期向后翻页**真实可用**，不是只有近期600根。不同日请求可能断开，采用独立校验和断点。探针：ParquetLiveSync/probe_minute_history_window.py。来源：东方财富 push2his kline/get，非上游 a-stock-data 包自带。

新增 minute_history.py：按实际返回最早日-1逆向分页（不能按日历天数猜行数），逐股票逐周期保存源响应SHA及URL日期，禁止意外未来K线或同键冲突。新增 minute_5m_rollup.py：只接受全天沪深京真实股票的精确48根5m K线，其中上午09:35..11:30共24根、下午13:05..15:00共24根；每连续3/6/12根在各自上午/下午交易段内产生15/30/60m聚合。最高最低、首开末收、成交量额求和，少一根则整股票日隔离。这减少了每股票重复请求4套周期的负担，1min**没有**由5min伪造。

新增 minute_paid_calibration.py：用D:/stock/AllCycleAStockData/{5min,15min,30min,60min}/2026-09.parquet中的真实购买原始数据与官方公开09-30来源（5m原始及其分组15/30/60）交叉对照。对每周期独立推断真实timestamp偏移、成交量和金额乘数，验证原购买OHLC，SHA钉住每个历史原始Parquet，样本不足/标签不一致/量额不吻合则停止。**不要预设所有周期都和日线一样volume×1，公开接口5m成交量可能使用手。**

新增 minute_market_sync.py：真正按八字段目标格式生成可并入的每股票每周期Parquet候选；逐股票全天5min 48格、四周期实际时间戳和OHLCVA、日线成交量额和开高低收校验。若用户指定 --commit-complete-month-source，只有相应完整日期范围内**所有官方日线交易股票**均下载及校验过，才预检四个目标月文件同键原数据并在独占锁下逐周期调用已验local_layout.write_month（旧月文件SHA备份、临时文件完整Arrow读回、原子替换、可重试）。分批阶段只更新Git忽略的私有文件、显示ready/total、从每支股票的SHA收据断点继续；任一股缺少有效分钟数据则不标记全市场完成。当前只支持**2026年11月完整月初起点**，保护10月1-13日来源包含未经同单位验证的H5/高周期合成候选，不能把10月14日起数据创建成看似完整的10月正式月文件。

小步试运行（先真实购买历史校准与最多25只股票的四周期私有落盘，不写正式八周期数据库）：

    .\.venv\Scripts\python.exe -B ParquetLiveSync\minute_market_sync.py --root D:\stock --start 2026-11-02 --end 2026-11-11 --limit-stocks 25

自动继续所有股票并在完整性达到100%后才写四个月文件（非常耗时，允许停止/重启，期间仍不得把完成候选比率当成全市场K线已补齐）：

    .\.venv\Scripts\python.exe -B ParquetLiveSync\minute_market_sync.py --root D:\stock --start 2026-11-02 --end 2026-11-11 --limit-stocks 0 --commit-complete-month-source

简化GUI分钟模式里增加「11月四周期：自动补齐并拼接」，复用同一个下载按钮。它运行上述长期任务并显示私有待补比率或真正已验收四周期写入状态。原已经安装的21:30日/周/月自动任务**保持不变**，暂不在定时任务中强制写入分钟市场Parquet，确保用户本机先成功验证真实购买/来源差异。

时点：受官方日线在本机实际已验收截至2026-11-11限制，本版本第一次推荐到Nov11，不试图在尚无官方day收据时下载/提交Nov12；后续可随日线增量滚动扩展。新4周期的来源正式月文件必须是从11月首个交易日开始完整的聚合，10月需要单独验证H5过渡候选后再启动月初合并。1分钟仍缺完整真实OHLCVA源，暂不允许写入其正式Parquet。

用户若遇校准失败，应提供 MINUTE_PAID... / BLOCK_MINUTE... 的真实本机输出，以决定是时间偏移、手股单位还是缺源；程序当前会拒绝实际市场写入，不会修改任何H5。
