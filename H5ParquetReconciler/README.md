# H5 ↔ Parquet A股数据全量核对

本目录独立于旧的股票仿真仓库，专门开发本地 **Hikyuu H5 与购买的A股Parquet数据对比、补全、并集构建工具**。

**目标顺序：** ① 盘点双方覆盖 → ② 计算按证券/周期/时间的交集及双向差集 → ③ 核查重叠记录的OHLCV/成交额差异 → ④ 核实时间、单位、复权、历史证券代码 → ⑤ 在新目录生成可回滚的H5与Parquet并集库。

当前仅实现①–③的**只读基础版本**。无法直接承诺转换与合并是安全的，详情见 [完整需求文档](docs/REQUIREMENTS.md)、[当前审计规则与已知限制](docs/TECHNICAL_NOTES.md)。

## 文件结构

| 文件 | 用途 |
|---|---|
| tools/reconcile-local-a-share-h5-parquet.py | 全量年度/周期只读核对程序 |
| tests/test_reconcile_local_a_share_h5_parquet.py | 19项合成测试（含有界分钟模式），无需购买行情 |
| docs/REQUIREMENTS.md | 需求、验收与优先级（当前开发任务的长期依据） |
| docs/TECHNICAL_NOTES.md | 数据字段、单位假设、报告语义和局限 |
| docs/ROADMAP.md | 后续开发与并集构建步骤 |
| requirements.txt | 依赖 |

## 本地数据目录

程序默认本机的数据根目录为 `D:\stock`，要求至少存在：

```text
D:\stock\
├─ HikyuuData\
│  ├─ sh_day.h5   sz_day.h5   bj_day.h5
│  ├─ sh_5min.h5  sz_5min.h5  bj_5min.h5
│  └─ sh_1min.h5  sz_1min.h5  bj_1min.h5
└─ AllCycleAStockData\
   ├─ day\   (年度*.parquet)
   ├─ 5min\  (年度*.parquet)
   ├─ 1min\  (年度*.parquet)
   ├─ 15min\ 30min\ 60min\ week\ month\
   └─ 复权因子\
```

真实付费数据永远不上传本仓库。所有生成的报告及SQLite临时库必须保存在本模块内的 `reports/` 与 `work/` 目录，且均被Git忽略；源数据 `D:\stock` 不进行写入。

## Windows PowerShell 快速开始

**统一输出目录要求：所有生成文件只能位于 `AStockDataTools\H5ParquetReconciler` 下。** 程序不再依赖PowerShell当前工作目录来决定报告或临时文件的存放位置。默认结构：

```text
AStockDataTools\
└─ H5ParquetReconciler\
   ├─ tools\          # 核对源码
   ├─ tests\          # 合成测试
   ├─ docs\           # 需求与技术记录
   ├─ reports\        # 自动生成的JSON、Markdown报告；Git忽略
   └─ work\           # SQLite临时索引；Git忽略
```

在 **AStockDataTools仓库根目录**打开PowerShell，首次准备虚拟环境和运行测试：

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r H5ParquetReconciler\requirements.txt

.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test_reconcile_local_a_share_h5_parquet.py" -v
```

推荐先执行2025—2026年日线的A股候选差集检查（使用新文件名，保留你已移动的历史报告）：

```powershell
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\reconcile-local-a-share-h5-parquet.py "D:\stock" --years 2025 2026 --periods day --universe a-share-candidate --read-only --out "reports\h5-parquet-day-equity-2025-2026-v2.json"
```

**不传 `--out` 时**，默认输出：
- `H5ParquetReconciler\reports\h5-parquet-audit.json`
- `H5ParquetReconciler\reports\h5-parquet-audit.md`
- `H5ParquetReconciler\work\_union_scratch`（任务临时数据库，分区运行完自动清理）

`--out` 与 `--scratch` 的**相对路径以模块根目录为基准**，与当前PowerShell所在文件夹无关。指定模块外的绝对路径，或者使用 `..` 逃出模块，会被拒绝。

历史整年三周期命令（**五分钟/一分钟必须加 --allow-full-year-minute 才允许运行，不建议先运行**）：

```powershell
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\reconcile-local-a-share-h5-parquet.py "D:\stock" --years 2011 2012 2013 2014 2015 2016 2017 2018 2019 2020 2021 2022 2023 2024 2025 2026 --periods day 5min 1min --universe a-share-candidate --allow-full-year-minute --read-only --out "reports\h5-parquet-union-audit.json"
```

中断后使用**相同的参数与报告路径**追加 `--resume`；原有已完成的年度/周期不会重跑。已有报告若已移动到模块**根目录**（例如 `H5ParquetReconciler\h5-parquet-day-equity-2025-2026.json`），可以用 `--out h5-parquet-day-equity-2025-2026.json --resume` 精确指定它；不要把不同证券集、年份或周期的报告混用resume。工具不会挪动或覆盖你已整理的旧报告。

真实H5、购买的Parquet都继续保存在 `D:\stock`，脚本只读，不会把它们复制到模块内。若你的整个项目位于 `D:\stock` 源树之下，仍会拒绝生成报告，以保护源行情不被写入。

## 🧪 Arrow预览第三次真实查询慢于RowGroup；推进精确证券日行组定位（2026-10-28）

用户本机新增`pq-primary-arrow-preview-SH600000-20260930-verified.json`：**结果仍48根且逐根完全一致**，但同一次验证中Arrow为**2.972944秒**、原RowGroup为**1.791278秒**（Arrow约1.66倍耗时）。之前两次A/B均更快的结论只适用于当时的实验，**不可升格为Arrow全局更快或默认引擎替换**。两次引擎都受系统缓存和负载影响；正式引擎继续保持原RowGroup。

注意47个Footer候选行组中，Arrow只从18组输出目标证券当天K线。新增只读工具`tools/plan-parquet-5min-exact-rowgroups.py`对**全部47候选组的`ts,symbol`键列**进行有预算、有指纹保护的完整扫描，准确规划哪些行组含目标单股票单日键；**仅规划、不进入正式查询、不读OHLCVA、不自动并集**。能否从47减至真实18个仍待独立键列复核，首次完整键扫描本身有成本，不得先行宣称净加速。新增6项合成测试待Windows运行。详见[本次性能反转及精确行组计划](docs/2026_PARQUET_ARROW_PREVIEW_REGRESSION_AND_EXACT_ROWGROUP_PLAN.md)。

```powershell
git pull --ff-only origin main
.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test*.py" -v
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\plan-parquet-5min-exact-rowgroups.py "D:\\stock" --symbol SH600000 --date 2026-09-30 --max-candidate-rows 30000000 --max-candidate-groups 1000 --max-result-keys 25000 --read-only --out "reports\\pq-SH600000-20260930-5min-exact-rowgroups.json"
```

## ✅ 真实Arrow冷查询A/B双顺序完成；新增安全预览查询（2026-10-27）

用户本机两份真实 `SH600000 / 2026-09-30 / 5min` A/B：**RowGroup优先**传统4.579644秒、Arrow 1.425189秒（3.213×）；**Arrow优先**传统1.925149秒、Arrow 1.383294秒（1.392×）。两轮均48根、OHLCVA+时间+来源严格相同、源stat签名相同，47个候选RowGroup、5,685,792条源记录上限没有变化；Arrow过滤后向Python仅交付48条，不可据此认为物理只读48条。双顺序均更快，仅证明**本次单股票单日实验**，仍有OS缓存/运行顺序影响。

已加入**单独的、用户显式选择** `tools/query-parquet-arrow-preview-readonly.py`，复用实测Arrow过滤函数。仅输出`reports/`内无OHLCVA的元数据JSON；支持`--verify-rowgroup`令两个引擎在当前请求上重新逐根验证，但验证将增加查询耗时。默认`query-parquet-primary-readonly.py`**完全不变**，不建立私有缓存、不改写源行情、不自动合并。新增7项纯合成回归测试（当前**待Windows实际验证**）。详见[真实实验数据、限制与预览接口](docs/2026_PARQUET_REAL_ARROW_AB_RESULT_AND_PREVIEW.md)。

```powershell
git pull --ff-only origin main
.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test*.py" -v
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\query-parquet-arrow-preview-readonly.py "D:\stock" --symbol SH600000 --period 5min --from-date 2026-09-30 --to-date 2026-09-30 --max-candidate-rows 30000000 --verify-rowgroup --read-only --out "reports\pq-primary-arrow-preview-SH600000-20260930-verified.json"
```

## ✅ Windows完整298项合成测试全部通过；下一步真实Arrow冷查询双顺序对照（2026-10-27）

用户提供最新Windows完整 `unittest discover` 日志：**`Ran 298 tests in 16.243s`、`OK`**，包括上一轮的 PyArrow `LocalFileSystem` 修复、带空格路径，以及RowGroup/Arrow逐根OHLCVA/时间/来源一致性等回归。此前297项测试中5 failures/2 errors的问题已消除；此次结果只确认**合成测试通过**，不表示真实5分钟行情读取性能已提高。

真实冷查询仍待本机两次只读A/B及第三份安全交叉报告：`rowgroup-first`、`arrow-first`，输出路径均在本模块`reports/`，源数据`D:\\stock`只读、不允许上传付费K线。**按[双顺序A/B验收命令](docs/2026_PARQUET_COLD_AB_REVERSED_ORDER_AUDIT.md)执行；只上传3份汇总JSON，不上传`work/`缓存。** 在取得真实报告以前不替换正式RowGroup引擎、不宣称Arrow解码或磁盘IO更少。

## ✅ Parquet缓存冷热实测69.86倍；新增首次查询Arrow过滤A/B（2026-10-27）

用户上传`pq-primary-SH600000-20260930-cache-cold.json`/`...cache-warm.json`：2026-09-30 SH600000 5min首次查询48根耗时**3.515286秒、实际569万源行/9份Footer**，热缓存48根耗时**0.050318秒、零Parquet源行/零Footer读取**，实测重复查询约**69.86倍**加速、耗时降低约**98.57%**。这不是未经测试的性能推断，但**只适用于该单次重复查询，不能表示首次查询已提速或缓存来源内容哈希已验证**。

接下来真正待解决的瓶颈是首次每根目标K线要读取118,454源行。新增独立工具`tools/benchmark-parquet-arrow-filter-cold.py`：用经过真实验证的默认ParquetFile RowGroup方式与Arrow Dataset指定同RowGroup的`filter=ts/symbol`过滤方式进行**只读冷查询A/B**，**禁用私有缓存**，在内存逐根严格比较六字段OHLCVA、原始时间、文件/RowGroup来源，任何不等都会拒绝生成性能报告。只向模块`reports/`输出摘要、真实耗时、RowGroup预算及Arrow过滤后交付根数；**过滤输出只有48根不等于底层只解码48根，真实物理解码行/磁盘字节未知**。支持反转执行顺序避免把文件系统缓存效应当成优化结果。7项合成Arrow测试待本机运行，总计预计283项。见[本机真实约70倍热缓存与Arrow首次查询实验](docs/2026_PARQUET_WARM_CACHE_70X_REAL_AND_ARROW_COLD_AB.md)。

```powershell
git pull --ff-only origin main
.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test*.py" -v
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\benchmark-parquet-arrow-filter-cold.py "D:\stock" --symbol SH600000 --period 5min --from-date 2026-09-30 --to-date 2026-09-30 --max-candidate-rows 30000000 --order rowgroup-first --read-only --out "reports\pq-primary-cold-ab-SH600000-20260930-rowgroup-first.json"
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\benchmark-parquet-arrow-filter-cold.py "D:\stock" --symbol SH600000 --period 5min --from-date 2026-09-30 --to-date 2026-09-30 --max-candidate-rows 30000000 --order arrow-first --read-only --out "reports\pq-primary-cold-ab-SH600000-20260930-arrow-first.json"
```

## Parquet单股票重复查询：显式本地私有缓存，报告真实冷/热耗时（2026-10-27）

用户上传V2安全报告确认SH600000在2026-09-30的5min **48根**完全找到、09:30～14:55时间正常；9个月Footer均打开、8个非交叠月文件被安全跳过，但**同月47个RowGroup、5,685,792源行仍照常读取**，每返回根118,454源行，说明上轮改善的是规划，不是冷查询吞吐。

本轮新增`tools/private-parquet-query-cache.py`，在`query-parquet-primary-readonly.py`添加明确的**可选`--local-cache`**（Python`query_bars(...,local_cache=True)`）。首次仍从Parquet完整读取；会在**模块内`work/primary_query_cache/`落地真实购买OHLCVA子集**，该目录已被仓库.gitignore忽略，**不可上传、共享或放入reports/**。同股票/日期/周期/读取预算再次查询时只检查源文件清单、大小和mtime，匹配后可**零Parquet行情行读取/零Footer读取**并返回相同本地数据。源文件任何已检测到的stat变化或损坏缓存均触发重算。stat指纹**不是文件内容SHA256**，不能识别保留mtime/大小的隐式篡改。默认不开缓存，保留原接口行为和只读源保护。

新safe summary分别记录本次`source_rows_scanned_this_invocation`、`source_file_footers_opened_this_invocation`与`query_elapsed_seconds_this_invocation`，区分冷扫/热命中和历史冷扫成本，不在报告内输出OHLCVA。**缓存加速仅针对重复查询，不能声称解决首次569万行读取放大**。本轮增加5项合成测试，预计全量276项，待用户本机验证。见[本地缓存安全与冷/热验收](docs/2026_PARQUET_PRIVATE_REPEAT_QUERY_CACHE_AND_COLD_WARM_AUDIT.md)。

```powershell
git pull --ff-only origin main
.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test*.py" -v
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\query-parquet-primary-readonly.py "D:\stock" --symbol SH600000 --period 5min --from-date 2026-09-30 --to-date 2026-09-30 --max-candidate-rows 30000000 --read-only --local-cache --out "reports\pq-primary-SH600000-20260930-cache-cold.json"
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\query-parquet-primary-readonly.py "D:\stock" --symbol SH600000 --period 5min --from-date 2026-09-30 --to-date 2026-09-30 --max-candidate-rows 30000000 --read-only --local-cache --out "reports\pq-primary-SH600000-20260930-cache-warm.json"
```

## ✅ Parquet首个真实查询成功：SH600000 5min 48根；需要改善569万源行读放大（2026-10-27）

真实上传`pq-primary-query-SH600000-5min-2026-09-30.json`：SH600000/2026-09-30/Parquet 5min查询实际`matching_bar_count=48`，原始时间标签09:30～14:55，未调单位、未读H5、未写源，安全JSON不含OHLCVA。**但旧版为了这48根读了47个RowGroup、5,685,792条源行，约118,454条源行/返回根**，需要认真优化而不是继续重复做数据一致性审计。

本轮更新`tools/query-parquet-primary-readonly.py`：对与请求时间不重叠的根目录YYYY-MM.parquet文件，在**实际RowGroup footer逐组验证无时间重叠后**跳过后续查询计划；文件名错月或缺时间统计时**保守保留**，不会静默漏真实行情。新安全报告明确区分已打开Footer数、跳过月文件数、匹配行组数、实际读取源行数及读放大；这只是元数据阶段优化，**不能宣称已经消除了九月内部47个行组的约569万行读取**。新增4项合成Arrow回归测试，预计本工具13项，Windows真实V2报告待运行。详见[真实48根查询及月文件规划优化](docs/2026_PARQUET_FIRST_REAL_QUERY_AND_MONTH_FOOTER_OPTIMIZATION.md)。

```powershell
git pull --ff-only origin main
.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test*.py" -v
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\query-parquet-primary-readonly.py "D:\stock" --symbol SH600000 --period 5min --from-date 2026-09-30 --to-date 2026-09-30 --max-candidate-rows 30000000 --read-only --out "reports\pq-primary-query-SH600000-5min-2026-09-30-v2.json"
```

## ✅ 2026年2/8月key-only异常明确在深市B股；A股Parquet直接只读查询首版（2026-10-27）

本机真实JSON`pq-key-only-2026-02.json`/`pq-key-only-2026-08.json`结果：2月77,772个证券日中77,771完整、唯一不完整为2026-02-24 **SZ200706（81×1min/17×5min）**；8月118,064个证券日中118,061完整，三组不完整均为2026-08-03 **SZ200019、SZ200045、SZ200869（各80×1min/16×5min）**。全部4组属于深圳200开头**B股**，两月被检查的时间键无重复或非正常时段。**未观察到代码模式符合普通A股的股票日时间键异常**，但只检查了这两个月及键完整性，不能认定全历史正确，也不能替B股捏造缺失分钟。见[真实2/8月报告与只读查询开发](docs/2026_PARQUET_B_SHARE_KEY_ANOMALIES_AND_PRIMARY_QUERY.md)。

新增`tools/query-parquet-primary-readonly.py`，直接向用户购买的`AllCycleAStockData/{day,1min,5min}`发起**单证券、最多31天的真实行情查询**，不转换数据包、不写Parquet、不使用H5/TDX。公开本地Python`query_bars()`接口返回该证券的原始OHLCVA及来源行组；命令行默认只生成元数据安全报告，`--show-first-bars 3`才会显式在**本机终端**展示前3根付费K线。对源RowGroup按日期/证券保守剪枝、查询前30M行预算、25k结果数上限、重复时间键及OHLC结构异常失败保护；保留day源08:00/1min结束标签+09:30独立源键/5min开始标签，无私自价格复权和量额倍数换算。新增9项合成Arrow测试（待本机），下一阶段再实现TDX盘后**独立增量层**。

```powershell
git pull --ff-only origin main
.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test*.py" -v
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\query-parquet-primary-readonly.py "D:\stock" --symbol SH600000 --period 5min --from-date 2026-09-30 --to-date 2026-09-30 --max-candidate-rows 30000000 --read-only --out "reports\pq-primary-query-SH600000-5min-2026-09-30.json"
```

这是只读查询，不是合并主库或全历史认证；报告中`matching_bar_count`是**真数据查询结果**，不是根据Footer倍数推断。

## Parquet覆盖盘点实测：72文件/50.47GiB/2011—2026.09；2026年2月与8月需key-only精确核验（2026-10-27）

收到用户真实`parquet-primary-footer-inventory-2011-2026.json`：2011—2025年day/1min/5min每周期每年都有一个年度Parquet，2026年三个周期分别有1—9月各9份月度Parquet；**总计72文件/约50.47GiB/41.48亿条Footer统计记录**。所有非空行组均有可信`ts`范围统计，无元数据错年、命名歧义或缺失统计。**但这不是每证券逐交易日完整性认证**。实际供应商day原时间标签约08:00，1min为结束标签，5min为开始标签，保留原值供主查询标准化。

比较2026年每个月“241根1min/48根5min”的完整证券日整数倍后，**2月多81根1min/17根5min，8月仅1min差一根**，有必要用真实`ts`与`symbol`两列定位，不应随意把差异视为错误或补数据。新增`tools/audit-parquet-month-minute-keys.py`：按单月限定读取原Parquet的**两列key，不读任何OHLCVA**；按证券日241/48位图统计缺失、重复、非交易时段时间键，异常实例最多60个，单周期读取预算默认5000万源行；报告和暂存只在模块内，**不自动合并、不修改购买源**。新增8项合成/临时Arrow回归测试待Windows本机执行。详见[2011—2026全周期Footer与2026年2/8月key-only诊断](docs/2026_PARQUET_FOOTER_INVENTORY_AND_KEY_ONLY_ANOMALY_TARGETS.md)。

```powershell
git pull --ff-only origin main
.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test*.py" -v
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\audit-parquet-month-minute-keys.py "D:\stock" --year 2026 --month 2 --universe all --max-candidate-rows 50000000 --read-only --out "reports\pq-key-only-2026-02.json"
```

如2月结果显示异常高度集中，再检查8月`--month 8 --out "reports\pq-key-only-2026-08.json"`。报告出来后，继续推进只读历史主查询接口与通达信盘后分层更新。

## Parquet主数据源：已收到5个证券日样本台账；新增2011～2026只读Parquet元数据覆盖盘点（2026-10-27）

用户上传`parquet-primary-sampled-evidence-2026-08-24-09-30.json`，两交易日5个证券日样本均被标记为`candidate_parquet_primary_in_this_sample_only`，`sampled_stock_day_count=5`，`sampled_date_count=2`；全部`eligible_for_unattended_import=false`、`verified_full_history_coverage=false`，原市场行情未读写、未自动并集。至此不再反复重读已验的2026年8月/9月行情。

新增只读`tools/inventory-parquet-primary-footers.py`：针对用户准备作为历史主源的购买Parquet，按2011—2026年、day/1min/5min输出每年文件数、Parquet Footer源行总数与RowGroup数、原始北京时间时间标签最早/最新统计、无可信ts统计组数、文件名年份与时间边界冲突、文件元数据stat清单SHA256（**非完整文件内容SHA**）。**仅读取元数据，不读取任何分钟时间键或付费OHLCVA**。明确所有日期边界只为footer覆盖候选，不能声称全股票/全交易日无缺失。新增10项无版权模拟Parquet合成测试待Windows端执行，详见[只读元数据覆盖盘点说明](docs/2026_PARQUET_PRIMARY_FOOTER_ONLY_COVERAGE_PLAN.md)。

```powershell
git pull --ff-only origin main
.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test*.py" -v
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\inventory-parquet-primary-footers.py "D:\stock" --from-year 2011 --to-year 2026 --periods day 1min 5min --max-files 5000 --max-row-groups 100000 --read-only --out "reports\parquet-primary-footer-inventory-2011-2026.json"
```

把`parquet-primary-footer-inventory-2011-2026.json`发回即可，不必上传付费市场文件。下一阶段根据这份报表只对真实疑点年份做key-only精确覆盖检查，再建立可追溯Parquet只读查询及通达信盘后新增层。

## Parquet历史主源准备：9月30日量额微差极低，已有JSON可直接登记5个证券日（2026-10-27）

已核查`pq-day-vs-minute-2026-09-30.json`：SH600000与SZ000001分别241根1min/48根5min，1→5 **48/48严格六字段合成**，日线OHLC、量与两分钟周期严格一致，日线额相对分钟额仅**0.005ppm与0.049ppm**，均过已有容差但不是原始六字段严格一致；源选定数据无重复、非法时标或非有限数据。8月24日对应离线结果三股票全部标为“价格严格一致、量额≤7.157ppm小偏差需审查”，原严格标志没有被改写。这两个日期已检查的**5组日线-分钟股票日样本全部OHLC严格一致+量额过现有容差**，不等于整个历史库质量全认证。

为了避免无意义地重复扫描数百万行，新增`tools/plan-parquet-primary-evidence-ledger.py`：读取现有`pq-day-vs-minute-2026-08-24-offline-assessment.json`及`pq-day-vs-minute-2026-09-30.json`两个**安全汇总JSON**，交叉审查来源标志/字段等级、同一证券日不重复登记，仅生成5个**样本级Parquet主源候选**的安全登记台账，不读付费行情、不进行导入或自动并集。明确H5仅为确认缺口补充、通达信盘后作为后续新交易日来源候选。新增9项纯合成测试待Windows验证；详见[已验证Parquet证券日证据台账](docs/2026_PARQUET_PRIMARY_SAMPLED_EVIDENCE_LEDGER.md)。

```powershell
git pull --ff-only origin main
.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test*.py" -v
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\plan-parquet-primary-evidence-ledger.py --reports "H5ParquetReconciler\reports\pq-day-vs-minute-2026-08-24-offline-assessment.json" "H5ParquetReconciler\reports\pq-day-vs-minute-2026-09-30.json" --review-ppm 10 --out "H5ParquetReconciler\reports\parquet-primary-sampled-evidence-2026-08-24-09-30.json"
```

## Parquet day↔1min/5min实测：价格四字段严格一致、数量额仅≤7.157ppm微差；离线报告审计（2026-10-27）

收到用户本机`pq-day-vs-minute-2026-08-24.json`：2026-08-24 SH600000、SZ000001、SZ300750三个证券交易日的Parquet日线均有数据，1分钟各241根、5分钟各48根，**1min→5min各48/48六字段严格合成，Parquet日线开高低收与两种分钟的日内聚合四价严格一致**。日线量：SH600000与SZ000001严格一致，SZ300750与两周期有约**7.157 ppm**的微差；日线额：三股均略有偏差（0.025/0.033/0.018 ppm）。所有六字段均**满足先前已有比较容差**、且候选量额倍率×1，源无重复、非有限或异常交易时刻。**但三股`raw_all_three_periods_strict_agree=false`是准确结果，绝不能声称六字段严格全部通过或源量纲已正式认证。** 更多信息见[本机真实日线报告及量额微差](docs/2026_08_24_PARQUET_DAILY_TINY_QUANTITY_DIFFERENCES_REAL_REPORT.md)。

新增无需任何行情扫描的`tools/audit-parquet-day-minute-report-offline.py`，只读取已有三周期报告，核对其证据自洽性，分开列出严格一致/既有容差一致/价格严格一致、量额比率导出的ppm误差，并用**默认10ppm仅供复核的门槛**标示小偏差候选；它不是交易所/单位认证，**不会自动合并或覆盖原始数据**。新增8项合成测试待Windows验收。

```powershell
git pull --ff-only origin main
.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test*.py" -v
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\audit-parquet-day-minute-report-offline.py --report "H5ParquetReconciler\reports\pq-day-vs-minute-2026-08-24.json" --out "H5ParquetReconciler\reports\pq-day-vs-minute-2026-08-24-offline-assessment.json"
```

需要扩样时再运行9月30日day↔分钟真实对账；**不要为了重新评估已生成JSON重复读取几百万行Parquet**。

## ✅ Parquet跨日期跨沪深市场384/384六字段严格重建；新增日线↔分钟只读审计（2026-10-27）

新增真实报告：2026-08-24的SH600000、SZ000001、SZ300750均48/48严格一致；2026-09-30的SH600000、SZ000001均48/48严格一致，**本轮240/240**。连同9/28科创板三只144/144，已在2026年8、9月三交易日覆盖沪市主板、科创板、深市主板、创业板，**8组股票交易日384/384根Parquet 5min由同源1min严格重建**，首根09:30额外一分钟只算一次。所有样本同源成交量额分位数及最大值比率均1.0；仅证明该样本内部一致性，不能认证早期历史年份、北交所或交易所逐笔正确性。

下一步新增`tools/validate-parquet-day-to-minute.py`，**纯Parquet**只读原始`day`、`1min`、`5min`三个周期，按交易日完整241根1min/48根5min时间网格、09:30特殊分钟独立聚合两种分钟周期的OHLC/成交量/成交额，再与Parquet日线比较严格值/原容差和**量额倍率候选×1/×100/×0.01**；数据缺失、时间异常、重复键或量额倍率不明都拒绝自动认证，更不自动合并。另增8项合成测试含生成Arrow日线读取测试，Windows真实日线结果待验证。详见[跨市场384/384与日线守恒审计](docs/2026_PARQUET_CROSSMARKET_384_OF_384_AND_DAILY_AUDIT.md)。

```powershell
git pull --ff-only origin main
.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test*.py" -v
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\validate-parquet-day-to-minute.py "D:\stock" --date 2026-08-24 --symbols SH600000 SZ000001 SZ300750 --max-candidate-rows 30000000 --read-only --out "reports\pq-day-vs-minute-2026-08-24.json"
```

请上传新的day↔minute安全汇总JSON核对**日线**的口径后，再选择是否检查9月30日；原H5和购买Parquet始终只读。

## ✅ Parquet本机真实验证：2026-09-28三股票144/144六字段严格合成成功（2026-10-27）

用户已上传PR #51新增09:30候选规则后的**真实Parquet-only**报告`pq-only-2026-09-28-1min-to-5min-opening0930.json`。SH688629、SH688017、SH688172各有241根1min与48根5min，**三只合计144/144根均满足开高低收、成交量、成交额六字段严格浮点数值准则（abs_tol=1e-6，rel_tol=1e-10）**，上午72/72、下午72/72，且同源五分量额与分钟和比值均1.0。此前47/48的首根09:30差异已证明由一个单独的09:30一分钟键纳入首根五分钟即可完全解释，其他47根各按普通结束标签五根聚合，**无需任何两周期成交量倍率调整**。原源无重复键/非法时间、非有限数值，所有目标股票质量检查无异常。

这标志该日**Parquet两个周期内部一致性样本验证完成**，是用户将Parquet设为2011～2026-09历史候选主源的关键实证；**不是所有年份/市场、Parquet日线或交易所正确性认证，也不是允许原文件自动合并的许可**。留存[真实验证报告总结及后续抽检方案](docs/2026_09_28_PARQUET_144_OF_144_REAL_DATA_CONFIRMED.md)。下一步优先抽2026-08-24深市/沪市、9月另一天和历史年份，再新增`day`↔1min/5min的守恒检验；最后才构建可追溯、可回滚的Parquet主库和通达信盘后增量同步。

## Parquet自身1min→5min实测：141/144严格一致；排查09:30额外开盘分钟（2026-10-27）

用户上传`pq-only-2026-09-28-1min-to-5min-top3.json`：Parquet 1min三证券各241根，5min各48根，最佳普通假说`five_start_minute_end`（五分**起始**时间标记、一分**结束**时间标记），在**144个完整窗口中141个六字段严格一致（97.92%）**，下午三股72/72严格一致。三股各有**一根上午5min**的开盘价、量、额不合，最高/最低/收盘48/48一致；现有报告没有标明哪一根。最值得验证的解释是1min有单独的09:30开盘/集合竞价记录，5min首根包含它。**这仍是推断，不是确认已144/144通过。**

本轮扩展`tools/validate-parquet-1min-to-5min.py`：保留原四种普通五根分钟的窗口假说，再加入**`five_start_minute_end_plus_opening_0930`**，只针对09:30首根五分钟明确要求额外09:30一分钟源键并只计算一次；输出具体不合时间和字段、开盘源分钟存在性，全部汇总/时间标签，不写任何付费价量额。新增3项合成测试，共本脚本16项；旧报告与Parquet源不覆盖。详细解读：[Parquet 09:30特殊分钟独立验证](docs/2026_09_28_PARQUET_OPENING_0930_SPECIAL_MINUTE_AUDIT.md)。

```powershell
git pull --ff-only origin main
.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test*.py" -v
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\validate-parquet-1min-to-5min.py "D:\stock" --date 2026-09-28 --symbols SH688629 SH688017 SH688172 --max-candidate-rows 30000000 --read-only --out "reports\pq-only-2026-09-28-1min-to-5min-opening0930.json"
```

上传新JSON后才能判断是不是每股票48/48严格吻合，再决定是否批准Parquet作为历史主源的该日期样本。

## Parquet确定为候选历史主源：核验购买数据自身1分钟能否合成5分钟（2026-10-27）

此前实测H5自身1min→5min 144/144吻合，**不等于Parquet两个周期内部也正确**。用户拟改以2011～2026-09购买的Parquet作为主数据源，后续用通达信盘后数据更新，必须先做Parquet的独立周期完整性检查。因此新增`tools/validate-parquet-1min-to-5min.py`：只读取Parquet `AllCycleAStockData/1min`、`5min`，从同一证券日将五根1min合成OHLCVA，尝试五分钟/一分钟各自“开始/结束”两种时间标签共4个候选组合；**严格数值（浮点容差1e-6/1e-10）与原容差两个层次分开**，对比分时段和整日完整窗口、量/额求和、同源候选成交量倍率，并把缺分钟、缺源、重复键和异常价格明确列为未认证。**不读取H5，不写源OHLCVA，不自动并集**；候选RowGroup每周期默认上限3000万行，超过时提示而不直接扫昂贵行情。完整方法见[Parquet同源一分钟到五分钟审计](docs/2026_PARQUET_1MIN_5MIN_PRIMARY_SOURCE_AUDIT_20261027.md)。

```powershell
git pull --ff-only origin main
.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test*.py" -v
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\validate-parquet-1min-to-5min.py "D:\stock" --date 2026-09-28 --symbols SH688629 SH688017 SH688172 --max-candidate-rows 30000000 --read-only --out "reports\pq-only-2026-09-28-1min-to-5min-top3.json"
```

上传安全汇总`pq-only-2026-09-28-1min-to-5min-top3.json`。先看Parquet自身4种时间窗口和1:1成交量额求和能否复现48根，再将结论扩展到8月、深市/北交所和日线互相守恒；**通过内部合成不等于交易所逐笔数据正确**。新增13项合成测试待本机验收。

## 数据合并方向调整：优先选可靠主源，再由通达信盘后增量补录（2026-10-27）

用户明确：购买Parquet覆盖2011～2026-09，Hikyuu H5日线覆盖更长并持续更新至2026-10，但分钟线可能仅从2025年附近开始，计划未来改用通达信盘后更新。**真实目标是一个来源清晰、历史连续、允许不同日期不同供应商但同一证券日单一来源的主数据视图**；不需要强求双方K线完全一样，更不能将原始文件彼此覆盖。初步倾向H5作为日线主线、Parquet补历史缺失分钟、最近重叠段H5为候选主线，最终由同花顺“不复权、同一五分钟区间”的独立人工抽样决定；通达信更新按日线/1m/5m分别记录最后完整时间，盘后增量补齐。过去5min H5在2026-10-13有记录但10-19～23报告缺源，**不能假设日线新就代表分钟线最新**。

新工具`tools/prepare-5min-tonghuashun-spotcheck.py`直接从2026-09-28经过验证的前三股票（SH688629/SH688017/SH688172）中，读取实际H5/PQ两源后自动选择**真实有量价差异**的五分钟K线，优先覆盖上午下午、OHLC差异较明显的时间点，输出只含代码/五分钟区间/差异字段的安全JSON。可选`--show-local-values`将两边OHLCV**只显示在本机终端**供同花顺对照，绝不写入公开仓库报告。**此步骤重扫Parquet当日相关47组（此前5,685,792行），与只读Footer或3组键列探测不同；若只想粗查可先按文档里的固定时间点人工看**。完整[来源优先与同花顺抽样核验方案](docs/2026_H5_PQ_TDX_PRIMARY_SOURCE_THS_SPOTCHECK_20261027.md)。

```powershell
git pull --ff-only origin main
.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test*.py" -v
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\prepare-5min-tonghuashun-spotcheck.py "D:\stock" --date 2026-09-28 --baseline-report "H5ParquetReconciler\reports\h5-parquet-5min-2026-09-28-exact-residual-masks.json" --top-symbols 3 --per-symbol 3 --show-local-values --read-only --out "reports\ths-2026-09-28-top3-manual-checks.json"
```

你在同花顺核对后只需告诉我**每个核验区间是H5更接近、Parquet更接近、两边一致或两边都不同**；无需上传付费源K线。此次新增6项合成测试，Windows尚需验收；正式自动并集和原始数据覆盖继续禁止。

## 已收到Footer真实报告：9月47组全部无法靠symbol min/max剪枝；先做键列成员关系抽样（2026-10-27）

用户上传`pq-5min-2026-09-28-top3-footer-read-plan.json`：2026年9个月文件共407个RowGroup，旧月份360组成功跳过；**剩余47组全部来自2026-09.parquet**，每组都不能通过目标SH688629/SH688017/SH688172的symbol min/max排除，预计读取5,685,792行、Footer未压缩元数据143,128,330字节。这完全重现先前三证券真实诊断的47组、568万行成本；说明主要瓶颈是9月份文件内部的证券—日期定位，而**不是全年文件选择**。

但min/max无法排除并不表示47组真实包含目标股票。新增`tools/probe-parquet-5min-rowgroup-membership.py`，只对确定性的**3个候选RowGroup（第0/23/46组）**读取`ts/symbol`两列、检查这些样本组里真实的证券—日期键存在性、48时段数和重复键，**不读取价量额、不开H5、不建大索引、不声称未采样组可跳读**。新增6项纯合成测试待本机验证。详见[2026-09-28三组键列成员关系试验](docs/2026_09_28_PARQUET_3GROUP_KEY_MEMBERSHIP_PILOT_20261027.md)。

```powershell
git pull --ff-only origin main
.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test*.py" -v
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\probe-parquet-5min-rowgroup-membership.py "D:\stock" --date 2026-09-28 --baseline-report "H5ParquetReconciler\reports\h5-parquet-5min-2026-09-28-exact-residual-masks.json" --top-symbols 3 --max-groups 3 --read-only --out "reports\pq-5min-2026-09-28-top3-key-pilot-3groups.json"
```

上传新`pq-5min-2026-09-28-top3-key-pilot-3groups.json`，确认3组内实际是否有目标证券/交易日键，再评估只为9月建立月度安全索引的价值。

## 下一轮：2026五分钟Parquet Footer扫描成本预检及完整索引可选接入（2026-10-27）

用户Windows本机**180项unittest全通过**；2026-09-28三证券原检测在47个Parquet行组内解码5,685,792条源行，最终只选中144根股票K线。已有2025 V3行组索引，**不能直接用于2026**；现阶段先不重扫或构建2026大索引。

扩展`tools/analyze-5min-x100-focused-sessions.py`：`--plan-only`仅读年度Parquet **Footer元数据**，不加载H5/Parquet K线，报告在现有时间/symbol最小最大值保守规则下，需要读取哪些RowGroup以及行数；`--coverage-index`可选接入**完整且源清单校验通过**的同年度V3索引，索引无效或只构建部分时直接拒绝，绝不因不完整索引误跳K线；原聚焦对账功能/8mask计数保持不变。新增7项纯合成测试待Windows验收。说明：[Parquet Footer读取成本与索引安全门槛](docs/2026_5MIN_PARQUET_FOOTER_COST_PLAN_INDEX_OPTION_20261027.md)。

```powershell
git pull --ff-only origin main
.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test*.py" -v
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\analyze-5min-x100-focused-sessions.py "D:\stock" --date 2026-09-28 --baseline-report "H5ParquetReconciler\reports\h5-parquet-5min-2026-09-28-exact-residual-masks.json" --top-symbols 3 --plan-only --read-only --out "reports\pq-5min-2026-09-28-top3-footer-read-plan.json"
```

上传新`pq-5min-2026-09-28-top3-footer-read-plan.json`，只核对元数据预期的候选行组和行数，不重扫付费OHLCV。**不要把Footer统计误认为已经实际提速。**

## 已验收H5一分钟到五分钟144/144一致：新增全离线证据链校验（2026-10-27）

用户上传`h5-1min-2026-09-28-top3-no-parquet.json`：SH688629、SH688017、SH688172各有**240根H5一分钟和48根H5五分钟**；每只按一分钟**结束标签**将5根聚合成1根，OHLC四项、成交额、H5五分钟量×100与1分钟量×100，均**48/48非零窗口**在既有容差内；合计144/144一致。反向采用一分钟**开始标签**时，仅138个完整窗口、**OHLC全一致0/138**，成交额3/138、×100量1/138。该证据支持H5的时间标签/量单位内部一致性，**不是供应商时标认证，也不能证明Parquet错误**。此前三股票H5与PQ成交量在上午/下午均报告为**小数精度下0%净差**、单根却存在毛差，继续支持K线时间窗/成交归属差异假说。

本轮新增纯JSON工具`tools/audit-5min-source-evidence-chain-offline.py`，将9月28日**精确8类冲突报告**、**top3分时守恒报告**和本次**H5一分钟报告**互相校验、计算溯源指纹及保守状态；核验证券/日期一致、8mask及边际守恒、晨/午24根计数、分钟重聚合有效分母、源只读及禁止自动并集。**无需读取H5或Parquet源文件**；新增8项合成测试待本机验证。完整分析见[9月28日分钟周期证据链](docs/2026_09_28_H5_1MIN_EVIDENCE_CHAIN_20261027.md)。

```powershell
git pull --ff-only origin main
.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test*.py" -v
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\audit-5min-source-evidence-chain-offline.py --exact-report "H5ParquetReconciler\reports\h5-parquet-5min-2026-09-28-exact-residual-masks.json" --focused-report "H5ParquetReconciler\reports\h5-parquet-5min-x100-2026-09-28-top3-sessions.json" --h5-minute-report "H5ParquetReconciler\reports\h5-1min-2026-09-28-top3-no-parquet.json" --out "reports\h5-parquet-2026-09-28-provenance-chain.json"
```

只需上传新`h5-parquet-2026-09-28-provenance-chain.json`。下次若确需比较Parquet边界来源，优先改善索引/减少rowgroup读取，而不是重做已经检查过的47组、568万行扫描。

## 三只证券×100分时报告验收后：只读取H5一分钟复核，不重扫Parquet（2026-10-26）

2026-09-28真实报告`h5-parquet-5min-x100-2026-09-28-top3-sessions.json`显示：SH688629、SH688017、SH688172各48根两源5min完整配对，候选成交量×100后**三只均上午与下午分别完全守恒（净差0）**，但逐K线毛差存在。三只股票的全天成交量毛差比例分别为0.928496%、0.561701%、0.717788%，相邻成交量差相关系数依次为-0.482、-0.455、-0.446。成交额全天净差仅0.000017%～0.000189%，支持但未证明“分时窗内数据分配差异”假说。**上次仅选144根K线仍解码Parquet 5,685,792行**，下一步应避免再次读Parquet。

新增`tools/inspect-h5-1min-top3-no-parquet.py`：自动从该真实分时报告提取已验收三证券，仅读本地H5 1min/5min文件2026-09-28对应证券一日数据；试验1min时间戳为结束/开始两种假设，严格5根聚合OHLC、金额，并检验H5 5min成交量×100与1min原成交量乘1或×100两种候选。一分钟不完整则明确计入缺窗、无H5一分钟数据则标为不可验证；零成交量窗口不能虚增有效单位证据。**绝不读取Parquet，不写源OHLCV、不认证正式行情单位、不自动并集**。新增6项合成测试待Windows验收；详见[前三证券H5 1min零Parquet读取核验](docs/2026_09_28_H5_1MIN_TOP3_NO_PQ_20261026.md)。

```powershell
git pull --ff-only origin main
.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test*.py" -v
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\inspect-h5-1min-top3-no-parquet.py "D:\stock" --date 2026-09-28 --baseline-report "H5ParquetReconciler\reports\h5-parquet-5min-x100-2026-09-28-top3-sessions.json" --read-only --out "reports\h5-1min-2026-09-28-top3-no-parquet.json"
```

上传新`h5-1min-2026-09-28-top3-no-parquet.json`即可，无需重复全市场K线扫描。

## 本机单日精确分类已确认：下一步针对前三证券做H5×100分时守恒（2026-10-26）

用户新上传的`h5-parquet-5min-2026-09-28-exact-residual-masks.json`已完成且守恒：9月28日匹配266,256根，×100后候选冲突**1,029根**，8种互斥类别为`volume=47、amount=2、price=117、volume_amount=392、volume_price=37、amount_price=0、volume_amount_price=434`（其余265,227根none）。候选volume=**910**、amount=**828**、OHLC price=**588**，与旧日级聚合精确一致。SH其他候选冲突535、BJ336、SH688/689 158、SZ两组0。BJ有**113根纯价格差**，不能与沪市量额三字段联差混成同一原因。

新工具`tools/analyze-5min-x100-focused-sessions.py`直接用已有的9月28日精确mask报告**自动选择真实最多冲突的三只股票SH688629、SH688017、SH688172**（总共95根冲突，其中72根三字段同差），仅加载这三个证券的H5/PQ 5min候选数据，先把H5 5min成交量**只在内存中×100**，对逐证券精确8mask计数和旧基线逐项核实后，再区分上午/下午比较成交量及成交额净差、相互抵消比例、相邻根差分相关和价格边界连续性。报告不含原始OHLCV，保留未认证映射、自动并集禁止。新增5项合成测试待Windows验收。详见[前三只股票×100分时归因](docs/2026_09_28_TOP3_X100_SESSION_DIAGNOSTIC_20261026.md)。

```powershell
git pull --ff-only origin main
.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test*.py" -v
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\analyze-5min-x100-focused-sessions.py "D:\stock" --date 2026-09-28 --baseline-report "H5ParquetReconciler\reports\h5-parquet-5min-2026-09-28-exact-residual-masks.json" --top-symbols 3 --read-only --out "reports\h5-parquet-5min-x100-2026-09-28-top3-sessions.json"
```

上传新的`h5-parquet-5min-x100-2026-09-28-top3-sessions.json`，**不要再次做9月28日全市场267,264根Parquet重对账**。本次只读选中股票（受Parquet行组统计粒度影响，实际可能解码更多来源行），不会修改源。

## 下一阶段：09-28单日精准划分8种量价残余组合（2026-10-26）

最新用户离线报告`h5-parquet-5min-2026-09-24-30-residual-triage.json`验证了1,065,216条重叠K线、3,440条候选量价残余，并严格指出：**343条确定没有成交量差异、至少922条同时涉及成交量/成交额/价格**。原聚合只能提供下界，不能直接计算互斥精确分类。5min候选量差按组SH其他1,742、BJ806、SH688/689 549、SZ两组0；交易日中09-28的候选量差910条最多。

在原有有界`reconcile-local-a-share-h5-parquet.py`里新增**8种互斥逐K线量价冲突mask**（none/仅volume/仅amount/仅price/三种两两组合/三者同时），保留原H5 5min×100候选和原严格价格/量额容差；按日、前缀分组强制守恒，输出最多16个冲突最集中的股票日（仅代码、日期及掩码计数，无原始行情）。旧汇总字段不变；新增4项合成测试，Windows待验收。详见[2026候选×100量价残余精准分类](docs/2026_5MIN_EXACT_RESIDUAL_FIELD_MASKS_20261026.md)。

只读核验先跑9月28日**一次单日扫描**（需要读该日H5/PQ源数据，但不会再扫描完整4天），与旧离线报告09-28的候选量差910、成交额差828、价格差588作守恒对照：

```powershell
git pull --ff-only origin main
.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test*.py" -v
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\reconcile-local-a-share-h5-parquet.py "D:\stock" --years 2026 --periods 5min --universe a-share-candidate --from-date 2026-09-28 --to-date 2026-09-28 --batch-size 8192 --read-only --out "reports\h5-parquet-5min-2026-09-28-exact-residual-masks.json"
```

上传这份新的单日JSON即可，**不上传源K线，不改源，不自动并集**。

## 新增无需重扫行情的3440条残余量价冲突离线分析（2026-10-26）

基于此前已生成的`h5-parquet-5min-2026-09-24-30-volume-x100-candidate.json`，候选换算后总量价冲突**3,440**，其中成交量3,097、成交额2,812、OHLC价格1,893。这3个是交叉边际统计，**不可直接相加或宣称互斥**。集合容斥至少能严格推出：**343条不涉及成交量而涉及价格或成交额**；**至少922条同时涉及成交量、成交额和OHLC价格**；至少2,469条同时涉及成交量和成交额。

新增纯报告处理工具`tools/triage-5min-x100-residual-offline.py`，只读取现有汇总JSON，检查旧/新冲突及按日期、代码前缀的边际计数是否守恒，计算严格可证的双字段/三字段交集下界、各代码组和每日量价残余总数的上下界；**不读取D盘H5/Parquet、不创建SQLite索引、不复制原始OHLCV、不认证单位或自动合并**。已新增合成测试，Windows执行待验收。详见[3440条残余冲突的数学约束和离线核验](docs/2026_5MIN_X100_OFFLINE_RESIDUAL_TRIAGE_20261026.md)。

```powershell
git pull --ff-only origin main
.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test*.py" -v
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\triage-5min-x100-residual-offline.py --report "H5ParquetReconciler\reports\h5-parquet-5min-2026-09-24-30-volume-x100-candidate.json" --out "reports\h5-parquet-5min-2026-09-24-30-residual-triage.json"
```

上传唯一新`h5-parquet-5min-2026-09-24-30-residual-triage.json`即可；若源报告在别的位置，仅按实际路径修改`--report`。**不要为了做离线分析重新运行前四日百万根K线核对。**

## 9月29日四周期聚焦实测：修正H5跨周期容差口径（2026-10-26）

用户提供的`pq-h5-bj-focused-2026-09-29.json`和`-v2.json`**完全相同**，无需重复Parquet扫描。两只证券`BJ920069`、`BJ920121`在9月29日的H5/PQ五分钟均有48根，**每根H5成交量×100与Parquet成交量均通过原严格容差**；两者的Parquet day总量都不满足5min总和的0.1%守恒。对于day跨源，BJ920069 H5 day×100与PQ day也不一致；BJ920121 H5 day×100与PQ day一致。

旧聚焦结果`h5_day_vs_minute_raw_sum_agree_0_1pct=true`可能因**以未换算的手数使用绝对容差1**而把日分差异错判为通过；独立H5日线/五分钟审计以**乘100后的股份候选量纲**使用绝对容差1，并在BJ920121上报告超差。本轮修复增补`h5_day_vs_minute_normalized_sum_agree_0_1pct`，直接复用独立H5审计的阈值，不修改旧字段，新增模拟48与49数量近似却单位归一化后超差的回归测试。

另已确认9月29日Parquet **12个完整48根5min但缺day键的候选证券日**：SH600293、SH600363、SH601059、SH601198、SH603400、SH688496、SZ000016、SZ002731、SZ002860、SZ300082、SZ300527、SZ301139。证据详见[四周期报告结论与H5统一容差修复](docs/2026_09_29_FOCUSED_4CYCLE_VOLUME_FINDINGS_20261026.md)。原JSON可保留，无需仅为更新一个布尔字段再次扫描约568万条Parquet组记录。

## 2026年9月29日四周期北交所异常聚焦（2026-10-26）

最新两份本机只读报告同时核实了单位假设及少量异常：**H5**当日5,548组完整证券日中5,547组日线—5min量能守恒（99.982%），唯一超0.1%的是**BJ920121**；**Parquet**当日5,558组完整证券日中5,556组原口径量能守恒（99.964%），异常为**BJ920121、BJ920069**，而且还有**12个Parquet分钟有键、day无键的证券日**。Parquet day/5min分别×100的替代映射通过数均为0，H5五分钟×100及Parquet原值更值得继续验证，但尚非官方认证。

新版`inspect-parquet-day-vs-5min-volume.py`新增了不含OHLCV的**12个缺日线股票日期示例**，并接受`--focus-symbols`同时核查指定证券的**H5 day/H5 5min/Parquet day/Parquet 5min**记录数量、48根标签完整性、各自内部量能守恒和跨供应商分钟量候选×100差异。新增2项纯合成测试；源文件始终只读，`safe_to_automatically_union=false`。详情：[2026年北交所两证券异常及12组缺日线](docs/DUAL_SOURCE_2026_BJ_4CYCLE_EXCEPTION_AUDIT_20261026.md)。

Windows仓库根目录执行（先通过全部测试）：

```powershell
git pull --ff-only origin main
.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test*.py" -v
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\inspect-parquet-day-vs-5min-volume.py "D:\stock" --year 2026 --from-date 2026-09-29 --to-date 2026-09-29 --batch-size 8192 --focus-symbols BJ920121 BJ920069 --read-only --out "reports\pq-h5-bj-focused-2026-09-29.json"
```

上传唯一的新`pq-h5-bj-focused-2026-09-29.json`，无需再单独跑H5身份扫描或整个年度Parquet。严格保留已有统计，不修改购买数据，不上传行情条目。

## 最新H5跨周期实测22,191/22,192通过，进一步核对购买Parquet（2026-10-26）

`h5-day-vs-5min-volume-2026-09-24-30.json`真实核验：H5四个有数据日共有**22,192个完整48根、日线与5min同证券同日都存在的候选股票日**；将5min `transCount×100`和日线`transCount×100`比较，**22,191组（99.9955%）**满足0.1%守恒阈值，22,021组原始计数求和严格相等，另170组仅有容差内差异；只有**9月29日1个证券日超差**。未换算的五分钟成交量对比候选日线成交量：**0组通过**。新工具路径与报告见[H5真实守恒结论与Parquet跨周期下一步](docs/DUAL_SOURCE_2026_H5_CONSERVATION_CONFIRMED_PQ_NEXT_20261026.md)。

本轮两个精准诊断：现有`inspect-h5-day-vs-5min-volume.py`增加**最多12个异常证券+日期示例（不公开量价）**；新增`inspect-parquet-day-vs-5min-volume.py`，只扫描限定日期的Parquet `day`和`5min`的ts/symbol/volume列，按ts footer跳过其他行组，统计48根完整证券日的成交量守恒及三种候选倍率。没有官方证券主数据、交易时标和单位定义前仍不认证单位、不自动并集。新增合成测试，待Windows本机通过。

更新main后依次执行全部测试及9月29日两个有界工具：

```powershell
git pull --ff-only origin main
.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test*.py" -v
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\inspect-h5-day-vs-5min-volume.py "D:\stock" --year 2026 --from-date 2026-09-29 --to-date 2026-09-29 --read-only --out "reports\h5-day-vs-5min-volume-2026-09-29-anomaly-id.json"
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\inspect-parquet-day-vs-5min-volume.py "D:\stock" --year 2026 --from-date 2026-09-29 --to-date 2026-09-29 --batch-size 8192 --read-only --out "reports\pq-day-vs-5min-volume-2026-09-29.json"
```

**只需上传2份新JSON。** 不重复2026年9月前四天双源全量审计、10月H5尾段或2025年度V3索引，不写源`D:\stock`。

## H5五分钟成交量×100实测通过，进入跨周期守恒检查（2026-10-26）

最新本地`h5-parquet-5min-2026-09-24-30-volume-x100-candidate.json`显示：2026年9月24、28、29、30日1,065,216个同键五分钟样本，原成交量冲突1,060,937，H5`transCount×100`后仅**3,097**根；**1,057,840个旧成交量冲突消除（99.708%），新引入冲突0**。价格/成交额沿用原规则时完整量价冲突从1,060,937下降至**3,440（0.323%）**，完整量价一致1,061,776根。这个结果强烈支持100倍单位假设，但还不是数据商的正式单位认证。

为避免再次扫描巨大的购买Parquet年度文件，新增只读`tools/inspect-h5-day-vs-5min-volume.py`：在已验证的4个日期读取H5的日线和5min成交量字段，只对恰好48个候选常规时标的证券日，核对`day.transCount×100`与`sum(5min.transCount)`（旧）以及`sum(5min.transCount×100)`（候选）。按日输出通过数、源缺失/不完整日数和原始跨周期和完全相等数；**同一H5数据商的跨周期一致性仍不是独立官方验证**。新增6项纯合成测试待本机运行。

Windows仓库根目录：

```powershell
git pull --ff-only origin main
.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test*.py" -v
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\inspect-h5-day-vs-5min-volume.py "D:\stock" --year 2026 --from-date 2026-09-24 --to-date 2026-09-30 --read-only --out "reports\h5-day-vs-5min-volume-2026-09-24-30.json"
```

只需上传新JSON用于下一轮核验；不改原始行情、不自动合并。详见[2026五分钟100倍实测与日线交叉守恒计划](docs/DUAL_SOURCE_2026_H5_DAY_5MIN_VOLUME_CONSERVATION_20261026.md)。

## 五分钟成交量约100倍线索与只读候选测试（2026-10-26）

新增量额诊断报告`h5-parquet-5min-2026-09-24-30-quantity-diagnostic.json`显示：2026年9月末有1,065,216条双源同键；1,058,125条仅volume不同，2,812条volume和amount都不同，0条仅amount不同。双方volume均非零时**1,059,453/1,060,935（99.86%）**接近`Parquet/H5=100`（1%候选倍率容差），而amount均非零时**1,046,098/1,060,840（98.61%）**接近1倍。既有`store_h5`仅day成交量乘100，5min成交量不乘100。**这是强候选单位问题，而非单位已经认证。**

主线新增**并行、可证伪**的`h5_volume_times_100_candidate`：原`quantity_scale_diagnostics`与`value_mismatch_rows`全部保留不变；只对五分钟重叠键试算H5`transCount*100`，用完全一样的旧容差统计新剩余冲突、旧冲突被解决、旧匹配被破坏、OHLC与amount不变时的剩余完整K线冲突，同时给出日期和代码前缀细分。源数据和临时表数值都不修改，`safe_to_automatically_union=false`，新增3项纯合成回归测试待Windows核验。

仓库根目录执行（不要覆盖以前JSON）：

```powershell
git pull --ff-only origin main
.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test*.py" -v
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\reconcile-local-a-share-h5-parquet.py "D:\stock" --years 2026 --periods 5min --from-date 2026-09-24 --to-date 2026-09-30 --universe a-share-candidate --batch-size 8192 --read-only --out "reports\h5-parquet-5min-2026-09-24-30-volume-x100-candidate.json"
```

下一份仅需新`volume-x100-candidate.json`。细节见[2026双源五分钟成交量×100并行候选验证](docs/DUAL_SOURCE_2026_5MIN_VOLUME_X100_CANDIDATE_20261026.md)。

## 2026年9月末/10月真实双源互补与量额口径诊断（2026-10-26）

2026-09-24、28、29、30四天全候选A股五分钟真实核对：H5 **1,065,216**键、Parquet **1,069,296**键，重叠1,065,216、H5独有0、Parquet独有**4,080**（**85个整证券日缺失候选，平均每组48根**，没有日内部分缺键；尚未证明每组恰好48根）；**量价差异1,060,937（99.598%）**，但只有**1,893（0.178%）**重叠键OHLC价格不同，其余差异集中在成交量/额。2026-10-08、09、12、13四日Parquet无记录，H5实际独有**1,066,368**键，共22,216个整证券日缺口候选，平均每组48根。两次均`scan_complete=true`、`issues=[]`，只读源。

当前最重要的研究转为**解释量额冲突**，而不是再扩大扫盘或修改单源索引。新版`reconcile-local-a-share-h5-parquet.py`针对有界5min重叠键新增`quantity_scale_diagnostics`：分别量化volume/amount超容差数量、同时/单项差异、非零相对误差分布和Parquet/H5接近0.01、0.1、1、10、100、1000倍的计数，按日和代码前缀也保留独立计数。全部是聚合数据，不导出原始OHLCV；不能仅凭倍率匹配就认证单位/改写源数据。新增4项纯合成测试，需Windows本机验收。

测试通过后仅需针对**已有真实重叠窗口**用新文件名复测一次：

```powershell
git pull --ff-only origin main
.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test*.py" -v
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\reconcile-local-a-share-h5-parquet.py "D:\stock" --years 2026 --periods 5min --from-date 2026-09-24 --to-date 2026-09-30 --universe a-share-candidate --batch-size 8192 --read-only --out "reports\h5-parquet-5min-2026-09-24-30-quantity-diagnostic.json"
```

请上传`h5-parquet-5min-2026-09-24-30-quantity-diagnostic.json`，用于决定是否需要数据商字段定义及同证券日线的单位校验。10月已确认1,066,368根H5独有，不需再重复扫描。详情见[2026年双源实测及量额口径诊断](docs/DUAL_SOURCE_2026_SEP_OCT_PRICE_QUANTITY_DIAGNOSTICS_20261026.md)。

## 2026五分钟数据源实际截止边界已确认（2026-10-26）

用户上传`dual-source-5min-2026-date-envelopes.json`：候选证券H5 5,579个dataset在2026年有数据，**5,562个dataset最近一条落在2026年10月**；H5全局最新记录时间**2026-10-13 15:00**。Parquet年度2026五分钟9个月度文件，共407行组，全部有可用ts页脚，页脚最新候选时刻**2026-09-30 15:00**。因此最新可能双源重叠窗口为**2026-09-24—30**，H5晚于Parquet的最新尾段候选为**2026-10-07—13**。均只是时间元数据边界，不构成逐条覆盖审计或自动并集资格。

新增`suggested_h5_newer_window`保守推荐较晚的H5候选尾段；已上传的旧JSON足够确定本次两个窗口，**不用为了这个新字段重复扫描H5数据集边界**。本机更新代码并运行全部测试成功后，直接执行：

```powershell
git pull --ff-only origin main
.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test*.py" -v

.\.venv\Scripts\python.exe H5ParquetReconciler\tools\reconcile-local-a-share-h5-parquet.py "D:\stock" --years 2026 --periods 5min --from-date 2026-09-24 --to-date 2026-09-30 --universe a-share-candidate --batch-size 8192 --read-only --out "reports\h5-parquet-5min-2026-09-24-30-overlap.json"

.\.venv\Scripts\python.exe H5ParquetReconciler\tools\reconcile-local-a-share-h5-parquet.py "D:\stock" --years 2026 --periods 5min --from-date 2026-10-07 --to-date 2026-10-13 --universe a-share-candidate --batch-size 8192 --read-only --out "reports\h5-parquet-5min-2026-10-07-13-h5-newer.json"
```

请上传两份JSON，分析两源9月重叠数据的量价冲突以及10月H5实际有多少独有键。两段扫描只是独立有界审计，不更改任何原始行情、现有V3索引或正式合并状态。详情：[2026真实时间边界与两段双源核验](docs/DUAL_SOURCE_2026_BOUNDARY_CONFIRMED_20261026.md)。

## 2026年10月双源0行：先发现真实数据截止日期，再选窗口比较（2026-10-26）

最新上传的`h5-parquet-5min-2026-10-19-23-latest-gap.json`已验证本地2026-10-19至23日五分钟候选股票：**H5=0、Parquet=0、交集=0、两向独有=0**；2026 Parquet 9个文件的407个RowGroup全部被日期过滤、`issues=[]`。这不是两源行情一致或全年完整的证明，也不能据此判断H5最后一次下载日期。

新增纯只读工具`tools/inspect-h5-parquet-coverage-bounds.py`：H5仅读取候选股票dataset首末datetime（跨年二分定位）；Parquet仅读取row group footer ts最早/最晚，报告两源实际日期包络及保守的**不超过7天最新候选重叠窗口**。它不会读取真实OHLCV/Parquet行数据，也不会更新2025单源SQLite索引。缺失市场文件、时标footer不可用或两源时间包络不重合则不推荐日期；**元数据窗口不是实测时间键交集**。

更新main后在仓库根目录：

```powershell
git pull --ff-only origin main
.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test*.py" -v
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\inspect-h5-parquet-coverage-bounds.py "D:\stock" --year 2026 --read-only --out "reports\dual-source-5min-2026-date-envelopes.json"
```

把`dual-source-5min-2026-date-envelopes.json`上传后，基于`suggested_bounded_window`真实候选日期开展2026同键差集核验，不再盲目扫描空日期。此前2025-09-26至30真实核对有Parquet独有2,784根，也可使用已合并的`stock_day_gap_summary`功能做精确整证券日/局部K线缺口归因。

详见[2026年10月空窗口与时间边界探针说明](docs/DUAL_SOURCE_2026_OCT_EMPTY_AND_COVERAGE_BOUNDS_20261026.md)。

## 双源三日实测与证券日缺口归因（2026-10-26）

2025-09-26、29、30三日全候选A股真实双源报告：H5 779,568、Parquet 782,352、交集779,568、H5独有0、Parquet独有2,784；同键量价差461,937（59.26%），价格差227,715、量额差454,682（分类有交叠）。两源重复键0、issues=[]，但+5分钟时标、单位及证券真值尚未认证，不能自动合并。

为尽快定位2,784根Parquet独有K线的原因，新版报告按`证券+交易日`精确区分“整只证券当天H5无记录”和“该证券已有H5记录但仅部分五分钟键缺失”，并按代码前缀（非认证板块）分组统计量价冲突；JSON、Markdown同步输出，缺口统计须严格与全体记录守恒。

先运行全部测试，再优先检测2026-10-19至23日新H5数据是否超出购买Parquet的覆盖：

```powershell
git pull --ff-only origin main
.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test*.py" -v
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\reconcile-local-a-share-h5-parquet.py "D:\stock" --years 2026 --periods 5min --from-date 2026-10-19 --to-date 2026-10-23 --universe a-share-candidate --batch-size 8192 --read-only --out "reports\h5-parquet-5min-2026-10-19-23-latest-gap.json"
```

之后可用全新`--out reports\h5-parquet-5min-2025-09-26-30-gap-attribution-v2.json`以及原2025三日命令复核缺口归因。详见[三日双源实测与证券日缺口分类](docs/DUAL_SOURCE_2025_3DAY_GAP_CLASSIFICATION_20261026.md)。

## 双源主线优先：2025年三个交易日全市场五分钟对账（2026-10-26）

主线改回`Hikyuu H5 ↔ 购买的Parquet`真实数据对比，不等待2025年522个RowGroup单源索引完全完成。此前2025-09-30全市场单日（A股候选）已经得到H5 259,872根、Parquet 260,832根、同时间键重叠259,872、Parquet独有960、量价差异151,099根（58.14%）；但+5分钟时标、复权及数量单位仍是候选规则，不直接并集。

本轮让既有`reconcile-local-a-share-h5-parquet.py`在**一次有界窗口扫描**中按日分别输出两源唯一键、交集、双向差集与量价冲突，并在模块内scratch SQLite以`(symbol,time)`去重，检测所有Arrow批次/RowGroup之间的Parquet重复键，不再重复累计同一键。新增2项完全合成的测试，不会上传行情数据。

先`git pull --ff-only origin main`，运行本模块全部`unittest`（原main预计115项+本轮2项，实际以本机结果为准），再运行下列**一次Parquet年度文件扫描，涵盖9/26、9/29、9/30**的全候选证券对账：

```powershell
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\reconcile-local-a-share-h5-parquet.py "D:\stock" --years 2025 --periods 5min --from-date 2025-09-26 --to-date 2025-09-30 --universe a-share-candidate --batch-size 8192 --read-only --out "reports\h5-parquet-5min-2025-09-26-30-mainline.json"
```

重点复核报告`results["5min/2025"].by_day`的`h5_unique/parquet_unique/matched/h5_only/pq_only/value_mismatch`和`pq_duplicate_keys_across_batches`。双方重叠量价不一致不能未经核实就选择某一源覆盖另一源。全流程只读`D:\stock`，报告写`reports/`，临时SQLite写`work/`且自动清理；已有文件名不能覆盖。详见[2025年双源主线与多日单次对账说明](docs/DUAL_SOURCE_2025_5MIN_MAINLINE_20261026.md)。

## 五分钟数据太慢：先按交易日核验（2026-10-25）

原来的 `--years 2025 2026 --periods 5min` 会先把一整年的H5五分钟数据装入SQLite，**启动后可能数小时没有输出**。这不是一个适合你当前数据规模的默认操作。

新版增加：
- `--from-date` 与 `--to-date`（含首尾，`YYYY-MM-DD`），两者对应同一个年度。H5利用有序datetime二分查找，只读取指定日期的记录。
- Parquet只读取该年度文件中与目标时段有交集的行组；有可靠的 `ts` min/max统计时可大量跳过；统计缺失时保守读对应行组，不会错误地宣称无数据。**这仍不保证特定性能**，由原Parquet分区和行组结构决定。
- H5按市场及每400个证券打印进度，Parquet每约20秒或文件最后一组打印进度，包含行组读取/跳过、实际读取行数和窗口记录数。
- **默认不允许直接进行整年1min/5min核对**。需要明确 `--allow-full-year-minute` 才能运行旧的昂贵全年路径，不建议未经单日试跑就使用。
- 指定日期时，即便该日H5无任何记录，仍核对Parquet实际证券+时刻键（不再仅报告整个年度的Footer行数），这样可以判断某个交易日真正哪边独有。
- 报告包含开始/结束日期，`--resume` 只允许完全相同的日期范围、周期、年份及证券模式。先前未完成的2025年全年尝试不会自动恢复为单日结果。

先运行本机测试：
```powershell
git pull --ff-only origin main
.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test_reconcile_local_a_share_h5_parquet.py" -v
```

**第一轮只核对2025年9月30日的5min**，输出与SQLite全部自动放在模块内：

```powershell
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\reconcile-local-a-share-h5-parquet.py "D:\stock" --years 2025 --periods 5min --from-date 2025-09-30 --to-date 2025-09-30 --universe a-share-candidate --read-only --out "reports\h5-parquet-5min-2025-09-30-pilot.json"
```

如想扩大为同一月份，将日期改为 `--from-date 2025-09-01 --to-date 2025-09-30`，**并指定不同报告文件名**（同文件名不可覆盖或混用resume）。

对于新的短窗扫描，进度中的 `pq_row_groups_skipped_by_time` 为0，或者 `pq_source_rows_scanned` 非常大，说明原Parquet行组没有有效的时间聚类，后续需要换基于排序/分区索引的算法，不能单靠时间过滤解决全年性能。

如果中断时临时SQLite没有出现在 `work/_union_scratch`，可能是 `TemporaryDirectory` 已经在退出时清理，不能仅凭找不到临时文件判断数据库没有写入；本机要以进程、磁盘活动和日志验证。

更多实现细节见 [五分钟核对性能调整](docs/5MIN_PERFORMANCE_20261025.md)。

## 五分钟量价大面积差异：仅诊断少量证券（2026-10-25）

2025-09-30单日真实核对在259,872条匹配键里有151,099条（58.14%）被判为价格/量额不同，Parquet一年522个行组无一跳过。不要先扩大到整月，更不要先自动合并两库。

用新脚本进行**独立、只读、证券级诊断**，比较5分钟时间偏移和H5量额倍数假设。输出仍在本模块`reports/`，不含原始OHLCV值：

```powershell
git pull --ff-only origin main
.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test*.py" -v
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\diagnose-5min-alignment.py "D:\stock" --date 2025-09-30 --symbols SH600000 SZ000636 SH603181 SZ300747 BJ920680 --read-only --out "reports\5min-2025-09-30-alignment-diagnostics.json"
```

它将比较Parquet原始时标-5、0、+5、+10分钟四种候选，对每种记录四价全部相符次数、各价格字段异常次数，以及成交量/成交额的候选乘数相符次数。若Parquet行组存在有效`symbol`范围统计，将直接跳过不含所选股票的行组；统计缺失则保守读取。对少量证券的结果不可冒充全市场结论。

单日原始汇总、性能分析及下一轮依据见 [2025-09-30五分钟实际核对](docs/5MIN_DAY_20250930_FINDINGS.md)。该诊断不会生成并集数据。

## 五分钟第二轮诊断：2025-09-30价差幅度、量额比值及分时归因

首轮5只证券共240条Parquet、192条H5；可比的192条在Parquet起点+5分钟时完全匹配时刻，但只有63条OHLC全部一致。差异分别为开盘价80条、收盘价86条、最高价8条、最低价8条；固定量额倍数仍不足以解释冲突。具体见 [5MIN_ALIGNMENT_20250930_FINDINGS.md](docs/5MIN_ALIGNMENT_20250930_FINDINGS.md)。

`diagnose-5min-alignment.py` 新增按证券归因输出：开收高低价格绝对/相对误差分位数、上午/下午差异、成交量/成交额Parquet÷H5比值分位数与零成交计数，以及相邻K线边界的开收价格相符次数。它只保存汇总统计、不保存原始付费量价，不会进行合并。

从仓库根目录执行：

```powershell
git pull --ff-only origin main
.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test*.py" -v
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\diagnose-5min-alignment.py "D:\stock" --date 2025-09-30 --symbols SH600000 SZ000636 SH603181 SZ300747 BJ920680 --read-only --out "reports\5min-2025-09-30-attribution-v2.json"
```

新输出位于 `H5ParquetReconciler/reports/`，不会覆盖上次的 `5min-2025-09-30-alignment-diagnostics.json`。旧的6项诊断测试增加到10项，与核对程序的19项合计29项合成测试，本轮需要本地执行后才能确认全部通过。

## 第三轮：用H5一分钟记录重建五分钟K线（边界验证）

2025-09-30的V2报告发现4只股票的80处开盘价差异、86处收盘价差异与相邻K线边界价格之间存在高度关联，且量额总体接近，但尚不知道是数据商的成交归属、采样时标还是首末价补值规则。

新增只读程序 `tools/validate-5min-against-h5-1min.py`，**从不同的H5一分钟周期文件按两种分钟时标候选规则重建五分钟K线**，再与H5五分钟和Parquet五分钟分别比较OHLC、成交量、成交额。分钟不齐时不出假差异结论。H5两种周期文件不一定源头独立，不能把相符看作真值认证。

运行：

```powershell
git pull --ff-only origin main
.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test*.py" -v
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\validate-5min-against-h5-1min.py "D:\stock" --date 2025-09-30 --symbols SH600000 SZ000636 SH603181 SZ300747 BJ920680 --read-only --out "reports\5min-1min-independent-2025-09-30.json"
```

结果只保存到 `AStockDataTools/H5ParquetReconciler/reports/`，不修改原始行情且不覆盖其他报告。若该日一分钟H5不完整会直接标识 `not_verifiable_...`，无需反复扫描整年。

[本轮设计和判读规则](docs/5MIN_V3_H5_1MIN_CROSSCHECK.md)。新加入8项合成测试，目前核对19项、既有对齐10项、新一分钟交叉验证8项，合计**37项**，需本机测试验证，不能据提交推定全部通过。

## H5一分钟缺失后的五分钟量额守恒验证（2026-10-25）

V3实测已经确认，2025-09-30四只可比股票在H5一分钟文件中均为0条记录，BJ920680一分钟dataset不存在；无法用H5一分钟独立重建五分钟K线。不过4只可比证券的**全天Parquet/H5五分钟成交量和成交额合计比值均极其接近1**，提示逐根量额差异可能主要来自五分钟窗口边界划分。

新脚本 `tools/analyze-5min-session-conservation.py` 只读取选择的五分钟数据，不需要一分钟源，按上午/下午交易时段分别统计量额**净差、逐根差异毛差、抵消比例、相邻异号差额和累计差额峰值**，并检查OHLC几何合法性、跨源和同源的相邻开收价关系。这些都是区分“总成交缺损”与“可能的窗口重分配”的诊断证据，不会自动纠正源数据。

```powershell
git pull --ff-only origin main
.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test*.py" -v
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\analyze-5min-session-conservation.py "D:\stock" --date 2025-09-30 --symbols SH600000 SZ000636 SH603181 SZ300747 BJ920680 --read-only --out "reports\5min-session-conservation-2025-09-30.json"
```

[本轮证据、指标定义及验收要求](docs/5MIN_SESSION_CONSERVATION_20251025.md)。报告仅生成在本模块的 `reports/` 目录中，付费行情源文件保持只读。本轮添加7项合成测试，当前总共44项，仍需在用户本机实际验收。

## 只读并集预检：开始整理可补录键和隔离冲突

2025-09-30守恒实测发现：四只股票的逐根成交量毛差约0.9%—1.25%，全天净差仅0.0009%—0.0039%，且168组相邻非零差额中118组方向相反。这支持进一步研究不同五分钟窗口划分，但**不能选定任何一个来源为最终真值**。

新增 `tools/plan-5min-readonly-union.py`：按证券、单日、五分钟标准键划分H5独有、Parquet独有、完全一致、未经认证的容差一致和量价冲突，生成**候选补录计划和冲突隔离报告**。它不会将原始K线转换/写入任何文件；未认证的证券类型、时间标签、量额单位及冲突规则全部保持阻断状态，避免未经审查就自动合并。

```powershell
git status -sb
git pull --ff-only origin main
.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test*.py" -v
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\plan-5min-readonly-union.py "D:\stock" --date 2025-09-30 --symbols SH600000 SZ000636 SH603181 SZ300747 BJ920680 --read-only --out "reports\5min-union-preflight-2025-09-30.json"
```

所有产物只位于 `H5ParquetReconciler` 内，报告保存在 `reports/`。本轮新增8项合成测试，目前全部合成测试共52项，仍需本机执行验证。[开发说明及验收边界](docs/5MIN_UNION_PREFLIGHT_20251025.md)。

## 年度Parquet重复键和行组定位索引（2026-10-26）

2025-09-30的真实五分钟只读并集预检已完成：H5 192条、Parquet 240条、交集192、并集键240；H5独有0、Parquet独有48（BJ920680）、容差内不同8、重叠冲突184。这个小范围结果**不能证明全年没有重复键**，也不具备自动合并资格。

本轮新增 `tools/index-parquet-5min-coverage.py`：只读年度Parquet中的 `ts/symbol`，一次性生成证券—日期—48时段位图、跨批次/跨行组/跨文件重复键数量，以及证券/日期→Parquet行组定位表。SQLite保存在本模块 `work/indexes/`，不包含任何OHLCV价格/成交数值；报告在 `reports/`。可按RowGroup断点续跑，若源文件元数据发生变化将拒绝恢复。**第一次建全年索引仍需扫全年一次，不是瞬间完成。**

先测试并建立2个行组的试运行索引，再决定是否继续完整年度：

```powershell
git pull --ff-only origin main
.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test*.py" -v
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\index-parquet-5min-coverage.py "D:\stock" --year 2025 --universe a-share-candidate --max-new-groups 2 --read-only --report "reports\pq-5min-2025-index-smoke.json"
```

随后使用 `--resume` 和不同报告文件名继续完整索引。完整索引才能用于 `plan-5min-readonly-union.py --coverage-index "work\indexes\pq-5min-2025-a-share-candidate.sqlite"`，后续同日少数证券预检便只读取该索引指向的行组，**不需要每次重新扫描522组**。需比较索引前后预检的全部分类计数完全一致才视为通过。

[完整命令、索引适用范围、回滚和质量限制](docs/PARQUET_5MIN_KEY_INDEX_20261026.md)。新添加9项合成测试，当前总共61项，未经Windows本机完整验收前不得称已通过。

## Parquet五分钟索引V2：压缩行组位置（2026-10-26）

用户2025年五分钟索引的2个RowGroup试跑已经成功：247,776个有效候选时间键、重复键0、源时间异常0；但产出122,277条行组定位关系，说明旧版全年构建存在潜在的SQLite膨胀风险。

新版本将同股票、同日、同源文件的多个RowGroup编号打包成**一条压缩BLOB位图**；严格保留原来的48时段覆盖统计、跨组/跨文件重复键检测和恢复能力。**V2另用** `work/indexes/pq-5min-2025-a-share-candidate-v2.sqlite`，不触碰已生成的V1两组索引。

只先进行V2的2个行组试运行，**不要直接执行全年--resume**：

```powershell
git pull --ff-only origin main
.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test*.py" -v
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\index-parquet-5min-coverage.py "D:\stock" --year 2025 --universe a-share-candidate --max-new-groups 2 --read-only --report "reports\pq-5min-2025-index-v2-smoke.json"
```

预计新增2项单测，总数63项，需本机执行核验。对比V1/V2的源键数、重复数、逻辑行组关系数和`row_group_locator_compact_rows`，确认正确后再评估全年构建的磁盘开销。[V2索引设计与对照验收说明](docs/PARQUET_5MIN_INDEX_V2_STORAGE_20261026.md)。

## Parquet五分钟索引V3：稀疏行组列表（2026-10-26）

已在用户上传的两份真实SQLite中核实：V1索引2组大小5.79 MiB、V2大小5.89 MiB；两者247,776个有效唯一键、122,277条逻辑行组定位均一致。V2虽然把定位表从122,277行压缩到120,646行，但SQLite总大小**没有下降**，因为绝大多数股票/日期只出现在一个行组，位图未能充分压缩；对第522组这种稀疏高编号，旧V2位置位图还会产生大量零填充。

新V3将行组编号写成**升序的LEB128变长整数列表**，避免高编号位置位图的空字节。v1/v2两个SQLite文件完全保留；v3默认新建 `work/indexes/pq-5min-2025-a-share-candidate-v3.sqlite`。合并源行情仍被禁止。

先跑本机测试和**仅2个行组的V3试运行**，与V1/V2核对计数：

```powershell
git pull --ff-only origin main
.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test*.py" -v
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\index-parquet-5min-coverage.py "D:\stock" --year 2025 --universe a-share-candidate --max-new-groups 2 --read-only --report "reports\pq-5min-2025-index-v3-smoke-2groups.json"
```

V3验证正确后，再`--resume --max-new-groups 8`处理另外8组，观察累计10组的SQLite体积和速度。**不得直接从2组跳到522组**；V3是稀疏场景优化，不承诺所有布局都比V2快或小。[V1/V2的真实数据审查与V3使用说明](docs/PARQUET_5MIN_INDEX_V3_SPARSE_20261026.md)。本轮新增1项索引测试，模块总数64项，需用户Windows本机验收。

## V3索引：10个RowGroup已验证，增加磁盘预算续建

2025年度V3五分钟索引已经真实累计完成10/522个RowGroup：扫描1,230,846条ts/symbol，候选唯一键1,230,687，重复0，分区565,023，SQLite逻辑占用约27.64MiB；只有10组，并非全年度数据。**不要直接将剩余512组全部跑完。**

本轮新增 `--max-index-mib` 软磁盘保护，按每个RowGroup事务完成时，使用SQLite已分配空间及主库+WAL实际字节中的较大值判断；超过阈值会停止下一个RowGroup，保留`--resume`断点。它不是严格容量上限：单组事务可能使文件超额。报告新增本轮索引处理行数、耗时、组/秒和磁盘使用字段。

在 `D:\ChatGPT\AStockDataTools` 根目录，先通过合成测试（预计67项），再用已有10组V3索引续建**最多20个新行组，96MiB软预算**：

```powershell
git pull --ff-only origin main
.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test*.py" -v
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\index-parquet-5min-coverage.py "D:\stock" --year 2025 --universe a-share-candidate --resume --max-new-groups 20 --max-index-mib 96 --read-only --report "reports\pq-5min-2025-index-v3-budgeted-next.json"
```

需检查`soft_budget_reached`、`stopped_for`、`sqlite_budget_measure_bytes`、`elapsed_seconds_this_run`及新重复键。所有索引/报告写在本模块 `work/`和 `reports/`，付费源行情保持只读。[10组实测记录与分段续建指导](docs/PARQUET_5MIN_V3_10GROUP_BUDGET_20261026.md)。

## V3索引20组实测：WAL检查点回收避免容量预算过早停止

用户上传的2025年V3 20/522组报告显示，**已扫描2,459,646条源行、候选唯一键2,459,297、重复键0**；本轮新增10组耗时76.125秒。SQLite逻辑主库仅约47.93MiB，主库+WAL却达到96.14MiB，导致96MiB预算在第20组触发。

本轮保留V3原格式和已有索引文件，改进 `--max-index-mib`：触发软预算时先在行组事务提交后尝试 `PRAGMA wal_checkpoint(TRUNCATE)`，重新测量主库+WAL空间。如果回收后低于阈值可继续；若主库本体仍太大或检查点繁忙，继续保守停止。**不无条件放宽预算、不删除有效WAL，不对源数据写入。**

```powershell
git pull --ff-only origin main
.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test*.py" -v
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\index-parquet-5min-coverage.py "D:\stock" --year 2025 --universe a-share-candidate --resume --max-new-groups 10 --max-index-mib 96 --read-only --report "reports\pq-5min-2025-index-v3-wal-recovery-next.json"
```

新报告包含`wal_checkpoint_attempts_this_run`、`wal_checkpoint_busy_this_run`、`wal_reclaimed_bytes_this_run`，用于检验预算是否主要被可回收的临时WAL占用触发。**仍仅小批续建，不直接扫完剩余502个行组**。现有合成测试预计71项，新增4项需用户本机验收。

[20组真实结果、修复原理与本机步骤](docs/PARQUET_5MIN_V3_WAL_CHECKPOINT_20261026.md)。

## V3索引30组：WAL/DELETE事务模式对照（2026-10-26）

用户2025年V3最新报告：已完成30/522行组、有效唯一键3,687,846、重复0，本轮新增10组耗时129.36秒。96MiB容量保护未触发，但WAL截断检查点调用9次，报告中累计回收字节523,606,968是**多次回收操作总和**，不是净节省磁盘量。当前主库和主库+WAL都约61.01MiB，频繁截断对性能的影响仍需同条件试验。

新增`--journal-mode wal|delete`与`--clone-from-index`，从现有30组V3索引**只读快照**生成两份独立SQLite样本，在相同31—35号RowGroup分别测量WAL和DELETE。原V3文件完全不更改、不切换日志模式；两份试验文件只放在模块`work/indexes`，用户付费行情源仍只读。两组报告应在唯一键、重复键和覆盖分区方面完全一致，再比较耗时，不能根据不同RowGroup上两轮76秒/129秒的差距归因。

先运行全模块测试（本轮新增5项、预计76项），后用[完整两条对照试验命令](docs/PARQUET_5MIN_V3_WAL_DELETE_AB_20261026.md)。须保证足够的本机磁盘余量，96MiB仍是行组事务边界的**软预算**，DELETE日志也可能产生临时峰值。未经对照，不修改主V3索引模式，更不开始自动合并H5/Parquet。

## 2025 V3索引35组：WAL/DELETE性能持平，新增耗时阶段分析

用户已从同一30组索引快照分别用WAL与DELETE处理第31—35个RowGroup，结果唯一键均4,302,144、重复0、索引大小均64MiB左右，处理5组耗时**51.796秒 vs 51.219秒**，差距仅约1.1%。WAL执行5次检查点，但**不能由此证明SQLite日志模式是主要瓶颈**，暂不切换原主索引的默认WAL。

下一步只增加`stage_profile_this_run`分段耗时字段，测量`parquet_read_and_key_aggregation`（Arrow惰性读取与Python键聚合）、`sqlite_group_commit`、`budget_guard_and_checkpoint`与最多5个最慢RowGroup，分别确认实际慢在何处。报告不包含原始OHLCV。

```powershell
git pull --ff-only origin main
.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test*.py" -v
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\index-parquet-5min-coverage.py "D:\stock" --year 2025 --universe a-share-candidate --resume --max-new-groups 5 --max-index-mib 128 --journal-mode wal --read-only --report "reports\pq-5min-2025-v3-stage-profile-35.json"
```

此命令继续**原主V3**索引，不再建性能对照副本；如原V3已被手动推进到其他组数，要根据实际组数验收，不要固定认为停在35组。现有76项合成测试预计新增3项，累计79项，需用户本机验收。[A/B真实结果与性能分段诊断说明](docs/PARQUET_5MIN_V3_STAGE_PROFILE_20261026.md)。

## 2025五分钟索引第35组：SQLite写入已成已测最大耗时项

用户2025 V3主索引实际完成35/522 RowGroup，累计唯一五分钟键4,302,144、重复0。新增5组用时53.078秒，其中SQLite事务写入28.486秒（53.7%）、Parquet读取与Python键聚合14.764秒（27.8%），未细分9.828秒。结尾完整SQLite摘要扫描属于原“未归因”部分，本轮已经增加 `stage_profile_this_run.phases_seconds.final_index_summary` 单独测量，避免误判为全是Parquet或数据库事务时间。

新增可选 `--write-order source|pk-sorted`：保持现有默认`source`；`pk-sorted`只改变批量UPSERT前的内存排序顺序，不改变SQLite schema、48时段键、重复数或WAL/DELETE策略。理论上按主键连续写入可能减少B-tree随机页更新，但排序本身也有成本，尚无本机提速证据。

**下一次要先跑83项合成测试，再从已完成35组的主V3索引创建两份独立SQLite快照，各以相同WAL/128MiB软预算处理第36—40组。** 具体完整命令、报告文件名和正确性/性能比较标准见 [本轮35组性能分析和主键排序A/B说明](docs/PARQUET_5MIN_V3_SQLITE_WRITE_AB_20261026.md)。只有两份报告所有键数、异常和索引摘要一致，才比较写入耗时。主V3本身不更改，购买的源行情始终只读。

## 第40组排序写入A/B与可选轻量进度报告（2026-10-26）

用户提交两份从35组V3索引快照开始、同样处理第36—40组的报告：`source`原顺序耗时55.484秒（SQLite提交30.969秒），`pk-sorted`排序耗时50.922秒（SQLite提交26.452秒），分别总耗时降8.2%、SQLite写入降14.6%。最终唯一键4,918,521、正常时段重复0、股票日分区1,276,936等统计完全一致；仅一轮A/B，不据此自动改变默认写入顺序。

两模式报告显示末尾 `final_index_summary` 分别耗时10.156秒及9.687秒。新版增加 **`--report-detail progress`**，用于未完成全年索引的分批续建：省去每批末尾数百万键的完整唯一性/定位扫描，但**这些未经核验的指标会显式显示`null`，绝不会伪造成0，也不会把索引标记为年度完成**。默认`full`不变；全部522组完成时无条件执行`full`完整审计才能获得完成标记。必须定期做完整审计；报告细节模式不改变源Parquet读取或SQL写入。

先做本机88项合成测试；通过后，可在仍为35组的V3**主索引**上尝试一次最多10组的保守续建（两份第40组A/B索引是另外的副本）：

```powershell
git pull --ff-only origin main
.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test*.py" -v
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\index-parquet-5min-coverage.py "D:\stock" --year 2025 --universe a-share-candidate --resume --max-new-groups 10 --max-index-mib 192 --journal-mode wal --write-order source --report-detail progress --read-only --report "reports\pq-5min-2025-v3-quick-progress-45.json"
```

V3索引仍在本模块`work/indexes`；本轮报告写入`reports`，原始`D:\stock`仍只读。若要完整唯一键/重复键审计，使用默认`--report-detail full`并以不同`--report`文件名运行，不能把快报的空指标视为源数据没有重复。[真实40组A/B分析及快报安全设计](docs/PARQUET_5MIN_V3_FAST_PROGRESS_20261026.md)。

## 2025五分钟主V3索引57组：定位事务退出的真实耗时（2026-10-26）

主索引已经从52组真正续建至57/522组，累计候选源行7,009,197，本轮40.828秒新增5组。SQLite写入25.923秒中，事务退出及其他开销15.156秒（58.47%），定位表更新8.376秒（32.31%），覆盖表更新2.047秒（7.90%）；本轮无预算/源文件异常，主库+WAL约137.11MiB。`progress`不执行新的精确重复键审计，因此该主库的唯一/重复字段仍为null。先前57组A/B副本full审计不能代替主库的独立审计。

最新索引器仅增加原sqlite3连接`__exit__`/事务进入的细分时钟计量；**不更改SQL语句、SQLite schema、WAL、`synchronous=FULL`、事务提交与回滚逻辑**，新字段为旧`commit_and_other`的内部子项，不能作为额外耗时。先运行预计115项合成测试，通过后从主库57组仅新增5组至62：

```powershell
git pull --ff-only origin main
.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test*.py" -v
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\index-parquet-5min-coverage.py "D:\stock" --year 2025 --universe a-share-candidate --resume --max-new-groups 5 --max-run-seconds 90 --max-index-mib 192 --journal-mode wal --write-order source --report-detail progress --read-only --report "reports\pq-5min-2025-v3-transaction-exit-62.json"
```

通过`stage_profile_this_run.sqlite_transaction_boundary_seconds.context_exit_seconds`核实提交耗时，再决定是否在隔离副本中开展不同同步持久化策略的试验，主库保持严格FULL。详见[57组主库分项结论与事务退出直接计时](docs/PARQUET_5MIN_V3_57GROUP_TRANSACTION_PROFILE_20261026.md)。

## V3索引第57组严格A/B：source保留默认，定位SQLite写入瓶颈（2026-10-26）

主V3索引在52组的独立完整键审计已确认6,394,912个有效唯一键、重复0；两份从52组快照克隆的source和pk-sorted实验副本均处理到57/522组，并经严格只读比较器确认完全相同：7,009,197个唯一五分钟键、重复0，三张逻辑表逐行相同。**主索引仍为52组，不要混淆实验副本和真实续建进度。**

本轮source总耗时40.687秒、SQLite写入25.156秒；pk-sorted总耗时40.859秒、写入26.233秒。对比早前36—40组排序写入快约8.2%的单轮结果，**pk-sorted加速没有复现，保留source默认配置**。新的分项计时把SQLite写入再拆成Python准备、daily覆盖UPSERT、locator定位UPSERT、checkpoint插入和事务提交/其他，嵌套计时**不是新增加的总耗时**。本轮新增3项合成测试，预计合计113项，尚需Windows本机测试。

下一步在保持原始`D:\stock`完全只读的前提下，从主库52组resume最多新增5组至57组，90秒时间软预算与192MiB空间软预算不变：

```powershell
git pull --ff-only origin main
.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test*.py" -v
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\index-parquet-5min-coverage.py "D:\stock" --year 2025 --universe a-share-candidate --resume --max-new-groups 5 --max-run-seconds 90 --max-index-mib 192 --journal-mode wal --write-order source --report-detail progress --read-only --report "reports\pq-5min-2025-v3-sqlite-breakdown-57.json"
```

核对`stage_profile_this_run.sqlite_write_breakdown_seconds`、`stopped_for`和`soft_budget_reached`等字段后，再决定是否做新的SQL优化。详见[真实第二轮A/B结果及写入阶段细分](docs/PARQUET_5MIN_V3_AB_ROUND2_SQLITE_BREAKDOWN_20261026.md)。

## 2025 V3索引52组：先full审计，再做同快照严格A/B（2026-10-26）

主V3索引已顺利推进至52/522组：新处理5组共614,400行、耗时44.703秒（SQLite写入28.484秒，读取聚合16.203秒），90秒软时间预算和192MiB磁盘软预算未触发。累计6,394,912条**A股候选源行**，由于使用progress报告，准确的去重键/重复键数量仍为`null`。必须先使用`audit-parquet-5min-coverage.py`对目前52组做单独full只读审计。

新增`tools/compare-v3-write-order-ab.py`，用于随后从同一个52组快照分别创建source和pk-sorted副本、各处理第53—57组后，严格检验两份SQLite的三个逻辑表逐行相等。它在**两份均已完成单独full审计、来源和处理范围一致、未触发软预算**时才报告总耗时和SQLite提交阶段的性能差异；不能仅靠progress字段或物理SQLite数据库大小推断数据正确性。**不会推动主V3索引或自动修改默认写入顺序。** 完整审计和A/B三条运行命令、空间注意事项、8项新增离线测试详见[52组完整审计和严格A/B计划](docs/PARQUET_5MIN_V3_52GROUP_AB_CHECK_20261026.md)。

## 2025年V3索引47/522：可选单轮运行时间软预算（2026-10-26）

本机第46—47组只用了16.687秒，原45组报告里的1,145秒异常未归因空档在这次两组测试中没有复现；这不足以确定早前性能波动的根因。新增`--max-run-seconds`，与现有`--max-new-groups`、`--max-index-mib`同时使用；**仅在提交一个完整RowGroup之后及进入下一个组之前**检查运行时间，因此不是能中断长事务/系统休眠的硬超时。未指定该参数不改变已有CLI行为。

下一次建议最多5组（47→52），90秒单轮软时间上限和192MiB SQLite软容量上限，仍保留`source`默认写法：

```powershell
.\\.venv\\Scripts\\python.exe H5ParquetReconciler\\tools\\index-parquet-5min-coverage.py "D:\\stock" --year 2025 --universe a-share-candidate --resume --max-new-groups 5 --max-run-seconds 90 --max-index-mib 192 --journal-mode wal --write-order source --report-detail progress --read-only --report "reports\\pq-5min-2025-v3-soft-wall-52.json"
```

新字段`soft_wall_budget_reached`、`max_run_seconds_soft_budget`和`stopped_for`用于区分正常数量截止、时间预算与磁盘预算。只有另行full审计才能获得准确去重键数；详见[47组复测与软时间预算说明](docs/PARQUET_5MIN_V3_SOFT_TIME_BUDGET_20261026.md)。

## 2025年五分钟V3索引45/522：异常墙钟耗时诊断（2026-10-26）

用户主V3索引从35→45组的 `--report-detail progress` 报告，新增10组处理1,232,892行，总耗时1,318.813秒；其中现有读取+写入+预算+摘要仅173.750秒，其他1,145.063秒（86.83%）**原因未查明**。SQLite第40号RowGroup一次提交耗时79.235秒，主库+WAL约132.70MiB，192MiB预算未触发；累计候选行5,534,876，**不是**经full复核的去重唯一键数。

索引器最新进度报告新增Parquet footer、checkpoint查询、进度输出、整段行组循环剩余墙钟耗时和最慢整组时长。不要将剩余墙钟时间武断解释成SQLite I/O，也不要直接扩展至剩余477组。先完整测试，再从45组主索引**最多新增2组**：

```powershell
.\\.venv\\Scripts\\python.exe H5ParquetReconciler\\tools\\index-parquet-5min-coverage.py "D:\\stock" --year 2025 --universe a-share-candidate --resume --max-new-groups 2 --max-index-mib 192 --journal-mode wal --write-order source --report-detail progress --read-only --report "reports\\pq-5min-2025-v3-wall-gap-47.json"
```

实际断点、限额和stop原因均以本地JSON为准。详见[45组异常性能与复测说明](docs/PARQUET_5MIN_V3_WALL_GAP_PROFILE_20261026.md)。

## V3 索引的独立只读完整审计（2026-10-26）

当使用 `--report-detail progress` 跳过大表扫描后，可用独立的 `tools/audit-parquet-5min-coverage.py` 对**现有已提交 RowGroup**重新执行全量键统计，不推进断点、不改 SQLite 认证元数据、不读取原 Parquet 的行情行：

```powershell
.\\.venv\\Scripts\\python.exe H5ParquetReconciler\\tools\\audit-parquet-5min-coverage.py "D:\\stock" --year 2025 --universe a-share-candidate --read-only --report "reports\\pq-5min-2025-v3-readonly-full-audit-01.json"
```

此报告的重复键/唯一键是**当前已建立索引部分**的全表重审，不是完整年度认证；即使发现0个重复也绝不能据此执行自动并集。详情和合成测试见 [V3 只读定期审计文档](docs/PARQUET_5MIN_V3_READONLY_AUDIT_20261026.md)。

## 输出

程序在输出目录产生：

- `h5-parquet-union-audit.json`：所有年份/周期的来源行数、交集、差集、量价不一致、时间首末、按日统计及少量股票@时间示例。
- `h5-parquet-union-audit.md`：中文汇总报告。

核心计数：`h5_only_rows`、`pq_only_rows`、`matched_keys`、`value_mismatch_rows`、`opening_candidate_mismatch_rows`、`pq_0930_extra_candidate_rows`。当某周期该年H5全无数据时，Parquet仅做footer候选统计，字段 `pq_year_metadata_only_no_h5_rows=true`，**不能视为精确Parquet独有键清单**。

### 关键限制（请先了解）

1. 当前只覆盖H5存在的 `day / 5min / 1min` 三个周期；并不报告15/30/60分钟、周/月、复权因子的H5/Parquet差集。
2. 成交额和成交量、5分钟起点/终点、09:30额外一分钟等采用**候选规则**；H5出现的13:00疑似午间误标需要另审。重叠不同并不自动意味着其中一方坏了。
3. H5某年份某周期完全没数据时，为节约读取成本，Parquet只统计年度文件footer信息；明细覆盖没有验证。
4. 数据扫描错误、重复键及未知证券格式必须检查`issues`与完整性标记。当前版本**没有完全处理跨Parquet批次的重复键**，不能据此直接自动构建并集。
5. 本程序从不写原始H5或Parquet，也不产生合并数据库；后续合并将在源数据目录以外生成新库，必须先获冲突策略验收。

## 既有研究背景

此前在本地抽查发现H5部分2026-07-16日线与分钟累计成交额异常、Parquet时间/单位与H5口径存在差异；同时H5早期分钟数据未手工下载。历史样本验证已证明**不能用有日线推断有分钟线**，因此本项目按每个周期独立核验，先验证重叠，再找差集。具体核验事实与新数据报告以后保存在本目录的 `docs` 内。


## 2026-10-25：真实16年日线报告后的A股候选范围核验

原先的`--universe all`（默认值）包含H5指数、B股及其他非A股品种。例如`SH000001` 被纳入H5独有，导致旧报告的数百万条“差集”**不能直接理解为可以补齐的A股股票K线**；一些BJ920xxx在2015年就被Parquet标为北交所，也可能是历史证券代码回溯。

现在可选 `--universe a-share-candidate`：用沪市600/601/603/605/688/689、深市000/001/002/003/300/301、2022年起的京市920/430/830/870股票**代码前缀**初步隔离指数、B股和北交所开市前代码回溯。它并没有独立上市/退市证券主数据，**只能称为A股候选证券集**，不能认证所有入选代码皆为股票或覆盖所有真实A股。默认 `all` 不变，以兼容旧报告。Parquet年度footer若仅用元数据估计，仍无法依代码过滤，状态字段 `pq_footer_row_count_not_equity_filtered` 会显式提示。

从仓库根目录运行**新的模块内报告路径**（不要在旧JSON上`--resume`）：

```powershell
git pull --ff-only origin main

.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test_reconcile_local_a_share_h5_parquet.py" -v

.\.venv\Scripts\python.exe H5ParquetReconciler\tools\reconcile-local-a-share-h5-parquet.py "D:\stock" --years 2025 2026 --periods day --universe a-share-candidate --read-only --out "reports\h5-parquet-day-equity-2025-2026-v2.json"
```

检查完成后，扩大到2011—2026年整段；**无法直接将旧16年报告合并为新报告**，两种证券集分母不同、交易日及历史代码口径不同，且候选代码仍有风险。新模式仍只读、未处理跨批次重复键，不允许直接生成并集库。

旧16年数据报告的具体统计与风险见 [日线16年全量核对分析](docs/DAY_AUDIT_20261025.md)。
