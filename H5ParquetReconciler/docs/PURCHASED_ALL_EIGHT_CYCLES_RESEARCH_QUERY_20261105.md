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

## 2026-11-08 Windows HFQ factor source schema PASS, then independent key/date health gate

The user's real Windows output of `run-purchased-adjustment-factor-schema-readonly.ps1` passed **6/6 synthetic tests and real source footer/schema**. The purchased `复权因子` folder has **1 actual Parquet file**, **68,438 source footer rows**, **1 RowGroup**, and exactly the observed fields `symbol:string`, `d:date32[day]`, `hfq_factor:double`. No factor column data, OHLCVA, or source values were read in that acceptance; no source files were modified and production remained disabled.

The name `hfq_factor` suggests a vendor **后复权** multiplier column. It does **not** prove that the factor should be multiplied/divided into unadjusted historical prices, that factors are daily instead of sparse event updates, that an earlier date requires a carry-forward, or that the base date / adjustment policies match the eight-cycle purchased OHLCVA. Do not automatically create adjusted K-lines or a ninth K-line cycle.

**Next bounded data-key health check (NEW; not yet Windows-verified):** `tools/audit-purchased-adjustment-factor-keys-readonly.py` and `run-purchased-adjustment-factor-keys-readonly.ps1`, with seven synthetic source-only tests plus the existing six schema tests. They inspect **only** the original factor file's `symbol,d,hfq_factor` columns (not any purchased OHLCVA source), streaming bounded batches. Output aggregates only: earliest/latest valid factor date, count of distinct raw symbols, count of distinct exact `symbol,d` keys and duplicates, by-year row counts, null/nonfinite/nonpositive factor counts, and counts of factors equal/not equal to one. The original source stat identity is verified after inspection; no individual ticker or factor value is printed or written. Even if all quality counts pass, calendar/master, factor direction and legal corporate-action semantics remain `false` until independent vendor and price-adjustment evidence is obtained.

**Priority:** This factor-key source-health gate is deliberately small (68,438 reported rows) and should not delay the outstanding post-2026-09-30 15/30/60-minute, day/week/month source frontier validation. In the meantime purchased original eight-cycle research query is usable with *raw unadjusted source OHLCVA* and the already gated 1/5-minute H5-only private stockdays. No production activation/mirror is permitted.

## 2026-11-08 Windows real factor key audit: 5,499 invalid-date rows require classification

The user ran `run-purchased-adjustment-factor-keys-readonly.ps1` on their local original factor source: 6 existing schema + 7 key-health synthetic tests PASS; real audit output PASS with no original K-line reads or market writes.

Real source totals: 68,438 factor rows across a single source file / 1 RowGroup; prior schema was `symbol:string,d:date32[day],hfq_factor:double`. With the **original** tool's date-gated counting, 5,501 raw source symbol strings had **valid dated keys**, 62,939 valid distinct `symbol,d` keys, **0** exact dated duplicate keys, and valid-key dates 1990-12-01..2026-09-30. There were **5,499 `INVALID_DATE` rows** and 0 invalid symbol strings. Annual valid-dated records ranged from 1990=6 through 2025=5,007 and 2026=4,292. The original tool's factor health counts `POSITIVE_ONE=5207`, `POSITIVE_NONONE=57732`, `NONFINITE=0`, `NONPOSITIVE=0`, `NULL_OR_NONNUMERIC=0` sum to **62,939**, NOT 68,438. The **5,499 invalid-date records were skipped before their factor values were checked**: those zero anomaly counts cannot be generalized to the whole file.

**Interpretation:** The 5,499 invalid-date rows almost equal the 5,501 symbols with valid-dated entries. It is plausible (but **NOT** demonstrated) that the vendor encodes an undated factor/base anchor per symbol. The existing data does not show whether date32 `d` is actually null, outside supported calendar, or something else, whether each symbol has one such record, or whether factor values in those rows are finite/positive. **Do not delete, fill, forward-propagate, adjust historical K-lines, or discard them.**

**In-place correction (pending new Windows run):** We updated the *same* `tools/audit-purchased-adjustment-factor-keys-readonly.py`, `tests/test_audit_purchased_adjustment_factor_keys_readonly.py` and `run-purchased-adjustment-factor-keys-readonly.ps1` (no duplicate report pipeline). New version:
- Classifies **every source factor value** before rejecting a row for invalid symbol/date, with total value-health counts required to conserve to all 68,438 rows.
- Separates true null-date rows from non-null invalid/out-of-range date32 rows, counts raw symbols including invalid-date-only symbols, checks number of symbols with one vs multiple null-date rows, with only null dates, and with both dated and null records.
- Maintains all original `valid-symbol, valid-date` key count and per-year statistics and does not interpret null dates as a baseline.
- Uses 9 revised HFQ key/source regression tests plus the original 6 Arrow schema/footer tests; emits aggregate counts only. It still scans ONLY `symbol,d,hfq_factor` from the factor source and never purchases, copies, or modifies eight-cycle OHLCVA, source files or production routes.

**Do not claim the revised code has passed Windows yet**; treat both the vendor factor's true adjustment direction and any undated-anchor semantics as explicitly unverified. If next run shows a per-symbol null-date pattern, record it as source evidence and proceed to the higher-priority October 2026 higher-cycle source-gap/aggregation gate without turning the factor file into a ninth K-line cycle.

## 2026-11-08 Windows verified complete HFQ null-date and factor-value audit

The user ran branch revision `90f2b14` locally on original purchased `复权因子` and obtained `PASS_PURCHASED_FACTOR_SOURCE_KEYS_READONLY` with **6/6 schema and 9/9 key-health tests passing**. Original source read was only `symbol,d,hfq_factor` factor columns; **all 68,438 factor rows** were classified, not just valid-dated records. The source files were unchanged, no K-line OHLCVA was read and production was not activated.

* 68,438 total rows, 5,501 distinct valid-dated symbols and 62,939 distinct valid-dated `symbol,d` keys; no duplicate valid-dated keys, no invalid symbol fields.
* Valid-dated range 1990-12-01..2026-09-30. `NULL_DATE_ROWS=0`, **`OTHER_INVALID_DATE_ROWS=5499`**, so previous guess that these 5,499 rows are null-date factor anchors is disproved. All 5,499 have **non-null `d` values** which fail the existing accepted date/type predicate; their exact calendar labels have NOT been inspected or certified. `RAW_SYMBOLS_INCLUDING_NULL_DATE=5501` (same as valid-dated symbols), `SYMBOLS_WITH_NULL_DATE=0`.
* For all **68,438 source rows** `NONFINITE=0`, `NONPOSITIVE=0`, `NULL_OR_NONNUMERIC=0`. Exactly **10,706 factor values ==1**, 57,732 finite positive non-one. The previous valid-dated-only 1-factor count was **5,207**, so the difference **10,706-5,207=5,499** equals all currently invalid-date rows: **every invalid-date row has factor value 1**. This arithmetic relies on the same unchanged source observed in the two user-run audits.
* Likely sentinel/base records per raw symbol, but ***NO*** confirmation of special date encoding, factor baseline, adjustment direction, trading calendar, stock listing or corporate action mapping. These records are **preserved**, not dropped, normalized into dates, forward-filled or automatically multiplied into OHLCVA. No further factor health scan is needed for the current raw unadjusted eight-cycle query milestone; the exact sentinel dates and vendor policy can be investigated as a separate future optional factor-view acceptance task.

**Mainline moves to October 2026:** original purchased 15/30/60min/day/week/month sources stop at 2026-09-30 and there are known SHA-verified private H5 1/5-minute stockdays through 2026-10-13. Calibrate **real purchased 5min→15/30/60min/day** timestamp + OHLCVA behavior on September 30 before proposing any Oct derived high-cycle candidate. Always use 2026 October private minute SHA-gated inputs and verify purchased higher-cycle absence first. Do not fabricate incomplete sessions or weekly/monthly bars from a single midweek/midmonth day; no high-cycle private files or production updates until calibration and unit gates are satisfactory.

## 2026-11-08 October post-purchased-frontier high-cycle H5 5min candidate calibration (Windows pending)

New bounded code `tools/audit-2026-oct-h5-five-minute-high-cycle-candidates-readonly.py`, 8 synthetic tests and ASCII Windows launcher `run-2026-oct-h5-5min-high-cycle-readonly-calibration.ps1`. This is a **new unverified Windows gate, not a published high-cycle fill**.

The code **does not re-scan entire years**: for each of `SH600000`/`SZ000001`, it reuses the accepted eight-cycle purchased-first API on exactly two previously probed trading dates:
- **2026-09-30 baseline**: verify 48 original purchased 5min bars on the source **start-labeled** 09:30..11:25,13:00..14:55 grid, group by exchange AM and PM sessions into 16×15min, 8×30min, 4×60min and a one-bar full trading day. Compare only aggregate *counts* of timestamp-key, six-field OHLCVA, volume and amount agreement with the **original purchased source** 15/30/60min and day on the same date. This empirically tests a candidate time-label and value rule; mismatches are recorded rather than silently relabeled or fixed. No unapproved adjustment factor is applied.
- **2026-10-13 gap-source**: verify the existing receipt/SHA-gated **private H5-only** 5min bars are exactly 48 complete source-grid records, and check the purchased original high-cycle existence separately. Only when a purchased source high-cycle is absent does the report count *potential* 16/8/4/1 derived buckets. Those buckets stay in process memory and are discarded at end; no actual Parquet is written, no production source pointer changes and no original H5 opens. **Potential is NOT approved to merge**.
- **Week/month excluded**: one 2026-10-13 day cannot establish a full trading week/month, official calendars, vendor time-label policy, corporate actions, source quantity units or complete 2026-10 history. Do not fill those without a separate multiday/month-end gate.
- Safe output prints only two sample tickers and per-cycle agreement/candidate counts, not original proprietary price/volume/amount fields.

The already Windows-verified eight-cycle research query remains the only accepted read-only consumer. This new code has 8 additional synthetic regressions and reuses 10 earlier eight-cycle tests in its Windows launcher; **do not call it Windows-PASS or output H5-derived high-cycle market bars before the user's real run**. If purchased 5min versus source high-cycle calibration does not agree, investigate period time labels or vendor units instead of auto materializing an H5-derived high-cycle overlay.

## 2026-11-08 first Windows Oct high-cycle calibration: synthetic fixture failure, real-source phase NOT entered

The user pulled the initial `3f9d90e` revision and ran `run-2026-oct-h5-5min-high-cycle-readonly-calibration.ps1`. The existing eight-cycle synthetic set **10/10 PASS**, but the new source-calibration synthetic set **7/8 PASS, 1 FAIL** before any real licensed market source opened. Failing test: `test_bad_clock_grid_and_repeated_keys_rejected`. The purported duplicate case `fake5()[:-1] + [dict(fake5()[-1])]` was in fact the original 48 bars unchanged, so the validator correctly did NOT raise an exception. This is a bad test fixture, **not** evidence of a source-data corruption or a successful/failed real September-vs-October calibration.

Commit `be43c7c` repairs **only** the synthetic fixture: replace the final 5min bar with a second copy of the penultimate bar, and independently assert exactly 47 distinct timestamps for 48 rows; retain a separate off-grid case with 48 distinct times. No market parsing, aggregation, routing, production logic, previously verified minute sources, or original source files changed. The synthetic and actual Windows real-data calibration must be rerun on a revision with `be43c7c` as an ancestor. Until the user reports it, the `PASS_2026_OCT_HIGH_CYCLE_5MIN_CANDIDATE_SOURCE_CALIBRATION_READONLY` status is **NOT** accepted.

## 2026-11-08 Windows 2026-10-13 high-cycle candidate gate PASS: isolated SZ000001 daily divergence

User ran revision `5b22451`, verified with Git ancestor gate, on the local originals. The existing eight-cycle synthetic checks **10/10 PASS**, new clock-grid and aggregation tests **8/8 PASS**; then real `PASS_2026_OCT_HIGH_CYCLE_5MIN_CANDIDATE_SOURCE_CALIBRATION_READONLY` with 0 original market writes or production activation.

Original purchased **2026-09-30** per-stockday calibration:

| Stock | 15min full OHLCVA bars / source | 30min | 60min | day |
| --- | --- | --- | --- | --- |
| SH600000 | 16/16 | 8/8 | 4/4 | 1/1 |
| SZ000001 | 16/16 | 8/8 | 4/4 | **0/1** |

Each high-cycle reference had its expected original-source rows and the aggregated purchased 5min **raw timestamp labels match**. Six-field OHLCVA equality uses the existing tolerance; **SZ000001 2026-09-30 original purchased daily is an observed discrepancy**, not an absent stockday or a failed source read. Do not infer its cause until the actual per-field agreement is shown. Do NOT weaken the tolerance, normalize vendor units speculatively, or change the original daily source to make the test pass. All original purchased higher-cycle OHLCVA records still win.

On **2026-10-13**, for both sample stocks, 48 SHA-checked verified H5 5min start-label bars form the complete expected 48-slot day, and the original purchased high-cycle 15/30/60min/day **has zero rows**. Each stock therefore yields **16/8/4/1 potential buckets** in process memory (29 each, 58 across two stocks). No physical high-cycle Parquet has been created; no extrapolation to additional securities or 2026 Oct days, nor production unit, corporate-action, or independent source certification.

To avoid additional modules or new duplicated reports, the EXISTING `run-2026-oct-h5-5min-high-cycle-readonly-calibration.ps1` now prints a supplementary `OCT_HIGH_CYCLE_REFERENCE_FIELD_DIAGNOSTIC` line **only** for a source high-cycle with valid matching raw keys but fewer than expected full six-field matches. That line contains per-field counts for `OPEN/HIGH/LOW/CLOSE/VOLUME/AMOUNT`, **not** proprietary prices/quantities. Source computation, synthesis hypotheses, SHA gates and original market files are unchanged. This print-only change **is newly committed and not yet rerun on Windows**. Once diagnosed, prioritize only fully evidenced intraday cycles; daily derived values remain separate research candidates until the independent price-volume-amount and cross-source unit gates pass. Never manufacture weekly/monthly from these isolated dates.

## 2026-11-08 SZ000001 day amount-only divergence confirmed; four-day intraday gate pending Windows

The user's Windows `51f8118` runner succeeded with the existing 10/10 and new 8/8 synthetic tests plus real 2026-09-30 purchased source calibration and Oct-13 SHA-gated H5 5-minute check. **SZ000001** daily purchased-vs-5m rollup has only a single **AMOUNT** mismatch: `OPEN/HIGH/LOW/CLOSE/VOLUME` each match **1/1**; `AMOUNT=0/1`. SH600000 daily 6/6 matched. For both stocks, purchased 15/30/60min agree with 5m rollup in all six fields: 16/16, 8/8, 4/4 respectively. The amount difference **magnitude** and vendor causes are not known from this count-only output. Original purchased daily source must NOT be overwritten. A few matched stocks and one day do not prove H5 units match purchased schema in all periods.

**No repeated whole-history audits.** The existing calibration module and its PowerShell entry have been extended (new code **pending Windows user run**) with an opt-in `--oct-four-day-intraday-sweep` that checks exactly the previously vetted **2026-10-08, 09, 12, 13** dates for `SH600000` and `SZ000001`. Each stockday loads **only the already-existing SHA/SAFE-gated private H5 5min** through the earlier purchased-first query. It requires 48 actual source-start grid bars. Then it checks existing original purchased **15/30/60min** for that stockday and reports counts of **potential** 16/8/4 buckets **only when the original higher cycle is fully absent**; even a partial purchased high-cycle blocks H5-derived overwrite. The candidate OHLCVA values are retained solely in Python memory, not materialized or exported, and no week/month/day is synthesized by this sweep. Missing/invalid private source or a bad session **fails closed**. The original Sept30/Oct13 day diagnostics remain available, but the daily amount issue is explicitly isolated from the intraday 3-cycle track.

Three new synthetic checks added to the same test file (11 vs previous 8), verifying 4 dates × 2 securities, purchased high-cycle partial blocking and incomplete H5 stockday rejection. The Windows runner now runs **10 old + 11 high-cycle tests**, outputs `OCT_INTRADAY_SOURCE_SYMBOL` lines and a final `OCT_FOUR_DAY_INTRADAY_CANDIDATES` 15/30/60min count line. It still emits the old September reference field count diagnostic. These newly expanded tests and four-day real source checks are **not yet user-Windows accepted**, and cannot establish production unit or trading-calendar certification. The user should only run this bounded existing launcher; do not turn potential candidates into actual Parquet without the independent source-quality gates.

## 2026-11-08 four-day high-cycle synthetic TypeError: date mock contract fixed (pending Windows)

First user Windows run of four-day runner revision `36546a8`:
- existing 8-cycle synthetic tests `Ran 10 ... OK`;
- newly expanded `Ran 11` high-cycle tests with **3 errors, 8 other tests passed**. All three are in *new mocked tests*, with `TypeError: fromisoformat: argument must be str`: `sweep_verified_october_intraday` deliberately passes a Python `datetime.date` directly into internal `_query`; the three test doubles incorrectly call `date.fromisoformat(day)` as though `day` were a string.
- The two mocked special-case checks `day=="2026-10-09"` had the same wrong assumption and would silently mis-test both purchased partial-source priority and incomplete-H5 rejection if left unchanged.
- The launcher **stopped before opening any real H5/private or purchased market sources**. Neither a four-day `PASS` nor 224 real provisional intraday bars may be claimed at this time.

Test-only commit `18ba346` fixes all three mocked source constructors to use `fake5(day,symbol)`, compares the two special 2026-10-09 cases to `date(2026,10,9)`, and explicitly asserts the mock day input is a `datetime.date` instance. No source aggregation, SHA, stockday routing, price amount logic, market writer, or high-cycle business code changed. Run the same Windows launcher after pulling revision with `18ba346` ancestor and report its output. **Real four-day gate is pending user Windows acceptance**.


## 2026-11-08 four-day Windows PASS and next same-H5 1min-to-5min diagnostic (Windows pending)

The user's real Windows execution on revision 12ac4bb passed both 10/10 existing and 11/11 new synthetic tests. It verified exactly four October days (08, 09, 12, 13) and two symbols (SH600000, SZ000001): each of eight H5 5-minute stockdays has all 48 required start-labelled bars. Purchased 15/30/60m sources are absent on these particular stockdays. Accordingly **128 + 64 + 32 = 224** bounded potential H5-derived 15/30/60m bars are identified in process memory, NOT physically written. The Sep30 purchased intraday references match all six fields for both symbols, while SZ000001 purchased daily diverges **only** in AMOUNT. No private H5 units, independent calendar, daily amount behavior, corporate-action policy or production writing is thereby certified.

The next experiment extends the SAME original calibration Python module, the SAME tests and the SAME PowerShell runner. It adds an explicitly opt-in one-minute-to-five-minute crosscheck on the exact same eight stockdays, using purchased-first minute queries and already SHA/SAFE-verified private H5 1/5min candidates. The diagnostic groups H5 native **end-labelled** 1min into native **start-labelled** 5min candidate windows: each 5m start requires the next five minute-end labels. This is a working clock convention, NOT a certified vendor conversion rule.

An H5 1min stockday may contain 239 rather than 240 bars. A missing 1min prevents the affected 5m window from being counted as comparable, rather than inventing data or blocking the independent valid 5m source. Report the number of 1m rows, complete vs incomplete 5m windows, all-six OHLCVA matching complete windows and the six individual field counts, never the original OHLCVA. Values are compared with the existing calibration diagnostic tolerance: relative 1e-8 and absolute 1e-7. Invalid grid/provenance/duplicates/geometry fail closed. If original purchased 1min wins under source priority (possibly 241 rows), it is explicitly **not same-H5-source comparable**; zero/missing one-minute source is also **not comparable**. Neither case counts as a certified H5 1min-to-5min match.

The existing Windows launcher now enables this bounded crosscheck alongside the earlier four-day source sweep and emits eight OCT_H5_ONE_TO_FIVE_DIAGNOSTIC aggregate lines. Six newly added synthetic tests cover 240->48, 239->47, amount-only mismatch, malformed source, purchased priority and explicit opt-in. **New commits and Windows runner have not yet been verified on the user's Windows machine**; the last verified result remains revision 12ac4bb. Even a perfect same-provider 1m/5m match is NOT independent volume-unit certification. Retain candidate-only status: no licensed value export, no new high-cycle Parquet, no production merge or H5 mirror, and no day/week/month construction. Run the same existing launcher after pulling this branch; do not repeat historical whole-database scans.


## 2026-11-08 Windows actual eight H5 1m/5m stockdays: strict volume conserved, AMOUNT mismatch classified next

The user ran revision \`e07d272\` on the actual Windows purchased-first source and SHA-verified private H5 minute receipts. The original 10 tests and the newer 17 tests PASS; the same bounded 2-stock, 4-day Oct-08/09/12/13 intraday candidate gate still prints the verified in-memory **128×15min + 64×30min + 32×60min = 224** potential bars, zero production writes, and no daily/week/month authorization. All eight H5 one-minute stockdays contained **240 native end-labelled 1m bars** and **48 complete five-minute windows** each (1,920 1m / 384 5m). The eight 1m-sum vs H5 5m VOLUME matching counts are 48/48 each, or **384/384** under the existing strict calibration tolerance. Per-stockday AMOUNT matching counts are SH600000: 21,31,25,29; SZ000001: 30,30,25,27. Thus **218/384 match and 166/384 fail the original 1e-8 relative/1e-7 absolute diagnostic tolerance**, notwithstanding 384 complete windows. These findings do NOT prove identical original source amount fields or independent volume units; six-field matching exactly follows amount in these eight reports, but OHLC counts were not separately displayed. The separate Sep30 purchased SZ000001 **daily** amount-only mismatch remains unresolved and must not be confused with the October H5-internal minute amount discrepancy.

**Next bounded read-only cause triage committed after Windows result (NOT YET Windows-accepted):** Modify only the SAME existing October calibration tool, its synthetic test file, runner and this document. Keep strict match criteria, original source routing and 224 candidates exactly unchanged. For each complete H5 1m/5m five-minute window, output count-only **OPEN/HIGH/LOW/CLOSE/VOLUME/AMOUNT** match counts; for AMOUNT values that fail the original tolerance, classify sign (sum-1m greater/less than source-5m), morning/afternoon, one-side-zero, and *mutually exclusive* relative residual bins based on \`abs(sum1m - source5m)/max(abs(sum1m),abs(source5m))\`: <=1e-7; (1e-7,1e-6]; (1e-6,1e-5]; (1e-5,1e-4]; (1e-4,1e-3]; (1e-3,1e-2]; >1e-2. Count only **failed original-tolerance** amount windows, not all 384 windows. The diagnostic must conserve AMOUNT_FAIL = COMPLETE_WINDOWS - AMOUNT_MATCH = SUM_GT + SUM_LT = AM + PM = sum(relative bins). No original or derived OHLCVA, raw difference or identifiable proprietary amounts are exported. Noncomparable purchased-first or missing H5 1m must have zero comparison and zero residual counts. Four new synthetic regressions cover sign/session conservation, tiny residual tier while still failing original strict threshold, zero-counter/missing window separation, and missing/purchased source. Expected new synthetic suite is 21 tests, plus previous 10; this total has **not yet been verified on Windows**. Even if discrepancies fall into small-relative-error buckets, that would only support a supplier rounding/precision hypothesis, not authorize relaxation of the primary comparison threshold or automatic source replacement.

Run the same bounded original PowerShell launcher on this branch after \`git pull --ff-only\` and a commit-ancestor check. Interpret the eight \`OCT_H5_ONE_TO_FIVE_DIAGNOSTIC\` lines. Do not run full history scans or materialize private intraday high-cycle Parquet until a safe batch plan, multi-symbol evidence and vendor unit/corporate action gates are designed. H5-only 5m is still the direct input for *potential* 15/30/60m high-cycle bars; its independent SHA/provenance gate remains effective regardless of the separate H5 internal 1m amount residual.
