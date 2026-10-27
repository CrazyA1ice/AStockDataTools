# Parquet历史主源候选：跨市场合成验证384/384及日线↔分钟守恒第一阶段（2026-10-27）

## 已收到的两份用户Windows真实报告

- `pq-only-2026-08-24-cross-market.json`：SH600000（沪市主板）、SZ000001（深市主板）、SZ300750（深市创业板），各241根1分钟、48根5分钟；三者的最佳窗口都是`five_start_minute_end_plus_opening_0930`，即**5min起始标签T ↔ 1min结束标签T+1至T+5；开盘首根额外纳入单独09:30一分钟且不重复纳入其余窗口**。逐股严格全六字段**48/48、48/48、48/48**，8月24日合计**144/144**。上午各24/24、下午各24/24，成交量和成交额每组五分钟/一分钟合计的p10、median、p90、max皆为1.0。选中数据无重复键、非有限值、无效时间戳及股票内OHLC/数量网格异常。5min读取48个RowGroup/5,666,976源行；1min读取20组/2,377,661源行。
- `pq-only-2026-09-30-cross-market.json`：SH600000（沪市主板）与SZ000001（深市主板），同规则各**48/48严格六字段一致**，合计**96/96**。每股241根1min和48根5min，上午/下午各24/24，量额比率四个统计量均1.0；无选中源质量异常。5min读取47组/5,685,792源行；1min读取17组/2,034,466源行。
- 连同此前实测`pq-only-2026-09-28-1min-to-5min-opening0930.json`三只科创板样本（各48/48），**2026年8、9月三个交易日，沪市主板、科创板、深市主板、创业板共8组股票-交易日，384/384根Parquet五分钟K线可按已确认特殊开盘时间规则由Parquet一分钟数据严格重建。**

**严格一致**指软件原有`math.isclose(rel_tol=1e-10,abs_tol=1e-6)`针对OHLC、volume、amount六字段同时满足，**不是二进制逐位一致，也不是与交易所原始逐笔数据一致**。购买Parquet与自己H5在相同5min K线上存在供应商差异并不否定各自内部周期间一致。没有证据认证2011年～2026年9月全部日/证券，北交所尚未抽查，2011年后各类历史时段也未抽查。

## 进入下一阶段：Parquet day vs 1min vs 5min，只读

新增`tools/validate-parquet-day-to-minute.py`，只读`AllCycleAStockData/day`、`1min`、`5min`三个购买Parquet周期，复用`validate-parquet-1min-to-5min.py`现有的按交易日和证券别名保守RowGroup剪枝。**不读取H5，不写入源，报告不包含原始付费OHLCVA值**；全部输出/临时文件仍位于模块内部。

1. 逐股票单交易日验证是否有**1条日线、241个严格分钟时间键（09:30额外开盘键+09:31—11:30+13:01—15:00）、48根五分钟起始标签**。缺/多时间标签均做数量记录；只在**时段完整**的证券日计算一分钟/五分钟全日OHLC及量额。停牌、无成交或特殊交易日不强求241根，结果标为`incomplete/not_certified`，**不能隐式插值成完整日**。
2. 日线OHLC与两套分钟（开价首根、高价最大、低价最小、收价末根）独立比对；成交量及额使用`math.fsum`求和。输出`strict_field_agree`、`strict_all_six_raw_agree`、旧容差匹配以及**日线量/分钟量、日线额/分钟额比率**；仅比较标准化量因子候选×1、×100、×0.01，不做任何自动选择、单位转换、修改或覆盖。
3. 保留之前已实证通过的1min→5min`09:30`特殊合成门槛：需实际48/48六字段严格吻合、源无重复非有限/无效时间、完整时间键；`raw_all_three_periods_strict_agree`还要求**日线原始量额不经换算**分别与两周期严格一致且日线OHLC几何合法。遇到日线口径不同或缺失，分别输出量因子候选与失败原因，绝不标记已通过。
4. 修改唯一共用日线读取时间归一化：`read_parquet_period(...,"day",...)`将源时间戳解为**北京日期YYYYMMDD0000**，原1min/5min读数时间标签行为不变。日线数据字段需要在本机真实报告中单独验收，不能事先假设日线字段量纲或复权机制同分钟。
5. 每周期待读取候选RowGroup行数默认**≤30,000,000**，超过先失败，无大范围年度批量扫描；只报告处理量、证券日源键、计数/布尔、假设倍率和比率，不回传许可证数据源OHLCVA。共新增**8项合成回归测试**，含临时生成的无版权Arrow日线文件进行真实`read_parquet_period("day")`测试；新增测试本机尚未执行。

## Windows验证

仓库根目录（在已有本机数据`D:\stock`）：

```powershell
git pull --ff-only origin main
.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test*.py" -v
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\validate-parquet-day-to-minute.py "D:\stock" --date 2026-08-24 --symbols SH600000 SZ000001 SZ300750 --max-candidate-rows 30000000 --read-only --out "reports\pq-day-vs-minute-2026-08-24.json"
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\validate-parquet-day-to-minute.py "D:\stock" --date 2026-09-30 --symbols SH600000 SZ000001 --max-candidate-rows 30000000 --read-only --out "reports\pq-day-vs-minute-2026-09-30.json"
```

**注意：需要额外读取`day`+对应`5min`+`1min`行组，之前扫描过的结果不会自动缓存，因此确实会重新扫描分钟源（8月24日约804万行；9月30日约772万行，另加日线待定）。** 若不希望一次运行两个日期，可只先运行2026-08-24，确认日线的时间与量纲后再运行9/30。若输出文件已存在则换新文件名，脚本拒绝覆盖。

上传安全JSON后再分析日线数值口径、是否需要倍率候选与是否能够直接作为历史主库完整证券日数据依据。**未通过这一阶段前，禁止直接将日线/分钟不同来源或不同量纲拼接进Parquet历史主库。**

完成跨时段/市场与日线守恒抽样后，开发独立标准化目标数据库：历史首选购买Parquet，H5只补真正缺失或做核查；后续通达信盘后新增**完整证券日**，按day、1min、5min独立确定数据的实际最后完整交易日，保存source ID、源文件指纹、复权模式、量纲声明及可回滚版本。未经认证不自动并集，不覆盖原购买Parquet文件。
