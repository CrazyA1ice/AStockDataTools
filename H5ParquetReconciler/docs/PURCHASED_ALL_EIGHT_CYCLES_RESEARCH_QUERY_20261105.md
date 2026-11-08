# 2026-11-05 购买Parquet八周期原位查询与2025来源边界

## 已在用户 Windows 真实环境验证的证据

- 全周期2025/2026页脚清单：9项合成测试 OK（其中Windows符号链接测试1项 SKIP），真实源脚本 PASS，80个带2025/2026年份标签的Parquet文件。
- 实际目录：`15min,1min,30min,5min,60min,day,month,week,复权因子`。**复权因子非K线周期**，不可当OHLCVA输入；其2025/2026文件名匹配结果为0，不代表目录无其他有效数据。
- 2025 1min=321744640,5min=64081920,15min=21360640,30min=10680320,60min=5340160（页脚行数）。分别按241/48/16/8/4除，均为1335040个**理论标准股票日当量**，不证明逐股票每个交易日完整。
- 2025所有五个分钟周期页脚最早2025-01-02、最晚2025-12-31，日/周/月也有2025年购买源。
- 2026所有八周期实际最晚页脚日期2026-09-30；10月8/9/12/13有已SHA验收、与精确差集数量匹配的私有H5-only分钟补缺分区。
- 1/5分钟双股票本机验证19/19合成 PASS、`SH600000`+`SZ000001` 1min总2402/5min总480，购买源优先，已验证私有H5补缺只在购买股票日缺失时使用。没有市场写入或生产指针激活。

## 八周期研究查询（2026-11-08 Windows首次真实验收已通过）

- 扩展原有`query-parquet-primary-readonly.py`白名单为`day,1min,5min,15min,30min,60min,week,month`；新增周期仅使用**原始Parquet时间戳**，不自动转换为区间起止、交易所自然周/月或复权后行情。
- 新增`tools/query-purchased-primary-all-eight-cycles-readonly.py`统一单证券/周期/日期查询：1/5分钟复用已验收的原有分钟购买优先+显式私有H5补缺接口，其余六周期复用原购买Parquet只读查询器，无H5替代或重采样。
- 新增`tests/test_query_purchased_primary_all_eight_cycles_readonly.py`（10项新增合成测试）和`run-purchased-primary-all-eight-cycles-smoke.ps1`，后者重跑旧购买查询、分钟19项及新合成测试，再读取真实2025/2026九月六个购买源周期与2026年9/10月1/5分钟补缺。
- **2026-11-08 Windows实机已通过新增10项八周期合成测试，及另37项相关回归与2025/2026真实样本。** 部分月/周原始时间标签和2026完整交易日仍未证实；`复权因子`还需单独调查文件结构和企业行为语义。
- 所有新查询仅将授权OHLCVA留在用户本机Python内存；CLI只有计数和来源字段，无原始行情价格输出，不写盘/激活生产，也不做金额/成交量的供应商单位认证。

## 下一步

1. 八周期真实样本已经通过；不重复测试同一股票同一日期。后续使用既有页脚工具盘点2011—2026各购买周期的来源年份与真实原始时间边界，定位缺源或异常年份。
2. 2025年1/5分钟购买H5时间键差集已按月验收，不重复构建原购买源索引；剩余是2026未验收窗口及历史高周期的逐证券、逐时间键覆盖，不得把页脚当自动缺口。
3. 独立检查复权因子目录文件格式和复权规则；禁止在缺乏原数据授权/语义认证时进行默认调整。
4. 完成完整日期/量纲/来源质量门禁后再考虑正式生产入口及H5镜像。

## 2026-11-08 Windows physical inventory: existing 15/30/60min and day/week/month files

User's latest Windows read-only inventory of original `D:\stock\AllCycleAStockData` shows six original PURCHASED source folders, **24 Parquet files in each**, 144 in total. Approximate `GB=bytes/1GiB` sizes below are rounded to three decimal places:

| Native purchased cycle folder | Parquet files | Reported GiB |
| --- | ---: | ---: |
| 15min | 24 | 3.941 |
| 30min | 24 | 2.030 |
| 60min | 24 | 1.049 |
| day | 24 | 0.226 |
| week | 24 | 0.059 |
| month | 24 | 0.015 |
| **Six-cycle total** | **144** | **7.320** |

This is **filesystem inventory only**, not evidence that all 24 files
represent 24 distinct years, or that any stockday/calendar/source schema
is certified. No file data or price values were opened or changed.

**Avoid reimplementation:** The branch already contains
`tools/query-purchased-primary-all-eight-cycles-readonly.py` and the
ASCII Windows one-command gate
`run-purchased-primary-all-eight-cycles-smoke.ps1`, which:
- runs previously developed synthetic original Parquet query checks, the
  19-tested 1/5minute purchased/H5 opt-in routing checks, and 10 independent
  eight-cycle synthetic tests;
- directly queries existing **2025/2026** original purchased Parquet for
  15/30/60-minute, day, week, month using bounded real `SH600000`
  date windows, **without** copying or resampling any purchased bars;
- separately exercises the existing purchased-first and explicitly opt-in
  SHA-verified PRIVATE H5 fallback for 1/5minute on 2026-09-30..10-13;
- emits only aggregate counts and provenance, retains existing raw
  purchased time labels, and refuses any production activation.

**The six-cycle 144-file inventory has passed on Windows; the combined
eight-cycle *real-market smoke* has not yet been reported as passed.**
The next command should be the existing
`run-purchased-primary-all-eight-cycles-smoke.ps1`, not another materialization
or manual 144-file reader. After this real sample passes, continue year-range
and securities/date coverage checks with the already available
`run-purchased-2025-cycle-footer-survey.ps1` (footer evidence only), then
establish separate numerical unit, corporate action/adjustment and calendar
certification before production release. Do not interpret raw week/month
timestamps as proven exchange aggregation boundaries.

## 2026-11-08 Windows real all-eight-cycle query acceptance PASS

User's real Windows output accepted the already-present `run-purchased-primary-all-eight-cycles-smoke.ps1`: **18 direct-source + 19 minute-source-priority + 10 all-eight-cycle synthetic tests PASS (47 total)**, and ALL real original-source queries succeeded, with zero original-market or production writes.

| Cycle | 2025 purchased `SH600000` real query | 2026 purchased `SH600000` real query |
| --- | ---: | ---: |
| 15min | 16 bars | 16 bars |
| 30min | 8 bars | 8 bars |
| 60min | 4 bars | 4 bars |
| day | 1 bar | 1 bar |
| week | 5 bars (September bounded window) | 5 bars |
| month | 1 bar (September bounded window) | 1 bar |

The minute delegation real sample was 2026-09-30..2026-10-13 for `SH600000`: 1min purchased=241 plus SHA-checked existing private H5=960 (total 1201); 5min purchased=48 plus private H5=192 (total 240). Original purchased source wins whenever its stockday has rows, and H5 fallback requires explicit research opt-in. No purchased bar copies, H5 mirror changes, new market/index artifacts, or production activation occurred. All period timestamps are preserved in original source conventions, not verified cross-cycle/session semantics. This is a bounded **research query acceptance**, not all-market/all-history coverage or unit/adjustment certification.

**Already available next step without new code or data rewrites:** `tools/survey-purchased-all-cycle-footers-readonly.py` accepts `--years 2011 2012 ... 2026`; run a single original-Parquet-FOOTER-only 2011-2026 eight-cycle source-year audit, printing condensed year-level counts/envelopes. Identify missing named years, unassigned filenames, unknown/noncanonical source directories and absent rowgroup timestamps; avoid rescanning OHLCVA or claiming independent exchange calendar. The older `run-purchased-2025-cycle-footer-survey.ps1` is only a 2025/2026 convenience wrapper; do not mistake it for 2011-2026 coverage certification. Once source-year ranges are known, finish per-security coverage / corporate action / price volume amount gates before considering a production active version.

## 2011—2026八周期页脚年度库存：最短下一步入口（新代码待Windows）

为避免重复实现导入器，已新增 ASCII Windows PowerShell 5.1 入口 `run-purchased-2011-2026-all-eight-cycle-footer-coverage-readonly.ps1`。它复用**已有**的 `tools/survey-purchased-all-cycle-footers-readonly.py`，先跑旧九项合成回归，再对2011—2026连续16个年份的原购买Parquet元数据执行单次只读盘点，按照八周期分别输出：文件名年份实际存在数量、源文件数、页脚原始行数、分组数、最早与最晚原始时间戳、未见来源文件的年份、失效ts统计组数、跨文件名年份组数。非K线 `复权因子` 保留为独立的未映射目录。仅输出汇总，不生成新的行情文件或数据库索引。

**此新入口尚待用户Windows实机验收**；支持的源签名是源文件元数据而非全内容SHA。报告中的命名年份与元数据日期包络不能作为该年份每一笔行情、每一证券、交易所交易日或数值量纲经认证的证据，也不保证所有24个物理文件各自对应不同年份。验收后再决定需要对哪些具体年份/周期做更细粒度的缺口验证，不要开启旧全量购买数据重物化worker。

## 2026-11-08 Windows real 2011-2026 purchased eight-cycle footer envelopes PASS

The real Windows 2011..2026 footer-only acceptance wrapper completed: `Ran 9 tests ... OK (skipped=1)` (8 passed, one skipped), all eight purchased K-line folders show **16/16 filename-assigned years and 24 files per folder**. No source file-year gaps, nonempty RowGroups with missing/unusable `ts` bounds, or bounds outside the filename-assigned year; **0 original OHLCVA copied and 0 market files altered**. Each entry is *Parquet footer row count*, not a census of A-share unique valid keys.

| Purchased source period | Footer rows (16 named years) | RowGroups | First observed raw source timestamp | Latest observed raw source timestamp |
| --- | ---: | ---: | --- | --- |
| 1min | 3,447,422,899 | 28,035 | 2011-01-04 09:30 | 2026-09-30 15:00 |
| 5min | 686,623,649 | 5,572 | 2011-01-04 09:30 | 2026-09-30 14:55 |
| 15min | 228,874,552 | 1,876 | 2011-01-04 09:30 | 2026-09-30 14:45 |
| 30min | 114,437,276 | 951 | 2011-01-04 09:30 | 2026-09-30 14:30 |
| 60min | 57,218,640 | 484 | 2011-01-04 09:30 | 2026-09-30 14:00 |
| day | 14,115,707 | 139 | 2011-01-04 08:00 | 2026-09-30 08:00 |
| week | 2,996,956 | 47 | 2011-01-04 08:00 | 2026-09-30 08:00 |
| month | 711,331 | 24 | 2011-01-06 08:00 | 2026-09-30 08:00 |

**Critical scope:** 16/16 is evidence for **named-year source availability only**, not the full set of trading dates, unique per-security K-lines, session/weekly/monthly labeling, physical units, corporate adjustments, or continuous market availability. The monthly first source label `2011-01-06` must be preserved, not forcibly treated as a universal month-end. Do not equate purchased row footer counts with candidate A-share filtered row counts.

There is an additional **`复权因子`** source folder with one Parquet file unassigned to a year by filename. Its schema, date range, adjustment sign/direction and applicability are **unverified**, and its missing filename year is NOT proof of no data. The next small gate should inspect only its Parquet footers/schema (no row decoding and no implicit price adjustment). Independent coverage for post-2026-09-30 15/30/60min/day/week/month remains a separate source gap/synthesis candidate and is not made complete by this inventory.

## 2026-11-08 adjustment factor source structure preflight (pending Windows acceptance)

After the real eight-cycle 2011..2026 purchase footer inventory passed, the only noncanonical purchased-source directory observed was `复权因子` with one `.parquet` file lacking the inventory's expected filename-year pattern. **This is a separate adjustment-factor source, NOT a ninth K-line period; do not assume the unassigned file has zero effective dates or factors.**

The branch now includes `tools/inspect-purchased-adjustment-factor-parquet-schema-readonly.py`, its six synthetic tests, and the ASCII-only `run-purchased-adjustment-factor-schema-readonly.ps1` runner. This preflight reads **only original Parquet footer and Arrow schema** for files in `D:\stock\AllCycleAStockData\复权因子` using strict file/rowgroup/column budgets. It outputs file count, footer rows/rowgroups, column names and Arrow types. **It does not read any original row batches, any factor values, OHLCVA or ticker identifiers; it does not infer year coverage, adjustment-factor direction, base date or split/dividend convention.** All original market files and production pointers remain untouched. Source stat metadata is rechecked after read, which is not a content SHA certificate.

The six synthetic tests + real original adjustment-factor source gate have **not yet run on the user's Windows market**. Only after seeing the actual Arrow schema should the project decide whether to build a separate optional corporate-action-factor reader and prove source date semantics. Keep raw purchased OHLCVA and unadjusted query results unchanged until that gate is passed. The post-2026-09-30 lack of purchased 15/30/60min/day/week/month source files is still a separate incomplete source frontier requiring a verified low-cycle aggregation proposal, not an automatic fill.
