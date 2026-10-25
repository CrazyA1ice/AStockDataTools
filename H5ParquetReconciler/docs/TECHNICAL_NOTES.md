# 数据格式、算法约定与当前风险

## 1. 输入数据规格（用户本机已有文件的实际观察）

| 来源 | 存放位置 | 布局 | 已观察到的字段 |
|---|---|---|---|
| Hikyuu H5 | `D:\stock\HikyuuData` | sh/sz/bj × day/5min/1min，组 `/data/SH600000` 等 | datetime(u64), openPrice/highPrice/lowPrice/closePrice(u32), transCount/transAmount(u64) |
| 购买的 Parquet | `D:\stock\AllCycleAStockData` | day/5min/1min等8个周期文件夹，按年文件 | ts(int64),symbol(str),open/high/low/close(float64),volume/amount(float64),source(str) |
| Parquet 复权因子 | `D:\stock\AllCycleAStockData\复权因子` | all.parquet | 尚需单独认证复权字段与生效日 |

这些是本机已观察到的格式，不是所有其他数据商Parquet或所有Hikyuu导出文件的普适规范。当前代码对其他Schema会拒绝或标识异常。

## 2. 时标与市场代码归一化

- H5 `datetime` 当前当作 `YYYYMMDDHHMM` 十进制整数；日线一般为 `YYYYMMDD0000`。
- Parquet `ts` 当前当作Unix**毫秒**UTC时戳，并转东八区；不能在尚未检查的另一家供应商字段上直接套用。
- 5分钟Parquet时标按**起始**标注，候选规则：`ts + 5分钟` → H5**结束**时标。
- 1分钟09:30在Parquet可能单独保存（此前9个股票日样本全部有额外09:30），现只归为特殊候选 `pq_0930_extra_candidate_rows`，不算作正式缺失，也不自动合并到09:31。
- H5 11:30曾在2026-07-16某些股票出现13:00疑似归属错误；本版本只在剩余记录里做疑似标记，不直接纠正日期键。
- 支持XSHG/SHSE/SSE、XSHE/SZSE、XBSE/BJSE/BSE等交易所标签；旧代码市场历史（如2021年精选层/北交所代码回溯）另需版本化码表。

## 3. 比对键、阈值和归一化假设

比对键：`(market+6位股票代码, 标准化到周期结束的时标)`，外层按周期及年份隔离。

归一化候选：
- H5价格：原整数 ÷ 1000。
- H5成交额：原 `transAmount` × 1000。
- H5成交量：day × 100；分钟原值直接比较。
- Parquet价格/成交量/成交额：按原浮点数比较。
- OHLC不同判定：任一价差 > 0.005元（从价格精度推测，需按品种确认）。
- 成交量不同判定：绝对差 > `max(1, 0.00001 × 两源绝对值最大者)`。
- 成交额不同判定：绝对差 > `max(1000, 0.001 × 两源绝对值最大者)`。

以上是**用于定位差异的经验性阈值及比例**，不是已认证的单位、交易所标准或最终合并规则。09:31价格和量额疑似口径差单列，不由“多数相同”来证明其绝对正确。

## 4. 数据处理与状态语义

流程：遍历一个周期的年度Parquet文件 → H5对应年份每证券通过二分查找时间范围并分批读入SQLite的`h`表 → Arrow按批读取Parquet → 分批在SQLite `p`临时表执行键连接 → 记录“匹配值不同/Parquet独有/09:30候选” → 统计H5未见键 → 写该年JSON checkpoint。

主要字段：

| 字段 | 含义 |
|---|---|
| `h5_rows` | 实际读取/去重后的H5该年键数 |
| `pq_rows` | Parquet遍历行数，或在H5无行时的footer候选行数（**留意状态字段**） |
| `matched_keys` | 读到的Parquet行与H5键成功相遇的次数（跨Parquet批次重复未穷尽检查） |
| `h5_only_rows` | H5中没有被Parquet匹配到的键数；异常/不完整扫描下不代表真实源缺失 |
| `pq_only_rows` | 读到的Parquet中未找到H5键的行数；当前另将09:30候选单列 |
| `value_mismatch_rows` | 非09:31候选的OHLC/量额不同记录数 |
| `opening_candidate_mismatch_rows` | 09:31开盘口径待确认的不同记录数 |
| `pq_0930_extra_candidate_rows` | Parquet单列09:30行，不等于证实H5损坏 |
| `pq_year_metadata_only_no_h5_rows` | H5该年/周期全无时，只读Parquet文件footer；不能证明逐行证券/时间差集 |
| `scan_complete` | 本程序本分区未记录严重解析错误；不等于全部键已去重、真实单位认证或记录已证明无缺失 |
| `duplicate_keys_across_batches_not_exhaustively_checked` | 当前版本仍有跨批重复键检测限制，生产并集前必须修复 |
| `issues` | 缺文件、读取、Schema、重复键或未知证券代码等导致结论不完整的原因 |

## 5. 性能和安全边界

- 每年每周期分别运行，SQLite临时库按区间自动清理；内存负载取决于Arrow batch-size及SQLite page cache。
- 由于对全年H5进行SQLite索引，临时磁盘容量仍可能较大；尤其是1分钟数据较密时。
- Parquet数据必须是可读本地文件；本仓库不包含也不下载用户付费数据。
- H5若有多市场缺文件、Parquet分区缺文件、Schema列不全，检查报告必须标记issues；不能把不可比较直接判为数据缺失。
- Resume只跳过 `scan_complete` 的分区，当前检查只确认年份/周期相同，没有自动验证文件指纹、batch-size、阈值及历史源变更。因此数据源变化后要用**新报告路径**重新运行。
- SQLite临时数据库设置 `synchronous=OFF` 只用于可丢弃临时库，不能沿用在正式并集数据库上。
- 报告不导出具体OHLCV数值；只包含统计、不同字段名称、证券、时间戳和临时报错文件名。付费数据访问授权仍需遵守使用约定。

## 6. 验收前明确要修的逻辑风险

1. 全市场Parquet整年1min非常大，目前跨批Parquet重复键尚未穷尽检查；报告不能将匹配行次数视为已经确认的唯一键数。
2. 没有H5的早期年份采用footer快捷统计，不提供逐个Parquet独有键。后续若要实作并集，必须为这些年份建立真正的Parquet键索引或直接经认证复制整个年份。
3. H5日线和分钟线可能覆盖范围完全不同，绝对不能以日线覆盖推断分钟覆盖。
4. H5/Parquet同一证券同一天可能存在停牌、集合竞价、不同分钟聚合规则；不能机械要求所有交易日恰好240根/48根。
5. 缺独立权威交易日历、历史代码表、复权类别，故无法评估“双方都漏掉”的记录。

## 7. 与既有工程的关系

旧研究工程 GLSSTKGM 已验证的部分异常仅作为迁移背景，新的AStockDataTools才是后续所有核验及并集工具的主要维护位置。数据质量核查不应该混入行情仿真主程序或直接修改模拟器实验数据。
