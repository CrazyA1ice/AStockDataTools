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
