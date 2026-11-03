# 2026-11-03 架构与计划纠偏：购买Parquet权威原位引用，H5只写真实差集

> **本文件取代此前一切“2026整年按工作日逐日重写购买1/5min到私有统一Parquet，再2025重做”的执行建议。** 旧已运行批次不能靠更新GitHub代码停止；用户已要求按日安全暂停，先核验状态，不强杀、不中途改写状态JSON。此前转换产物保留为隔离审计证据，**不可计作新增市场覆盖**，不自动加入正式统一版本。
>
> 本文件基于用户明确的“以购买Parquet为主；H5仅补缺；后续Parquet→H5同步；原市场文件不修改”的目标。2011—2026日线物化成功、已核实的旧分钟实写SHA成功都是真的；错误在于**是否需要大规模重复生成那些记录**、**统计口径**和**启动2025/26全范围无差集物化**。

## 已结束旧任务的实机最终净增量结论（用户Windows回执）

旧批次 `0625f02019fe` 已安全进入 `status=paused`，处理6/204个候选工作日，最后完成2026-01-08，日志显示 `Pause requested: no new day started`、`Worker ended: paused`，无错误。无须再次提交暂停、不重启旧模式。

用户对01-05/06/07/08四个有源交易日读取旧 `minute-batch-unified-YYYYMMDD-*.json` 的实际 `periods[p].source_rows`，**逐周期购买来源行数均等于物理总行数**：

| 日期 | 原购买源1min | 原购买源5min | 原购源重复写盘合计 | 新H5完整股日补入 |
| --- | ---: | ---: | ---: | ---: |
| 2026-01-05 | 1,317,788 | 262,464 | 1,580,252 | 0 |
| 2026-01-06 | 1,318,029 | 262,512 | 1,580,541 | 0 |
| 2026-01-07 | 1,318,029 | 262,512 | 1,580,541 | 0 |
| 2026-01-08 | 1,318,029 | 262,512 | 1,580,541 | 0 |
| **合计** | **5,271,875** | **1,050,000** | **6,321,875** | **0** |

**JSON实现注意：** `source_rows`仅序列化`Counter`中实际存在的非零来源，`h5_only_complete_stockday`为零时该字段不存在，因此PowerShell的 `H5Gap`列显示空白、`Measure-Object -Sum`把空值算作零。严格判断须检查 `source_rows`对象和受支持来源字段，按 `source_rows.get("h5_only_complete_stockday",0)` 显式补零，并验算 `unified_rows == purchased_parquet + h5_only_complete_stockday`（`run-real-minute-h5-gap-unified-range.py::verified_completed`已经要求 `n==sum(cnt.values())`且H5计数匹配物理stage）。此次从四日报告可证：旧模式新写6,321,875条**全是购买源物理副本，H5净补0条**；但**不能据此证明同一股票日内部不存在可补的部分分钟键**，旧写出器只处理完全缺失的股票日。

今后 **禁止**以6,321,875重复购买副本或更大旧SAFE累计数字作为市场补缺。下一步读取已确认的来源差集，只有 `accepted_h5_gap_unique_keys>0` 才允许出现新补缺Parquet文件，并在零缺口时不产生行情副本。

## 2026-11-03 Windows首轮真实预览报错与修复：跨日行组预算误计

用户在开发分支`2d4b4a4`上运行`run-minute-h5-gap-only.ps1 -Day 2026-01-07`：

- 原H5 gap合成实写测试 **3/3 PASS**，新购买优先overlay合成测试 **8/8 PASS**。
- 随后真实**只读**预览在`write-h5-only-complete-minute-stockdays-to-private-parquet.py::purchased_stockdays`的`Minute purchased key scan budget exceeded`处失败；购买和H5未写。尚无实际H5 gap预览结果，不能宣称01-07真实0条通过。
- **根因明确**：年度Parquet可存在跨日期的timestamp rowgroup，旧`inspected+=len(ts)`把目标日之外的行也计入`max_rows=6,000,000`“目标日候选键”预算。1月7日已有购买1min约131万行，行组扫描可能远多于目标日行数，误触发。
- **修复**：对每个rowgroup仍只读`ts,symbol`两列，按65,536记录的小批次用Arrow时间范围谓词筛选，**只对目标日期行进行Python股票解析**；`max_rows`仅检查命中目标日的键数，不再以跨日期扫描量触发误报。原`purchased_key_candidate_rows_scanned`保留总扫描量统计，并新增`purchased_timestamp_matched_day_rows`和`purchased_key_budget_applied_to=matching_day_rows_only`。timestamp需整数毫秒；symbol支持普通及Arrow字典编码字符串。
- 增加**3个**针对跨日大rowgroup、真实目标日超预算拒绝、字典编码symbol兼容性的合成单测。现核心测试应为**6项**，新overlay测试**8项**（合计14项）。**新修复尚待用户Windows实机重跑，不能声称已经PASS**。
- 不扩大预算到不受控的几千万，不从原源复制OHLCVA，不启动旧全年批量worker，不自动启用生产查询。下一步仍是对01-07先跑全部测试再做真实**只读**预览；正确验收标准为`purchased_timestamp_matched_day_rows`与`eligible_h5_only_rows`逐周期可见且原文件不变。

## 2026-11-03 已实现第一段新主线：仅完整缺股票日的H5增量写盘（待Windows实机验收）

本轮新代码**已提交但未在用户Windows市场实数据执行**：
- `tools/run-minute-h5-gap-only-overlay.py` 是**全新独立入口**，不调用旧的 `write-purchased-first-unified-minute-day-parquet.py` 合并复制程序。
- 按日期对1min/5min只读原购买Parquet的 `ts/symbol` 两列获取已有股票日；检查H5源中购买**完全缺失**的股票日，按既有时间格/原生整数/OHLCVA约束校验。
- 只在严格发现至少1个完整且有效的H5独有股票日时，调用既有经过实机使用的 `write-h5-only-complete-minute-stockdays-to-private-parquet.py::write_private_day`；写出的市场行**100%来自H5**, 保留原H5整数，走全行回读和SHA。若两个周期分别为0行则不创建任意分钟Parquet，甚至不创建`work/unified_parquet/minute_gap_staging/<rid>/`目录；显式写入时仅留0增量JSON报告。
- 只读预览是默认行为；真实写盘需要**显式**`--write-gap-only`或新PowerShell wrapper 的`-Run`。新/旧任务共享单一写盘锁；先后检查原购买和H5元数据签名，来源处理期间变化就拒绝验收。签名基于路径、文件大小、mtime_ns、inode，**不是源文件内容SHA**，不得声称跨运行不可变生产版本证明。
- `partial_purchased_stockday_minute_keys_checked=false`：一旦购买源某个股票日有任何分钟记录，本轮**不猜测**该日其余时间键，也不把它宣称“完整无缺”。本轮只能处理“购买端整股票日0行”的H5补缺；下一步才扩展到同股票日内部的精确时间键差集并建立年级复用索引。即使该新程序输出零行，也**不代表该日完全没有部分缺分钟**。
- 写盘前检查该日期旧 `minute-batch-stage-*`、旧H5时间键迁移以及新gap-only验收记录；若曾有历史H5补差且本次又发现候选补差，则**拒绝新增**，避免重复计算此前的10月13日等已验收H5行；复核旧证据与新来源版本后才可另行处理。
- 输出含`purchased_bars_rematerialized=0`、`accepted_new_h5_full_stockday_gap_rows`、每周期H5验收行数与SHA、隔离计数、来源元数据指纹、生产未激活标记，便于以后发布逻辑统一源版本。
- `tests/test_run_minute_h5_gap_only_overlay.py`新增8项本地合成真实H5/Parquet写盘测试：只读无副作用、购买覆盖0文件、真实H5独有288条仅写H5、5min不完整隔离、来源期间变化拒绝、无数据日不写、run-id防覆盖、已存在旧H5日验收报告时拒绝重复计为净增量。**这些新测试尚未得到用户Windows PASS回执，不能声称实机验证**。

用户现在可在Windows仓库目录运行下面**一整行**：更新开发分支，自动跑既有H5补差测试与7项新测试，再只读核查之前误重写的2026-01-07，**默认不写任何真实行情或结果文件**：

```powershell
cd D:\ChatGPT\AStockDataTools; git fetch origin; if ($LASTEXITCODE -ne 0) { throw "fetch失败" }; git switch feat/private-2011-2025-purchased-physical-year-20261031; if ($LASTEXITCODE -ne 0) { throw "切换失败" }; git pull --ff-only origin feat/private-2011-2025-purchased-physical-year-20261031; if ($LASTEXITCODE -ne 0) { throw "更新失败" }; powershell.exe -NoProfile -ExecutionPolicy Bypass -File H5ParquetReconciler\run-minute-h5-gap-only.ps1 -Day 2026-01-07; if ($LASTEXITCODE -ne 0) { throw "新H5-only差集测试/只读预览失败；禁止写盘" }
```

在检查新输出中的 `eligible_h5_only_rows` 后，若有真实需要补齐的日期且确认未重复已有gap SAFE，再明确选择 `-Run` 实际只写H5缺口；不要现在无差别遍历全年，也不要恢复旧worker。现有2026-10-13等已有验收H5-only日期必须先做跨批次去重和来源版本绑定后才允许纳入正式逻辑覆盖，不能因为本轮新run-id而再计为新补入。

## A. 证据与已证实错误

1. 旧后台任务 `0625f02019fe` 对2026-01-05购买源已存在的1min **1,317,788**、5min **262,464**条再次生成私有文件，H5-gap两周期**均0**。因此“新增1,580,252条行情覆盖”是错的；准确说是“新写1,580,252条购买来源的副本”。原文件未覆盖，私有物化有来源保全价值，但本方案里没有必要。
2. 用户日志又显示2026-01-06 `1min=1,318,029`、`5min=262,512`，2026-01-07同样；已开始01-08。**01-06/07来源拆分尚未在粘贴日志里出现**，必须读取相应`reports/minute-batch-unified-YYYYMMDD-*.json`的`source_rows`才能判断真正新增H5股日多少，不能把这两天全部推定为重复。
3. `minute-private-parquet-worker.py::verified_existing_batch`检查“有没有已经生成过、SHA可重验的**私有统一分钟Parquet**”，不是“**购买Parquet已覆盖**”。没有私有文件就会执行`run-real-minute-h5-gap-unified-range.py`，后者每个候选工作日都写一个购买来源完整复制文件，即使`h5_gap_rows=0`。
4. `report-verified-unified-minute-progress.py`报告的前次**41个非空日期、65,787,155条**是“已验收私有物理复制/混合文件总量”，**不是从H5给购买数据净补的记录数**，更不是全源分钟覆盖率；不应作为新补覆盖的KPI。
5. `run-minute-2026-backfill.ps1 -Run`曾将2026-01-01→10-13的204个候选工作日作为批量复制队列，任务`done`包含`no_market_source_rows`且不代表已验收行情交易日。这个全范围批量启动建议**撤回**，2025同模式后续批量启动建议**撤回**。
6. 同一购买分钟年度文件在`purchased_stockdays`与`stage_unified`中重复解码/扫描，后者还对每条购买OHLCVA转Python对象、两次JSON指纹及全量回读，造成不必要的数亿次CPU和磁盘操作。刚提交的“购买股票日跳过H5二分”优化只能改善部分查询，不解决重复物化主因，**不作为下阶段P0**。

## B. 其余主线同类问题与纠正边界

| 范围 | 已有事实/风险 | 下一阶段必须遵循 |
| --- | --- | --- |
| 2011—2026 DAY | 14,115,707条购买源+22,274条H5补差已经写成14,137,981条独立私有年度Parquet。结果已SHA验收，**历史工作有价值但复制购买数据不应在未来周期重复执行**。 | 保留并引用既有私有日线版本；后续增量优先只追加真实缺键，不重新写既有16年度；如需生产物理合并，另列必要性和成本。 |
| 1990—2010 DAY | 3,682,327条原生RAW已保存；3,673,987标准字段**量纲假设**+8,340原生隔离已落盘。曾有部分阶段文档误写“候选尚待运行”，已过时。 | 不重跑21年H5抽取、候选转换；先从已验SHA产物认证历史证券、量额及复权，无法确认部分仍保留隔离。没有证据不宣称1990—2026全可用。 |
| 1min/5min | 原购买数据可能已覆盖2011—2026大部分，源H5在2025/26有补差；旧GUI无源差集时也写完整购买日副本。 | 首先构建按`period, market, symbol, date, normalized_time_key`的**只读来源差集**，只写未被购买覆盖且可验收的H5键/股日；已有购买Parquet保持原位引用，**不复制其OHLCVA**。 |
| 部分股票日 | 现有写出器仅补`H5完整股日且购买该股日0行`，不补购买同一股日内部缺分钟；也不代表所有H5-only键都能自动补。 | `purchased_only`、`h5_only_full_stockday`、`h5_only_partial_minute_keys`、`both_conflict`、`no_source`分别统计；部分缺分钟与异常时间格隔离，只有独立验证时间桶、单位、复权和无重复键后才追加。 |
| 15/30/60分钟、周/月、复权 | 购买Parquet已有这些周期与附加字段；过去计划可能误解为应重新从1/5min合成所有数据。 | **原位引用购买Parquet**；只对证实缺失且源时间/聚合和复权口径通过的记录计算补集，不重建已购周期、不凭空制造源记录。 |
| H5镜像 | 日线已验有14,137,981条独立H5，分钟仅小批量镜像6,427,013条；购买Float64→H5整数有金额量化损失。 | Hikyuu读取要求单一原生H5时，正式镜像可能确实需要一次完整构建，但**绝不先为其复制一套购买分钟Parquet再镜像H5**；优先从购买原始分区+已验H5补差直接建目标H5，版本化且保留量化误差报告。 |
| 源版本与复用 | 旧`verified_existing_batch`核的是私有输出SHA、关联SAFE，**没有证明购买源或可变H5后来未增量更新**。 | 用独立来源版本清单、时间范围、SHA/不可变来源登记、增量源变化定位；有新H5/TDX源时必须重新计算受影响键，不能无条件复用旧输出。 |
| 无行情工作日 | 旧worker将`no_market_source_rows`视为可跳过的“已处理”；后续源更新可能漏补。 | 使用官方交易日历与原源范围分别标记`exchange_closed`/`not_in_current_source`/`gap_unknown`；源版本变化后允许重新评估，绝不当完整覆盖。 |
| 查询/激活 | 私有分层DAY研究接口已PASS，但生产指针仍false；分钟查询仍分散于购买与独立私有文件。 | 建立**逻辑统一查询**（买家原分区+H5补差overlay）并按键购买优先/去重，验证跨周期日期边界，经过接受门禁才可切换正式生产版本。 |
| 每日TDX增量 | 原末端仅观测到2026-10-13 H5、2026-09-30购买分钟；这不是当前行情总已更新到11月的证据。 | 新增真实源先以版本/时间格/证券身份校验，定向补入Parquet，再仅同步更改部分的H5；不可把无源10/14之后空Parquet误称“已同步”。 |

## C. 修订后的最短交付路线（先用已有数据，再只写增量）

**P0：安全停止错误流程（现在）**：用户已在 `0625f02019fe/stop_after_day.flag`请求“当前日完成后暂停”；读取`state.json`和`activity.log`核实最终`paused`。不要强杀，不要重复启动或编辑现有state/SAFE。已经生成的私有复制文件保留隔离作为历史证据，禁止误计净新增，禁止删除原始购买/H5。

**P1：一次性只读来源覆盖清单**：按已购1/5min的**实际年份/周期/股票/日期/时间标签**，优先复用已有行组元数据和`reconcile-local-a-share-h5-parquet.py`已实现的`summarize_stock_day_gaps`/SQLite精确差集逻辑。范围按已知源边界/年分批，不要求逐日反复解析整年购买OHLCVA。输出每个来源`source_version`和明确的缺失/异常分类；只计key，不导出私有行情。**若证实某个日子对购买数据零增量，可直接跳过该日写盘。**

**P2：H5-only GAP Parquet，0有效缺口则0行情文件**：每个周期仅把购买原位文件中不存在、且H5原生完整股日与统一时间键/单位检查通过的真正差键写入`work/unified_parquet/minute_h5_gap_only`下新的不可变分区；保留原生整数字段、来源版本/SHA/键清单、重复键和精度隔离。购买部分股日内部缺分钟先列清单，未认证不自动插入。H5没有源端覆盖或非交易日时不生成空“完成”Parquet。

**P3：逻辑统一Parquet/查询层**：声明`purchased=authoritative`、`h5_gap=overlay`；对相同规范键永远购买优先、不得双计；保留所有购买供应商字段及复权信息。年/周期清单只存源文件的**稳定路径、版本、SHA或快照引用及增量分区元数据**，不复制购买行。只读回归比较旧混合私有分区和新逻辑接口在已验证样本上的键/数值、发现差异直接失败隔离。

**P4：高周期/日线历史认证**：15/30/60min与周/月的购买原数据原位挂载；仅以确证缺口合成。旧1990—2010日线RAW/候选复用已验产物开展认证；不能把候选量纲/复权当正式依据，8,340隔离不丢弃。

**P5：正式版本、Hikyuu原生镜像与盘后TDX增量**：发布不可变逻辑分区清单及只读正式查询；全周期通过后视Hikyuu读取要求构建**一次**独立原生H5镜像，按原生固定精度公布误差，抽样及全量核验；后续仅有新日键或变更时增量更新Parquet overlay和目标H5。**镜像不会回灌成Parquet第二权威源**。

## D. 新的进度与验收标准：杜绝“复制多少算完成多少”

独立列出：
- `purchased_existing_unique_keys`：权威购买源本来就有的唯一规范键数量（不应计入新增）。
- `new_h5_gap_unique_keys`：购买源缺失、H5补入且真正新通过验证的唯一键。
- `new_tdx_increment_unique_keys`：版本之后新源真正增加的唯一键。
- `reused_source_or_alias_rows`：直接引用购买数据的数量，不发生复制。
- `legacy_purchased_rows_rematerialized`：此前已复制的购买来源行数，**单列存储开销**、净新增=0。
- `quarantined_keys`、`overlap_conflict_keys`、`source_absent_dates`：按源版本记录，不能隐藏在总量下。
- `logical_unique_query_keys`：逻辑查询购源+验收补集、按规范键去重后的可查唯一键；`ready_for_production`独立确认。

**必须证明的两个不变量**：
`intersection(purchased_keys, accepted_gap_keys) = empty`；
`logical_unique_query_keys = purchased_existing_unique_keys + accepted_gap_unique_keys (+ accepted TDX genuinely new keys)`，所有集合均为同一证券身份、周期、规范时间与来源版本范围。**不能用复制后的文件条数相加代替这些核对。**

### 通过以下验收门槛后，才能允许新的全量任务

1. **零重复写盘测试**：购买已有完整股日且H5无新键 → **不产生新行情Parquet文件、净新增0**；购买仅部分有 → 仅符合政策/验证的H5缺键写出；无源/休市 → 不物化空文件。
2. **数据不变测试**：所有原购买OHLCVA及其供应商附加字段直接回读无损；不会用H5覆盖购买同键值；历史隔离/复权不得默默转换。
3. **来源变更测试**：更新源版本后旧`no_source`、旧已验日期可以重新核对，输出旧SHA不能作为新源覆盖认证。
4. **长周期测试**：15/30/60min、week、month原位引用，不对已有购买周期重复重采样。
5. **净增量审计**：最终报告分别给出“原始购源覆盖、H5实际新增、TDX新增、误差/隔离、历史重复副本”，不能再以41日/65,787,155条或一周新私有文件总行数宣称完成数据补全。

## E. 代码与旧计划的安全边界

- `run-minute-2026-backfill.ps1 -Run`、`tools/launch-minute-year-backfill.py`以及GUI“开始新任务/恢复已有任务”的旧**全来源复制模式不再属于主线**，在新只写缺口程序验收之前不得继续用它们批量写盘；旧GUI**仅用于观察和日终暂停**。
- `tools/write-purchased-first-unified-minute-day-parquet.py`和`tools/run-real-minute-h5-gap-unified-range.py`保留作隔离的历史验收工具，不应冒充新差集写出器。下一阶段不通过人为删除已有SAFE来绕过重复检查。
- `docs/2026_11_03_MINUTE_41D_REAL_BACKFILL.md`、`docs/2026_11_03_FASTEST_COMPLETE_PARQUET_DELIVERY.md`及README旧分钟按日批量启动建议均视为**历史记录、已被本文件取代**。
- **现已实现并提交仅补“完整缺失股票日”的H5-only写出器、零增量不写行情，以及8项合成测试（尚待Windows回归）；“同股票日内部精确分钟键差集、跨批次SHA级来源版本合并、生产统一查询”仍未实现，绝不能称全部差集处理与生产激活已完成。**
