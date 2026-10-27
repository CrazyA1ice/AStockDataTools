# 2026-10-27：真实Parquet查询48/48成功；月度文件定位的安全性能改进

## 用户本机真实查询回执

`pq-primary-query-SH600000-5min-2026-09-30.json`（PR#59首版查询）明确显示：
- 请求`SH600000`，购买Parquet 5min，2026-09-30。
- `matching_bar_count=48`，时间起止`2026-09-30 09:30`至`14:55`，`time_label_policy=five_minute_start_label`；与此前同日内部5min完整性证据一致。
- 原版`source_files_examined=9`（扫描了2026年1～9月的9份源月度文件Footer），`candidate_row_groups=47`、`source_rows_scanned=5,685,792`、`candidate_source_rows_upper_bound=5,685,792`。为了返回48条，实际扫描了**118,454个源行/每根返回K线**。这揭示当前查询主要是月文件内RowGroup读放大，不能把“元数据文件数减少”说成“OHLCVA扫描源行已降低”。
- 原报告`source_quantity_unit_rescaling_applied=false`、`no_h5_read=true`、`source_market_files_modified=false`、`no_automatic_gaps_fill=true`、`no_raw_ohlcva_in_safe_summary=true`。**它不包含实际OHLCVA，不能据此重新核验单根行情价格或源行情的交易所真实度**。

## 当前小步性能改进

更新`tools/query-parquet-primary-readonly.py`：
- 仅针对`AllCycleAStockData/<period>/YYYY-MM.parquet`这种根目录一级、年份月份严格合法的月度文件判定**文件名月份是否与查询范围不交叠**；年度文件、嵌套文件、无法解析的文件仍保持候选。
- **必须先打开实际Parquet文件Footer（只读元数据）并检查每一个RowGroup的真实时间戳区间**；只有**所有行组都确定与请求区间不重叠**才从进一步规划跳过月文件。若文件名为一月而某RowGroup却真的含九月数据，仍读取并输出`month_filename_disagrees_with_footer_query_range`，绝不因文件名漏数据。RowGroup`ts`缺统计则`core.row_group_overlaps_timestamp`保守返回可能相交，不跳过。
- 安全摘要新增`source_files_discovered_for_year`、`source_file_footers_opened`、`source_files_skipped_nonoverlapping_named_month`、`month_filename_disagrees_with_footer_query_range`及`source_rows_read_per_returned_bar`。其中扫描读放大按实际`source_rows_scanned/matching_bar_count`计算，若0返回则为null，**数值直观呈现真实性能瓶颈**。
- 对2026-09-30目标股票，预期有9份月文件Footer仍需被打开检验；**按此前已收到的库存盘点**，其中1～8月与目标时间不重叠，可望跳过这8份的深层RowGroup规划，继续关注2026-09同月内47个RowGroup和约569万行**是否仍需读**。这是**元数据规划减负，不保证查询时间显著提升，更不能宣传实际读取源记录减少**。
- 新增4项临时Arrow源文件回归测试，覆盖月文件排除、月文件标签错月份仍命中、跨月窗口和年度/嵌套文件保守回退。现有9项保持，新查询脚本测试预计13项；总代码测试预计**271项**（之前267项+4项），但新测试未在用户Windows运行。
- 默认命令仍只把来源数量和时间等**安全摘要JSON写入模块reports**，不写源Parquet，不访问H5/TDX，不导出购买价量额，也不自动加入数据库。用户本机Python`query_bars`可在内存里返回自己持权的原始OHLCVA。

## Windows更新与回归检验

在用户本地仓库根目录：

```powershell
git pull --ff-only origin main
.\.venv\Scripts\python.exe -m unittest discover -s H5ParquetReconciler\tests -p "test*.py" -v
.\.venv\Scripts\python.exe H5ParquetReconciler\tools\query-parquet-primary-readonly.py "D:\stock" --symbol SH600000 --period 5min --from-date 2026-09-30 --to-date 2026-09-30 --max-candidate-rows 30000000 --read-only --out "reports\pq-primary-query-SH600000-5min-2026-09-30-v2.json"
```

对比**v1**与**v2**两个安全JSON应重点看：
- `matching_bar_count`必须保持48；原时间范围仍09:30～14:55；
- `source_files_discovered_for_year`预计9、`source_file_footers_opened`预计9、`source_files_skipped_nonoverlapping_named_month`预计8、`source_files_examined`预计1；
- `candidate_row_groups`可能仍47，`source_rows_scanned`可能仍5,685,792，`source_rows_read_per_returned_bar`可能仍118,454；**若仍然巨大不是功能失败，而是下一轮真正要优化的行级检索瓶颈**；
- 如果实际输出与预计值不同应先检查真实数据/元数据，不能用预期替换真实结论；若行数比以前减少，应再比较样本OHLCVA和来源时间，确认无遗漏。

## 下一轮：真正降低RowGroup内读取放大

仅靠月文件筛选不足以解决1个证券日读取600万行的问题。下一阶段需要实测Arrow Dataset predicate pushdown是否能真正减少源读取及wall/CPU时间，再考虑构建**仅包含按证券×日期的局部行组索引或小型按需缓存**，优先单股票少量时间段、标注源文件指纹和过期失效条件。任何缓存或目标索引**必须落在H5ParquetReconciler/work/**，保持默认不导出原始OHLCVA，不复制整个50GiB包，不因索引缺失或过期返回静默不完整结果。主查询层验证稳定后才进入通达信盘后可回滚增量层。
