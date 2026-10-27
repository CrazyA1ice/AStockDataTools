# 2026-10-27 Parquet主数据源准备阶段：两次三周期验证的证据登记（不扫描行情）

## 已有真实结果（用户Windows本机生成的安全JSON）

| 日期 | 股票 | 1min数量 | 5min数量 | 1min→5min六字段严格 | day OHLC | day 成交量 | day 成交额 | day vs 两种分钟全部旧容差 |
|---|---|---:|---:|---|---|---|---|---|
| 2026-08-24 | SH600000 | 241 | 48 | 48/48 | 严格一致 | 严格一致 | 原始严格微差，报告比值0.999999975（0.025 ppm） | **通过** |
| 2026-08-24 | SZ000001 | 241 | 48 | 48/48 | 严格一致 | 严格一致 | 比值0.999999967（0.033 ppm） | **通过** |
| 2026-08-24 | SZ300750 | 241 | 48 | 48/48 | 严格一致 | 比值0.999992843（7.157 ppm） | 比值0.999999982（0.018 ppm） | **通过** |
| 2026-09-30 | SH600000 | 241 | 48 | 48/48 | 严格一致 | 严格一致 | 比值0.999999995（0.005 ppm） | **通过** |
| 2026-09-30 | SZ000001 | 241 | 48 | 48/48 | 严格一致 | 严格一致 | 比值1.000000049（0.049 ppm） | **通过** |

证据文件：
- 用户此前的`pq-day-vs-minute-2026-08-24.json`与本轮上传`pq-day-vs-minute-2026-08-24-offline-assessment.json`；后者按**既有10ppm研究复核阈值**将三股正确归类为`strict_OHLC_and_minute_aggregation_small_daily_quantity_gap_review`，并保留三股原始六字段严格全部为False，不暗改为通过。
- 本轮上传`pq-day-vs-minute-2026-09-30.json`：日线找到2条，5min找到96条，1min找到482条；源day扫描28,191行、5min 5,685,792行、1min 2,034,466行。所选源`duplicate_keys`、`nonfinite_source_rows`、`invalid_timestamp_rows`全部为0，两个股票均日线/两套分钟OHLC严格一致、日量严格一致，仅日额微差且落在既有容差内。
- 累计**两日5组股票-日期**Parquet三周期检查；早前还有9月28日三只科创板样本只检查1min→5min。合计**8组股票-日期384/384五分钟严格可由同源一分钟重建**。

三个比较层次必须严格区分：`raw_all_three_periods_strict_agree=false`仍正确；`existing_tolerance_all_six_raw_agree=true`是真的，严格OHLC全部一样；量额相对偏差ppm根据源JSON保留的9位小数比值计算，**不是原始精度下的精确绝对差额**。**10 ppm是开发阶段研究分组门槛，不是交易所统一质量认证标准**。

## 本轮新增：不触碰行情的Parquet样本级证据台账

`tools/plan-parquet-primary-evidence-ledger.py`接受一个或多个此前生成的**三周期原始汇总JSON**或**离线复核汇总JSON**：
- 对原始三周期报告复用`audit-parquet-day-minute-report-offline.py`已有一致性/安全标志/来源异常检查；
- 对已生成离线报告验证来源标记、报告统计、证券清单与股票级审查等级；同一`交易日×证券`不能重复汇总；
- 将已验样本标成`candidate_parquet_primary_in_this_sample_only`，或`not_a_qualified_sample_investigate`；**所有项都强制`eligible_for_unattended_import=false`**。标志通过的仅代表该日该股票有内部支持，绝不推断未抽检的2011～2026.09全部历史也已通过。
- 候选来源明确`purchased_parquet`；只将`H5`标记为后续**确认缺口时**的候选补充，`tdx_postclose`标记为未来完整交易日盘后更新候选。并不意味着已连接通达信、已找到所有历史缺口或已完成任何文件互转。
- 输出只有股票、日期、证据等级、最大量额ppm、原JSON文件名及未来来源策略标志；不含购买OHLCVA，不读任何H5/Parquet原始行情，不写入主库、不覆盖文件。**这是设计迁移前的证据索引，绝不是可以立即自动交易/自动并集的完整主数据仓库。**

### Windows运行（零行情扫描）

```powershell
git pull --ff-only origin main
.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test*.py" -v

.\.venv\Scripts\python.exe H5ParquetReconciler\tools\plan-parquet-primary-evidence-ledger.py --reports "H5ParquetReconciler\reports\pq-day-vs-minute-2026-08-24-offline-assessment.json" "H5ParquetReconciler\reports\pq-day-vs-minute-2026-09-30.json" --review-ppm 10 --out "H5ParquetReconciler\reports\parquet-primary-sampled-evidence-2026-08-24-09-30.json"
```

预计输出：`sampled_stock_day_count=5`、`sampled_date_count=2`、`candidate_parquet_primary_in_this_sample_only=5`。这些预计值是从用户已上传的两份报告得到，**不是声称完成新的本机运行**。两份输入安全JSON都应已存在于模块`reports/`下；若文件名或位置与示例不一致，以用户实际保存位置为准，输出拒绝覆盖已有文件。新增9项合成测试，完整unitest预计**240项**（此前预计231项，未收到完整Windows测试通过日志）。

## 下一阶段：主数据源实践验收

建议停止对2026年两个已检交易日做无意义重复扫描。历史Parquet在用户使用场景作为首选方向已经得到样本支持。下一阶段的高价值开发任务是：

1. 读取Parquet全盘**元数据**和按周期/市场的真实覆盖，不复制数据（分辨2011早期哪几年的1min/5min有文件及哪些股票无数据，不能仅凭目录有文件就认定每一日完整）；
2. 建立独立**只读Parquet主查询接口**，统一价格/量额单位元信息、交易时段标签（包括09:30）和证券代码，保留source ID与文件指纹；优先不转换全部付费数据为另一个巨型副本；
3. 通达信盘后输入在落地前按证券×完整交易日与旧Parquet尾端比对，先跑dry-run，从`2026-10`之后按真实可用周期增量接入，写入**独立、可回滚的新增数据层**，不修改购买Parquet/H5原始包；
4. 缺失分钟按真实市场交易/停牌情况标记而非硬填充241根，跨历史年份与北交所样本小规模验收后才逐步扩大。

本轮工具本身从已有汇总报告登记已验收“证券日”，**不提供上述生产级查询和导入能力**。
