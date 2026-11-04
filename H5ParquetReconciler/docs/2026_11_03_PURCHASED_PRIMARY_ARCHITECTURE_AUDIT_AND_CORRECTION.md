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

## 2026-11-04 三日精确键实机确认：全部没有可补H5键；下一段1月尾单次建索引

用户在GitHub HTTPS连接中断时，直接用已存在的索引
`work/unified_parquet/minute_key_index/purchased-minute-keys-2026-01-05-2026-01-07-8b70d1032ad0.sqlite`
离线只读核对01-05、01-06、01-07。**三个日期的1min、5min两周期均零H5完整股日缺口、零局部分钟时间键候选**；无原始市场文件修改或新行情Parquet写入，源元数据均为同一个既有指纹（非内容SHA）。

| 日期 | 购买有效1min键 | 购买有效5min键 | 与H5重合1min键 | 与H5重合5min键 | 购买1min独有（限H5完整股日） | H5可补完整/局部分钟键 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 2026-01-05 | 1,317,788 | 262,464 | 1,239,840 | 261,696 | 5,166 | **0 / 0** |
| 2026-01-06 | 1,318,029 | 262,512 | 1,240,320 | 261,792 | 5,168 | **0 / 0** |
| 2026-01-07 | 1,318,029 | 262,512 | 1,240,560 | 261,840 | 5,169 | **0 / 0** |
| **三日合计** | **3,953,846** | **787,488** | **3,720,720** | **785,328** | **15,503** | **0 / 0** |

**重要边界**：购买1min独有键数量逐日约等于完整H5股票日数，疑似09:30约定差异，**未经独立按时间桶确认**；H5价格、量额、复权一致性尚未验收；没有出现在H5的股票日也无法由H5证明购源完整；不应扩大本次结论为全年行情无缺口。

**本轮新增代码（待Windows实机测试）**：
- `tools/ensure-minute-key-index-window.py`：若`from_day..through_day`已经有且只有一个来源指纹匹配的私有键SQLite，则经两个周期、区间头尾、来源路径和元数据校验后**直接复用**，任何现有索引都不重建；无索引才创建一次；同窗口出现多个或失效则fail-closed，不绕过旧指纹另写一个“新”索引。
- `tools/audit-minute-index-window-readonly.py`及其独立PowerShell仍可用于复用旧三日索引进行多日汇总，但上传回执的离线三次旧单日命令**已经完成了等价三日真实核对**，无需再重复使用旧三日索引运行同样的审计。
- `run-minute-jan2026-tail-index-audit.ps1`直接专注**2026-01-08→2026-01-31**新范围，不覆盖已验三日。只需调用一次入口，先运行索引5项+多日审计4项+索引复用4项合成测试（**累计13项本轮要求，新的8项未实机PASS**），后在私有SQLite里建立或复用这24日窗口两周期分钟位图，最后使用索引核对**17个候选周一至周五日期**。不会读取购买OHLCVA、不会生成额外的购买分钟行情Parquet、不会改变H5、不会恢复已暂停的旧worker。
- 专用入口默认2026年1月尾，不代表全2026或2025已经完成。若发现任何`h5_only_candidate_keys_on_partial_purchased_stockdays`，仅报告候选，**不自动写入**。
- 若GitHub HTTPS仍无法连接，**先检查网络或代理配置，保持本地源数据不变；不要重建旧索引，也不要关闭Git SSL验证**。新代码只有成功`git pull`后才可运行。

**下一步一行PowerShell（仅新建/复用私有SQLite + 只读市场核对，不复制行情）**：

```powershell
cd D:\ChatGPT\AStockDataTools; git -c http.version=HTTP/1.1 pull --ff-only origin feat/private-2011-2025-purchased-physical-year-20261031; if ($LASTEXITCODE -ne 0) { throw "GitHub更新失败，未运行新的月尾索引" }; powershell.exe -NoProfile -ExecutionPolicy Bypass -File H5ParquetReconciler\run-minute-jan2026-tail-index-audit.ps1; if ($LASTEXITCODE -ne 0) { throw "2026年1月尾索引/精确差集测试失败，禁止计入正式行情补缺" }
```

## 2026-11-03 Windows实机确认三日购买键索引PASS；多日批量复用正式开发

**最新用户真实Windows验收（已PASS，无需重建）**：
- `test_write_h5_only_complete_minute_stockdays_to_private_parquet.py` 6/6；`test_run_minute_h5_gap_only_overlay.py` 8/8；`test_preview_minute_exact_key_diff_readonly.py` 6/6；`test_build_minute_purchased_key_index.py` 5/5。**共25/25合成通过**。
- `work/unified_parquet/minute_key_index/purchased-minute-keys-2026-01-05-2026-01-07-8b70d1032ad0.sqlite`真实已存在：范围3个日历日；购源1min唯一A股键 **3,953,846**、5min **787,488**，合计 **4,741,334**。**购买OHLCVA复制0条**，原始Parquet/H5没有被修改。
- 通过已有SQLite索引复查`2026-01-07`，报告`index_used=true`、`no_purchased_parquet_scanned_during_lookup=true`；购买有效1min **1,318,029**、5min **262,512**，与原单日扫描结果一致；H5完整缺股日候选与同股票日内局部缺分钟候选**两周期均0**，未生成任何行情文件。1min购源独有键5,169，5min为0，仍未对09:30分布独立认证。
- 源指纹覆盖24个源文件，以mtime_ns/大小/inode/路径计算，**非全文件内容SHA**。只证明此次同版本数据的快速只读核对，不能推导全年源数据完整或认证量纲。

**下一段已开发代码（尚待Windows运行4项新合成测试）**：
- `tools/audit-minute-index-window-readonly.py` 接收一个**已经存在且与来源元数据相符**的购源SQLite键位图、起止日期，逐日期用相同索引比对H5完整时间格及`(period,symbol,ts)`，统计两周期的整股票日缺失、局部分钟键候选、购买端独有键、异常隔离。默认周末跳过但**不会擅自认定任何无源日期为交易所休市**。
- `run-minute-index-window-audit.ps1` 从`work/unified_parquet/minute_key_index`自动查找**唯一**符合日期范围的现有SQLite索引；若有0个或多个相同日期索引，拒绝隐式选择，允许`-Index`指定已有文件。它**不新建索引、不扫描购买Parquet数据、不写报告或任何市场数据**，只从已购索引与H5原始只读计算。
- 新增`tests/test_audit_minute_index_window_readonly.py` **4项测试**：同索引两个日期复用而不调用旧Parquet扫描、日期越界拒绝、源版本变化拒绝、单日与已有精确对比一致；代码提交，不等于Windows已实测。
- **先验收现成的3日索引**，检查01-05、06、07三日有无H5局部缺分钟，再决定是否扩至本月剩余日期；**避免重新构建已经验收的三日索引**。运行以下单行命令（只读）：
```powershell
cd D:\ChatGPT\AStockDataTools; git pull --ff-only origin feat/private-2011-2025-purchased-physical-year-20261031; if ($LASTEXITCODE -ne 0) { throw "更新失败" }; powershell.exe -NoProfile -ExecutionPolicy Bypass -File H5ParquetReconciler\run-minute-index-window-audit.ps1 -FromDay 2026-01-05 -ThroughDay 2026-01-07; if ($LASTEXITCODE -ne 0) { throw "既有分钟键索引多日核对失败" }
```
- 若本轮PASS，后续按**不重叠的日期范围**建2026-01-08→01-31月末购源键索引，沿用同样只读多日核对，再逐月推进2026/2025有真实分钟源覆盖的月份。新增市场行情永远只来自经过签名、时标和量纲认证的缺口，而不是购买数据重写副本。
- `reusable index`和`exact key audit`是分析工具，**不含生产逻辑版本、全SHA时间快照、全部市场证券身份/交易事实认证或日内缺分钟自动补入**。按月索引不是全历史已完成。若本轮发现H5-only候选，先隔离调查，不自动写Parquet或同步H5。

## 2026-11-03 精确键审计实机验收与购买源一次扫描复用索引（代码待Windows验收）

**用户实际Windows日志已验收的20项合成测试全部PASS**：既有H5写盘6/6、购买优先H5差集8/8、新精确分钟键审计6/6。针对真实`2026-01-07`的精确`(period,symbol,normalized_ts)`比对：

| 精确核对量 | 1min | 5min |
| --- | ---: | ---: |
| 购买Parquet A股唯一规范键 | 1,318,029 | 262,512 |
| H5完整时间格中与购买精确重合键 | 1,240,560 | 261,840 |
| H5购买整股票日完全缺失的键 | **0** | **0** |
| H5在已有购买股票日中额外候选分钟键 | **0** | **0** |
| 购买独有时间键（限H5完整股票日） | 5,169 | 0 |
| 对应H5完整股票日 | 5,169 | 5,455 |

**重要限定**：1min多出的5,169个购源独有键恰好每个H5完整股票日有一个，很可能与已知的09:30购买分钟开始标签有关，**本轮输出没有给出独立09:30分布审计，不能把推测当认证**。两个周期均没有找到本次可补的完整股日或局部分钟键；只说明当前日期、代码筛选和通过H5完整时间格验证的股票日，不代表全年无缺口。程序报告`new_market_parquet_or_h5_files_written=false`、`purchased_bars_rematerialized=0`、`ready_for_production_query=false`。扫描仍昂贵：1min购买Parquet 9个源文件、218个rowgroup、26,736,299个跨日候选行；5min 9文件45rowgroup、5,325,072行。因此**禁止对全年逐日反复运行单日扫描**。

**本轮新开发（尚待Windows首次实际执行）**：
- `tools/build-minute-purchased-key-index.py`：将某一段**1—31个连续日期（同一年）**的购买Parquet`ts/symbol`，按1min和5min分别**只扫描一次**，转为每个`period/day/symbol`一个1440分钟位图（180字节）、保存在`work/unified_parquet/minute_key_index`的新隔离SQLite。任何已购OHLCVA都不复制，原购买Parquet/H5只读。这是**按日期范围（月级）复用的键索引，不是已经构建全年度索引**；后续可逐月按年滚动，避免一次持有全年数亿个键。
- 位图保留一天1440个整分钟位置，包含09:30等购买端额外时标；原购买非整分钟时间键或重复A股键都`fail closed`，不擅自纠错。源筛选仍按A股代码候选规则，不能宣称股票身份已获交易所认证。
- 建好SQLite后，`preview-minute-exact-key-diff-readonly.py --key-index <private_index.sqlite>`读取日级位图、重构精确购买键，与同日H5对比；**不重新扫描购买Parquet的上千万行**。允许不同日期重复读取同一个索引，只要日期在范围内且源元数据fingerprint仍一致；来源文件发生变化则拒绝旧索引。
- 显式可见的来源版本限制：目前来源fingerprint只由路径/大小/mtime_ns/inode计算，**不是全文件内容SHA**；索引仅供只读诊断和候选缺口，不授权正式生产查询或自动写补缺。
- SQLite在临时`.partial`构建、`PRAGMA integrity_check`并确保Windows数据库文件句柄关闭后才原子改名；意外失败保留私有partial，不覆盖旧索引或原始市场文件。
- 新增`tests/test_build_minute_purchased_key_index.py`共**5项合成真实Arrow/SQLite测试**：与旧扫描精确键结果相同、索引复用禁止重读购买Parquet、跨范围/重复键拒绝、来源更新使旧索引失效、保留09:30额外键。现有测试预计20+5=**25项**，**新5项尚待Windows验收**。
- 新PowerShell入口`run-minute-purchased-key-index.ps1`默认只建**2026-01-05—01-07三日私有键索引**，并以索引直接检查`2026-01-07`，不用再扫描原购买Parquet一次；仅写私有SQLite索引，**不写任何行情Parquet/H5文件**。测试通过后才能扩大到单月；不要直接全年度运行。

**用户Windows下一条一行命令：**
```powershell
cd D:\ChatGPT\AStockDataTools; git pull --ff-only origin feat/private-2011-2025-purchased-physical-year-20261031; if ($LASTEXITCODE -ne 0) { throw "更新失败" }; powershell.exe -NoProfile -ExecutionPolicy Bypass -File H5ParquetReconciler\run-minute-purchased-key-index.ps1 -FromDay 2026-01-05 -ThroughDay 2026-01-07 -CheckDay 2026-01-07; if ($LASTEXITCODE -ne 0) { throw "购买分钟键索引构建或索引核对失败" }
```

## 2026-11-03 Windows真实01-07购源优先零补差验收 + 精确分钟键只读比较器

**用户实机回执（已通过）**：修复购买日期预算后，H5写盘合成测试6/6 + overlay合成测试8/8 共**14/14 PASS**。真实2026-01-07两周期只读预览成功、无任何原市场或私有行情写盘：
- 1min 购买源2026-01-07命中（A股模式过滤之前）**1,336,345条**、已买股票日5,469个，H5对应已买股票日无需探查数据集5,465个；9个购买年文件218个行组、候选扫描26,736,299行（两列，无OHLCVA）。
- 5min 目标日原源时间命中**266,160条**、已买股票日5,469个，H5无需查已买数据集5,465个；9个购买年文件45行组、扫描5,325,072行。
- 两周期`eligible_complete_h5_only_stockdays=0`、`eligible_h5_only_rows=0`、`written_h5_gap_rows=0`、`purchased_bars_rematerialized=0`。这**仅验证完全缺失的完整股票日补差为0**，不能证明部分分钟键没有缺失。
- 旧2026-01-07`source_rows.purchased_parquet`是1min 1,318,029、5min 262,512，与此次购源**原始时间戳全记录**命中数不同，这是A股股码过滤前后不同统计口径，不得作为18,316/3,648条缺口来计算；未来精确键审计只比较**同一A股筛选条件与规范时间标签**。
- `previous_gap_receipt_count_for_date=1`只是发现旧日级报告，**不代表旧报告确实有H5补缺行**；此前旧日数据来源拆分已证实0 H5补入。此次结果`existing_gap_key_reconciliation_completed=false`如实表明跨版本键集合未对账。
- `source_fingerprint`基于24个文件路径/大小/mtime_ns/inode，**不是内容SHA，也不是永久版本认证**；只证实本次运行期间的元数据未变。

**本次继续开发（尚待Windows第一次运行）**：
- 新增`tools/preview-minute-exact-key-diff-readonly.py`。为每周期、一个日期单次Arrow读取购买`ts/symbol`两列、仅保留目标日A股精确时间键（`purchased_stockdays(include_time_keys=True)`，复用原有预算过滤与股票身份规则）；对H5逐股票日提取原生时间标签，使用已验证1min-END与5min-START候选映射、会话时间格校验，按真正的`(symbol, normalized_ts,period)`划分：
  - `h5_only_keys_on_full_purchased_absence_days`：整股票日购买0行的H5键；
  - `h5_only_candidate_keys_on_partial_purchased_stockdays`：**购买同日已有数据**但H5还有不同规范分钟键；
  - `overlapping_exact_keys`：实际相同键；
  - `purchased_only_keys_on_native_complete_H5_stockdays`：购买有但H5没有的键（如购买1min额外09:30，不代表异常）；
  - `quarantined_h5_stockdays_by_reason`：不完整会话、非法原生schema、重复等隔离。
- 新工具**只检查键，不读取H5的OHLCVA来做价值/复权/真实交易认证**；候选局部分钟全部`candidate_keys_automatically_accepted=0`，不能自动写盘或进入生产查询；输出只显示聚合计数，不含个股、价格。源元数据前后比对用于快速防事故，不替代全SHA。
- 新增`tests/test_preview_minute_exact_key_diff_readonly.py`共**6项合成Parquet/H5只读单测**，覆盖整日缺失vs局部缺失、购买09:30多一根不误判、真实单分钟缺失、原买键重复必须失败、H5不完整隔离与元数据变更失败。加上旧6+8现共**20项**。尚未Windows实测，不能称PASS。
- 独立Windows只读入口`run-minute-exact-key-diff-readonly.ps1`（自动测试全部20项、真实只读2026-01-07，**不写任何行情或报告文件**）。单行命令：
```powershell
cd D:\ChatGPT\AStockDataTools; git pull --ff-only origin feat/private-2011-2025-purchased-physical-year-20261031; if ($LASTEXITCODE -ne 0) { throw "更新失败" }; powershell.exe -NoProfile -ExecutionPolicy Bypass -File H5ParquetReconciler\run-minute-exact-key-diff-readonly.ps1 -Day 2026-01-07; if ($LASTEXITCODE -ne 0) { throw "精确分钟键只读对比或回归测试失败" }
```
- **注意性能边界**：2026全年源Parquet行组跨日使单日1min筛选仍要扫描2,674万行左右，**新比较器只应用于一个诊断日**，不要逐日循环全2025/26。下一主线应该建立**按年/周期只扫描一次购源的只读精确键缓存/索引**，再分日期批量比较（数据源变化需重建受影响的索引分区），而不是为每一天重复解析同一个年度文件。

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
