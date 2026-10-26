# 2026 H5五分钟成交量×100：实测成立，下一步跨周期守恒验证

记录日期：2026-10-26。依据本机用户上传 `h5-parquet-5min-2026-09-24-30-volume-x100-candidate.json` 和Markdown文件。来源包含真实候选A股的聚合统计，不包含任何原始H5/Parquet OHLCV。

## 1. 最新实测（对原严格成交量容差重算）

2026-09-24、28、29、30四天两源5min同键重叠为**1,065,216**根，H5独有0、Parquet独有4,080。对相同的全部重叠键、相同的价格/金额映射和完全相同的成交量容差，比对下列两种候选：

| 验证指标 | 旧规则：H5分钟transCount不乘100 | 新并行候选：H5分钟transCount乘100 |
|---|---:|---:|
| 五分钟成交量不同 | 1,060,937 | **3,097** |
| 任意量价不同 | 1,060,937 | **3,440** |
| 任意量价冲突率 | 99.598% | **0.323%** |
| 六项量价均在现有容差内 | 4,279 | **1,061,776** |

原先1,060,937根volume差中，`legacy_mismatch_resolved_by_candidate=1,057,840`，**99.708%**的旧成交量冲突被候选消除；`legacy_match_broken_by_candidate=0`，没有引入“旧成交量一致、新口径却不一致”的记录。成交量残余3,097根在4个有记录日分别为744、910、832、611；候选代码前缀组BJ 806、SH688/689 549、SH其它1,742，SZ300/301及SZ其它均0。候选完整量价残余3,440，仍含价格、金额和成交量异常的重叠交集。**不得将剩余3,440当成全部是成交量异常，成交量仅有3,097。**

已证实：现有程序的五分钟H5成交量原始值和Parquet对应值多数相差100倍，该候选乘100在**同键比较**中具有高度可重复效果。尚未证实：这个因子是交易所官方量纲、两源字段规范明确如此、适用于全部历史年代/所有证券种类或可以直接启用自动并集。旧统计和输入值在代码中始终未改。

## 2. 新增快速跨周期验证

`tools/inspect-h5-day-vs-5min-volume.py` 仅在指定日期窗口，分别只读`HikyuuData/{sh,sz,bj}_day.h5`和`*_5min.h5`：

- 遵循原有`a-share-candidate`代码前缀过滤；H5仅读取`datetime`及`transCount`字段的有界日期切片，不读取OHLC或成交额列，不读任何购买Parquet文件。
- 只选择两个H5周期该证券该日同时有数据，且**日线恰好一条午夜键、五分钟线恰有48个不重复且符合候选常规时段结束时标**的证券—日期；其它分别统计`day_bar_not_single_midnight`、`five_minute_session_not_48_exact`、`stock_days_only_day`、`stock_days_only_minute`，不误算作候选映射通过。
- 对完整证券日按完全一样的0.1%容差计算：日线候选`day.transCount*100` 与五分钟`sum(minute.transCount)`（旧分钟单位），再与`sum(minute.transCount*100)`（候选分钟单位）比较；另外统计日线raw transCount是否与五分钟raw总和完全相等，作为独立的**H5内两个周期自洽性线索**。
- 输出按交易日、窗口总计的覆盖数、完整48根证券日数、旧/新映射通过数、严格原始和相等数，以及周期缺口和异常时标数。**不会输出证券级OHLCV、量额总值或具体原始成交量**。
- 使用原有模块`reports/`输出护栏：必须`--read-only`、新JSON文件名不可覆盖，所有`D:\stock`原始数据只读；不修改原有SQLite和H5/Parquet本体。

**这不是跨供应商独立验证。** 同一个H5供应商的day和5min周期可能有共同系统性偏差，其一致性不代表Parquet真实交易量绝对正确。且48个常规标签仍是候选时段规则，非交易所日历与异常停牌时段的认证。

## 3. 下一次Windows本机低成本验证

先更新GitHub main并执行全部模块测试；本轮新增加6项完全合成H5测试，真实Windows测试通过需以本机运行记录确认：

```powershell
git pull --ff-only origin main
.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test*.py" -v

.\.venv\Scripts\python.exe H5ParquetReconciler\tools\inspect-h5-day-vs-5min-volume.py "D:\stock" --year 2026 --from-date 2026-09-24 --to-date 2026-09-30 --read-only --out "reports\h5-day-vs-5min-volume-2026-09-24-30.json"
```

上传新`h5-day-vs-5min-volume-2026-09-24-30.json`。将`totals.complete_48_bar_stock_days_compared`、`totals.baseline_day_minute_volume_agree_0_1pct`、`totals.candidate_day_minute_volume_agree_0_1pct`、`totals.h5_raw_daily_equals_sum_minute_raw_exact`与排除组数量结合分析，不能只报通过比例。

如果H5内部跨周期支持100倍映射，后续有针对性地读取购买Parquet日线同证券同日与五分钟成交量汇总，在各源内部建立日级守恒，再结合提供方文档核定量纲与处理3,440根跨源残余冲突。未经充分审核，`safe_to_automatically_union=false`不变，也不会自动选择一个源覆盖另一个。
