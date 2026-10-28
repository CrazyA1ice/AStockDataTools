# 2026-10-28：两组跨源一分钟最高价孤立反例——跨周期只读复核方案

## 证据：用户实际上传的两份安全JSON

- `tdx-pq-sh600000-20260716-boundary-detail-v1.json`：SH600000，2026-07-16。
- `tdx-pq-sh600519-20260630-boundary-detail-v1.json`：SH600519，2026-06-30。

| 字段及门槛 | SH600000 2026-07-16 | SH600519 2026-06-30 |
| --- | --- | --- |
| 09:30+09:31合并首根（全部六字段） | 1/1通过 | 1/1通过 |
| 后239根Open/Low/Close | 各239/239 | 各239/239 |
| 后239根**High** | **238/239** | **238/239** |
| 后239根Volume/Amount | 各239/239，最大相对差0 | 各239/239，最大相对差0 |
| 全240根High | **239/240** | **239/240** |
| High最大相对差 | 0.0011299866（约0.11299866%） | 0.0000169735（约0.00169735%） |
| 候选240根→购买Parquet原生5min | 六字段48/48 | 六字段48/48 |
| verdict | diagnostic_candidate_mismatch_do_not_materialize | 同左 |

两份安全报告的241原始分钟、240候选、48个购买5分钟时间网格
均完整合法，来源校验通过；失败只发生在跨供应商比较时的
**某一条常规一分钟High**，不能据此判断具体一分钟时间
或哪一家数据源为真值。两份High误差数量级不同，尤其不能将
明显的SH600000高价相对差笼统解释为浮点舍入。

## 下一步：优先复用既有日/五分钟跨源审计工具

已有工具 `tools/audit-tdx-vs-parquet-day5min-readonly.py`：
对同一股票日检查TDX原生day、5min、1min三周期内部
OHLCVA一致性，再比对购买Parquet原生day与5min，
对Parquet 5min START和TDX 5min END标签明确加5分钟对齐。
输出只有按字段聚合的匹配数量及相对误差，不输出原始数据或
个别高价的具体分钟位置。这个过程完全独立于此前
仅与Parquet自己的48根5min对比的候选预演。

**必须区分**：购买Parquet的五分钟线与自己的分钟线48/48
全部相等，只证明购买来源内部一致；**不代表TDX原生5min
与Parquet5min也一致**。加入TDX原生5min和day作第三方
粒度核验后才能决定差异是否在五分钟或日线层面仍存在。

从仓库根目录 `D:\ChatGPT\AStockDataTools` 执行单行PowerShell：

浦发银行 2026-07-16：

```powershell
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\audit-tdx-vs-parquet-day5min-readonly.py --parquet-root "D:\stock" --tdx-day-file "D:\software\TDX\vipdoc\sh\lday\sh600000.day" --tdx-5min-file "D:\software\TDX\vipdoc\sh\fzline\sh600000.lc5" --tdx-1min-file "D:\software\TDX\vipdoc\sh\minline\sh600000.lc1" --symbol SH600000 --date 2026-07-16 --read-only --out "reports\tdx-pq-sh600000-20260716-high-crosscycle-v1.json"
```

贵州茅台 2026-06-30：

```powershell
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\audit-tdx-vs-parquet-day5min-readonly.py --parquet-root "D:\stock" --tdx-day-file "D:\software\TDX\vipdoc\sh\lday\sh600519.day" --tdx-5min-file "D:\software\TDX\vipdoc\sh\fzline\sh600519.lc5" --tdx-1min-file "D:\software\TDX\vipdoc\sh\minline\sh600519.lc1" --symbol SH600519 --date 2026-06-30 --read-only --out "reports\tdx-pq-sh600519-20260630-high-crosscycle-v1.json"
```

如上述TDX `.day` 或 `.lc5` 文件不在约定路径、缺少当日
记录或时间网格不合法，应保留完整原始错误并停止该次核验，
**不要创建文件、补齐行情、改动来源、更换时间标签以凑齐通过**。
安全报告仅保存在模块内新文件 `H5ParquetReconciler/reports/`，
程序对重名目标拒绝覆盖。

## 收到两份跨周期审计后如何判读

1. 首看 `tdx_internal_three_period_all_fields_within_tolerance`，
   以及 `comparisons.tdx_5min_vs_parquet_5min_by_interval.high`。
   如果TDX内部聚合已不一致，说明TDX原生周期数据之间亦有差异，
   需要先调查TDX本身的分辨率归并与历史修订。
2. 若TDX内部三个周期都自洽、两来源五分钟High均匹配，
   可以推断这根孤立的一分钟High差异**未改变**五分钟
   区间最高值；**仍然不能把该分钟误差视作不存在**。
3. 若TDX内部自洽、两来源五分钟High不匹配，
   说明差异也反映在至少一个五分钟区间；应考虑再加
   不导出价量/具体分钟位置的细粒度统计作证据定位。
4. 若两来源日线High或其它字段有差异，也要原样保留，
   不能单凭日线判定错误来源。需要有独立可信来源或上游修订说明
   才可能归属责任。不同粒度比较均是诊断性容差而非认证。

## 适用边界

- 已知先前10组正常历史股票日预演与原始审计cohort交叉核验通过；
  新增这2组单High反例揭示跨来源的差异可局部且稀疏。
- 两组均保持 `eligible_for_automatic_production_union=false`；
  禁止跳过错误分钟、扩大容差、静默修正High、覆盖付费Parquet、
  TDX、H5或生产查询。
- 2026-10-28用户尚未提供PR #92修复后的边界调查9项单元测试结果；
  不把该项列为通过。
