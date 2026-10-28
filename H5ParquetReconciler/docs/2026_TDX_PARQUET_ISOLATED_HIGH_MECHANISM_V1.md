# 2026-10-28：两个真实单分钟High反例的跨周期三角证据与内存机制核验

## 现实证据：TDX和Parquet五分钟一致，不等于一分钟逐根一致

用户从Windows上传既有工具 `audit-tdx-vs-parquet-day5min-readonly.py`
生成的两份跨周期安全报告：

| 证据 | 浦发银行 SH600000 2026-07-16 | 贵州茅台 SH600519 2026-06-30 |
| --- | --- | --- |
| TDX 原生1min→5min→日线内部六字段 | 全部诊断容差内通过 | 全部诊断容差内通过 |
| TDX 5min vs Parquet 5min 六字段 | 48/48全部通过 | 48/48全部通过 |
| TDX日线 vs Parquet日线 OHLC/amount | 全部通过 | 全部通过 |
| TDX日线 vs Parquet日线 volume | 1/1通过，最大相对误差4.366e-07 | **0/1未通过**，最大相对误差1.99456e-05 |
| Parquet 5min汇总 vs Parquet日线 volume | 1/1通过 | **0/1未通过**，最大相对误差2.52474e-05 |
| 既有1min High问题 | 1根High不匹配（238/239） | 1根High不匹配（238/239） |

两只股票各有1根常规分钟High不匹配，但对应全天48根五分钟
High均匹配；**不能因此判断单分钟High没有错误，
也不能用5min数据修正或覆盖1min数据**。

贵州茅台还存在独立的日成交量差异。由于它的Parquet
5min与TDX 5min成交量均通过，且TDX自身1min→5min→
日线诊断也通过，可能是购买Parquet日线成交量的
独立口径、修订或汇总问题，但原因尚未被认证。
日线量额不被此分钟High研究工具擅自改写；后续另设证据分支核验。
Parquet清单仍为stat-only来源指纹，非内容认证。

## 新增内存定位工具（按区间统计，不导出具体分钟位置）

`tools/triage-tdx-parquet-isolated-high-readonly.py`

工具对**一只股票、一个日期**严格只读地重新加载：
- TDX 1min 240条END和5min 48条END，二次读取原生全文件SHA256校验；
- 购买Parquet原生1min 241（09:30单独记录）及5min 48 START，
  使用已有安全有界查询、时间网格与stat-only来源清单二次校验；
- 内存生成241→240候选序列，严格保留开盘OHLCVA聚合，
  不补造、修改或导出任何分钟K线。

除统计六字段不匹配次数外，新工具能直接回答：

1. 是否仅1根High不匹配，其他五字段均相符；
2. 该不匹配的分钟是否是其来源**对应五分钟区间的最大High**
   （分别统计TDX与购买数据，考虑同一区间有并列最高价的情况）；
3. 不匹配分钟分布到多少个五分钟区间、那些区间重新聚合后
   High有多少仍不匹配；
4. TDX1min聚合vsTDX原生5min、购买候选聚合vs购买原生5min、
   TDX原生5min vs购买原生5min的全部六字段对比。

只能输出安全统计、来源哈希、规则ID及判断结果，不输出实际
OHLCVA、成交价格、具体异常分钟位置或本机绝对路径。
结果即使匹配也永不放行生产转换，
`eligible_for_automatic_production_union=false`。

## Windows验收：所有命令为物理单行PowerShell

在 `D:\ChatGPT\AStockDataTools` 仓库根目录运行：

```powershell
git pull --ff-only origin main
```

先执行新增9项纯合成测试（**本轮尚未实机验收**）：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test_triage_tdx_parquet_isolated_high_readonly.py" -v
```

针对浦发银行2026-07-16：

```powershell
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\triage-tdx-parquet-isolated-high-readonly.py --parquet-root "D:\stock" --tdx-1min-file "D:\software\TDX\vipdoc\sh\minline\sh600000.lc1" --tdx-5min-file "D:\software\TDX\vipdoc\sh\fzline\sh600000.lc5" --symbol SH600000 --date 2026-07-16 --read-only --out "reports\tdx-pq-sh600000-20260716-isolated-high-mechanism-v1.json"
```

针对贵州茅台2026-06-30：

```powershell
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\triage-tdx-parquet-isolated-high-readonly.py --parquet-root "D:\stock" --tdx-1min-file "D:\software\TDX\vipdoc\sh\minline\sh600519.lc1" --tdx-5min-file "D:\software\TDX\vipdoc\sh\fzline\sh600519.lc5" --symbol SH600519 --date 2026-06-30 --read-only --out "reports\tdx-pq-sh600519-20260630-isolated-high-mechanism-v1.json"
```

目标文件必须尚不存在；脚本只在
`H5ParquetReconciler/reports` 下独占新建安全JSON。
若失败，请反馈原始错误；不得因重跑而覆盖之前证据。

## 证据判断的边界

- `isolated_minute_high_disagreement_not_visible_at_5min_tolerance`
  只表示“该单分钟High差异没有导致五分钟High超出当前
  诊断容差”，**不是源数据正确性证明**。
- 五分钟High最大值可能由另一根分钟线决定；
  工具将给出源区间控制情况的匿名**聚合计数**，
  不暴露精确异常分钟。
- `other_or_cross_period_disagreement_do_not_materialize`
  表示比单High更复杂的错误/不一致，不应自动转换。
- 贵州茅台的Parquet日线成交量问题已经由先前
  日/5分钟跨来源报告单独支持，与这一分钟High问题分开追踪。
- 所有来源数据、H5、私有缓存、转换后的K线与生产查询
  仍不修改，也不因本轮研究而扩大已有误差容差。
