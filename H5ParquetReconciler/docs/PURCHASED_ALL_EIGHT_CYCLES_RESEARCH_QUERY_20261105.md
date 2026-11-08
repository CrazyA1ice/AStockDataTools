# 2026-11-05 购买Parquet八周期原位查询与2025来源边界

## 已在用户 Windows 真实环境验证的证据

- 全周期2025/2026页脚清单：9项合成测试 OK（其中Windows符号链接测试1项 SKIP），真实源脚本 PASS，80个带2025/2026年份标签的Parquet文件。
- 实际目录：`15min,1min,30min,5min,60min,day,month,week,复权因子`。**复权因子非K线周期**，不可当OHLCVA输入；其2025/2026文件名匹配结果为0，不代表目录无其他有效数据。
- 2025 1min=321744640,5min=64081920,15min=21360640,30min=10680320,60min=5340160（页脚行数）。分别按241/48/16/8/4除，均为1335040个**理论标准股票日当量**，不证明逐股票每个交易日完整。
- 2025所有五个分钟周期页脚最早2025-01-02、最晚2025-12-31，日/周/月也有2025年购买源。
- 2026所有八周期实际最晚页脚日期2026-09-30；10月8/9/12/13有已SHA验收、与精确差集数量匹配的私有H5-only分钟补缺分区。
- 1/5分钟双股票本机验证19/19合成 PASS、`SH600000`+`SZ000001` 1min总2402/5min总480，购买源优先，已验证私有H5补缺只在购买股票日缺失时使用。没有市场写入或生产指针激活。

## 本开发分支新增的八周期研究查询（首次Windows测试尚未完成）

- 扩展原有`query-parquet-primary-readonly.py`白名单为`day,1min,5min,15min,30min,60min,week,month`；新增周期仅使用**原始Parquet时间戳**，不自动转换为区间起止、交易所自然周/月或复权后行情。
- 新增`tools/query-purchased-primary-all-eight-cycles-readonly.py`统一单证券/周期/日期查询：1/5分钟复用已验收的原有分钟购买优先+显式私有H5补缺接口，其余六周期复用原购买Parquet只读查询器，无H5替代或重采样。
- 新增`tests/test_query_purchased_primary_all_eight_cycles_readonly.py`（10项新增合成测试）和`run-purchased-primary-all-eight-cycles-smoke.ps1`，后者重跑旧购买查询、分钟19项及新合成测试，再读取真实2025/2026九月六个购买源周期与2026年9/10月1/5分钟补缺。
- **新测试尚待用户Windows实机PASS，不可提前标记已验收。** 部分月/周原始时间标签和2026完整交易日仍未证实；`复权因子`还需单独调查文件结构和企业行为语义。
- 所有新查询仅将授权OHLCVA留在用户本机Python内存；CLI只有计数和来源字段，无原始行情价格输出，不写盘/激活生产，也不做金额/成交量的供应商单位认证。

## 下一步

1. Windows运行八周期单命令验收；如有原始源RowGroup预算、交易周期标签或测试错误，先做小范围修复，不扩大行情扫描范围。
2. 按月复用或建立2025分钟键索引，验证逐股票完整性，不能用文件页脚当作缺口自动填充授权。
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
