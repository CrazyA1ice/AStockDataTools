# 2025-09-30 五分钟K线边界：独立一分钟周期文件交叉验证

更新：2026-10-25。开发位置：`AStockDataTools/H5ParquetReconciler`。

## 已确认的证据及解释界限

用户上传的 `5min-2025-09-30-attribution-v2.json` 对5只股票做了一个交易日的五分钟对账，其中SH600000、SZ000636、SH603181、SZ300747分别有48条H5及Parquet相同时间窗口数据，BJ920680只有Parquet有48条。当Parquet原始5min开始时标+5分钟后，192条K线全部与H5时间键匹配。

价格差异：Open 80条、Close 86条、High 8条、Low 8条。量额Parquet/H5逐K线比值的各股中位数都非常接近1，但有真实波动；不是一个统一的×100、×1000问题。

V2诊断还观察到：
- Open不一致的80条中，所检查的H5当前open与上一根Parquet close全部相等；
- Close不一致的86条中，所检查的Parquet当前close与下一根H5 open全部相等。

**不能凭此给某一个数据源“判错”**。这可能是K线边界交易的价格归属、采样时点/补值口径或成交聚合方式不同；也可能两份行情共享上游源。需要验证另一周期是否能重组出其中一种五分钟记录。H5一分钟与H5五分钟虽然存放不同文件，也不意味着它们一定来自独立原始成交源。

## 第三轮：用H5独立1min文件重组两种5min来源

新程序：`tools/validate-5min-against-h5-1min.py`。

输入本机只读：`D:\stock\HikyuuData\{sh,sz,bj}_5min.h5`、`{sh,sz,bj}_1min.h5`、`D:\stock\AllCycleAStockData\5min\2025.parquet`。

它对所选股票及指定交易日执行以下检查：

1. 从不同H5周期文件提取当天的一分钟、五分钟记录。根据Parquet原始时标+5分钟确定工作五分钟结束时刻，但不认为是已经认证的时间规则。
2. 分别按`minute_end_label`（5min末4/3/2/1/0分钟）、`minute_start_label`（5min末5/4/3/2/1分钟）两种假设，尝试拼出严格5根一分钟K线的五分钟OHLC、成交量和成交额。
3. 只有五根均存在时，才分别与H5 5min、Parquet 5min比较六个字段，输出“有完整1分钟窗口数、OHLC四价全相同数、逐字段相同数、量额匹配数、量额归一化比值分位数”。完整窗口为零时给出`not_verifiable_no_complete_one_minute_windows`，不下结论。
4. 另记录H5与Parquet同键五分钟K线全天成交量、成交额合计的比值（仅统计双方都有的键），检查差异是否主要发生在分钟边界附近、日内总量是否接近。
5. 如果指定证券缺一分钟H5文件、缺dataset、缺指定日期记录，明确标记`missing_file/missing_dataset/no_records_on_date`和`not_verifiable_no_one_minute_data`，绝不把缺失当作不一致；H5一分钟有重复键时不做聚合认证。
6. 只输出聚合计数、比值、窗口结束时间样例（**不输出购买的原始OHLCV**）。生成报告严格在模块`reports/`下，源数据`D:\stock`全程只读，禁止覆盖旧报告。

## Windows运行方式

在`D:\ChatGPT\AStockDataTools`仓库根目录执行：

```powershell
git pull --ff-only origin main
.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test*.py" -v
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\validate-5min-against-h5-1min.py "D:\stock" --date 2025-09-30 --symbols SH600000 SZ000636 SH603181 SZ300747 BJ920680 --read-only --out "reports\5min-1min-independent-2025-09-30.json"
```

输出：
`AStockDataTools\H5ParquetReconciler\reports\5min-1min-independent-2025-09-30.json`。

诊断程序读取2025年Parquet全部522行组并使用Arrow对选定证券过滤，既有单日5股测试约15秒，但再次执行耗时取决于本机缓存、磁盘和文件状态；不要以15秒为保证。

## 进入下一阶段前的判读规则

- 如果H5 1min重聚合与H5 5min对齐、却与Parquet 5min开收/量额不同，说明H5的两个周期较自洽，但仍不能认定Parquet错误。
- 如果H5 1min重聚合更接近Parquet 5min，则需要检查H5 5min的K线边界规则与其数据来源。
- 如果二者都无法重组，则优先核对一分钟H5本身的数据完整性、时间标签、分钟复权/成交额单位与集合竞价、午间边界情况。
- 如果H5 1min缺少那一天，直接记录来源覆盖缺口，下一步再考虑可选、只读的Parquet 1min独立交叉验证，不能根据缺失强行推断哪边正确。

未完成的任务仍包括唯一键去重、交易日及历史代码表、Parquet年度数据的高性能分区索引和正式两格式并集。禁止自动合并或覆盖原始文件。
