# H5 ↔ Parquet A股数据全量核对

本目录独立于旧的股票仿真仓库，专门开发本地 **Hikyuu H5 与购买的A股Parquet数据对比、补全、并集构建工具**。

**目标顺序：** ① 盘点双方覆盖 → ② 计算按证券/周期/时间的交集及双向差集 → ③ 核查重叠记录的OHLCV/成交额差异 → ④ 核实时间、单位、复权、历史证券代码 → ⑤ 在新目录生成可回滚的H5与Parquet并集库。

当前仅实现①–③的**只读基础版本**。无法直接承诺转换与合并是安全的，详情见 [完整需求文档](docs/REQUIREMENTS.md)、[当前审计规则与已知限制](docs/TECHNICAL_NOTES.md)。

## 文件结构

| 文件 | 用途 |
|---|---|
| tools/reconcile-local-a-share-h5-parquet.py | 全量年度/周期只读核对程序 |
| tests/test_reconcile_local_a_share_h5_parquet.py | 六项生成数据的合成测试，无需购买行情 |
| docs/REQUIREMENTS.md | 需求、验收与优先级（当前开发任务的长期依据） |
| docs/TECHNICAL_NOTES.md | 数据字段、单位假设、报告语义和局限 |
| docs/ROADMAP.md | 后续开发与并集构建步骤 |
| requirements.txt | 依赖 |

## 本地数据目录

程序默认本机的数据根目录为 `D:\stock`，要求至少存在：

```text
D:\stock\
├─ HikyuuData\
│  ├─ sh_day.h5   sz_day.h5   bj_day.h5
│  ├─ sh_5min.h5  sz_5min.h5  bj_5min.h5
│  └─ sh_1min.h5  sz_1min.h5  bj_1min.h5
└─ AllCycleAStockData\
   ├─ day\   (年度*.parquet)
   ├─ 5min\  (年度*.parquet)
   ├─ 1min\  (年度*.parquet)
   ├─ 15min\ 30min\ 60min\ week\ month\
   └─ 复权因子\
```

真实数据永远不上传本仓库。输出报告、SQLite临时库请放到另外的目录，如新仓库下 `h5-private-candidates`。

## Windows PowerShell 快速开始

在 **AStockDataTools 仓库根目录**打开终端（不是 GLSSTKGM），准备虚拟环境：

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r H5ParquetReconciler\requirements.txt -i https://pypi.org/simple

.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test_reconcile_local_a_share_h5_parquet.py" -v
```

**建议先跑日线，检查结果后再跑分钟线**（年度Parquet可能超过1GB，且读取过程有临时磁盘需求）：

**Windows路径注意事项：** `D:\stock` 是源数据目录，报告及SQLite临时文件必须在此目录**之外**。新版本默认把临时文件存放在 `--out` 的同级 `_union_scratch` 目录，不再依赖PowerShell的当前工作目录。如果你将仓库放在 `D:\stock` 之下，下面的相对 `--out` 也会被安全校验拒绝；建议直接使用以下与工作目录无关的绝对路径命令：

```powershell
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\reconcile-local-a-share-h5-parquet.py "D:\stock" --periods day --read-only --scratch "D:\AStockAuditScratch" --out "D:\AStockAuditReports\h5-parquet-day-audit.json"
```

该错误发生在数据读取之前，**不代表H5或Parquet损坏**。路径报错会显示解析后的实际目录，便于查看PowerShell当前位置造成的相对路径差异。


```powershell
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\reconcile-local-a-share-h5-parquet.py "D:\stock" --periods day --read-only --out "h5-private-candidates\h5-parquet-day-audit.json"
```

再执行完整的三个H5已有周期（2011—2026年，按周期/年串行执行）：

```powershell
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\reconcile-local-a-share-h5-parquet.py "D:\stock" --periods day 5min 1min --read-only --out "h5-private-candidates\h5-parquet-union-audit.json"
```

中断后：使用**原命令、原参数、原输出文件名**，仅追加 `--resume`；已成功完成的年度/周期将跳过。也可独立执行 `--years 2025 2026 --periods day 5min`，通过较小的目标检查性能和脚本兼容性，但结果仅覆盖明确指定的范围。

## 输出

程序在输出目录产生：

- `h5-parquet-union-audit.json`：所有年份/周期的来源行数、交集、差集、量价不一致、时间首末、按日统计及少量股票@时间示例。
- `h5-parquet-union-audit.md`：中文汇总报告。

核心计数：`h5_only_rows`、`pq_only_rows`、`matched_keys`、`value_mismatch_rows`、`opening_candidate_mismatch_rows`、`pq_0930_extra_candidate_rows`。当某周期该年H5全无数据时，Parquet仅做footer候选统计，字段 `pq_year_metadata_only_no_h5_rows=true`，**不能视为精确Parquet独有键清单**。

### 关键限制（请先了解）

1. 当前只覆盖H5存在的 `day / 5min / 1min` 三个周期；并不报告15/30/60分钟、周/月、复权因子的H5/Parquet差集。
2. 成交额和成交量、5分钟起点/终点、09:30额外一分钟等采用**候选规则**；H5出现的13:00疑似午间误标需要另审。重叠不同并不自动意味着其中一方坏了。
3. H5某年份某周期完全没数据时，为节约读取成本，Parquet只统计年度文件footer信息；明细覆盖没有验证。
4. 数据扫描错误、重复键及未知证券格式必须检查`issues`与完整性标记。当前版本**没有完全处理跨Parquet批次的重复键**，不能据此直接自动构建并集。
5. 本程序从不写原始H5或Parquet，也不产生合并数据库；后续合并将在源数据目录以外生成新库，必须先获冲突策略验收。

## 既有研究背景

此前在本地抽查发现H5部分2026-07-16日线与分钟累计成交额异常、Parquet时间/单位与H5口径存在差异；同时H5早期分钟数据未手工下载。历史样本验证已证明**不能用有日线推断有分钟线**，因此本项目按每个周期独立核验，先验证重叠，再找差集。具体核验事实与新数据报告以后保存在本目录的 `docs` 内。
