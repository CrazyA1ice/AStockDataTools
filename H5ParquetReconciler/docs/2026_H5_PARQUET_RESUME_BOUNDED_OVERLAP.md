# 2026-10-28：完成TDX与Parquet异常证据验收，恢复H5↔Parquet覆盖主线

## 已收到的真实验收（不要与生产认证混淆）

用户Windows终端上传的最新字段级判定测试输出包含11项，每项均显示`... ok`，
执行用时0.620秒；截取的末尾没有完整`OK`行及明确退出码，
可表述为11个单项全部显示成功，但不要额外推断其它测试。

用户随后上传两份`field-disposition-v1.json`，由已实现的
`tools/evaluate-tdx-parquet-case-evidence-readonly.py`生成，
其各自三个既有SAFE上游报告的来源证据交叉核验均为true：

| 股票日 | 一分钟异常 | 五分钟 | TDX日线vsPQ日线Volume | PQ五分钟汇总vsPQ日线Volume | 生产合并 |
| --- | --- | --- | --- | --- | --- |
| SH600000 / 2026-07-16 | 仅High 1根 | 六字段均通过 | diagnostic_match | diagnostic_match | 关闭 |
| SH600519 / 2026-06-30 | 仅High 1根 | 六字段均通过 | mismatch | mismatch | 关闭 |

两个异常一分钟High均非其来源五分钟区间的极大值；
不能将高周期匹配当作分钟逐根匹配，也不能据此改写异常分钟。
两个报告的`source_evidence_crosschecked=true`不等于购买Parquet内容
已获得第三方加密认证；stat-only来源清单、未认证的安全报告来源
均是当前诊断的保留条件。两例的
`eligible_for_automatic_production_union=false`、
`candidate_materialized=false`、`original_sources_modified=false`。

## 主线恢复：先做一个实际的单日H5与购买Parquet重叠核对

**不要再为两根High继续创建同类分析程序。** 该项目主要目标是
判定两套源在`day/5min/1min`中哪些证券、日期、记录
相交/仅在H5/仅在Parquet，以及相交记录哪些字段不同。

仓库已存在主核对入口
`tools/reconcile-local-a-share-h5-parquet.py`，
支持`--years`、`--periods`、`--from-date`、`--to-date`、
`--universe a-share-candidate`、`--read-only`、`--resume`，
并会用有界临时SQLite输出`h5_rows`、`pq_rows`、
`matched_keys`、`h5_only_rows`、`pq_only_rows`、
`value_mismatch_rows`与逐日`by_day`、5min股票日缺失分解等
实际报告。重叠价量比较是诊断性数值/单位假说，不是
源优先级认证或可写合并。

### Windows：先仅运行2026-09-30的day和5min（单行PowerShell）

在`D:\ChatGPT\AStockDataTools`仓库根目录，先更新：

```powershell
git pull --ff-only origin main
```

然后执行**一条**完整命令：

```powershell
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\reconcile-local-a-share-h5-parquet.py "D:\stock" --years 2026 --periods day 5min --from-date 2026-09-30 --to-date 2026-09-30 --universe a-share-candidate --read-only --out "reports\h5-pq-overlap-20260930-day5min-v1.json" --scratch "work\h5-pq-overlap-20260930-day5min-v1"
```

这是**单日窗口，但可能仍读取较大年度文件**；
不要添加`--allow-full-year-minute`。倘若运行慢、目录缺失或
源扫描失败，应记录实际状态并停止，不能改动源行情。
输出JSON与Markdown留在`H5ParquetReconciler/reports/`，
SQLite临时数据只在`H5ParquetReconciler/work/`，
不应在仓库根目录或`D:\stock`留下任务输出。

若任务中断、且报告已存在但未完整完成，可使用**与上面
完全相同的命令参数及报告路径**并加`--resume`继续；
不要改变日期窗口、证券集或周期后复用旧报告。

### 分析返回的真实JSON

首先核对：

- `status`与`results['day/2026']`、`results['5min/2026']`的`scan_complete`；
- `h5_rows`、`pq_rows`、`matched_keys`、
  `h5_only_rows`、`pq_only_rows`及`value_mismatch_rows`；
- 对5min的`stock_day_gap_summary`区分整股票日缺失与局部缺键；
- `by_day`中的日期范围必须属于2026-09-30；
- `security_master_certified=false`、`eligible_for_automatic_union=false`。

确认一次窗口的实际结果后，再研究是否有必要限定证券
以及怎样复用年文件行组定位以降低成本；不先提出
无证据的速度或覆盖优势。1min有09:30特殊标签语义，
下一轮**单独**执行同一天的1min核对，而不是先混入
day/5min诊断或直接把09:30当作无效的Parquet-only记录。

本阶段**不生成统一行情、不写原始H5/Parquet、不自动
挑选来源或补足缺失K线**。主要目的是产生真实覆盖证据，
进一步决定双向差集核对和后续可追溯并集策略。
