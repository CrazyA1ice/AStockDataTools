# 五分钟并集预检阶段：来源差集、重叠冲突隔离和禁止自动覆盖

日期：2026-10-25。工具维护目录：`AStockDataTools/H5ParquetReconciler`。

## 一、前序报告支持的结论

来自用户上传的 `5min-session-conservation-2025-09-30.json`，对2025-09-30五只样本股票做了守恒诊断：

| 股票 | 共有五分钟K线 | 成交量全天净差占H5比例 | 逐根毛差占H5比例 | 正负抵消率 | 相邻异号/两者差额均非0 |
|---|---:|---:|---:|---:|---:|
| SH600000 | 48 | 0.001106% | 1.178754% | 99.9061% | 30/46 |
| SZ000636 | 48 | 0.000921% | 1.252004% | 99.9264% | 33/41 |
| SH603181 | 48 | 0.003939% | 0.919133% | 99.5715% | 27/40 |
| SZ300747 | 48 | 0.003737% | 1.219353% | 99.6936% | 28/41 |
| BJ920680 | 0 | 无可比性 | 无可比性 | 无可比性 | 无可比性 |

四只可比证券相邻差额方向相反的计数合计118/168，即70.24%。成交额也有类似的接近零净差、较大逐根毛差和高比例抵消。上午/下午拆分后的抵消比例同样很高。全部四只股票H5/Parquet OHLC内部几何违反数为0。

**支持的谨慎推断**：部分逐根五分钟量额差异可能来自时间窗口成交归属或边界构造差异，而非全天成交量完全不同。但不等于确定是哪一方使用了错误的窗口划分；相邻异号不保证差异必然来自相邻成交转移。H5 1min对该日这些股票没有可用记录，因此不能从H5 1min构造独立真值。

## 二、停止重复抽样，开始只读并集预检

新增脚本 `tools/plan-5min-readonly-union.py`。它直接用本地H5和Parquet读取指定日期、最多20只股票，规范候选五分钟时标（Parquet原始起点+5分钟），按照**唯一证券+五分钟终点时间键**区分：

- `h5_only`：H5存在、Parquet不存在；仅作为**Parquet补录候选**。
- `parquet_only`：Parquet存在、H5不存在；仅作为**H5补录候选**。
- `identical_values`：六个字段数值完全相同；单列，不与容差一致混淆。
- `within_unverified_tolerance`：原始数值不同，但均处在工具**未经认证**的价格、量、金额阈值内。
- `value_conflict`：至少一个字段超出上述阈值；保留发生冲突的字段类别和至多12条证券@时间示例，绝不从H5或Parquet擅自选择正确的一套。

每股给出H5/Parquet唯一键、交集、按类别的并集数量、被隔离冲突数和异常OHLC几何计数；总计遵循 `H5 + PQ - 交集 = 并集键`。分析与报告不写任何原始OHLCV数值。

## 三、为什么现在仍不允许生成真正并集

新报告的 `preflight_passed_for_automatic_union` 恒为 `false`，`output_database_generated` 为 `false`。`quality_barriers` 至少包括：

1. 股票候选代码不是正式上市/退市证券主数据，不足以认证旧代码/北交所证券；
2. 5min Parquet起点+5分钟、量额单位、比较阈值仍属经验性映射；
3. 冲突裁决/来源优先规则未认证；
4. 若发生Parquet重复键、H5重复键、非数值/不合法OHLC、行情文件缺失等，也会额外标记阻断项。

原有少股票Parquet读取过程会记录被跳过的源重复键计数。如果重复键存在，本轮先对分区阻断而非强行生成可补录清单。此工具只生成**候选与障碍报告**，不创建H5/Parquet并集副本。

## 四、本机验收命令

在 `D:\ChatGPT\AStockDataTools` 仓库根目录运行：

```powershell
git status -sb
git pull --ff-only origin main
.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test*.py" -v
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\plan-5min-readonly-union.py "D:\stock" --date 2025-09-30 --symbols SH600000 SZ000636 SH603181 SZ300747 BJ920680 --read-only --out "reports\5min-union-preflight-2025-09-30.json"
```

报告严格在 `H5ParquetReconciler/reports/`，旧报告不覆盖。保留H5及购买的Parquet在 `D:\stock` 只读。

## 五、工程后续路线（避免重复扫描的下一阶段）

这一原型在少量股票和单日上证明分类、重复键阻断、交集守恒与冲突隔离规则，然后开发**分日期/证券外部索引**，避免对购买的按股票跨日期存储的Parquet每核对一天都重新读取约6,408万条年度源行。全历史一致性、历史证券主数据、未认证的时间/单位映射以及安全导出新H5/Parquet都属于后续准入。先保证可复核的键级差集和冲突隔离，才能谈格式互转。

本轮新增8项合成测试，原有44项加上这8项总共52项。新增测试在用户Windows本机运行通过前不得宣称正式验收。
