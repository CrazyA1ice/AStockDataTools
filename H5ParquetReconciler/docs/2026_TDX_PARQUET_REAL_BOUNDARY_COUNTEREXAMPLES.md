# 2026-10-28：首次发现241→240只读候选规则的真实边界反例

## 证据来源及结论

用户本机执行既有 `survey-tdx-parquet-minute-rule-boundaries-readonly.py` 后上传
`tdx-pq-minute-boundary-survey-20260716-20260630-v1.json`（安全汇总；
未输出OHLCVA或具体分钟时间）。

| 股票 | 日期 | status | failed_gates |
| --- | --- | --- | --- |
| SH600000 | 2026-07-16 | mismatch | remaining_239_match_native, candidate_240_matches_native |
| SZ300750 | 2026-07-16 | diagnostic_match | 无 |
| SH600519 | 2026-06-30 | mismatch | remaining_239_match_native, candidate_240_matches_native |
| SZ000001 | 2026-06-30 | diagnostic_match | 无 |

4个股票日：匹配2、明确六字段不匹配2、来源结构不支持0。
整个调查的正式结论是 `anomaly_observed_do_not_apply_mapping`。
`candidate_was_not_materialized=true`、`sources_modified=false`、
`production_mapping_certified=false`、
`eligible_for_automatic_production_union=false` 均保留。

**最重要的观察**：两个反例的首根09:30+09:31聚合门槛未失败；
Parquet候选240→原生Parquet48根五分钟的门槛也未失败；
只有剩余239根与原生TDX1min的比对失败，并使整日240根失败。
所以眼下不能认定“09:30合并规则失效”。实际问题是
*TDX原生1min与购买Parquet原生1min在部分常规分钟存在差异*。
报告没有逐字段的失败数量和最大误差，因此也**不能**由此推断
是OHLC价格、成交量额、复权、源版本、数据供应商或某个具体
交易时间出现错误。尤其不能把某个日期概括为“全市场异常日”：
同一2026-07-16的SZ300750诊断匹配、SH600000不匹配。

这些反例必须阻止对应股票日的候选材料化；不能通过放宽容差、
改原始行情、删除异常分钟或直接按五分钟线倒推来“修好”。

## 下一步——使用已实现的安全逐字段统计定位，而不是重复开发聚合

已有 `tools/preview-tdx-parquet-1min-normalization-readonly.py`
会输出四个比较组各六字段的 `n`、
`within_diagnostic_tolerance`、`max_relative_error`、
`mean_relative_error`，不输出具体价格/量额/分钟标签，
即使发生候选不一致也会生成带有
`diagnostic_candidate_mismatch_do_not_materialize` 的安全报告。

在Windows仓库根目录 `D:\ChatGPT\AStockDataTools` 执行以下
**两条独立的单行PowerShell命令**（仅运行仍有反例的两个股票日）：

```powershell
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\preview-tdx-parquet-1min-normalization-readonly.py --parquet-root "D:\stock" --tdx-1min-file "D:\software\TDX\vipdoc\sh\minline\sh600000.lc1" --symbol SH600000 --date 2026-07-16 --read-only --out "reports\tdx-pq-sh600000-20260716-boundary-detail-v1.json"
```

```powershell
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\preview-tdx-parquet-1min-normalization-readonly.py --parquet-root "D:\stock" --tdx-1min-file "D:\software\TDX\vipdoc\sh\minline\sh600519.lc1" --symbol SH600519 --date 2026-06-30 --read-only --out "reports\tdx-pq-sh600519-20260630-boundary-detail-v1.json"
```

脚本输出仅在 `H5ParquetReconciler/reports` 内独占创建，
不会覆盖已存在文件。如果该报告已生成，请改用新的输出文件名，
不要删除原报告。

重点对比两个安全JSON的以下分组，按字段查看哪个统计
`within_diagnostic_tolerance < n`，以及对应
`max_relative_error`：

- `candidate_vs_native_first_minute`（预计通过，仅以实际结果为准）。
- `candidate_vs_native_remaining_239`（已知有字段失败；需确定哪些字段与失败数）。
- `candidate_vs_native_full_240`（已知失败）。
- `candidate_240_to_purchased_48_five_minute`（预计通过，仍以JSON为准）。

**仅在拿到按字段差异后**，才决定是否需要进一步开发
“按半日/固定时段分组的聚合误差计数”诊断工具；
即使那样也不输出具体分钟时间标签、行情数值或绝对源路径。

## 研究边界和测试状态

- 之前10个股票日的开盘合并、10组真实内存预演、
  10组预演cohort交叉审计均通过，仍然是探索性、非生产认证。
  此次2个反例证明不能默认把未验证的其它股票日纳入映射。
- 新 `test_survey_tdx_parquet_minute_rule_boundaries_readonly.py` 的
  Windows9项合成测试先前存在一个隐私断言的误报，
  PR #92已修复断言；**用户尚未回传修复后9项完整通过的日志**，
  不将该项记为已验收。
- 一切候选240根记录仅存在于临时进程内存，原始购买Parquet、
  TDX、H5、私有暂存和生产并集均不修改。
