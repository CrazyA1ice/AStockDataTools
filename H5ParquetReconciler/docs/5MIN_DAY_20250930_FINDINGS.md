# 2025-09-30 五分钟试跑：覆盖完整、数值口径不统一的证据

数据来源：用户在本机成功运行2025年9月30日的5min有界核对，上传 `h5-parquet-5min-2025-09-30-pilot.json`。源行情仍位于`D:\stock`且保持只读；本文仅保存统计结果，不保存原始量价。

## 覆盖统计（代码前缀筛选的A股候选集）

|项目|统计|
|---|---:|
|H5五分钟K线|259,872|
|Parquet五分钟K线|260,832|
|按当前“Parquet开始+5分钟”规则的匹配键|259,872|
|H5独有|0|
|Parquet独有|960|
|匹配键中任何价格/量额冲突|151,099（58.14%）|
|OHLC某项差异|72,678（27.97%）|
|成交量或成交额差异|148,742（57.24%）|
|记录标签范围|2025-09-30 09:35至15:00|
|错误与数据源写入|issues=[]、source_modified=false|

价格和量额冲突是可重叠分类，不能把两列直接相加。上述数字是**采用未认证的金额、成交量和时间归一化候选规则得到的结果**，不是两源物理数据均准确或某一源有误的证明。

部分Parquet独有代码当天正好有48根完整五分钟K线，例如`BJ920680、SH600200、SH601133、SH603056、SH603388、SH605255`等；这些证券不应直接被当成H5“下载丢失”，还要核实代码/板块、停复牌、历史证券主数据。

## 性能数据

|阶段|实际耗时|
|---|---:|
|H5三个交易所、约11,000个symbol dataset依次扫描|约163.3秒|
|Parquet 2025年度文件|约131.3秒|
|合计|约294.6秒（4分55秒）|
|Parquet row group|522个全部读取；跳过0|
|Parquet处理源行|64,081,920行|
|落在当日候选股票的行|260,832行|

这意味着只是限制日期范围并没有使Parquet I/O按天减少——年度文件每个row group的时间范围仍与请求日重叠，可能按股票/分块存储。后续若要多日期核对，应考虑一次性建设可复用的日期索引或按日期/证券分区副本，不能逐天重复扫6,408万条。短窗只用于纠正口径与测试正确性。

## 已明确的下一步：最小证券样本对齐诊断

新增 `tools/diagnose-5min-alignment.py`，只针对所选少量证券，检查Parquet原始开始时刻偏移-5、0、+5、+10分钟时的OHLC一致次数，并计算H5成交量/成交额在×0.001、×0.01、×1、×100、×1000候选乘数下的匹配次数。

工具只输出汇总：每个偏移的匹配条数、四价均匹配条数、字段差异条数及单位候选的匹配数，不将OHLCV原始数值发到GitHub；如Parquet的`symbol`行组保存了可信的min/max统计，先剔除与所选证券完全不相交的行组，以减少源数据扫描。

在`D:\ChatGPT\AStockDataTools`仓库根目录运行：

```powershell
git pull --ff-only origin main
.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test*.py" -v

.\.venv\Scripts\python.exe H5ParquetReconciler\tools\diagnose-5min-alignment.py "D:\stock" --date 2025-09-30 --symbols SH600000 SZ000636 SH603181 SZ300747 BJ920680 --read-only --out "reports\5min-2025-09-30-alignment-diagnostics.json"
```

本次重点查看报告中 `lag_minutes_parquet_start_to_h5_end` 对应的每个候选偏移是否提高四价一致率；`volume_agreement_by_h5_multiplier`、`amount_agreement_by_h5_multiplier` 是否有一组统一因子显著优于其他。判断前需同时核实样本证券是否属于相同市场板块/复权口径和开收盘时标。

若诊断仍有大量价格冲突，不能放宽容差掩盖错误，也不能把某一源直接写回另一源。真正并集任务必须按冲突证券/时刻隔离。

生成的JSON严格写到`AStockDataTools\H5ParquetReconciler\reports`，不向原始D盘源数据写入文件。
