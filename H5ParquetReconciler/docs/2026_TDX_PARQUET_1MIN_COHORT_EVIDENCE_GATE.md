# 2026-10-28：TDX/Parquet 09:30+09:31首分钟映射——跨样本只读证据门槛

## 真实单日实证

用户实际上传：
`tdx-vs-pq-sh600000-20260930-first-minute-merge-v2.json`。
SH600000/2026-09-30，源TDX 240根一分钟结束键，
购买Parquet 241根（额外09:30开盘成交记录）：

- 直接比较双方共同240根，open、volume、amount分别239/240
  容差内；high、low、close分别240/240。
- TDX 09:31 vs Parquet **单独09:31**：
  open相对差0.0021692263，volume相对差0.0991382916，
  amount相对差0.0992703168，分别不匹配。
- TDX 09:31 vs Parquet **09:30+09:31两条聚合**：
  六字段全部1/1匹配；开高低收最大相对差不超过
  4.96e-08，volume、amount均0相对差。
- 其余239根分别六字段239/239全部匹配；按首根聚合再拼接
  239根后240根六字段全部匹配，volume、amount相对误差0。
- Parquet独立09:30记录volume和amount均非零，首分钟映射
  不能以“丢弃零量占位”解释。
- Parquet额外09:30条计入第一根五分钟后，48根五分钟所有
  OHLCVA均匹配购买的五分钟原记录。
- 这是一个**特定股票日**的实际证据；不是原厂字段语义认证，
  也不是对所有股票/日期的可直接上线转换规则。

## 新的多样本证据工具

`tools/summarize-tdx-parquet-minute-evidence-readonly.py`

工具完全不接触市场价量额或Parquet/TDX原件；只读取之前由
`audit-tdx-vs-parquet-1min-opening-readonly.py`
产生的**模块reports/**安全JSON。

- `--report`可重复传入最多12个现有报告，必须每个
  `(symbol,date)`不同，格式、source SHA、Parquet source
  stat-only清单指纹和数量必须完整，禁止重复字段或非有限JSON。
- 根据报告已有的字段级统计独立复核三组证据：
  ① TDx第一根09:31 vs Parquet 09:30+09:31；
  ②其余239根逐根对照；③合并首根后的240根对照；
  同时检查Parquet 241分钟按额外09:30贡献还原48根五分钟
  的六字段容差匹配数。不同字段任意不匹配立即标识
  `disagreement_observed_do_not_apply_mapping`。
- 合成型**探索样本目标**（不是认证门槛）：
  不少于6个不同股票日、至少2只股票和至少3个不同交易日期。
  如果全部吻合但达不到探索目标，输出
  `matched_but_exploratory_cohort_too_small`；
  全部吻合且达到探索目标，输出
  `exploratory_sample_target_met_not_certified`，
  **依然不认证生产转换规则或任何正式数据源优先级**。
- 每份来源报告输入不得超过256KiB，须在模块
  `reports/`内、非符号链接，不修改原报告；结果写入该目录
  **全新**JSON，不能覆盖，报告只有符号/日期/布尔结果、
  指纹和指标数量，不含实际OHLCVA或个别分钟K线。
- 原报告来源指纹只包含部分文件大小/修改时间，
  **无法验证Parquet内容真伪**；这仍然属于本机自查证据，
  不能替代独立市场源、复权、停牌与公司行为核验。
- 即便6个样本全部吻合，`production_mapping_certified=false`、
  `eligible_for_automatic_production_union=false`，
  用户尚未批准任何生产写入；不创建/修改隔离暂存。

## Windows真实验收

在仓库根目录`D:\ChatGPT\AStockDataTools`：

```powershell
git pull --ff-only origin main
.\.venv\Scripts\python.exe -m py_compile H5ParquetReconciler\tools\summarize-tdx-parquet-minute-evidence-readonly.py
.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test_summarize_tdx_parquet_minute_evidence_readonly.py" -v
```

**先用已经通过实测的那份报告跑证据汇总**（只应返回
`matched_but_exploratory_cohort_too_small`）：

```powershell
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\summarize-tdx-parquet-minute-evidence-readonly.py --report "reports\tdx-vs-pq-sh600000-20260930-first-minute-merge-v2.json" --read-only --out "reports\tdx-pq-opening-cohort-one-sample.json"
```

下一步可先测试**同一只股票的其他历史交易日**，
本机已知存在相同源文件、原生分钟线覆盖2026-05-11～10-13；
购买Parquet截至2026年9月，建议先试2026-09-29、
2026-09-28。对这些日期**尚未实际验证数据存在和时间网格**，
如果脚本拒绝某天，不要手工补数据，回传具体错误。

```powershell
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\audit-tdx-vs-parquet-1min-opening-readonly.py --parquet-root "D:\stock" --tdx-1min-file "D:\software\TDX\vipdoc\sh\minline\sh600000.lc1" --symbol SH600000 --date 2026-09-29 --read-only --out "reports\tdx-vs-pq-sh600000-20260929-minute.json"
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\audit-tdx-vs-parquet-1min-opening-readonly.py --parquet-root "D:\stock" --tdx-1min-file "D:\software\TDX\vipdoc\sh\minline\sh600000.lc1" --symbol SH600000 --date 2026-09-28 --read-only --out "reports\tdx-vs-pq-sh600000-20260928-minute.json"
```

若新增报告成功，可传给证据汇总工具，
追加2个`--report`参数，`--out`必须改成尚未存在的新
JSON。为避免单独发送已购买数据，请只上传reports/中的
安全JSON，绝不上传原生`.lc1`或购买Parquet原始文件。

不同股票的样本需要先检查对应TDX本机文件是否存在，不能预设
所有股票均拥有同一数据覆盖范围。
完整模块合成回归仍应在本机执行：
```powershell
.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test*.py" -v
```

## 主线推进门槛

单个股票日的映射证明已成立；现在目标是识别这个映射在
交易日、股票类型与非零开盘成交场景中的适用范围及例外。
发现任一样本失败，应先归因（时间网格、停牌、复权、单源
更新延迟、单位差异等），不能自动删除09:30、重采样覆盖
购买数据或宣布原生TDX全市场优先。
